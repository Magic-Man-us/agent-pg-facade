from __future__ import annotations

import math
import re
from collections.abc import Mapping
from typing import Annotated, Literal, Self

from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, Field, Tag, ValidationError, computed_field, model_validator

from pgfacade.contracts.enums import (
    DatabaseErrorCategory,
    ErrorCode,
    ErrorDetailKind,
    ErrorReason,
    KnownValidationCode,
    Operation,
    Outcome,
    ValidationConstraintKind,
    ValidationContextKind,
    ValidationOrigin,
)
from pgfacade.shared.config import CONTRACT_CONFIG
from pgfacade.shared.types import (
    ErrorMessage,
    ErrorStatusCode,
    SqlState,
    ValidationConstraintValue,
    ValidationDiscriminator,
    ValidationIssueCode,
    ValidationLocation,
    ValidationTagNames,
)

VALIDATION_MESSAGES: dict[ValidationIssueCode, ErrorMessage] = {
    KnownValidationCode.INT_TYPE: "Expected an integer",
    KnownValidationCode.INT_PARSING: "Expected an integer",
    KnownValidationCode.INT_FROM_FLOAT: "Expected an integer without a fractional part",
    KnownValidationCode.FLOAT_TYPE: "Expected a number",
    KnownValidationCode.FLOAT_PARSING: "Expected a number",
    KnownValidationCode.BOOL_TYPE: "Expected a boolean",
    KnownValidationCode.BOOL_PARSING: "Expected a boolean",
    KnownValidationCode.STRING_TYPE: "Expected text",
    KnownValidationCode.STRING_PATTERN_MISMATCH: "Text does not match the declared format",
    KnownValidationCode.LIST_TYPE: "Expected a list",
    KnownValidationCode.TUPLE_TYPE: "Expected a sequence",
    KnownValidationCode.DICT_TYPE: "Expected an object",
    KnownValidationCode.MODEL_TYPE: "Expected an object",
    KnownValidationCode.FINITE_NUMBER: "Expected a finite number",
    KnownValidationCode.JSON_INVALID: "Invalid JSON syntax",
}
MAX_DISPLAY_TAGS = 6
TAG_LABEL_PATTERN = re.compile(r"'([A-Za-z0-9_][A-Za-z0-9_.:/-]*)'")
DISCRIMINATOR_PATTERN = re.compile(r"[A-Za-z_][A-Za-z0-9_.-]*\Z")


class ValidationBound(BaseModel):
    model_config = CONTRACT_CONFIG

    name: ValidationConstraintKind
    value: ValidationConstraintValue


class ValidationBoundsContext(BaseModel):
    model_config = CONTRACT_CONFIG

    kind: Literal[ValidationContextKind.BOUNDS] = ValidationContextKind.BOUNDS
    bounds: tuple[ValidationBound, ...]


class ValidationTagContext(BaseModel):
    model_config = CONTRACT_CONFIG

    kind: Literal[ValidationContextKind.TAG] = ValidationContextKind.TAG
    discriminator: ValidationDiscriminator | None = None
    expected_tags: ValidationTagNames


ValidationContext = Annotated[
    Annotated[ValidationTagContext, Tag(ValidationContextKind.TAG)] | Annotated[ValidationBoundsContext, Tag(ValidationContextKind.BOUNDS)],
    Field(discriminator="kind"),
]


def _validation_context(code: ValidationIssueCode, context: object) -> ValidationContext | None:
    if not isinstance(context, Mapping):
        return None
    if code in {
        KnownValidationCode.UNION_TAG_INVALID,
        KnownValidationCode.UNION_TAG_NOT_FOUND,
        KnownValidationCode.LITERAL_ERROR,
        KnownValidationCode.ENUM,
    }:
        expected = context.get("expected_tags", context.get("expected"))
        labels: tuple[str, ...] = ()
        if isinstance(expected, str):
            labels = tuple(dict.fromkeys(TAG_LABEL_PATTERN.findall(expected)))
        elif isinstance(expected, tuple | list) and all(isinstance(label, str) for label in expected):
            labels = tuple(expected)
        raw_discriminator = context.get("discriminator")
        discriminator = raw_discriminator.strip("'\"") if isinstance(raw_discriminator, str) else None
        if discriminator is not None and not DISCRIMINATOR_PATTERN.fullmatch(discriminator):
            discriminator = None
        if not labels and discriminator is None:
            return None
        return ValidationTagContext(discriminator=discriminator, expected_tags=labels)
    bounds = tuple(
        ValidationBound(name=name, value=value)
        for name in ValidationConstraintKind
        if isinstance(value := context.get(name), int | float)
        and not isinstance(value, bool)
        and (not isinstance(value, float) or math.isfinite(value))
    )
    return ValidationBoundsContext(bounds=bounds) if bounds else None


