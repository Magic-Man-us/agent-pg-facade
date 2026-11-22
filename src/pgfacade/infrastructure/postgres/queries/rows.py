from __future__ import annotations

from typing import LiteralString

from psycopg import sql

from pgfacade.contracts.base import Filtered
from pgfacade.contracts.rows import (
    RowsAggregateInput,
    RowsDeleteInput,
    RowsExportCsvInput,
    RowsImportCsvInput,
    RowsInsertInput,
    RowsSelectInput,
    RowsUpdateInput,
    SqlExecuteInput,
    SqlExplainInput,
    SqlQueryInput,
)
from pgfacade.contracts.types import RowLimit, RowOffset
from pgfacade.infrastructure.postgres.queries import Statement
from pgfacade.infrastructure.postgres.queries.composition import (
    Binder,
    TableMeta,
    adapt_params,
    aggregate_sql,
    on_conflict_sql,
    order_sql,
    returning_sql,
    text,
    where_sql,
)
from pgfacade.infrastructure.postgres.queries.records import PreparedQuery

_MAX_PARAMS = 65_535


def select(meta: TableMeta, spec: RowsSelectInput | RowsExportCsvInput, limit: RowLimit, offset: RowOffset = 0) -> PreparedQuery:
    binder = Binder(meta)
    columns = sql.SQL(", ").join([binder.col(column) for column in spec.columns]) if spec.columns else sql.SQL("*")
    distinct = spec.distinct if isinstance(spec, RowsSelectInput) else False
    statement = Statement.ROWS_SELECT.sql.format(
        distinct=sql.SQL("DISTINCT " if distinct else ""),
        cols=columns,
        table=meta.ident,
        where=where_sql(spec, binder),
        order=order_sql(spec.order_by, binder),
        limit=sql.Literal(limit),
        offset=sql.Literal(offset),
    )
    return PreparedQuery(statement, binder.params)


def count(meta: TableMeta, spec: Filtered) -> PreparedQuery:
    binder = Binder(meta)
    return PreparedQuery(Statement.ROWS_COUNT.sql.format(meta.ident, where_sql(spec, binder)), binder.params)


def exists(meta: TableMeta, spec: Filtered) -> PreparedQuery:
    binder = Binder(meta)
    return PreparedQuery(Statement.ROWS_EXISTS.sql.format(meta.ident, where_sql(spec, binder)), binder.params)


def aggregate(meta: TableMeta, spec: RowsAggregateInput, limit: RowLimit) -> PreparedQuery:
    binder = Binder(meta)
    groups = [binder.col(group) for group in spec.group_by]
    aggregates = [sql.SQL("{} AS {}").format(aggregate_sql(item, binder), sql.Identifier(item.name)) for item in spec.aggregates]
    statement = Statement.ROWS_AGGREGATE.sql.format(
        select=sql.SQL(", ").join([*groups, *aggregates]),
        table=meta.ident,
        where=where_sql(spec, binder),
        group=(sql.SQL(" GROUP BY ") + sql.SQL(", ").join(groups)) if groups else sql.SQL(""),
        order=order_sql(spec.order_by, binder, frozenset(item.name for item in spec.aggregates)),
        limit=sql.Literal(limit + 1),
    )
    return PreparedQuery(statement, binder.params)


def insert(meta: TableMeta, spec: RowsInsertInput) -> list[PreparedQuery]:
    names = list(dict.fromkeys(key for row in spec.rows for key in row))
    probe = Binder(meta)
    identifiers = [probe.col(name) for name in names]
    if not names:
        statement = Statement.ROWS_INSERT_DEFAULTS.sql.format(
            meta.ident, on_conflict_sql(spec.on_conflict, names, probe), returning_sql(spec.returning, probe)
        )
        return [PreparedQuery(statement, []) for _ in spec.rows]
    statements = []
    per_batch = max(1, _MAX_PARAMS // len(names))
    for start in range(0, len(spec.rows), per_batch):
        binder = Binder(meta)
        values = sql.SQL(", ").join(
            [
                sql.SQL("({})").format(
                    sql.SQL(", ").join([binder.value(name, row[name]) if name in row else sql.SQL("DEFAULT") for name in names])
                )
                for row in spec.rows[start : start + per_batch]
            ]
        )
        statement = Statement.ROWS_INSERT.sql.format(
            table=meta.ident,
            cols=sql.SQL(", ").join(identifiers),
            values=values,
            conflict=on_conflict_sql(spec.on_conflict, names, binder),
            returning=returning_sql(spec.returning, binder),
        )
        statements.append(PreparedQuery(statement, binder.params))
    return statements


def update(meta: TableMeta, spec: RowsUpdateInput) -> PreparedQuery:
    binder = Binder(meta)
    assignments = sql.SQL(", ").join(
        [sql.SQL("{} = {}").format(binder.col(key), binder.value(key, value)) for key, value in spec.values.items()]
    )
    statement = Statement.ROWS_UPDATE.sql.format(
        table=meta.ident, sets=assignments, where=where_sql(spec, binder), returning=returning_sql(spec.returning, binder)
    )
    return PreparedQuery(statement, binder.params)


def delete(meta: TableMeta, spec: RowsDeleteInput) -> PreparedQuery:
    binder = Binder(meta)
    statement = Statement.ROWS_DELETE.sql.format(
        table=meta.ident, where=where_sql(spec, binder), returning=returning_sql(spec.returning, binder)
    )
    return PreparedQuery(statement, binder.params)


def export_csv(meta: TableMeta, spec: RowsExportCsvInput, limit: RowLimit) -> PreparedQuery:
    inner = select(meta, spec, limit)
    return PreparedQuery(
        Statement.ROWS_EXPORT_CSV.sql.format(inner.statement, sql.SQL("true" if spec.header else "false")), inner.parameters
    )


def import_csv(meta: TableMeta, spec: RowsImportCsvInput) -> sql.Composed:
    binder = Binder(meta)
    columns = sql.SQL(" ({})").format(sql.SQL(", ").join([binder.col(column) for column in spec.columns])) if spec.columns else sql.SQL("")
    return Statement.ROWS_IMPORT_CSV.sql.format(
        table=meta.ident, cols=columns, header=sql.SQL("true" if spec.header else "false"), delim=sql.Literal(spec.delimiter)
    )


def raw(spec: SqlQueryInput | SqlExecuteInput) -> PreparedQuery:
    return PreparedQuery(text(spec.sql), adapt_params(spec.params))


def explain(spec: SqlExplainInput) -> PreparedQuery:
    options: LiteralString = "FORMAT JSON, ANALYZE, BUFFERS" if spec.analyze else "FORMAT JSON"
    return PreparedQuery(Statement.ROWS_EXPLAIN.sql.format(sql.SQL(options)) + text(spec.sql), adapt_params(spec.params))
