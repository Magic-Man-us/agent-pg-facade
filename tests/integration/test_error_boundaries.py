from __future__ import annotations

import psycopg
import pytest
from fastapi.testclient import TestClient
from fastmcp import Client

from pgfacade import PgFacade, PgSettings, Principal
from pgfacade.application.errors import IdentityProviderInvalidResponse, NoMatchingPolicy
from pgfacade.contracts.admin import ServerInfo, ServerInfoGet, ServerInfoGetInput
from pgfacade.contracts.base import Contract, RequestContract
from pgfacade.contracts.enums import ErrorReason, Operation, ValidationOrigin
from pgfacade.contracts.envelopes import Failure, ResponseEnvelope, ValidationDetails
from pgfacade.webapp import create_app
from pgfacade.webmcp import create_mcp
from tests.support import swapped_handler

KEY = "synthetic-boundary-key"


class InMemoryFacade(PgFacade):
    async def open(self) -> None:
        return None

    async def close(self) -> None:
        return None


async def invalid_server_info(db: PgFacade, request: RequestContract[Contract]) -> Contract:
    return ServerInfo.model_validate({"server_version": "synthetic-private-result"})


async def test_native_result_validation_has_identical_http_and_mcp_server_errors() -> None:
    settings = PgSettings(_env_file=None, keys={KEY: Principal()}, mcp_key=KEY)
    facade = InMemoryFacade(settings)
    with swapped_handler(Operation.SERVER_INFO, invalid_server_info):
        failures: list[Failure] = []
        client = TestClient(create_app(settings, facade), headers={"Authorization": f"Bearer {KEY}"}, raise_server_exceptions=False)
        for path in ("/server/info", "/call"):
            response = client.post(path, json={"kind": "server.info", "input": {}})
            assert response.status_code == 500
            envelope = ResponseEnvelope[ServerInfo].model_validate_json(response.content)
            assert envelope.kind == "server.info"
            assert isinstance(envelope.outcome, Failure)
            failures.append(envelope.outcome)
        async with Client(create_mcp(settings, facade)) as mcp:
            result = await mcp.call_tool("pg_server_info", {"request": {"kind": "server.info", "input": {}}}, raise_on_error=False)
            assert result.is_error
            envelope = ResponseEnvelope[ServerInfo].model_validate(result.structured_content)
            assert envelope.kind == "server.info"
            assert isinstance(envelope.outcome, Failure)
            failures.append(envelope.outcome)
        assert failures[0] == failures[1] == failures[2]
        native = await facade.call(ServerInfoGet(input=ServerInfoGetInput()))
    assert native.outcome == failures[0]
    assert failures[0].error.reason is ErrorReason.RESPONSE_INVALID
    assert isinstance(failures[0].error.details, ValidationDetails)
    assert failures[0].error.details.origin is ValidationOrigin.RESPONSE
    assert failures[0].error.code == "internal_error"
    assert "synthetic-private-result" not in failures[0].model_dump_json()


async def test_http_and_mcp_input_validation_provide_safe_typed_issues() -> None:
    settings = PgSettings(_env_file=None, keys={KEY: Principal()}, mcp_key=KEY)
    facade = InMemoryFacade(settings)
    request = {"kind": "synthetic-private-operation", "input": {}}
    http = TestClient(create_app(settings, facade), headers={"Authorization": f"Bearer {KEY}"})
    response = http.post("/server/info", json=request)
    assert response.status_code == 422
    failures = [Failure.model_validate_json(response.content)]
    async with Client(create_mcp(settings, facade)) as mcp:
        result = await mcp.call_tool("pg_server_info", {"request": request}, raise_on_error=False)
        assert result.is_error
        failures.append(Failure.model_validate(result.structured_content))
    for failure in failures:
        assert failure.error.status == 422
        assert failure.error.details is not None
        assert failure.error.details.issues[0].code == "literal_error"
        assert failure.error.details.issues[0].path[-1] == "kind"
        assert "synthetic-private-operation" not in failure.model_dump_json()


@pytest.mark.parametrize(
    ("error", "reason"),
    [
        (psycopg.errors.UniqueViolation("synthetic-private-sql"), ErrorReason.DATABASE_CONFLICT),
        (NoMatchingPolicy("No matching policy allows this request"), ErrorReason.POLICY_NO_MATCH),
        (IdentityProviderInvalidResponse("Identity provider returned an invalid identity"), ErrorReason.IDENTITY_PROVIDER_INVALID_RESPONSE),
    ],
)
async def test_structured_failures_match_across_python_http_and_mcp(error: Exception, reason: ErrorReason) -> None:
    settings = PgSettings(_env_file=None, keys={KEY: Principal()}, mcp_key=KEY)
    facade = InMemoryFacade(settings)
    request = ServerInfoGet(input=ServerInfoGetInput())

    async def failing_server_info(db: PgFacade, received: RequestContract[Contract]) -> Contract:
        raise error

    with swapped_handler(Operation.SERVER_INFO, failing_server_info):
        native = await facade.call(request)
        assert isinstance(native.outcome, Failure)
        assert native.outcome.error.reason is reason
        http = TestClient(create_app(settings, facade), headers={"Authorization": f"Bearer {KEY}"})
        response = http.post("/call", json=request.model_dump(mode="json"))
        assert response.status_code == native.outcome.error.status
        assert "www-authenticate" not in response.headers
        assert ResponseEnvelope[ServerInfo].model_validate_json(response.content) == native
        async with Client(create_mcp(settings, facade)) as mcp:
            result = await mcp.call_tool("pg_server_info", {"request": request.model_dump(mode="json")}, raise_on_error=False)
            assert result.is_error
            assert ResponseEnvelope[ServerInfo].model_validate(result.structured_content) == native
    assert "synthetic-private-sql" not in native.model_dump_json()
    assert "502" in http.get("/openapi.json").json()["paths"]["/call"]["post"]["responses"]
