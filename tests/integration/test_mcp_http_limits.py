from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

import pytest
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient

from pgfacade import MyApp, PgSettings, Principal
from pgfacade.contracts.envelopes import Failure
from pgfacade.shared.enums import McpTransport
from pgfacade.shared.types import McpHttpTransport, SecurityFlag
from pgfacade.webmcp import create_mcp_http_app


class LifespanFacade(MyApp):
    opened: SecurityFlag = False

    async def open(self) -> None:
        self.opened = True

    async def close(self) -> None:
        self.opened = False


@pytest.mark.parametrize("transport", [McpTransport.HTTP, McpTransport.STREAMABLE_HTTP, McpTransport.SSE])
async def test_mcp_http_rejects_oversized_body(transport: McpHttpTransport) -> None:
    settings = PgSettings(_env_file=None, keys={"test": Principal()}, max_request_bytes=8)
    app = create_mcp_http_app(settings, transport=transport)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://localhost") as client:
        response = await client.post("/mcp" if transport != McpTransport.SSE else "/messages/", content=b"x" * 9)
    assert response.status_code == 413
    result = Failure.model_validate_json(response.content)
    assert result.error.status == 413
    assert result.error.code == "request_too_large"


@pytest.mark.parametrize("transport", [McpTransport.HTTP, McpTransport.STREAMABLE_HTTP, McpTransport.SSE])
async def test_mcp_http_times_out_incomplete_request(transport: McpHttpTransport) -> None:
    settings = PgSettings(_env_file=None, keys={"test": Principal()}, request_read_timeout_s=0.01)
    app = create_mcp_http_app(settings, transport=transport)

    async def stalled_body() -> AsyncIterator[bytes]:
        yield b"{"
        await asyncio.Event().wait()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://localhost") as client:
        response = await client.post("/mcp" if transport != McpTransport.SSE else "/messages/", content=stalled_body())
    assert response.status_code == 408
    result = Failure.model_validate_json(response.content)
    assert result.error.status == 408
    assert result.error.code == "timeout"


@pytest.mark.parametrize("transport", [McpTransport.HTTP, McpTransport.SSE])
def test_mcp_http_app_preserves_database_lifespan(transport: McpHttpTransport) -> None:
    settings = PgSettings(_env_file=None, keys={"test": Principal()})
    db = LifespanFacade(settings)
    app = create_mcp_http_app(settings, db, transport=transport)
    assert not db.opened
    with TestClient(app):
        assert db.opened
    assert not db.opened
