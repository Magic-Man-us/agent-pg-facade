"""lifecycle.*, event.*, and query.* through PgFacade.call."""

import asyncio
import json
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from pydantic import ValidationError

from pgfacade import PgFacade, Principal
from pgfacade.contracts.enums import ErrorCode, ErrorReason, KnownValidationCode
from pgfacade.contracts.envelopes import Failure, ValidationDetails
from pgfacade.contracts.events import (
    EventNotify,
    EventNotifyInput,
    EventUnwatch,
    EventUnwatchInput,
    EventWait,
    EventWaitInput,
    EventWatch,
    EventWatchInput,
    EventWatchList,
    EventWatchListInput,
)
from pgfacade.contracts.lifecycle import (
    LifecycleInstall,
    LifecycleInstallInput,
    LifecycleList,
    LifecycleListInput,
    LifecyclePreview,
    LifecyclePreviewInput,
    LifecycleRemove,
    LifecycleRemoveInput,
    LifecycleRowTtl,
    LifecycleRowTtlInput,
    LifecycleRun,
    LifecycleRunInput,
    LifecycleRuns,
    LifecycleRunsInput,
    LifecycleSchedule,
    LifecycleScheduleInput,
    LifecycleTableExpiry,
    LifecycleTableExpiryInput,
)
from pgfacade.contracts.queries import QueryList, QueryListInput, QueryReload, QueryReloadInput, QueryRun, QueryRunInput
from pgfacade.contracts.rows import (
    RowsCount,
    RowsCountInput,
    RowsInsert,
    RowsInsertInput,
    RowsSelect,
    RowsSelectInput,
    RowsUpdate,
    RowsUpdateInput,
    SqlExecute,
    SqlExecuteInput,
)
from pgfacade.contracts.schema import ColumnAdd, ColumnAddInput, ColumnSpec, TableCreate, TableCreateInput, TableDrop, TableDropInput
from tests.conftest import age_rows, make_settings, unique
from tests.support import fails, successful

pytestmark = pytest.mark.integration


@pytest.fixture
async def lifecycle(db: PgFacade) -> AsyncIterator[PgFacade]:
    """Installed, with no policies before or after."""
    await successful(db.call(LifecycleInstall(input=LifecycleInstallInput())))
    for p in (await successful(db.call(LifecycleList(input=LifecycleListInput())))).items:
        await successful(db.call(LifecycleRemove(input=LifecycleRemoveInput(policy_id=p.id))))
    yield db
    for p in (await successful(db.call(LifecycleList(input=LifecycleListInput())))).items:
        await successful(db.call(LifecycleRemove(input=LifecycleRemoveInput(policy_id=p.id))))


async def test_install_is_idempotent_and_list_reports_state(lifecycle: PgFacade) -> None:
    assert (await successful(lifecycle.call(LifecycleInstall(input=LifecycleInstallInput())))).status == "INSTALLED"
    listing = await successful(lifecycle.call(LifecycleList(input=LifecycleListInput())))
    assert listing.installed and listing.items == [] and (listing.scheduled is None)
    with fails(match="pg_cron", code=ErrorCode.NOT_FOUND):
        await successful(lifecycle.call(LifecycleSchedule(input=LifecycleScheduleInput(cron="*/5 * * * *"))))


