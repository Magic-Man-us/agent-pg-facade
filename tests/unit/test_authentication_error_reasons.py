from __future__ import annotations

from dataclasses import dataclass
from typing import cast

import pytest
from fastapi.testclient import TestClient

from pgfacade.application.errors import (
    AmbiguousExecutionIdentity,
    AuthenticationNotConfigured,
    Forbidden,
    IdentityProviderInvalidResponse,
    IdentityProviderNotConfigured,
    IdentityProviderUnavailable,
    InvalidCredential,
    MissingCredential,
    NoMatchingPolicy,
    error_payload,
)
from pgfacade.authorization.contracts import IdentityLookupRequest
from pgfacade.authorization.credentials import resolve_principal
from pgfacade.authorization.engine import PolicyEngine
from pgfacade.authorization.models import AccessControlConfig, AuthorizationContext, Identity
from pgfacade.authorization.providers import IdentityProvider, authenticate
from pgfacade.configuration.settings import PgSettings, Principal
from pgfacade.contracts.enums import ErrorCode, ErrorReason
from pgfacade.contracts.envelopes import Failure
from pgfacade.contracts.rows import RowsSelect, RowsSelectInput
from pgfacade.shared.types import ApiKey, HttpStatusCode
from pgfacade.webapp import create_app
from tests.support import _DENY, allow, config, identity

CREDENTIAL = "synthetic-auth-reason-credential"
PRIVATE_PROVIDER_VALUE = "synthetic-private-provider-value"


@pytest.mark.parametrize(
    ("credential", "error_type", "reason"),
    [
        (None, MissingCredential, ErrorReason.CREDENTIAL_MISSING),
        ("synthetic-wrong-credential", InvalidCredential, ErrorReason.CREDENTIAL_INVALID),
    ],
)
def test_api_key_failures_have_distinct_typed_reasons(
    credential: ApiKey | None, error_type: type[MissingCredential | InvalidCredential], reason: ErrorReason
) -> None:
    settings = PgSettings(_env_file=None, keys={CREDENTIAL: Principal()})
    with pytest.raises(error_type) as caught:
        resolve_principal(settings, credential)
    payload = error_payload(caught.value)
    assert payload.error.status == 401
    assert payload.error.code is ErrorCode.UNAUTHENTICATED
    assert payload.error.reason is reason
    assert CREDENTIAL not in payload.model_dump_json()
    if credential is not None:
        assert credential not in payload.model_dump_json()


def test_unconfigured_api_keys_are_a_service_configuration_failure() -> None:
    with pytest.raises(AuthenticationNotConfigured) as caught:
        resolve_principal(PgSettings(_env_file=None), CREDENTIAL)
    payload = error_payload(caught.value)
    assert payload.error.status == 503
    assert payload.error.reason is ErrorReason.AUTHENTICATION_UNCONFIGURED
    assert CREDENTIAL not in payload.model_dump_json()


async def test_missing_identity_credential_and_unconfigured_provider_are_distinct() -> None:
    settings = PgSettings(_env_file=None, access_control=AccessControlConfig())
    with pytest.raises(MissingCredential) as missing:
        await authenticate(settings, None)
    with pytest.raises(IdentityProviderNotConfigured) as unconfigured:
        await authenticate(settings, CREDENTIAL)
    assert error_payload(missing.value).error.reason is ErrorReason.CREDENTIAL_MISSING
    assert error_payload(unconfigured.value).error.status == 503
    assert error_payload(unconfigured.value).error.reason is ErrorReason.IDENTITY_PROVIDER_UNCONFIGURED


@dataclass(frozen=True, slots=True)
class FailingProvider:
    error: Exception

    async def lookup(self, request: IdentityLookupRequest) -> Identity:
        raise self.error


class MalformedProvider:
    async def lookup(self, request: IdentityLookupRequest) -> Identity:
        # An external provider can violate its annotation; the returned identity remains a validation boundary.
        return cast(Identity, {"subject": "", "name": PRIVATE_PROVIDER_VALUE})


class CorruptedProvider:
    async def lookup(self, request: IdentityLookupRequest) -> Identity:
        return Identity(subject="valid-subject").model_copy(update={"subject": "", "name": PRIVATE_PROVIDER_VALUE})


@pytest.mark.parametrize("credential", ["", "synthetic invalid credential"])
async def test_malformed_credential_does_not_reach_the_identity_provider(credential: ApiKey) -> None:
    settings = PgSettings(_env_file=None, access_control=AccessControlConfig())
    provider = FailingProvider(AssertionError("Invalid credential reached provider"))
    with pytest.raises(InvalidCredential) as caught:
        await authenticate(settings, credential, provider)
    payload = error_payload(caught.value)
    assert payload.error.status == 401
    assert payload.error.reason is ErrorReason.CREDENTIAL_INVALID
    if credential:
        assert credential not in payload.model_dump_json()


