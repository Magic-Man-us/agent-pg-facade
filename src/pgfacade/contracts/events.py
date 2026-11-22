"""event.* requests and results: LISTEN/NOTIFY and table change watches."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Literal

from pydantic import AliasChoices, BaseModel, Field, field_validator, model_validator

from pgfacade.contracts.base import Contract, Done, Name, RequestContract, TableName
from pgfacade.contracts.enums import Operation
from pgfacade.contracts.types import (
    EventDateTime,
    NonEmptyItems,
    NotificationChannels,
    NotificationPayload,
    OperationFlag,
    ProcessId,
    ResultLabel,
    ResultText,
    RowLimit,
    WaitTimeoutSeconds,
    WatchEvent,
)
from pgfacade.shared.config import SOURCE_CONFIG


class Notification(Contract):
    channel: ResultLabel
    payload: ResultText
    pid: ProcessId
    received_at: EventDateTime


class NotificationList(Contract):
    items: list[Notification]
    timed_out: OperationFlag


_WATCH_DEFINITION = re.compile(r"AFTER (?P<events>[A-Z OR]+?) ON .*? EXECUTE FUNCTION \S+\('(?P<channel>[^']*)'(?:, '(?P<cols>[^']*)')?\)")


class _WatchDefinition(Contract):
    channel: ResultLabel = ""
    events: list[WatchEvent] = Field(default_factory=list)
    columns: list[ResultLabel] | None = Field(default=None, validation_alias=AliasChoices("columns", "cols"))

    @model_validator(mode="before")
    @classmethod
    def parse_definition(cls, value: object) -> object:
        if isinstance(value, str):
            matched = _WATCH_DEFINITION.search(value)
            return matched.groupdict() if matched is not None else {}
        return value

    @field_validator("events", mode="before")
    @classmethod
    def parse_events(cls, value: object) -> object:
        return [event.strip().lower() for event in value.split(" OR ")] if isinstance(value, str) else value

    @field_validator("columns", mode="before")
    @classmethod
    def parse_columns(cls, value: object) -> object:
        if isinstance(value, str):
            return value.split(",") if value else None
        return value


class _WatchRow(BaseModel):
    model_config = SOURCE_CONFIG

    schema_name: ResultLabel
    table_name: ResultLabel
    definition: _WatchDefinition


class WatchInfo(Contract):
    schema_name: ResultLabel
    table_name: ResultLabel
    channel: ResultLabel
    events: list[WatchEvent]
    columns: list[ResultLabel] | None = None

    @model_validator(mode="before")
    @classmethod
    def read_database_row(cls, value: object) -> object:
        if isinstance(value, Mapping) and "definition" in value:
            source = _WatchRow.model_validate(value)
            return source.model_dump(exclude={"definition"}) | source.definition.model_dump()
        return value


class WatchInfoList(Contract):
    items: list[WatchInfo]


class EventNotifyInput(Contract):
    channel: Name
    payload: NotificationPayload = ""


class EventNotify(RequestContract[Done]):
    """pg_notify(channel, payload); delivered to listeners on commit."""

    kind: Literal[Operation.EVENT_NOTIFY] = Operation.EVENT_NOTIFY
    input: EventNotifyInput


class EventWaitInput(Contract):
    channels: NotificationChannels
    timeout_s: WaitTimeoutSeconds = 10.0
    max_events: RowLimit = Field(100)


class EventWait(RequestContract[NotificationList]):
    """Block up to timeout_s for notifications on channels (one-shot; for streaming use the SSE endpoint)."""

    kind: Literal[Operation.EVENT_WAIT] = Operation.EVENT_WAIT
    input: EventWaitInput


class EventWatchInput(Contract):
    table: TableName
    events: NonEmptyItems[WatchEvent] = [WatchEvent.INSERT, WatchEvent.UPDATE, WatchEvent.DELETE]
    channel: Name | None = Field(None, description="Default pgfacade:<schema>.<table>")
    columns: list[Name] | None = Field(None, description="Limit the row payload to these columns")


class EventWatch(RequestContract[WatchInfo]):
    """Install a trigger that NOTIFYs a JSON change record for inserts/updates/deletes on a table."""

    kind: Literal[Operation.EVENT_WATCH] = Operation.EVENT_WATCH
    input: EventWatchInput


class EventUnwatchInput(Contract):
    table: TableName


class EventUnwatch(RequestContract[Done]):
    """Remove the change trigger from a table."""

    kind: Literal[Operation.EVENT_UNWATCH] = Operation.EVENT_UNWATCH
    input: EventUnwatchInput


class EventWatchListInput(Contract):
    pass


class EventWatchList(RequestContract[WatchInfoList]):
    """Tables with change triggers installed."""

    kind: Literal[Operation.EVENT_WATCHES] = Operation.EVENT_WATCHES
    input: EventWatchListInput
