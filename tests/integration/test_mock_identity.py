from __future__ import annotations

import asyncio
import socket
from collections.abc import Callable
from typing import Never
from urllib import request as urllib_request

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from fastmcp import Client
from pydantic import ValidationError
from starlette.requests import Request

from pgfacade import PgFacade, PgSettings, Principal, Unauthenticated
from pgfacade.application.errors import IdentityProviderNotConfigured
from pgfacade.authorization.contracts import IdentityLookupRequest
from pgfacade.authorization.models import (
    AccessControlConfig,
    AllowPolicy,
    ExecutionIdentity,
    Identity,
    MockIdentityConfig,
    MockIdentityRecord,
)
from pgfacade.authorization.providers import (
    IdentityProvider,
    MockIdentityProvider,
    StubIdentityProvider,
    authenticate,
    configure_identity_provider,
)
from pgfacade.contracts.enums import ErrorReason
from pgfacade.contracts.envelopes import Failure
from pgfacade.shared.types import ApiKey
from pgfacade.webapp import Context, create_app
from pgfacade.webmcp import create_mcp, resolve_mcp_context

ALICE_TOKEN = "synthetic-alice-credential"
BOB_TOKEN = "synthetic-bob-credential"
ALICE = Identity(subject="subject-alice", groups=frozenset({"reports-readers"}), name="Alice")
BOB = Identity(subject="subject-bob", groups=frozenset({"other-readers"}), name="Bob")


@pytest.fixture
def mock_settings() -> PgSettings:
    policy = AllowPolicy.model_validate_json(
        '{"id":"read-identity","groups":["reports-readers","other-readers"],"connector":"local","operations":["server.whoami"],"resources":["@connector"],"execution_identity":"reader"}'
    )
    source = MockIdentityConfig(
        records=(MockIdentityRecord(token=ALICE_TOKEN, identity=ALICE), MockIdentityRecord(token=BOB_TOKEN, identity=BOB))
    )
    access = AccessControlConfig(
        identity=source, execution_identities={"reader": ExecutionIdentity(role="pgfacade_reader")}, policies=(policy,)
    )
    return PgSettings(_env_file=None, access_control=access, mcp_key=ALICE_TOKEN)


def identity_app(settings: PgSettings, provider: IdentityProvider | None = None) -> FastAPI:
    app = create_app(settings, identity_provider=provider)

    @app.get("/test-identity")
    async def identity(context: Context) -> Principal:
        return context.principal

    return app


async def test_mock_lookup_uses_only_configured_identity(mock_settings: PgSettings) -> None:
    provider = configure_identity_provider(mock_settings)
    principal = await authenticate(mock_settings, ALICE_TOKEN, provider)
    assert principal.identity == ALICE
    assert principal.name == "Alice"
    assert principal.role is None and principal.execution_identity is None
    assert principal.read_only
    assert not any((principal.sql, principal.ddl, principal.admin, principal.migrate, principal.listen))


@pytest.mark.parametrize("credential", [None, "not-configured", "eyJhbGciOiJub25lIn0.fake-google-claims.signature"])
async def test_mock_lookup_rejects_unknown_or_missing_credentials(mock_settings: PgSettings, credential: ApiKey | None) -> None:
    with pytest.raises(Unauthenticated):
        await authenticate(mock_settings, credential)


async def test_stub_lookup_always_denies_without_network() -> None:
    settings = PgSettings(_env_file=None, access_control=AccessControlConfig())
    assert isinstance(configure_identity_provider(settings), StubIdentityProvider)
    with pytest.raises(IdentityProviderNotConfigured, match="not configured"):
        await authenticate(settings, ALICE_TOKEN)


async def test_legacy_api_key_mode_is_unchanged() -> None:
    settings = PgSettings(_env_file=None, keys={ALICE_TOKEN: Principal(name="legacy")})
    assert configure_identity_provider(settings) is None
    principal = await authenticate(settings, ALICE_TOKEN)
    assert principal.name == "legacy" and principal.identity is None


async def test_group_mode_never_falls_back_to_legacy_api_keys(mock_settings: PgSettings) -> None:
    settings = PgSettings(
        _env_file=None, access_control=mock_settings.access_control, keys={"legacy-key": Principal(name="legacy", admin=True)}
    )
    with pytest.raises(Unauthenticated):
        await authenticate(settings, "legacy-key")


def test_http_headers_cannot_supply_groups_or_database_identity(mock_settings: PgSettings) -> None:
    client = TestClient(identity_app(mock_settings))
    headers = {
        "Authorization": f"Bearer {ALICE_TOKEN}",
        "X-Google-Groups": "administrators",
        "X-User": "someone-else",
        "X-Database-Role": "postgres",
    }
    response = client.get("/test-identity", headers=headers)
    assert response.status_code == 200
    principal = Principal.model_validate_json(response.content)
    assert principal.identity == ALICE
    assert principal.role is None and principal.name == "Alice"
    assert ALICE_TOKEN not in response.text


