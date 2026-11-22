"""rows.*, sql.*, batch, transactions, and principals through MyApp.call."""

import pytest
from pydantic import ValidationError

from pgfacade import REGISTRY, InvalidRequest, MyApp, Principal
from pgfacade.contracts.admin import ServerInfoGet, ServerInfoGetInput, ServerWhoAmI, ServerWhoAmIInput
from pgfacade.contracts.base import Between, Cmp, Contains, Count, In, IsNull, Not, Or, OrderBy, TextSearch
from pgfacade.contracts.enums import ErrorCode
from pgfacade.contracts.requests import Batch, BatchInput
from pgfacade.contracts.rows import (
    Aggregate,
    DoNothing,
    DoUpdate,
    RowsAggregate,
    RowsAggregateInput,
    RowsCount,
    RowsCountInput,
    RowsDelete,
    RowsDeleteInput,
    RowsExists,
    RowsExistsInput,
    RowsExportCsv,
    RowsExportCsvInput,
    RowsGet,
    RowsGetInput,
    RowsImportCsv,
    RowsImportCsvInput,
    RowsInsert,
    RowsInsertInput,
    RowsSelect,
    RowsSelectInput,
    RowsUpdate,
    RowsUpdateInput,
    SqlExecute,
    SqlExecuteInput,
    SqlExplain,
    SqlExplainInput,
    SqlQuery,
    SqlQueryInput,
)
from pgfacade.contracts.schema import (
    ColumnSpec,
    TableCreate,
    TableCreateInput,
    TableDrop,
    TableDropInput,
    TableTruncate,
    TableTruncateInput,
)
from tests.conftest import make_settings, unique
from tests.support import fails, successful

pytestmark = pytest.mark.integration


@pytest.mark.parametrize(("conflict", "expected_score"), [(DoNothing(), 9), (DoUpdate(target=["label"], update=["score"]), 0)])
async def test_default_only_insert_honors_conflict_handling(db: MyApp, conflict: DoNothing | DoUpdate, expected_score: int) -> None:
    table = unique("default_conflict")
    await successful(
        db.call(
            TableCreate(
                input=TableCreateInput(
                    table=table,
                    columns=[
                        ColumnSpec(name="label", type="text", unique=True, default="fixed"),
                        ColumnSpec(name="score", type="int", default=0),
                    ],
                )
            )
        )
    )
    try:
        await successful(db.call(RowsInsert(input=RowsInsertInput(table=table, rows=[{"label": "fixed", "score": 9}]))))
        await successful(db.call(RowsInsert(input=RowsInsertInput(table=table, rows=[{}], on_conflict=conflict))))
        result = await successful(db.call(RowsSelect(input=RowsSelectInput(table=table))))
        assert result.rows == [{"label": "fixed", "score": expected_score}]
    finally:
        await successful(db.call(TableDrop(input=TableDropInput(table=table))))


def test_registry_is_complete() -> None:
    assert len(REGISTRY) >= 85
    spec = REGISTRY["rows.delete"]
    assert spec.area == "rows" and spec.action == "delete" and (spec.hint == "destructive") and spec.perm.write
    assert REGISTRY["sql.execute"].perm.flags() == {"write": True, "raw": True}
    assert REGISTRY["event.wait"].perm.flags() == {"listen": True}


async def test_call_uses_typed_requests_and_validated_boundary_models(db: MyApp, users: str) -> None:
    from pgfacade.contracts.requests import parse_request

    request = parse_request({"kind": "rows.count", "input": {"table": users}})
    result = await successful(db.call(request))
    assert isinstance(result, Count) and result.count == 3
    assert (await successful(db.call(RowsCount(input=RowsCountInput(table=users))))).count == 3
    with pytest.raises(ValidationError):
        parse_request({"kind": "rows.nope", "input": {"table": users}})


