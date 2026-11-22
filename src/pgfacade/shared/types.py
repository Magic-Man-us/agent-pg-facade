from __future__ import annotations

from pathlib import Path
from typing import Annotated, Literal

from pydantic import BeforeValidator, Field, SecretStr

from pgfacade.contracts.enums import OperationHint as OperationHint
from pgfacade.shared.enums import McpTransport as McpTransport
from pgfacade.shared.enums import PermissionName as PermissionName


def reject_boolean_number(value: object) -> object:
    if isinstance(value, bool):
        raise ValueError("Boolean values are not numbers")
    return value


IntegerValue = Annotated[int, BeforeValidator(reject_boolean_number), Field(description="Integer numeric value")]
FloatValue = Annotated[
    float,
    BeforeValidator(reject_boolean_number),
    Field(allow_inf_nan=False, description="Finite floating-point value"),
]


SecurityFlag = Annotated[bool, Field(description="Whether a security capability is enabled")]
ApiKey = Annotated[str, Field(min_length=1, pattern=r"^\S+$", description="Nonempty bearer API credential without whitespace")]
RequestByteLimit = Annotated[IntegerValue, Field(ge=1, le=64 * 1024 * 1024, description="Maximum accepted HTTP request body bytes")]
RequestReadTimeout = Annotated[FloatValue, Field(gt=0, le=300, description="Seconds allowed to receive an HTTP request body")]

DEFAULT_REQUEST_BYTE_LIMIT = 1024 * 1024
DEFAULT_REQUEST_READ_TIMEOUT = 10.0

CredentialPath = Annotated[Path, Field(description="Path to a protected API key mapping")]
SettingName = Annotated[str, Field(min_length=1, description="Runtime configuration field name")]
SettingsValues = Annotated[dict[SettingName, object], Field(description="Raw values supplied by the settings sources")]

CommandArgument = Annotated[str, Field(max_length=32768, pattern=r"^[^\x00]*$", description="One literal subprocess argument")]
CommandArgv = Annotated[
    tuple[CommandArgument, ...], Field(min_length=1, max_length=128, description="Operator-configured executable and arguments")
]
ReadyMarker = Annotated[
    str,
    Field(min_length=1, max_length=128, pattern=r"^\S(?:[^\r\n]*\S)?$", description="Complete output line signaling subprocess readiness"),
]
StartupTimeoutSeconds = Annotated[FloatValue, Field(gt=0, le=3600, description="Deadline for startup readiness in seconds")]
StopTimeoutSeconds = Annotated[FloatValue, Field(gt=0, le=60, description="Grace period for subprocess termination in seconds")]

ErrorMessage = Annotated[str, Field(min_length=1, description="Public description of an API failure")]
HttpStatusCode = Annotated[IntegerValue, Field(ge=100, le=599, description="HTTP-equivalent status of an API failure")]
SqlState = Annotated[str, Field(pattern=r"^[0-9A-Z]{5}$", description="PostgreSQL SQLSTATE code")]

ErrorStatusCode = Annotated[IntegerValue, Field(ge=400, le=599, description="HTTP-equivalent error status")]

CommandArguments = list[CommandArgument]
McpHttpTransport = Annotated[
    Literal[McpTransport.HTTP, McpTransport.STREAMABLE_HTTP, McpTransport.SSE], Field(description="MCP HTTP transport mode")
]
McpCliTransport = Annotated[Literal[McpTransport.STDIO, McpTransport.HTTP, McpTransport.SSE], Field(description="MCP CLI transport mode")]

PermissionValues = tuple[SecurityFlag, ...]
PermissionFlags = dict[PermissionName, SecurityFlag]
OperationArea = Annotated[str, Field(description="Operation catalog resource area")]
OperationAction = Annotated[str, Field(description="Operation catalog action")]
OperationSummary = Annotated[str, Field(description="Operation catalog summary")]
OperationTag = Annotated[str, Field(description="Operation catalog tag")]


