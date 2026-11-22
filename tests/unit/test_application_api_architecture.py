from __future__ import annotations

import ast
import asyncio
import inspect
from pathlib import Path
from typing import Literal

import pytest

import pgfacade
from pgfacade import PgFacade, PgSettings
from pgfacade.application.errors import InvalidRequest
from pgfacade.application.registry import OPERATIONS
from pgfacade.contracts.base import Contract, Count, Flag, RequestContract
from pgfacade.contracts.enums import ErrorCode, ErrorReason, Operation
from pgfacade.contracts.envelopes import Failure, Success
from pgfacade.contracts.requests import REQUEST_TYPES
from pgfacade.contracts.rows import RowsCount, RowsCountInput, RowsSelect, SqlExecute, SqlExecuteInput
from tests.support import swapped_handler


def test_request_union_and_catalog_agree() -> None:
    known = {model.model_fields["kind"].default: model for model in REQUEST_TYPES}
    assert len(known) == len(REQUEST_TYPES)
    assert set(known) == set(OPERATIONS)
    handlers = {(spec.handler.__module__, spec.handler.__qualname__) for spec in OPERATIONS.values()}
    assert len(handlers) == len(OPERATIONS)
    for operation, spec in OPERATIONS.items():
        assert spec.op is operation
        assert spec.request is known[operation]
        assert inspect.iscoroutinefunction(spec.handler)
        assert issubclass(spec.request, RequestContract.__class_getitem__(spec.response))
        schema = spec.envelope.model_json_schema()
        assert schema["properties"]["kind"]["const"] == spec.op
        assert schema["properties"]["outcome"]["discriminator"]["propertyName"] == "status"


def test_transports_have_no_operation_or_driver_execution_imports() -> None:
    package = Path(pgfacade.__file__).parent
    modules = [package / "webapp.py", package / "webmcp.py"]
    violations = []
    for module in modules:
        for node in ast.walk(ast.parse(module.read_text(encoding="utf-8"))):
            if isinstance(node, ast.ImportFrom) and node.module is not None:
                if node.module.startswith("pgfacade.application.operations") or node.module.startswith("pgfacade.infrastructure.postgres"):
                    violations.append(f"{module.name}:{node.lineno}:{node.module}")
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if node.func.attr in {"execute", "fetch", "read", "ddl", "transaction", "_execute"}:
                    violations.append(f"{module.name}:{node.lineno}:{node.func.attr}")
    assert not violations
    assert not (package / "application/facade.py").exists()
    assert not (package / "presentation/mcp.py").exists()
    assert not (package / "presentation/http.py").exists()
    assert not (package / "mcpapp.py").exists()