async def test_select_all_orders_and_counts(db: MyApp, users: str) -> None:
    page = await successful(
        db.call(RowsSelect(input=RowsSelectInput(table=users, order_by=[OrderBy(column="email", desc=True)], with_total=True)))
    )
    assert [r["email"] for r in page.rows] == ["cat@x.io", "bob@x.io", "ann@x.io"]
    assert page.rowcount == 3 and page.total == 3 and (not page.truncated)


async def test_select_columns_limit_offset(db: MyApp, users: str) -> None:
    page = await successful(
        db.call(
            RowsSelect(
                input=RowsSelectInput(table=users, columns=["email"], order_by=[OrderBy(column="id")], limit=1, offset=1, with_total=True)
            )
        )
    )
    assert page.rows == [{"email": "bob@x.io"}] and page.total == 3


async def test_schema_qualified_table(db: MyApp, users: str) -> None:
    assert (await successful(db.call(RowsCount(input=RowsCountInput(table=f"public.{users}"))))).count == 3


async def test_truncated_flag_respects_max_rows(users: str) -> None:
    async with MyApp(make_settings(max_rows=2)) as small:
        page = await successful(small.call(RowsSelect(input=RowsSelectInput(table=users, order_by=[OrderBy(column="id")]))))
    assert len(page.rows) == 2 and page.truncated


async def test_match_shorthand_and_casts(db: MyApp, users: str) -> None:
    assert [
        r["email"] for r in (await successful(db.call(RowsSelect(input=RowsSelectInput(table=users, match={"score": None}))))).rows
    ] == ["cat@x.io"]
    assert [r["email"] for r in (await successful(db.call(RowsSelect(input=RowsSelectInput(table=users, match={"score": "5"}))))).rows] == [
        "ann@x.io"
    ]


@pytest.mark.parametrize(
    ("filt", "expected"),
    [
        (Cmp(column="score", op="gte", value=4), {"ann@x.io"}),
        (Cmp(column="email", op="ilike", value="B%"), {"bob@x.io"}),
        (Cmp(column="email", op="regex", value="^(ann|cat)"), {"ann@x.io", "cat@x.io"}),
        (Cmp(column="score", op="ne", value=None), {"ann@x.io", "bob@x.io"}),
        (In(column="email", values=["ann@x.io", "cat@x.io"]), {"ann@x.io", "cat@x.io"}),
        (In(column="email", values=[], negate=True), {"ann@x.io", "bob@x.io", "cat@x.io"}),
        (IsNull(column="meta"), {"cat@x.io"}),
        (IsNull(column="meta", negate=True), {"ann@x.io", "bob@x.io"}),
        (Between(column="score", low=3, high=4), {"bob@x.io"}),
        (Contains(column="meta", value={"plan": "pro"}), {"ann@x.io"}),
        (Contains(column="tags", value=["b"]), {"ann@x.io", "bob@x.io"}),
        (TextSearch(column="email", query="bob@x.io"), {"bob@x.io"}),
        (Or(filters=[Cmp(column="score", value=3), IsNull(column="score")]), {"bob@x.io", "cat@x.io"}),
        (Not(filter=Cmp(column="email", value="ann@x.io")), {"bob@x.io", "cat@x.io"}),
    ],
)
async def test_filters(db: MyApp, users: str, filt, expected: set[str]) -> None:
    page = await successful(db.call(RowsSelect(input=RowsSelectInput(table=users, where=[filt]))))
    assert {r["email"] for r in page.rows} == expected


async def test_filter_errors(db: MyApp, users: str) -> None:
    with fails(match="jsonb or array", code=ErrorCode.INVALID_REQUEST):
        await successful(db.call(RowsSelect(input=RowsSelectInput(table=users, where=[Contains(column="email", value="x")]))))
    with fails(match='column "nope"', code=ErrorCode.INVALID_REQUEST):
        await successful(db.call(RowsSelect(input=RowsSelectInput(table=users, match={"nope": 1}))))
    with fails(code=ErrorCode.NOT_FOUND):
        await successful(db.call(RowsSelect(input=RowsSelectInput(table="no_such_table"))))


