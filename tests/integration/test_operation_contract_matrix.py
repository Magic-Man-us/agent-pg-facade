"""Exercise advertised contracts through all adapters with in-memory handlers, independently of SQL behavior."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from fastmcp import Client
from pydantic import JsonValue

from pgfacade import PgFacade, PgSettings, Principal
from pgfacade.application.context import ExecutionContext
from pgfacade.application.errors import Forbidden
from pgfacade.application.registry import OPERATIONS, OpSpec
from pgfacade.contracts.admin import (
    Health,
    MigrationOutcome,
    MigrationStatus,
    RevisionInfo,
    RevisionInfoList,
    ServerInfo,
    SettingInfoList,
    WhoAmI,
)
from pgfacade.contracts.base import Contract, Count, Done, Flag, QueryResult, RequestContract, Row, Text
from pgfacade.contracts.enums import Operation
from pgfacade.contracts.envelopes import Failure, Success
from pgfacade.contracts.events import NotificationList, WatchInfo, WatchInfoList
from pgfacade.contracts.lifecycle import LifecyclePolicyList, LifecycleRunList, LifecycleRunReport, RowTtlPolicy, TableExpiryPolicy
from pgfacade.contracts.queries import QueryInfoList
from pgfacade.contracts.requests import BatchResult
from pgfacade.contracts.roles import PrivilegeInfoList, RoleInfo, RoleInfoList
from pgfacade.contracts.rows import Plan
from pgfacade.contracts.schema import DatabaseInfoList, ExtensionInfoList, SchemaInfoList, TableDetail, TableInfo, TableInfoList
from pgfacade.webapp import create_app
from pgfacade.webmcp import create_mcp
from tests.support import swapped_handler

_KEY = "contract-matrix-test-only"
_PRINCIPAL = Principal(name="matrix", ddl=True, sql=True, admin=True, migrate=True, listen=True)

_IDENTIFIER_VALUES: dict[str, JsonValue] = {
    "table": "items",
    "name": "fixture",
    "column": "value",
    "new_name": "renamed",
    "index": "fixture_idx",
}
_ROW_VALUES: dict[str, JsonValue] = {
    "key": 1,
    "rows": [{"value": 1}],
    "values": {"value": 2},
    "aggregates": [{"fn": "count"}],
    "columns": ["value"],
}
_SQL_VALUES: dict[str, JsonValue] = {"sql": "SELECT 1", "query": "SELECT 1", "data": "value\n1\n", "comment": None}
_ROLE_VALUES: dict[str, JsonValue] = {
    "role": "fixture",
    "members": ["fixture"],
    "roles": ["fixture"],
    "privileges": ["select"],
    "on": "table",
}
_EVENT_VALUES: dict[str, JsonValue] = {
    "target": "items",
    "password": "test-placeholder",
    "channels": ["events"],
    "channel": "events",
    "policy_id": 1,
}
_OTHER_VALUES: dict[str, JsonValue] = {
    "kind": "table",
    "action": "upgrade",
    "pid": 1,
    "message": "fixture",
    "requests": [{"kind": "rows.count", "input": {"table": "items"}}],
}
_INPUT_VALUES = _IDENTIFIER_VALUES | _ROW_VALUES | _SQL_VALUES | _ROLE_VALUES | _EVENT_VALUES | _OTHER_VALUES
_INPUT_OVERRIDES: dict[Operation, dict[str, JsonValue]] = {
    Operation.TABLE_CREATE: {"columns": [{"name": "value", "type": "text"}]},
    Operation.COLUMN_ADD: {"column": {"name": "value", "type": "text"}},
    Operation.COLUMN_ALTER: {"type": "text"},
    Operation.CONSTRAINT_ADD: {"kind": "unique", "columns": ["value"]},
    Operation.ROLE_ALTER: {"login": True},
}
_NOW = datetime(2026, 1, 1, tzinfo=UTC)
_RESULTS: tuple[Contract, ...] = (
    BatchResult(results=[]),
    Count(count=1),
    DatabaseInfoList(items=[]),
    Done(status="OK"),
    ExtensionInfoList(items=[]),
    Flag(ok=True),
    Health(ok=True, latency_ms=0),
    RowTtlPolicy(
        id=1,
        kind="row_ttl",
        schema_name="public",
        table_name="items",
        column_name="created_at",
        action="delete",
        batch_size=1,
        enabled=True,
        created_at=_NOW,
    ),
    TableExpiryPolicy(
        id=2,
        schema_name="public",
        table_name="items",
        action="truncate",
        expires_at=_NOW,
        batch_size=1,
        enabled=True,
        created_at=_NOW,
    ),
    LifecyclePolicyList(items=[], installed=True),
    LifecycleRunList(items=[]),
    LifecycleRunReport(items=[]),
    MigrationOutcome(before=[], after=[], output=""),
    MigrationStatus(directory="migrations", initialized=False, current=[], heads=[], up_to_date=True, pending=[]),
    NotificationList(items=[], timed_out=True),
    Plan(plan=[]),
    PrivilegeInfoList(items=[]),
    QueryInfoList(items=[]),
    QueryResult(),
    RevisionInfo(revision="fixture", down_revision=None, message="fixture", is_head=True, path="fixture.py"),
    RevisionInfoList(items=[]),
    RoleInfo(
        name="fixture",
        login=True,
        superuser=False,
        createdb=False,
        createrole=False,
        inherit=True,
        replication=False,
        bypassrls=False,
        connection_limit=-1,
    ),
    RoleInfoList(items=[]),
    Row(),
    SchemaInfoList(items=[]),
    ServerInfo(
        server_version="16",
        version="PostgreSQL 16",
        database="fixture",
        user="fixture",
        session_role="fixture",
        started_at=_NOW,
        database_bytes=0,
        connections=0,
        max_connections=100,
        in_recovery=False,
    ),
    SettingInfoList(items=[]),
    TableDetail(
        info=TableInfo(schema_name="public", name="items", kind="table", owner="fixture", est_rows=0, total_bytes=0),
        columns=[],
        primary_key=[],
        constraints=[],
        indexes=[],
    ),
    TableInfoList(items=[]),
    Text(text="fixture"),
    WatchInfo(schema_name="public", table_name="items", channel="events", events=["insert"]),
    WatchInfoList(items=[]),
    WhoAmI(principal="matrix", role=None, read_only=False, sql=True, ddl=True, admin=True, migrate=True, listen=True),
)
_RESULT_BY_MODEL = {type(result): result for result in _RESULTS}


class InMemoryApp(PgFacade):
    async def open(self) -> None:
        pass

    async def close(self) -> None:
        pass


def sample_request(spec: OpSpec) -> RequestContract[Contract]:
    # Catalog models are only known at runtime; fail on any new required argument without a declared fixture.
    if spec.op == Operation.CONSTRAINT_ADD:
        return spec.request.model_validate({"input": {"table": "items", "kind": "unique", "columns": ["value"]}})
    input_model = spec.request.model_fields["input"].annotation
    assert isinstance(input_model, type) and issubclass(input_model, Contract)
    values = {name: _INPUT_VALUES[name] for name, field in input_model.model_fields.items() if field.is_required()}
    values.update(_INPUT_OVERRIDES.get(spec.op, {}))
    if spec.op == Operation.LIFECYCLE_TABLE_EXPIRY:
        values["expires_in"] = "1 day"
    if spec.op == Operation.MAINT_BACKEND:
        values["action"] = "cancel"
    request = spec.request.model_validate({"input": values})
    assert isinstance(request, RequestContract)
    return request


@pytest.fixture(scope="module")
async def adapters() -> AsyncIterator[tuple[InMemoryApp, TestClient, Client]]:
    settings = PgSettings(
        _env_file=None,
        keys={_KEY: _PRINCIPAL},
        mcp_key=_KEY,
        lifecycle_sweep_s=0,
        allow_raw_sql=True,
        allow_ddl=True,
        allow_admin=True,
        allow_migrate=True,
        allow_listen=True,
    )
    app = InMemoryApp(settings)
    with TestClient(create_app(db=app), headers={"Authorization": f"Bearer {_KEY}"}) as http:
        async with Client(create_mcp(db=app)) as mcp:
            yield app, http, mcp


@pytest.mark.parametrize("operation", tuple(OPERATIONS))
@pytest.mark.parametrize("fails", [False, True], ids=["success", "domain-failure"])
async def test_every_operation_uses_the_same_python_http_mcp_contract(
    adapters: tuple[InMemoryApp, TestClient, Client], operation: Operation, fails: bool
) -> None:
    app, http, mcp = adapters
    spec = OPERATIONS[operation]
    request = sample_request(spec)
    result = _RESULT_BY_MODEL[spec.response]
    seen = []

    async def matrix_handler(execution: PgFacade, received: RequestContract[Contract]) -> Contract:
        assert execution._execution_context is not None
        seen.append((received.model_dump(mode="json"), execution._execution_context.provenance))
        if fails:
            raise Forbidden("Matrix operation denied")
        return result

    with swapped_handler(operation, matrix_handler):
        native = await app.call(request, ExecutionContext(principal=_PRINCIPAL))
        response = http.post(f"/{spec.area}/{spec.action}", json=request.model_dump(mode="json"))
        tool = await mcp.call_tool(f"pg_{spec.area}_{spec.action}", {"request": request.model_dump(mode="json")}, raise_on_error=False)
    expected = native.model_dump(mode="json")
    assert native.kind == operation
    if fails:
        assert isinstance(native.outcome, Failure)
        assert native.outcome.error.code == "forbidden"
        assert response.status_code == 403
        assert tool.is_error
    else:
        assert isinstance(native.outcome, Success)
        assert native.outcome.data == result
        assert response.status_code == 200
        assert not tool.is_error
    assert response.json() == tool.structured_content == expected
    assert seen == [(request.model_dump(mode="json"), provenance) for provenance in ("python", "http", "mcp")]
