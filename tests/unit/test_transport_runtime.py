"""Shared transport runtime: who owns the database lifetime, who the MCP caller is, and what that caller is shown."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from fastmcp import Client, FastMCP
from starlette.requests import Request

from pgfacade import PgFacade, PgSettings, Principal, Unauthenticated
from pgfacade.application.registry import OPERATIONS
from pgfacade.contracts.envelopes import Failure
from pgfacade.infrastructure.startup import StartupCommand
from pgfacade.presentation.runtime import server_runtime
from pgfacade.webapp import create_app
from pgfacade.webmcp import create_mcp, create_mcp_http_app, resolve_mcp_http_context

READER, ADMIN = "reader-key", "admin-key"
_CATALOG = {f"pg_{spec.area}_{spec.action}" for spec in OPERATIONS.values()}
_WRITES = {"pg_rows_insert", "pg_rows_update", "pg_rows_delete", "pg_table_create", "pg_sql_query", "pg_lifecycle_run"}


class TrackingFacade(PgFacade):
    """Records pool lifetime calls without a database."""

    def __init__(self, settings: PgSettings) -> None:
        super().__init__(settings)
        self.opens = 0
        self.closes = 0
        self._tracked_open = False

    @property
    def is_open(self) -> bool:
        return self._tracked_open

    async def open(self) -> None:
        self.opens += 1
        self._tracked_open = True

    async def close(self) -> None:
        self.closes += 1
        self._tracked_open = False


def _settings(**overrides: object) -> PgSettings:
    values: dict[str, object] = {
        "keys": {
            READER: Principal(name="reader", read_only=True),
            ADMIN: Principal(name="admin", ddl=True, sql=True, admin=True, migrate=True, listen=True),
        },
        "mcp_key": ADMIN,
        "allow_admin": True,
        "allow_ddl": True,
        "allow_raw_sql": True,
        "allow_migrate": True,
        "allow_listen": True,
    }
    return PgSettings(_env_file=None, **(values | overrides))


def _marker_command(marker: Path) -> StartupCommand:
    script = "import sys,time; from pathlib import Path; Path(sys.argv[1]).touch(); print('READY', flush=True); time.sleep(60)"
    return StartupCommand(argv=(sys.executable, "-u", "-c", script, str(marker)), timeout_s=5, stop_timeout_s=0.2)


def _request(key: str | None) -> Request:
    headers = [] if key is None else [(b"authorization", f"Bearer {key}".encode())]
    return Request({"type": "http", "headers": headers})


def _no_request() -> Request:
    raise RuntimeError("No active HTTP request found.")


# ---------------------------------------------------------------- database lifetime


async def test_runtime_opens_and_closes_a_facade_it_received_closed(tmp_path: Path) -> None:
    settings = _settings(startup_command=_marker_command(tmp_path / "started"))
    db = TrackingFacade(settings)
    async with server_runtime(settings, db, None, require_auth=True).running():
        assert db.is_open and (tmp_path / "started").exists()
    assert (db.opens, db.closes) == (1, 1)


async def test_runtime_leaves_an_open_facade_and_its_startup_command_to_the_owner(tmp_path: Path) -> None:
    settings = _settings(startup_command=_marker_command(tmp_path / "started"))
    db = TrackingFacade(settings)
    await db.open()
    async with server_runtime(settings, db, None, require_auth=True).running():
        assert db.is_open
    assert db.is_open and (db.opens, db.closes) == (1, 0)
    assert not (tmp_path / "started").exists()


def test_embedded_mcp_app_shares_the_host_database_lifetime() -> None:
    settings = _settings()
    db = TrackingFacade(settings)
    with TestClient(create_app(settings, db)) as api:
        assert db.opens == 1 and api.get("/healthz").json()["ok"] is True
        with TestClient(create_mcp_http_app(settings, db)):
            assert db.opens == 1
        assert db.is_open and db.closes == 0
        assert api.get("/healthz").json()["ok"] is True
    assert (db.opens, db.closes) == (1, 1)


# ---------------------------------------------------------------- MCP HTTP caller


async def test_mcp_http_context_without_a_request_never_uses_the_stdio_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("pgfacade.webmcp.get_http_request", _no_request)
    with pytest.raises(Unauthenticated, match="missing API key"):
        await resolve_mcp_http_context(_settings())


async def test_mcp_http_context_uses_the_request_bearer(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("pgfacade.webmcp.get_http_request", lambda: _request(READER))
    assert (await resolve_mcp_http_context(_settings())).principal.name == "reader"


async def test_mcp_http_server_called_outside_a_request_is_unauthenticated() -> None:
    settings = _settings()
    server = create_mcp_http_app(settings, TrackingFacade(settings)).state.fastmcp_server
    assert isinstance(server, FastMCP)
    async with Client(server) as client:
        response = await client.call_tool("pg_server_whoami", {"request": {"kind": "server.whoami", "input": {}}}, raise_on_error=False)
    assert response.is_error and response.structured_content is not None
    failure = Failure.model_validate(response.structured_content)
    assert failure.error.status == 401 and failure.error.code == "unauthenticated"


# ---------------------------------------------------------------- tools/list


async def _tools(server: FastMCP) -> set[str]:
    return {tool.name for tool in await server.list_tools()}


@pytest.mark.parametrize(("key", "principal"), [(READER, "reader"), (ADMIN, "admin")])
async def test_mcp_http_tools_match_the_rest_operation_list_for_each_caller(
    key: str, principal: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = _settings()
    db = TrackingFacade(settings)
    server = create_mcp_http_app(settings, db).state.fastmcp_server
    monkeypatch.setattr("pgfacade.webmcp.get_http_request", lambda: _request(key))
    tools = await _tools(server)
    with TestClient(create_app(settings, db), headers={"Authorization": f"Bearer {key}"}) as api:
        operations = {f"pg_{item['op'].replace('.', '_', 1)}" for item in api.get("/ops").json()}
    assert tools == operations
    assert (tools == _CATALOG) is (principal == "admin")
    assert bool(tools & _WRITES) is (principal == "admin")
    assert {"pg_rows_select", "pg_server_whoami", "pg_table_describe"} <= tools


@pytest.mark.parametrize("key", [None, "unknown-key"])
async def test_mcp_http_discovery_without_a_usable_credential_shows_the_server_catalog(
    key: str | None, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = _settings(allow_raw_sql=False)
    server = create_mcp_http_app(settings, TrackingFacade(settings)).state.fastmcp_server
    monkeypatch.setattr("pgfacade.webmcp.get_http_request", lambda: _request(key))
    tools = await _tools(server)
    assert "pg_rows_insert" in tools and "pg_sql_query" not in tools


async def test_stdio_tools_are_narrowed_to_the_configured_key() -> None:
    settings = _settings(mcp_key=READER)
    async with Client(create_mcp(settings, TrackingFacade(settings))) as client:
        tools = {tool.name for tool in await client.list_tools()}
    assert "pg_rows_select" in tools and not tools & _WRITES
