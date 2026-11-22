"""lifecycle.* requests and results: TTL and expiry policies on rows and tables.

Postgres has no native row TTL. Policies are stored in `_pgfacade.lifecycle_policies` and applied
by the SQL function `_pgfacade.run_lifecycle()`, which the in-process sweeper calls on an interval
and which pg_cron can call when available (lifecycle.schedule).

Every choice between alternatives is a union discriminated by `kind`: how rows expire, what happens
to them, when a table expires, which policies a run covers, and whether a pg_cron schedule exists.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Annotated, Literal

from pydantic import Field, TypeAdapter, model_validator

from pgfacade.contracts.base import Contract, Count, Done, Interval, Name, RequestContract, TableName
from pgfacade.contracts.enums import (
    ExpiryTimeKind,
    LifecycleAction,
    LifecycleKind,
    LifecycleScheduleKind,
    LifecycleTargetKind,
    Operation,
    RowExpiryKind,
)
from pgfacade.contracts.types import (
    CronExpression,
    DatabaseInterval,
    EventDateTime,
    LifecycleBatchSize,
    LifecyclePolicyId,
    LifecycleRunId,
    OperationFlag,
    ResultCount,
    ResultLabel,
    ResultText,
    RowCount,
    RowLimit,
)
from pgfacade.shared.config import SOURCE_CONFIG

TableAction = Literal[LifecycleAction.TRUNCATE, LifecycleAction.DROP]


# ---------------------------------------------------------------- row expiry and disposal


class RowAge(Contract):
    """Rows expire once `column` is older than `ttl`."""

    kind: Literal[RowExpiryKind.AGE] = RowExpiryKind.AGE
    column: ResultLabel
    ttl: DatabaseInterval


class RowDeadline(Contract):
    """Rows expire once the time stored in `column` has passed."""

    kind: Literal[RowExpiryKind.DEADLINE] = RowExpiryKind.DEADLINE
    column: ResultLabel


RowExpiry = Annotated[RowAge | RowDeadline, Field(discriminator="kind")]


class RowAgeInput(Contract):
    """Rows expire once `column` is older than `ttl`."""

    kind: Literal[RowExpiryKind.AGE] = RowExpiryKind.AGE
    column: Name = Field(description="timestamp, timestamptz or date column, e.g. created_at")
    ttl: Interval
    add_column: OperationFlag = Field(False, description="Add the column if missing (timestamptz NOT NULL DEFAULT now())")


class RowDeadlineInput(Contract):
    """Rows expire once the time stored in `column` has passed."""

    kind: Literal[RowExpiryKind.DEADLINE] = RowExpiryKind.DEADLINE
    column: Name = Field(description="timestamp, timestamptz or date column holding each row's expiry time, e.g. expires_at")


RowExpiryInput = Annotated[RowAgeInput | RowDeadlineInput, Field(discriminator="kind")]


class DeleteRows(Contract):
    """Expired rows are deleted."""

    kind: Literal[LifecycleAction.DELETE] = LifecycleAction.DELETE


class ArchiveRows(Contract):
    """Expired rows are moved to `table`."""

    kind: Literal[LifecycleAction.ARCHIVE] = LifecycleAction.ARCHIVE
    table: ResultText


RowAction = Annotated[DeleteRows | ArchiveRows, Field(discriminator="kind")]


class ArchiveRowsInput(Contract):
    """Expired rows are moved to an archive table."""

    kind: Literal[LifecycleAction.ARCHIVE] = LifecycleAction.ARCHIVE
    table: TableName | None = Field(None, description="Defaults to <table>_archive; created if missing")


RowActionInput = Annotated[DeleteRows | ArchiveRowsInput, Field(discriminator="kind")]


# ---------------------------------------------------------------- table expiry time


class ExpiresAt(Contract):
    """The table expires at a fixed time."""

    kind: Literal[ExpiryTimeKind.AT] = ExpiryTimeKind.AT
    time: EventDateTime


class ExpiresIn(Contract):
    """The table expires once an interval, counted from now, has passed."""

    kind: Literal[ExpiryTimeKind.IN] = ExpiryTimeKind.IN
    interval: Interval


TableExpiryTime = Annotated[ExpiresAt | ExpiresIn, Field(discriminator="kind")]


# ---------------------------------------------------------------- run target and schedule


class AllPolicies(Contract):
    """Every enabled policy."""

    kind: Literal[LifecycleTargetKind.ALL] = LifecycleTargetKind.ALL


class OnePolicy(Contract):
    kind: Literal[LifecycleTargetKind.POLICY] = LifecycleTargetKind.POLICY
    policy_id: LifecyclePolicyId


RunTarget = Annotated[AllPolicies | OnePolicy, Field(discriminator="kind")]


class CronSchedule(Contract):
    """pg_cron runs run_lifecycle() on this expression."""

    kind: Literal[LifecycleScheduleKind.CRON] = LifecycleScheduleKind.CRON
    expression: CronExpression = Field(description="e.g. '*/5 * * * *'")


class NoSchedule(Contract):
    """No pg_cron job; only the in-process sweeper applies policies."""

    kind: Literal[LifecycleScheduleKind.OFF] = LifecycleScheduleKind.OFF


SweepSchedule = Annotated[CronSchedule | NoSchedule, Field(discriminator="kind")]


# ---------------------------------------------------------------- stored policies


class _StoredPolicy(Contract):
    """Bookkeeping every policy carries, whatever its kind."""

    id: LifecyclePolicyId
    schema_name: ResultLabel
    table_name: ResultLabel
    enabled: OperationFlag
    created_at: EventDateTime
    last_run_at: EventDateTime | None = None
    last_rows: RowCount | None = None
    last_error: ResultText | None = None


class _RowTtlRow(_StoredPolicy):
    """A row_ttl row of _pgfacade.lifecycle_policies. The table is flat and holds every kind's columns."""

    model_config = SOURCE_CONFIG

    kind: Literal[LifecycleKind.ROW_TTL]
    column_name: ResultLabel
    ttl: DatabaseInterval | None = None
    action: Literal[LifecycleAction.DELETE, LifecycleAction.ARCHIVE]
    archive_table: ResultText | None = None
    batch_size: ResultCount

    @property
    def expiry(self) -> RowAge | RowDeadline:
        return RowDeadline(column=self.column_name) if self.ttl is None else RowAge(column=self.column_name, ttl=self.ttl)

    @property
    def disposal(self) -> DeleteRows | ArchiveRows:
        if self.action == LifecycleAction.DELETE:
            return DeleteRows()
        return ArchiveRows.model_validate({"table": self.archive_table})


