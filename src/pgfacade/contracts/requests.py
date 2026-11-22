"""Business models shared by the facade, webapp, and webmcp. `Request` is the discriminated union of every op."""

from __future__ import annotations

from functools import cache
from typing import TYPE_CHECKING, Annotated, Literal, Union, cast, get_args

from pydantic import BaseModel, Field, TypeAdapter, create_model

from pgfacade.contracts.admin import (
    DiagActivity,
    DiagLocks,
    DiagTableStats,
    DiagTopQueries,
    DiagUnusedIndexes,
    MaintAnalyze,
    MaintBackend,
    MaintReindex,
    MaintVacuum,
    MigrationHistory,
    MigrationInit,
    MigrationRevision,
    MigrationRun,
    MigrationStatusGet,
    ServerHealth,
    ServerInfoGet,
    ServerSettings,
    ServerWhoAmI,
)
from pgfacade.contracts.base import (
    Contract,
    RequestContract,
)
from pgfacade.contracts.enums import Operation
from pgfacade.contracts.envelopes import ResponseEnvelope
from pgfacade.contracts.events import (
    EventNotify,
    EventUnwatch,
    EventWait,
    EventWatch,
    EventWatchList,
)
from pgfacade.contracts.lifecycle import (
    LifecycleInstall,
    LifecycleList,
    LifecyclePreview,
    LifecycleRemove,
    LifecycleRowTtl,
    LifecycleRun,
    LifecycleRuns,
    LifecycleSchedule,
    LifecycleTableExpiry,
)
from pgfacade.contracts.queries import (
    QueryList,
    QueryReload,
    QueryRun,
)
from pgfacade.contracts.roles import (
    MembershipGrant,
    MembershipRevoke,
    PrivilegeGrant,
    PrivilegeList,
    PrivilegeRevoke,
    RoleAlter,
    RoleCreate,
    RoleDrop,
    RoleGet,
    RoleList,
    RoleSetPassword,
)
from pgfacade.contracts.rows import (
    RowsAggregate,
    RowsCount,
    RowsDelete,
    RowsExists,
    RowsExportCsv,
    RowsGet,
    RowsImportCsv,
    RowsInsert,
    RowsSelect,
    RowsUpdate,
    SqlExecute,
    SqlExplain,
    SqlQuery,
)
from pgfacade.contracts.schema import (
    ColumnAdd,
    ColumnAlter,
    ColumnDrop,
    ColumnRename,
    ConstraintAdd,
    ConstraintDrop,
    DatabaseList,
    ExtensionCreate,
    ExtensionDrop,
    ExtensionList,
    IndexCreate,
    IndexDrop,
    SchemaCreate,
    SchemaDrop,
    SchemaList,
    TableComment,
    TableCreate,
    TableDescribe,
    TableDrop,
    TableList,
    TableRename,
    TableTruncate,
    ViewCreate,
    ViewDrop,
    ViewRefresh,
)
from pgfacade.contracts.types import NonEmptyItems

# ---------------------------------------------------------------- the request union


if TYPE_CHECKING:
    BatchItem = ResponseEnvelope[Contract]


class BatchResult(Contract):
    results: list[BatchItem]


class BatchInput(Contract):
    requests: NonEmptyItems[Request]


class Batch(RequestContract[BatchResult]):
    """Run several requests in order inside one transaction; any failure rolls back all of them."""

    kind: Literal[Operation.BATCH_RUN] = Operation.BATCH_RUN
    input: BatchInput


Request = Annotated[
    RowsSelect
    | RowsGet
    | RowsCount
    | RowsExists
    | RowsAggregate
    | RowsInsert
    | RowsUpdate
    | RowsDelete
    | RowsExportCsv
    | RowsImportCsv
    | SqlQuery
    | SqlExecute
    | SqlExplain
    | SchemaList
    | SchemaCreate
    | SchemaDrop
    | TableList
    | TableDescribe
    | TableCreate
    | TableDrop
    | TableRename
    | TableTruncate
    | TableComment
    | ColumnAdd
    | ColumnAlter
    | ColumnRename
    | ColumnDrop
    | ConstraintAdd
    | ConstraintDrop
    | IndexCreate
    | IndexDrop
    | ViewCreate
    | ViewDrop
    | ViewRefresh
    | ExtensionList
    | ExtensionCreate
    | ExtensionDrop
    | DatabaseList
    | RoleList
    | RoleGet
    | RoleCreate
    | RoleAlter
    | RoleSetPassword
    | RoleDrop
    | MembershipGrant
    | MembershipRevoke
    | PrivilegeGrant
    | PrivilegeRevoke
    | PrivilegeList
    | ServerHealth
    | ServerInfoGet
    | ServerWhoAmI
    | ServerSettings
    | DiagActivity
    | DiagLocks
    | DiagTopQueries
    | DiagTableStats
    | DiagUnusedIndexes
    | MaintBackend
    | MaintVacuum
    | MaintAnalyze
    | MaintReindex
    | MigrationStatusGet
    | MigrationInit
    | MigrationHistory
    | MigrationRevision
    | MigrationRun
    | LifecycleInstall
    | LifecycleList
    | LifecycleRowTtl
    | LifecycleTableExpiry
    | LifecycleRemove
    | LifecycleRun
    | LifecyclePreview
    | LifecycleRuns
    | LifecycleSchedule
    | EventNotify
    | EventWait
    | EventWatch
    | EventUnwatch
    | EventWatchList
    | QueryList
    | QueryRun
    | QueryReload
    | Batch,
    Field(discriminator="kind"),
]
BatchInput.model_rebuild()
Batch.model_rebuild()
REQUEST_TYPES: tuple[type[RequestContract[Contract]], ...] = get_args(get_args(Request)[0])
RequestAdapter: TypeAdapter[Request] = TypeAdapter(Request)


def parse_request(data: object) -> Request:
    """Validate a dict (or model) into the concrete request model by its `kind`."""
    return RequestAdapter.validate_python(data)


@cache
def response_model(request: type[RequestContract[Contract]]) -> type[BaseModel]:
    # Pydantic stores specialization arguments on generic base classes, including phantom result parameters.
    for base in request.__mro__:
        if not issubclass(base, RequestContract):
            continue
        arguments = base.__pydantic_generic_metadata__["args"]
        if len(arguments) == 1 and isinstance(result := arguments[0], type) and issubclass(result, Contract):
            kind: Operation = request.model_fields["kind"].default
            return create_model(
                f"{request.__name__}Response",
                __base__=cast(type[BaseModel], ResponseEnvelope.__class_getitem__(result)),
                kind=(Literal[kind], kind),  # type: ignore[arg-type]  # Runtime operation tags specialize envelope literals.
            )
    raise TypeError(f"{request.__name__} must declare its response contract")


_RESPONSE_VARIANTS = tuple(response_model(request) for request in REQUEST_TYPES if request is not Batch)
# The request union owns batch response variants independently of executable handler registrations.
BatchItemContract = Annotated[Union[_RESPONSE_VARIANTS], Field(discriminator="kind")]  # type: ignore[valid-type]  # noqa: UP007
BatchResult.model_rebuild(_types_namespace={"BatchItem": BatchItemContract})
RESPONSE_MODELS = {request.model_fields["kind"].default: response_model(request) for request in REQUEST_TYPES}
