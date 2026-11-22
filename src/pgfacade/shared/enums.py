from __future__ import annotations

from enum import StrEnum


class McpTransport(StrEnum):
    STDIO = "stdio"
    HTTP = "http"
    STREAMABLE_HTTP = "streamable-http"
    SSE = "sse"


class PermissionName(StrEnum):
    WRITE = "write"
    RAW = "raw"
    DDL = "ddl"
    ADMIN = "admin"
    MIGRATE = "migrate"
    LISTEN = "listen"
