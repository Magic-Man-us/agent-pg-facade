"""role.* membership.* privilege.* handlers. Need admin on the key plus CREATEROLE/ownership in Postgres."""

from __future__ import annotations

from typing import TYPE_CHECKING

from psycopg import sql

from pgfacade.contracts.enums import GrantTarget, Privilege
from pgfacade.contracts.roles import (
    GrantSpec,
    MembershipGrant,
    MembershipRevoke,
    PrivilegeGrant,
    PrivilegeRevoke,
    RoleAlter,
    RoleAlterInput,
    RoleCreate,
    RoleCreateInput,
    RoleDrop,
    RoleList,
    RoleSetPassword,
)
from pgfacade.contracts.types import Name, ObjectComment, PasswordHash, RolePasswordText
from pgfacade.infrastructure.postgres.queries.types import QuerySql

if TYPE_CHECKING:
    from pgfacade.infrastructure.postgres.engine import Conn, Core
from pgfacade.infrastructure.postgres.queries import Statement
from pgfacade.infrastructure.postgres.queries.composition import flag, kw

_FLAG_SQL = {
    "login": ("LOGIN", "NOLOGIN"),
    "superuser": ("SUPERUSER", "NOSUPERUSER"),
    "createdb": ("CREATEDB", "NOCREATEDB"),
    "createrole": ("CREATEROLE", "NOCREATEROLE"),
    "inherit": ("INHERIT", "NOINHERIT"),
    "replication": ("REPLICATION", "NOREPLICATION"),
    "bypassrls": ("BYPASSRLS", "NOBYPASSRLS"),
}
_TARGET_SQL = {
    GrantTarget.TABLE: "TABLE {}",
    GrantTarget.SEQUENCE: "SEQUENCE {}",
    GrantTarget.SCHEMA: "SCHEMA {}",
    GrantTarget.DATABASE: "DATABASE {}",
    GrantTarget.FUNCTION: "FUNCTION {}",
    GrantTarget.ALL_TABLES_IN_SCHEMA: "ALL TABLES IN SCHEMA {}",
    GrantTarget.ALL_SEQUENCES_IN_SCHEMA: "ALL SEQUENCES IN SCHEMA {}",
    GrantTarget.ALL_FUNCTIONS_IN_SCHEMA: "ALL FUNCTIONS IN SCHEMA {}",
}


def _hash(conn: Conn, name: Name, password: RolePasswordText) -> PasswordHash:
    """SCRAM-SHA-256 hash computed client-side so plaintext never reaches server logs."""
    return conn.pgconn.encrypt_password(password.encode(), name.encode(), b"scram-sha-256").decode()


def _options(conn: Conn, name: Name, spec: RoleCreateInput | RoleAlterInput) -> list[sql.Composable]:
    opts: list[sql.Composable] = []
    flags = (
        ("superuser", spec.superuser),
        ("login", spec.login),
        ("createdb", spec.createdb),
        ("createrole", spec.createrole),
        ("inherit", spec.inherit),
        ("replication", spec.replication),
        ("bypassrls", spec.bypassrls),
    )
    for flag_name, enabled in flags:
        if enabled is not None:
            opts.append(kw(_FLAG_SQL[flag_name][0 if enabled else 1]))
    if spec.password is not None:
        opts.append(sql.SQL("PASSWORD {}").format(sql.Literal(_hash(conn, name, spec.password.get_secret_value()))))
    if spec.connection_limit is not None:
        opts.append(sql.SQL("CONNECTION LIMIT {}").format(sql.Literal(spec.connection_limit)))
    if spec.valid_until is not None:
        opts.append(sql.SQL("VALID UNTIL {}").format(sql.Literal(spec.valid_until.isoformat())))
    return opts


PUBLIC_ROLE = "public"


def _grantee(name: Name) -> sql.Composable:
    return sql.SQL("PUBLIC") if name.lower() == PUBLIC_ROLE else sql.Identifier(name)


def _grantees(names: list[Name]) -> sql.Composable:
    return sql.SQL(", ").join([_grantee(r) for r in names])


def _idents(names: list[Name]) -> sql.Composable:
    return sql.SQL(", ").join([sql.Identifier(n) for n in names])


