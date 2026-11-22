"""Application exceptions and one mapping from any error to an HTTP status and payload."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from http import HTTPStatus

import psycopg
from fastapi.exceptions import RequestValidationError
from pydantic import ValidationError
from starlette.exceptions import HTTPException

from pgfacade.contracts.enums import DatabaseErrorCategory, ErrorCode, ErrorReason, ValidationOrigin
from pgfacade.contracts.envelopes import (
    ApiError,
    AuthenticationDetails,
    AuthorizationDetails,
    DatabaseDetails,
    ErrorDetails,
    Failure,
    ValidationDetails,
)
from pgfacade.shared.types import ErrorMessage, HttpStatusCode, SqlState

log = logging.getLogger("pgfacade")


class PgFacadeError(Exception):
    status: HttpStatusCode = HTTPStatus.BAD_REQUEST
    reason: ErrorReason = ErrorReason.REQUEST_INVALID


class InvalidRequest(PgFacadeError):
    status = HTTPStatus.BAD_REQUEST


class RequestValidationFailure(InvalidRequest):
    status = HTTPStatus.UNPROCESSABLE_ENTITY
    reason = ErrorReason.INPUT_INVALID

    def __init__(self, error: ValidationError, message: ErrorMessage = "Request validation failed") -> None:
        super().__init__(message)
        self.error = error


class Unauthenticated(PgFacadeError):
    status = HTTPStatus.UNAUTHORIZED
    reason = ErrorReason.CREDENTIAL_INVALID


class MissingCredential(Unauthenticated):
    reason = ErrorReason.CREDENTIAL_MISSING


class InvalidCredential(Unauthenticated):
    reason = ErrorReason.CREDENTIAL_INVALID


class AuthenticationNotConfigured(PgFacadeError):
    status = HTTPStatus.SERVICE_UNAVAILABLE
    reason = ErrorReason.AUTHENTICATION_UNCONFIGURED


class IdentityProviderNotConfigured(PgFacadeError):
    status = HTTPStatus.SERVICE_UNAVAILABLE
    reason = ErrorReason.IDENTITY_PROVIDER_UNCONFIGURED


class IdentityProviderInvalidResponse(PgFacadeError):
    status = HTTPStatus.BAD_GATEWAY
    reason = ErrorReason.IDENTITY_PROVIDER_INVALID_RESPONSE


class IdentityProviderUnavailable(PgFacadeError):
    status = HTTPStatus.SERVICE_UNAVAILABLE
    reason = ErrorReason.IDENTITY_PROVIDER_UNAVAILABLE


class Forbidden(PgFacadeError):
    status = HTTPStatus.FORBIDDEN
    reason = ErrorReason.POLICY_DENIED


class NoMatchingPolicy(Forbidden):
    reason = ErrorReason.POLICY_NO_MATCH


class AmbiguousExecutionIdentity(Forbidden):
    reason = ErrorReason.IDENTITY_AMBIGUOUS


class NotFound(PgFacadeError):
    status = HTTPStatus.NOT_FOUND
    reason = ErrorReason.RESOURCE_NOT_FOUND


class Timeout(PgFacadeError):
    status = HTTPStatus.REQUEST_TIMEOUT
    reason = ErrorReason.REQUEST_TIMEOUT


_AUTHENTICATION_REASONS = frozenset(
    {
        ErrorReason.CREDENTIAL_MISSING,
        ErrorReason.CREDENTIAL_INVALID,
        ErrorReason.AUTHENTICATION_UNCONFIGURED,
        ErrorReason.IDENTITY_PROVIDER_UNCONFIGURED,
        ErrorReason.IDENTITY_PROVIDER_INVALID_RESPONSE,
        ErrorReason.IDENTITY_PROVIDER_UNAVAILABLE,
    }
)


@dataclass(frozen=True, slots=True)
class _ErrorInfo:
    status: HttpStatusCode
    code: ErrorCode
    reason: ErrorReason
    message: ErrorMessage
    sqlstate: SqlState | None = None
    details: ErrorDetails | None = None


def _http_error(
    status: HttpStatusCode,
    message: ErrorMessage,
    *,
    reason: ErrorReason | None = None,
    sqlstate: SqlState | None = None,
    details: ErrorDetails | None = None,
) -> _ErrorInfo:
    match status:
        case HTTPStatus.BAD_REQUEST:
            code, default_reason = ErrorCode.INVALID_REQUEST, ErrorReason.REQUEST_INVALID
        case HTTPStatus.UNAUTHORIZED:
            code, default_reason = ErrorCode.UNAUTHENTICATED, ErrorReason.CREDENTIAL_INVALID
        case HTTPStatus.FORBIDDEN:
            code, default_reason = ErrorCode.FORBIDDEN, ErrorReason.POLICY_DENIED
        case HTTPStatus.NOT_FOUND:
            code, default_reason = ErrorCode.NOT_FOUND, ErrorReason.RESOURCE_NOT_FOUND
        case HTTPStatus.METHOD_NOT_ALLOWED:
            code, default_reason = ErrorCode.METHOD_NOT_ALLOWED, ErrorReason.METHOD_NOT_ALLOWED
        case HTTPStatus.REQUEST_TIMEOUT:
            code, default_reason = ErrorCode.TIMEOUT, ErrorReason.REQUEST_TIMEOUT
        case HTTPStatus.CONFLICT:
            code, default_reason = ErrorCode.CONFLICT, ErrorReason.REQUEST_INVALID
        case HTTPStatus.REQUEST_ENTITY_TOO_LARGE:
            code, default_reason = ErrorCode.REQUEST_TOO_LARGE, ErrorReason.REQUEST_TOO_LARGE
        case HTTPStatus.UNPROCESSABLE_ENTITY:
            code, default_reason = ErrorCode.VALIDATION_ERROR, ErrorReason.INPUT_INVALID
        case HTTPStatus.BAD_GATEWAY | HTTPStatus.SERVICE_UNAVAILABLE:
            code, default_reason = ErrorCode.UNAVAILABLE, ErrorReason.UNEXPECTED_FAILURE
        case _:
            code, default_reason = ErrorCode.INTERNAL_ERROR, ErrorReason.UNEXPECTED_FAILURE
    return _ErrorInfo(status, code, reason if reason is not None else default_reason, message, sqlstate, details)


def _database_error(exc: psycopg.Error) -> _ErrorInfo:
    state = exc.sqlstate
    if state in {"23505", "23503", "23P01", "42710", "42P04", "42P06", "42P07", "40001", "40P01", "55P03", "2BP01"}:
        status, category, reason = HTTPStatus.CONFLICT, DatabaseErrorCategory.CONFLICT, ErrorReason.DATABASE_CONFLICT
    elif state in {"23502", "23514"} or (state is not None and state.startswith("22")):
        status, category, reason = (
            HTTPStatus.UNPROCESSABLE_ENTITY,
            DatabaseErrorCategory.CONSTRAINT,
            ErrorReason.DATABASE_CONSTRAINT_VIOLATION,
        )
    elif state in {"42P01", "42704", "42703", "3F000"}:
        status, category, reason = HTTPStatus.NOT_FOUND, DatabaseErrorCategory.NOT_FOUND, ErrorReason.DATABASE_RESOURCE_NOT_FOUND
    elif state in {"42501", "25006"}:
        status, category, reason = HTTPStatus.FORBIDDEN, DatabaseErrorCategory.PERMISSION, ErrorReason.DATABASE_PERMISSION_DENIED
    elif state == "57014":
        status, category, reason = HTTPStatus.REQUEST_TIMEOUT, DatabaseErrorCategory.TIMEOUT, ErrorReason.DATABASE_TIMEOUT
    elif state is None or state.startswith(("08", "53", "57P")):
        status, category, reason = HTTPStatus.SERVICE_UNAVAILABLE, DatabaseErrorCategory.UNAVAILABLE, ErrorReason.DATABASE_UNAVAILABLE
    else:
        status = HTTPStatus.INTERNAL_SERVER_ERROR if state.startswith("XX") else HTTPStatus.BAD_REQUEST
        category, reason = DatabaseErrorCategory.FAILURE, ErrorReason.DATABASE_FAILURE
    return _http_error(
        status, "Database request failed", reason=reason, sqlstate=state, details=DatabaseDetails(sqlstate=state, category=category)
    )


def _classify_error(exc: BaseException) -> _ErrorInfo:
    if isinstance(exc, RequestValidationError | RequestValidationFailure):
        error = exc.error if isinstance(exc, RequestValidationFailure) else exc
        return _http_error(HTTPStatus.UNPROCESSABLE_ENTITY, "Request validation failed", details=ValidationDetails.from_error(error))
    if isinstance(exc, ValidationError):
        return _http_error(
            HTTPStatus.INTERNAL_SERVER_ERROR,
            "Internal server error",
            reason=ErrorReason.RESPONSE_INVALID,
            details=ValidationDetails.from_error(exc, ValidationOrigin.RESPONSE),
        )
    if isinstance(exc, PgFacadeError):
        details: ErrorDetails | None = None
        if exc.reason in _AUTHENTICATION_REASONS:
            details = AuthenticationDetails(reason=exc.reason)
        elif isinstance(exc, Forbidden):
            details = AuthorizationDetails(reason=exc.reason)
        return _http_error(exc.status, str(exc) or HTTPStatus(exc.status).phrase, reason=exc.reason, details=details)
    if isinstance(exc, psycopg.Error):
        return _database_error(exc)
    if isinstance(exc, HTTPException):
        message = HTTPStatus(exc.status_code).phrase if exc.status_code in HTTPStatus else "HTTP request failed"
        return _http_error(exc.status_code, message)
    return _http_error(HTTPStatus.INTERNAL_SERVER_ERROR, "Internal server error")


def _render_error(info: _ErrorInfo) -> Failure:
    return Failure(
        error=ApiError(
            code=info.code, reason=info.reason, message=info.message, status=info.status, sqlstate=info.sqlstate, details=info.details
        )
    )


def failure(status: HttpStatusCode, message: ErrorMessage) -> Failure:
    return _render_error(_http_error(status, message))


def error_payload(exc: BaseException) -> Failure:
    info = _classify_error(exc)
    if info.status >= HTTPStatus.INTERNAL_SERVER_ERROR:
        log.error("Request failed: %s", info.reason, exc_info=exc)
    return _render_error(info)