async def test_get_exists_count(db: MyApp, users: str) -> None:
    assert (await successful(db.call(RowsGet(input=RowsGetInput(table=users, key=1, columns=["email"]))))).row == {"email": "ann@x.io"}
    assert (await successful(db.call(RowsGet(input=RowsGetInput(table=users, key=999))))).row is None
    assert (await successful(db.call(RowsExists(input=RowsExistsInput(table=users, match={"email": "bob@x.io"}))))).ok
    assert not (await successful(db.call(RowsExists(input=RowsExistsInput(table=users, match={"email": "zed@x.io"}))))).ok
    assert (
        await successful(db.call(RowsCount(input=RowsCountInput(table=users, where=[Cmp(column="score", op="gt", value=0)]))))
    ).count == 2


async def test_aggregate(db: MyApp, users: str) -> None:
    aggs = [Aggregate(fn="count"), Aggregate(fn="sum", column="score"), Aggregate(fn="max", column="score", alias="top")]
    assert (await successful(db.call(RowsAggregate(input=RowsAggregateInput(table=users, aggregates=aggs))))).rows == [
        {"count": 3, "sum_score": 8, "top": 5}
    ]
    grouped = await successful(
        db.call(
            RowsAggregate(
                input=RowsAggregateInput(
                    table=users,
                    aggregates=[Aggregate(fn="count")],
                    group_by=["score"],
                    order_by=[OrderBy(column="count", desc=True), OrderBy(column="score", nulls="last")],
                )
            )
        )
    )
    assert [r["score"] for r in grouped.rows] == [3, 5, None]


async def test_insert_returning_and_defaults(db: MyApp, users: str) -> None:
    res = await successful(
        db.call(RowsInsert(input=RowsInsertInput(table=users, rows=[{"email": "dan@x.io"}], returning=["id", "email", "created_at"])))
    )
    assert res.rowcount == 1 and res.rows[0]["email"] == "dan@x.io" and (res.rows[0]["created_at"] is not None)
    res = await successful(
        db.call(RowsInsert(input=RowsInsertInput(table=users, rows=[{"email": "e@x.io", "score": 1}, {"email": "f@x.io"}])))
    )
    assert [r["score"] for r in res.rows] == [1, None]


async def test_upsert_and_do_nothing(db: MyApp, users: str) -> None:
    res = await successful(
        db.call(
            RowsInsert(
                input=RowsInsertInput(table=users, rows=[{"email": "ann@x.io", "score": 50}], on_conflict=DoUpdate(target=["email"]))
            )
        )
    )
    assert res.rows[0]["score"] == 50 and res.rows[0]["meta"] == {"plan": "pro"}
    res = await successful(
        db.call(
            RowsInsert(
                input=RowsInsertInput(table=users, rows=[{"email": "ann@x.io", "score": 1}], on_conflict=DoNothing(target=["email"]))
            )
        )
    )
    assert res.rowcount == 0 and (await successful(db.call(RowsGet(input=RowsGetInput(table=users, key=1))))).row["score"] == 50
    with fails(code=ErrorCode.CONFLICT, sqlstate="23505"):
        await successful(db.call(RowsInsert(input=RowsInsertInput(table=users, rows=[{"email": "ann@x.io"}]))))


async def test_update_delete_and_guards(db: MyApp, users: str) -> None:
    res = await successful(
        db.call(RowsUpdate(input=RowsUpdateInput(table=users, values={"score": 0, "meta": {"plan": "none"}}, match={"email": "bob@x.io"})))
    )
    assert res.rowcount == 1 and res.rows[0]["meta"] == {"plan": "none"}
    res = await successful(db.call(RowsDelete(input=RowsDeleteInput(table=users, where=[IsNull(column="score")], returning=["email"]))))
    assert res.rows == [{"email": "cat@x.io"}] and (await successful(db.call(RowsCount(input=RowsCountInput(table=users))))).count == 2
    with fails(match="refusing UPDATE", code=ErrorCode.INVALID_REQUEST):
        await successful(db.call(RowsUpdate(input=RowsUpdateInput(table=users, values={"score": 0}))))
    with fails(match="refusing DELETE", code=ErrorCode.INVALID_REQUEST):
        await successful(db.call(RowsDelete(input=RowsDeleteInput(table=users))))
    assert (await successful(db.call(RowsDelete(input=RowsDeleteInput(table=users, allow_all=True))))).rowcount == 2


