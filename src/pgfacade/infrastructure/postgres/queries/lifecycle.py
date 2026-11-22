from __future__ import annotations

from typing import assert_never

from psycopg import sql

from pgfacade.contracts.lifecycle import (
    LifecycleRowTtlInput,
    LifecycleTableExpiryInput,
    RowAge,
    RowAgeInput,
    RowDeadline,
    RowTtlPolicy,
)
from pgfacade.contracts.types import EventDateTime, Name, TableName
from pgfacade.infrastructure.postgres.queries import Statement
from pgfacade.infrastructure.postgres.queries.composition import TableMeta
from pgfacade.infrastructure.postgres.queries.records import PreparedQuery
from pgfacade.shared.types import LifecycleChannel


def install(channel: LifecycleChannel) -> sql.Composed:
    return Statement.LIFECYCLE_INSTALL.sql.format(channel=sql.Literal(channel))


def create_archive(archive: sql.Identifier, source: sql.Identifier) -> sql.Composed:
    return Statement.LIFECYCLE_CREATE_ARCHIVE.sql.format(archive, source)


def add_expiry_column(table: sql.Identifier, column: Name) -> sql.Composed:
    return Statement.LIFECYCLE_ADD_EXPIRY_COLUMN.sql.format(table, sql.Identifier(column))


def upsert_row_ttl(table: TableMeta, rule: LifecycleRowTtlInput, archive: TableName | None) -> PreparedQuery:
    """Bind a row TTL policy to its stored columns. A deadline policy stores no ttl; only archiving stores a table."""
    return PreparedQuery(
        statement=Statement.LIFECYCLE_UPSERT_ROW_TTL.sql,
        parameters={
            "schema_name": table.schema_name,
            "table_name": table.name,
            "column_name": rule.expiry.column,
            "ttl": rule.expiry.ttl if isinstance(rule.expiry, RowAgeInput) else None,
            "action": rule.action.kind,
            "archive_table": archive,
            "batch_size": rule.batch_size,
            "enabled": rule.enabled,
        },
    )


def upsert_table_expiry(table: TableMeta, rule: LifecycleTableExpiryInput, expires_at: EventDateTime) -> PreparedQuery:
    return PreparedQuery(
        statement=Statement.LIFECYCLE_UPSERT_TABLE_EXPIRY.sql,
        parameters={
            "schema_name": table.schema_name,
            "table_name": table.name,
            "expires_at": expires_at,
            "action": rule.action,
            "enabled": rule.enabled,
        },
    )


def preview(policy: RowTtlPolicy) -> PreparedQuery:
    column = sql.Identifier(policy.expiry.column)
    table = sql.Identifier(policy.schema_name, policy.table_name)
    match policy.expiry:
        case RowDeadline():
            condition = sql.SQL("{} <= now()").format(column)
            return PreparedQuery(statement=Statement.LIFECYCLE_PREVIEW_ROWS.sql.format(table, condition), parameters=[])
        case RowAge(ttl=ttl):
            condition = sql.SQL("{} <= now() - %s::interval").format(column)
            return PreparedQuery(statement=Statement.LIFECYCLE_PREVIEW_ROWS.sql.format(table, condition), parameters=[ttl])
        case _:
            assert_never(policy.expiry)
