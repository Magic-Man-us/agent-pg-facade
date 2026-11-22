"""server.* diag.* maint.* handlers."""

from __future__ import annotations

import time

from pgfacade.application.errors import NotFound
from pgfacade.application.registry import ADMIN, ADMIN_WRITE, DDL, LISTEN, MIGRATE, RAW, op
from pgfacade.contracts.admin import (
    DiagActivity,
    DiagLocks,
    DiagTableStats,
    DiagTopQueries,
    DiagUnusedIndexes,
    Health,
    MaintAnalyze,
    MaintBackend,
    MaintReindex,
    MaintVacuum,
    ServerHealth,
    ServerInfo,
    ServerInfoGet,
    ServerSettings,
    ServerWhoAmI,
    SettingInfo,
    SettingInfoList,
    WhoAmI,
)
from pgfacade.contracts.base import Done, Flag, QueryResult
from pgfacade.contracts.enums import MaintenanceKind, OperationHint
from pgfacade.infrastructure.postgres.engine import Core
from pgfacade.infrastructure.postgres.queries import Statement
from pgfacade.infrastructure.postgres.queries import admin as queries

# ---------------------------------------------------------------- server


@op(ServerHealth, response=Health)
async def health(db: Core, req: ServerHealth) -> Health:
    start = time.perf_counter()
    async with db.lease() as conn:
        await conn.execute(Statement.ADMIN_PING.text)
    return Health(ok=True, latency_ms=round((time.perf_counter() - start) * 1000, 2), pool=db.pool.get_stats())


@op(ServerInfoGet, response=ServerInfo)
async def info(db: Core, req: ServerInfoGet) -> ServerInfo:
    async with db.tx() as conn:
        row = await (await conn.execute(Statement.ADMIN_SERVER.text)).fetchone()
    return ServerInfo.model_validate(row)


@op(ServerWhoAmI, response=WhoAmI)
async def whoami(db: Core, req: ServerWhoAmI) -> WhoAmI:
    p = db.principal
    return WhoAmI(
        principal=p.name,
        role=p.role,
        read_only=db.settings.read_only or p.read_only,
        sql=db.allows(RAW),
        ddl=db.allows(DDL) if not (db.settings.read_only or p.read_only) else False,
        admin=db.allows(ADMIN),
        migrate=db.allows(MIGRATE),
        listen=db.allows(LISTEN),
    )


@op(ServerSettings, response=SettingInfoList, perm=ADMIN)
async def settings(db: Core, req: ServerSettings) -> SettingInfoList:
    result = await db.read(Statement.ADMIN_SETTINGS.text, [req.input.pattern, min(req.input.limit, db.settings.max_rows)])
    return SettingInfoList(items=[SettingInfo.model_validate(r) for r in result.rows])


# ---------------------------------------------------------------- diagnostics


@op(DiagActivity, response=QueryResult, perm=ADMIN)
async def activity(db: Core, req: DiagActivity) -> QueryResult:
    return await db.read(Statement.ADMIN_ACTIVITY.text, [req.input.include_idle])


@op(DiagLocks, response=QueryResult, perm=ADMIN)
async def locks(db: Core, req: DiagLocks) -> QueryResult:
    return await db.read(Statement.ADMIN_LOCKS.text)


@op(DiagTopQueries, response=QueryResult, perm=ADMIN)
async def top_queries(db: Core, req: DiagTopQueries) -> QueryResult:
    async with db.tx() as conn:
        found = await (await conn.execute(Statement.ADMIN_STATEMENTS_EXTENSION_EXISTS.text)).fetchone()
    if found is None:
        raise NotFound("pg_stat_statements extension is not installed")
    return await db.read(Statement.ADMIN_TOP_QUERIES.text, [min(req.input.limit, db.settings.max_rows)])


@op(DiagTableStats, response=QueryResult, perm=ADMIN)
async def table_stats(db: Core, req: DiagTableStats) -> QueryResult:
    return await db.read(
        Statement.ADMIN_TABLE_STATS.text, [req.input.schema_name, req.input.schema_name, min(req.input.limit, db.settings.max_rows)]
    )


@op(DiagUnusedIndexes, response=QueryResult, perm=ADMIN)
async def unused_indexes(db: Core, req: DiagUnusedIndexes) -> QueryResult:
    return await db.read(Statement.ADMIN_UNUSED_INDEXES.text, [min(req.input.limit, db.settings.max_rows)])


# ---------------------------------------------------------------- maintenance


@op(MaintBackend, response=Flag, perm=ADMIN, hint=OperationHint.DESTRUCTIVE)
async def backend(db: Core, req: MaintBackend) -> Flag:
    async with db.tx() as conn:
        row = await (await conn.execute(queries.backend(req.input), [req.input.pid])).fetchone()
    return Flag.model_validate(row)


@op(MaintVacuum, response=Done, perm=ADMIN_WRITE)
async def vacuum(db: Core, req: MaintVacuum) -> Done:
    async with db.no_tx("VACUUM") as conn:
        meta = await db.table(conn, req.input.table) if req.input.table else None
        cur = await conn.execute(queries.vacuum(req.input, meta))
        return Done(status=cur.statusmessage)


@op(MaintAnalyze, response=Done, perm=ADMIN_WRITE)
async def analyze(db: Core, req: MaintAnalyze) -> Done:
    async with db.tx() as conn:
        meta = await db.table(conn, req.input.table) if req.input.table else None
        cur = await conn.execute(queries.analyze(meta))
        return Done(status=cur.statusmessage)


@op(MaintReindex, response=Done, perm=ADMIN_WRITE)
async def reindex(db: Core, req: MaintReindex) -> Done:
    query = queries.reindex(db, req.input)
    if req.input.concurrently or req.input.kind == MaintenanceKind.SCHEMA:
        async with db.no_tx("REINDEX") as conn:
            return Done(status=(await conn.execute(query)).statusmessage)
    async with db.tx() as conn:
        return Done(status=(await conn.execute(query)).statusmessage)
