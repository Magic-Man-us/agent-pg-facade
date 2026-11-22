"""schema.* table.* column.* constraint.* index.* view.* extension.* database.* handlers."""

from __future__ import annotations

from pgfacade.application.errors import NotFound
from pgfacade.application.registry import DDL, RAW, WRITE, op
from pgfacade.contracts.base import Done
from pgfacade.contracts.enums import ConstraintKind, OperationHint
from pgfacade.contracts.schema import (
    ColumnAdd,
    ColumnAlter,
    ColumnDrop,
    ColumnInfo,
    ColumnRename,
    ConstraintAdd,
    ConstraintDrop,
    ConstraintInfo,
    DatabaseInfo,
    DatabaseInfoList,
    DatabaseList,
    ExtensionCreate,
    ExtensionDrop,
    ExtensionInfo,
    ExtensionInfoList,
    ExtensionList,
    IndexCreate,
    IndexDrop,
    IndexInfo,
    SchemaCreate,
    SchemaDrop,
    SchemaInfo,
    SchemaInfoList,
    SchemaList,
    TableComment,
    TableCreate,
    TableDescribe,
    TableDetail,
    TableDrop,
    TableInfo,
    TableInfoList,
    TableList,
    TableRename,
    TableTruncate,
    ViewCreate,
    ViewDrop,
    ViewRefresh,
)
from pgfacade.infrastructure.postgres.engine import Core
from pgfacade.infrastructure.postgres.queries import Statement
from pgfacade.infrastructure.postgres.queries import schema as statements
from pgfacade.infrastructure.postgres.queries.composition import Binder
from pgfacade.infrastructure.postgres.types import RelationKind

_VIEW_KINDS = {RelationKind.VIEW, RelationKind.MATERIALIZED_VIEW}


# ---------------------------------------------------------------- schemas


@op(SchemaList, response=SchemaInfoList)
async def schema_list(db: Core, req: SchemaList) -> SchemaInfoList:
    result = await db.read(Statement.SCHEMA_SCHEMAS.text)
    return SchemaInfoList(items=[SchemaInfo.model_validate(r) for r in result.rows])


@op(SchemaCreate, response=Done, perm=DDL)
async def schema_create(db: Core, req: SchemaCreate) -> Done:
    query = statements.create_schema(db, req)
    return await db.ddl(query)


@op(SchemaDrop, response=Done, perm=DDL, hint=OperationHint.DESTRUCTIVE)
async def schema_drop(db: Core, req: SchemaDrop) -> Done:
    query = statements.drop_schema(db, req)
    return await db.ddl(query)


# ---------------------------------------------------------------- tables


@op(TableList, response=TableInfoList)
async def table_list(db: Core, req: TableList) -> TableInfoList:
    query = statements.list_tables(req)
    async with db.tx() as conn:
        cur = await conn.execute(query, [req.input.schema_name] if req.input.schema_name else [])
        return TableInfoList(items=[TableInfo.model_validate(r) for r in await cur.fetchall()])


@op(TableDescribe, response=TableDetail)
async def table_describe(db: Core, req: TableDescribe) -> TableDetail:
    async with db.tx() as conn:
        meta = await db.table(conn, req.input.table)
        reg = [meta.ident.as_string(conn)]
        info_q = statements.describe_table()
        info = await (await conn.execute(info_q, reg)).fetchone()
        columns = await (await conn.execute(Statement.SCHEMA_COLUMNS.text, reg)).fetchall()
        constraints = await (await conn.execute(Statement.SCHEMA_CONSTRAINTS.text, reg)).fetchall()
        indexes = await (await conn.execute(Statement.SCHEMA_INDEXES.text, reg)).fetchall()
        view_def = None
        if meta.kind in _VIEW_KINDS:
            row = await (await conn.execute(Statement.SCHEMA_VIEW_DEFINITION.text, reg)).fetchone()
            view_def = row["d"] if row else None
    if info is None:
        raise NotFound(f"relation {meta.label} does not exist")
    return TableDetail(
        info=TableInfo.model_validate(info),
        columns=[ColumnInfo.model_validate(r) for r in columns],
        primary_key=list(meta.primary_key),
        constraints=[ConstraintInfo.model_validate(r) for r in constraints],
        indexes=[IndexInfo.model_validate(r) for r in indexes],
        view_definition=view_def,
    )


@op(TableCreate, response=Done, perm=DDL)
async def table_create(db: Core, req: TableCreate) -> Done:
    ident = db.qualified(req.input.table)
    async with db.tx() as conn:
        cur = await conn.execute(statements.create_table(db, req))
        status = cur.statusmessage
        if req.input.comment is not None:
            await conn.execute(statements.comment(ident, req.input.comment))
        for c in req.input.columns:
            if c.comment is not None:
                await conn.execute(statements.comment(ident, c.comment, c.name))
    db.invalidate()
    return Done(status=status)


@op(TableDrop, response=Done, perm=DDL, hint=OperationHint.DESTRUCTIVE)
async def table_drop(db: Core, req: TableDrop) -> Done:
    query = statements.drop_table(db, req)
    return await db.ddl(query)


@op(TableRename, response=Done, perm=DDL, hint=OperationHint.DESTRUCTIVE)
async def table_rename(db: Core, req: TableRename) -> Done:
    query = statements.rename_table(db, req)
    return await db.ddl(query)


@op(TableTruncate, response=Done, perm=DDL, hint=OperationHint.DESTRUCTIVE)
async def table_truncate(db: Core, req: TableTruncate) -> Done:
    query = statements.truncate_table(db, req)
    return await db.ddl(query)