class _TableExpiryRow(_StoredPolicy):
    """A table_expiry row of _pgfacade.lifecycle_policies."""

    model_config = SOURCE_CONFIG

    kind: Literal[LifecycleKind.TABLE_EXPIRY]
    expires_at: EventDateTime
    action: TableAction


def _is_table_row(value: object) -> bool:
    return isinstance(value, Mapping) and "column_name" in value


class RowTtlPolicy(_StoredPolicy):
    kind: Literal[LifecycleKind.ROW_TTL] = LifecycleKind.ROW_TTL
    expiry: RowExpiry
    action: RowAction
    batch_size: ResultCount

    @model_validator(mode="before")
    @classmethod
    def read_database_row(cls, value: object) -> object:
        if _is_table_row(value):
            row = _RowTtlRow.model_validate(value)
            stored = row.model_dump(exclude={"column_name", "ttl", "archive_table"})
            return stored | {"expiry": row.expiry, "action": row.disposal}
        return value


class TableExpiryPolicy(_StoredPolicy):
    kind: Literal[LifecycleKind.TABLE_EXPIRY] = LifecycleKind.TABLE_EXPIRY
    expires_at: EventDateTime
    action: TableAction

    @model_validator(mode="before")
    @classmethod
    def read_database_row(cls, value: object) -> object:
        return _TableExpiryRow.model_validate(value).model_dump() if _is_table_row(value) else value


LifecyclePolicy = Annotated[RowTtlPolicy | TableExpiryPolicy, Field(discriminator="kind")]
LIFECYCLE_POLICY_ADAPTER = TypeAdapter(LifecyclePolicy)


class LifecyclePolicyList(Contract):
    items: list[LifecyclePolicy]
    installed: OperationFlag
    schedule: SweepSchedule = Field(default_factory=NoSchedule, description="pg_cron schedule of run_lifecycle()")


