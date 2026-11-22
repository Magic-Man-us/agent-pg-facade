from __future__ import annotations

import re

import pytest
from pydantic import JsonValue, TypeAdapter

from pgfacade import PgSettings
from pgfacade.application.registry import REGISTRY
from pgfacade.contracts.enums import Operation
from pgfacade.webmcp import create_mcp

_SCHEMA = TypeAdapter(dict[str, JsonValue])
_KIND = re.compile(rb'"const":"([a-z_]+\.[a-z_]+)"')
_FULL_ACCESS = {"allow_admin": True, "allow_ddl": True, "allow_raw_sql": True, "allow_migrate": True, "allow_listen": True}


async def _batch_schema(**flags: bool) -> tuple[bytes, set[str]]:
    server = create_mcp(PgSettings(_env_file=None, **flags))
    tools = {tool.name: tool for tool in await server.list_tools()}
    encoded = _SCHEMA.dump_json(tools["pg_batch_run"].parameters)
    return encoded, {name for name in tools if name != "pg_batch_run"}


@pytest.mark.parametrize("flags", [{"read_only": True}, {}, _FULL_ACCESS], ids=["read-only", "default", "full-access"])
async def test_batch_tool_advertises_only_the_operations_this_server_exposes(flags: dict[str, bool]) -> None:
    encoded, other_tools = await _batch_schema(**flags)
    kinds = {match.decode() for match in _KIND.findall(encoded)} - {Operation.BATCH_RUN}
    assert {f"pg_{kind.replace('.', '_', 1)}" for kind in kinds} == other_tools


async def test_read_only_batch_schema_is_smaller_than_the_full_catalog() -> None:
    read_only, _ = await _batch_schema(read_only=True)
    full, full_tools = await _batch_schema(**_FULL_ACCESS)
    assert len(full_tools) == len(REGISTRY) - 1
    assert len(read_only) * 3 < len(full)


async def test_batch_schema_keeps_the_request_envelope_shape() -> None:
    server = create_mcp(PgSettings(_env_file=None, read_only=True))
    parameters = (await server.get_tool("pg_batch_run")).parameters
    assert parameters["required"] == ["request"]
    assert set(parameters["properties"]) == {"request"}


@pytest.mark.parametrize(("flags", "read_only"), [({"read_only": True}, True), ({}, False)], ids=["read-only", "default"])
async def test_batch_hints_follow_what_the_server_exposes(flags: dict[str, bool], read_only: bool) -> None:
    hints = (await create_mcp(PgSettings(_env_file=None, **flags)).get_tool("pg_batch_run")).annotations
    assert hints is not None
    assert (hints.readOnlyHint, hints.destructiveHint, hints.idempotentHint) == (read_only, not read_only, read_only)


async def test_scheduling_row_expiry_is_marked_destructive() -> None:
    server = create_mcp(PgSettings(_env_file=None, **_FULL_ACCESS))
    hints = (await server.get_tool("pg_lifecycle_schedule")).annotations
    assert hints is not None and hints.destructiveHint is True and hints.readOnlyHint is False
