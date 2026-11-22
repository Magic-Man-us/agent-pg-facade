from __future__ import annotations

from collections.abc import Awaitable, Iterator
from contextlib import contextmanager

import pytest

from pgfacade.authorization.models import AccessControlConfig, AllowPolicy, DenyPolicy, ExecutionIdentity, Identity, Policy
from pgfacade.authorization.types import ExecutionIdentityId, GroupId, OperationPattern, PolicyId, PolicyPriority, ResourcePattern
from pgfacade.contracts.enums import ErrorCode
from pgfacade.contracts.envelopes import ApiError, Failure, ResponseEnvelope
from pgfacade.shared.types import ErrorMessage, SqlState

_ALLOW = AllowPolicy.model_validate_json(
    '{"id":"read","groups":["team"],"connector":"local","operations":["rows.select"],"resources":["app.reports"],"execution_identity":"reader"}'
)

_DENY = DenyPolicy.model_validate_json(
    '{"id":"blocked","groups":["team"],"connector":"local","operations":["rows.select"],"resources":["app.reports"]}'
)


def allow(
    policy_id: PolicyId = "read",
    operation: OperationPattern = "rows.select",
    resource: ResourcePattern = "app.reports",
    profile: ExecutionIdentityId = "reader",
    priority: PolicyPriority = 0,
) -> AllowPolicy:
    return AllowPolicy.model_validate(
        _ALLOW.model_dump()
        | {"id": policy_id, "operations": (operation,), "resources": (resource,), "execution_identity": profile, "priority": priority}
    )


def config(*policies: Policy) -> AccessControlConfig:
    return AccessControlConfig(
        execution_identities={
            "reader": ExecutionIdentity(role="app_reader"),
            "writer": ExecutionIdentity(role="app_writer", read_only=False),
            "auditor": ExecutionIdentity(role="app_auditor"),
        },
        policies=policies,
    )


def identity(*groups: GroupId) -> Identity:
    return Identity(subject="person", groups=groups)


class FailedOutcome(AssertionError):
    def __init__(self, error: ApiError) -> None:
        super().__init__(error.message)
        self.error = error


async def successful[DataT](operation: Awaitable[ResponseEnvelope[DataT]]) -> DataT:
    response = await operation
    if isinstance(response.outcome, Failure):
        raise FailedOutcome(response.outcome.error)
    return response.outcome.data


@contextmanager
def fails(*, code: ErrorCode | None = None, sqlstate: SqlState | None = None, match: ErrorMessage | None = None) -> Iterator[None]:
    with pytest.raises(FailedOutcome, match=match) as captured:
        yield
    if code is not None:
        assert captured.value.error.code is code
    if sqlstate is not None:
        assert captured.value.error.sqlstate == sqlstate
