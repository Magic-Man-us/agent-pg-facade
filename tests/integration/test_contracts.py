from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from fastmcp import Client

from pgfacade import REGISTRY, MyApp, PgSettings, Principal
from pgfacade.contracts.admin import WhoAmI
from pgfacade.contracts.base import Contract, Count, RequestContract
from pgfacade.contracts.envelopes import Failure, ResponseEnvelope, Success
from pgfacade.contracts.streaming import EventStreamResponse
from pgfacade.webapp import create_app
from pgfacade.webmcp import create_mcp

KEY = "contract-test-key"
HEADERS = {"Authorization": f"Bearer {KEY}"}


@pytest.fixture
def settings() -> PgSettings:
    return PgSettings(_env_file=None, keys={KEY: Principal(name="contract-reader", read_only=True)}, mcp_key=KEY)


def test_typed_request_and_generated_route_return_the_same_response(settings: PgSettings) -> None:
    client = TestClient(create_app(settings), headers=HEADERS)
    expected = client.post("/server/whoami", json={"kind": "server.whoami", "input": {}})
    dispatched = client.post("/call", json={"kind": "server.whoami", "input": {}})
    assert expected.status_code == dispatched.status_code == 200
    assert expected.json() == dispatched.json()
    assert set(expected.json()) == {"kind", "outcome"}
    assert expected.json()["kind"] == "server.whoami"
    assert expected.json()["outcome"]["status"] == "success"
    assert expected.json()["outcome"]["data"]["principal"] == "contract-reader"


@pytest.mark.parametrize(
    ("method", "path", "body", "expected_status"),
    [
        ("POST", "/server/whoami", {}, 422),
        ("POST", "/server/whoami", {"kind": "rows.select", "input": {"table": "private"}}, 422),
        ("POST", "/server/whoami", {"kind": "server.whoami", "input": {}, "extra": "synthetic-secret"}, 422),
        ("POST", "/call", {"kind": "unknown.operation", "input": {}}, 422),
        ("POST", "/rows/insert", {"kind": "rows.insert", "input": {"table": "private", "rows": [{"value": "synthetic-secret"}]}}, 403),
        ("GET", "/missing", None, 404),
        ("GET", "/server/whoami", None, 405),
    ],
)
def test_rest_error_statuses_share_one_typed_contract(
    settings: PgSettings, method: str, path: str, body: dict[str, object] | None, expected_status: int
) -> None:
    client = TestClient(create_app(settings), headers=HEADERS)
    response = client.request(method, path, json=body)
    assert response.status_code == expected_status
    if expected_status == 403:
        envelope = ResponseEnvelope[Contract].model_validate_json(response.content)
        assert envelope.kind == "rows.insert"
        failure = envelope.outcome
        assert isinstance(failure, Failure)
        assert set(response.json()) == {"kind", "outcome"}
    else:
        failure = Failure.model_validate_json(response.content)
        assert set(response.json()) == {"status", "error"}
    assert failure.status == "error"
    assert failure.error.status == expected_status
    assert "synthetic-secret" not in response.text
    assert "detail" not in response.json()


def test_authentication_failure_uses_the_same_contract(settings: PgSettings) -> None:
    response = TestClient(create_app(settings)).post("/server/whoami", json={"kind": "server.whoami", "input": {}})
    failure = Failure.model_validate_json(response.content)
    assert response.status_code == failure.error.status == 401
    assert failure.error.code == "unauthenticated"
    assert response.headers["WWW-Authenticate"] == "Bearer"


def test_request_limit_failure_uses_the_same_contract() -> None:
    settings = PgSettings(_env_file=None, keys={KEY: Principal()}, max_request_bytes=8)
    response = TestClient(create_app(settings), headers=HEADERS).post("/call", content=b"x" * 9)
    failure = Failure.model_validate_json(response.content)
    assert response.status_code == failure.error.status == 413
    assert failure.error.code == "request_too_large"


def test_malformed_json_does_not_echo_input(settings: PgSettings) -> None:
    response = TestClient(create_app(settings), headers=HEADERS).post(
        "/call", content=b'{"request":"synthetic-private-input"', headers={"Content-Type": "application/json"}
    )
    failure = Failure.model_validate_json(response.content)
    assert response.status_code == failure.error.status == 422
    assert "synthetic-private-input" not in response.text


class BrokenFacade(MyApp):
    async def _execute(self, request: RequestContract[Contract]) -> Contract:
        raise RuntimeError("synthetic-internal-credential")


