"""server.* diag.* maint.* migration.* requests and results."""

from __future__ import annotations

from typing import Literal

from pydantic import AliasChoices, Field

from pgfacade.contracts.base import Contract, Done, Flag, Name, QueryResult, RequestContract, TableName
from pgfacade.contracts.enums import BackendAction, MaintenanceKind, Operation, SettingContext
from pgfacade.contracts.types import (
    ByteCount,
    DirectoryName,
    EventDateTime,
    FileName,
    LatencyMilliseconds,
    MaintenanceTarget,
    MigrationAction,
    OperationFlag,
    PoolStatistics,
    ProcessId,
    ResultCount,
    ResultLabel,
    ResultText,
    RevisionId,
    RevisionMessage,
    RowLimit,
    SettingPattern,
    SqlBody,
)


class Health(Contract):
    ok: OperationFlag
    latency_ms: LatencyMilliseconds
    pool: PoolStatistics = Field(default_factory=dict)


class ServerInfo(Contract):
    server_version: ResultText
    version: ResultText
    database: ResultLabel
    user: ResultLabel
    session_role: ResultLabel
    started_at: EventDateTime
    database_bytes: ByteCount
    connections: ResultCount
    max_connections: ResultCount
    in_recovery: OperationFlag


class WhoAmI(Contract):
    principal: ResultLabel
    role: ResultLabel | None
    read_only: OperationFlag
    sql: OperationFlag
    ddl: OperationFlag
    admin: OperationFlag
    migrate: OperationFlag
    listen: OperationFlag


class SettingInfo(Contract):
    name: ResultLabel
    value: ResultText
    unit: ResultText | None = None
    category: ResultText
    context: SettingContext
    description: ResultText


class SettingInfoList(Contract):
    items: list[SettingInfo]


class RevisionInfo(Contract):
    revision: RevisionId
    down_revision: RevisionId | list[RevisionId] | None
    message: ResultText | None = Field(validation_alias=AliasChoices("message", "doc"))
    is_head: OperationFlag
    applied: OperationFlag = False
    path: FileName


class RevisionInfoList(Contract):
    items: list[RevisionInfo]


class MigrationStatus(Contract):
    directory: DirectoryName
    initialized: OperationFlag
    current: list[RevisionId]
    heads: list[RevisionId]
    up_to_date: OperationFlag
    pending: list[RevisionId]


class MigrationOutcome(Contract):
    before: list[RevisionId]
    after: list[RevisionId]
    output: ResultText


class ServerHealthInput(Contract):
    pass


class ServerHealth(RequestContract[Health]):
    """Round-trip latency and pool statistics."""

    kind: Literal[Operation.SERVER_HEALTH] = Operation.SERVER_HEALTH
    input: ServerHealthInput


class ServerInfoGetInput(Contract):
    pass


class ServerInfoGet(RequestContract[ServerInfo]):
    """Version, database, user and session role, uptime start, size, connections."""

    kind: Literal[Operation.SERVER_INFO] = Operation.SERVER_INFO
    input: ServerInfoGetInput


class ServerWhoAmIInput(Contract):
    pass


class ServerWhoAmI(RequestContract[WhoAmI]):
    """The principal this call runs as and its effective permissions."""

    kind: Literal[Operation.SERVER_WHOAMI] = Operation.SERVER_WHOAMI
    input: ServerWhoAmIInput


class ServerSettingsInput(Contract):
    pattern: SettingPattern = "%"
    limit: RowLimit = Field(200)


class ServerSettings(RequestContract[SettingInfoList]):
    """pg_settings matching an ILIKE pattern, e.g. 'work_mem' or '%timeout%'."""

    kind: Literal[Operation.SERVER_SETTINGS] = Operation.SERVER_SETTINGS
    input: ServerSettingsInput


class DiagActivityInput(Contract):
    include_idle: OperationFlag = False


class DiagActivity(RequestContract[QueryResult]):
    """Client sessions from pg_stat_activity."""

    kind: Literal[Operation.DIAG_ACTIVITY] = Operation.DIAG_ACTIVITY
    input: DiagActivityInput


class DiagLocksInput(Contract):
    pass


class DiagLocks(RequestContract[QueryResult]):
    """Blocked sessions paired with the sessions blocking them."""

    kind: Literal[Operation.DIAG_LOCKS] = Operation.DIAG_LOCKS
    input: DiagLocksInput


