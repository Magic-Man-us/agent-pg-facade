"""schema.* table.* column.* constraint.* index.* view.* extension.* role.* privilege.* server.* diag.* maint.* migration.*"""

from pathlib import Path

import pytest
from pydantic import ValidationError

from pgfacade import PgFacade
from pgfacade.contracts.admin import (
    DiagActivity,
    DiagActivityInput,
    DiagLocks,
    DiagLocksInput,
    DiagTableStats,
    DiagTableStatsInput,
    DiagTopQueries,
    DiagTopQueriesInput,
    DiagUnusedIndexes,
    DiagUnusedIndexesInput,
    MaintAnalyze,
    MaintAnalyzeInput,
    MaintBackend,
    MaintBackendInput,
    MaintReindex,
    MaintReindexInput,
    MaintVacuum,
    MaintVacuumInput,
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
    ServerHealth,
    ServerHealthInput,
    ServerInfoGet,
    ServerInfoGetInput,
    ServerSettings,
    ServerSettingsInput,
)
from pgfacade.contracts.enums import ErrorCode
from pgfacade.contracts.roles import (
    MembershipGrant,
    MembershipGrantInput,
    MembershipRevoke,
    MembershipRevokeInput,
    PrivilegeGrant,
    PrivilegeGrantInput,
    PrivilegeList,
    PrivilegeListInput,
    PrivilegeRevoke,
    PrivilegeRevokeInput,
    RoleAlter,
    RoleAlterInput,
    RoleCreate,
    RoleCreateInput,
    RoleDrop,
    RoleDropInput,
    RoleGet,
    RoleGetInput,
    RoleList,
    RoleListInput,
    RoleSetPassword,
    RoleSetPasswordInput,
)
from pgfacade.contracts.rows import (
    RowsCount,
    RowsCountInput,
    RowsInsert,
    RowsInsertInput,
    RowsSelect,
    RowsSelectInput,
    SqlExecute,
    SqlExecuteInput,
)
from pgfacade.contracts.schema import (
    CheckConstraintInput,
    ColumnAdd,
    ColumnAddInput,
    ColumnAlter,
    ColumnAlterInput,
    ColumnDrop,
    ColumnDropInput,
    ColumnRename,
    ColumnRenameInput,
    ColumnSpec,
    ConstraintAdd,
    ConstraintDrop,
    ConstraintDropInput,
    DatabaseList,
    DatabaseListInput,
    ExtensionCreate,
    ExtensionCreateInput,
    ExtensionDrop,
    ExtensionDropInput,
    ExtensionList,
    ExtensionListInput,
    ForeignKeyConstraintInput,
    ForeignRef,
    IndexCreate,
    IndexCreateInput,
    IndexDrop,
    IndexDropInput,
    SchemaCreate,
    SchemaCreateInput,
    SchemaDrop,
    SchemaDropInput,
    SchemaList,
    SchemaListInput,
    TableComment,
    TableCommentInput,
    TableCreate,
    TableCreateInput,
    TableDescribe,
    TableDescribeInput,
    TableDrop,
    TableDropInput,
    TableList,
    TableListInput,
    TableRename,
    TableRenameInput,
    ViewCreate,
    ViewCreateInput,
    ViewDrop,
    ViewDropInput,
    ViewRefresh,
    ViewRefreshInput,
)
from tests.conftest import make_settings, unique
from tests.support import fails, successful

pytestmark = pytest.mark.integration


async def test_introspection(db: PgFacade, users: str) -> None:
    assert "public" in {s.name for s in (await successful(db.call(SchemaList(input=SchemaListInput())))).items}
    assert users in {t.name for t in (await successful(db.call(TableList(input=TableListInput(schema_name="public"))))).items}
    detail = await successful(db.call(TableDescribe(input=TableDescribeInput(table=users))))
    assert detail.primary_key == ["id"] and detail.info.owner and (detail.view_definition is None)
    assert {c.name: c.type for c in detail.columns}["meta"] == "jsonb"
    assert any(c.type == "unique" for c in detail.constraints)


async def test_schema_lifecycle(db: PgFacade) -> None:
    name = unique("shop")
    await successful(db.call(SchemaCreate(input=SchemaCreateInput(name=name))))
    try:
        assert name in {s.name for s in (await successful(db.call(SchemaList(input=SchemaListInput())))).items}
        await successful(
            db.call(
                TableCreate(input=TableCreateInput(table=f"{name}.items", columns=[ColumnSpec(name="id", type="int", primary_key=True)]))
            )
        )
        assert (await successful(db.call(TableDescribe(input=TableDescribeInput(table=f"{name}.items"))))).info.schema_name == name
    finally:
        await successful(db.call(SchemaDrop(input=SchemaDropInput(name=name, cascade=True))))
    assert name not in {s.name for s in (await successful(db.call(SchemaList(input=SchemaListInput())))).items}