async def test_row_ttl_delete_with_preview_history_and_event(lifecycle: PgFacade, users: str) -> None:
    db = lifecycle
    await age_rows(db, users, ["ann@x.io", "bob@x.io"], days=10)
    policy = await successful(db.call(LifecycleRowTtl(input=LifecycleRowTtlInput(table=users, column="created_at", ttl="7 days"))))
    assert policy.kind == "row_ttl" and policy.action == "delete" and (policy.ttl == "7 days") and (policy.last_run_at is None)
    assert (await successful(db.call(LifecyclePreview(input=LifecyclePreviewInput(policy_id=policy.id))))).count == 2
    waiter = asyncio.create_task(
        successful(db.call(EventWait(input=EventWaitInput(channels=[db.settings.lifecycle_channel], timeout_s=5, max_events=1))))
    )
    await asyncio.sleep(0.3)
    report = await successful(db.call(LifecycleRun(input=LifecycleRunInput(policy_id=policy.id))))
    assert [(o.policy_id, o.rows_affected, o.error) for o in report.items] == [(policy.id, 2, None)]
    assert (await successful(db.call(RowsCount(input=RowsCountInput(table=users))))).count == 1
    event = json.loads((await waiter).items[0].payload)
    assert event["event"] == "lifecycle.run" and event["policy_id"] == policy.id and (event["rows_affected"] == 2)
    runs = (await successful(db.call(LifecycleRuns(input=LifecycleRunsInput(policy_id=policy.id))))).items
    assert len(runs) == 1 and runs[0].rows_affected == 2 and (runs[0].action == "delete") and (runs[0].error is None)
    listed = (await successful(db.call(LifecycleList(input=LifecycleListInput())))).items[0]
    assert listed.last_rows == 2 and listed.last_run_at is not None
    assert (await successful(db.call(LifecycleRun(input=LifecycleRunInput(policy_id=policy.id))))).items[0].rows_affected == 0
    assert (await successful(db.call(LifecyclePreview(input=LifecyclePreviewInput(policy_id=policy.id))))).count == 0


async def test_row_ttl_archive(lifecycle: PgFacade, users: str) -> None:
    db = lifecycle
    await age_rows(db, users, ["ann@x.io", "bob@x.io"], days=40)
    policy = await successful(
        db.call(LifecycleRowTtl(input=LifecycleRowTtlInput(table=users, column="created_at", ttl="30 days", action="archive")))
    )
    assert policy.action == "archive" and policy.archive_table == f"public.{users}_archive"
    assert (await successful(db.call(LifecycleRun(input=LifecycleRunInput(policy_id=policy.id))))).items[0].rows_affected == 2
    assert (await successful(db.call(RowsCount(input=RowsCountInput(table=users))))).count == 1
    archived = await successful(db.call(RowsSelect(input=RowsSelectInput(table=f"{users}_archive"))))
    assert {r["email"] for r in archived.rows} == {"ann@x.io", "bob@x.io"} and all(r["archived_at"] for r in archived.rows)
    await successful(db.call(TableDrop(input=TableDropInput(table=f"{users}_archive"))))


async def test_row_ttl_expiry_column_batches_and_add_column(lifecycle: PgFacade, users: str) -> None:
    db = lifecycle
    await successful(db.call(ColumnAdd(input=ColumnAddInput(table=users, column=ColumnSpec(name="expires_at", type="timestamptz")))))
    await successful(
        db.call(
            SqlExecute(
                input=SqlExecuteInput(
                    sql=f'''UPDATE "{users}" SET expires_at = now() - interval '1 minute' WHERE email <> %s''', params=["cat@x.io"]
                )
            )
        )
    )
    policy = await successful(db.call(LifecycleRowTtl(input=LifecycleRowTtlInput(table=users, column="expires_at", batch_size=1))))
    assert policy.ttl is None
    assert (await successful(db.call(LifecycleRun(input=LifecycleRunInput(policy_id=policy.id))))).items[0].rows_affected == 2
    assert [r["email"] for r in (await successful(db.call(RowsSelect(input=RowsSelectInput(table=users))))).rows] == ["cat@x.io"]
    added = await successful(
        db.call(LifecycleRowTtl(input=LifecycleRowTtlInput(table=users, column="seen_at", ttl="1 day", add_column=True)))
    )
    assert added.column_name == "seen_at"
    assert "seen_at" in {c for c in (await successful(db.call(RowsSelect(input=RowsSelectInput(table=users))))).columns}
    assert (await successful(db.call(LifecyclePreview(input=LifecyclePreviewInput(policy_id=added.id))))).count == 0


