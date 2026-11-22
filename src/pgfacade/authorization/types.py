from __future__ import annotations

from typing import Annotated

from pydantic import AfterValidator, Field, SecretStr, TypeAdapter, ValidationError

from pgfacade.shared.types import ApiKey, IntegerValue

SubjectId = Annotated[str, Field(min_length=1, max_length=255, pattern=r"^\S+$", description="Stable identity subject identifier")]
GroupId = Annotated[str, Field(min_length=1, max_length=255, pattern=r"^\S+$", description="Verified provider group identifier")]
IdentityName = Annotated[str, Field(min_length=1, max_length=128, pattern=r"^[^\r\n]+$", description="Identity display label")]
IdentityIssuer = Annotated[str, Field(min_length=1, max_length=128, pattern=r"^\S+$", description="Identity provider namespace")]
ConnectorId = Annotated[
    str, Field(min_length=1, max_length=63, pattern=r"^[A-Za-z_][A-Za-z0-9_-]*$", description="Configured connector identifier")
]
ExecutionIdentityId = Annotated[
    str, Field(min_length=1, max_length=63, pattern=r"^[A-Za-z_][A-Za-z0-9_-]*$", description="Configured database execution profile")
]
DatabaseRole = Annotated[
    str, Field(min_length=1, max_length=63, pattern=r"^[A-Za-z_][A-Za-z0-9_]*$", description="PostgreSQL execution role")
]
DatabaseIdentifier = Annotated[
    str, Field(min_length=1, max_length=63, pattern=r"^[A-Za-z_][A-Za-z0-9_]*$", description="Policy-supported PostgreSQL identifier")
]
PolicyId = Annotated[
    str, Field(min_length=1, max_length=128, pattern=r"^[A-Za-z_][A-Za-z0-9_-]*$", description="Stable authorization policy identifier")
]
OperationPattern = Annotated[
    str,
    Field(
        min_length=1,
        max_length=128,
        pattern=r"^(\*|[a-z][a-z0-9_]*\.(\*|[a-z][a-z0-9_]*))$",
        description="Operation name, area wildcard, or global wildcard",
    ),
]
ResourceName = Annotated[
    str,
    Field(
        min_length=1,
        max_length=127,
        pattern=r"^(@connector|[A-Za-z_][A-Za-z0-9_]{0,62}\.[A-Za-z_][A-Za-z0-9_]{0,62})$",
        description="Canonical table or connector resource",
    ),
]
ResourcePattern = Annotated[
    str,
    Field(
        min_length=1,
        max_length=127,
        pattern=r"^(\*|@connector|[A-Za-z_][A-Za-z0-9_]{0,62}\.(\*|[A-Za-z_][A-Za-z0-9_]{0,62}))$",
        description="Canonical table, schema wildcard, connector, or global wildcard",
    ),
]
PolicyPriority = Annotated[
    IntegerValue, Field(ge=0, le=10000, description="Allow-policy precedence; ties between different profiles are denied")
]
BatchOperationLimit = Annotated[IntegerValue, Field(ge=1, le=1000, description="Maximum operations per group-authorized batch")]
AuthorizationFlag = Annotated[bool, Field(description="Authorization decision flag")]
MockCredential = Annotated[SecretStr, Field(min_length=1, description="Synthetic local bearer credential")]
_MOCK_TOKEN_ADAPTER = TypeAdapter(ApiKey)


def _validate_mock_token(value: MockCredential) -> MockCredential:
    try:
        _MOCK_TOKEN_ADAPTER.validate_python(value.get_secret_value())
    except ValidationError:
        raise ValueError("Mock credentials must be nonempty and contain no whitespace") from None
    return value


MockToken = Annotated[MockCredential, AfterValidator(_validate_mock_token)]


IdentityGroups = Annotated[frozenset[GroupId], Field(description="Verified identity group memberships")]
PolicyGroups = Annotated[frozenset[GroupId], Field(min_length=1, description="Groups matched by one authorization policy")]
PolicyOperations = Annotated[tuple[OperationPattern, ...], Field(min_length=1, description="Operation patterns matched by one policy")]
PolicyResources = Annotated[tuple[ResourcePattern, ...], Field(min_length=1, description="Resource patterns matched by one policy")]
MatchedPolicies = tuple[PolicyId, ...]
