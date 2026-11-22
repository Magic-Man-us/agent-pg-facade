"""Connection pool, transactions, role binding, permission checks, table metadata, background sweeper."""

from __future__ import annotations

import asyncio
import copy
import logging
import time
from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import AbstractAsyncContextManager, aclosing, asynccontextmanager
from typing import Self, cast

import psycopg
from psycopg import AsyncConnection, generators, pq, sql
from psycopg.errors import error_from_result
from psycopg.rows import DictRow, dict_row
from psycopg_pool import AsyncConnectionPool

from pgfacade.application.errors import Forbidden, InvalidRequest, NotFound
from pgfacade.application.registry import Perm
from pgfacade.configuration.settings import ANONYMOUS, PgSettings, Principal
from pgfacade.contracts.base import Done, QueryResult
from pgfacade.contracts.types import DatabaseRow, Name, ResultLabel, ResultText, RowLimit, SqlStatement, TableName
from pgfacade.infrastructure.postgres.models import TableMetadataRequest, TableMetadataResponse
from pgfacade.infrastructure.postgres.queries import Statement
from pgfacade.infrastructure.postgres.queries.composition import TableMeta, collect, text
from pgfacade.infrastructure.postgres.types import DatabaseParameters, DatabaseValue, MonotonicSeconds
from pgfacade.shared.types import SecurityFlag

# PostgreSQL determines arbitrary query column names and Python value types at runtime.
type Conn = AsyncConnection[DictRow]

log = logging.getLogger("pgfacade")


