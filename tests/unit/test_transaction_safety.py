from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Self
from unittest.mock import AsyncMock, Mock, patch

import pytest

from pgfacade import MyApp, PgSettings, Principal
from pgfacade.contracts.admin import (
    MaintBackend,
    MaintBackendInput,
    MaintReindex,
    MaintReindexInput,
    MigrationHistory,
    MigrationHistoryInput,
    MigrationInit,
    MigrationInitInput,
    MigrationRevision,
    MigrationRevisionInput,
    MigrationRun,
    MigrationRunInput,
    MigrationStatusGet,
    MigrationStatusGetInput,
)
from pgfacade.contracts.base import Contract
from pgfacade.contracts.enums import ErrorCode
from pgfacade.contracts.queries import QueryList, QueryListInput, QueryReload, QueryReloadInput, QueryRun, QueryRunInput
from pgfacade.contracts.requests import Batch, BatchInput
from pgfacade.contracts.rows import RowsInsert, RowsInsertInput
from pgfacade.infrastructure.postgres.queries.registry import Statement
from pgfacade.infrastructure.postgres.queries.types import QueryAccess
from pgfacade.shared.types import SecurityFlag
from tests.support import fails, successful


class UnopenedFacade(MyApp):
    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[Self]:
        pytest.fail("A migration batch must be rejected before opening a database transaction")
        yield self


class BoundFacade(MyApp):
    @property
    def in_transaction(self) -> SecurityFlag:
        return True


@pytest.mark.parametrize(
    "migration",
    [
        MigrationInit(input=MigrationInitInput()),
        MigrationStatusGet(input=MigrationStatusGetInput()),
        MigrationHistory(input=MigrationHistoryInput()),
        MigrationRevision(input=MigrationRevisionInput(message="blocked")),
        MigrationRun(input=MigrationRunInput(action="upgrade")),
    ],
)
async def test_batch_migration_preflight_runs_before_any_database_work(migration: Contract) -> None:
    db = UnopenedFacade(PgSettings(_env_file=None, allow_migrate=True))
    batch = Batch(
        input=BatchInput(requests=[RowsInsert(input=RowsInsertInput(table="batch_probe", rows=[{"note": "not committed"}])), migration])
    )
    with fails(match="cannot run inside a transaction", code=ErrorCode.INVALID_REQUEST):
        await successful(db.call(batch))


async def test_bound_transaction_rejects_migration_status_before_handler(tmp_path: Path) -> None:
    db = BoundFacade(PgSettings(_env_file=None, allow_migrate=True, migrations_dir=tmp_path))
    with fails(match="cannot run inside a transaction", code=ErrorCode.INVALID_REQUEST):
        await successful(db.call(MigrationStatusGet(input=MigrationStatusGetInput())))


async def test_migration_preflight_preserves_permission_denial() -> None:
    db = UnopenedFacade(PgSettings(_env_file=None))
    with fails(match="migrations are disabled", code=ErrorCode.FORBIDDEN):
        await successful(db.call(Batch(input=BatchInput(requests=[MigrationInit(input=MigrationInitInput())]))))


async def test_query_list_hides_unavailable_builtin_diagnostics() -> None:
    db = MyApp(PgSettings(_env_file=None))
    result = await successful(db.call(QueryList(input=QueryListInput())))
    names = {query.name for query in result.items}
    assert names.isdisjoint(statement.query_name for statement in Statement if statement.access == QueryAccess.ADMIN)
    assert {"rows.duplicates", "table.column_stats"} <= names
    assert (await successful(db.call(QueryList(input=QueryListInput(category="health"))))).items == []


async def test_query_list_requires_both_server_and_principal_admin() -> None:
    db = MyApp(PgSettings(_env_file=None, allow_admin=True))
    result = await successful(db.call(QueryList(input=QueryListInput())))
    assert {statement.query_name for statement in Statement if statement.access == QueryAccess.ADMIN} <= {
        query.name for query in result.items
    }
    reader = db.as_(Principal(name="reader", read_only=True))
    result = await successful(reader.call(QueryList(input=QueryListInput())))
    assert {query.name for query in result.items}.isdisjoint(
        statement.query_name for statement in Statement if statement.access == QueryAccess.ADMIN
    )


