from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Annotated

from pydantic import AfterValidator, BeforeValidator, Field, JsonValue, TypeAdapter

from pgfacade.contracts.enums import DefaultExpr as DefaultExpr
from pgfacade.contracts.enums import MigrationAction as MigrationAction
from pgfacade.contracts.enums import OperationHint as OperationHint
from pgfacade.contracts.enums import OperationStatus, ParamType
from pgfacade.contracts.enums import WatchEvent as WatchEvent
from pgfacade.shared.types import FloatValue, IntegerValue

MAX_IDENTIFIER_BYTES = 63
QUALIFIED_TABLE_NAME_LENGTH = 127
SQL_TYPE_LENGTH = 64
MAX_NOTIFICATION_PAYLOAD_BYTES = 7900

IdentifierValue = Annotated[
    str, Field(min_length=1, max_length=MAX_IDENTIFIER_BYTES, pattern=r"^[^\x00]+$", description="PostgreSQL identifier")
]


def validate_identifier_bytes(value: IdentifierValue) -> IdentifierValue:
    if len(value.encode("utf-8")) > MAX_IDENTIFIER_BYTES:
        raise ValueError(f"PostgreSQL identifiers must fit in {MAX_IDENTIFIER_BYTES} UTF-8 bytes")
    return value


Name = Annotated[IdentifierValue, AfterValidator(validate_identifier_bytes)]
_IDENTIFIER_ADAPTER = TypeAdapter(Name)
QualifiedNameValue = Annotated[str, Field(min_length=1, max_length=QUALIFIED_TABLE_NAME_LENGTH, description='"table" or "schema.table"')]


def validate_table_identifier(value: QualifiedNameValue) -> QualifiedNameValue:
    parts = value.split(".")
    if len(parts) not in (1, 2):
        raise ValueError("Expected a table or schema.table identifier")
    for part in parts:
        _IDENTIFIER_ADAPTER.validate_python(part)
    return value


TableName = Annotated[QualifiedNameValue, AfterValidator(validate_table_identifier)]
Returning = Annotated[list[Name], Field(description='Columns to return: ["*"] for all, [] for none')]
Params = Annotated[
    list[JsonValue] | dict[str, JsonValue] | None,
    Field(description="Positional (%s) or named (%(name)s) parameters; objects are sent as jsonb"),
]
SQL_TYPE_PATTERN = r"^[A-Za-z_][A-Za-z0-9_ ]*(\(\s*\d+\s*(,\s*\d+\s*)?\))?(\s*\[\])*$"
SqlType = Annotated[
    str,
    Field(
        max_length=SQL_TYPE_LENGTH,
        pattern=SQL_TYPE_PATTERN,
        description="Postgres type, e.g. text, bigint, numeric(12,2), timestamptz, jsonb, text[]",
    ),
]
Interval = Annotated[
    str,
    Field(
        pattern=r"^\d+\s*(microseconds?|milliseconds?|seconds?|minutes?|hours?|days?|weeks?|months?|years?)$",
        description="Postgres interval, e.g. '30 days', '12 hours'",
    ),
]


OperationFlag = Annotated[bool, Field(description="Whether an operation option or result flag is enabled")]
ResultLabel = Annotated[str, Field(description="Name returned by PostgreSQL or a query result")]
ResultText = Annotated[str, Field(description="Text returned by an operation")]
RowCount = Annotated[IntegerValue, Field(description="Rows returned or affected by an operation")]
ByteCount = Annotated[IntegerValue, Field(description="Size in bytes reported by PostgreSQL")]
ResultCount = Annotated[IntegerValue, Field(description="Count reported by PostgreSQL")]
ProcessId = Annotated[IntegerValue, Field(description="PostgreSQL backend process identifier")]
EventDateTime = Annotated[datetime, Field(description="Timestamp of a database or notification event")]
SqlStatement = Annotated[str, Field(min_length=1, description="One PostgreSQL statement")]
SqlBody = Annotated[str, Field(description="SQL expression or migration body")]
RowLimit = Annotated[IntegerValue, Field(ge=1, description="Maximum requested result count")]
RowOffset = Annotated[IntegerValue, Field(ge=0, description="Number of matching rows to skip")]
QueryText = Annotated[str, Field(min_length=1, description="Full-text search query")]
SearchConfiguration = Annotated[str, Field(description="PostgreSQL text-search configuration")]
DatabaseCommandStatus = Annotated[str, Field(description="PostgreSQL command status tag")]
_OPERATION_STATUS_BY_VALUE = {status.value: status for status in OperationStatus}


def restore_command_status(value: object) -> object:
    return _OPERATION_STATUS_BY_VALUE.get(value, value) if isinstance(value, str) else value