async def test_columns(db: PgFacade, users: str) -> None:
    await successful(
        db.call(
            ColumnAdd(
                input=ColumnAddInput(table=users, column=ColumnSpec(name="price", type="numeric(10,2)", default=0, comment="unit price"))
            )
        )
    )
    await successful(db.call(ColumnAlter(input=ColumnAlterInput(table=users, column="price", nullable=False, default=1))))
    await successful(db.call(ColumnRename(input=ColumnRenameInput(table=users, column="price", new_name="cost"))))
    cols = {c.name: c for c in (await successful(db.call(TableDescribe(input=TableDescribeInput(table=users))))).columns}
    assert cols["cost"].type == "numeric(10,2)" and (not cols["cost"].nullable) and (cols["cost"].comment == "unit price")
    assert cols["cost"].default == "1"
    await successful(db.call(ColumnAlter(input=ColumnAlterInput(table=users, column="cost", type="text", using="cost::text"))))
    assert {c.name: c.type for c in (await successful(db.call(TableDescribe(input=TableDescribeInput(table=users))))).columns}[
        "cost"
    ] == "text"
    await successful(db.call(ColumnDrop(input=ColumnDropInput(table=users, column="cost"))))
    assert "cost" not in {c.name for c in (await successful(db.call(TableDescribe(input=TableDescribeInput(table=users))))).columns}
    with pytest.raises(ValidationError, match="nothing to alter"):
        ColumnAlter(input=ColumnAlterInput(table=users, column="score"))


async def test_constraints_and_indexes(db: PgFacade, users: str) -> None:
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
        fk = ConstraintAdd(
            input=ForeignKeyConstraintInput(
                table=child, kind="foreign_key", columns=["user_id"], references=ForeignRef(table=users, column="id", on_delete="cascade")
            )
        )
        name = (await successful(db.call(fk))).detail["constraint"]
        await successful(
            db.call(ConstraintAdd(input=CheckConstraintInput(table=child, kind="check", expression="id > 0", name="positive_id")))
        )
        names = {c.name for c in (await successful(db.call(TableDescribe(input=TableDescribeInput(table=child))))).constraints}
        assert name in names and "positive_id" in names
        await successful(db.call(ConstraintDrop(input=ConstraintDropInput(table=child, name="positive_id"))))
        res = await successful(db.call(IndexCreate(input=IndexCreateInput(table=users, columns=["meta"], method="gin"))))
        assert res.detail["index"] == f"public.{users}_meta_idx"
        await successful(db.call(IndexDrop(input=IndexDropInput(index=res.detail["index"]))))
        assert not any(
            i.name.endswith("_meta_idx") for i in (await successful(db.call(TableDescribe(input=TableDescribeInput(table=users))))).indexes
        )
    finally:
        await successful(db.call(TableDrop(input=TableDropInput(table=child))))


async def test_views_comments_rename(db: PgFacade, users: str) -> None:
    view = unique("v")
    await successful(db.call(ViewCreate(input=ViewCreateInput(name=view, query=f'SELECT email FROM "{users}" WHERE score IS NOT NULL'))))
    try:
        detail = await successful(db.call(TableDescribe(input=TableDescribeInput(table=view))))
        assert detail.info.kind == "view" and "score IS NOT NULL" in (detail.view_definition or "")
        assert (await successful(db.call(RowsSelect(input=RowsSelectInput(table=view))))).rowcount == 2
    finally:
        await successful(db.call(ViewDrop(input=ViewDropInput(name=view))))
    mat = unique("mv")
    await successful(db.call(ViewCreate(input=ViewCreateInput(name=mat, query=f'SELECT count(*) AS n FROM "{users}"', materialized=True))))
    try:
        await successful(db.call(RowsInsert(input=RowsInsertInput(table=users, rows=[{"email": "z@x.io"}]))))
        assert (await successful(db.call(RowsSelect(input=RowsSelectInput(table=mat))))).rows == [{"n": 3}]
        await successful(db.call(ViewRefresh(input=ViewRefreshInput(name=mat))))
        assert (await successful(db.call(RowsSelect(input=RowsSelectInput(table=mat))))).rows == [{"n": 4}]
    finally:
        await successful(db.call(ViewDrop(input=ViewDropInput(name=mat, materialized=True))))
    await successful(db.call(TableComment(input=TableCommentInput(table=users, comment="people"))))
    await successful(db.call(TableComment(input=TableCommentInput(table=users, comment="mail", column="email"))))
    detail = await successful(db.call(TableDescribe(input=TableDescribeInput(table=users))))
    assert detail.info.comment == "people" and {c.name: c.comment for c in detail.columns}["email"] == "mail"
    renamed = f"{users}_r"
    await successful(db.call(TableRename(input=TableRenameInput(table=users, new_name=renamed))))
    assert (await successful(db.call(RowsCount(input=RowsCountInput(table=renamed))))).count == 4
    await successful(db.call(TableRename(input=TableRenameInput(table=renamed, new_name=users))))


