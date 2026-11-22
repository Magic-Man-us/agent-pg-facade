from __future__ import annotations

import pytest
from fastmcp.tools import Tool

from pgfacade import MyApp, PgSettings, Principal
from pgfacade.application.registry import REGISTRY
from pgfacade.contracts.enums import Operation
from pgfacade.webmcp import create_mcp


@pytest.fixture(scope="module")
async def tools() -> dict[str, Tool]:
    settings = PgSettings(
        _env_file=None,
        keys={"annotation-test": Principal(name="tester")},
        allow_admin=True,
        allow_ddl=True,
        allow_raw_sql=True,
        allow_migrate=True,
        allow_listen=True,
    )
    return {tool.name: tool for tool in await create_mcp(settings, MyApp(settings)).list_tools()}


async def test_every_tool_publishes_catalog_annotations(tools: dict[str, Tool]) -> None:
    assert set(tools) == {f"pg_{spec.area}_{spec.action}" for spec in REGISTRY.values()}
    for spec in REGISTRY.values():
        hints = tools[f"pg_{spec.area}_{spec.action}"].annotations
        assert hints is not None
        assert hints.idempotent_hint == spec.idempotent
        assert hints.open_world_hint is False


@pytest.mark.parametrize(
    "operation",
    [
        Operation.ROWS_INSERT,
        Operation.ROWS_UPDATE,
        Operation.TABLE_RENAME,
        Operation.TABLE_COMMENT,
        Operation.COLUMN_ALTER,
        Operation.COLUMN_RENAME,
        Operation.VIEW_CREATE,
        Operation.VIEW_REFRESH,
        Operation.ROLE_ALTER,
        Operation.ROLE_SET_PASSWORD,
        Operation.MEMBERSHIP_REVOKE,
        Operation.PRIVILEGE_REVOKE,
        Operation.EVENT_WATCH,
        Operation.EVENT_UNWATCH,
        Operation.LIFECYCLE_ROW_TTL,
        Operation.LIFECYCLE_REMOVE,
    ],
)
async def test_overwrites_and_removals_are_not_described_as_additive(operation: Operation, tools: dict[str, Tool]) -> None:
    spec = REGISTRY[operation]
    hints = tools[f"pg_{spec.area}_{spec.action}"].annotations
    assert hints is not None
    assert hints.read_only_hint is False
    assert hints.destructive_hint is True
    assert hints.idempotent_hint is False


async def test_idempotency_is_independent_of_read_only_status(tools: dict[str, Tool]) -> None:
    reload = tools["pg_query_reload"].annotations
    insert = tools["pg_rows_insert"].annotations
    select = tools["pg_rows_select"].annotations
    assert reload is not None and insert is not None and select is not None
    assert reload.read_only_hint is False and reload.idempotent_hint is True
    assert insert.read_only_hint is False and insert.idempotent_hint is False
    assert select.read_only_hint is True and select.idempotent_hint is True
