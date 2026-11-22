"""event.* handlers: NOTIFY, one-shot wait, streaming listen, and table change watches."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from hashlib import sha256

from pgfacade.application.errors import InvalidRequest
from pgfacade.application.registry import ADMIN_WRITE, LISTEN, WRITE, op
from pgfacade.contracts.base import Done
from pgfacade.contracts.enums import OperationHint
from pgfacade.contracts.events import (
    EventNotify,
    EventUnwatch,
    EventWait,
    EventWatch,
    EventWatchList,
    Notification,
    NotificationList,
    WatchInfo,
    WatchInfoList,
)
from pgfacade.contracts.types import MAX_IDENTIFIER_BYTES, EventDateTime, Name, NotificationChannel
from pgfacade.infrastructure.postgres.engine import Core
from pgfacade.infrastructure.postgres.queries import Statement
from pgfacade.infrastructure.postgres.queries import events as event_sql
from pgfacade.infrastructure.postgres.queries.composition import Binder, truncate_name
from pgfacade.infrastructure.postgres.types import RelationKind
from pgfacade.shared.types import HeartbeatSeconds

_CHANNEL_HASH_HEX_LENGTH = 16


def default_channel(schema: Name, table: Name) -> NotificationChannel:
    channel = f"pgfacade:{schema}.{table}"
    if len(channel.encode()) <= MAX_IDENTIFIER_BYTES:
        return channel
    digest = sha256(channel.encode()).hexdigest()[:_CHANNEL_HASH_HEX_LENGTH]
    return truncate_name(f"pgfacade:{digest}:{schema}.{table}")


def _now() -> EventDateTime:
    return datetime.now(UTC)


async def listen(
    db: Core, channels: list[NotificationChannel], *, heartbeat_s: HeartbeatSeconds = 15.0
) -> AsyncIterator[Notification | None]:
    """Stream notifications on one dedicated connection until cancelled. Yields None after heartbeat_s of silence
    so callers can keep an idle stream alive without ever dropping the LISTEN."""
    async with db.dedicated() as conn:
        for ch in channels:
            await conn.execute(event_sql.listen(ch))
        while True:
            received = False
            async for n in conn.notifies(timeout=heartbeat_s):
                received = True
                yield Notification(channel=n.channel, payload=n.payload, pid=n.pid, received_at=_now())
            if not received:
                yield None


@op(EventNotify, response=Done, perm=WRITE | LISTEN)
async def notify(db: Core, req: EventNotify) -> Done:
    async with db.tx() as conn:
        await conn.execute(Statement.EVENTS_NOTIFY.text, [req.input.channel, req.input.payload])
    return Done(status="NOTIFY")


@op(EventWait, response=NotificationList, perm=LISTEN)
async def wait(db: Core, req: EventWait) -> NotificationList:
    timeout = min(req.input.timeout_s, db.settings.max_wait_s)
    items: list[Notification] = []
    async with db.dedicated() as conn:
        for ch in req.input.channels:
            await conn.execute(event_sql.listen(ch))
        async for n in conn.notifies(timeout=timeout, stop_after=req.input.max_events):
            items.append(Notification(channel=n.channel, payload=n.payload, pid=n.pid, received_at=_now()))
    return NotificationList(items=items, timed_out=len(items) < req.input.max_events)


@op(EventWatch, response=WatchInfo, perm=ADMIN_WRITE | LISTEN, hint=OperationHint.DESTRUCTIVE)
async def watch(db: Core, req: EventWatch) -> WatchInfo:
    async with db.tx() as conn:
        meta = await db.table(conn, req.input.table)
        if meta.kind not in (RelationKind.TABLE, RelationKind.PARTITIONED_TABLE):
            raise InvalidRequest(f"{meta.label} is not a table; watches need a plain or partitioned table")
        b = Binder(meta)
        cols: list[Name] = []
        for c in req.input.columns or []:
            b.col(c)  # validates against the catalog
            cols.append(c)
        result = WatchInfo(
            schema_name=meta.schema_name,
            table_name=meta.name,
            channel=req.input.channel or default_channel(meta.schema_name, meta.name),
            events=sorted(set(req.input.events)),
            columns=cols or None,
        )
        await conn.execute(Statement.EVENTS_NOTIFY_FN.text)
        await conn.execute(event_sql.drop_watch(meta))
        await conn.execute(event_sql.create_watch(meta, result))
    return result


@op(EventUnwatch, response=Done, perm=ADMIN_WRITE | LISTEN, hint=OperationHint.DESTRUCTIVE)
async def unwatch(db: Core, req: EventUnwatch) -> Done:
    async with db.tx() as conn:
        meta = await db.table(conn, req.input.table)
        cur = await conn.execute(event_sql.drop_watch(meta))
        return Done(status=cur.statusmessage)


@op(EventWatchList, response=WatchInfoList, perm=LISTEN)
async def watches(db: Core, req: EventWatchList) -> WatchInfoList:
    result = await db.read(Statement.EVENTS_WATCHES.text)
    return WatchInfoList(items=[WatchInfo.model_validate(row) for row in result.rows])