async def test_table_expiry(lifecycle: PgFacade) -> None:
    db = lifecycle
    doomed, kept = (unique("doomed"), unique("kept"))
    for t in (doomed, kept):
        await successful(db.call(TableCreate(input=TableCreateInput(table=t, columns=[ColumnSpec(name="id", type="int")]))))
        await successful(db.call(RowsInsert(input=RowsInsertInput(table=t, rows=[{"id": 1}]))))
    try:
        drop = await successful(
            db.call(LifecycleTableExpiry(input=LifecycleTableExpiryInput(table=doomed, expires_in="0 seconds", action="drop")))
        )
        trunc = await successful(
            db.call(LifecycleTableExpiry(input=LifecycleTableExpiryInput(table=kept, expires_at="2000-01-01T00:00:00Z")))
        )
        assert drop.expires_at is not None and trunc.action == "truncate"
        assert (await successful(db.call(LifecyclePreview(input=LifecyclePreviewInput(policy_id=drop.id))))).count == 1
        outcomes = {o.policy_id: o.rows_affected for o in (await successful(db.call(LifecycleRun(input=LifecycleRunInput())))).items}
        assert outcomes[drop.id] == 1 and outcomes[trunc.id] == 1
        with fails(code=ErrorCode.NOT_FOUND):
            await successful(db.call(RowsCount(input=RowsCountInput(table=doomed))))
        assert (await successful(db.call(RowsCount(input=RowsCountInput(table=kept))))).count == 0
        assert not {p.id: p for p in (await successful(db.call(LifecycleList(input=LifecycleListInput())))).items}[drop.id].enabled
        assert (await successful(db.call(LifecyclePreview(input=LifecyclePreviewInput(policy_id=drop.id))))).count == 0
    finally:
        await successful(db.call(TableDrop(input=TableDropInput(table=kept))))


async def test_lifecycle_validation_and_errors(lifecycle: PgFacade, users: str) -> None:
    db = lifecycle
    with fails(match="needs a timestamp", code=ErrorCode.INVALID_REQUEST):
        await successful(db.call(LifecycleRowTtl(input=LifecycleRowTtlInput(table=users, column="email", ttl="1 day"))))
    with fails(match="add_column=true", code=ErrorCode.INVALID_REQUEST):
        await successful(db.call(LifecycleRowTtl(input=LifecycleRowTtlInput(table=users, column="nope"))))
    with fails(code=ErrorCode.NOT_FOUND):
        await successful(db.call(LifecycleRowTtl(input=LifecycleRowTtlInput(table="no_such_table", column="created_at"))))
    with pytest.raises(ValidationError, match="exactly one"):
        await successful(db.call(LifecycleTableExpiry(input=LifecycleTableExpiryInput(table=users))))
    with fails(code=ErrorCode.NOT_FOUND):
        await successful(db.call(LifecycleRemove(input=LifecycleRemoveInput(policy_id=999999))))
    with fails(code=ErrorCode.NOT_FOUND):
        await successful(db.call(LifecyclePreview(input=LifecyclePreviewInput(policy_id=999999))))
    with fails(code=ErrorCode.FORBIDDEN):
        await successful(
            db.as_(Principal(name="ro", read_only=True, admin=True)).call(
                LifecycleRowTtl(input=LifecycleRowTtlInput(table=users, column="created_at", ttl="1 day"))
            )
        )
    victim = unique("victim")
    await successful(
        db.call(
            TableCreate(input=TableCreateInput(table=victim, columns=[ColumnSpec(name="at", type="timestamptz", default_expr="now()")]))
        )
    )
    policy = await successful(db.call(LifecycleRowTtl(input=LifecycleRowTtlInput(table=victim, column="at", ttl="1 day"))))
    await successful(db.call(TableDrop(input=TableDropInput(table=victim))))
    outcome = (await successful(db.call(LifecycleRun(input=LifecycleRunInput(policy_id=policy.id))))).items[0]
    assert outcome.rows_affected == 0 and outcome.error and ("does not exist" in outcome.error)
    assert (await successful(db.call(LifecycleRuns(input=LifecycleRunsInput(policy_id=policy.id))))).items[0].error == outcome.error


