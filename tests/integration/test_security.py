import asyncio
from collections.abc import Callable
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from starlette.requests import Request
from starlette.types import Message, Receive, Scope, Send

from pgfacade import ANONYMOUS, PgFacade, PgSettings, Principal, Unauthenticated
from pgfacade.application.errors import AuthenticationNotConfigured
from pgfacade.authorization.credentials import resolve_principal
from pgfacade.contracts.enums import ErrorCode, ErrorReason
from pgfacade.contracts.envelopes import Failure
from pgfacade.contracts.queries import QueryRun, QueryRunInput
from pgfacade.presentation.middleware import RequestBodyLimit
from pgfacade.webapp import create_app
from pgfacade.webmcp import create_mcp, create_mcp_http_app, resolve_mcp_context
from tests.support import fails, successful

TEST_KEY = "security-test-bearer-key"
TEST_HEADERS = {"Authorization": f"Bearer {TEST_KEY}"}


@pytest.fixture
def settings() -> PgSettings:
    return PgSettings(_env_file=None, keys={TEST_KEY: Principal(name="writer")}, mcp_key=TEST_KEY)


def test_default_capabilities_are_restricted() -> None:
    settings = PgSettings(_env_file=None)
    assert not any((settings.allow_raw_sql, settings.allow_ddl, settings.allow_admin, settings.allow_migrate, settings.allow_listen))
    assert not Principal().ddl


@pytest.mark.parametrize("factory", [create_app, create_mcp_http_app])
def test_network_factories_reject_missing_keys(factory: Callable) -> None:
    with pytest.raises(ValueError, match="API key"):
        factory(PgSettings(_env_file=None))


@pytest.mark.parametrize("factory", [create_app, create_mcp])
def test_network_factories_reject_mismatched_facade(factory: Callable, settings: PgSettings) -> None:
    other = PgSettings(_env_file=None, keys={"other": Principal()})
    with pytest.raises(ValueError, match="server settings"):
        factory(settings, PgFacade(other))


@pytest.mark.parametrize("key", [None, "bad-key"])
def test_empty_configuration_never_resolves_anonymous(key: str | None) -> None:
    with pytest.raises(AuthenticationNotConfigured, match="not configured"):
        resolve_principal(PgSettings(_env_file=None), key)


@pytest.mark.parametrize("key", [None, "wrong-key", ""])
def test_bad_bearer_keys_are_denied(settings: PgSettings, key: str | None) -> None:
    with pytest.raises(Unauthenticated):
        resolve_principal(settings, key)


def test_valid_key_resolves_exact_principal(settings: PgSettings) -> None:
    assert resolve_principal(settings, TEST_KEY).name == "writer"


def test_keys_are_omitted_from_normal_representations(settings: PgSettings) -> None:
    assert TEST_KEY not in repr(settings)
    assert "keys" not in settings.model_dump()


@pytest.mark.parametrize("contents", ["{}", "[]", '{"sentinel-private-key": {"name": "x", "unknown": true}}', "not-json"])
def test_empty_or_invalid_key_file_fails_closed(tmp_path: Path, contents: str) -> None:
    path = tmp_path / "keys.json"
    path.write_text(contents)
    if contents == "{}":
        settings = PgSettings(_env_file=None, keys_file=path)
        with pytest.raises(ValueError, match="API key"):
            create_app(settings)
    else:
        with pytest.raises(ValidationError) as error:
            PgSettings(_env_file=None, keys_file=path)
        assert "sentinel-private-key" not in str(error.value)


def test_key_file_validates_principal_and_inline_precedence(tmp_path: Path) -> None:
    path = tmp_path / "keys.json"
    path.write_text('{"file-key": {"name": "file"}, "shared": {"name": "old"}}')
    settings = PgSettings(_env_file=None, keys_file=path, keys={"shared": Principal(name="inline")})
    assert settings.keys["file-key"].name == "file"
    assert settings.keys["shared"].name == "inline"


@pytest.mark.parametrize("key", ["", "white space", "line\nbreak"])
def test_invalid_configured_keys_are_rejected(key: str) -> None:
    with pytest.raises(ValidationError):
        PgSettings(_env_file=None, keys={key: Principal()})


