from __future__ import annotations

from psycopg import sql

from pgfacade.contracts.lifecycle import RowTtlPolicy
from pgfacade.contracts.types import Name
from pgfacade.infrastructure.postgres.queries import Statement
from pgfacade.infrastructure.postgres.queries.records import PreparedQuery
from pgfacade.shared.types import LifecycleChannel


def install(channel: LifecycleChannel) -> sql.Composed:
    return Statement.LIFECYCLE_INSTALL.sql.format(channel=sql.Literal(channel))


def create_archive(archive: sql.Identifier, source: sql.Identifier) -> sql.Composed:
    return Statement.LIFECYCLE_CREATE_ARCHIVE.sql.format(archive, source)


def add_expiry_column(table: sql.Identifier, column: Name) -> sql.Composed:
    return Statement.LIFECYCLE_ADD_EXPIRY_COLUMN.sql.format(table, sql.Identifier(column))


def preview(policy: RowTtlPolicy) -> PreparedQuery:
    column = sql.Identifier(policy.expiry_column)
    condition = sql.SQL("{} <= now()").format(column) if policy.ttl is None else sql.SQL("{} <= now() - %s::interval").format(column)
    statement = Statement.LIFECYCLE_PREVIEW_ROWS.sql.format(sql.Identifier(policy.schema_name, policy.table_name), condition)
    return PreparedQuery(statement=statement, parameters=[] if policy.ttl is None else [policy.ttl])