async def test_background_sweeper(users: str) -> None:
    async with PgFacade(make_settings(lifecycle_sweep_s=0.2)) as db:
        await successful(db.call(LifecycleInstall(input=LifecycleInstallInput())))
        await age_rows(db, users, ["ann@x.io"], days=3)
        policy = await successful(db.call(LifecycleRowTtl(input=LifecycleRowTtlInput(table=users, column="created_at", ttl="1 day"))))
        try:
            for _ in range(50):
                await asyncio.sleep(0.1)
                if (await successful(db.call(LifecycleRuns(input=LifecycleRunsInput(policy_id=policy.id))))).items:
                    break
            assert (await successful(db.call(RowsCount(input=RowsCountInput(table=users))))).count == 2
        finally:
            await successful(db.call(LifecycleRemove(input=LifecycleRemoveInput(policy_id=policy.id))))


async def test_notify_and_wait(db: PgFacade) -> None:
    channel = unique("chan")
    waiter = asyncio.create_task(
        successful(db.call(EventWait(input=EventWaitInput(channels=[channel, "other"], timeout_s=5, max_events=2))))
    )
    await asyncio.sleep(0.3)
    await successful(db.call(EventNotify(input=EventNotifyInput(channel=channel, payload="one"))))
    await successful(db.call(EventNotify(input=EventNotifyInput(channel="other", payload="two"))))
    got = await waiter
    assert [(n.channel, n.payload) for n in got.items] == [(channel, "one"), ("other", "two")] and (not got.timed_out)
    empty = await successful(db.call(EventWait(input=EventWaitInput(channels=[channel], timeout_s=0.2))))
    assert empty.items == [] and empty.timed_out
    with fails(match="may not listen", code=ErrorCode.FORBIDDEN):
        await successful(db.as_(Principal(name="deaf")).call(EventWait(input=EventWaitInput(channels=[channel], timeout_s=0.1))))


async def test_table_watch(db: PgFacade, users: str) -> None:
    watch = await successful(db.call(EventWatch(input=EventWatchInput(table=users, events=["insert", "delete"], columns=["id", "email"]))))
    assert watch.channel == f"pgfacade:public.{users}" and watch.events == ["delete", "insert"] and (watch.columns == ["id", "email"])
    listed = [w for w in (await successful(db.call(EventWatchList(input=EventWatchListInput())))).items if w.table_name == users]
    assert (
        listed
        and listed[0].channel == watch.channel
        and (set(listed[0].events) == {"insert", "delete"})
        and (listed[0].columns == ["id", "email"])
    )
    waiter = asyncio.create_task(successful(db.call(EventWait(input=EventWaitInput(channels=[watch.channel], timeout_s=5, max_events=2)))))
    await asyncio.sleep(0.3)
    await successful(db.call(RowsInsert(input=RowsInsertInput(table=users, rows=[{"email": "new@x.io", "score": 9}]))))
    await successful(db.call(RowsUpdate(input=RowsUpdateInput(table=users, values={"score": 1}, match={"email": "new@x.io"}))))
    await successful(db.call(SqlExecute(input=SqlExecuteInput(sql=f'DELETE FROM "{users}" WHERE email = %s', params=["new@x.io"]))))
    events = [json.loads(n.payload) for n in (await waiter).items]
    assert [e["op"] for e in events] == ["insert", "delete"]
    assert events[0]["table"] == users and events[0]["schema"] == "public" and (set(events[0]["row"]) == {"id", "email"})
    assert events[0]["row"]["email"] == "new@x.io" and "at" in events[0]
    custom = unique("ch")
    await successful(db.call(EventWatch(input=EventWatchInput(table=users, channel=custom))))
    waiter = asyncio.create_task(successful(db.call(EventWait(input=EventWaitInput(channels=[custom], timeout_s=5, max_events=1)))))
    await asyncio.sleep(0.3)
    await successful(db.call(RowsUpdate(input=RowsUpdateInput(table=users, values={"score": 0}, match={"id": 1}))))
    event = json.loads((await waiter).items[0].payload)
    assert event["op"] == "update" and event["row"]["score"] == 0 and ("tags" in event["row"])
    assert (await successful(db.call(EventUnwatch(input=EventUnwatchInput(table=users))))).status == "DROP TRIGGER"
    assert not [w for w in (await successful(db.call(EventWatchList(input=EventWatchListInput())))).items if w.table_name == users]


