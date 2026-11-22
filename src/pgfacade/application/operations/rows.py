"""rows.* and sql.* handlers."""

from __future__ import annotations

import re
from contextlib import AbstractAsyncContextManager

from pgfacade.application.errors import InvalidRequest
from pgfacade.application.registry import RAW, WRITE, Perm, op
from pgfacade.contracts.base import Count, Filtered, Flag, QueryResult, Row, Text
from pgfacade.contracts.enums import OperationHint
from pgfacade.contracts.rows import (
    Plan,
    RowsAggregate,
    RowsCount,
    RowsDelete,
    RowsExists,
    RowsExportCsv,
    RowsGet,
    RowsImportCsv,
    RowsInsert,
    RowsSelect,
    RowsSelectInput,
    RowsUpdate,
    SqlExecute,
    SqlExplain,
    SqlQuery,
)
from pgfacade.contracts.types import RowCount, SqlBody, SqlStatement
from pgfacade.infrastructure.postgres.engine import Conn, Core
from pgfacade.infrastructure.postgres.queries import rows as queries
from pgfacade.infrastructure.postgres.queries.composition import (
    TableMeta,
    collect,
    key_match,
)


async def _count(db: Core, conn: Conn, meta: TableMeta, req: Filtered) -> RowCount:
    query = queries.count(meta, req)
    row = await (await conn.execute(query.statement, query.parameters)).fetchone()
    return Count.model_validate(row).count


# ---------------------------------------------------------------- read


@op(RowsSelect, response=QueryResult)
async def select(db: Core, req: RowsSelect) -> QueryResult:
    limit = min(req.input.limit or db.settings.max_rows, db.settings.max_rows)
    async with db.tx() as conn:
        meta = await db.table(conn, req.input.table)
        query = queries.select(meta, req.input, limit + 1, req.input.offset)
        result = await db.fetch(conn, query.statement, query.parameters, limit)
        if req.input.with_total:
            result = result.model_copy(update={"total": await _count(db, conn, meta, req.input)})
    return result


@op(RowsGet, response=Row)
async def get(db: Core, req: RowsGet) -> Row:
    async with db.tx() as conn:
        meta = await db.table(conn, req.input.table)
        probe = RowsSelectInput(table=req.input.table, match=key_match(meta, req.input.key), columns=req.input.columns)
        query = queries.select(meta, probe, 1)
        result = await db.fetch(conn, query.statement, query.parameters)
    return Row(row=result.rows[0] if result.rows else None)


@op(RowsCount, response=Count)
async def count(db: Core, req: RowsCount) -> Count:
    async with db.tx() as conn:
        return Count(count=await _count(db, conn, await db.table(conn, req.input.table), req.input))


@op(RowsExists, response=Flag)
async def exists(db: Core, req: RowsExists) -> Flag:
    async with db.tx() as conn:
        meta = await db.table(conn, req.input.table)
        query = queries.exists(meta, req.input)
        row = await (await conn.execute(query.statement, query.parameters)).fetchone()
    return Flag.model_validate(row)


@op(RowsAggregate, response=QueryResult)
async def aggregate(db: Core, req: RowsAggregate) -> QueryResult:
    limit = min(req.input.limit or db.settings.max_rows, db.settings.max_rows)
    async with db.tx() as conn:
        meta = await db.table(conn, req.input.table)
        query = queries.aggregate(meta, req.input, limit)
        return await db.fetch(conn, query.statement, query.parameters, limit)


# ---------------------------------------------------------------- write


@op(RowsInsert, response=QueryResult, perm=WRITE, hint=OperationHint.DESTRUCTIVE)
async def insert(db: Core, req: RowsInsert) -> QueryResult:
    limit = db.settings.max_rows
    async with db.tx() as conn:
        meta = await db.table(conn, req.input.table)
        statements = queries.insert(meta, req.input)
        results = [await db.fetch(conn, query.statement, query.parameters, limit) for query in statements]
    if len(results) == 1:
        return results[0]
    rows = [r for res in results for r in res.rows]
    return QueryResult(
        columns=results[0].columns,
        rows=rows[:limit],
        rowcount=sum(r.rowcount for r in results),
        truncated=len(rows) > limit or any(r.truncated for r in results),
        status=results[-1].status,
    )


@op(RowsUpdate, response=QueryResult, perm=WRITE, hint=OperationHint.DESTRUCTIVE)
async def update(db: Core, req: RowsUpdate) -> QueryResult:
    if not req.input.has_filters and not req.input.allow_all:
        raise InvalidRequest("refusing UPDATE without filters; set allow_all=true to update every row")
    async with db.tx() as conn:
        meta = await db.table(conn, req.input.table)
        query = queries.update(meta, req.input)
        return await db.fetch(conn, query.statement, query.parameters, db.settings.max_rows)


