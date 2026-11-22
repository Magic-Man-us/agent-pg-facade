"""Typed query operations over registered SQL resources and operator files."""

from __future__ import annotations

from pgfacade.application.errors import NotFound
from pgfacade.application.registry import ADMIN, WRITE, op
from pgfacade.contracts.base import Done, QueryResult
from pgfacade.contracts.enums import OperationHint, OperationStatus
from pgfacade.contracts.queries import QueryInfo, QueryInfoList, QueryList, QueryParam, QueryReload, QueryRun
from pgfacade.infrastructure.postgres.engine import Core
from pgfacade.infrastructure.postgres.queries import Statement
from pgfacade.infrastructure.postgres.queries.loader import query_definitions, reload
from pgfacade.infrastructure.postgres.queries.models import QueryDefinition
from pgfacade.infrastructure.postgres.queries.preparation import prepare_query
from pgfacade.infrastructure.postgres.queries.types import (
    BUILTIN_QUERY_SOURCE,
    QueryAccess,
    QueryName,
)


def _info(name: QueryName, q: QueryDefinition) -> QueryInfo:
    return QueryInfo(
        name=name,
        category=q.category,
        description=q.description,
        params=[QueryParam.model_validate(p.model_dump() | {"name": k}) for k, p in q.params.items()],
        requires=q.requires,
        source=q.source,
    )


@op(QueryList, response=QueryInfoList)
async def query_list(db: Core, req: QueryList) -> QueryInfoList:
    entries = query_definitions(db.settings.queries_dir)
    can_admin = db.allows(ADMIN)
    admin_queries = {statement.query_name for statement in Statement if statement.access == QueryAccess.ADMIN}
    items = [
        _info(name, query)
        for name, query in sorted(entries.items())
        if (can_admin or name not in admin_queries) and (req.input.category is None or query.category == req.input.category)
    ]
    return QueryInfoList(items=items, directory=str(db.settings.queries_dir) if db.settings.queries_dir else None)


@op(QueryRun, response=QueryResult)
async def query_run(db: Core, req: QueryRun) -> QueryResult:
    q = query_definitions(db.settings.queries_dir).get(req.input.name)
    if q is None:
        raise NotFound(f"no curated query named {req.input.name!r}; see query.list")
    if any(statement.query_name == req.input.name and statement.access == QueryAccess.ADMIN for statement in Statement):
        db.require(ADMIN)
    parameters = q.validate_parameters(req.input.params, name=req.input.name)
    if q.requires is not None:
        found = await db.read(Statement.QUERIES_EXTENSION_EXISTS.text, [q.requires])
        if not found.rows:
            raise NotFound(f"{req.input.name} needs the {q.requires} extension")
    cap = min(req.input.limit or db.settings.max_rows, db.settings.max_rows)
    async with db.tx(read_only=True, rollback=True) as conn:
        prepared = await prepare_query(db, conn, q, parameters)
        return await db.stream(conn, prepared.statement, prepared.parameters, cap)


@op(QueryReload, response=Done, perm=WRITE, hint=OperationHint.DESTRUCTIVE, idempotent=True)
async def query_reload(db: Core, req: QueryReload) -> Done:
    reload()
    entries = query_definitions(db.settings.queries_dir)
    files = sum(q.source != BUILTIN_QUERY_SOURCE for q in entries.values())
    return Done(status=OperationStatus.RELOADED, detail={"queries": len(entries), "files": files})
