"""migration.* handlers: Alembic driven programmatically (no alembic.ini).

Migrations run as the connector user through Alembic's own SQLAlchemy connection, not under the
caller's SET ROLE. Revision files are plain SQL wrapped in op.execute().
"""

from __future__ import annotations

import asyncio

from pgfacade.application.registry import MIGRATE, MIGRATE_WRITE, op
from pgfacade.contracts.admin import (
    MigrationHistory,
    MigrationInit,
    MigrationOutcome,
    MigrationRevision,
    MigrationRun,
    MigrationStatus,
    MigrationStatusGet,
    RevisionInfo,
    RevisionInfoList,
)
from pgfacade.contracts.enums import MigrationAction, OperationHint
from pgfacade.infrastructure.migrations import AlembicBackend
from pgfacade.infrastructure.postgres.engine import Core

_DEFAULT_TARGET = {MigrationAction.UPGRADE: "head", MigrationAction.DOWNGRADE: "-1", MigrationAction.STAMP: "head"}


@op(MigrationStatusGet, response=MigrationStatus, perm=MIGRATE)
async def status(db: Core, req: MigrationStatusGet) -> MigrationStatus:
    return await asyncio.to_thread(AlembicBackend(db).status)


@op(MigrationInit, response=MigrationStatus, perm=MIGRATE_WRITE)
async def init(db: Core, req: MigrationInit) -> MigrationStatus:
    return await asyncio.to_thread(AlembicBackend(db).init)


@op(MigrationHistory, response=RevisionInfoList, perm=MIGRATE)
async def history(db: Core, req: MigrationHistory) -> RevisionInfoList:
    return RevisionInfoList(items=await asyncio.to_thread(AlembicBackend(db).history))


@op(MigrationRevision, response=RevisionInfo, perm=MIGRATE_WRITE)
async def revision(db: Core, req: MigrationRevision) -> RevisionInfo:
    return await asyncio.to_thread(AlembicBackend(db).revision, req.input)


@op(MigrationRun, response=MigrationOutcome, perm=MIGRATE_WRITE, hint=OperationHint.DESTRUCTIVE)
async def run(db: Core, req: MigrationRun) -> MigrationOutcome:
    outcome = await asyncio.to_thread(AlembicBackend(db).run, req.input.action, req.input.target or _DEFAULT_TARGET[req.input.action])
    db.invalidate()
    return outcome
