"""query.* requests: the curated catalog of ready-made queries."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, JsonValue

from pgfacade.contracts.base import Contract, Done, QueryResult, RequestContract
from pgfacade.contracts.enums import Operation
from pgfacade.contracts.types import (
    DirectoryName,
    OperationFlag,
    QueryArguments,
    QueryCategory,
    QueryDescription,
    QueryName,
    QueryParameterName,
    QueryParameterType,
    QuerySource,
    ResultLabel,
    ResultText,
    RowLimit,
)


class QueryParam(Contract):
    name: QueryParameterName
    type: QueryParameterType
    default: JsonValue = None
    required: OperationFlag = False
    description: QueryDescription = ""


class QueryInfo(Contract):
    name: ResultLabel
    category: QueryCategory
    description: QueryDescription
    params: list[QueryParam]
    requires: ResultText | None = Field(None, description="Extension needed, if any")
    source: QuerySource = Field("builtin", description="builtin, or the file it was loaded from")


class QueryInfoList(Contract):
    items: list[QueryInfo]
    directory: DirectoryName | None = Field(None, description="PGFACADE_QUERIES_DIR when set")


class QueryListInput(Contract):
    category: QueryCategory | None = None


class QueryList(RequestContract[QueryInfoList]):
    """Catalog of curated queries with their parameters."""

    kind: Literal[Operation.QUERY_LIST] = Operation.QUERY_LIST
    input: QueryListInput


class QueryRunInput(Contract):
    name: QueryName
    params: QueryArguments = Field(default_factory=dict)
    limit: RowLimit | None = Field(None, description="Capped by server max_rows")


class QueryRun(RequestContract[QueryResult]):
    """Run a curated query by name (rolled back, READ ONLY; needs no raw-SQL permission)."""

    kind: Literal[Operation.QUERY_RUN] = Operation.QUERY_RUN
    input: QueryRunInput


class QueryReloadInput(Contract):
    pass


class QueryReload(RequestContract[Done]):
    """Re-read the bundled library and PGFACADE_QUERIES_DIR *.sql files."""

    kind: Literal[Operation.QUERY_RELOAD] = Operation.QUERY_RELOAD
    input: QueryReloadInput