class LifecycleRunOutcome(Contract):
    policy_id: LifecyclePolicyId
    rows_affected: RowCount
    error: ResultText | None = None


class LifecycleRunReport(Contract):
    items: list[LifecycleRunOutcome]


class LifecycleRunRecord(Contract):
    id: LifecycleRunId
    policy_id: LifecyclePolicyId
    table_name: ResultLabel
    action: LifecycleAction
    started_at: EventDateTime
    finished_at: EventDateTime
    rows_affected: RowCount
    error: ResultText | None = None


class LifecycleRunList(Contract):
    items: list[LifecycleRunRecord]


# ---------------------------------------------------------------- requests


class LifecycleInstallInput(Contract):
    pass


class LifecycleInstall(RequestContract[Done]):
    """Create the _pgfacade schema, policy table, and run_lifecycle() function (idempotent)."""

    kind: Literal[Operation.LIFECYCLE_INSTALL] = Operation.LIFECYCLE_INSTALL
    input: LifecycleInstallInput


class LifecycleListInput(Contract):
    pass


class LifecycleList(RequestContract[LifecyclePolicyList]):
    """All policies with last run outcome."""

    kind: Literal[Operation.LIFECYCLE_LIST] = Operation.LIFECYCLE_LIST
    input: LifecycleListInput


class LifecycleRowTtlInput(Contract):
    table: TableName
    expiry: RowExpiryInput
    action: RowActionInput = Field(default_factory=DeleteRows)
    batch_size: LifecycleBatchSize = 5_000
    enabled: OperationFlag = True


class LifecycleRowTtl(RequestContract[RowTtlPolicy]):
    """Expire rows by age (column older than ttl) or by a per-row deadline column: delete them or move them to an archive."""

    kind: Literal[Operation.LIFECYCLE_ROW_TTL] = Operation.LIFECYCLE_ROW_TTL
    input: LifecycleRowTtlInput


class LifecycleTableExpiryInput(Contract):
    table: TableName
    expiry: TableExpiryTime
    action: TableAction = LifecycleAction.TRUNCATE
    enabled: OperationFlag = True


class LifecycleTableExpiry(RequestContract[TableExpiryPolicy]):
    """Truncate or drop a whole table at a point in time (or after an interval from now)."""

    kind: Literal[Operation.LIFECYCLE_TABLE_EXPIRY] = Operation.LIFECYCLE_TABLE_EXPIRY
    input: LifecycleTableExpiryInput


class LifecycleRemoveInput(Contract):
    policy_id: LifecyclePolicyId


class LifecycleRemove(RequestContract[Done]):
    """Delete a policy by id."""

    kind: Literal[Operation.LIFECYCLE_REMOVE] = Operation.LIFECYCLE_REMOVE
    input: LifecycleRemoveInput


class LifecycleRunInput(Contract):
    target: RunTarget


class LifecycleRun(RequestContract[LifecycleRunReport]):
    """Apply one policy, or every enabled policy, now."""

    kind: Literal[Operation.LIFECYCLE_RUN] = Operation.LIFECYCLE_RUN
    input: LifecycleRunInput


class LifecyclePreviewInput(Contract):
    policy_id: LifecyclePolicyId


class LifecyclePreview(RequestContract[Count]):
    """Count the rows a policy would touch right now, without changing anything."""

    kind: Literal[Operation.LIFECYCLE_PREVIEW] = Operation.LIFECYCLE_PREVIEW
    input: LifecyclePreviewInput


class LifecycleRunsInput(Contract):
    policy_id: LifecyclePolicyId | None = None
    limit: RowLimit = Field(50)


class LifecycleRuns(RequestContract[LifecycleRunList]):
    """Run history, newest first (kept for 30 days)."""

    kind: Literal[Operation.LIFECYCLE_RUNS] = Operation.LIFECYCLE_RUNS
    input: LifecycleRunsInput


class LifecycleScheduleInput(Contract):
    schedule: SweepSchedule


class LifecycleSchedule(RequestContract[Done]):
    """Schedule run_lifecycle() in pg_cron with a cron expression, or remove the schedule."""

    kind: Literal[Operation.LIFECYCLE_SCHEDULE] = Operation.LIFECYCLE_SCHEDULE
    input: LifecycleScheduleInput