@op(TableComment, response=Done, perm=DDL, hint=OperationHint.DESTRUCTIVE)
async def table_comment(db: Core, req: TableComment) -> Done:
    async with db.tx() as conn:
        meta = await db.table(conn, req.input.table)
        if req.input.column:
            Binder(meta).col(req.input.column)
        cur = await conn.execute(statements.comment(meta.ident, req.input.comment, req.input.column))
        return Done(status=cur.statusmessage)


# ---------------------------------------------------------------- columns


@op(ColumnAdd, response=Done, perm=DDL)
async def column_add(db: Core, req: ColumnAdd) -> Done:
    ident = db.qualified(req.input.table)
    async with db.tx() as conn:
        cur = await conn.execute(statements.add_column(db, req))
        status = cur.statusmessage
        if req.input.column.comment is not None:
            await conn.execute(statements.comment(ident, req.input.column.comment, req.input.column.name))
    db.invalidate()
    return Done(status=status)


@op(ColumnAlter, response=Done, perm=DDL, hint=OperationHint.DESTRUCTIVE)
async def column_alter(db: Core, req: ColumnAlter) -> Done:
    if req.input.using is not None:
        db.require(RAW)
    async with db.tx() as conn:
        meta = await db.table(conn, req.input.table)
        query = statements.alter_column(meta, req)
        status = None
        if query is not None:
            cur = await conn.execute(query)
            status = cur.statusmessage
        if req.input.comment is not None:
            cur = await conn.execute(statements.comment(meta.ident, req.input.comment, req.input.column))
            status = status or cur.statusmessage
    db.invalidate()
    return Done(status=status)


@op(ColumnRename, response=Done, perm=DDL, hint=OperationHint.DESTRUCTIVE)
async def column_rename(db: Core, req: ColumnRename) -> Done:
    async with db.tx() as conn:
        meta = await db.table(conn, req.input.table)
        cur = await conn.execute(statements.rename_column(meta, req))
    db.invalidate()
    return Done(status=cur.statusmessage)


@op(ColumnDrop, response=Done, perm=DDL, hint=OperationHint.DESTRUCTIVE)
async def column_drop(db: Core, req: ColumnDrop) -> Done:
    query = statements.drop_column(db, req)
    return await db.ddl(query)


# ---------------------------------------------------------------- constraints, indexes


@op(ConstraintAdd, response=Done, perm=DDL)
async def constraint_add(db: Core, req: ConstraintAdd) -> Done:
    if req.input.kind == ConstraintKind.CHECK:
        db.require(RAW)
    async with db.tx() as conn:
        meta = await db.table(conn, req.input.table)
        compiled = statements.add_constraint(db, meta, req)
        cur = await conn.execute(compiled.statement)
    db.invalidate()
    return Done(status=cur.statusmessage, detail={"constraint": compiled.name})


@op(ConstraintDrop, response=Done, perm=DDL, hint=OperationHint.DESTRUCTIVE)
async def constraint_drop(db: Core, req: ConstraintDrop) -> Done:
    query = statements.drop_constraint(db, req)
    return await db.ddl(query)


@op(IndexCreate, response=Done, perm=DDL)
async def index_create(db: Core, req: IndexCreate) -> Done:
    async with db.tx() as conn:
        meta = await db.table(conn, req.input.table)
    compiled = statements.create_index(meta, req)
    return await db.ddl(compiled.statement, no_tx=req.input.concurrently, index=f"{meta.schema_name}.{compiled.name}")


@op(IndexDrop, response=Done, perm=DDL, hint=OperationHint.DESTRUCTIVE)
async def index_drop(db: Core, req: IndexDrop) -> Done:
    query = statements.drop_index(db, req)
    return await db.ddl(query, no_tx=req.input.concurrently)


# ---------------------------------------------------------------- views


@op(ViewCreate, response=Done, perm=DDL | RAW, hint=OperationHint.DESTRUCTIVE)
async def view_create(db: Core, req: ViewCreate) -> Done:
    query = statements.create_view(db, req)
    return await db.ddl(query)


@op(ViewDrop, response=Done, perm=DDL, hint=OperationHint.DESTRUCTIVE)
async def view_drop(db: Core, req: ViewDrop) -> Done:
    query = statements.drop_view(db, req)
    return await db.ddl(query)


@op(ViewRefresh, response=Done, perm=WRITE, hint=OperationHint.DESTRUCTIVE)
async def view_refresh(db: Core, req: ViewRefresh) -> Done:
    query = statements.refresh_view(db, req)
    async with db.tx() as conn:
        cur = await conn.execute(query)
        return Done(status=cur.statusmessage)


# ---------------------------------------------------------------- extensions, databases


@op(ExtensionList, response=ExtensionInfoList)
async def extension_list(db: Core, req: ExtensionList) -> ExtensionInfoList:
    result = await db.read(Statement.SCHEMA_AVAILABLE.text if req.input.available else Statement.SCHEMA_EXTENSIONS.text)
    return ExtensionInfoList(items=[ExtensionInfo.model_validate(r) for r in result.rows])


@op(ExtensionCreate, response=Done, perm=DDL)
async def extension_create(db: Core, req: ExtensionCreate) -> Done:
    query = statements.create_extension(req)
    return await db.ddl(query)


@op(ExtensionDrop, response=Done, perm=DDL, hint=OperationHint.DESTRUCTIVE)
async def extension_drop(db: Core, req: ExtensionDrop) -> Done:
    query = statements.drop_extension(req)
    return await db.ddl(query)


@op(DatabaseList, response=DatabaseInfoList)
async def database_list(db: Core, req: DatabaseList) -> DatabaseInfoList:
    result = await db.read(Statement.SCHEMA_DATABASES.text)
    return DatabaseInfoList(items=[DatabaseInfo.model_validate(r) for r in result.rows])