def test_each_transport_has_one_canonical_factory() -> None:
    package = Path(pgfacade.__file__).parent
    factories: dict[str, list[str]] = {"FastAPI": [], "FastMCP": []}
    for module in package.rglob("*.py"):
        for node in ast.walk(ast.parse(module.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in factories:
                factories[node.func.id].append(str(module.relative_to(package)))
    assert factories == {"FastAPI": ["webapp.py"], "FastMCP": ["webmcp.py"]}


async def test_unsupported_request_reaches_the_default_rejection() -> None:
    class Unsupported(RequestContract[Count]):
        kind: Literal[Operation.ROWS_COUNT] = Operation.ROWS_COUNT
        input: RowsCountInput

    app = PgFacade(PgSettings(_env_file=None))
    request = Unsupported(input=RowsCountInput(table="items"))
    with pytest.raises(InvalidRequest, match="Unsupported request type"):
        app.spec_for(request)
    response = await app.call(request)
    assert isinstance(response.outcome, Failure)
    assert response.kind == request.kind
    assert response.outcome.error.code == ErrorCode.INVALID_REQUEST


async def test_request_subclasses_inherit_the_registered_base_handler() -> None:
    class SpecializedCount(RowsCount):
        pass

    seen = []

    async def return_count(app: PgFacade, request: RowsCount) -> Count:
        seen.append(type(request))
        return Count(count=7)

    with swapped_handler(Operation.ROWS_COUNT, return_count):
        response = await PgFacade(PgSettings(_env_file=None)).call(SpecializedCount(input=RowsCountInput(table="items")))
    assert isinstance(response.outcome, Success)
    assert response.outcome.data.count == 7
    assert seen == [SpecializedCount]


async def test_multiple_inheritance_cannot_dispatch_beyond_the_declared_operation() -> None:
    class Hybrid(SqlExecute, RowsSelect):
        kind: Literal[Operation.ROWS_SELECT] = Operation.ROWS_SELECT
        input: SqlExecuteInput

    invoked = []

    async def forbidden_sql_handler(app: PgFacade, request: SqlExecute) -> Contract:
        invoked.append(request)
        raise AssertionError("The SQL handler must not run under rows.select permissions")

    request = Hybrid(input=SqlExecuteInput(sql="DELETE FROM items"))
    with swapped_handler(Operation.SQL_EXECUTE, forbidden_sql_handler), swapped_handler(Operation.ROWS_SELECT, forbidden_sql_handler):
        with pytest.raises(InvalidRequest, match="Request inheritance does not match its operation contract"):
            PgFacade.spec_for(request)
        response = await PgFacade(PgSettings(_env_file=None)).call(request)
    assert isinstance(response.outcome, Failure)
    assert response.outcome.error.code == ErrorCode.INVALID_REQUEST
    assert not invoked


async def test_invalid_handler_output_becomes_an_application_failure() -> None:
    async def wrong_result(app: PgFacade, request: RowsCount) -> Flag:
        return Flag(ok=True)

    with swapped_handler(Operation.ROWS_COUNT, wrong_result):
        response = await PgFacade(PgSettings(_env_file=None)).call(RowsCount(input=RowsCountInput(table="items")))
    assert isinstance(response.outcome, Failure)
    assert response.outcome.error.code == ErrorCode.INTERNAL_ERROR
    assert response.outcome.error.status == 500
    assert response.outcome.error.reason is ErrorReason.RESPONSE_INVALID


async def test_cancellation_propagates_without_becoming_an_error_outcome() -> None:
    cleaned = []

    async def cancelled_count(app: PgFacade, request: RowsCount) -> Count:
        try:
            raise asyncio.CancelledError
        finally:
            cleaned.append(True)

    with swapped_handler(Operation.ROWS_COUNT, cancelled_count), pytest.raises(asyncio.CancelledError):
        await PgFacade(PgSettings(_env_file=None)).call(RowsCount(input=RowsCountInput(table="items")))
    assert cleaned == [True]


async def test_stream_output_validation_redacts_invalid_values_and_closes_listener(monkeypatch: pytest.MonkeyPatch) -> None:
    import warnings
    from collections.abc import AsyncIterator

    from pgfacade import ExecutionContext, Principal
    from pgfacade.application.operations import events
    from pgfacade.contracts.events import Notification
    from pgfacade.contracts.streaming import EventStreamInput, EventStreamRequest
    from pgfacade.contracts.types import NotificationChannels
    from pgfacade.infrastructure.postgres.engine import Core
    from pgfacade.shared.types import HeartbeatSeconds

    closed = []

    async def invalid_notifications(
        app: Core, channels: NotificationChannels, *, heartbeat_s: HeartbeatSeconds = 15.0
    ) -> AsyncIterator[Notification | None]:
        try:
            yield Notification.model_validate(
                {"channel": "events", "payload": "fixture", "pid": 1, "received_at": "synthetic-private-timestamp"}
            )
        finally:
            closed.append(True)

    monkeypatch.setattr(events, "listen", invalid_notifications)
    app = PgFacade(PgSettings(_env_file=None, allow_listen=True))
    context = ExecutionContext(principal=Principal(listen=True))
    with warnings.catch_warnings(record=True) as captured:
        stream = await app.stream_events(EventStreamRequest(input=EventStreamInput(channels=["events"])), context)
        responses = [item async for item in stream]
    assert len(responses) == 1
    assert responses[0] is not None
    assert isinstance(responses[0].outcome, Failure)
    assert responses[0].outcome.error.code is ErrorCode.INTERNAL_ERROR
    assert "synthetic-private-timestamp" not in responses[0].model_dump_json()
    assert closed == [True]
    assert not captured


async def test_stream_cancellation_propagates_and_closes_listener(monkeypatch: pytest.MonkeyPatch) -> None:
    from collections.abc import AsyncIterator

    from pgfacade import ExecutionContext, Principal
    from pgfacade.application.operations import events
    from pgfacade.contracts.events import Notification
    from pgfacade.contracts.streaming import EventStreamInput, EventStreamRequest
    from pgfacade.contracts.types import NotificationChannels
    from pgfacade.infrastructure.postgres.engine import Core
    from pgfacade.shared.types import HeartbeatSeconds

    started = asyncio.Event()
    closed = []

    async def pending_notifications(
        app: Core, channels: NotificationChannels, *, heartbeat_s: HeartbeatSeconds = 15.0
    ) -> AsyncIterator[Notification | None]:
        try:
            started.set()
            await asyncio.Event().wait()
            yield None
        finally:
            closed.append(True)

    monkeypatch.setattr(events, "listen", pending_notifications)
    app = PgFacade(PgSettings(_env_file=None, allow_listen=True))
    context = ExecutionContext(principal=Principal(listen=True))
    stream = await app.stream_events(EventStreamRequest(input=EventStreamInput(channels=["events"])), context)
    pending = asyncio.create_task(anext(stream))
    await started.wait()
    pending.cancel()
    with pytest.raises(asyncio.CancelledError):
        await pending
    assert closed == [True]
