from __future__ import annotations

from psycopg import sql

from pgfacade.configuration.settings import META_SCHEMA
from pgfacade.contracts.enums import WatchEvent
from pgfacade.contracts.events import WatchInfo
from pgfacade.contracts.types import NotificationChannel
from pgfacade.infrastructure.postgres.queries import Statement
from pgfacade.infrastructure.postgres.queries.composition import TableMeta

TRIGGER = "_pgfacade_watch"


def listen(channel: NotificationChannel) -> sql.Composed:
    return Statement.EVENTS_LISTEN.sql.format(sql.Identifier(channel))


def drop_watch(meta: TableMeta) -> sql.Composed:
    return Statement.EVENTS_DROP_TRIGGER.sql.format(sql.Identifier(TRIGGER), meta.ident)


def create_watch(meta: TableMeta, watch: WatchInfo) -> sql.Composed:
    events = sql.SQL(" OR ").join(
        sql.SQL(event.upper()) for event in sorted(set(watch.events), key=[WatchEvent.INSERT, WatchEvent.UPDATE, WatchEvent.DELETE].index)
    )
    return Statement.EVENTS_CREATE_TRIGGER.sql.format(
        sql.Identifier(TRIGGER),
        events,
        meta.ident,
        sql.Identifier(META_SCHEMA),
        sql.Literal(watch.channel),
        sql.Literal(",".join(watch.columns or [])),
    )
