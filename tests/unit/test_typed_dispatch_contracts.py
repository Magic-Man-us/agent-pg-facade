from __future__ import annotations

import inspect
from collections import UserDict
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import FrozenInstanceError, fields, is_dataclass
from pathlib import Path

import pytest
from pydantic import TypeAdapter, ValidationError

from pgfacade import MyApp, Perm, PgSettings
from pgfacade.application.registry import REGISTRY, op
from pgfacade.contracts.admin import MigrationStatus, RevisionInfo
from pgfacade.contracts.base import Count, QueryResult, RequestContract
from pgfacade.contracts.enums import ErrorCode, Operation
from pgfacade.contracts.envelopes import Failure, Success
from pgfacade.contracts.events import EventWait, EventWaitInput, WatchInfo
from pgfacade.contracts.requests import REQUEST_TYPES
from pgfacade.contracts.rows import RowsCount, RowsCountInput, RowsSelect
from pgfacade.contracts.types import MAX_IDENTIFIER_BYTES, Name, NotificationChannels, TableName


@contextmanager
def count_handler(handler: object) -> Iterator[None]:
    # functools exposes dispatch registrations on its descriptor rather than the bound method.
    dispatch = inspect.getattr_static(MyApp, "_execute")
    original = dispatch.dispatcher.dispatch(RowsCount)
    dispatch.register(RowsCount, handler)
    try:
        yield
    finally:
        dispatch.register(RowsCount, original)


def test_every_native_request_declares_its_registered_response() -> None:
    for request_model in REQUEST_TYPES:
        operation = request_model.model_fields["kind"].default
        assert isinstance(operation, Operation)
        response_model = REGISTRY[operation].response
        result_contract = RequestContract.__class_getitem__(response_model)
        assert isinstance(result_contract, type)
        assert issubclass(request_model, result_contract)


def test_registry_records_are_frozen_pydantic_models() -> None:
    assert is_dataclass(Perm())
    specification = REGISTRY[Operation.ROWS_COUNT]
    assert is_dataclass(specification)
    assert "handler" not in {field.name for field in fields(specification)}
    with pytest.raises(TypeError):
        Perm(unknown=True)
    with pytest.raises(FrozenInstanceError):
        specification.hint = "write"


def test_registration_rejects_request_response_mismatch() -> None:
    with pytest.raises(TypeError, match="not a request"):
        op(RowsSelect, response=Count)


async def test_native_dispatch_returns_its_declared_model() -> None:
    returned = Count(count=7)

    async def counted(db: MyApp, request: RowsCount) -> Count:
        return returned

    with count_handler(counted):
        result = await MyApp(PgSettings(_env_file=None)).call(RowsCount(input=RowsCountInput(table="items")))
    assert isinstance(result.outcome, Success)
    assert result.outcome.data is returned
    assert result.kind is Operation.ROWS_COUNT


async def test_internal_validation_error_has_application_outcome() -> None:
    async def invalid_count(db: MyApp, request: RowsCount) -> Count:
        return Count.model_validate({"count": "synthetic-private-result"})

    with count_handler(invalid_count):
        result = await MyApp(PgSettings(_env_file=None)).call(RowsCount(input=RowsCountInput(table="items")))
    assert isinstance(result.outcome, Failure)
    assert result.outcome.error.code is ErrorCode.INTERNAL_ERROR
    assert "synthetic-private-result" not in result.model_dump_json()


async def test_wrong_handler_model_has_application_outcome() -> None:
    async def wrong_count(db: MyApp, request: RowsCount) -> QueryResult:
        return QueryResult()

    with count_handler(wrong_count):
        result = await MyApp(PgSettings(_env_file=None)).call(RowsCount(input=RowsCountInput(table="items")))
    assert isinstance(result.outcome, Failure)
    assert result.outcome.error.code is ErrorCode.INTERNAL_ERROR


def test_invalid_raw_request_is_rejected_at_the_boundary() -> None:
    from pgfacade.contracts.requests import parse_request

    with pytest.raises(ValidationError):
        parse_request(UserDict({"kind": "rows.count", "input": {}}))


@pytest.mark.parametrize("identifier", ["a" * 64, "é" * 32])
def test_identifier_limits_are_measured_in_utf8_bytes(identifier: str) -> None:
    with pytest.raises(ValidationError):
        TypeAdapter(Name).validate_python(identifier)
    with pytest.raises(ValidationError):
        TypeAdapter(TableName).validate_python("public." + identifier)
    assert len(TypeAdapter(Name).validate_python("é" * 31).encode()) <= MAX_IDENTIFIER_BYTES


def test_notification_channels_share_request_and_stream_validation() -> None:
    assert TypeAdapter(NotificationChannels).validate_python("alpha,,beta") == ["alpha", "beta"]
    assert EventWait(input=EventWaitInput(channels="alpha,beta")).input.channels == ["alpha", "beta"]  # type: ignore[arg-type]  # The boundary alias accepts CSV input.
    for value in ("", ",,", "é" * 32):
        with pytest.raises(ValidationError):
            TypeAdapter(NotificationChannels).validate_python(value)


def test_database_watch_definition_is_normalized_by_the_model() -> None:
    value = WatchInfo.model_validate(
        {
            "schema_name": "public",
            "table_name": "items",
            "definition": "AFTER INSERT OR UPDATE ON public.items EXECUTE FUNCTION watch('events', '')",
        }
    )
    assert value.channel == "events"
    assert value.events == ["insert", "update"]
    assert value.columns is None


def test_migration_paths_are_normalized_by_the_model(tmp_path: Path) -> None:
    status = MigrationStatus.model_validate(
        {"directory": tmp_path, "initialized": False, "current": [], "heads": [], "up_to_date": True, "pending": []}
    )
    assert status.directory == str(tmp_path)
    revision = RevisionInfo.model_validate(
        {"revision": "one", "down_revision": None, "doc": "First", "is_head": True, "path": tmp_path / "one.py"}
    )
    assert revision.message == "First"
    assert revision.path == str(tmp_path / "one.py")
    assert revision.applied is False