class DiagTopQueriesInput(Contract):
    limit: RowLimit = Field(20)


class DiagTopQueries(RequestContract[QueryResult]):
    """Most expensive statements by total time (needs pg_stat_statements)."""

    kind: Literal[Operation.DIAG_TOP_QUERIES] = Operation.DIAG_TOP_QUERIES
    input: DiagTopQueriesInput


class DiagTableStatsInput(Contract):
    schema_name: Name | None = None
    limit: RowLimit = Field(50)


class DiagTableStats(RequestContract[QueryResult]):
    """Live/dead rows, scans, writes, last vacuum/analyze per table."""

    kind: Literal[Operation.DIAG_TABLE_STATS] = Operation.DIAG_TABLE_STATS
    input: DiagTableStatsInput


class DiagUnusedIndexesInput(Contract):
    limit: RowLimit = Field(50)


class DiagUnusedIndexes(RequestContract[QueryResult]):
    """Non-unique indexes with zero scans since stats reset, largest first."""

    kind: Literal[Operation.DIAG_UNUSED_INDEXES] = Operation.DIAG_UNUSED_INDEXES
    input: DiagUnusedIndexesInput


class MaintBackendInput(Contract):
    action: BackendAction
    pid: ProcessId


class MaintBackend(RequestContract[Flag]):
    """Cancel a backend's running query, or terminate its connection."""

    kind: Literal[Operation.MAINT_BACKEND] = Operation.MAINT_BACKEND
    input: MaintBackendInput


class MaintVacuumInput(Contract):
    table: TableName | None = None
    full: OperationFlag = False
    analyze: OperationFlag = True


class MaintVacuum(RequestContract[Done]):
    """VACUUM [FULL] [ANALYZE]; table=null means the whole database."""

    kind: Literal[Operation.MAINT_VACUUM] = Operation.MAINT_VACUUM
    input: MaintVacuumInput


class MaintAnalyzeInput(Contract):
    table: TableName | None = None


class MaintAnalyze(RequestContract[Done]):
    """ANALYZE; table=null means the whole database."""

    kind: Literal[Operation.MAINT_ANALYZE] = Operation.MAINT_ANALYZE
    input: MaintAnalyzeInput


class MaintReindexInput(Contract):
    kind: MaintenanceKind
    name: MaintenanceTarget
    concurrently: OperationFlag = False


class MaintReindex(RequestContract[Done]):
    """REINDEX a table, index, or schema."""

    kind: Literal[Operation.MAINT_REINDEX] = Operation.MAINT_REINDEX
    input: MaintReindexInput


class MigrationStatusGetInput(Contract):
    pass


class MigrationStatusGet(RequestContract[MigrationStatus]):
    """Alembic state: current revision(s), heads, pending."""

    kind: Literal[Operation.MIGRATION_STATUS] = Operation.MIGRATION_STATUS
    input: MigrationStatusGetInput


class MigrationInitInput(Contract):
    pass


class MigrationInit(RequestContract[MigrationStatus]):
    """Create the migrations directory (env.py, versions/) if missing."""

    kind: Literal[Operation.MIGRATION_INIT] = Operation.MIGRATION_INIT
    input: MigrationInitInput


class MigrationHistoryInput(Contract):
    pass


class MigrationHistory(RequestContract[RevisionInfoList]):
    """All revisions oldest first with applied flags."""

    kind: Literal[Operation.MIGRATION_HISTORY] = Operation.MIGRATION_HISTORY
    input: MigrationHistoryInput


class MigrationRevisionInput(Contract):
    message: RevisionMessage = Field(description="Becomes the revision module's docstring")
    upgrade_sql: SqlBody | None = None
    downgrade_sql: SqlBody | None = None


class MigrationRevision(RequestContract[RevisionInfo]):
    """Write a new revision file; SQL bodies are embedded as op.execute()."""

    kind: Literal[Operation.MIGRATION_REVISION] = Operation.MIGRATION_REVISION
    input: MigrationRevisionInput


class MigrationRunInput(Contract):
    action: MigrationAction
    target: RevisionId | None = None


class MigrationRun(RequestContract[MigrationOutcome]):
    """upgrade (default head), downgrade (default -1), or stamp (default head)."""

    kind: Literal[Operation.MIGRATION_RUN] = Operation.MIGRATION_RUN
    input: MigrationRunInput
