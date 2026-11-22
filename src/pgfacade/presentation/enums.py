from __future__ import annotations

from enum import StrEnum


class CliOperation(StrEnum):
    API = "api"
    MCP = "mcp"
    OPS = "ops"
    KEYGEN = "keygen"