async def test_transactions(db: MyApp, users: str) -> None:
    with fails(code=ErrorCode.CONFLICT, sqlstate="23505"):
        async with db.transaction() as tx:
            await successful(tx.call(RowsUpdate(input=RowsUpdateInput(table=users, values={"score": 99}, match={"id": 1}))))
            await successful(tx.call(RowsInsert(input=RowsInsertInput(table=users, rows=[{"email": "bob@x.io"}]))))
    assert (await successful(db.call(RowsGet(input=RowsGetInput(table=users, key=1))))).row["score"] == 5
    async with db.transaction() as tx:
        assert tx.in_transaction
        await successful(tx.call(RowsUpdate(input=RowsUpdateInput(table=users, values={"score": 99}, match={"id": 1}))))
        await successful(tx.call(RowsDelete(input=RowsDeleteInput(table=users, match={"id": 2}))))
    assert (await successful(db.call(RowsGet(input=RowsGetInput(table=users, key=1))))).row["score"] == 99 and (
        await successful(db.call(RowsGet(input=RowsGetInput(table=users, key=2))))
    ).row is None


async def test_batch_is_atomic_and_checks_permissions_first(db: MyApp, users: str) -> None:
    ok = await successful(
        db.call(
            Batch(
                input=BatchInput(
                    requests=[
                        RowsUpdate(input=RowsUpdateInput(table=users, values={"score": 7}, match={"id": 1})),
                        SqlExecute(input=SqlExecuteInput(sql=f'DELETE FROM "{users}" WHERE id = %s', params=[2])),
                    ]
                )
            )
        )
    )
    assert [r.outcome.data.rowcount for r in ok.results] == [1, 1]
    with fails(code=ErrorCode.NOT_FOUND, sqlstate="42703"):
        await successful(
            db.call(
                Batch(
                    input=BatchInput(
                        requests=[
                            RowsUpdate(input=RowsUpdateInput(table=users, values={"score": 1}, match={"id": 1})),
                            SqlExecute(input=SqlExecuteInput(sql="SELECT nope")),
                        ]
                    )
                )
            )
        )
    assert (await successful(db.call(RowsGet(input=RowsGetInput(table=users, key=1))))).row["score"] == 7
    with fails(match="nested", code=ErrorCode.INVALID_REQUEST):
        await successful(
            db.call(Batch(input=BatchInput(requests=[Batch(input=BatchInput(requests=[RowsCount(input=RowsCountInput(table=users))]))])))
        )
    reader = db.as_(Principal(name="r", read_only=True))
    with fails(code=ErrorCode.FORBIDDEN):
        await successful(
            reader.call(
                Batch(
                    input=BatchInput(
                        requests=[
                            RowsCount(input=RowsCountInput(table=users)),
                            RowsDelete(input=RowsDeleteInput(table=users, allow_all=True)),
                        ]
                    )
                )
            )
        )
    assert (await successful(db.call(RowsCount(input=RowsCountInput(table=users))))).count == 2


async def test_csv_roundtrip(db: MyApp, users: str) -> None:
    csv = (
        await successful(
            db.call(RowsExportCsv(input=RowsExportCsvInput(table=users, columns=["email", "score"], order_by=[OrderBy(column="id")])))
        )
    ).text
    assert csv.splitlines()[0] == "email,score"
    await successful(db.call(TableTruncate(input=TableTruncateInput(table=users))))
    assert (
        await successful(db.call(RowsImportCsv(input=RowsImportCsvInput(table=users, data=csv, columns=["email", "score"]))))
    ).rowcount == 3
    assert (await successful(db.call(RowsSelect(input=RowsSelectInput(table=users, match={"email": "ann@x.io"}))))).rows[0]["score"] == 5