def test_api_missing_and_wrong_keys_return_401(settings: PgSettings) -> None:
    client = TestClient(create_app(settings))
    for headers, reason in (
        ({}, ErrorReason.CREDENTIAL_MISSING),
        ({"Authorization": "Bearer synthetic-invalid-credential"}, ErrorReason.CREDENTIAL_INVALID),
    ):
        response = client.post("/server/whoami", json={"input": {}}, headers=headers)
        assert response.status_code == 401
        assert response.headers["WWW-Authenticate"] == "Bearer"
        assert Failure.model_validate_json(response.content).error.reason is reason
        assert "synthetic-invalid-credential" not in response.text
    assert client.post("/server/whoami", json={"input": {}}, headers=TEST_HEADERS).json()["outcome"]["data"]["principal"] == "writer"


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("POST", "/sql/query", {"sql": "SELECT 1"}),
        ("POST", "/sql/execute", {"sql": "SELECT 1"}),
        ("POST", "/sql/explain", {"sql": "SELECT 1"}),
        ("POST", "/schema/create", {"name": "forbidden"}),
        ("POST", "/migration/init", {}),
        ("POST", "/maint/backend", {"action": "cancel", "pid": 0}),
        ("POST", "/event/notify", {"channel": "blocked", "payload": "x"}),
        ("POST", "/event/wait", {"channels": ["blocked"], "timeout_s": 0.01}),
        ("GET", "/events/blocked", None),
        ("POST", "/server/settings", {}),
        ("POST", "/diag/activity", {}),
        ("POST", "/diag/locks", {}),
        ("POST", "/diag/top_queries", {}),
        ("POST", "/diag/table_stats", {}),
        ("POST", "/diag/unused_indexes", {}),
        ("POST", "/event/watches", {}),
        ("POST", "/query/run", {"name": "health.connections"}),
        ("POST", "/query/run", {"name": "health.long_running"}),
        ("POST", "/query/run", {"name": "health.idle_in_transaction"}),
        ("POST", "/query/run", {"name": "statements.top_total_time"}),
    ],
)
def test_restricted_endpoints_deny_before_database_access(
    settings: PgSettings, method: str, path: str, body: dict[str, str] | None
) -> None:
    client = TestClient(create_app(settings), headers=TEST_HEADERS)
    response = client.request(method, path, json={"input": body} if body is not None else None)
    assert response.status_code == 403, response.text


async def test_http_mcp_never_uses_stdio_key(settings: PgSettings, monkeypatch: pytest.MonkeyPatch) -> None:
    request = Request({"type": "http", "headers": []})
    monkeypatch.setattr("pgfacade.webmcp.get_http_request", lambda: request)
    with pytest.raises(Unauthenticated, match="missing API key"):
        await resolve_mcp_context(settings)


async def test_http_mcp_uses_request_key(settings: PgSettings, monkeypatch: pytest.MonkeyPatch) -> None:
    request = Request({"type": "http", "headers": [(b"authorization", f"Bearer {TEST_KEY}".encode())]})
    monkeypatch.setattr("pgfacade.webmcp.get_http_request", lambda: request)
    assert (await resolve_mcp_context(settings)).principal.name == "writer"


async def test_stdio_mcp_uses_configured_key(settings: PgSettings, monkeypatch: pytest.MonkeyPatch) -> None:

    def no_request() -> None:
        raise RuntimeError("No active HTTP request found.")

    monkeypatch.setattr("pgfacade.webmcp.get_http_request", no_request)
    assert (await resolve_mcp_context(settings)).principal.name == "writer"


async def test_stdio_mcp_without_keys_runs_as_the_local_principal(monkeypatch: pytest.MonkeyPatch) -> None:

    def no_request() -> None:
        raise RuntimeError("No active HTTP request found.")

    monkeypatch.setattr("pgfacade.webmcp.get_http_request", no_request)
    settings = PgSettings(_env_file=None)
    create_mcp(settings)
    assert (await resolve_mcp_context(settings)).principal == ANONYMOUS


async def test_stdio_mcp_with_keys_still_requires_its_key(monkeypatch: pytest.MonkeyPatch) -> None:

    def no_request() -> None:
        raise RuntimeError("No active HTTP request found.")

    monkeypatch.setattr("pgfacade.webmcp.get_http_request", no_request)
    with pytest.raises(Unauthenticated, match="missing API key"):
        await resolve_mcp_context(PgSettings(_env_file=None, keys={TEST_KEY: Principal(name="writer")}))


@pytest.mark.parametrize("headers", [[], [(b"authorization", b"Bearer any-key")]])
async def test_http_mcp_without_keys_is_never_local(headers: list[tuple[bytes, bytes]], monkeypatch: pytest.MonkeyPatch) -> None:
    request = Request({"type": "http", "headers": headers})
    monkeypatch.setattr("pgfacade.webmcp.get_http_request", lambda: request)
    with pytest.raises(AuthenticationNotConfigured):
        await resolve_mcp_context(PgSettings(_env_file=None))


async def test_unexpected_mcp_context_failure_does_not_fallback(settings: PgSettings, monkeypatch: pytest.MonkeyPatch) -> None:

    def broken_request() -> None:
        raise ValueError("context failed")

    monkeypatch.setattr("pgfacade.webmcp.get_http_request", broken_request)
    with pytest.raises(ValueError, match="context failed"):
        await resolve_mcp_context(settings)