def test_internal_exception_uses_redacted_error_contract(settings: PgSettings) -> None:
    client = TestClient(create_app(settings, BrokenFacade(settings)), headers=HEADERS, raise_server_exceptions=False)
    response = client.post("/server/whoami", json={"kind": "server.whoami", "input": {}})
    envelope = ResponseEnvelope[WhoAmI].model_validate_json(response.content)
    failure = envelope.outcome
    assert isinstance(failure, Failure)
    assert envelope.kind == "server.whoami"
    assert response.status_code == failure.error.status == 500
    assert failure.error.code == "internal_error"
    assert "synthetic-internal-credential" not in response.text


def _references(value: object) -> set[str]:
    if isinstance(value, dict):
        result = {value["$ref"].rsplit("/", 1)[-1]} if "$ref" in value else set()
        return result | {item for child in value.values() for item in _references(child)}
    if isinstance(value, list):
        return {item for child in value for item in _references(child)}
    return set()


def _reachable_references(schema: dict[str, object], definitions: dict[str, object]) -> set[str]:
    seen: set[str] = set()
    pending = _references(schema)
    while pending - seen:
        name = next(iter(pending - seen))
        seen.add(name)
        pending |= _references(definitions[name])
    return seen


def test_openapi_documents_envelopes_for_each_operation_and_dispatch(settings: PgSettings) -> None:
    schema = TestClient(create_app(settings)).get("/openapi.json").json()
    definitions = schema["components"]["schemas"]
    for spec in REGISTRY.values():
        operation = schema["paths"][f"/{spec.area}/{spec.action}"]["post"]
        request_schema = operation["requestBody"]["content"]["application/json"]["schema"]
        request_refs = _reachable_references(request_schema, definitions)
        assert spec.request.__name__ in request_refs
        success_schema = operation["responses"]["200"]["content"]["application/json"]["schema"]
        response_refs = _reachable_references(success_schema, definitions)
        assert spec.response.__name__ in response_refs
        assert "Failure" in response_refs
        for code in ("401", "403", "404", "422", "500"):
            failure_schema = operation["responses"][code]["content"]["application/json"]["schema"]
            assert "Failure" in _reachable_references(failure_schema, definitions)
    call_schema = schema["paths"]["/call"]["post"]["responses"]["200"]["content"]["application/json"]["schema"]
    call_refs = _reachable_references(call_schema, definitions)
    assert {spec.response.__name__ for spec in REGISTRY.values()} <= call_refs


class InMemoryFacade(MyApp):
    async def open(self) -> None:
        return None

    async def close(self) -> None:
        return None


async def test_mcp_success_and_failure_share_rest_contract(settings: PgSettings) -> None:
    server = create_mcp(settings, InMemoryFacade(settings))
    async with Client(server) as client:
        success = await client.call_tool("pg_server_whoami", {"request": {"kind": "server.whoami", "input": {}}})
        assert success.structured_content is not None
        assert success.structured_content["kind"] == "server.whoami"
        assert success.structured_content["outcome"]["status"] == "success"
        assert set(success.structured_content) == {"kind", "outcome"}
        assert success.structured_content["outcome"]["data"]["principal"] == "contract-reader"
        failed = await client.call_tool("pg_server_whoami", {"request": {"kind": "unknown.operation", "input": {}}}, raise_on_error=False)
        assert failed.is_error
        assert failed.structured_content is not None
        failure = Failure.model_validate(failed.structured_content)
        assert failure.error.status == 422
        assert set(failed.structured_content) == {"status", "error"}
        tools = {tool.name: tool for tool in await client.list_tools()}
        tool = tools["pg_server_whoami"]
        assert set(tool.input_schema["properties"]) == {"request"}
        assert tool.output_schema["properties"]["outcome"]["discriminator"]["propertyName"] == "status"


async def test_mcp_unknown_tool_and_missing_request_use_error_contract(settings: PgSettings) -> None:
    async with Client(create_mcp(settings, InMemoryFacade(settings))) as client:
        for name, arguments, status in (
            ("pg_missing_operation", {"request": {}}, 404),
            ("pg_server_whoami", {}, 422),
        ):
            response = await client.call_tool(name, arguments, raise_on_error=False)
            assert response.is_error
            assert response.structured_content is not None
            failure = Failure.model_validate(response.structured_content)
            assert failure.error.status == status


async def test_mcp_authentication_failure_is_structured() -> None:
    settings = PgSettings(_env_file=None, keys={KEY: Principal()})
    async with Client(create_mcp(settings, InMemoryFacade(settings))) as client:
        response = await client.call_tool("pg_server_whoami", {"request": {"kind": "server.whoami", "input": {}}}, raise_on_error=False)
        assert response.is_error
        assert response.structured_content is not None
        failure = Failure.model_validate(response.structured_content)
        assert failure.error.status == 401
        assert failure.error.code == "unauthenticated"


