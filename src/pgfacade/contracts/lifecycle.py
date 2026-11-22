"""lifecycle.* requests and results: TTL and expiry policies on rows and tables.

Postgres has no native row TTL. Policies are stored in `_pgfacade.lifecycle_policies` and applied
by the SQL function `_pgfacade.run_lifecycle()`, which the in-process sweeper calls on an interval
and which pg_cron can call when available (lifecycle.schedule).
"""

from __future__ import annotations

from typing import Annotated, Literal, Self

from pydantic import AliasChoices, Field, TypeAdapter, model_validator

from pgfacade.contracts.base import Contract, Count, Done, Interval, Name, RequestContract, TableName
from pgfacade.contracts.enums import LifecycleAction, LifecycleKind, Operation
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

RowAction = Literal[LifecycleAction.DELETE, LifecycleAction.ARCHIVE]


class _LifecyclePolicy(Contract):
    id: LifecyclePolicyId
    schema_name: ResultLabel
    table_name: ResultLabel
    column_name: ResultLabel | None = None
    ttl: DatabaseInterval | None = None
    expires_at: EventDateTime | None = None
    archive_table: ResultText | None = None
    batch_size: ResultCount
    enabled: OperationFlag
    created_at: EventDateTime
    last_run_at: EventDateTime | None = None
    last_rows: RowCount | None = None
    last_error: ResultText | None = None


class RowTtlPolicy(_LifecyclePolicy):
    kind: Literal[LifecycleKind.ROW_TTL] = LifecycleKind.ROW_TTL
    column_name: ResultLabel
    expires_at: None = None
    action: RowAction

    @property
    def expiry_column(self) -> ResultLabel:
        return self.column_name


class TableExpiryPolicy(_LifecyclePolicy):
    kind: Literal[LifecycleKind.TABLE_EXPIRY] = LifecycleKind.TABLE_EXPIRY
    expires_at: EventDateTime
    column_name: None = None
    ttl: None = None
    archive_table: None = None
    action: Literal[LifecycleAction.TRUNCATE, LifecycleAction.DROP]


LifecyclePolicy = Annotated[RowTtlPolicy | TableExpiryPolicy, Field(discriminator="kind")]
LIFECYCLE_POLICY_ADAPTER = TypeAdapter(LifecyclePolicy)


class LifecyclePolicyList(Contract):
    items: list[LifecyclePolicy]
    installed: OperationFlag
    scheduled: CronExpression | None = Field(None, description="pg_cron schedule when one exists")


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
    column: Name = Field(description="timestamp/timestamptz column, e.g. created_at or expires_at")
    ttl: Interval | None = Field(None, description="Age after which rows expire; null means the column itself is the expiry time")
    action: RowAction = Field(LifecycleAction.DELETE, description="delete rows, or archive them (move to archive_table before deleting)")
    archive_table: TableName | None = Field(None, description="archive only: defaults to <table>_archive, created if missing")
    batch_size: LifecycleBatchSize = 5_000
    add_column: OperationFlag = Field(
        False, description="Add the column if missing (timestamptz DEFAULT now(), or now()+ttl for expiry columns)"
    )
    enabled: OperationFlag = True


class LifecycleRowTtl(RequestContract[RowTtlPolicy]):
    """Expire rows once a timestamp column is older than ttl (or past, when ttl is null): delete them or move them to an archive."""

    kind: Literal[Operation.LIFECYCLE_ROW_TTL] = Operation.LIFECYCLE_ROW_TTL
    input: LifecycleRowTtlInput


class LifecycleTableExpiryInput(Contract):
    table: TableName
    expires_at: EventDateTime | None = None
    expires_in: Interval | None = None
    action: Literal[LifecycleAction.TRUNCATE, LifecycleAction.DROP] = LifecycleAction.TRUNCATE
    enabled: OperationFlag = True

    @model_validator(mode="after")
    def validate_expiry_input(self) -> Self:
        if (self.expires_at is None) == (self.expires_in is None):
            raise ValueError("pass exactly one of expires_at or expires_in")
        return self


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
    policy_id: LifecyclePolicyId | None = None


class LifecycleRun(RequestContract[LifecycleRunReport]):
    """Apply one policy (or all) now."""

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
    cron: CronExpression | None = Field(None, description="e.g. '*/5 * * * *'; null removes the job")


class LifecycleSchedule(RequestContract[Done]):
    """Schedule run_lifecycle() in pg_cron (cron expression), or unschedule with null."""

    kind: Literal[Operation.LIFECYCLE_SCHEDULE] = Operation.LIFECYCLE_SCHEDULE
    input: LifecycleScheduleInput


class LifecyclePolicyWrite(Contract):
    model_config = SOURCE_CONFIG

    kind: LifecycleKind
    schema_name: Name
    table_name: Name
    column_name: Name | None = Field(default=None, validation_alias=AliasChoices("column_name", "column"))
    ttl: Interval | None = None
    expires_at: EventDateTime | None = None
    action: LifecycleAction
    archive_table: TableName | None = None
    batch_size: LifecycleBatchSize = 1
    enabled: OperationFlag = True
