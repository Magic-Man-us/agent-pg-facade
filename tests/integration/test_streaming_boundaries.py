from __future__ import annotations

import asyncio

import pytest
from psycopg import sql
from psycopg.errors import Diagnostic

from pgfacade import InvalidRequest, MyApp, PgSettings
from pgfacade.contracts.enums import ErrorCode
from pgfacade.contracts.rows import RowsCount, RowsCountInput
from pgfacade.contracts.types import ResultText
from tests.conftest import unique
from tests.support import fails, successful

pytestmark = pytest.mark.integration
NOTICE = "pgfacade-stream-invoked"


async def test_empty_stream_returns_columns_without_replaying_sql(db: MyApp) -> None:
    function = unique("empty_stream")
    notices: list[ResultText] = []

    def count_call(diagnostic: Diagnostic) -> None:
        if diagnostic.message_primary == NOTICE:
            notices.append(diagnostic.message_primary)

    async with db.tx() as conn:
        await conn.execute(
            sql.SQL(
                "CREATE FUNCTION {}() RETURNS TABLE (value integer) LANGUAGE plpgsql AS $$ BEGIN RAISE NOTICE 'pgfacade-stream-invoked'; RETURN; END $$"
            ).format(sql.Identifier(function))
        )
    try:
        async with db.tx(read_only=True, rollback=True) as conn:
            conn.add_notice_handler(count_call)
            try:
                result = await db.stream(conn, sql.SQL("SELECT value AS café FROM {}()").format(sql.Identifier(function)), None, 10)
            finally:
                conn.remove_notice_handler(count_call)
        assert result.columns == ["café"]
        assert result.rows == []
        assert notices == [NOTICE]
    finally:
        async with db.tx() as conn:
            await conn.execute(sql.SQL("DROP FUNCTION {}()").format(sql.Identifier(function)))


async def test_truncated_stream_releases_its_connection(settings: PgSettings) -> None:
    async with MyApp(settings.model_copy(update={"pool_min": 1, "pool_max": 1})) as db:
        async with db.tx(read_only=True, rollback=True) as conn:
            backend = conn.info.backend_pid
            result = await db.stream(conn, sql.SQL("SELECT generate_series(1, 100000) AS value"), None, 2)
        assert result.rows == [{"value": 1}, {"value": 2}]
        assert result.truncated
        async with db.tx() as conn:
            assert conn.info.backend_pid == backend
            row = await (await conn.execute("SELECT 7 AS value")).fetchone()
            assert row == {"value": 7}


async def test_cancelled_stream_releases_its_connection(settings: PgSettings) -> None:
    async with MyApp(settings.model_copy(update={"pool_min": 1, "pool_max": 1})) as db:
        function = unique("slow_stream")
        started = asyncio.Event()

        def signal_start(diagnostic: Diagnostic) -> None:
            if diagnostic.message_primary == NOTICE:
                started.set()

        async with db.tx() as conn:
            await conn.execute(
                sql.SQL(
                    "CREATE FUNCTION {}() RETURNS integer LANGUAGE plpgsql AS $$ BEGIN RAISE NOTICE 'pgfacade-stream-invoked'; PERFORM pg_sleep(30); RETURN 1; END $$"
                ).format(sql.Identifier(function))
            )
        try:
            async with db.tx(read_only=True, rollback=True) as conn:
                backend = conn.info.backend_pid
                conn.add_notice_handler(signal_start)
                task = asyncio.create_task(db.stream(conn, sql.SQL("SELECT {}()").format(sql.Identifier(function)), None, 1))
                try:
                    await asyncio.wait_for(started.wait(), timeout=5)
                finally:
                    task.cancel()
                    with pytest.raises(asyncio.CancelledError):
                        await task
                    conn.remove_notice_handler(signal_start)
            async with db.tx() as conn:
                assert conn.info.backend_pid == backend
                assert await (await conn.execute("SELECT 7 AS value")).fetchone() == {"value": 7}
        finally:
            async with db.tx() as conn:
                await conn.execute(sql.SQL("DROP FUNCTION {}()").format(sql.Identifier(function)))


async def test_transaction_bound_connection_rejects_another_task(db: MyApp, users: ResultText) -> None:
    async with db.transaction() as transaction:
        task = asyncio.create_task(successful(transaction.call(RowsCount(input=RowsCountInput(table=users)))))
        with fails(code=ErrorCode.INVALID_REQUEST, match="belongs to the task"):
            await task
        assert (await successful(transaction.call(RowsCount(input=RowsCountInput(table=users))))).count == 3


async def test_released_transaction_view_cannot_reuse_or_close_the_pool(db: MyApp, users: ResultText) -> None:
    async with db.transaction() as transaction:
        assert (await successful(transaction.call(RowsCount(input=RowsCountInput(table=users))))).count == 3
    with fails(match="no longer active", code=ErrorCode.INVALID_REQUEST):
        await successful(transaction.call(RowsCount(input=RowsCountInput(table=users))))
    await transaction.close()
    assert (await successful(db.call(RowsCount(input=RowsCountInput(table=users))))).count == 3


async def test_released_transaction_view_cannot_acquire_native_resources(db: MyApp) -> None:
    async with db.transaction() as transaction:
        pass
    with pytest.raises(InvalidRequest, match="no longer active"):
        async with transaction.no_tx("test"):
            pytest.fail("A released view must not borrow a connection")
    with pytest.raises(InvalidRequest, match="no longer active"):
        async with transaction.dedicated():
            pytest.fail("A released view must not open a dedicated connection")
    with pytest.raises(InvalidRequest, match="no longer active"):
        await transaction.open()
