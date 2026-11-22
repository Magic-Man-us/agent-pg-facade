from __future__ import annotations

import secrets
from typing import Protocol

from pydantic import ValidationError

from pgfacade.application.errors import (
    IdentityProviderInvalidResponse,
    IdentityProviderNotConfigured,
    IdentityProviderUnavailable,
    InvalidCredential,
    MissingCredential,
)
from pgfacade.authorization.contracts import IdentityLookupRequest
from pgfacade.authorization.credentials import resolve_principal
from pgfacade.authorization.enums import IdentitySource
from pgfacade.authorization.models import Identity, MockIdentityConfig
from pgfacade.configuration.settings import PgSettings, Principal
from pgfacade.shared.types import ApiKey


class IdentityProvider(Protocol):
    async def lookup(self, request: IdentityLookupRequest) -> Identity: ...


class StubIdentityProvider:
    async def lookup(self, request: IdentityLookupRequest) -> Identity:
        raise IdentityProviderNotConfigured("Identity lookup is not configured")


class MockIdentityProvider:
    def __init__(self, settings: MockIdentityConfig) -> None:
        self._records = settings.records

    async def lookup(self, request: IdentityLookupRequest) -> Identity:
        found: Identity | None = None
        for record in self._records:
            if secrets.compare_digest(record.token.get_secret_value().encode(), request.credential.encode()):
                found = record.identity
        if found is None:
            raise InvalidCredential("Invalid mock identity credential")
        return found


def configure_identity_provider(settings: PgSettings, provider: IdentityProvider | None = None) -> IdentityProvider | None:
    if settings.access_control is None:
        if provider is not None:
            raise ValueError("An injected identity provider requires access_control configuration")
        return None
    if provider is not None:
        return provider
    match settings.access_control.identity.kind:
        case IdentitySource.MOCK:
            return MockIdentityProvider(settings.access_control.identity)
        case IdentitySource.STUB:
            return StubIdentityProvider()
        case _:
            raise ValueError("Unsupported identity lookup kind")


async def authenticate(settings: PgSettings, credential: ApiKey | None, provider: IdentityProvider | None = None) -> Principal:
    resolved_provider = configure_identity_provider(settings, provider)
    if settings.access_control is None:
        return resolve_principal(settings, credential)
    if credential is None:
        raise MissingCredential("Missing identity credential")
    if resolved_provider is None:
        raise IdentityProviderNotConfigured("Identity lookup is not configured")
    try:
        request = IdentityLookupRequest(credential=credential)
    except ValidationError:
        raise InvalidCredential("Invalid identity credential") from None
    try:
        response = await resolved_provider.lookup(request)
        identity = Identity.model_validate(response)
    except ValidationError:
        raise IdentityProviderInvalidResponse("Identity provider returned an invalid identity") from None
    except (TimeoutError, ConnectionError):
        raise IdentityProviderUnavailable("Identity provider is unavailable") from None
    return Principal(name=identity.name or identity.subject, identity=identity, read_only=True)
