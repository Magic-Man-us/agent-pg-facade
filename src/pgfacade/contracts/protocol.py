from __future__ import annotations

from enum import StrEnum


class ASGIScopeType(StrEnum):
    HTTP = "http"
    WEBSOCKET = "websocket"
    LIFESPAN = "lifespan"


class ASGIMessageType(StrEnum):
    HTTP_REQUEST = "http.request"
    HTTP_DISCONNECT = "http.disconnect"


class StreamEvent(StrEnum):
    NOTIFY = "notify"
    ERROR = "error"
