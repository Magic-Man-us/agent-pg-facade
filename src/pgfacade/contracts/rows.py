"""rows.* and sql.* requests."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, JsonValue, model_validator

from pgfacade.contracts.base import (
    Contract,
    Count,
    Filtered,
    Flag,
    Name,
    OrderBy,
    Params,
    QueryResult,
    RequestContract,
    Returning,
    Row,
    TableName,
    Text,
)
from pgfacade.contracts.enums import AggregateFunction, ConflictKind, Operation
from pgfacade.contracts.types import (
    CsvData,
    CsvDelimiter,
    NonEmptyItems,
    NonEmptyRowInput,
    OperationFlag,
    ResultLabel,
    RowInput,
    RowLimit,
    RowOffset,
    SqlStatement,
)


class Ordered(Contract):
    order_by: list[OrderBy] = Field(default_factory=list)
    limit: RowLimit | None = Field(None, description="Capped by server max_rows")


class Aggregate(Contract):
    fn: AggregateFunction
    column: Name | None = Field(None, description="Omit only for count(*)")
    alias: Name | None = None

    @model_validator(mode="after")
    def _column_required(self) -> Aggregate:
        if self.column is None and self.fn != AggregateFunction.COUNT:
            raise ValueError(f"{self.fn} requires a column")
        return self

    @property
    def name(self) -> ResultLabel:
        return self.alias or (f"{self.fn}_{self.column}" if self.column else AggregateFunction.COUNT)


class DoNothing(Contract):
    kind: Literal[ConflictKind.DO_NOTHING] = ConflictKind.DO_NOTHING
    target: list[Name] = Field(default_factory=list, description="Conflict columns; empty matches any constraint")


class DoUpdate(Contract):
    kind: Literal[ConflictKind.DO_UPDATE] = ConflictKind.DO_UPDATE
    target: NonEmptyItems[Name] = Field(description="Conflict columns (must match a unique index)")
    update: list[Name] | None = Field(None, description="Columns overwritten from EXCLUDED; default all non-target inserted columns")


OnConflict = Annotated[DoNothing | DoUpdate, Field(discriminator="kind")]


class Plan(Contract):
    plan: JsonValue


class RowsSelectInput(Filtered, Ordered):
    table: TableName
    columns: list[Name] | None = Field(None, description="None selects all columns")
    offset: RowOffset = Field(0)
    distinct: OperationFlag = False
    with_total: OperationFlag = Field(False, description="Also return total matching row count")


class RowsSelect(RequestContract[QueryResult]):
    """Select rows with filters, ordering, and pagination."""

    kind: Literal[Operation.ROWS_SELECT] = Operation.ROWS_SELECT
    input: RowsSelectInput


class RowsGetInput(Contract):
    table: TableName
    key: JsonValue
    columns: list[Name] | None = None


class RowsGet(RequestContract[Row]):
    """Fetch one row by primary key (scalar for single-column keys, object for composite)."""

    kind: Literal[Operation.ROWS_GET] = Operation.ROWS_GET
    input: RowsGetInput


class RowsCountInput(Filtered):
    table: TableName


class RowsCount(RequestContract[Count]):
    """Count rows matching filters."""

    kind: Literal[Operation.ROWS_COUNT] = Operation.ROWS_COUNT
    input: RowsCountInput


class RowsExistsInput(Filtered):
    table: TableName


class RowsExists(RequestContract[Flag]):
    """Whether any row matches the filters."""

    kind: Literal[Operation.ROWS_EXISTS] = Operation.ROWS_EXISTS
    input: RowsExistsInput


class RowsAggregateInput(Filtered, Ordered):
    table: TableName
    aggregates: NonEmptyItems[Aggregate]
    group_by: list[Name] = Field(default_factory=list)


class RowsAggregate(RequestContract[QueryResult]):
    """count/count_distinct/sum/avg/min/max with optional GROUP BY; order_by may use aggregate names."""

    kind: Literal[Operation.ROWS_AGGREGATE] = Operation.ROWS_AGGREGATE
    input: RowsAggregateInput


class RowsInsertInput(Contract):
    table: TableName
    rows: NonEmptyItems[RowInput] = Field(description="Missing keys use column DEFAULT")
    on_conflict: OnConflict | None = None
    returning: Returning = Field(default_factory=lambda: ["*"])


class RowsInsert(RequestContract[QueryResult]):
    """Insert rows; on_conflict do_update = upsert, do_nothing = insert-ignore."""

    kind: Literal[Operation.ROWS_INSERT] = Operation.ROWS_INSERT
    input: RowsInsertInput


class RowsUpdateInput(Filtered):
    table: TableName
    values: NonEmptyRowInput
    returning: Returning = Field(default_factory=lambda: ["*"])
    allow_all: OperationFlag = False


class RowsUpdate(RequestContract[QueryResult]):
    """Update rows matching filters. Refused without filters unless allow_all."""

    kind: Literal[Operation.ROWS_UPDATE] = Operation.ROWS_UPDATE
    input: RowsUpdateInput


class RowsDeleteInput(Filtered):
    table: TableName
    returning: Returning = Field(default_factory=list)
    allow_all: OperationFlag = False


class RowsDelete(RequestContract[QueryResult]):
    """Delete rows matching filters. Refused without filters unless allow_all."""

    kind: Literal[Operation.ROWS_DELETE] = Operation.ROWS_DELETE
    input: RowsDeleteInput


class RowsExportCsvInput(Filtered, Ordered):
    table: TableName
    columns: list[Name] | None = None
    header: OperationFlag = True


class RowsExportCsv(RequestContract[Text]):
    """COPY matching rows to CSV text (capped by max_export_rows)."""

    kind: Literal[Operation.ROWS_EXPORT_CSV] = Operation.ROWS_EXPORT_CSV
    input: RowsExportCsvInput


class RowsImportCsvInput(Contract):
    table: TableName
    data: CsvData
    columns: list[Name] | None = Field(None, description="Target columns; default table order")
    header: OperationFlag = True
    delimiter: CsvDelimiter = ","


class RowsImportCsv(RequestContract[QueryResult]):
    """COPY CSV text into a table."""

    kind: Literal[Operation.ROWS_IMPORT_CSV] = Operation.ROWS_IMPORT_CSV
    input: RowsImportCsvInput


class SqlQueryInput(Contract):
    sql: SqlStatement
    params: Params = None


class SqlQuery(RequestContract[QueryResult]):
    """Run ONE read-only statement in a READ ONLY transaction that is always rolled back."""

    kind: Literal[Operation.SQL_QUERY] = Operation.SQL_QUERY
    input: SqlQueryInput


class SqlExecuteInput(Contract):
    sql: SqlStatement
    params: Params = None


class SqlExecute(RequestContract[QueryResult]):
    """Run ONE write or DDL statement; auto-committed."""

    kind: Literal[Operation.SQL_EXECUTE] = Operation.SQL_EXECUTE
    input: SqlExecuteInput


class SqlExplainInput(Contract):
    sql: SqlStatement
    params: Params = None
    analyze: OperationFlag = False


class SqlExplain(RequestContract[Plan]):
    """EXPLAIN (FORMAT JSON); analyze executes inside a read-only, rolled-back transaction."""

    kind: Literal[Operation.SQL_EXPLAIN] = Operation.SQL_EXPLAIN
    input: SqlExplainInput
