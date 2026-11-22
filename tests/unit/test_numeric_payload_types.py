from __future__ import annotations

import pytest
from pydantic import TypeAdapter, ValidationError

from pgfacade.authorization.types import BatchOperationLimit, PolicyPriority
from pgfacade.configuration.types import DatabasePort
from pgfacade.contracts.base import Count
from pgfacade.contracts.rows import RowsSelect
from pgfacade.contracts.types import (
    MAX_NOTIFICATION_PAYLOAD_BYTES,
    Name,
    NotificationPayload,
    RoleConnectionLimit,
    RowInput,
    RowLimit,
    RowOffset,
    WaitTimeoutSeconds,
)
from pgfacade.infrastructure.postgres.queries.types import ParameterBoolean, ParameterFloat, ParameterInteger
from pgfacade.infrastructure.postgres.types import MonotonicSeconds, PrimaryKeyPosition
from pgfacade.shared.types import (
    EventWaitSeconds,
    FloatValue,
    HeartbeatSeconds,
    IntegerValue,
    LifecycleSweepSeconds,
    PoolTimeoutSeconds,
    RequestByteLimit,
    SchemaCacheTtlSeconds,
    SecurityFlag,
    ServerPort,
)


@pytest.mark.parametrize(
    "adapter",
    [
        TypeAdapter(IntegerValue),
        TypeAdapter(FloatValue),
        TypeAdapter(RowLimit),
        TypeAdapter(RowOffset),
        TypeAdapter(WaitTimeoutSeconds),
        TypeAdapter(DatabasePort),
        TypeAdapter(ServerPort),
        TypeAdapter(RequestByteLimit),
        TypeAdapter(PolicyPriority),
        TypeAdapter(BatchOperationLimit),
        TypeAdapter(MonotonicSeconds),
        TypeAdapter(PrimaryKeyPosition),
        TypeAdapter(ParameterInteger),
        TypeAdapter(ParameterFloat),
    ],
)
@pytest.mark.parametrize("value", [True, False])
def test_numeric_aliases_reject_booleans(adapter: TypeAdapter[object], value: object) -> None:
    with pytest.raises(ValidationError):
        adapter.validate_python(value)


@pytest.mark.parametrize(
    "adapter",
    [
        TypeAdapter(FloatValue),
        TypeAdapter(WaitTimeoutSeconds),
        TypeAdapter(HeartbeatSeconds),
        TypeAdapter(PoolTimeoutSeconds),
        TypeAdapter(SchemaCacheTtlSeconds),
        TypeAdapter(EventWaitSeconds),
        TypeAdapter(LifecycleSweepSeconds),
        TypeAdapter(MonotonicSeconds),
        TypeAdapter(ParameterFloat),
    ],
)
@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf"), "NaN", "Infinity"])
def test_float_aliases_reject_nonfinite_values(adapter: TypeAdapter[object], value: object) -> None:
    with pytest.raises(ValidationError):
        adapter.validate_python(value)


@pytest.mark.parametrize(
    ("adapter", "raw", "expected"),
    [
        (TypeAdapter(IntegerValue), "17", 17),
        (TypeAdapter(FloatValue), "0.25", 0.25),
        (TypeAdapter(DatabasePort), "5432", 5432),
        (TypeAdapter(RowOffset), "0", 0),
        (TypeAdapter(RoleConnectionLimit), "-1", -1),
        (TypeAdapter(ParameterInteger), "7", 7),
        (TypeAdapter(ParameterFloat), "1.5", 1.5),
    ],
)
def test_numeric_text_coercion_is_preserved(adapter: TypeAdapter[object], raw: object, expected: object) -> None:
    assert adapter.validate_python(raw) == expected


def test_model_boundaries_reject_boolean_numbers() -> None:
    with pytest.raises(ValidationError):
        RowsSelect.model_validate({"input": {"table": "items", "limit": True}})
    with pytest.raises(ValidationError):
        Count.model_validate({"count": True})


def test_boolean_fields_and_arbitrary_row_values_remain_valid() -> None:
    assert TypeAdapter(SecurityFlag).validate_python(True) is True
    assert TypeAdapter(ParameterBoolean).validate_python(True) is True
    assert TypeAdapter(RowInput).validate_python({"enabled": True}) == {"enabled": True}


@pytest.mark.parametrize("payload", ["", "a" * MAX_NOTIFICATION_PAYLOAD_BYTES, "é" * (MAX_NOTIFICATION_PAYLOAD_BYTES // 2)])
def test_notification_payload_accepts_valid_byte_lengths(payload: object) -> None:
    assert TypeAdapter(NotificationPayload).validate_python(payload) == payload


@pytest.mark.parametrize("payload", ["a" * (MAX_NOTIFICATION_PAYLOAD_BYTES + 1), "é" * 4000])
def test_notification_payload_rejects_oversized_utf8(payload: object) -> None:
    with pytest.raises(ValidationError):
        TypeAdapter(NotificationPayload).validate_python(payload)


@pytest.mark.parametrize("adapter", [TypeAdapter(Name), TypeAdapter(NotificationPayload)])
def test_postgres_text_boundaries_reject_nul(adapter: TypeAdapter[object]) -> None:
    with pytest.raises(ValidationError):
        adapter.validate_python("before\x00after")


def test_quoted_and_unusual_identifiers_remain_valid() -> None:
    assert TypeAdapter(Name).validate_python('odd "name"\n') == 'odd "name"\n'