@pytest.mark.parametrize("headers", [[], [(b"content-length", b"1")]])
async def test_request_limit_counts_chunked_body(headers: list[tuple[bytes, bytes]]) -> None:
    called = False
    outgoing: list[Message] = []
    incoming = iter(
        [{"type": "http.request", "body": b"1234", "more_body": True}, {"type": "http.request", "body": b"5678", "more_body": False}]
    )

    async def app(scope: Scope, receive: Receive, send: Send) -> None:
        nonlocal called
        called = True

    async def receive() -> Message:
        return next(incoming)

    async def send(message: Message) -> None:
        outgoing.append(message)

    middleware = RequestBodyLimit(app, max_bytes=7)
    await middleware({"type": "http", "headers": headers}, receive, send)
    assert not called
    assert outgoing[0]["status"] == 413
    failure = Failure.model_validate_json(b"".join(message.get("body", b"") for message in outgoing))
    assert failure.error.status == 413 and failure.error.code == "request_too_large"


async def test_request_limit_accepts_exact_bound_and_replays_body() -> None:
    outgoing: list[Message] = []
    incoming = iter(
        [{"type": "http.request", "body": b"1234", "more_body": True}, {"type": "http.request", "body": b"5678", "more_body": False}]
    )

    async def app(scope: Scope, receive: Receive, send: Send) -> None:
        outgoing.append(await receive())

    async def receive() -> Message:
        return next(incoming)

    async def send(message: Message) -> None:
        outgoing.append(message)

    await RequestBodyLimit(app, max_bytes=8)({"type": "http"}, receive, send)
    assert outgoing == [{"type": "http.request", "body": b"12345678", "more_body": False}]


def test_api_body_limit_is_installed(settings: PgSettings) -> None:
    data = settings.model_dump()
    data.update(keys=settings.keys, max_request_bytes=16)
    limited = PgSettings.model_validate(data)
    client = TestClient(create_app(limited), headers=TEST_HEADERS)
    assert client.post("/sql/query", content=b"x" * 17).status_code == 413


async def test_mcp_restricted_tool_surface(settings: PgSettings) -> None:
    server = create_mcp(settings)
    tools = await server.list_tools()
    names = {tool.name for tool in tools}
    assert not names & {"pg_sql_query", "pg_sql_execute", "pg_table_create", "pg_migration_run", "pg_event_wait", "pg_event_notify"}


async def test_diagnostics_require_principal_admin_even_when_server_allows(settings: PgSettings) -> None:
    data = settings.model_dump()
    data.update(keys=settings.keys, allow_admin=True)
    db = PgFacade(PgSettings.model_validate(data)).as_(settings.keys[TEST_KEY])
    with fails(code=ErrorCode.FORBIDDEN):
        await successful(db.call(QueryRun(input=QueryRunInput(name="health.long_running"))))


@pytest.mark.parametrize("factory", [create_app, create_mcp])
def test_factory_uses_supplied_facade_settings(factory: Callable, settings: PgSettings) -> None:
    assert factory(db=PgFacade(settings)) is not None


async def test_request_body_read_timeout() -> None:
    outgoing: list[Message] = []

    async def app(scope: Scope, receive: Receive, send: Send) -> None:
        pytest.fail("A timed-out request must not reach the application")

    async def receive() -> Message:
        await asyncio.Event().wait()
        return {"type": "http.disconnect"}

    async def send(message: Message) -> None:
        outgoing.append(message)

    await RequestBodyLimit(app, max_bytes=8, timeout_s=0.01)({"type": "http"}, receive, send)
    assert outgoing[0]["status"] == 408
    failure = Failure.model_validate_json(b"".join(message.get("body", b"") for message in outgoing))
    assert failure.error.status == 408 and failure.error.code == "timeout"


@pytest.mark.parametrize("principal", [{"unknown": True}, {"name": 123}, {"role": []}])
def test_inline_key_validation_errors_do_not_disclose_credentials(principal: dict[str, object]) -> None:
    private_key = "inline-credential-must-stay-redacted"
    with pytest.raises(ValidationError) as error:
        PgSettings(_env_file=None, keys={private_key: principal})
    assert private_key not in str(error.value)


def test_key_assembly_does_not_mutate_caller_mapping(tmp_path: Path) -> None:
    path = tmp_path / "keys.json"
    path.write_text('{"file-key": {"name": "file"}}')
    inline = {"inline-key": Principal(name="inline")}
    settings = PgSettings(_env_file=None, keys_file=path, keys=inline)
    assert set(inline) == {"inline-key"}
    assert set(settings.keys) == {"inline-key", "file-key"}
    with pytest.raises(ValidationError, match="frozen"):
        settings.keys_file = None


def test_pool_bounds_are_validated_at_configuration_boundary() -> None:
    with pytest.raises(ValidationError, match="pool_min must not exceed pool_max"):
        PgSettings(_env_file=None, pool_min=3, pool_max=2)
    assert PgSettings(_env_file=None, pool_min=0, pool_max=1).pool_min == 0
