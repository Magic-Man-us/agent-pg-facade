from __future__ import annotations

import logging

import psycopg
import pytest
from fastapi.exceptions import RequestValidationError
from pydantic import ValidationError

from pgfacade.application.errors import Forbidden, RequestValidationFailure, error_payload
from pgfacade.contracts.admin import ServerInfo
from pgfacade.contracts.enums import DatabaseErrorCategory, ErrorReason, ValidationOrigin
from pgfacade.contracts.envelopes import DatabaseDetails, Failure, ValidationDetails


def invalid_database_result() -> ValidationError:
    with pytest.raises(ValidationError) as captured:
        ServerInfo.model_validate({"server_version": "synthetic-private-database-value"})
    return captured.value


def test_database_validation_is_a_redacted_internal_error() -> None:
    failure = error_payload(invalid_database_result())
    assert failure.error.status == 500
    assert failure.error.code == "internal_error"
    assert failure.error.message == "Internal server error"
    assert failure.error.reason is ErrorReason.RESPONSE_INVALID
    assert isinstance(failure.error.details, ValidationDetails)
    assert failure.error.details.origin is ValidationOrigin.RESPONSE
    assert "synthetic-private-database-value" not in failure.model_dump_json()
    assert Failure.model_validate_json(failure.model_dump_json()) == failure


def test_explicit_input_validation_exposes_only_issue_paths_and_codes() -> None:
    error = invalid_database_result()
    failure = error_payload(RequestValidationFailure(error))
    assert failure.error.status == 422
    assert failure.error.code == "validation_error"
    assert isinstance(failure.error.details, ValidationDetails)
    assert failure.error.details.origin is ValidationOrigin.REQUEST
    assert failure.error.details.issues[0].path == ("version",)
    assert failure.error.details.issues[0].code == "missing"
    assert set(failure.error.details.issues[0].model_dump()) == {"path", "code", "context", "message"}
    assert failure.error.details.issues[0].message == "Field is required"
    assert "synthetic-private-database-value" not in failure.model_dump_json()


def test_fastapi_validation_discards_message_input_and_context() -> None:
    error = RequestValidationError(
        [
            {
                "loc": ("body", "request", "limit"),
                "type": "int_parsing",
                "msg": "synthetic-private-value",
                "input": "synthetic-private-value",
                "ctx": {"value": "synthetic-private-value"},
            }
        ]
    )
    failure = error_payload(error)
    assert failure.error.status == 422
    assert isinstance(failure.error.details, ValidationDetails)
    assert failure.error.details.issues[0].path == ("body", "request", "limit")
    assert failure.error.details.issues[0].code == "int_parsing"
    assert "synthetic-private-value" not in failure.model_dump_json()


def test_database_errors_keep_sqlstate_without_database_detail() -> None:
    failure = error_payload(psycopg.errors.UniqueViolation("synthetic-private-sql-value"))
    assert failure.error.status == 409
    assert failure.error.sqlstate == "23505"
    assert isinstance(failure.error.details, DatabaseDetails)
    assert failure.error.details.category is DatabaseErrorCategory.CONFLICT
    assert failure.error.reason is ErrorReason.DATABASE_CONFLICT
    assert "synthetic-private-sql-value" not in failure.model_dump_json()


@pytest.mark.parametrize(
    "error",
    [RuntimeError("synthetic fault"), psycopg.OperationalError("synthetic outage")],
    ids=["unexpected", "database-unavailable"],
)
def test_server_failures_are_logged_with_their_traceback(error: Exception, caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.DEBUG, logger="pgfacade"):
        failure = error_payload(error)
    assert failure.error.status >= 500
    assert [(record.levelno, record.exc_info and record.exc_info[1]) for record in caplog.records] == [(logging.ERROR, error)]
    assert failure.error.reason in caplog.records[0].getMessage()


@pytest.mark.parametrize(
    "error",
    [Forbidden("Denied"), psycopg.errors.UniqueViolation("synthetic conflict")],
    ids=["forbidden", "database-conflict"],
)
def test_caller_failures_are_not_logged(error: Exception, caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.DEBUG, logger="pgfacade"):
        failure = error_payload(error)
    assert failure.error.status < 500
    assert not caplog.records