def _target(db: Core, spec: GrantSpec) -> sql.Composable:
    if spec.on in (GrantTarget.TABLE, GrantTarget.SEQUENCE):
        ident: sql.Composable = db.qualified(spec.target)
    elif spec.on == GrantTarget.FUNCTION:
        # Validated by GrantSpec: "schema.fn(type, type)". Quote the name; each argument type is a checked keyword.
        name, args = spec.function_signature
        ident = sql.SQL("{}({})").format(db.qualified(name), sql.SQL(", ").join([kw(a) for a in args]))
    else:
        ident = sql.Identifier(spec.target)
    return sql.SQL(_TARGET_SQL[spec.on]).format(ident)


def _privs(spec: GrantSpec) -> sql.Composable:
    if Privilege.ALL in spec.privileges:
        return sql.SQL("ALL PRIVILEGES")
    return sql.SQL(", ").join([kw(p.upper()) for p in spec.privileges])


def get_role() -> QuerySql:
    return Statement.ROLES_LIST.text.replace("__COND__", "r.rolname = %s")


def list_roles(req: RoleList) -> QuerySql:
    cond = "TRUE" if req.input.include_system else "r.rolname !~ '^pg_'"
    return Statement.ROLES_LIST.text.replace("__COND__", cond)


def create_role(conn: Conn, req: RoleCreate) -> sql.Composed:
    opts = _options(conn, req.input.name, req.input)
    if req.input.in_roles:
        opts.append(sql.SQL("IN ROLE {}").format(_idents(req.input.in_roles)))
    return Statement.ROLES_CREATE.sql.format(
        sql.Identifier(req.input.name), (Statement.ROLES_OPTIONS.sql + sql.SQL(" ").join(opts)) if opts else sql.SQL("")
    )


def comment_role(name: Name, comment: ObjectComment) -> sql.Composed:
    return Statement.ROLES_COMMENT.sql.format(sql.Identifier(name), sql.Literal(comment))


def alter_role(conn: Conn, req: RoleAlter) -> sql.Composed | None:
    opts = _options(conn, req.input.name, req.input)
    if req.input.clear_valid_until:
        opts.append(sql.SQL("VALID UNTIL 'infinity'"))
    return Statement.ROLES_ALTER.sql.format(sql.Identifier(req.input.name), sql.SQL(" ").join(opts)) if opts else None


def rename_role(req: RoleAlter) -> sql.Composed:
    assert req.input.rename_to is not None
    return Statement.ROLES_RENAME.sql.format(sql.Identifier(req.input.name), sql.Identifier(req.input.rename_to))


def set_password(conn: Conn, req: RoleSetPassword) -> sql.Composed:
    hashed = _hash(conn, req.input.name, req.input.password.get_secret_value())
    return Statement.ROLES_SET_PASSWORD.sql.format(sql.Identifier(req.input.name), sql.Literal(hashed))


def reassign_owned(req: RoleDrop) -> sql.Composed:
    assert req.input.reassign_to is not None
    return Statement.ROLES_REASSIGN_OWNED.sql.format(sql.Identifier(req.input.name), sql.Identifier(req.input.reassign_to))


def drop_owned(req: RoleDrop) -> sql.Composed:
    return Statement.ROLES_DROP_OWNED.sql.format(sql.Identifier(req.input.name))


def drop_role(req: RoleDrop) -> sql.Composed:
    return Statement.ROLES_DROP.sql.format(sql.Identifier(req.input.name))


def grant_membership(req: MembershipGrant) -> sql.Composed:
    return Statement.ROLES_MEMBERSHIP_GRANT.sql.format(
        sql.Identifier(req.input.role), _idents(req.input.members), flag(req.input.admin_option, " WITH ADMIN OPTION")
    )


def revoke_membership(req: MembershipRevoke) -> sql.Composed:
    return Statement.ROLES_MEMBERSHIP_REVOKE.sql.format(
        flag(req.input.admin_option, "ADMIN OPTION FOR "), sql.Identifier(req.input.role), _idents(req.input.members)
    )


def grant_privilege(db: Core, req: PrivilegeGrant) -> sql.Composed:
    return Statement.ROLES_PRIVILEGE_GRANT.sql.format(
        _privs(req.input), _target(db, req.input), _grantees(req.input.roles), flag(req.input.with_grant_option, " WITH GRANT OPTION")
    )


def revoke_privilege(db: Core, req: PrivilegeRevoke) -> sql.Composed:
    return Statement.ROLES_PRIVILEGE_REVOKE.sql.format(
        flag(req.input.with_grant_option, "GRANT OPTION FOR "),
        _privs(req.input),
        _target(db, req.input),
        _grantees(req.input.roles),
        flag(req.input.cascade, " CASCADE"),
    )
