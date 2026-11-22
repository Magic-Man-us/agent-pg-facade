from __future__ import annotations

from enum import StrEnum


class ExecutionProvenance(StrEnum):
    PYTHON = "python"
    HTTP = "http"
    MCP = "mcp"
    WORKER = "worker"