async def test_catalog_contents(db: PgFacade) -> None:
    listing = await successful(db.call(QueryList(input=QueryListInput())))
    names = {q.name for q in listing.items}
    assert {"size.tables", "health.long_running", "index.missing_fk", "rows.duplicates", "table.column_stats"} <= names
    assert listing.directory is None and all(q.source == "builtin" for q in listing.items)
    dup = next(q for q in listing.items if q.name == "rows.duplicates")
    assert dup.category == "rows" and [p.name for p in dup.params] == ["table", "column", "min_count"]
    assert dup.params[0].required and dup.params[0].type == "table" and (not dup.params[2].required) and (dup.params[2].default == 2)
    assert {q.name for q in (await successful(db.call(QueryList(input=QueryListInput(category="security"))))).items} >= {
        "security.superusers",
        "security.rls_status",
    }


async def test_row_level_queries(db: PgFacade, users: str) -> None:
    assert (await successful(db.call(QueryRun(input=QueryRunInput(name="rows.recent", params={"table": users, "limit": 2}))))).rowcount == 2
    assert (
        await successful(
            db.call(QueryRun(input=QueryRunInput(name="rows.since", params={"table": users, "since": "2000-01-01T00:00:00Z"})))
        )
    ).rowcount == 3
    assert (await successful(db.call(QueryRun(input=QueryRunInput(name="rows.count_by_day", params={"table": users}))))).rows[0]["n"] == 3
    res = await successful(db.call(QueryRun(input=QueryRunInput(name="rows.distinct_values", params={"table": users, "column": "score"}))))
    assert [(r["value"], r["n"]) for r in res.rows] == [(3, 1), (5, 1), (None, 1)]
    await successful(db.call(RowsInsert(input=RowsInsertInput(table=users, rows=[{"email": "dup@x.io", "score": 5}]))))
    assert (
        await successful(db.call(QueryRun(input=QueryRunInput(name="rows.duplicates", params={"table": users, "column": "score"}))))
    ).rows == [{"value": 5, "n": 2}]
    res = await successful(
        db.call(QueryRun(input=QueryRunInput(name="rows.duplicates", params={"table": users, "column": "score", "min_count": 1}, limit=1)))
    )
    assert res.rowcount == 1 and res.truncated
    child = unique("orders")
    await successful(
        db.call(
            TableCreate(
                input=TableCreateInput(
                    table=child, columns=[ColumnSpec(name="id", type="int", primary_key=True), ColumnSpec(name="user_id", type="bigint")]
                )
            )
        )
    )
    try:
        await successful(
            db.call(
                RowsInsert(
                    input=RowsInsertInput(
                        table=child, rows=[{"id": 1, "user_id": 1}, {"id": 2, "user_id": 999}, {"id": 3, "user_id": None}]
                    )
                )
            )
        )
        res = await successful(
            db.call(
                QueryRun(
                    input=QueryRunInput(
                        name="rows.orphans", params={"table": child, "column": "user_id", "parent": users, "parent_column": "id"}
                    )
                )
            )
        )
        assert [r["id"] for r in res.rows] == [2]
        assert (await successful(db.call(QueryRun(input=QueryRunInput(name="table.foreign_keys", params={"table": users}))))).rows == []
    finally:
        await successful(db.call(TableDrop(input=TableDropInput(table=child))))
    for name in ("table.column_stats", "table.index_usage"):
        assert (await successful(db.call(QueryRun(input=QueryRunInput(name=name, params={"table": users}))))).columns


@pytest.mark.parametrize(
    "name",
    [
        "size.database",
        "size.tables",
        "health.connections",
        "health.long_running",
        "maintenance.bloat",
        "index.unused",
        "index.missing_fk",
        "schema.no_primary_key",
        "security.superusers",
        "security.rls_status",
    ],
)
async def test_catalog_queries_run(db: PgFacade, name: str) -> None:
    assert (await successful(db.call(QueryRun(input=QueryRunInput(name=name))))).columns