class Core:
    """Connection and permission plumbing shared by all handlers. MyApp adds dispatch on top."""

    def __init__(self, settings: PgSettings | None = None) -> None:
        self.settings = settings or PgSettings()
        self._pool: AsyncConnectionPool[Conn] | None = None
        self._conn: Conn | None = None
        self._transaction_task: asyncio.Task[object] | None = None
        self._principal: Principal = ANONYMOUS
        self._meta: dict[tuple[Name, Name], tuple[MonotonicSeconds, TableMeta]] = {}

    # ------------------------------------------------------------ lifecycle

    async def open(self) -> None:
        self._check_transaction_owner()
        if self._pool is not None:
            return
        s = self.settings
        options = f"-c statement_timeout={s.statement_timeout_ms} -c lock_timeout={s.lock_timeout_ms}"
        if s.read_only:
            options += " -c default_transaction_read_only=on"
        pool = AsyncConnectionPool(
            s.dsn.get_secret_value(),
            connection_class=AsyncConnection[DictRow],
            min_size=s.pool_min,
            max_size=s.pool_max,
            timeout=s.pool_timeout_s,
            kwargs={"autocommit": True, "row_factory": dict_row, "application_name": s.application_name, "options": options},
            check=AsyncConnectionPool.check_connection,
            name=s.application_name,
            open=False,
        )
        await pool.open(wait=True, timeout=s.pool_timeout_s)
        self._pool = pool

    async def close(self) -> None:
        if self._transaction_task is not None:
            return  # A transaction-bound view never owns the pool.
        if self._pool is not None:
            await self._pool.close()
            self._pool = None

    async def __aenter__(self) -> Self:
        await self.open()
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.close()

    @property
    def pool(self) -> AsyncConnectionPool[Conn]:
        self._check_transaction_owner()
        if self._pool is None:
            raise RuntimeError("MyApp is not open; call 'await db.open()' or use 'async with MyApp() as db'")
        return self._pool

    @property
    def principal(self) -> Principal:
        return self._principal

    @property
    def in_transaction(self) -> bool:
        return self._conn is not None

    def invalidate(self) -> None:
        """Drop cached column/PK metadata (done automatically after DDL and raw execute)."""
        self._meta.clear()

    # ------------------------------------------------------------ binding: principal, transaction

    def as_(self, principal: Principal) -> Self:
        """View of this facade that runs every call as the principal's role with its permissions."""
        if self._conn is not None:
            raise InvalidRequest("cannot change principal inside a transaction")
        bound = copy.copy(self)
        bound._principal = principal
        return bound

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[Self]:
        """Yield a view bound to one connection; everything inside commits or rolls back together."""
        if self._principal.identity is not None and self._principal.execution_identity is None:
            raise InvalidRequest("Group principals must use batch.run to select a transaction identity")
        async with self.tx() as conn:
            bound = copy.copy(self)
            bound._conn = conn
            bound._transaction_task = asyncio.current_task()
            try:
                yield bound
            finally:
                bound._conn = None

    def _check_transaction_owner(self) -> None:
        if self._transaction_task is None:
            return
        if self._conn is None:
            raise InvalidRequest("The transaction-bound facade is no longer active")
        if self._transaction_task is not asyncio.current_task():
            raise InvalidRequest("A transaction-bound facade belongs to the task that opened it")

    @asynccontextmanager
    async def lease(self) -> AsyncIterator[Conn]:
        self._check_transaction_owner()
        if self._conn is not None:
            yield self._conn
            return
        async with self.pool.connection() as conn:
            yield conn

    def _session_setup(self, read_only: SecurityFlag) -> sql.Composed | None:
        parts: list[sql.Composable] = []
        if (read_only or self._principal.read_only) and not self.settings.read_only:
            parts.append(Statement.ENGINE_TRANSACTION_READ_ONLY.sql)
        if self._principal.role is not None:
            parts.append(Statement.ENGINE_SET_LOCAL_ROLE.sql.format(sql.Identifier(self._principal.role)))
        return sql.SQL("; ").join(parts) if parts else None

    @asynccontextmanager
    async def tx(self, *, read_only: SecurityFlag = False, rollback: bool = False) -> AsyncIterator[Conn]:
        """One transaction (a savepoint when already bound). Role and read-only mode apply at the top level."""
        async with self.lease() as conn, conn.transaction() as t:
            if self._conn is None:
                setup = self._session_setup(read_only)
                if setup is not None:
                    await conn.execute(setup)
            elif read_only:
                # Bound to an outer read-write transaction: SET LOCAL inside the savepoint makes this part read-only
                # and is reverted when the savepoint rolls back, so the outer transaction stays writable afterwards.
                await conn.execute(Statement.ENGINE_LOCAL_READ_ONLY.text)
            yield conn
            if rollback:
                raise psycopg.Rollback(t)

    @asynccontextmanager
    async def no_tx(self, what: ResultText) -> AsyncIterator[Conn]:
        """Autocommit connection for statements that refuse to run in a transaction block."""
        self._check_transaction_owner()
        if self._conn is not None:
            raise InvalidRequest(f"{what} cannot run inside a transaction")
        async with self.pool.connection() as conn:
            role = self._principal.role
            if role is not None:
                await conn.execute(Statement.ENGINE_SET_ROLE.sql.format(sql.Identifier(role)))
            try:
                yield conn
            finally:
                if role is not None:
                    await conn.execute(Statement.ENGINE_RESET_ROLE.text)

    @asynccontextmanager
    async def dedicated(self) -> AsyncIterator[Conn]:
        """A connection outside the pool (LISTEN). Role applied with SET ROLE for the connection's life."""
        self._check_transaction_owner()
        conn: Conn = await AsyncConnection.connect(
            self.settings.dsn.get_secret_value(),
            autocommit=True,
            row_factory=dict_row,
            application_name=f"{self.settings.application_name}-listen",
        )
        try:
            if self._principal.role is not None:
                await conn.execute(Statement.ENGINE_SET_ROLE.sql.format(sql.Identifier(self._principal.role)))
            yield conn
        finally:
            await conn.close()

    # ------------------------------------------------------------ permissions

    def require(self, perm: Perm) -> None:
        self._check_transaction_owner()
        s, p = self.settings, self._principal
        if perm.write and s.read_only:
            raise Forbidden("server is read-only (PGFACADE_READ_ONLY=true)")
        if perm.write and p.read_only:
            raise Forbidden(f"principal {p.name!r} is read-only")
        if perm.raw and not s.allow_raw_sql:
            raise Forbidden("raw SQL is disabled (PGFACADE_ALLOW_RAW_SQL=false)")
        if perm.raw and not p.sql:
            raise Forbidden(f"principal {p.name!r} may not run raw SQL")
        if perm.ddl and not s.allow_ddl:
            raise Forbidden("DDL is disabled (PGFACADE_ALLOW_DDL=false)")
        if perm.ddl and not p.ddl:
            raise Forbidden(f"principal {p.name!r} may not run DDL")
        if perm.admin and not s.allow_admin:
            raise Forbidden("admin operations are disabled (set PGFACADE_ALLOW_ADMIN=true)")
        if perm.admin and not p.admin:
            raise Forbidden(f"principal {p.name!r} may not run admin operations")
        if perm.migrate and not s.allow_migrate:
            raise Forbidden("migrations are disabled (PGFACADE_ALLOW_MIGRATE=false)")
        if perm.migrate and not p.migrate:
            raise Forbidden(f"principal {p.name!r} may not run migrations")
        if perm.listen and not s.allow_listen:
            raise Forbidden("LISTEN is disabled (PGFACADE_ALLOW_LISTEN=false)")
        if perm.listen and not p.listen:
            raise Forbidden(f"principal {p.name!r} may not listen for notifications")

    def allows(self, perm: Perm) -> SecurityFlag:
        try:
            self.require(perm)
        except Forbidden:
            return False
        return True

    # ------------------------------------------------------------ names and metadata

    def split(self, name: TableName) -> tuple[Name, Name]:
        schema, dot, rest = name.partition(".")
        return (schema, rest) if dot else (self.settings.default_schema, schema)

    def qualified(self, name: TableName) -> sql.Identifier:
        return sql.Identifier(*self.split(name))

    async def table(self, conn: Conn, table: TableName) -> TableMeta:
        key = self.split(table)
        now = time.monotonic()
        cached = self._meta.get(key)
        if cached is not None and now - cached[0] < self.settings.schema_cache_ttl_s:
            return cached[1]
        request = TableMetadataRequest(schema_name=key[0], table_name=key[1])
        relation = sql.Identifier(request.schema_name, request.table_name).as_string(conn)
        cur = await conn.execute(Statement.ENGINE_META.text, [relation])
        response = TableMetadataResponse.model_validate({"columns": await cur.fetchall()})
        if not response.columns:
            raise NotFound(f"relation {key[0]}.{key[1]} does not exist")
        records = response.columns
        columns = {column.name: column for column in records}
        primary = sorted((column for column in records if column.pk_pos is not None), key=lambda column: column.pk_pos or 0)
        meta = TableMeta(
            schema_name=key[0], name=key[1], kind=records[0].relkind, columns=columns, primary_key=tuple(column.name for column in primary)
        )
        self._meta[key] = (now, meta)
        return meta

    # ------------------------------------------------------------ shared helpers

    async def fetch(self, conn: Conn, query: sql.Composable, params: DatabaseParameters, limit: RowLimit | None = None) -> QueryResult:
        async with conn.cursor() as cursor:
            await cursor.execute(sql.Composed([query]), params)
            return await collect(cursor, limit)

    async def stream(self, conn: Conn, query: sql.Composable, params: DatabaseParameters, limit: RowLimit) -> QueryResult:
        rows: list[DatabaseRow] = []
        truncated = False
        async with conn.cursor() as cursor:
            # The driver returns an async generator but annotates its public API as AsyncIterator.
            records = cast(AsyncGenerator[DictRow, None], cursor.stream(sql.Composed([query]), params))
            async with aclosing(records):
                async for row in records:
                    if len(rows) == limit:
                        truncated = True
                        break
                    rows.append(row)
            if cursor.description is not None:
                columns = [column.name for column in cursor.description]
            else:
                columns = await self._empty_stream_columns(conn)
        return QueryResult(columns=columns, rows=rows, rowcount=len(rows), truncated=truncated)

    @staticmethod
    async def _empty_stream_columns(conn: Conn) -> list[ResultLabel]:
        # Psycopg drops the empty stream's description; describe its existing portal without replaying the statement.
        async with conn.lock:
            conn.pgconn.send_describe_portal(b"")
            results = await conn.wait(generators.execute(conn.pgconn))
        columns: list[ResultLabel] = []
        for result in results:
            if result.status == pq.ExecStatus.FATAL_ERROR:
                raise error_from_result(result, conn.info.encoding)
            for index in range(result.nfields):
                name = result.fname(index)
                assert name is not None
                columns.append(name.decode(conn.info.encoding))
        return columns

    async def read(self, query: SqlStatement, params: DatabaseParameters = None, limit: RowLimit | None = None) -> QueryResult:
        """Run an internal, trusted read statement."""
        async with self.tx() as conn:
            return await self.fetch(conn, text(query), params, limit or self.settings.max_rows)

    async def ddl(self, query: sql.Composable, *, no_tx: bool = False, **detail: DatabaseValue) -> Done:
        """Run an internal DDL statement and drop the metadata cache."""
        ctx: AbstractAsyncContextManager[Conn] = self.no_tx("this statement") if no_tx else self.tx()
        async with ctx as conn:
            cur = await conn.execute(sql.Composed([query]))
            status = cur.statusmessage
        self.invalidate()
        return Done(status=status, detail=detail)
