from __future__ import annotations

from fnmatch import fnmatchcase

from pydantic import TypeAdapter, ValidationError

from pgfacade.application.errors import AmbiguousExecutionIdentity, Forbidden, InvalidRequest, NoMatchingPolicy
from pgfacade.authorization.enums import AuthorizationResource, PolicyEffect
from pgfacade.authorization.models import (
    AccessControlConfig,
    AuthorizationContext,
    AuthorizationDecision,
    Identity,
    OperationTarget,
    Policy,
)
from pgfacade.authorization.types import AuthorizationFlag, ExecutionIdentityId, PolicyPriority, ResourceName
from pgfacade.contracts.enums import Operation
from pgfacade.contracts.requests import Request

_ROW_OPERATIONS = frozenset(
    {
        Operation.ROWS_SELECT,
        Operation.ROWS_GET,
        Operation.ROWS_COUNT,
        Operation.ROWS_EXISTS,
        Operation.ROWS_AGGREGATE,
        Operation.ROWS_INSERT,
        Operation.ROWS_UPDATE,
        Operation.ROWS_DELETE,
        Operation.ROWS_EXPORT_CSV,
        Operation.ROWS_IMPORT_CSV,
    }
)
_WRITE_OPERATIONS = frozenset({Operation.ROWS_INSERT, Operation.ROWS_UPDATE, Operation.ROWS_DELETE, Operation.ROWS_IMPORT_CSV})
_CONNECTOR_OPERATIONS = frozenset({Operation.SERVER_HEALTH, Operation.SERVER_WHOAMI})
SUPPORTED_OPERATIONS = _ROW_OPERATIONS | _CONNECTOR_OPERATIONS | {Operation.BATCH_RUN}
_RESOURCE_ADAPTER = TypeAdapter(ResourceName)


def _targets(request: Request, context: AuthorizationContext) -> tuple[OperationTarget, ...]:
    match request.kind:
        case Operation.BATCH_RUN:
            if any(child.kind == Operation.BATCH_RUN for child in request.input.requests):
                raise InvalidRequest("nested batches are not allowed")
            return tuple(target for child in request.input.requests for target in _targets(child, context))
        case (
            Operation.ROWS_SELECT
            | Operation.ROWS_GET
            | Operation.ROWS_COUNT
            | Operation.ROWS_EXISTS
            | Operation.ROWS_AGGREGATE
            | Operation.ROWS_INSERT
            | Operation.ROWS_UPDATE
            | Operation.ROWS_DELETE
            | Operation.ROWS_EXPORT_CSV
            | Operation.ROWS_IMPORT_CSV
        ):
            schema, separator, _table = request.input.table.partition(".")
            qualified = request.input.table if separator else f"{context.default_schema}.{schema}"
            try:
                resource = _RESOURCE_ADAPTER.validate_python(qualified)
            except ValidationError:
                raise Forbidden("Group policies require simple qualified table identifiers") from None
            return (OperationTarget(operation=request.kind, resource=resource),)
        case Operation.SERVER_HEALTH | Operation.SERVER_WHOAMI:
            return (OperationTarget(operation=request.kind, resource=AuthorizationResource.CONNECTOR),)
        case _:
            raise Forbidden("This operation does not support group-scoped resource authorization")


def _matches(policy: Policy, identity: Identity, context: AuthorizationContext, target: OperationTarget) -> AuthorizationFlag:
    return (
        policy.connector == context.connector
        and bool(policy.groups & identity.groups)
        and any(fnmatchcase(target.operation, pattern) for pattern in policy.operations)
        and any(fnmatchcase(target.resource, pattern) for pattern in policy.resources)
    )


