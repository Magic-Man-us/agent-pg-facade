from __future__ import annotations

from enum import StrEnum
from http import HTTPStatus
from typing import Annotated, Literal

import psycopg
import pytest
from pydantic import BaseModel, Field, ValidationError, field_validator
from pydantic_core import PydanticCustomError
from starlette.exceptions import HTTPException

from pgfacade.application.errors import (
    AmbiguousExecutionIdentity,
    AuthenticationNotConfigured,
    IdentityProviderInvalidResponse,
    IdentityProviderNotConfigured,
    IdentityProviderUnavailable,
    InvalidCredential,
    MissingCredential,
    NoMatchingPolicy,
    PgFacadeError,
    RequestValidationFailure,
    error_payload,
)
from pgfacade.contracts.enums import DatabaseErrorCategory, ErrorCode, ErrorDetailKind, ErrorReason, ValidationConstraintKind
from pgfacade.contracts.envelopes import (
    AuthenticationDetails,
    AuthorizationDetails,
    DatabaseDetails,
    Failure,
    ValidationBoundsContext,
    ValidationDetails,
    ValidationTagContext,
)

PRIVATE_VALUE = "synthetic-private-credential-or-sql-value"


@pytest.mark.parametrize(
    ("exception", "status", "reason"),
    [
        (MissingCredential, 401, ErrorReason.CREDENTIAL_MISSING),
        (InvalidCredential, 401, ErrorReason.CREDENTIAL_INVALID),
        (AuthenticationNotConfigured, 503, ErrorReason.AUTHENTICATION_UNCONFIGURED),
        (IdentityProviderNotConfigured, 503, ErrorReason.IDENTITY_PROVIDER_UNCONFIGURED),
        (IdentityProviderInvalidResponse, 502, ErrorReason.IDENTITY_PROVIDER_INVALID_RESPONSE),
        (IdentityProviderUnavailable, 503, ErrorReason.IDENTITY_PROVIDER_UNAVAILABLE),
        (NoMatchingPolicy, 403, ErrorReason.POLICY_NO_MATCH),
        (AmbiguousExecutionIdentity, 403, ErrorReason.IDENTITY_AMBIGUOUS),
    ],
)
def test_named_failures_preserve_machine_readable_reason(exception: type[PgFacadeError], status: int, reason: ErrorReason) -> None:
    failure = error_payload(exception("Controlled application message"))
    assert failure.error.status == status
    assert failure.error.reason is reason
    assert isinstance(failure.error.details, AuthorizationDetails if status == 403 else AuthenticationDetails)
    assert failure.error.details.reason is reason
    assert Failure.model_validate_json(failure.model_dump_json()) == failure
    if status in {502, 503}:
        assert failure.error.code is ErrorCode.UNAVAILABLE


@pytest.mark.parametrize("error", [RuntimeError(PRIVATE_VALUE), HTTPException(HTTPStatus.INTERNAL_SERVER_ERROR, PRIVATE_VALUE)])
def test_unexpected_and_http_details_are_redacted(error: Exception) -> None:
    failure = error_payload(error)
    assert failure.error.reason is ErrorReason.UNEXPECTED_FAILURE
    assert PRIVATE_VALUE not in failure.model_dump_json()


@pytest.mark.parametrize(
    ("error", "category", "reason"),
    [
        (psycopg.errors.CheckViolation(PRIVATE_VALUE), DatabaseErrorCategory.CONSTRAINT, ErrorReason.DATABASE_CONSTRAINT_VIOLATION),
        (psycopg.errors.UndefinedTable(PRIVATE_VALUE), DatabaseErrorCategory.NOT_FOUND, ErrorReason.DATABASE_RESOURCE_NOT_FOUND),
        (psycopg.errors.InsufficientPrivilege(PRIVATE_VALUE), DatabaseErrorCategory.PERMISSION, ErrorReason.DATABASE_PERMISSION_DENIED),
        (psycopg.errors.QueryCanceled(PRIVATE_VALUE), DatabaseErrorCategory.TIMEOUT, ErrorReason.DATABASE_TIMEOUT),
        (psycopg.OperationalError(PRIVATE_VALUE), DatabaseErrorCategory.UNAVAILABLE, ErrorReason.DATABASE_UNAVAILABLE),
    ],
)
def test_database_categories_do_not_expose_driver_messages(
    error: psycopg.Error, category: DatabaseErrorCategory, reason: ErrorReason
) -> None:
    failure = error_payload(error)
    assert failure.error.reason is reason
    assert isinstance(failure.error.details, DatabaseDetails)
    assert failure.error.details.category is category
    assert failure.error.details.sqlstate == error.sqlstate
    assert PRIVATE_VALUE not in failure.model_dump_json()


