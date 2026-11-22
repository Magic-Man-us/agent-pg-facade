from __future__ import annotations

from typing import TYPE_CHECKING, cast

from psycopg import sql

from pgfacade.application.errors import InvalidRequest
from pgfacade.infrastructure.postgres.queries.composition import Binder
from pgfacade.infrastructure.postgres.queries.models import QueryDefinition
from pgfacade.infrastructure.postgres.queries.records import PreparedQuery
from pgfacade.infrastructure.postgres.queries.types import ParameterIdentifier, ParameterValue, ParamType, QueryParameterName

if TYPE_CHECKING:
    from pgfacade.infrastructure.postgres.engine import Conn, Core


async def prepare_query(
    db: Core, conn: Conn, definition: QueryDefinition, given: dict[QueryParameterName, ParameterValue]
) -> PreparedQuery:
    """Identifier params become quoted {placeholders}; value params are bound as %(name)s."""
    identifiers: dict[QueryParameterName, sql.Composable] = {}
    values: dict[QueryParameterName, ParameterValue] = {}
    tables = {
        key: await db.table(conn, cast(ParameterIdentifier, given[key]))
        for key, param in definition.params.items()
        if param.type == ParamType.TABLE and given[key] is not None
    }
    meta = next(iter(tables.values()), None)
    for key, p in definition.params.items():
        value = given[key]
        if value is None:
            values[key] = None
            continue
        if p.type == ParamType.TABLE:
            ident = tables[key].ident
            identifiers[key] = ident
            values[f"{key}_regclass"] = ident.as_string(conn)
        elif p.type == ParamType.COLUMN:
            column = cast(ParameterIdentifier, value)
            identifiers[key] = Binder(meta).col(column) if meta is not None else sql.Identifier(column)
        elif p.type == ParamType.IDENTIFIER:
            identifiers[key] = sql.Identifier(*cast(ParameterIdentifier, value).split(".", 1))
        else:
            values[key] = value
    if "limit" in values and isinstance(values["limit"], int):
        values["limit"] = min(values["limit"], db.settings.max_rows)
    statement: sql.SQL | sql.Composed = sql.SQL(definition.sql)
    if definition.has_identifiers:
        try:
            statement = sql.SQL(definition.sql).format(**identifiers)
        except (KeyError, IndexError, ValueError) as exc:
            raise InvalidRequest("Query template has invalid identifier placeholders") from exc
    return PreparedQuery(statement=statement, parameters=values)