ValidationIssueCode = Annotated[str, Field(min_length=1, description="Machine-readable validation error type")]
ValidationLocation = tuple[str | int, ...]
HttpRoutePath = Annotated[str, Field(min_length=1, description="HTTP application route path")]
HttpHeaderName = Annotated[str, Field(min_length=1, description="HTTP header name")]
HttpHeaderValue = Annotated[str, Field(description="HTTP header value")]
HttpHeaders = dict[HttpHeaderName, HttpHeaderValue]
ErrorResponseMetadata = dict[str, object]
McpLifespanState = dict[str, object]
EventChannelList = Annotated[str, Field(description="Comma-separated notification channels")]
HeartbeatSeconds = Annotated[FloatValue, Field(gt=0, description="Notification heartbeat interval in seconds")]
EventStreamChunk = Annotated[bytes, Field(description="Encoded notification event stream chunk")]

PrincipalName = Annotated[str, Field(min_length=1, max_length=255, description="Caller label used in audit output")]
PrincipalRole = Annotated[str, Field(min_length=1, max_length=63, pattern=r"^[^\x00]+$", description="PostgreSQL role used for one caller")]
DefaultSchema = Annotated[str, Field(min_length=1, max_length=63, pattern=r"^[^\x00]+$", description="Default PostgreSQL schema")]
ApplicationName = Annotated[str, Field(min_length=1, max_length=128, description="PostgreSQL connection application name")]
PoolMinimum = Annotated[IntegerValue, Field(ge=0, description="Minimum pooled database connections")]
PoolMaximum = Annotated[IntegerValue, Field(ge=1, description="Maximum pooled database connections")]
PoolTimeoutSeconds = Annotated[FloatValue, Field(gt=0, description="Database connection acquisition timeout in seconds")]
StatementTimeoutMilliseconds = Annotated[IntegerValue, Field(ge=0, description="Statement timeout in milliseconds; zero disables")]
LockTimeoutMilliseconds = Annotated[IntegerValue, Field(ge=0, description="Lock timeout in milliseconds; zero disables")]
SchemaCacheTtlSeconds = Annotated[FloatValue, Field(ge=0, description="Schema metadata cache lifetime in seconds")]
ReadRowLimit = Annotated[IntegerValue, Field(ge=1, description="Maximum rows returned by one read")]
ExportRowLimit = Annotated[IntegerValue, Field(ge=1, description="Maximum rows written by one CSV export")]
EventWaitSeconds = Annotated[FloatValue, Field(gt=0, description="Maximum notification wait in seconds")]
MigrationsDirectory = Annotated[Path, Field(description="Directory containing Alembic migrations")]
QueriesDirectory = Annotated[Path, Field(description="Directory containing SQL query definitions")]
LifecycleSweepSeconds = Annotated[FloatValue, Field(ge=0, description="Lifecycle sweep interval in seconds; zero disables")]
LifecycleChannel = Annotated[
    str, Field(min_length=1, max_length=63, pattern=r"^[^\x00]+$", description="PostgreSQL lifecycle notification channel")
]
ServerHost = Annotated[str, Field(min_length=1, max_length=2048, description="Application server bind address")]
ServerPort = Annotated[IntegerValue, Field(ge=1, le=65535, description="Application server listen port")]
GeneratedCredentialBytes = Annotated[IntegerValue, Field(ge=1, description="Bytes of entropy in a generated API credential")]


type CredentialMap[Principal] = dict[ApiKey, Principal]
RequestBodyBytes = Annotated[bytes, Field(description="Complete buffered HTTP request body")]
DEFAULT_API_KEY_ENTROPY_BYTES = 32


DatabaseConnectionString = Annotated[str, Field(min_length=1, description="PostgreSQL driver connection string")]
SqlAlchemyUrl = Annotated[str, Field(min_length=1, description="SQLAlchemy database connection URL")]

McpCredential = Annotated[SecretStr, Field(min_length=1, description="API credential used by the MCP stdio session")]


ValidationDiscriminator = Annotated[
    str, Field(min_length=1, max_length=128, pattern=r"^[A-Za-z_][A-Za-z0-9_.-]*$", description="Validated discriminator name")
]
ValidationTagName = Annotated[
    str, Field(min_length=1, max_length=256, pattern=r"^[A-Za-z0-9_][A-Za-z0-9_.:/-]*$", description="Declared discriminator choice")
]
ValidationTagNames = Annotated[tuple[ValidationTagName, ...], Field(max_length=256)]
ValidationConstraintValue = Annotated[
    Annotated[int, Field(strict=True)] | Annotated[float, Field(strict=True, allow_inf_nan=False)],
    Field(description="Finite declared numeric validation constraint"),
]
