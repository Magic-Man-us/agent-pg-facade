from __future__ import annotations

from dataclasses import FrozenInstanceError, is_dataclass

import pytest
from pydantic import ValidationError

from pgfacade.authorization.models import AuthorizationContext, AuthorizationDecision, ExecutionIdentity, OperationTarget
from pgfacade.configuration.settings import PgSettings, Principal
from pgfacade.contracts.enums import Operation
from pgfacade.presentation.middleware import BufferedRequestMessage


def test_authorization_context_is_a_trusted_frozen_record() -> None:
    context = AuthorizationContext(connector="local", default_schema="app")
    assert is_dataclass(context)
    assert context.default_schema == "app"
    with pytest.raises(FrozenInstanceError):
        context.connector = "other"


def test_operation_targets_preserve_validated_operation_and_resource_values() -> None:
    target = OperationTarget(operation=Operation.ROWS_SELECT, resource="app.reports")
    assert is_dataclass(target)
    assert target.operation is Operation.ROWS_SELECT
    assert target.resource == "app.reports"


def test_authorization_decision_preserves_profile_and_policy_types() -> None:
    profile = ExecutionIdentity(role="app_reader")
    decision = AuthorizationDecision(execution_identity="reader", profile=profile, matched_policies=("read_reports",))
    assert is_dataclass(decision)
    assert decision.profile is profile
    assert decision.matched_policies == ("read_reports",)
    with pytest.raises(FrozenInstanceError):
        decision.execution_identity = "writer"


def test_principal_keeps_quoted_postgresql_role_names() -> None:
    assert Principal(role="role with spaces").role == "role with spaces"
    with pytest.raises(ValidationError):
        Principal(role="bad\x00role")


def test_settings_keep_credentials_out_of_normal_serialization() -> None:
    settings = PgSettings(
        _env_file=None, dsn="dbname=fixture user=fixture password=fixture-password", keys={"fixture-key": Principal(name="fixture")}
    )
    serialized = settings.model_dump_json()
    assert "fixture-key" not in serialized
    assert "fixture-password" not in serialized
    assert "keys" not in settings.model_dump()


@pytest.mark.parametrize("values", [{"pool_min": -1}, {"pool_max": 0}, {"pool_timeout_s": 0}, {"max_rows": 0}, {"max_wait_s": 0}])
def test_settings_aliases_enforce_existing_numeric_limits(values: object) -> None:
    with pytest.raises(ValidationError):
        PgSettings.model_validate(values)


def test_buffered_http_message_owns_bytearray_coercion() -> None:
    message = BufferedRequestMessage.model_validate({"body": bytearray(b"payload")})
    assert message.body == b"payload"
    assert message.model_dump() == {"type": "http.request", "body": b"payload", "more_body": False}
    with pytest.raises(ValidationError):
        BufferedRequestMessage.model_validate({"body": b"payload", "more_body": True})
