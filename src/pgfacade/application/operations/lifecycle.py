"""lifecycle.* handlers: TTL/expiry policies stored in the database and applied by a SQL function.

The function runs with the privileges of whoever calls it (the sweeper runs as the connector user,
pg_cron as the job owner), so that caller needs DELETE/TRUNCATE/DROP rights on policy targets.
Every run is logged in _pgfacade.lifecycle_runs and, when it changed rows or failed, announced
with a NOTIFY on the lifecycle channel.
"""

from __future__ import annotations

from psycopg import sql
from pydantic import TypeAdapter

from pgfacade.application.errors import InvalidRequest, NotFound
from pgfacade.application.registry import ADMIN, ADMIN_WRITE, DDL, op
from pgfacade.configuration.settings import META_SCHEMA as M
from pgfacade.contracts.base import Count, Done, Flag
from pgfacade.contracts.enums import LifecycleAction, LifecycleKind, OperationHint, OperationStatus
from pgfacade.contracts.lifecycle import (
    LIFECYCLE_POLICY_ADAPTER,
    LifecycleInstall,
    LifecycleList,
    LifecyclePolicy,
    LifecyclePolicyList,
    LifecyclePolicyWrite,
    LifecyclePreview,
    LifecycleRemove,
    LifecycleRowTtl,
    LifecycleRun,
    LifecycleRunList,
    LifecycleRunOutcome,
    LifecycleRunRecord,
    LifecycleRunReport,
    LifecycleRuns,
    LifecycleSchedule,
    LifecycleTableExpiry,
    RowTtlPolicy,
    TableExpiryPolicy,
)
from pgfacade.contracts.types import (
    CronExpression,
    LifecyclePolicyId,
    OperationFlag,
    TableName,
)
from pgfacade.infrastructure.postgres.engine import Conn, Core
from pgfacade.infrastructure.postgres.queries import Statement
from pgfacade.infrastructure.postgres.queries import lifecycle as lifecycle_sql

CRON_JOB = "pgfacade_lifecycle"
_CRON_SCHEDULE = TypeAdapter(CronExpression | None)
_TIME_TYPES = ("timestamp with time zone", "timestamp without time zone", "date")


async def _installed(db: Core) -> OperationFlag:
    result = await db.read(Statement.LIFECYCLE_INSTALLED.text)
    return Flag.model_validate(result.rows[0]).ok


async def _require_installed(db: Core) -> None:
    if not await _installed(db):
        raise NotFound("lifecycle is not installed; run lifecycle.install first")


async def _has_cron(db: Core) -> OperationFlag:
    result = await db.read(Statement.LIFECYCLE_CRON_EXTENSION_EXISTS.text)
    return len(result.rows) > 0


async def _policy(db: Core, policy_id: LifecyclePolicyId) -> LifecyclePolicy:
    await _require_installed(db)
    result = await db.read(Statement.LIFECYCLE_GET.text, [policy_id])
    if not result.rows:
        raise NotFound(f"policy {policy_id} does not exist")
    return LIFECYCLE_POLICY_ADAPTER.validate_python(result.rows[0])


@op(LifecycleInstall, response=Done, perm=ADMIN_WRITE)
async def install(db: Core, req: LifecycleInstall) -> Done:
    statement = lifecycle_sql.install(db.settings.lifecycle_channel)
    async with db.tx() as conn:
        await conn.execute(statement)
    db.invalidate()
    return Done(status=OperationStatus.INSTALLED, detail={"schema": M, "channel": db.settings.lifecycle_channel})


@op(LifecycleList, response=LifecyclePolicyList, perm=ADMIN)
async def list_policies(db: Core, req: LifecycleList) -> LifecyclePolicyList:
    if not await _installed(db):
        return LifecyclePolicyList(items=[], installed=False)
    result = await db.read(Statement.LIFECYCLE_LIST.text)
    scheduled: CronExpression | None = None
    if await _has_cron(db):
        cron = await db.read(Statement.LIFECYCLE_CRON.text)
        scheduled = _CRON_SCHEDULE.validate_python(cron.rows[0]["schedule"]) if cron.rows else None
    return LifecyclePolicyList(
        items=[LIFECYCLE_POLICY_ADAPTER.validate_python(r) for r in result.rows], installed=True, scheduled=scheduled
    )


async def _ensure_archive(db: Core, conn: Conn, source: sql.Identifier, archive: TableName) -> None:
    db.require(DDL)
    await conn.execute(lifecycle_sql.create_archive(db.qualified(archive), source))
    db.invalidate()