async def test_mcp_internal_error_is_structured_and_redacted(settings: PgSettings) -> None:
    class BrokenInMemoryFacade(InMemoryFacade):
        async def _execute(self, request: RequestContract[Contract]) -> Contract:
            raise RuntimeError("synthetic-internal-credential")

    async with Client(create_mcp(settings, BrokenInMemoryFacade(settings))) as client:
        response = await client.call_tool("pg_server_whoami", {"request": {"kind": "server.whoami", "input": {}}}, raise_on_error=False)
        assert response.is_error
        assert response.structured_content is not None
        envelope = ResponseEnvelope[WhoAmI].model_validate(response.structured_content)
        failure = envelope.outcome
        assert isinstance(failure, Failure)
        assert envelope.kind == "server.whoami"
        assert failure.error.status == 500
        assert "synthetic-internal-credential" not in failure.model_dump_json()


def test_sse_notification_and_stream_failure_use_typed_envelopes(monkeypatch: pytest.MonkeyPatch) -> None:
    from collections.abc import AsyncIterator

    from pgfacade.contracts.events import Notification

    notification = Notification.model_validate_json('{"channel":"events","payload":"hello","pid":7,"received_at":"2026-10-24T12:00:00Z"}')

    async def notifications(*args: object, **kwargs: object) -> AsyncIterator[Notification]:
        yield notification
        raise RuntimeError("synthetic-stream-credential")

    monkeypatch.setattr("pgfacade.application.operations.events.listen", notifications)
    settings = PgSettings(_env_file=None, keys={KEY: Principal(listen=True)}, allow_listen=True)
    response = TestClient(create_app(settings), headers=HEADERS).get("/events/events")
    assert response.status_code == 200
    data = [line.removeprefix("data: ") for line in response.text.splitlines() if line.startswith("data: ")]
    assert len(data) == 2
    first = EventStreamResponse.model_validate_json(data[0])
    assert first.kind == "event.stream"
    assert isinstance(first.outcome, Success)
    assert first.outcome.data == notification
    second = EventStreamResponse.model_validate_json(data[1])
    assert second.kind == "event.stream"
    assert isinstance(second.outcome, Failure)
    assert second.outcome.error.status == 500
    assert "synthetic-stream-credential" not in response.text


async def test_wrong_operation_result_is_a_shared_internal_error(settings: PgSettings) -> None:
    class WrongResultFacade(InMemoryFacade):
        async def _execute(self, request: RequestContract[Contract]) -> Contract:
            return Count(count=1)

    client = TestClient(create_app(settings, WrongResultFacade(settings)), headers=HEADERS, raise_server_exceptions=False)
    failures: list[Failure] = []
    for path in ("/server/whoami", "/call"):
        response = client.post(path, json={"kind": "server.whoami", "input": {}})
        assert response.status_code == 500
        envelope = ResponseEnvelope[WhoAmI].model_validate_json(response.content)
        failure = envelope.outcome
        assert isinstance(failure, Failure)
        assert envelope.kind == "server.whoami"
        assert failure.error.status == 500
        assert failure.error.code == "internal_error"
        failures.append(failure)
    async with Client(create_mcp(settings, WrongResultFacade(settings))) as mcp:
        response = await mcp.call_tool("pg_server_whoami", {"request": {"kind": "server.whoami", "input": {}}}, raise_on_error=False)
        assert response.is_error
        assert response.structured_content is not None
        envelope = ResponseEnvelope[WhoAmI].model_validate(response.structured_content)
        assert isinstance(envelope.outcome, Failure)
        assert envelope.kind == "server.whoami"
        failures.append(envelope.outcome)
    assert failures[0] == failures[1] == failures[2]


async def test_mcp_rejects_extra_request_envelope_fields(settings: PgSettings) -> None:
    async with Client(create_mcp(settings, InMemoryFacade(settings))) as client:
        response = await client.call_tool(
            "pg_server_whoami", {"request": {"kind": "server.whoami", "input": {}}, "extra": "synthetic-extra-field"}, raise_on_error=False
        )
        assert response.is_error
        assert response.structured_content is not None
        failure = Failure.model_validate(response.structured_content)
        assert failure.error.status == 422
        assert failure.error.code == "validation_error"
        assert "synthetic-extra-field" not in failure.model_dump_json()