def test_http_spoofed_google_claims_do_not_authenticate(mock_settings: PgSettings) -> None:
    client = TestClient(identity_app(mock_settings))
    response = client.get(
        "/test-identity", headers={"Authorization": "Bearer eyJ.fake-google-jwt.signature", "X-Google-Groups": "reports-readers"}
    )
    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"
    assert Failure.model_validate_json(response.content).error.reason is ErrorReason.CREDENTIAL_INVALID
    assert "fake-google-jwt" not in response.text


async def test_concurrent_http_requests_do_not_share_identity(mock_settings: PgSettings) -> None:
    app = identity_app(mock_settings)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        responses = await asyncio.gather(
            client.get("/test-identity", headers={"Authorization": f"Bearer {ALICE_TOKEN}"}),
            client.get("/test-identity", headers={"Authorization": f"Bearer {BOB_TOKEN}"}),
        )
    identities = [Principal.model_validate_json(response.content).identity for response in responses]
    assert identities == [ALICE, BOB]


class InjectedProvider:
    def __init__(self, identity: Identity) -> None:
        self.identity = identity
        self.calls: list[ApiKey] = []

    async def lookup(self, request: IdentityLookupRequest) -> Identity:
        self.calls.append(request.credential)
        await asyncio.sleep(0)
        return self.identity


def test_async_provider_is_an_explicit_replaceable_hook() -> None:
    settings = PgSettings(_env_file=None, access_control=AccessControlConfig())
    identity = Identity(subject="custom-subject", groups=frozenset({"custom-group"}), issuer="custom")
    provider = InjectedProvider(identity)
    response = TestClient(identity_app(settings, provider)).get(
        "/test-identity", headers={"Authorization": "Bearer arbitrary-source-credential"}
    )
    assert response.status_code == 200
    assert Principal.model_validate_json(response.content).identity == identity
    assert provider.calls == ["arbitrary-source-credential"]


@pytest.mark.parametrize("factory", [create_app, create_mcp])
def test_injected_provider_requires_policy_configuration(factory: Callable[..., object]) -> None:
    settings = PgSettings(_env_file=None, keys={ALICE_TOKEN: Principal()})
    with pytest.raises(ValueError, match="requires access_control"):
        factory(settings, identity_provider=InjectedProvider(ALICE))


async def test_http_mcp_never_uses_stdio_mock_credential(mock_settings: PgSettings, monkeypatch: pytest.MonkeyPatch) -> None:
    request = Request({"type": "http", "headers": []})
    monkeypatch.setattr("pgfacade.webmcp.get_http_request", lambda: request)
    with pytest.raises(Unauthenticated, match="Missing identity credential"):
        await resolve_mcp_context(mock_settings)


async def test_http_mcp_resolves_request_mock_credential(mock_settings: PgSettings, monkeypatch: pytest.MonkeyPatch) -> None:
    request = Request({"type": "http", "headers": [(b"authorization", f"Bearer {BOB_TOKEN}".encode())]})
    monkeypatch.setattr("pgfacade.webmcp.get_http_request", lambda: request)
    db = await resolve_mcp_context(mock_settings)
    assert db.principal.identity == BOB


class InMemoryFacade(PgFacade):
    async def open(self) -> None:
        return None

    async def close(self) -> None:
        return None


async def test_mcp_tool_uses_the_same_mock_lookup(mock_settings: PgSettings) -> None:
    server = create_mcp(mock_settings, InMemoryFacade(mock_settings))
    async with Client(server) as client:
        response = await client.call_tool("pg_server_whoami", {"request": {"kind": "server.whoami", "input": {}}})
    assert response.structured_content["outcome"]["data"]["principal"] == "Alice"


async def test_mock_lookup_performs_no_network_requests(mock_settings: PgSettings, monkeypatch: pytest.MonkeyPatch) -> None:

    def forbidden_network(*_args: object, **_kwargs: object) -> Never:
        pytest.fail("Mock identity lookup attempted network access")

    monkeypatch.setattr(socket, "create_connection", forbidden_network)
    monkeypatch.setattr(urllib_request, "urlopen", forbidden_network)
    monkeypatch.setattr(httpx.Client, "request", forbidden_network)
    monkeypatch.setattr(httpx.AsyncClient, "request", forbidden_network)
    provider = configure_identity_provider(mock_settings)
    assert isinstance(provider, MockIdentityProvider)
    assert await provider.lookup(IdentityLookupRequest(credential=ALICE_TOKEN)) == ALICE
    with pytest.raises(Unauthenticated):
        await provider.lookup(IdentityLookupRequest(credential="unknown"))


def test_mock_configuration_cannot_claim_a_real_google_issuer() -> None:
    with pytest.raises(ValidationError, match="mock issuer"):
        MockIdentityConfig(records=(MockIdentityRecord(token=ALICE_TOKEN, identity=Identity(subject="x", issuer="google")),))
