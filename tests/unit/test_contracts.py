from __future__ import annotations

import pytest
from pydantic import ValidationError

from pgfacade.contracts.admin import ServerWhoAmI
from pgfacade.contracts.base import Count
from pgfacade.contracts.enums import Operation
from pgfacade.contracts.envelopes import ResponseEnvelope, Success


@pytest.mark.parametrize(
    "outcome",
    [
        {"status": "success", "data": {"count": 1}, "error": {"code": "internal_error", "message": "bad", "status": 500}},
        {"status": "error", "data": {"count": 1}, "error": {"code": "internal_error", "message": "bad", "status": 500}},
        {"status": "success"},
        {"status": "error"},
        {"status": "unknown", "data": {"count": 1}},
        {"data": {"count": 1}},
    ],
)
def test_outcome_contract_rejects_ambiguous_or_incomplete_responses(outcome: object) -> None:
    with pytest.raises(ValidationError):
        ResponseEnvelope[Count].model_validate({"kind": "rows.count", "outcome": outcome})


def test_success_contract_serializes_and_validates_without_error_field() -> None:
    response = ResponseEnvelope[Count](kind=Operation.ROWS_COUNT, outcome=Success(data=Count(count=3)))
    assert response.model_dump(mode="json") == {"kind": "rows.count", "outcome": {"status": "success", "data": {"count": 3}}}
    assert ResponseEnvelope[Count].model_validate_json(response.model_dump_json()) == response


def test_request_contract_rejects_unknown_envelope_fields() -> None:
    with pytest.raises(ValidationError):
        ServerWhoAmI.model_validate({"input": {}, "unrecognized": "value"})


@pytest.mark.parametrize(
    "values",
    [
        {"code": "internal_error", "message": "Failure", "status": 200},
        {"code": "unrecognized_error_code", "message": "Failure", "status": 500},
    ],
)
def test_error_contract_rejects_success_status_and_unknown_codes(values: dict[str, object]) -> None:
    from pgfacade.contracts.envelopes import ApiError

    with pytest.raises(ValidationError):
        ApiError.model_validate(values)