async def test_query_list_keeps_builtin_name_overrides_admin_only(tmp_path: Path) -> None:
    (tmp_path / "health.connections.sql").write_text("-- category: custom\nSELECT 1 AS harmless")
    (tmp_path / "custom.safe.sql").write_text("-- category: custom\nSELECT 1 AS harmless")
    db = MyApp(PgSettings(_env_file=None, queries_dir=tmp_path))
    result = await successful(db.call(QueryList(input=QueryListInput(category="custom"))))
    assert [query.name for query in result.items] == ["custom.safe"]
    with fails(code=ErrorCode.FORBIDDEN):
        await successful(db.call(QueryRun(input=QueryRunInput(name="health.connections"))))


@pytest.mark.parametrize(
    "operation", [MaintBackend(input=MaintBackendInput(action="cancel", pid=0)), QueryReload(input=QueryReloadInput())]
)
async def test_batch_rejects_external_side_effects_before_database_work(operation: Contract) -> None:
    db = UnopenedFacade(PgSettings(_env_file=None, allow_admin=True))
    batch = Batch(
        input=BatchInput(requests=[RowsInsert(input=RowsInsertInput(table="batch_probe", rows=[{"note": "not committed"}])), operation])
    )
    with fails(match="cannot run inside a transaction", code=ErrorCode.INVALID_REQUEST):
        await successful(db.call(batch))


@pytest.mark.parametrize(
    "operation", [MaintBackend(input=MaintBackendInput(action="cancel", pid=0)), QueryReload(input=QueryReloadInput())]
)
async def test_bound_transaction_rejects_external_side_effects_before_handlers(operation: Contract) -> None:
    db = BoundFacade(PgSettings(_env_file=None, allow_admin=True))
    backend_read = AsyncMock(side_effect=AssertionError("Backend handler must not run"))
    reload_queries = Mock(side_effect=AssertionError("Query reload handler must not run"))
    with patch.object(MyApp, "read", backend_read), patch("pgfacade.application.operations.queries.reload", reload_queries):
        with fails(match="cannot run inside a transaction", code=ErrorCode.INVALID_REQUEST):
            await successful(db.call(operation))
    backend_read.assert_not_called()
    reload_queries.assert_not_called()


@pytest.mark.parametrize(
    "operation",
    [
        MaintReindex(input=MaintReindexInput(kind="schema", name="public")),
        MaintReindex(input=MaintReindexInput(kind="table", name="public.notes", concurrently=True)),
    ],
)
async def test_batch_rejects_nontransactional_reindex_before_database_work(operation: MaintReindex) -> None:
    db = UnopenedFacade(PgSettings(_env_file=None, allow_admin=True))
    batch = Batch(
        input=BatchInput(requests=[RowsInsert(input=RowsInsertInput(table="batch_probe", rows=[{"note": "not committed"}])), operation])
    )
    with fails(match="cannot run inside a transaction", code=ErrorCode.INVALID_REQUEST):
        await successful(db.call(batch))


async def test_bound_transaction_rejects_schema_reindex_before_handler() -> None:
    db = BoundFacade(PgSettings(_env_file=None, allow_admin=True))
    handler = AsyncMock(side_effect=AssertionError("REINDEX handler must not run"))
    with patch("pgfacade.application.operations.admin.reindex", handler):
        with fails(match="cannot run inside a transaction", code=ErrorCode.INVALID_REQUEST):
            await successful(db.call(MaintReindex(input=MaintReindexInput(kind="schema", name="public"))))
    handler.assert_not_called()


@pytest.mark.parametrize("analyze", [False, True])
async def test_explain_uses_read_only_rollback_transaction(monkeypatch: pytest.MonkeyPatch, analyze: bool) -> None:
    from typing import cast

    from pgfacade.application.operations.rows import explain
    from pgfacade.contracts.rows import SqlExplain, SqlExplainInput
    from pgfacade.infrastructure.postgres.engine import Conn

    application = MyApp(PgSettings(_env_file=None))
    connection = Mock()
    cursor = Mock()
    cursor.execute = AsyncMock()
    cursor.fetchone = AsyncMock(return_value={"QUERY PLAN": [{"Plan": {}}]})
    connection.cursor.return_value = cursor
    modes: list[tuple[bool, bool]] = []

    @asynccontextmanager
    async def transaction(*, read_only: bool = False, rollback: bool = False) -> AsyncIterator[Conn]:
        modes.append((read_only, rollback))
        yield cast(Conn, connection)

    monkeypatch.setattr(application, "tx", transaction)
    result = await explain(application, SqlExplain(input=SqlExplainInput(sql="SELECT 1", analyze=analyze)))
    assert result.plan == [{"Plan": {}}]
    assert modes == [(True, True)]
    cursor.execute.assert_awaited_once()
