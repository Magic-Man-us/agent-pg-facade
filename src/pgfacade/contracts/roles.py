"""role.* membership.* privilege.* requests and results."""

from __future__ import annotations

import re
from typing import Literal

from pydantic import Field, SecretStr, model_validator

from pgfacade.contracts.base import SQL_TYPE_PATTERN, Contract, Done, Name, RequestContract
from pgfacade.contracts.enums import GrantedPrivilege, Operation
from pgfacade.contracts.enums import GrantTarget as GrantTarget
from pgfacade.contracts.enums import Privilege as Privilege
from pgfacade.contracts.types import (
    EventDateTime,
    GrantObject,
    NonEmptyItems,
    ObjectComment,
    OperationFlag,
    ResultCount,
    ResultLabel,
    RoleConnectionLimit,
    SqlBody,
)

_FUNCTION_SIGNATURE = re.compile(r"^(?P<name>[^\s()]+)\s*\((?P<args>[^()]*)\)$")
_SQL_TYPE = re.compile(SQL_TYPE_PATTERN)


class GrantSpec(Contract):
    privileges: NonEmptyItems[Privilege]
    on: GrantTarget
    target: GrantObject = Field(
        min_length=1,
        description='"schema.table", "schema", "dbname", the schema for all_*, or "schema.fn(argtype, ...)" for function',
    )
    roles: NonEmptyItems[Name] = Field(description='Grantees; "public" is allowed')
    with_grant_option: OperationFlag = False

    @model_validator(mode="after")
    def _function_target(self) -> GrantSpec:
        if self.on == GrantTarget.FUNCTION:
            self.function_signature  # noqa: B018 - validates the target
        return self

    @property
    def function_signature(self) -> tuple[ResultLabel, list[SqlBody]]:
        """("schema.fn", ["integer", "text[]"]) from a function target; argument types are validated as SQL types."""
        m = _FUNCTION_SIGNATURE.match(self.target.strip())
        if m is None:
            raise ValueError('function target must look like "schema.fn(argtype, ...)" (use "fn()" for no arguments)')
        args = [a.strip() for a in m.group("args").split(",") if a.strip()]
        for arg in args:
            if not _SQL_TYPE.match(arg):
                raise ValueError(f"invalid argument type {arg!r} in function target")
        return m.group("name"), args


class RoleInfo(Contract):
    name: ResultLabel
    login: OperationFlag
    superuser: OperationFlag
    createdb: OperationFlag
    createrole: OperationFlag
    inherit: OperationFlag
    replication: OperationFlag
    bypassrls: OperationFlag
    connection_limit: ResultCount
    valid_until: EventDateTime | None = None
    member_of: list[ResultLabel] = Field(default_factory=list)
    members: list[ResultLabel] = Field(default_factory=list)
    comment: ObjectComment | None = None


class RoleInfoList(Contract):
    items: list[RoleInfo]


class PrivilegeInfo(Contract):
    grantee: ResultLabel
    privilege: GrantedPrivilege
    grantable: OperationFlag


class PrivilegeInfoList(Contract):
    items: list[PrivilegeInfo]


class RoleListInput(Contract):
    include_system: OperationFlag = False


class RoleList(RequestContract[RoleInfoList]):
    """Roles (users) with attributes and memberships."""

    kind: Literal[Operation.ROLE_LIST] = Operation.ROLE_LIST
    input: RoleListInput


class RoleGetInput(Contract):
    name: Name


class RoleGet(RequestContract[RoleInfo]):
    """One role with flags, limits, expiry, member_of and members."""

    kind: Literal[Operation.ROLE_GET] = Operation.ROLE_GET
    input: RoleGetInput


class RoleCreateInput(Contract):
    name: Name
    password: SecretStr | None = None
    login: OperationFlag = True
    superuser: OperationFlag = False
    createdb: OperationFlag = False
    createrole: OperationFlag = False
    inherit: OperationFlag = True
    replication: OperationFlag = False
    bypassrls: OperationFlag = False
    connection_limit: RoleConnectionLimit | None = Field(None, description="-1 for unlimited")
    valid_until: EventDateTime | None = None
    in_roles: list[Name] = Field(default_factory=list, description="Roles to grant membership in")
    comment: ObjectComment | None = None