async def test_query_param_handling(db: PgFacade, users: str) -> None:
    cases = (
        (QueryRunInput(name="rows.recent"), "table", KnownValidationCode.MISSING),
        (QueryRunInput(name="rows.recent", params={"table": users, "bogus": 1}), "bogus", KnownValidationCode.EXTRA_FORBIDDEN),
        (QueryRunInput(name="rows.recent", params={"table": users, "limit": "many"}), "limit", KnownValidationCode.INT_PARSING),
    )
    for request, parameter, expected_code in cases:
        response = await db.call(QueryRun(input=request))
        assert isinstance(response.outcome, Failure)
        error = response.outcome.error
        assert error.code is ErrorCode.VALIDATION_ERROR
        assert error.reason is ErrorReason.INPUT_INVALID
        assert error.message == "Request validation failed"
        assert isinstance(error.details, ValidationDetails)
        assert error.details.issues[0].path == (parameter,)
        assert error.details.issues[0].code == expected_code
    with fails(match='column "nope"', code=ErrorCode.INVALID_REQUEST):
        await successful(db.call(QueryRun(input=QueryRunInput(name="rows.recent", params={"table": users, "column": "nope"}))))
    with fails(code=ErrorCode.NOT_FOUND):
        await successful(db.call(QueryRun(input=QueryRunInput(name="rows.recent", params={"table": "no_such_table"}))))
    with fails(code=ErrorCode.NOT_FOUND):
        await successful(db.call(QueryRun(input=QueryRunInput(name="nope"))))
    with fails(match="pg_stat_statements", code=ErrorCode.NOT_FOUND):
        await successful(db.call(QueryRun(input=QueryRunInput(name="statements.top_total_time"))))
    agent = db.as_(Principal(name="agent", sql=False, read_only=True))
    assert (await successful(agent.call(QueryRun(input=QueryRunInput(name="rows.recent", params={"table": users}))))).rowcount == 3


async def test_queries_directory(tmp_path: Path, users: str) -> None:
    (tmp_path / "custom.top_scores.sql").write_text(
        "-- description: Highest scores\n-- param: table:table The table\n-- param: n:int=2 How many\nSELECT email, score FROM {table} WHERE score IS NOT NULL ORDER BY score DESC LIMIT %(n)s\n"
    )
    (tmp_path / "rows.duplicates.sql").write_text("-- description: override\nSELECT 1 AS overridden\n")
    (tmp_path / "custom.sneaky.sql").write_text("-- param: table:table T\nDELETE FROM {table}\n")
    async with PgFacade(make_settings(queries_dir=tmp_path)) as db:
        await successful(db.call(QueryReload(input=QueryReloadInput())))
        listing = await successful(db.call(QueryList(input=QueryListInput(category="custom"))))
        assert listing.directory == str(tmp_path) and {q.name for q in listing.items} == {"custom.top_scores", "custom.sneaky"}
        top = next(q for q in listing.items if q.name == "custom.top_scores")
        assert top.source == str(tmp_path / "custom.top_scores.sql") and top.params[1].default == 2
        assert (
            await successful(db.call(QueryRun(input=QueryRunInput(name="custom.top_scores", params={"table": users, "n": 1}))))
        ).rows == [{"email": "ann@x.io", "score": 5}]
        assert (await successful(db.call(QueryRun(input=QueryRunInput(name="rows.duplicates"))))).rows == [{"overridden": 1}]
        with fails(code=ErrorCode.FORBIDDEN, sqlstate="25006"):
            await successful(db.call(QueryRun(input=QueryRunInput(name="custom.sneaky", params={"table": users}))))
        assert (await successful(db.call(RowsCount(input=RowsCountInput(table=users))))).count == 3
        (tmp_path / "rows.duplicates.sql").unlink()
        await successful(db.call(QueryReload(input=QueryReloadInput())))
        assert (
            next(q for q in (await successful(db.call(QueryList(input=QueryListInput())))).items if q.name == "rows.duplicates").source
            == "builtin"
        )
        (tmp_path / "broken.sql").write_text("-- param: nonsense\nSELECT 1\n")
        with fails(match="Invalid query parameter declaration", code=ErrorCode.INVALID_REQUEST):
            await successful(db.call(QueryReload(input=QueryReloadInput())))
