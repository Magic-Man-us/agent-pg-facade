"""The MCP transport: generated tools, gating by server caps, key binding, structured results, errors."""

from collections.abc import AsyncIterator

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError

from pgfacade import REGISTRY, Principal
from pgfacade.webmcp import create_mcp
from tests.conftest import call_tool, make_settings, tool_names, unique

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
async def mcp() -> AsyncIterator[Client]:
    async with Client(create_mcp(make_settings())) as client:
        yield client


async def test_every_allowed_op_is_a_tool(mcp: Client) -> None:
    names = await tool_names(mcp)
    assert names == {f"pg_{s.area}_{s.action}" for s in REGISTRY.values()}  # allow_admin=True: everything
    tools = {t.name: t for t in await mcp.list_tools()}
    delete = tools["pg_rows_delete"]
    assert delete.annotations is not None and delete.annotations.destructive_hint is True
    assert tools["pg_rows_select"].annotations.read_only_hint is True
    assert set(tools["pg_rows_select"].input_schema["properties"]) == {"request"}


async def test_tools_gated_by_server_caps() -> None:
    async with Client(create_mcp(make_settings(read_only=True, allow_admin=False))) as ro:
        names = await tool_names(ro)
        assert {"pg_rows_select", "pg_sql_query", "pg_query_run", "pg_server_whoami"} <= names
        assert not names & {"pg_rows_insert", "pg_sql_execute", "pg_table_create", "pg_role_create", "pg_lifecycle_run", "pg_migration_run"}
    async with Client(create_mcp(make_settings(allow_raw_sql=False, allow_ddl=False, allow_listen=False))) as locked:
        names = await tool_names(locked)
        assert "pg_rows_insert" in names
        assert not names & {"pg_sql_query", "pg_sql_execute", "pg_view_create", "pg_table_create", "pg_event_wait"}


async def test_stdio_key_binds_principal(users: str) -> None:
    keys = {"k": Principal(name="claude", read_only=True)}
    async with Client(create_mcp(make_settings(keys=keys, mcp_key="k"))) as c:
        assert (await call_tool(c, "pg_server_whoami"))["principal"] == "claude"
        assert (await call_tool(c, "pg_rows_count", table=users))["count"] == 3
        with pytest.raises(ToolError, match="read-only"):
            await call_tool(c, "pg_rows_insert", table=users, rows=[{"email": "x@x.io"}])
    async with Client(create_mcp(make_settings(keys=keys, mcp_key=None))) as c:
        with pytest.raises(ToolError, match="missing API key"):
            await call_tool(c, "pg_server_whoami")


async def test_tool_calls(mcp: Client, users: str) -> None:
    detail = await call_tool(mcp, "pg_table_describe", table=users)
    assert detail["primary_key"] == ["id"]
    page = await call_tool(
        mcp,
        "pg_rows_select",
        table=users,
        where=[{"kind": "contains", "column": "tags", "value": ["b"]}],
        order_by=[{"column": "email"}],
        with_total=True,
    )
    assert [r["email"] for r in page["rows"]] == ["ann@x.io", "bob@x.io"] and page["total"] == 2
    assert (await call_tool(mcp, "pg_rows_get", table=users, key=1))["row"]["email"] == "ann@x.io"
    assert (await call_tool(mcp, "pg_rows_get", table=users, key=999))["row"] is None
    assert (await call_tool(mcp, "pg_rows_count", table=users, match={"meta": None}))["count"] == 1
    agg = await call_tool(mcp, "pg_rows_aggregate", table=users, aggregates=[{"fn": "avg", "column": "score", "alias": "avg"}])
    assert float(agg["rows"][0]["avg"]) == 4.0
    ins = await call_tool(mcp, "pg_rows_insert", table=users, rows=[{"email": "dan@x.io"}])
    assert ins["rowcount"] == 1
    assert (await call_tool(mcp, "pg_rows_update", table=users, values={"score": 1}, match={"email": "dan@x.io"}))["rows"][0]["score"] == 1
    assert (await call_tool(mcp, "pg_rows_delete", table=users, match={"email": "dan@x.io"}, returning=["id"]))["rowcount"] == 1
    reqs = [
        {"kind": "rows.update", "input": {"table": users, "values": {"score": 0}, "match": {"id": 1}}},
        {"kind": "sql.query", "input": {"sql": "SELECT 1 AS one"}},
    ]
    assert len((await call_tool(mcp, "pg_batch_run", requests=reqs))["results"]) == 2
    assert (await call_tool(mcp, "pg_sql_query", sql=f'SELECT count(*) AS n FROM "{users}"'))["rows"] == [{"n": 3}]
    assert "Plan" in (await call_tool(mcp, "pg_sql_explain", sql="SELECT 1"))["plan"][0]
    assert (await call_tool(mcp, "pg_rows_export_csv", table=users, columns=["email"]))["text"].startswith("email\n")
    assert any(q["name"] == "rows.duplicates" for q in (await call_tool(mcp, "pg_query_list", category="rows"))["items"])
    assert (await call_tool(mcp, "pg_query_run", name="rows.recent", params={"table": users, "limit": 1}))["rowcount"] == 1
    assert (await call_tool(mcp, "pg_maint_analyze", table=users))["status"] == "ANALYZE"
    assert (await call_tool(mcp, "pg_event_notify", channel="c"))["status"] == "NOTIFY"
    assert (await call_tool(mcp, "pg_event_wait", channels=["c"], timeout_s=0.2))["items"] == []


