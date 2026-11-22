from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

from pydantic import BaseModel

from pgfacade.contracts.base import Contract, RequestContract
from pgfacade.contracts.enums import Operation, OperationHint
from pgfacade.contracts.requests import response_model
from pgfacade.shared.types import (
    OperationAction,
    OperationArea,
    OperationSummary,
    PermissionFlags,
    PermissionName,
    PermissionValues,
    SecurityFlag,
)

if TYPE_CHECKING:
    from pgfacade.facade import PgFacade

_PERMISSION_NAMES: tuple[PermissionName, ...] = (
    PermissionName.WRITE,
    PermissionName.RAW,
    PermissionName.DDL,
    PermissionName.ADMIN,
    PermissionName.MIGRATE,
    PermissionName.LISTEN,
)


@dataclass(frozen=True, slots=True)
class Perm:
    write: SecurityFlag = False
    raw: SecurityFlag = False
    ddl: SecurityFlag = False
    admin: SecurityFlag = False
    migrate: SecurityFlag = False
    listen: SecurityFlag = False

    def __or__(self, other: Perm) -> Perm:
        return Perm(
            write=self.write or other.write,
            raw=self.raw or other.raw,
            ddl=self.ddl or other.ddl,
            admin=self.admin or other.admin,
            migrate=self.migrate or other.migrate,
            listen=self.listen or other.listen,
        )

    def as_tuple(self) -> PermissionValues:
        return (self.write, self.raw, self.ddl, self.admin, self.migrate, self.listen)

    def flags(self) -> PermissionFlags:
        return {name: True for name, enabled in zip(_PERMISSION_NAMES, self.as_tuple(), strict=True) if enabled}


READ = Perm()
WRITE = Perm(write=True)
RAW = Perm(raw=True)
DDL = Perm(write=True, ddl=True)
ADMIN = Perm(admin=True)
ADMIN_WRITE = Perm(write=True, admin=True)
MIGRATE = Perm(migrate=True)
MIGRATE_WRITE = Perm(write=True, migrate=True)
LISTEN = Perm(listen=True)


type Handler = Callable[[PgFacade, RequestContract[Contract]], Awaitable[Contract]]


@dataclass(frozen=True, slots=True)
class OpSpec:
    op: Operation
    area: OperationArea
    action: OperationAction
    request: type[Contract]
    response: type[Contract]
    envelope: type[BaseModel]
    perm: Perm
    hint: OperationHint
    summary: OperationSummary
    idempotent: bool
    handler: Handler


OPERATIONS: dict[Operation, OpSpec] = {}


def op_name(request: type[Contract]) -> Operation:
    field = request.model_fields.get("kind")
    if field is None or not isinstance(field.default, Operation):
        raise TypeError(f"{request.__name__} needs an operation discriminator")
    return field.default


def op[RequestT: RequestContract[Contract], ResultT: Contract](
    request: type[RequestT],
    *,
    response: type[ResultT],
    perm: Perm = READ,
    hint: OperationHint | None = None,
    idempotent: bool | None = None,
) -> Callable[[Callable[[PgFacade, RequestT], Awaitable[ResultT]]], Callable[[PgFacade, RequestT], Awaitable[ResultT]]]:
    result_contract = RequestContract.__class_getitem__(response)
    if not isinstance(result_contract, type) or not issubclass(request, result_contract):
        raise TypeError(f"{request.__name__} is not a request for {response.__name__}")
    name = op_name(request)
    area, _, action = name.partition(".")
    resolved_hint: OperationHint = hint or (OperationHint.WRITE if perm.write else OperationHint.READ)
    summary = (request.__doc__ or name).strip().splitlines()[0]

    def decorate(
        function: Callable[[PgFacade, RequestT], Awaitable[ResultT]],
    ) -> Callable[[PgFacade, RequestT], Awaitable[ResultT]]:
        if name in OPERATIONS:
            raise RuntimeError(f"duplicate op {name!r}")
        envelope = response_model(request)
        OPERATIONS[name] = OpSpec(
            op=name,
            area=area,
            action=action,
            request=request,
            response=response,
            envelope=envelope,
            perm=perm,
            hint=resolved_hint,
            summary=summary,
            idempotent=(resolved_hint == OperationHint.READ) if idempotent is None else idempotent,
            # Dispatch only passes a handler an instance of its own request type.
            handler=cast(Handler, function),
        )
        return function

    return decorate
