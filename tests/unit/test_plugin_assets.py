from __future__ import annotations

import re
from pathlib import Path

import pytest
from pydantic import BaseModel, ConfigDict, JsonValue, TypeAdapter

import pgfacade.facade  # noqa: F401  # Registers the operation catalog.
from pgfacade.application.registry import OPERATIONS
from pgfacade.contracts.enums import ErrorCode
from pgfacade.contracts.requests import parse_request
from pgfacade.infrastructure.postgres.queries.loader import query_definitions

ROOT = Path(__file__).resolve().parents[2]
PLUGIN = ROOT / "plugin"
SKILL = PLUGIN / "skills" / "postgres"

# Deployment snapshots copy the package and tests without the plugin directory.
pytestmark = pytest.mark.skipif(not PLUGIN.is_dir(), reason="plugin assets are not part of this source snapshot")


class _Named(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str


class _PluginEntry(_Named):
    source: str


class _Marketplace(_Named):
    plugins: list[_PluginEntry]


class _ServerConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    command: str
    args: list[str]
    env: dict[str, str]


class _McpConfig(BaseModel):
    mcpServers: dict[str, _ServerConfig]


class _ToolCall(BaseModel):
    request: JsonValue


_JSON_BLOCK = re.compile(r"```json\n(.*?)```", re.DOTALL)
_CODE_ROW = re.compile(r"^\| `([a-z_]+)` \|", re.MULTILINE)


def test_marketplace_entry_points_at_the_plugin_manifest() -> None:
    marketplace = _Marketplace.model_validate_json((ROOT / ".claude-plugin" / "marketplace.json").read_bytes())
    manifest = _Named.model_validate_json((PLUGIN / ".claude-plugin" / "plugin.json").read_bytes())
    assert [(entry.name, (ROOT / entry.source).resolve()) for entry in marketplace.plugins] == [(manifest.name, PLUGIN)]


def test_bundled_server_runs_the_stdio_command() -> None:
    config = _McpConfig.model_validate_json((PLUGIN / ".mcp.json").read_bytes())
    server = config.mcpServers["postgres"]
    assert server.args[-2:] == ["pgfacade", "mcp"]
    assert set(server.env) == {"PGFACADE_DSN", "PGFACADE_READ_ONLY"}


def test_tool_reference_lists_every_operation() -> None:
    documented = set(re.findall(r"`(pg_[a-z_]+)`", (SKILL / "reference" / "tools.md").read_text(encoding="utf-8")))
    assert documented == {f"pg_{spec.area}_{spec.action}" for spec in OPERATIONS.values()}


def test_query_reference_lists_every_curated_query() -> None:
    documented = set(re.findall(r"^\| `([a-z_.]+)` \|", (SKILL / "reference" / "queries.md").read_text(encoding="utf-8"), re.MULTILINE))
    assert documented == set(query_definitions(None))


def test_skill_examples_are_valid_requests() -> None:
    blocks = _JSON_BLOCK.findall((SKILL / "SKILL.md").read_text(encoding="utf-8"))
    calls = [TypeAdapter(JsonValue).validate_json(block) for block in blocks]
    requests = [_ToolCall.model_validate(call).request for call in calls if isinstance(call, dict) and "request" in call]
    assert len(requests) >= 5
    for request in requests:
        parse_request(request)


def test_skill_error_table_uses_declared_codes() -> None:
    text = (SKILL / "SKILL.md").read_text(encoding="utf-8")
    table = text[text.index("## Errors") :]
    assert set(_CODE_ROW.findall(table)) <= set(ErrorCode)
    assert _CODE_ROW.findall(table)
