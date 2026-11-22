from __future__ import annotations

from pathlib import Path

import pytest

from pgfacade import MyApp
from pgfacade.contracts.admin import (
    MaintReindex,
    MaintReindexInput,
    MigrationInit,
    MigrationInitInput,
    MigrationRevision,
    MigrationRevisionInput,
    MigrationRun,
    MigrationRunInput,
    MigrationStatusGet,
    MigrationStatusGetInput,
)
from pgfacade.contracts.base import TableName
from pgfacade.contracts.enums import ErrorCode
from pgfacade.contracts.requests import Batch, BatchInput
from pgfacade.contracts.rows import (
    RowsCount,
    RowsCountInput,
    RowsInsert,
    RowsInsertInput,
    SqlExecute,
    SqlExecuteInput,
    SqlQuery,
    SqlQueryInput,
)
from pgfacade.contracts.schema import SchemaCreate, SchemaCreateInput, SchemaDrop, SchemaDropInput
from tests.conftest import make_settings, unique
from tests.support import fails, successful


@pytest.mark.integration
async def test_migration_batch_cannot_commit_outside_its_transaction(users: TableName, tmp_path: Path, clean_alembic: None) -> None:
    table = unique("outside_batch")
    async with MyApp(make_settings(migrations_dir=tmp_path)) as db:
        await successful(db.call(MigrationInit(input=MigrationInitInput())))
        await successful(
            db.call(
                MigrationRevision(
                    input=MigrationRevisionInput(
                        message="outside transaction probe",
                        upgrade_sql=f'CREATE TABLE "{table}" (id integer)',
                        downgrade_sql=f'DROP TABLE "{table}"',
                    )
                )
            )
        )
        before = await successful(db.call(RowsCount(input=RowsCountInput(table=users))))
        try:
            with fails(match="cannot run inside a transaction", code=ErrorCode.INVALID_REQUEST):
                await successful(
                    db.call(
                        Batch(
                            input=BatchInput(
                                requests=[
                                    RowsInsert(input=RowsInsertInput(table=users, rows=[{"email": "must-not-commit@example.test"}])),
                                    MigrationRun(input=MigrationRunInput(action="upgrade")),
                                    SqlExecute(input=SqlExecuteInput(sql="SELECT 1 / 0")),
                                ]
                            )
                        )
                    )
                )
            assert (await successful(db.call(RowsCount(input=RowsCountInput(table=users))))).count == before.count
            result = await successful(
                db.call(SqlQuery(input=SqlQueryInput(sql="SELECT to_regclass(%s) IS NULL AS absent", params=[table])))
            )
            assert result.rows == [{"absent": True}]
            assert (await successful(db.call(MigrationStatusGet(input=MigrationStatusGetInput())))).current == []
        finally:
            await successful(db.call(SqlExecute(input=SqlExecuteInput(sql=f'DROP TABLE IF EXISTS "{table}"'))))


@pytest.mark.integration
async def test_explicit_transaction_rejects_migration_file_creation(tmp_path: Path) -> None:
    directory = tmp_path / "not-created"
    async with MyApp(make_settings(migrations_dir=directory)) as db:
        async with db.transaction() as tx:
            with fails(match="cannot run inside a transaction", code=ErrorCode.INVALID_REQUEST):
                await successful(tx.call(MigrationInit(input=MigrationInitInput())))
    assert not directory.exists()


@pytest.mark.integration
async def test_schema_reindex_runs_outside_transaction(db: MyApp) -> None:
    schema = unique("reindex_schema")
    await successful(db.call(SchemaCreate(input=SchemaCreateInput(name=schema))))
    try:
        result = await successful(db.call(MaintReindex(input=MaintReindexInput(kind="schema", name=schema))))
        assert result.status == "REINDEX"
    finally:
        await successful(db.call(SchemaDrop(input=SchemaDropInput(name=schema, cascade=True))))
