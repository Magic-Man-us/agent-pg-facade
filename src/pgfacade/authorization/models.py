from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from pgfacade.authorization.enums import IdentitySource, PolicyEffect
from pgfacade.authorization.types import (
    AuthorizationFlag,
    BatchOperationLimit,
    ConnectorId,
    DatabaseIdentifier,
    DatabaseRole,
    ExecutionIdentityId,
    IdentityGroups,
    IdentityIssuer,
    IdentityName,
    MatchedPolicies,
    MockToken,
    PolicyGroups,
    PolicyId,
    PolicyOperations,
    PolicyPriority,
    PolicyResources,
    ResourcePattern,
    SubjectId,
)
from pgfacade.contracts.enums import Operation
from pgfacade.shared.config import CONTRACT_CONFIG


class Identity(BaseModel):
    model_config = ConfigDict(**CONTRACT_CONFIG, revalidate_instances="always")

    subject: SubjectId
    groups: IdentityGroups = Field(default_factory=frozenset)
    name: IdentityName | None = None
    issuer: IdentityIssuer = IdentitySource.MOCK


class MockIdentityRecord(BaseModel):
    model_config = CONTRACT_CONFIG

    token: MockToken = Field(repr=False, exclude=True)
    identity: Identity


class MockIdentityConfig(BaseModel):
    model_config = CONTRACT_CONFIG

    kind: Literal[IdentitySource.MOCK] = IdentitySource.MOCK
    records: tuple[MockIdentityRecord, ...] = Field(default_factory=tuple)

    @model_validator(mode="after")
    def _unique_tokens(self) -> Self:
        if any(record.identity.issuer != IdentitySource.MOCK for record in self.records):
            raise ValueError("Mock identities must use the mock issuer")
        values = [record.token.get_secret_value() for record in self.records]
        if len(values) != len(set(values)):
            raise ValueError("Mock identity credentials must be unique")
        return self


class StubIdentityConfig(BaseModel):
    model_config = CONTRACT_CONFIG

    kind: Literal[IdentitySource.STUB] = IdentitySource.STUB


IdentityConfig = Annotated[MockIdentityConfig | StubIdentityConfig, Field(discriminator="kind")]


class ExecutionIdentity(BaseModel):
    model_config = CONTRACT_CONFIG

    role: DatabaseRole
    read_only: AuthorizationFlag = True


class _Policy(BaseModel):
    model_config = CONTRACT_CONFIG

    id: PolicyId
    groups: PolicyGroups
    connector: ConnectorId
    operations: PolicyOperations
    resources: PolicyResources
    priority: PolicyPriority = 0


class AllowPolicy(_Policy):
    effect: Literal[PolicyEffect.ALLOW] = PolicyEffect.ALLOW
    execution_identity: ExecutionIdentityId


class DenyPolicy(_Policy):
    effect: Literal[PolicyEffect.DENY] = PolicyEffect.DENY


Policy = Annotated[AllowPolicy | DenyPolicy, Field(discriminator="effect")]


class AccessControlConfig(BaseModel):
    model_config = CONTRACT_CONFIG

    identity: IdentityConfig = Field(default_factory=StubIdentityConfig)
    max_batch_operations: BatchOperationLimit = 100
    execution_identities: dict[ExecutionIdentityId, ExecutionIdentity] = Field(default_factory=dict)
    policies: tuple[Policy, ...] = Field(default_factory=tuple)

    @model_validator(mode="after")
    def _validate_policy_bindings(self) -> Self:
        policy_ids = [policy.id for policy in self.policies]
        if len(policy_ids) != len(set(policy_ids)):
            raise ValueError("Policy identifiers must be unique")
        for policy in self.policies:
            if policy.effect == PolicyEffect.ALLOW and policy.execution_identity not in self.execution_identities:
                raise ValueError(f"Policy {policy.id!r} references an unknown execution identity")
        return self


@dataclass(frozen=True, slots=True)
class AuthorizationContext:
    connector: ConnectorId
    default_schema: DatabaseIdentifier
    execution_identity: ExecutionIdentityId | None = None


@dataclass(frozen=True, slots=True)
class OperationTarget:
    operation: Operation
    resource: ResourcePattern


@dataclass(frozen=True, slots=True)
class AuthorizationDecision:
    execution_identity: ExecutionIdentityId
    profile: ExecutionIdentity
    matched_policies: MatchedPolicies = ()