class PolicyEngine:
    def __init__(self, config: AccessControlConfig) -> None:
        self.config = config

    def authorize(self, request: Request, identity: Identity, context: AuthorizationContext) -> AuthorizationDecision:
        if request.kind == Operation.BATCH_RUN and len(request.input.requests) > self.config.max_batch_operations:
            raise InvalidRequest("Batch exceeds the configured group operation limit")
        targets = _targets(request, context)
        denied_targets = targets
        if request.kind == Operation.BATCH_RUN:
            envelope = tuple(OperationTarget(operation=Operation.BATCH_RUN, resource=target.resource) for target in targets)
            denied_targets += envelope + (OperationTarget(operation=Operation.BATCH_RUN, resource=AuthorizationResource.CONNECTOR),)
        for policy in self.config.policies:
            if policy.effect == PolicyEffect.DENY and any(_matches(policy, identity, context, target) for target in denied_targets):
                raise Forbidden("Group policy explicitly denies this operation or resource")
        candidates: dict[ExecutionIdentityId, list[PolicyPriority]] = {}
        for profile_id, profile in self.config.execution_identities.items():
            if context.execution_identity is not None and profile_id != context.execution_identity:
                continue
            if profile.read_only and any(target.operation in _WRITE_OPERATIONS for target in targets):
                continue
            priorities: list[PolicyPriority] = []
            for target in targets:
                matching = [
                    policy.priority
                    for policy in self.config.policies
                    if policy.effect == PolicyEffect.ALLOW
                    and policy.execution_identity == profile_id
                    and _matches(policy, identity, context, target)
                ]
                if not matching:
                    break
                priorities.append(max(matching))
            if len(priorities) == len(targets) and priorities:
                candidates[profile_id] = priorities
        if not candidates:
            raise NoMatchingPolicy("No group policy permits this operation and resource with one execution identity")
        priority = max(min(priorities) for priorities in candidates.values())
        winners = [profile for profile, priorities in candidates.items() if min(priorities) == priority]
        if len(winners) != 1:
            raise AmbiguousExecutionIdentity("Group policies select ambiguous execution identities")
        selected = winners[0]
        matched = tuple(
            sorted(
                {
                    policy.id
                    for policy in self.config.policies
                    if policy.effect == PolicyEffect.ALLOW
                    and policy.execution_identity == selected
                    and any(_matches(policy, identity, context, target) for target in targets)
                }
            )
        )
        return AuthorizationDecision(
            execution_identity=selected, profile=self.config.execution_identities[selected], matched_policies=matched
        )

    def discover(self, operation: Operation, identity: Identity, context: AuthorizationContext) -> tuple[AuthorizationDecision, ...]:
        if operation not in SUPPORTED_OPERATIONS:
            return ()
        candidates: dict[ExecutionIdentityId, AuthorizationDecision] = {}
        if operation == Operation.BATCH_RUN and any(
            policy.effect == PolicyEffect.DENY
            and _matches(policy, identity, context, OperationTarget(operation=operation, resource=AuthorizationResource.CONNECTOR))
            for policy in self.config.policies
        ):
            return ()
        for policy in self.config.policies:
            if policy.effect != PolicyEffect.ALLOW or policy.connector != context.connector or not policy.groups & identity.groups:
                continue
            if context.execution_identity is not None and policy.execution_identity != context.execution_identity:
                continue
            profile = self.config.execution_identities[policy.execution_identity]
            if operation == Operation.BATCH_RUN:
                possible = _ROW_OPERATIONS | _CONNECTOR_OPERATIONS
                if profile.read_only:
                    possible -= _WRITE_OPERATIONS
                eligible = any(fnmatchcase(candidate, pattern) for candidate in possible for pattern in policy.operations)
            else:
                eligible = any(fnmatchcase(operation, pattern) for pattern in policy.operations)
            if not eligible:
                continue
            if profile.read_only and operation in _WRITE_OPERATIONS:
                continue
            resources = policy.resources
            if operation in _CONNECTOR_OPERATIONS:
                resources = tuple(resource for resource in resources if fnmatchcase(AuthorizationResource.CONNECTOR, resource))
                if not resources:
                    continue
                resources = (AuthorizationResource.CONNECTOR,)
            elif operation in _ROW_OPERATIONS:
                resources = tuple(resource for resource in resources if resource != AuthorizationResource.CONNECTOR)
                if not resources:
                    continue
            if all(
                any(
                    denied.effect == PolicyEffect.DENY
                    and _matches(denied, identity, context, OperationTarget(operation=operation, resource=resource))
                    for denied in self.config.policies
                )
                for resource in resources
            ):
                continue
            candidates[policy.execution_identity] = AuthorizationDecision(
                execution_identity=policy.execution_identity, profile=profile, matched_policies=(policy.id,)
            )
        return tuple(candidates.values())