@op(LifecycleRowTtl, response=RowTtlPolicy, perm=ADMIN_WRITE, hint=OperationHint.DESTRUCTIVE)
async def row_ttl(db: Core, req: LifecycleRowTtl) -> RowTtlPolicy:
    await _require_installed(db)
    async with db.tx() as conn:
        meta = await db.table(conn, req.input.table)
        if req.input.column not in meta.columns:
            if not req.input.add_column:
                raise InvalidRequest(f'column "{req.input.column}" does not exist on {meta.label}; set add_column=true to create it')
            if req.input.ttl is None:
                raise InvalidRequest("add_column needs a ttl: the new column defaults to now() and rows expire ttl later")
            db.require(DDL)
            await conn.execute(lifecycle_sql.add_expiry_column(meta.ident, req.input.column))
            db.invalidate()
        elif meta.columns[req.input.column].regtype not in _TIME_TYPES:
            raise InvalidRequest(
                f'column "{req.input.column}" is {meta.columns[req.input.column].regtype}; row_ttl needs a timestamp or date column'
            )
        archive = None
        if req.input.action == LifecycleAction.ARCHIVE:
            archive = ".".join(db.split(req.input.archive_table or f"{meta.schema_name}.{meta.name}_archive"))
            await _ensure_archive(db, conn, meta.ident, archive)
        row = await (
            await conn.execute(
                Statement.LIFECYCLE_UPSERT.text,
                LifecyclePolicyWrite.model_validate(
                    req.input.model_dump()
                    | {"kind": LifecycleKind.ROW_TTL, "schema_name": meta.schema_name, "table_name": meta.name, "archive_table": archive}
                ).model_dump(),
            )
        ).fetchone()
    return RowTtlPolicy.model_validate(row)


@op(LifecycleTableExpiry, response=TableExpiryPolicy, perm=ADMIN_WRITE, hint=OperationHint.DESTRUCTIVE)
async def table_expiry(db: Core, req: LifecycleTableExpiry) -> TableExpiryPolicy:
    await _require_installed(db)
    async with db.tx() as conn:
        meta = await db.table(conn, req.input.table)
        if req.input.expires_in is not None:
            r = await (await conn.execute(Statement.LIFECYCLE_EXPIRY_TIME.text, [req.input.expires_in])).fetchone()
            expires_at = r["at"] if r else None
        else:
            expires_at = req.input.expires_at
        row = await (
            await conn.execute(
                Statement.LIFECYCLE_UPSERT.text,
                LifecyclePolicyWrite.model_validate(
                    req.input.model_dump()
                    | {
                        "kind": LifecycleKind.TABLE_EXPIRY,
                        "schema_name": meta.schema_name,
                        "table_name": meta.name,
                        "expires_at": expires_at,
                    }
                ).model_dump(),
            )
        ).fetchone()
    return TableExpiryPolicy.model_validate(row)


@op(LifecyclePreview, response=Count, perm=ADMIN)
async def preview(db: Core, req: LifecyclePreview) -> Count:
    p = await _policy(db, req.input.policy_id)
    if not p.enabled:
        return Count(count=0)
    async with db.tx(read_only=True, rollback=True) as conn:
        if p.kind == LifecycleKind.TABLE_EXPIRY:
            row = await (await conn.execute(Statement.LIFECYCLE_PREVIEW_EXPIRY.text, [p.expires_at])).fetchone()
            return Count.model_validate(row)
        prepared = lifecycle_sql.preview(p)
        row = await (await conn.execute(prepared.statement, prepared.parameters)).fetchone()
        return Count.model_validate(row)


@op(LifecycleRemove, response=Done, perm=ADMIN_WRITE, hint=OperationHint.DESTRUCTIVE)
async def remove(db: Core, req: LifecycleRemove) -> Done:
    await _require_installed(db)
    async with db.tx() as conn:
        cur = await conn.execute(Statement.LIFECYCLE_REMOVE.text, [req.input.policy_id])
        if cur.rowcount == 0:
            raise NotFound(f"policy {req.input.policy_id} does not exist")
    return Done(status="DELETE 1")


@op(LifecycleRun, response=LifecycleRunReport, perm=ADMIN_WRITE, hint=OperationHint.DESTRUCTIVE)
async def run(db: Core, req: LifecycleRun) -> LifecycleRunReport:
    await _require_installed(db)
    if req.input.policy_id is not None:
        await _policy(db, req.input.policy_id)
    result = await db.read(Statement.LIFECYCLE_RUN.text, [req.input.policy_id])
    db.invalidate()
    return LifecycleRunReport(items=[LifecycleRunOutcome.model_validate(r) for r in result.rows])


@op(LifecycleRuns, response=LifecycleRunList, perm=ADMIN)
async def runs(db: Core, req: LifecycleRuns) -> LifecycleRunList:
    await _require_installed(db)
    result = await db.read(
        Statement.LIFECYCLE_RUNS.text, [req.input.policy_id, req.input.policy_id, min(req.input.limit, db.settings.max_rows)]
    )
    return LifecycleRunList(items=[LifecycleRunRecord.model_validate(r) for r in result.rows])


@op(LifecycleSchedule, response=Done, perm=ADMIN_WRITE, hint=OperationHint.DESTRUCTIVE)
async def schedule(db: Core, req: LifecycleSchedule) -> Done:
    await _require_installed(db)
    if not await _has_cron(db):
        raise NotFound("pg_cron is not installed; the in-process sweeper (PGFACADE_LIFECYCLE_SWEEP_S) still runs")
    async with db.tx() as conn:
        if req.input.cron is None:
            existing = await (await conn.execute(Statement.LIFECYCLE_CRON.text)).fetchone()
            if existing:
                await conn.execute(Statement.LIFECYCLE_UNSCHEDULE.text, [CRON_JOB])
            return Done(status="UNSCHEDULED")
        await conn.execute(Statement.LIFECYCLE_SCHEDULE.text, [CRON_JOB, req.input.cron, Statement.LIFECYCLE_SCHEDULED_COMMAND.text])
    return Done(status=OperationStatus.SCHEDULED, detail={"job": CRON_JOB, "cron": req.input.cron})