CommandStatus = Annotated[OperationStatus | DatabaseCommandStatus, BeforeValidator(restore_command_status)]
ObjectComment = Annotated[str, Field(description="Comment attached to a database object")]
CsvData = Annotated[str, Field(description="CSV content")]
CsvDelimiter = Annotated[str, Field(min_length=1, max_length=1, description="CSV field delimiter")]
QueryName = Annotated[str, Field(min_length=1, description="Registered query name")]
QueryCategory = Annotated[str, Field(min_length=1, description="Registered query category")]
QueryDescription = Annotated[str, Field(description="Curated query or parameter description")]
QueryParameterName = Annotated[str, Field(min_length=1, pattern=r"^\w+$", description="Query parameter name")]
QueryParameterType = ParamType
QuerySource = Annotated[str, Field(min_length=1, description="Query source identifier or path")]


def path_text(value: object) -> object:
    return str(value) if isinstance(value, Path) else value


DirectoryName = Annotated[str, BeforeValidator(path_text), Field(description="Directory containing migrations or curated queries")]
FileName = Annotated[str, BeforeValidator(path_text), Field(description="Path to a migration revision file")]
RevisionId = Annotated[str, Field(description="Alembic revision identifier")]
SettingPattern = Annotated[str, Field(description="SQL ILIKE pattern for runtime setting names")]
SettingValue = Annotated[str, Field(description="PostgreSQL runtime setting value or metadata")]
LatencyMilliseconds = Annotated[FloatValue, Field(description="Database round-trip latency in milliseconds")]
PoolStatistic = Annotated[IntegerValue, Field(description="Connection-pool statistic")]
MaintenanceTarget = Annotated[str, Field(min_length=1, description="Schema, table, or index to maintain")]
GrantObject = Annotated[str, Field(min_length=1, description="Object receiving privilege changes")]
RoleConnectionLimit = Annotated[IntegerValue, Field(ge=-1, description="Role connection limit; -1 means unlimited")]


def validate_notification_bytes(value: ResultText) -> ResultText:
    if len(value.encode("utf-8")) > MAX_NOTIFICATION_PAYLOAD_BYTES:
        raise ValueError(f"Notification payloads must fit in {MAX_NOTIFICATION_PAYLOAD_BYTES} UTF-8 bytes")
    return value


NotificationPayload = Annotated[
    str,
    Field(max_length=MAX_NOTIFICATION_PAYLOAD_BYTES, pattern=r"^[^\x00]*$", description="PostgreSQL notification payload"),
    AfterValidator(validate_notification_bytes),
]
WaitTimeoutSeconds = Annotated[FloatValue, Field(gt=0, description="Notification wait timeout in seconds")]
LifecyclePolicyId = Annotated[IntegerValue, Field(description="Lifecycle policy identifier")]
LifecycleRunId = Annotated[IntegerValue, Field(description="Lifecycle execution record identifier")]
LifecycleBatchSize = Annotated[IntegerValue, Field(ge=1, le=100000, description="Maximum rows processed per lifecycle statement")]
CronExpression = Annotated[str, Field(description="pg_cron schedule expression")]
DatabaseInterval = Annotated[str, Field(description="Interval text reported by PostgreSQL")]
DatabaseRow = dict[ResultLabel, object]
RowInput = dict[ResultLabel, JsonValue]
QueryArguments = dict[QueryParameterName, JsonValue]
OperationDetail = dict[ResultLabel, object]
PoolStatistics = dict[ResultLabel, PoolStatistic]


def validate_revision_message(value: ResultText) -> ResultText:
    # Alembic embeds this value in the generated revision module's docstring.
    if '"""' in value or value.endswith("\\"):
        raise ValueError('message cannot contain """ or end with a backslash')
    return value


RevisionMessage = Annotated[str, Field(min_length=1, description="Migration revision message"), AfterValidator(validate_revision_message)]


RequestFieldName = Annotated[str, Field(min_length=1, description="Operation request field name")]
RequestValues = Mapping[RequestFieldName, object]
RolePasswordText = Annotated[str, Field(description="Password supplied to a PostgreSQL role statement")]
PasswordHash = Annotated[str, Field(description="Stored PostgreSQL role password hash")]
MigrationDirectory = Annotated[Path, Field(description="Directory containing an Alembic migration project")]
NotificationChannel = Annotated[str, Field(description="PostgreSQL notification channel")]
type NonEmptyItems[T] = Annotated[list[T], Field(min_length=1, description="Nonempty operation item sequence")]
NonEmptyRowInput = Annotated[RowInput, Field(min_length=1, description="Column values to update")]


def split_notification_channels(value: object) -> object:
    return [channel for channel in value.split(",") if channel] if isinstance(value, str) else value


NotificationChannels = Annotated[
    NonEmptyItems[Name],
    BeforeValidator(split_notification_channels),
    Field(description="PostgreSQL notification channels"),
]