async def test_query_is_read_only_single_statement_and_capped(db: MyApp, users: str) -> None:
    res = await successful(
        db.call(SqlQuery(input=SqlQueryInput(sql=f'SELECT email FROM "{users}" WHERE score > %s ORDER BY 1', params=[0])))
    )
    assert res.columns == ["email"] and [r["email"] for r in res.rows] == ["ann@x.io", "bob@x.io"]
    with fails(code=ErrorCode.FORBIDDEN, sqlstate="25006"):
        await successful(db.call(SqlQuery(input=SqlQueryInput(sql=f'DELETE FROM "{users}"'))))
    with fails():
        await successful(db.call(SqlQuery(input=SqlQueryInput(sql="SELECT 1; SELECT 2"))))
    empty = await successful(db.call(SqlQuery(input=SqlQueryInput(sql=f'SELECT email, score FROM "{users}" WHERE false'))))
    assert empty.columns == ["email", "score"] and empty.rows == []
    async with MyApp(make_settings(max_rows=2)) as small:
        res = await successful(small.call(SqlQuery(input=SqlQueryInput(sql=f'SELECT email FROM "{users}" ORDER BY id'))))
        assert res.rowcount == 2 and res.truncated
        assert (await successful(small.call(SqlQuery(input=SqlQueryInput(sql="SELECT 1 AS one"))))).rows == [{"one": 1}]


async def test_execute_explain_and_guards(db: MyApp, users: str) -> None:
    res = await successful(
        db.call(SqlExecute(input=SqlExecuteInput(sql=f'UPDATE "{users}" SET score = %(s)s WHERE id = %(id)s', params={"s": 42, "id": 1})))
    )
    assert res.rowcount == 1 and res.status == "UPDATE 1"
    with fails(match="transaction control", code=ErrorCode.INVALID_REQUEST):
        await successful(db.call(SqlExecute(input=SqlExecuteInput(sql="BEGIN"))))
    plan = (await successful(db.call(SqlExplain(input=SqlExplainInput(sql=f'SELECT * FROM "{users}"', analyze=True))))).plan
    assert isinstance(plan, list) and "Plan" in plan[0]


async def test_server_caps(users: str) -> None:
    async with MyApp(make_settings(read_only=True)) as ro:
        assert (await successful(ro.call(RowsCount(input=RowsCountInput(table=users))))).count == 3
        with fails(match="read-only", code=ErrorCode.FORBIDDEN):
            await successful(ro.call(RowsInsert(input=RowsInsertInput(table=users, rows=[{"email": "x@x.io"}]))))
    async with MyApp(make_settings(allow_raw_sql=False, allow_ddl=False, allow_admin=False)) as locked:
        with fails(match="raw SQL", code=ErrorCode.FORBIDDEN):
            await successful(locked.call(SqlQuery(input=SqlQueryInput(sql="SELECT 1"))))
        with fails(match="DDL", code=ErrorCode.FORBIDDEN):
            await successful(locked.call(TableTruncate(input=TableTruncateInput(table=users))))
        assert not locked.allows(REGISTRY["maint.vacuum"].perm)
        assert {s.op for s in locked.allowed_ops()} < set(REGISTRY)