class RoleCreate(RequestContract[RoleInfo]):
    """CREATE ROLE; login=true makes a user. Password is SCRAM-hashed client-side."""

    kind: Literal[Operation.ROLE_CREATE] = Operation.ROLE_CREATE
    input: RoleCreateInput


class RoleAlterInput(Contract):
    name: Name
    password: SecretStr | None = None
    login: OperationFlag | None = None
    superuser: OperationFlag | None = None
    createdb: OperationFlag | None = None
    createrole: OperationFlag | None = None
    inherit: OperationFlag | None = None
    replication: OperationFlag | None = None
    bypassrls: OperationFlag | None = None
    connection_limit: RoleConnectionLimit | None = None
    valid_until: EventDateTime | None = None
    clear_valid_until: OperationFlag = False
    rename_to: Name | None = None
    comment: ObjectComment | None = None

    @model_validator(mode="after")
    def _not_empty(self) -> RoleAlterInput:
        changes = self.model_dump(exclude={"name", "clear_valid_until"})
        if not any(v is not None for v in changes.values()) and not self.clear_valid_until:
            raise ValueError("nothing to alter")
        return self


class RoleAlter(RequestContract[RoleInfo]):
    """ALTER ROLE: only set fields change."""

    kind: Literal[Operation.ROLE_ALTER] = Operation.ROLE_ALTER
    input: RoleAlterInput


class RoleSetPasswordInput(Contract):
    name: Name
    password: SecretStr


class RoleSetPassword(RequestContract[Done]):
    """ALTER ROLE ... PASSWORD (SCRAM-hashed client-side)."""

    kind: Literal[Operation.ROLE_SET_PASSWORD] = Operation.ROLE_SET_PASSWORD
    input: RoleSetPasswordInput


class RoleDropInput(Contract):
    name: Name
    if_exists: OperationFlag = True
    reassign_to: Name | None = None


class RoleDrop(RequestContract[Done]):
    """DROP ROLE; reassign_to moves owned objects to another role first (current database only)."""

    kind: Literal[Operation.ROLE_DROP] = Operation.ROLE_DROP
    input: RoleDropInput


class MembershipGrantInput(Contract):
    role: Name
    members: NonEmptyItems[Name]
    admin_option: OperationFlag = False


class MembershipGrant(RequestContract[Done]):
    """GRANT group role TO members."""

    kind: Literal[Operation.MEMBERSHIP_GRANT] = Operation.MEMBERSHIP_GRANT
    input: MembershipGrantInput


class MembershipRevokeInput(Contract):
    role: Name
    members: NonEmptyItems[Name]
    admin_option: OperationFlag = Field(False, description="Revoke only the admin option")


class MembershipRevoke(RequestContract[Done]):
    """REVOKE group role FROM members."""

    kind: Literal[Operation.MEMBERSHIP_REVOKE] = Operation.MEMBERSHIP_REVOKE
    input: MembershipRevokeInput


class PrivilegeGrantInput(GrantSpec):
    pass


class PrivilegeGrant(RequestContract[Done]):
    """GRANT privileges on an object (or ALL ... IN SCHEMA) to roles."""

    kind: Literal[Operation.PRIVILEGE_GRANT] = Operation.PRIVILEGE_GRANT
    input: PrivilegeGrantInput


class PrivilegeRevokeInput(GrantSpec):
    cascade: OperationFlag = False


class PrivilegeRevoke(RequestContract[Done]):
    """REVOKE privileges (same shape as grant)."""

    kind: Literal[Operation.PRIVILEGE_REVOKE] = Operation.PRIVILEGE_REVOKE
    input: PrivilegeRevokeInput


class PrivilegeListInput(Contract):
    kind: Literal[GrantTarget.TABLE, GrantTarget.SCHEMA]
    target: GrantObject


class PrivilegeList(RequestContract[PrivilegeInfoList]):
    """Who holds which privileges on a table or schema."""

    kind: Literal[Operation.PRIVILEGE_LIST] = Operation.PRIVILEGE_LIST
    input: PrivilegeListInput