async def test_ddl_roles_and_lifecycle_tools(mcp: Client, users: str) -> None:
    table = f"{users}_child"
    await call_tool(
        mcp,
        "pg_table_create",
        table=table,
        columns=[{"name": "a", "type": "int"}, {"name": "b", "type": "int"}],
        primary_key=["a", "b"],
        comment="child",
    )
    try:
        detail = await call_tool(mcp, "pg_table_describe", table=table)
        assert detail["primary_key"] == ["a", "b"] and detail["info"]["comment"] == "child"
        await call_tool(mcp, "pg_column_add", table=table, column={"name": "c", "type": "text"})
        await call_tool(mcp, "pg_column_alter", table=table, column="c", nullable=False, default="x")
        await call_tool(mcp, "pg_constraint_add", table=table, kind="unique", columns=["c"])
        idx = await call_tool(mcp, "pg_index_create", table=table, columns=["b"])
        await call_tool(mcp, "pg_index_drop", index=idx["detail"]["index"])
    finally:
        await call_tool(mcp, "pg_table_drop", table=table)
    role = unique("mcp_role")
    assert (await call_tool(mcp, "pg_role_create", name=role, login=False))["name"] == role
    try:
        assert (await call_tool(mcp, "pg_role_alter", name=role, comment="x"))["comment"] == "x"
        await call_tool(mcp, "pg_privilege_grant", privileges=["select"], on="table", target=users, roles=[role])
        assert any(p["grantee"] == role for p in (await call_tool(mcp, "pg_privilege_list", kind="table", target=users))["items"])
    finally:
        await call_tool(mcp, "pg_role_drop", name=role, reassign_to="postgres")
    await call_tool(mcp, "pg_lifecycle_install")
    policy = await call_tool(mcp, "pg_lifecycle_row_ttl", table=users, column="created_at", ttl="30 days")
    try:
        assert (await call_tool(mcp, "pg_lifecycle_preview", policy_id=policy["id"]))["count"] == 0
        assert (await call_tool(mcp, "pg_lifecycle_run", policy_id=policy["id"]))["items"][0]["rows_affected"] == 0
        assert (await call_tool(mcp, "pg_lifecycle_runs", policy_id=policy["id"]))["items"]
    finally:
        await call_tool(mcp, "pg_lifecycle_remove", policy_id=policy["id"])


async def test_errors_become_tool_errors(mcp: Client, users: str) -> None:
    with pytest.raises(ToolError, match="23505"):
        await call_tool(mcp, "pg_rows_insert", table=users, rows=[{"email": "ann@x.io"}])
    with pytest.raises(ToolError, match="refusing DELETE"):
        await call_tool(mcp, "pg_rows_delete", table=users)
    with pytest.raises(ToolError, match="does not exist"):
        await call_tool(mcp, "pg_rows_select", table="nope")


async def test_keyless_session_lists_tables_in_its_instructions(users: str) -> None:
    async with Client(create_mcp(make_settings(keys={}, mcp_key=None))) as client:
        assert client.instructions is not None and f"public.{users}" in client.instructions
        assert (await call_tool(client, "pg_server_whoami"))["principal"] == "library"
        assert (await call_tool(client, "pg_rows_count", table=users))["count"] == 3


async def test_keyed_session_instructions_omit_tables(users: str) -> None:
    async with Client(create_mcp(make_settings())) as client:
        assert client.instructions is not None and users not in client.instructions