async def test_principal_flags(db: MyApp, users: str) -> None:
    reader = db.as_(Principal(name="reader", read_only=True, sql=False, ddl=False))
    assert (await successful(reader.call(RowsCount(input=RowsCountInput(table=users))))).count == 3
    with fails(match="'reader' is read-only", code=ErrorCode.FORBIDDEN):
        await successful(reader.call(RowsUpdate(input=RowsUpdateInput(table=users, values={"score": 0}, match={"id": 1}))))
    with fails(match="may not run raw SQL", code=ErrorCode.FORBIDDEN):
        await successful(reader.call(SqlQuery(input=SqlQueryInput(sql="SELECT 1"))))
    with fails(match="may not run DDL", code=ErrorCode.FORBIDDEN):
        await successful(db.as_(Principal(name="writer", ddl=False)).call(TableTruncate(input=TableTruncateInput(table=users))))
    who = await successful(reader.call(ServerWhoAmI(input=ServerWhoAmIInput())))
    assert who.read_only and (not who.sql) and (not who.listen) and (who.principal == "reader")
    with pytest.raises(InvalidRequest, match="inside a transaction"):
        async with db.transaction() as tx:
            tx.as_(Principal(name="x"))


async def test_role_binding_enforced_by_postgres(db: MyApp, users: str) -> None:
    """A principal with a Postgres role runs under SET LOCAL ROLE, so GRANTs decide what it can do."""
    role = f"{users}_reader"
    await successful(db.call(SqlExecute(input=SqlExecuteInput(sql=f'CREATE ROLE "{role}" NOLOGIN'))))
    await successful(db.call(SqlExecute(input=SqlExecuteInput(sql=f'GRANT SELECT ON "{users}" TO "{role}"'))))
    await successful(db.call(SqlExecute(input=SqlExecuteInput(sql=f'GRANT "{role}" TO current_user'))))
    try:
        bound = db.as_(Principal(name="svc", role=role, sql=True))
        assert (await successful(bound.call(RowsCount(input=RowsCountInput(table=users))))).count == 3
        assert (await successful(bound.call(ServerInfoGet(input=ServerInfoGetInput())))).session_role == role
        with fails(code=ErrorCode.FORBIDDEN, sqlstate="42501"):
            await successful(bound.call(RowsInsert(input=RowsInsertInput(table=users, rows=[{"email": "x@x.io"}]))))
        with fails(match="session role", code=ErrorCode.INVALID_REQUEST):
            await successful(bound.call(SqlQuery(input=SqlQueryInput(sql="SET ROLE postgres"))))
        assert (await successful(db.call(ServerInfoGet(input=ServerInfoGetInput())))).session_role != role
    finally:
        await successful(db.call(SqlExecute(input=SqlExecuteInput(sql=f'DROP OWNED BY "{role}"'))))
        await successful(db.call(SqlExecute(input=SqlExecuteInput(sql=f'DROP ROLE "{role}"'))))


async def test_read_only_holds_inside_transactions(db: MyApp, users: str) -> None:
    async with db.transaction() as tx:
        await successful(tx.call(RowsUpdate(input=RowsUpdateInput(table=users, values={"score": 1}, match={"id": 1}))))
        with fails(code=ErrorCode.FORBIDDEN, sqlstate="25006"):
            await successful(tx.call(SqlQuery(input=SqlQueryInput(sql=f'DELETE FROM "{users}"'))))
        assert (await successful(tx.call(SqlQuery(input=SqlQueryInput(sql=f'SELECT count(*) AS n FROM "{users}"'))))).rows == [{"n": 3}]
        await successful(tx.call(RowsUpdate(input=RowsUpdateInput(table=users, values={"score": 2}, match={"id": 1}))))
    assert (await successful(db.call(RowsGet(input=RowsGetInput(table=users, key=1))))).row["score"] == 2 and (
        await successful(db.call(RowsCount(input=RowsCountInput(table=users))))
    ).count == 3


async def test_explain_analyze_cannot_execute_writes(db: MyApp, users: str) -> None:
    reader = db.as_(Principal(name="explain-reader", read_only=True, sql=True))
    with fails(code=ErrorCode.FORBIDDEN, sqlstate="25006"):
        await successful(reader.call(SqlExplain(input=SqlExplainInput(sql=f'DELETE FROM "{users}"', analyze=True))))
    assert (await successful(db.call(RowsCount(input=RowsCountInput(table=users))))).count == 3