async def test_extensions_and_databases(db: PgFacade) -> None:
    installed = (await successful(db.call(ExtensionList(input=ExtensionListInput())))).items
    assert all(e.installed for e in installed) and "plpgsql" in {e.name for e in installed}
    everything = (await successful(db.call(ExtensionList(input=ExtensionListInput(available=True))))).items
    assert len(everything) >= len(installed) and any(not e.installed for e in everything)
    await successful(db.call(ExtensionCreate(input=ExtensionCreateInput(name="pgcrypto"))))
    assert "pgcrypto" in {e.name for e in (await successful(db.call(ExtensionList(input=ExtensionListInput())))).items}
    await successful(db.call(ExtensionDrop(input=ExtensionDropInput(name="pgcrypto"))))
    assert any(d.name == "postgres" for d in (await successful(db.call(DatabaseList(input=DatabaseListInput())))).items)


async def test_role_management(db: PgFacade, users: str) -> None:
    group, user = (unique("grp"), unique("usr"))
    await successful(db.call(RoleCreate(input=RoleCreateInput(name=group, login=False, comment="readers"))))
    info = await successful(db.call(RoleCreate(input=RoleCreateInput(name=user, password="s3cret", in_roles=[group], connection_limit=5))))
    try:
        assert info.login and info.member_of == [group] and (info.connection_limit == 5)
        grp = await successful(db.call(RoleGet(input=RoleGetInput(name=group))))
        assert grp.members == [user] and grp.comment == "readers"
        info = await successful(
            db.call(RoleAlter(input=RoleAlterInput(name=user, login=False, connection_limit=-1, valid_until="2030-01-01T00:00:00Z")))
        )
        assert not info.login and info.connection_limit == -1 and (info.valid_until is not None)
        info = await successful(db.call(RoleAlter(input=RoleAlterInput(name=user, clear_valid_until=True))))
        assert info.valid_until is None and user in {r.name for r in (await successful(db.call(RoleList(input=RoleListInput())))).items}
        await successful(db.call(RoleSetPassword(input=RoleSetPasswordInput(name=user, password="new"))))
        await successful(db.call(MembershipRevoke(input=MembershipRevokeInput(role=group, members=[user]))))
        assert (await successful(db.call(RoleGet(input=RoleGetInput(name=user))))).member_of == []
        await successful(db.call(MembershipGrant(input=MembershipGrantInput(role=group, members=[user]))))
        await successful(
            db.call(PrivilegeGrant(input=PrivilegeGrantInput(privileges=["select", "insert"], on="table", target=users, roles=[group])))
        )
        privs = {
            (p.grantee, p.privilege)
            for p in (await successful(db.call(PrivilegeList(input=PrivilegeListInput(kind="table", target=users))))).items
        }
        assert {(group, "SELECT"), (group, "INSERT")} <= privs
        await successful(
            db.call(PrivilegeRevoke(input=PrivilegeRevokeInput(privileges=["insert"], on="table", target=users, roles=[group])))
        )
        privs = {
            (p.grantee, p.privilege)
            for p in (await successful(db.call(PrivilegeList(input=PrivilegeListInput(kind="table", target=users))))).items
        }
        assert (group, "SELECT") in privs and (group, "INSERT") not in privs
        assert {
            p.grantee for p in (await successful(db.call(PrivilegeList(input=PrivilegeListInput(kind="schema", target="public"))))).items
        } >= {"public", "pg_database_owner"}
        fn = unique("fn")
        await successful(
            db.call(
                SqlExecute(input=SqlExecuteInput(sql=f'CREATE FUNCTION "{fn}"(x int, t text[]) RETURNS int LANGUAGE sql AS $$ SELECT x $$'))
            )
        )
        try:
            assert (
                await successful(
                    db.call(
                        PrivilegeGrant(
                            input=PrivilegeGrantInput(privileges=["execute"], on="function", target=f"{fn}(int, text[])", roles=[group])
                        )
                    )
                )
            ).status == "GRANT"
            with pytest.raises(ValidationError, match="function target"):
                PrivilegeGrant(
                    input=PrivilegeGrantInput(
                        privileges=["execute"], on="function", target=f"{fn}() TO PUBLIC; DROP TABLE x; --", roles=[group]
                    )
                )
        finally:
            await successful(db.call(SqlExecute(input=SqlExecuteInput(sql=f'DROP FUNCTION "{fn}"(int, text[])'))))
    finally:
        await successful(db.call(RoleDrop(input=RoleDropInput(name=user))))
        await successful(db.call(RoleDrop(input=RoleDropInput(name=group, reassign_to="postgres"))))
    with fails(code=ErrorCode.NOT_FOUND):
        await successful(db.call(RoleGet(input=RoleGetInput(name=user))))
    assert (await successful(db.call(RoleDrop(input=RoleDropInput(name=user))))).detail == {"existed": False}


