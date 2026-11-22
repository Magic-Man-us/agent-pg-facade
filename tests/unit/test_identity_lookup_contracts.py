from __future__ import annotations

import asyncio

import pytest
from pydantic import ValidationError

from pgfacade.application.errors import IdentityProviderInvalidResponse, IdentityProviderNotConfigured, InvalidCredential, MissingCredential
from pgfacade.authorization.contracts import IdentityLookupRequest
from pgfacade.authorization.models import AccessControlConfig, Identity, MockIdentityConfig, MockIdentityRecord
from pgfacade.authorization.providers import MockIdentityProvider, StubIdentityProvider, authenticate
from pgfacade.configuration.settings import PgSettings

CREDENTIAL = "synthetic-lookup-credential"


@pytest.mark.parametrize("raw", ["", " ", "space credential", "line\nbreak", 7, None])
def test_identity_lookup_request_rejects_invalid_credentials(raw: object) -> None:
    with pytest.raises(ValidationError):
        IdentityLookupRequest.model_validate({"credential": raw})


def test_identity_lookup_request_owns_validation_and_hides_credential_repr() -> None:
    request = IdentityLookupRequest.model_validate({"credential": CREDENTIAL})
    assert request.credential == CREDENTIAL
    assert CREDENTIAL not in repr(request)
    assert IdentityLookupRequest.model_validate_json(request.model_dump_json()) == request
    with pytest.raises(ValidationError):
        IdentityLookupRequest.model_validate({"credential": CREDENTIAL, "extra": True})


async def test_mock_lookup_returns_the_declared_identity_response() -> None:
    identity = Identity(subject="person")
    provider = MockIdentityProvider(MockIdentityConfig(records=(MockIdentityRecord(token=CREDENTIAL, identity=identity),)))
    response = await provider.lookup(IdentityLookupRequest(credential=CREDENTIAL))
    assert isinstance(response, Identity)
    assert response == identity
    with pytest.raises(InvalidCredential, match="Invalid mock identity credential"):
        await provider.lookup(IdentityLookupRequest(credential="unknown"))


async def test_stub_lookup_remains_deny_all() -> None:
    with pytest.raises(IdentityProviderNotConfigured, match="not configured"):
        await StubIdentityProvider().lookup(IdentityLookupRequest(credential=CREDENTIAL))


async def test_authentication_passes_the_typed_lookup_request_and_preserves_cancellation() -> None:
    seen: list[IdentityLookupRequest] = []

    class Provider:
        async def lookup(self, request: IdentityLookupRequest) -> Identity:
            seen.append(request)
            raise asyncio.CancelledError

    settings = PgSettings(_env_file=None, access_control=AccessControlConfig())
    with pytest.raises(asyncio.CancelledError):
        await authenticate(settings, CREDENTIAL, Provider())
    assert len(seen) == 1
    assert seen[0].credential == CREDENTIAL


async def test_authentication_rejects_a_malformed_provider_response_without_leaking_values() -> None:
    class Provider:
        async def lookup(self, request: IdentityLookupRequest) -> Identity:
            return Identity.model_construct(subject="synthetic-private invalid subject")

    settings = PgSettings(_env_file=None, access_control=AccessControlConfig())
    with pytest.raises(IdentityProviderInvalidResponse, match="invalid identity") as captured:
        await authenticate(settings, CREDENTIAL, Provider())
    assert "synthetic-private" not in str(captured.value)
    assert CREDENTIAL not in str(captured.value)


async def test_authentication_keeps_missing_credentials_unauthorized() -> None:
    settings = PgSettings(_env_file=None, access_control=AccessControlConfig())
    with pytest.raises(MissingCredential, match="Missing identity credential"):
        await authenticate(settings, None)