class ValidationIssue(BaseModel):
    model_config = CONTRACT_CONFIG

    path: ValidationLocation
    code: ValidationIssueCode
    context: ValidationContext | None = None

    @model_validator(mode="before")
    @classmethod
    def read_issue(cls, value: object) -> object:
        if not isinstance(value, Mapping):
            return value
        if "loc" not in value and "type" not in value:
            return {key: item for key, item in value.items() if key != "message"}
        code = value.get("type")
        context = _validation_context(code, value.get("ctx")) if isinstance(code, str) else None
        return {"path": value.get("loc", ()), "code": code, "context": context}

    @computed_field  # type: ignore[prop-decorator]
    @property
    def message(self) -> ErrorMessage:
        if isinstance(self.context, ValidationTagContext):
            choices = ", ".join(self.context.expected_tags[:MAX_DISPLAY_TAGS])
            if len(self.context.expected_tags) > MAX_DISPLAY_TAGS:
                choices += f", … ({len(self.context.expected_tags)} declared choices)"
            name = self.context.discriminator or "variant"
            suffix = f"; expected one of: {choices}" if choices else ""
            if self.code == KnownValidationCode.UNION_TAG_NOT_FOUND:
                message = f"Missing {name} tag{suffix}"
            elif self.code == KnownValidationCode.UNION_TAG_INVALID:
                message = f"Unknown {name} tag{suffix}"
            else:
                message = f"Expected one of: {choices}"
        elif isinstance(self.context, ValidationBoundsContext):
            bounds = ", ".join(f"{bound.name.value}={bound.value}" for bound in self.context.bounds)
            message = f"Value does not satisfy declared constraints: {bounds}"
        elif self.code == KnownValidationCode.MISSING:
            message = "Field is required"
        elif self.code == KnownValidationCode.EXTRA_FORBIDDEN:
            message = "Field is not accepted"
        elif self.code in {KnownValidationCode.UNION_TAG_INVALID, KnownValidationCode.UNION_TAG_NOT_FOUND}:
            message = "Unknown variant tag" if self.code == KnownValidationCode.UNION_TAG_INVALID else "Variant tag is required"
        else:
            message = VALIDATION_MESSAGES.get(self.code, "Invalid value")
        return message


class ValidationDetails(BaseModel):
    model_config = CONTRACT_CONFIG

    kind: Literal[ErrorDetailKind.VALIDATION] = ErrorDetailKind.VALIDATION
    origin: ValidationOrigin = ValidationOrigin.REQUEST
    issues: list[ValidationIssue]

    @model_validator(mode="before")
    @classmethod
    def read_error(cls, value: object) -> object:
        if isinstance(value, ValidationError):
            return {"issues": value.errors(include_url=False, include_context=True, include_input=False)}
        if isinstance(value, RequestValidationError):
            return {"issues": value.errors()}
        return value

    @classmethod
    def from_error(
        cls, error: ValidationError | RequestValidationError, origin: ValidationOrigin = ValidationOrigin.REQUEST
    ) -> ValidationDetails:
        details = cls.model_validate(error)
        return details.model_copy(update={"origin": origin})


class DatabaseDetails(BaseModel):
    model_config = CONTRACT_CONFIG

    kind: Literal[ErrorDetailKind.DATABASE] = ErrorDetailKind.DATABASE
    sqlstate: SqlState | None = None
    category: DatabaseErrorCategory


class AuthenticationDetails(BaseModel):
    model_config = CONTRACT_CONFIG

    kind: Literal[ErrorDetailKind.AUTHENTICATION] = ErrorDetailKind.AUTHENTICATION
    reason: ErrorReason


class AuthorizationDetails(BaseModel):
    model_config = CONTRACT_CONFIG

    kind: Literal[ErrorDetailKind.AUTHORIZATION] = ErrorDetailKind.AUTHORIZATION
    reason: ErrorReason


ErrorDetails = Annotated[
    Annotated[ValidationDetails, Tag(ErrorDetailKind.VALIDATION)]
    | Annotated[DatabaseDetails, Tag(ErrorDetailKind.DATABASE)]
    | Annotated[AuthenticationDetails, Tag(ErrorDetailKind.AUTHENTICATION)]
    | Annotated[AuthorizationDetails, Tag(ErrorDetailKind.AUTHORIZATION)],
    Field(discriminator="kind"),
]


class ApiError(BaseModel):
    model_config = CONTRACT_CONFIG

    code: ErrorCode
    reason: ErrorReason
    message: ErrorMessage
    status: ErrorStatusCode
    sqlstate: SqlState | None = None
    details: ErrorDetails | None = None

    @model_validator(mode="after")
    def consistent_reason(self) -> Self:
        if isinstance(self.details, AuthenticationDetails | AuthorizationDetails) and self.details.reason != self.reason:
            raise ValueError("Error reason does not match its diagnostic details")
        return self


class Success[T](BaseModel):
    model_config = CONTRACT_CONFIG

    status: Literal[Outcome.SUCCESS] = Outcome.SUCCESS
    data: T


class Failure(BaseModel):
    model_config = CONTRACT_CONFIG

    status: Literal[Outcome.ERROR] = Outcome.ERROR
    error: ApiError


class ResponseEnvelope[T](BaseModel):
    model_config = CONTRACT_CONFIG

    kind: Operation
    outcome: Annotated[
        Annotated[Success[T], Tag(Outcome.SUCCESS)] | Annotated[Failure, Tag(Outcome.ERROR)],
        Field(discriminator="status"),
    ]
