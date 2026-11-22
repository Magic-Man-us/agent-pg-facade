"""API key -> Principal resolution shared by webapp and webmcp."""

from __future__ import annotations

import secrets

from pgfacade.application.errors import AuthenticationNotConfigured, InvalidCredential, MissingCredential
from pgfacade.configuration.settings import PgSettings, Principal
from pgfacade.shared.types import ApiKey, HttpHeaders

AUTHORIZATION_HEADER = "authorization"
BEARER_SCHEME = "bearer"


def resolve_principal(settings: PgSettings, key: ApiKey | None) -> Principal:
    if not settings.auth_enabled:
        raise AuthenticationNotConfigured("API keys are not configured")
    if key is None:
        raise MissingCredential("missing API key")
    found: Principal | None = None
    for candidate, principal in settings.keys.items():  # compare all: constant time per key count
        if secrets.compare_digest(candidate.encode(), key.encode()):
            found = principal
    if found is None:
        raise InvalidCredential("invalid API key")
    return found


def bearer_token(headers: HttpHeaders) -> ApiKey | None:
    for name, value in headers.items():
        if name.lower() == AUTHORIZATION_HEADER:
            scheme, _, token = value.partition(" ")
            return token.strip() if scheme.lower() == BEARER_SCHEME and token.strip() else None
    return None