@pytest.mark.parametrize("error", [TimeoutError(PRIVATE_PROVIDER_VALUE), ConnectionError(PRIVATE_PROVIDER_VALUE)])
async def test_known_provider_transport_faults_are_unavailable(error: Exception) -> None:
    settings = PgSettings(_env_file=None, access_control=AccessControlConfig())
    with pytest.raises(IdentityProviderUnavailable) as caught:
        await authenticate(settings, CREDENTIAL, FailingProvider(error))
    payload = error_payload(caught.value)
    assert payload.error.status == 503
    assert payload.error.reason is ErrorReason.IDENTITY_PROVIDER_UNAVAILABLE
    assert PRIVATE_PROVIDER_VALUE not in payload.model_dump_json()
    assert CREDENTIAL not in payload.model_dump_json()


@pytest.mark.parametrize("provider", [MalformedProvider(), CorruptedProvider()])
async def test_malformed_provider_response_is_a_bad_gateway_failure(provider: IdentityProvider) -> None:
    settings = PgSettings(_env_file=None, access_control=AccessControlConfig())
    with pytest.raises(IdentityProviderInvalidResponse) as caught:
        await authenticate(settings, CREDENTIAL, provider)
    payload = error_payload(caught.value)
    assert payload.error.status == 502
    assert payload.error.reason is ErrorReason.IDENTITY_PROVIDER_INVALID_RESPONSE
    assert PRIVATE_PROVIDER_VALUE not in payload.model_dump_json()
    assert CREDENTIAL not in payload.model_dump_json()


async def test_unknown_provider_exception_keeps_internal_error_classification() -> None:
    settings = PgSettings(_env_file=None, access_control=AccessControlConfig())
    with pytest.raises(RuntimeError) as caught:
        await authenticate(settings, CREDENTIAL, FailingProvider(RuntimeError(PRIVATE_PROVIDER_VALUE)))
    payload = error_payload(caught.value)
    assert payload.error.status == 500
    assert payload.error.code is ErrorCode.INTERNAL_ERROR
    assert PRIVATE_PROVIDER_VALUE not in payload.model_dump_json()


@pytest.mark.parametrize(
    ("provider", "status", "reason"),
    [
        (None, 503, ErrorReason.IDENTITY_PROVIDER_UNCONFIGURED),
        (FailingProvider(TimeoutError(PRIVATE_PROVIDER_VALUE)), 503, ErrorReason.IDENTITY_PROVIDER_UNAVAILABLE),
        (FailingProvider(ConnectionError(PRIVATE_PROVIDER_VALUE)), 503, ErrorReason.IDENTITY_PROVIDER_UNAVAILABLE),
        (MalformedProvider(), 502, ErrorReason.IDENTITY_PROVIDER_INVALID_RESPONSE),
        (CorruptedProvider(), 502, ErrorReason.IDENTITY_PROVIDER_INVALID_RESPONSE),
        (FailingProvider(RuntimeError(PRIVATE_PROVIDER_VALUE)), 500, ErrorReason.UNEXPECTED_FAILURE),
    ],
)
def test_provider_http_failures_are_not_reported_as_invalid_credentials(
    provider: IdentityProvider | None, status: HttpStatusCode, reason: ErrorReason
) -> None:
    settings = PgSettings(_env_file=None, access_control=AccessControlConfig())
    response = TestClient(create_app(settings, identity_provider=provider), raise_server_exceptions=False).post(
        "/server/whoami", json={"input": {}}, headers={"Authorization": f"Bearer {CREDENTIAL}"}
    )
    assert response.status_code == status
    assert "WWW-Authenticate" not in response.headers
    payload = Failure.model_validate_json(response.content)
    assert payload.error.reason is reason
    assert PRIVATE_PROVIDER_VALUE not in response.text
    assert CREDENTIAL not in response.text


@pytest.mark.parametrize(
    ("access", "error_type", "reason"),
    [
        (config(), NoMatchingPolicy, ErrorReason.POLICY_NO_MATCH),
        (config(allow(), _DENY), Forbidden, ErrorReason.POLICY_DENIED),
        (config(allow(), allow("audit", profile="auditor")), AmbiguousExecutionIdentity, ErrorReason.IDENTITY_AMBIGUOUS),
    ],
)
def test_authorization_denial_reasons_preserve_policy_outcomes(
    access: AccessControlConfig, error_type: type[Forbidden], reason: ErrorReason
) -> None:
    engine = PolicyEngine(access)
    request = RowsSelect(input=RowsSelectInput(table="reports"))
    with pytest.raises(error_type) as caught:
        engine.authorize(request, identity("team"), AuthorizationContext(connector="local", default_schema="app"))
    payload = error_payload(caught.value)
    assert payload.error.status == 403
    assert payload.error.reason is reason