@op(RowsDelete, response=QueryResult, perm=WRITE, hint=OperationHint.DESTRUCTIVE)
async def delete(db: Core, req: RowsDelete) -> QueryResult:
    if not req.input.has_filters and not req.input.allow_all:
        raise InvalidRequest("refusing DELETE without filters; set allow_all=true (or use table.truncate)")
    async with db.tx() as conn:
        meta = await db.table(conn, req.input.table)
        query = queries.delete(meta, req.input)
        return await db.fetch(conn, query.statement, query.parameters, db.settings.max_rows)


# ---------------------------------------------------------------- COPY


@op(RowsExportCsv, response=Text)
async def export_csv(db: Core, req: RowsExportCsv) -> Text:
    limit = min(req.input.limit or db.settings.max_export_rows, db.settings.max_export_rows)
    chunks: list[bytes] = []
    async with db.tx() as conn:
        meta = await db.table(conn, req.input.table)
        query = queries.export_csv(meta, req.input, limit)
        async with conn.cursor().copy(query.statement, query.parameters) as cp:
            async for chunk in cp:
                chunks.append(bytes(chunk))
    return Text(text=b"".join(chunks).decode())


@op(RowsImportCsv, response=QueryResult, perm=WRITE)
async def import_csv(db: Core, req: RowsImportCsv) -> QueryResult:
    async with db.tx() as conn:
        meta = await db.table(conn, req.input.table)
        query = queries.import_csv(meta, req.input)
        cur = conn.cursor()
        async with cur.copy(query) as cp:
            await cp.write(req.input.data)
        return QueryResult(rowcount=max(cur.rowcount, 0), status=cur.statusmessage)


# ---------------------------------------------------------------- raw SQL

_NO_TX = re.compile(
    r"^\s*(VACUUM|CREATE\s+(UNIQUE\s+)?INDEX\s+CONCURRENTLY|DROP\s+INDEX\s+CONCURRENTLY"
    r"|REINDEX\b.*\bCONCURRENTLY|CREATE\s+DATABASE|DROP\s+DATABASE|ALTER\s+SYSTEM)\b",
    re.IGNORECASE | re.DOTALL,
)
_TX_CONTROL = re.compile(r"^\s*(BEGIN|START|COMMIT|END|ROLLBACK|ABORT|SAVEPOINT|RELEASE|PREPARE\s+TRANSACTION)\b", re.IGNORECASE)
# Tripwire for the obvious ways to leave the SET LOCAL ROLE sandbox. Not a security boundary.
_ROLE_ESCAPE = re.compile(
    r"(\bSET\s+(LOCAL\s+|SESSION\s+)?(ROLE|SESSION\s+AUTHORIZATION)\b|\bRESET\s+(ROLE|ALL|SESSION\s+AUTHORIZATION)\b"
    r"|set_config\s*\(\s*'(role|session_authorization)')",
    re.IGNORECASE,
)
_COMMENTS = re.compile(r"/\*.*?\*/|--[^\n]*", re.DOTALL)


def _check_sql(db: Core, statement: SqlStatement) -> SqlBody:
    bare = _COMMENTS.sub(" ", statement)
    if _TX_CONTROL.match(bare):
        raise InvalidRequest("transaction control is managed for you; use batch or transaction()")
    if db.principal.role is not None and _ROLE_ESCAPE.search(bare):
        raise InvalidRequest("changing the session role is not allowed")
    return bare


@op(SqlQuery, response=QueryResult, perm=RAW)
async def query(db: Core, req: SqlQuery) -> QueryResult:
    _check_sql(db, req.input.sql)
    prepared = queries.raw(req.input)
    async with db.tx(read_only=True, rollback=True) as conn:
        return await db.stream(conn, prepared.statement, prepared.parameters, db.settings.max_rows)


@op(SqlExecute, response=QueryResult, perm=Perm(write=True, raw=True), hint=OperationHint.DESTRUCTIVE)
async def execute(db: Core, req: SqlExecute) -> QueryResult:
    bare = _check_sql(db, req.input.sql)
    ctx: AbstractAsyncContextManager[Conn] = db.no_tx("this statement") if _NO_TX.match(bare) else db.tx()
    async with ctx as conn:
        cur = conn.cursor()
        prepared = queries.raw(req.input)
        await cur.execute(prepared.statement, prepared.parameters, prepare=True)
        result = await collect(cur, db.settings.max_rows)
    db.invalidate()
    return result


@op(SqlExplain, response=Plan, perm=RAW)
async def explain(db: Core, req: SqlExplain) -> Plan:
    _check_sql(db, req.input.sql)
    prepared = queries.explain(req.input)
    async with db.tx(read_only=True, rollback=True) as conn:
        cur = conn.cursor()
        await cur.execute(prepared.statement, prepared.parameters, prepare=True)
        row = await cur.fetchone()
    return Plan(plan=row["QUERY PLAN"] if row else None)
