from __future__ import annotations

from typing import TYPE_CHECKING

from psycopg import sql

from pgfacade.contracts.admin import MaintBackendInput, MaintReindexInput, MaintVacuumInput
from pgfacade.contracts.enums import BackendAction, MaintenanceKind
from pgfacade.infrastructure.postgres.queries import Statement
from pgfacade.infrastructure.postgres.queries.composition import TableMeta, flag, kw

if TYPE_CHECKING:
    from pgfacade.infrastructure.postgres.engine import Core


def backend(spec: MaintBackendInput) -> sql.Composed:
    function = "pg_cancel_backend" if spec.action == BackendAction.CANCEL else "pg_terminate_backend"
    return Statement.ADMIN_BACKEND_CONTROL.sql.format(sql.SQL(function))


def vacuum(spec: MaintVacuumInput, meta: TableMeta | None) -> sql.Composed:
    flags = [value for value, enabled in (("FULL", spec.full), ("ANALYZE", spec.analyze)) if enabled]
    target = sql.SQL(" ") + meta.ident if meta is not None else sql.SQL("")
    options = sql.SQL(" ({})").format(sql.SQL(", ").join([kw(value) for value in flags])) if flags else sql.SQL("")
    return Statement.ADMIN_VACUUM.sql.format(options, target)


def analyze(meta: TableMeta | None) -> sql.Composed:
    target = sql.SQL(" ") + meta.ident if meta is not None else sql.SQL("")
    return Statement.ADMIN_ANALYZE.sql.format(target)


def reindex(db: Core, spec: MaintReindexInput) -> sql.Composed:
    identifier = sql.Identifier(spec.name) if spec.kind == MaintenanceKind.SCHEMA else db.qualified(spec.name)
    return Statement.ADMIN_REINDEX.sql.format(kw(spec.kind.upper()), flag(spec.concurrently, "CONCURRENTLY "), identifier)
