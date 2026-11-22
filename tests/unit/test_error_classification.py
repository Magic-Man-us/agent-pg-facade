from __future__ import annotations

import psycopg
import pytest
from fastapi.testclient import TestClient
from starlette.exceptions import HTTPException

from pgfacade import PgSettings, Principal
from pgfacade.application.errors import Forbidden, error_payload
from pgfacade.contracts.enums import DatabaseErrorCategory, ErrorCode, ErrorReason
from pgfacade.contracts.envelopes import DatabaseDetails, Failure
from pgfacade.webapp import create_app


@pytest.mark.parametrize(
    ("states", "status", "code", "category", "reason"),
    [
        (
            ("23505", "23503", "23P01", "42710", "42P04", "42P06", "42P07", "40001", "40P01", "55P03", "2BP01"),
            409,
            ErrorCode.CONFLICT,
            DatabaseErrorCategory.CONFLICT,
            ErrorReason.DATABASE_CONFLICT,
        ),
        (
            ("23502", "23514", "22001"),
            422,
            ErrorCode.VALIDATION_ERROR,
            DatabaseErrorCategory.CONSTRAINT,
            ErrorReason.DATABASE_CONSTRAINT_VIOLATION,
        ),
        (
            ("42P01", "42704", "42703", "3F000"),
            404,
            ErrorCode.NOT_FOUND,
            DatabaseErrorCategory.NOT_FOUND,
            ErrorReason.DATABASE_RESOURCE_NOT_FOUND,
        ),
        (("42501", "25006"), 403, ErrorCode.FORBIDDEN, DatabaseErrorCategory.PERMISSION, ErrorReason.DATABASE_PERMISSION_DENIED),
        (("57014",), 408, ErrorCode.TIMEOUT, DatabaseErrorCategory.TIMEOUT, ErrorReason.DATABASE_TIMEOUT),
        (
            (None, "08006", "53300", "57P01"),
            503,
            ErrorCode.UNAVAILABLE,
            DatabaseErrorCategory.UNAVAILABLE,
            ErrorReason.DATABASE_UNAVAILABLE,
        ),
        (("XX000",), 500, ErrorCode.INTERNAL_ERROR, DatabaseErrorCategory.FAILURE, ErrorReason.DATABASE_FAILURE),
        (("42601",), 400, ErrorCode.INVALID_REQUEST, DatabaseErrorCategory.FAILURE, ErrorReason.DATABASE_FAILURE),
    ],
)
def test_sqlstate_policy_preserves_status_code_reason_and_details(
    states: tuple[str | None, ...], status: int, code: ErrorCode, category: DatabaseErrorCategory, reason: ErrorReason
) -> None:
    for state in states:
        error = type("DatabaseFixtureError", (psycopg.Error,), {"sqlstate": state})("private SQL and driver diagnostics")
        failure = error_payload(error)
        assert failure.error.status == status
        assert failure.error.code is code
        assert failure.error.reason is reason
        assert failure.error.sqlstate == state
        assert isinstance(failure.error.details, DatabaseDetails)
        assert failure.error.details.category is category
        assert failure.error.details.sqlstate == state
        assert "private SQL" not in failure.model_dump_json()
        assert Failure.model_validate_json(failure.model_dump_json()) == failure


@pytest.mark.parametrize("status", [400, 401, 403, 404, 405, 408, 409, 413, 422, 429, 499, 500, 502, 503, 599])
def test_http_errors_preserve_status_and_hide_framework_details(status: int) -> None:
    error = HTTPException(status, detail="private framework context")
    failure = error_payload(error)
    assert failure.error.status == status
    assert "private framework context" not in failure.model_dump_json()


def test_http_boundary_classifies_the_exception_once() -> None:
    classified: list[None] = []

    class CountedForbidden(Forbidden):
        @property
        def status(self) -> int:
            classified.append(None)
            return 403

    app = create_app(PgSettings(_env_file=None, keys={"test-key": Principal()}))

    @app.get("/classification-probe")
    async def probe() -> None:
        raise CountedForbidden("Controlled application message")

    response = TestClient(app, raise_server_exceptions=False).get("/classification-probe")
    assert response.status_code == 403
    assert Failure.model_validate_json(response.content).error.reason is ErrorReason.POLICY_DENIED
    assert len(classified) == 1
