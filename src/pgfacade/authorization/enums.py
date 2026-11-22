from __future__ import annotations

from enum import StrEnum


class IdentitySource(StrEnum):
    MOCK = "mock"
    STUB = "stub"


class PolicyEffect(StrEnum):
    ALLOW = "allow"
    DENY = "deny"


class AuthorizationResource(StrEnum):
    CONNECTOR = "@connector"
