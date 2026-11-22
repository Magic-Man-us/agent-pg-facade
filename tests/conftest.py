"""Shared fixtures. Tests need a scratch database: set PGFACADE_TEST_DSN, otherwise they are skipped."""

import os
import uuid
from collections.abc import AsyncIterator
from typing import Any

import pytest
from fastmcp import Client

from pgfacade import PgFacade, PgSettings, Principal
from pgfacade.contracts.rows import RowsInsert, RowsInsertInput, SqlExecute, SqlExecuteInput
from pgfacade.contracts.schema import ColumnSpec, TableCreate, TableCreateInput, TableDrop, TableDropInput
from tests.support import successful

DSN = os.environ.get("PGFACADE_TEST_DSN")


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    if DSN is None:
        skip = pytest.mark.skip(reason="PGFACADE_TEST_DSN not set")
        for item in items:
            if item.get_closest_marker("integration") is not None:
                item.add_marker(skip)


TEST_KEY = "integration-test-key"
TEST_HEADERS = {"Authorization": f"Bearer {TEST_KEY}"}


def make_settings(**overrides: Any) -> PgSettings:
    assert DSN is not None
    defaults = {"allow_admin": True, "allow_ddl": True, "allow_raw_sql": True, "allow_migrate": True, "allow_listen": True}
    defaults.update(
        lifecycle_sweep_s=0,
        keys={TEST_KEY: Principal(name="integration", ddl=True, sql=True, admin=True, migrate=True, listen=True)},
        mcp_key=TEST_KEY,
    )
    defaults.update(overrides)
    return PgSettings(dsn=DSN, _env_file=None, **defaults)


def unique(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


@pytest.fixture(scope="session")
def settings() -> PgSettings:
    return make_settings()


@pytest.fixture(scope="session")
async def db(settings: PgSettings) -> AsyncIterator[PgFacade]:
    async with PgFacade(settings) as facade:
        yield facade


def users_spec(table: str) -> TableCreate:
    return TableCreate(
        input=TableCreateInput(
            table=table,
            columns=[
                ColumnSpec(name="id", type="bigint", identity=True, primary_key=True),
                ColumnSpec(name="email", type="text", nullable=False, unique=True),
                ColumnSpec(name="score", type="int"),
                ColumnSpec(name="meta", type="jsonb"),
                ColumnSpec(name="tags", type="text[]"),
                ColumnSpec(name="created_at", type="timestamptz", default_expr="now()"),
            ],
        )
    )


SEED = [
    {"email": "ann@x.io", "score": 5, "meta": {"plan": "pro"}, "tags": ["a", "b"]},
    {"email": "bob@x.io", "score": 3, "meta": {"plan": "free"}, "tags": ["b"]},
    {"email": "cat@x.io", "score": None, "meta": None, "tags": None},
]


@pytest.fixture
async def users(db: PgFacade) -> AsyncIterator[str]:
    """A fresh, seeded users table with a unique name; dropped afterwards."""
    table = unique("users")
    await successful(db.call(users_spec(table)))
    await successful(db.call(RowsInsert(input=RowsInsertInput(table=table, rows=SEED))))
    try:
        yield table
    finally:
        await successful(db.call(TableDrop(input=TableDropInput(table=table, cascade=True))))


@pytest.fixture
async def clean_alembic(db: PgFacade) -> AsyncIterator[None]:
    """Migration tests share one database; start and finish with no alembic_version table."""
    await successful(db.call(SqlExecute(input=SqlExecuteInput(sql="DROP TABLE IF EXISTS alembic_version"))))
    try:
        yield
    finally:
        await successful(db.call(SqlExecute(input=SqlExecuteInput(sql="DROP TABLE IF EXISTS alembic_version"))))


async def age_rows(db: PgFacade, table: str, emails: list[str], days: int) -> None:
    await successful(
        db.call(
            SqlExecute(
                input=SqlExecuteInput(
                    sql=f'''UPDATE "{table}" SET created_at = now() - %s * interval '1 day' WHERE email = ANY(%s)''', params=[days, emails]
                )
            )
        )
    )


async def tool_names(client: Client) -> set[str]:
    return {t.name for t in await client.list_tools()}


async def call_tool(client: Client, tool: str, **args: Any) -> Any:
    result = await client.call_tool(tool, {"request": {"input": args}})
    assert result.structured_content is not None
    envelope = result.structured_content
    assert envelope["outcome"]["status"] == "success"
    assert set(envelope) == {"kind", "outcome"}
    return envelope["outcome"]["data"]
