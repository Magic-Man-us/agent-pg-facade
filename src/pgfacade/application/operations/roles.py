"""role.* membership.* privilege.* handlers. Need admin on the key plus CREATEROLE/ownership in Postgres."""

from __future__ import annotations

from pgfacade.application.errors import NotFound
from pgfacade.application.registry import ADMIN_WRITE, op
from pgfacade.contracts.base import Done
from pgfacade.contracts.enums import GrantTarget, OperationHint
from pgfacade.contracts.roles import (
    MembershipGrant,
    MembershipRevoke,
    PrivilegeGrant,
    PrivilegeInfo,
    PrivilegeInfoList,
    PrivilegeList,
    PrivilegeRevoke,
    RoleAlter,
    RoleCreate,
    RoleDrop,
    RoleGet,
    RoleInfo,
    RoleInfoList,
    RoleList,
    RoleSetPassword,
)
from pgfacade.contracts.types import Name
from pgfacade.infrastructure.postgres.engine import Core
from pgfacade.infrastructure.postgres.queries import Statement
from pgfacade.infrastructure.postgres.queries import roles as statements


async def _get(db: Core, name: Name) -> RoleInfo:
    result = await db.read(statements.get_role(), [name])
    if not result.rows:
        raise NotFound(f"role {name!r} does not exist")
    return RoleInfo.model_validate(result.rows[0])


# ---------------------------------------------------------------- roles


@op(RoleList, response=RoleInfoList)
async def role_list(db: Core, req: RoleList) -> RoleInfoList:
    result = await db.read(statements.list_roles(req))
    return RoleInfoList(items=[RoleInfo.model_validate(r) for r in result.rows])


@op(RoleGet, response=RoleInfo)
async def role_get(db: Core, req: RoleGet) -> RoleInfo:
    return await _get(db, req.input.name)


@op(RoleCreate, response=RoleInfo, perm=ADMIN_WRITE)
async def role_create(db: Core, req: RoleCreate) -> RoleInfo:
    async with db.tx() as conn:
        query = statements.create_role(conn, req)
        await conn.execute(query)
        if req.input.comment is not None:
            await conn.execute(statements.comment_role(req.input.name, req.input.comment))
    return await _get(db, req.input.name)


@op(RoleAlter, response=RoleInfo, perm=ADMIN_WRITE, hint=OperationHint.DESTRUCTIVE)
async def role_alter(db: Core, req: RoleAlter) -> RoleInfo:
    name = req.input.name
    async with db.tx() as conn:
        query = statements.alter_role(conn, req)
        if query is not None:
            await conn.execute(query)
        if req.input.comment is not None:
            await conn.execute(statements.comment_role(name, req.input.comment))
        if req.input.rename_to is not None:
            await conn.execute(statements.rename_role(req))
            name = req.input.rename_to
    return await _get(db, name)


@op(RoleSetPassword, response=Done, perm=ADMIN_WRITE, hint=OperationHint.DESTRUCTIVE)
async def role_set_password(db: Core, req: RoleSetPassword) -> Done:
    async with db.tx() as conn:
        cur = await conn.execute(statements.set_password(conn, req))
        return Done(status=cur.statusmessage)


@op(RoleDrop, response=Done, perm=ADMIN_WRITE, hint=OperationHint.DESTRUCTIVE)
async def role_drop(db: Core, req: RoleDrop) -> Done:
    async with db.tx() as conn:
        if req.input.if_exists:
            found = await (await conn.execute(Statement.ROLES_EXISTS.text, [req.input.name])).fetchone()
            if found is None:
                return Done(status="DROP ROLE", detail={"existed": False})
        if req.input.reassign_to is not None:
            await conn.execute(statements.reassign_owned(req))
            await conn.execute(statements.drop_owned(req))
        cur = await conn.execute(statements.drop_role(req))
        return Done(status=cur.statusmessage, detail={"existed": True})


# ---------------------------------------------------------------- membership, privileges


@op(MembershipGrant, response=Done, perm=ADMIN_WRITE)
async def membership_grant(db: Core, req: MembershipGrant) -> Done:
    query = statements.grant_membership(req)
    async with db.tx() as conn:
        return Done(status=(await conn.execute(query)).statusmessage)


@op(MembershipRevoke, response=Done, perm=ADMIN_WRITE, hint=OperationHint.DESTRUCTIVE)
async def membership_revoke(db: Core, req: MembershipRevoke) -> Done:
    query = statements.revoke_membership(req)
    async with db.tx() as conn:
        return Done(status=(await conn.execute(query)).statusmessage)


@op(PrivilegeGrant, response=Done, perm=ADMIN_WRITE)
async def privilege_grant(db: Core, req: PrivilegeGrant) -> Done:
    query = statements.grant_privilege(db, req)
    async with db.tx() as conn:
        return Done(status=(await conn.execute(query)).statusmessage)


@op(PrivilegeRevoke, response=Done, perm=ADMIN_WRITE, hint=OperationHint.DESTRUCTIVE)
async def privilege_revoke(db: Core, req: PrivilegeRevoke) -> Done:
    query = statements.revoke_privilege(db, req)
    async with db.tx() as conn:
        return Done(status=(await conn.execute(query)).statusmessage)


@op(PrivilegeList, response=PrivilegeInfoList)
async def privilege_list(db: Core, req: PrivilegeList) -> PrivilegeInfoList:
    if req.input.kind == GrantTarget.TABLE:
        schema, name = db.split(req.input.target)
        result = await db.read(Statement.ROLES_TABLE_PRIVS.text, [schema, name])
    else:
        result = await db.read(Statement.ROLES_SCHEMA_PRIVS.text, [req.input.target])
    return PrivilegeInfoList(items=[PrivilegeInfo.model_validate(r) for r in result.rows])