def test_role_alter_rejects_noop_but_accepts_false() -> None:
    with pytest.raises(ValidationError, match="nothing to alter"):
        RoleAlter(input=RoleAlterInput(name="x"))
    assert RoleAlter(input=RoleAlterInput(name="x", login=False)).input.login is False
    assert RoleAlter(input=RoleAlterInput(name="x", clear_valid_until=True)).input.clear_valid_until


async def test_server_and_diagnostics(db: PgFacade, users: str) -> None:
    health = await successful(db.call(ServerHealth(input=ServerHealthInput())))
    assert health.ok and health.pool["pool_max"] == db.settings.pool_max
    assert (await successful(db.call(ServerInfoGet(input=ServerInfoGetInput())))).max_connections > 0
    assert any(
        s.name == "work_mem" for s in (await successful(db.call(ServerSettings(input=ServerSettingsInput(pattern="work_mem"))))).items
    )
    assert isinstance((await successful(db.call(DiagActivity(input=DiagActivityInput())))).rows, list)
    assert (await successful(db.call(DiagLocks(input=DiagLocksInput())))).rows == []
    assert users in {r["name"] for r in (await successful(db.call(DiagTableStats(input=DiagTableStatsInput(schema_name="public"))))).rows}
    assert isinstance((await successful(db.call(DiagUnusedIndexes(input=DiagUnusedIndexesInput())))).rows, list)
    with fails(code=ErrorCode.NOT_FOUND):
        await successful(db.call(DiagTopQueries(input=DiagTopQueriesInput())))


async def test_maintenance(db: PgFacade, users: str) -> None:
    assert (await successful(db.call(MaintAnalyze(input=MaintAnalyzeInput(table=users))))).status == "ANALYZE"
    assert (await successful(db.call(MaintVacuum(input=MaintVacuumInput(table=users))))).status == "VACUUM"
    assert (await successful(db.call(MaintReindex(input=MaintReindexInput(kind="table", name=users))))).status == "REINDEX"
    assert (await successful(db.call(MaintBackend(input=MaintBackendInput(action="cancel", pid=0))))).ok is False


async def test_migrations_roundtrip(tmp_path: Path, clean_alembic: None) -> None:
    table = unique("migrated")
    async with PgFacade(make_settings(migrations_dir=tmp_path / "migrations")) as db:
        status = await successful(db.call(MigrationInit(input=MigrationInitInput())))
        assert status.initialized and status.current == [] and (status.pending == [])
        rev = await successful(
            db.call(
                MigrationRevision(
                    input=MigrationRevisionInput(
                        message="add table", upgrade_sql=f'CREATE TABLE "{table}" (id int)', downgrade_sql=f'DROP TABLE "{table}"'
                    )
                )
            )
        )
        assert rev.is_head and (not rev.applied)
        status = await successful(db.call(MigrationStatusGet(input=MigrationStatusGetInput())))
        assert status.pending == [rev.revision] and (not status.up_to_date)
        run = await successful(db.call(MigrationRun(input=MigrationRunInput(action="upgrade"))))
        assert run.before == [] and run.after == [rev.revision]
        assert (await successful(db.call(RowsCount(input=RowsCountInput(table=table))))).count == 0
        assert (await successful(db.call(MigrationHistory(input=MigrationHistoryInput())))).items[0].applied and (
            await successful(db.call(MigrationStatusGet(input=MigrationStatusGetInput())))
        ).up_to_date
        await successful(db.call(MigrationRun(input=MigrationRunInput(action="downgrade"))))
        with fails(code=ErrorCode.NOT_FOUND):
            await successful(db.call(RowsCount(input=RowsCountInput(table=table))))
        assert (await successful(db.call(MigrationRun(input=MigrationRunInput(action="stamp", target="head"))))).after == [rev.revision]
        await successful(db.call(MigrationRun(input=MigrationRunInput(action="stamp", target="base"))))
    with pytest.raises(ValidationError, match='cannot contain """'):
        MigrationRevision(input=MigrationRevisionInput(message='x"""\nimport os'))
