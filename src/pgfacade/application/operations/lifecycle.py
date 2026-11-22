"""lifecycle.* handlers: TTL/expiry policies stored in the database and applied by a SQL function.

The function runs with the privileges of whoever calls it (the sweeper runs as the connector user,
pg_cron as the job owner), so that caller needs DELETE/TRUNCATE/DROP rights on policy targets.
Every run is logged in _pgfacade.lifecycle_runs and, when it changed rows or failed, announced
with a NOTIFY on the lifecycle channel.
"""

from __future__ import annotations

from typing import assert_never

from pydantic import TypeAdapter

from pgfacade.application.errors import InvalidRequest, NotFound
from pgfacade.application.registry import ADMIN, ADMIN_WRITE, DDL, op
from pgfacade.configuration.settings import META_SCHEMA as M
from pgfacade.contracts.base import Count, Done, Flag
from pgfacade.contracts.enums import OperationHint, OperationStatus
from pgfacade.contracts.lifecycle import (
    LIFECYCLE_POLICY_ADAPTER,
    AllPolicies,
    ArchiveRowsInput,
    CronSchedule,
    DeleteRows,
    ExpiresAt,
    ExpiresIn,
    LifecycleInstall,
    LifecycleList,
    LifecyclePolicy,
    LifecyclePolicyList,
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
    NoSchedule,
    OnePolicy,
    RowAgeInput,
    RowDeadlineInput,
    RowTtlPolicy,
    TableExpiryPolicy,
)
from pgfacade.contracts.types import EventDateTime, LifecyclePolicyId, OperationFlag, TableName
from pgfacade.infrastructure.postgres.engine import Conn, Core
from pgfacade.infrastructure.postgres.queries import Statement
from pgfacade.infrastructure.postgres.queries import lifecycle as lifecycle_sql
from pgfacade.infrastructure.postgres.queries.composition import TableMeta

CRON_JOB = "pgfacade_lifecycle"
_EXPIRY_TIME = TypeAdapter(EventDateTime)
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


async def _schedule(db: Core) -> CronSchedule | NoSchedule:
    if not await _has_cron(db):
        return NoSchedule()
    cron = await db.read(Statement.LIFECYCLE_CRON.text)
    return CronSchedule.model_validate({"expression": cron.rows[0]["schedule"]}) if cron.rows else NoSchedule()


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
    return LifecyclePolicyList(
        items=[LIFECYCLE_POLICY_ADAPTER.validate_python(r) for r in result.rows], installed=True, schedule=await _schedule(db)
    )


async def _require_expiry_column(db: Core, conn: Conn, table: TableMeta, expiry: RowAgeInput | RowDeadlineInput) -> None:
    column = table.columns.get(expiry.column)
    if column is None:
        if not (isinstance(expiry, RowAgeInput) and expiry.add_column):
            raise InvalidRequest(f'column "{expiry.column}" does not exist on {table.label}; an age expiry can add it with add_column=true')
        db.require(DDL)
        await conn.execute(lifecycle_sql.add_expiry_column(table.ident, expiry.column))
        db.invalidate()
    elif column.regtype not in _TIME_TYPES:
        raise InvalidRequest(f'column "{expiry.column}" is {column.regtype}; row_ttl needs a timestamp or date column')


async def _archive_table(db: Core, conn: Conn, table: TableMeta, action: DeleteRows | ArchiveRowsInput) -> TableName | None:
    match action:
        case DeleteRows():
            return None
        case ArchiveRowsInput():
            archive = ".".join(db.split(action.table or f"{table.schema_name}.{table.name}_archive"))
            db.require(DDL)
            await conn.execute(lifecycle_sql.create_archive(db.qualified(archive), table.ident))
            db.invalidate()
            return archive
        case _:
            assert_never(action)


@op(LifecycleRowTtl, response=RowTtlPolicy, perm=ADMIN_WRITE, hint=OperationHint.DESTRUCTIVE)
async def row_ttl(db: Core, req: LifecycleRowTtl) -> RowTtlPolicy:
    await _require_installed(db)
    async with db.tx() as conn:
        table = await db.table(conn, req.input.table)
        await _require_expiry_column(db, conn, table, req.input.expiry)
        archive = await _archive_table(db, conn, table, req.input.action)
        upsert = lifecycle_sql.upsert_row_ttl(table, req.input, archive)
        row = await (await conn.execute(upsert.statement, upsert.parameters)).fetchone()
    return RowTtlPolicy.model_validate(row)


async def _expiry_time(conn: Conn, expiry: ExpiresAt | ExpiresIn) -> EventDateTime:
    match expiry:
        case ExpiresAt():
            return expiry.time
        case ExpiresIn():
            row = await (await conn.execute(Statement.LIFECYCLE_EXPIRY_TIME.text, [expiry.interval])).fetchone()
            return _EXPIRY_TIME.validate_python(row["at"] if row else None)
        case _:
            assert_never(expiry)


@op(LifecycleTableExpiry, response=TableExpiryPolicy, perm=ADMIN_WRITE, hint=OperationHint.DESTRUCTIVE)
async def table_expiry(db: Core, req: LifecycleTableExpiry) -> TableExpiryPolicy:
    await _require_installed(db)
    async with db.tx() as conn:
        table = await db.table(conn, req.input.table)
        upsert = lifecycle_sql.upsert_table_expiry(table, req.input, await _expiry_time(conn, req.input.expiry))
        row = await (await conn.execute(upsert.statement, upsert.parameters)).fetchone()
    return TableExpiryPolicy.model_validate(row)


@op(LifecyclePreview, response=Count, perm=ADMIN)
async def preview(db: Core, req: LifecyclePreview) -> Count:
    policy = await _policy(db, req.input.policy_id)
    if not policy.enabled:
        return Count(count=0)
    async with db.tx(read_only=True, rollback=True) as conn:
        match policy:
            case TableExpiryPolicy():
                row = await (await conn.execute(Statement.LIFECYCLE_PREVIEW_EXPIRY.text, [policy.expires_at])).fetchone()
            case RowTtlPolicy():
                prepared = lifecycle_sql.preview(policy)
                row = await (await conn.execute(prepared.statement, prepared.parameters)).fetchone()
            case _:
                assert_never(policy)
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
    policy_id: LifecyclePolicyId | None
    match req.input.target:
        case AllPolicies():
            policy_id = None
        case OnePolicy(policy_id=policy_id):
            await _policy(db, policy_id)
        case _:
            assert_never(req.input.target)
    result = await db.read(Statement.LIFECYCLE_RUN.text, [policy_id])
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
        match req.input.schedule:
            case NoSchedule():
                existing = await (await conn.execute(Statement.LIFECYCLE_CRON.text)).fetchone()
                if existing:
                    await conn.execute(Statement.LIFECYCLE_UNSCHEDULE.text, [CRON_JOB])
                return Done(status="UNSCHEDULED")
            case CronSchedule(expression=expression):
                await conn.execute(Statement.LIFECYCLE_SCHEDULE.text, [CRON_JOB, expression, Statement.LIFECYCLE_SCHEDULED_COMMAND.text])
                return Done(status=OperationStatus.SCHEDULED, detail={"job": CRON_JOB, "cron": expression})
            case _:
                assert_never(req.input.schedule)