class BoundedInput(BaseModel):
    count: Annotated[int, Field(ge=2, le=5)]
    name: Annotated[str, Field(max_length=3)]


class FixtureVariant(StrEnum):
    FIRST = "first"
    SECOND = "second"


class FirstInput(BaseModel):
    kind: Literal[FixtureVariant.FIRST]


class SecondInput(BaseModel):
    kind: Literal[FixtureVariant.SECOND]


class TaggedInput(BaseModel):
    item: Annotated[FirstInput | SecondInput, Field(discriminator="kind")]


class CustomInput(BaseModel):
    value: str

    @field_validator("value")
    @classmethod
    def reject_value(cls, value: str) -> str:
        raise PydanticCustomError("external_custom_code", PRIVATE_VALUE, {"error": PRIVATE_VALUE})


def test_declared_bounds_are_typed_without_rejected_values() -> None:
    with pytest.raises(ValidationError) as captured:
        BoundedInput.model_validate({"count": 1, "name": PRIVATE_VALUE})
    failure = error_payload(RequestValidationFailure(captured.value))
    assert isinstance(failure.error.details, ValidationDetails)
    issues = failure.error.details.issues
    assert isinstance(issues[0].context, ValidationBoundsContext)
    assert issues[0].context.bounds[0].name is ValidationConstraintKind.GE
    assert issues[0].context.bounds[0].value == 2
    assert isinstance(issues[1].context, ValidationBoundsContext)
    assert issues[1].context.bounds[0].name is ValidationConstraintKind.MAX_LENGTH
    assert "ge=2" in issues[0].message
    assert PRIVATE_VALUE not in failure.model_dump_json()


@pytest.mark.parametrize("item", [{"kind": PRIVATE_VALUE}, {}])
def test_tag_errors_expose_only_declared_choices(item: dict[str, str]) -> None:
    with pytest.raises(ValidationError) as captured:
        TaggedInput.model_validate({"item": item})
    failure = error_payload(RequestValidationFailure(captured.value))
    assert isinstance(failure.error.details, ValidationDetails)
    issue = failure.error.details.issues[0]
    assert issue.path == ("item",)
    assert isinstance(issue.context, ValidationTagContext)
    assert issue.context.discriminator == "kind"
    if item:
        assert issue.context.expected_tags == ("first", "second")
        assert "first, second" in issue.message
    else:
        assert issue.context.expected_tags == ()
        assert issue.message == "Missing kind tag"
    assert PRIVATE_VALUE not in failure.model_dump_json()
    assert Failure.model_validate_json(failure.model_dump_json()) == failure


def test_open_custom_validation_codes_retain_no_raw_message_or_context() -> None:
    with pytest.raises(ValidationError) as captured:
        CustomInput.model_validate({"value": PRIVATE_VALUE})
    failure = error_payload(RequestValidationFailure(captured.value))
    assert isinstance(failure.error.details, ValidationDetails)
    issue = failure.error.details.issues[0]
    assert issue.code == "external_custom_code"
    assert issue.message == "Invalid value"
    assert issue.context is None
    assert PRIVATE_VALUE not in failure.model_dump_json()


def test_error_schema_documents_discriminated_diagnostics() -> None:
    schema = Failure.model_json_schema()
    details = schema["$defs"]["ApiError"]["properties"]["details"]["anyOf"][0]
    assert details["discriminator"]["propertyName"] == "kind"
    assert set(details["discriminator"]["mapping"]) == {kind.value for kind in ErrorDetailKind}
