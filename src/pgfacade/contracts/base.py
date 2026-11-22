"""Base contract, shared aliases, filters, ordering, and generic results."""

from __future__ import annotations

from typing import Annotated, Generic, Literal, TypeVar, cast

from pydantic import BaseModel, Field, JsonValue, field_serializer
from pydantic_core import to_jsonable_python

from pgfacade.contracts.enums import CmpOp as CmpOp
from pgfacade.contracts.enums import FilterKind, NullOrder, Operation, TextSearchMode
from pgfacade.contracts.types import SQL_TYPE_PATTERN as SQL_TYPE_PATTERN
from pgfacade.contracts.types import (
    CommandStatus,
    DatabaseRow,
    NonEmptyItems,
    OperationDetail,
    OperationFlag,
    QueryText,
    ResultLabel,
    ResultText,
    RowCount,
    RowInput,
    SearchConfiguration,
)
from pgfacade.contracts.types import DefaultExpr as DefaultExpr
from pgfacade.contracts.types import Interval as Interval
from pgfacade.contracts.types import Name as Name
from pgfacade.contracts.types import Params as Params
from pgfacade.contracts.types import Returning as Returning
from pgfacade.contracts.types import SqlType as SqlType
from pgfacade.contracts.types import TableName as TableName
from pgfacade.shared.config import CONTRACT_CONFIG


class Contract(BaseModel):
    """All request and response models: frozen, no unknown fields."""

    model_config = CONTRACT_CONFIG


ResultT_co = TypeVar("ResultT_co", bound=Contract, covariant=True)


# Pydantic's phantom result parameter needs explicit covariance for request-wide dispatch.
class RequestContract(Contract, Generic[ResultT_co]):  # noqa: UP046
    kind: Operation
    input: Contract


# ---------------------------------------------------------------- filters


class Cmp(Contract):
    """column <op> value. eq/ne with null become IS [NOT] NULL."""

    kind: Literal[FilterKind.CMP] = FilterKind.CMP
    column: Name
    op: CmpOp = CmpOp.EQ
    value: JsonValue


class In(Contract):
    kind: Literal[FilterKind.IN] = FilterKind.IN
    column: Name
    values: list[JsonValue]
    negate: OperationFlag = False


class IsNull(Contract):
    kind: Literal[FilterKind.IS_NULL] = FilterKind.IS_NULL
    column: Name
    negate: OperationFlag = False


class Between(Contract):
    kind: Literal[FilterKind.BETWEEN] = FilterKind.BETWEEN
    column: Name
    low: JsonValue
    high: JsonValue


class Contains(Contract):
    """column @> value for jsonb or array columns."""

    kind: Literal[FilterKind.CONTAINS] = FilterKind.CONTAINS
    column: Name
    value: JsonValue


class TextSearch(Contract):
    """Full-text match on a text column (to_tsvector applied) or a tsvector column."""

    kind: Literal[FilterKind.TEXT_SEARCH] = FilterKind.TEXT_SEARCH
    column: Name
    query: QueryText
    config: SearchConfiguration = "english"
    mode: TextSearchMode = TextSearchMode.WEBSEARCH


class And(Contract):
    kind: Literal[FilterKind.AND] = FilterKind.AND
    filters: NonEmptyItems[Filter]


class Or(Contract):
    kind: Literal[FilterKind.OR] = FilterKind.OR
    filters: NonEmptyItems[Filter]


class Not(Contract):
    kind: Literal[FilterKind.NOT] = FilterKind.NOT
    filter: Filter


Filter = Annotated[Cmp | In | IsNull | Between | Contains | TextSearch | And | Or | Not, Field(discriminator="kind")]

for _model in (And, Or, Not):
    _model.model_rebuild()


class OrderBy(Contract):
    column: Name
    desc: OperationFlag = False
    nulls: NullOrder | None = None


class Filtered(Contract):
    """Mixin for requests that address rows: filter tree plus equality shorthand."""

    where: list[Filter] = Field(default_factory=list, description="Filters, ANDed together")
    match: RowInput = Field(default_factory=dict, description="Equality shorthand, ANDed; null means IS NULL")

    @property
    def has_filters(self) -> OperationFlag:
        return bool(self.where or self.match)


# ---------------------------------------------------------------- generic results


class QueryResult(Contract):
    columns: list[ResultLabel] = Field(default_factory=list)
    rows: list[DatabaseRow] = Field(default_factory=list)
    rowcount: RowCount = Field(0, description="Rows affected (DML) or returned (reads)")
    total: RowCount | None = Field(None, description="Total matches when with_total was requested")
    truncated: OperationFlag = Field(False, description="More rows existed than were returned")
    status: CommandStatus | None = Field(None, description="Server command tag, e.g. 'CREATE TABLE'")

    @field_serializer("rows", when_used="json")
    def _rows_json(self, rows: list[DatabaseRow]) -> JsonValue:
        return jsonable(rows)


class Row(Contract):
    row: DatabaseRow | None = Field(None, description="The row, or null when not found")

    @field_serializer("row", when_used="json")
    def _row_json(self, row: DatabaseRow | None) -> JsonValue:
        return jsonable(row)


class Count(Contract):
    count: RowCount


class Flag(Contract):
    ok: OperationFlag
    message: ResultText | None = None


class Text(Contract):
    text: ResultText


class Done(Contract):
    """Command outcome for DDL/admin statements."""

    status: CommandStatus | None = None
    detail: OperationDetail = Field(default_factory=dict)


def jsonable(value: object) -> JsonValue:
    """JSON-safe copy (dates to ISO strings, bytes to base64, Decimal to str)."""
    return cast(JsonValue, to_jsonable_python(value, fallback=str, bytes_mode="base64"))
