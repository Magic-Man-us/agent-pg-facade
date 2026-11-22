from __future__ import annotations

from enum import StrEnum, unique
from functools import cache
from importlib import resources

from psycopg import sql
from pydantic import BaseModel

from pgfacade.infrastructure.postgres.queries.types import QueryAccess, QueryName, QueryResourcePath, QuerySql
from pgfacade.shared.config import CONTRACT_CONFIG


@unique
class Statement(StrEnum):
    ADMIN_ACTIVITY = "internal/admin/activity"
    ADMIN_ANALYZE = "internal/admin/analyze"
    ADMIN_BACKEND_CONTROL = "internal/admin/backend_control"
    ADMIN_LOCKS = "internal/admin/locks"
    ADMIN_PING = "internal/admin/ping"
    ADMIN_REINDEX = "internal/admin/reindex"
    ADMIN_SERVER = "internal/admin/server"
    ADMIN_SETTINGS = "internal/admin/settings"
    ADMIN_STATEMENTS_EXTENSION_EXISTS = "internal/admin/statements_extension_exists"
    ADMIN_TABLE_STATS = "internal/admin/table_stats"
    ADMIN_TOP_QUERIES = "internal/admin/top_queries"
    ADMIN_UNUSED_INDEXES = "internal/admin/unused_indexes"
    ADMIN_VACUUM = "internal/admin/vacuum"
    DIAGNOSTIC_HEALTH_CACHE_HIT_RATIO = "diagnostics/health.cache_hit_ratio", QueryAccess.ADMIN
    DIAGNOSTIC_HEALTH_CHECKPOINTS = "diagnostics/health.checkpoints", QueryAccess.ADMIN
    DIAGNOSTIC_HEALTH_CONNECTIONS = "diagnostics/health.connections", QueryAccess.ADMIN
    DIAGNOSTIC_HEALTH_IDLE_IN_TRANSACTION = "diagnostics/health.idle_in_transaction", QueryAccess.ADMIN
    DIAGNOSTIC_HEALTH_LOCK_WAITS = "diagnostics/health.lock_waits", QueryAccess.ADMIN
    DIAGNOSTIC_HEALTH_LONG_RUNNING = "diagnostics/health.long_running", QueryAccess.ADMIN
    DIAGNOSTIC_HEALTH_REPLICATION = "diagnostics/health.replication", QueryAccess.ADMIN
    DIAGNOSTIC_INDEX_DUPLICATES = "diagnostics/index.duplicates", QueryAccess.ADMIN
    DIAGNOSTIC_INDEX_MISSING_FK = "diagnostics/index.missing_fk", QueryAccess.ADMIN
    DIAGNOSTIC_INDEX_UNUSED = "diagnostics/index.unused", QueryAccess.ADMIN
    DIAGNOSTIC_INDEX_USAGE_BY_TABLE = "diagnostics/index.usage_by_table", QueryAccess.ADMIN
    DIAGNOSTIC_MAINTENANCE_BLOAT = "diagnostics/maintenance.bloat", QueryAccess.ADMIN
    DIAGNOSTIC_MAINTENANCE_STALE_STATS = "diagnostics/maintenance.stale_stats", QueryAccess.ADMIN
    DIAGNOSTIC_MAINTENANCE_VACUUM_NEEDED = "diagnostics/maintenance.vacuum_needed", QueryAccess.ADMIN
    DIAGNOSTIC_MAINTENANCE_WRAPAROUND = "diagnostics/maintenance.wraparound", QueryAccess.ADMIN
    DIAGNOSTIC_SCHEMA_COLUMNS_BY_TYPE = "diagnostics/schema.columns_by_type", QueryAccess.ADMIN
    DIAGNOSTIC_SCHEMA_DEPENDENCIES = "diagnostics/schema.dependencies", QueryAccess.ADMIN
    DIAGNOSTIC_SCHEMA_NO_PRIMARY_KEY = "diagnostics/schema.no_primary_key", QueryAccess.ADMIN
    DIAGNOSTIC_SCHEMA_SEQUENCES_NEAR_LIMIT = "diagnostics/schema.sequences_near_limit", QueryAccess.ADMIN
    DIAGNOSTIC_SECURITY_EXPIRING_ROLES = "diagnostics/security.expiring_roles", QueryAccess.ADMIN
    DIAGNOSTIC_SECURITY_PUBLIC_GRANTS = "diagnostics/security.public_grants", QueryAccess.ADMIN
    DIAGNOSTIC_SECURITY_RLS_STATUS = "diagnostics/security.rls_status", QueryAccess.ADMIN
    DIAGNOSTIC_SECURITY_SUPERUSERS = "diagnostics/security.superusers", QueryAccess.ADMIN
    DIAGNOSTIC_SIZE_DATABASE = "diagnostics/size.database", QueryAccess.ADMIN
    DIAGNOSTIC_SIZE_INDEXES = "diagnostics/size.indexes", QueryAccess.ADMIN
    DIAGNOSTIC_SIZE_SCHEMAS = "diagnostics/size.schemas", QueryAccess.ADMIN
    DIAGNOSTIC_SIZE_TABLES = "diagnostics/size.tables", QueryAccess.ADMIN
    DIAGNOSTIC_STATEMENTS_MOST_CALLED = "diagnostics/statements.most_called", QueryAccess.ADMIN
    DIAGNOSTIC_STATEMENTS_TEMP_HEAVY = "diagnostics/statements.temp_heavy", QueryAccess.ADMIN
    DIAGNOSTIC_STATEMENTS_TOP_MEAN_TIME = "diagnostics/statements.top_mean_time", QueryAccess.ADMIN
    DIAGNOSTIC_STATEMENTS_TOP_TOTAL_TIME = "diagnostics/statements.top_total_time", QueryAccess.ADMIN
    ENGINE_LOCAL_READ_ONLY = "internal/engine/local_read_only"
    ENGINE_META = "internal/engine/meta"
    ENGINE_RESET_ROLE = "internal/engine/reset_role"
    ENGINE_SET_LOCAL_ROLE = "internal/engine/set_local_role"
    ENGINE_SET_ROLE = "internal/engine/set_role"
    ENGINE_TRANSACTION_READ_ONLY = "internal/engine/transaction_read_only"
    EVENTS_CREATE_TRIGGER = "internal/events/create_trigger"
    EVENTS_DROP_TRIGGER = "internal/events/drop_trigger"
    EVENTS_LISTEN = "internal/events/listen"
    EVENTS_NOTIFY = "internal/events/notify"
    EVENTS_NOTIFY_FN = "internal/events/notify_fn"
    EVENTS_WATCHES = "internal/events/watches"
    LIBRARY_ROWS_COUNT_BY_DAY = "library/rows.count_by_day", QueryAccess.PUBLIC
    LIBRARY_ROWS_DISTINCT_VALUES = "library/rows.distinct_values", QueryAccess.PUBLIC
    LIBRARY_ROWS_DUPLICATES = "library/rows.duplicates", QueryAccess.PUBLIC
    LIBRARY_ROWS_ORPHANS = "library/rows.orphans", QueryAccess.PUBLIC
    LIBRARY_ROWS_RECENT = "library/rows.recent", QueryAccess.PUBLIC
    LIBRARY_ROWS_SINCE = "library/rows.since", QueryAccess.PUBLIC
    LIBRARY_TABLE_COLUMN_STATS = "library/table.column_stats", QueryAccess.PUBLIC
    LIBRARY_TABLE_FOREIGN_KEYS = "library/table.foreign_keys", QueryAccess.PUBLIC
    LIBRARY_TABLE_INDEX_USAGE = "library/table.index_usage", QueryAccess.PUBLIC
    LIFECYCLE_ADD_EXPIRY_COLUMN = "internal/lifecycle/add_expiry_column"
    LIFECYCLE_CREATE_ARCHIVE = "internal/lifecycle/create_archive"
    LIFECYCLE_CRON = "internal/lifecycle/cron"
    LIFECYCLE_CRON_EXTENSION_EXISTS = "internal/lifecycle/cron_extension_exists"
    LIFECYCLE_EXPIRY_TIME = "internal/lifecycle/expiry_time"
    LIFECYCLE_GET = "internal/lifecycle/get"
    LIFECYCLE_INSTALL = "internal/lifecycle/install"
    LIFECYCLE_INSTALLED = "internal/lifecycle/installed"
    LIFECYCLE_LIST = "internal/lifecycle/list"
    LIFECYCLE_PREVIEW_EXPIRY = "internal/lifecycle/preview_expiry"
    LIFECYCLE_PREVIEW_ROWS = "internal/lifecycle/preview_rows"
    LIFECYCLE_REMOVE = "internal/lifecycle/remove"
    LIFECYCLE_RUN = "internal/lifecycle/run"
    LIFECYCLE_RUNS = "internal/lifecycle/runs"
    LIFECYCLE_SCHEDULE = "internal/lifecycle/schedule"
    LIFECYCLE_SCHEDULED_COMMAND = "internal/lifecycle/scheduled_command"
    LIFECYCLE_UNSCHEDULE = "internal/lifecycle/unschedule"
    LIFECYCLE_UPSERT = "internal/lifecycle/upsert"
    QUERIES_EXTENSION_EXISTS = "internal/queries/extension_exists"
    ROLES_ALTER = "internal/roles/alter"
    ROLES_COMMENT = "internal/roles/comment"
    ROLES_CREATE = "internal/roles/create"
    ROLES_DROP = "internal/roles/drop"
    ROLES_DROP_OWNED = "internal/roles/drop_owned"
    ROLES_EXISTS = "internal/roles/exists"
    ROLES_LIST = "internal/roles/list"
    ROLES_MEMBERSHIP_GRANT = "internal/roles/membership_grant"
    ROLES_MEMBERSHIP_REVOKE = "internal/roles/membership_revoke"
    ROLES_OPTIONS = "internal/roles/options"
    ROLES_PRIVILEGE_GRANT = "internal/roles/privilege_grant"
    ROLES_PRIVILEGE_REVOKE = "internal/roles/privilege_revoke"
    ROLES_REASSIGN_OWNED = "internal/roles/reassign_owned"
    ROLES_RENAME = "internal/roles/rename"
    ROLES_SCHEMA_PRIVS = "internal/roles/schema_privs"
    ROLES_SET_PASSWORD = "internal/roles/set_password"
    ROLES_TABLE_PRIVS = "internal/roles/table_privs"
    ROWS_AGGREGATE = "internal/rows/aggregate"
    ROWS_COUNT = "internal/rows/count"
    ROWS_DELETE = "internal/rows/delete"
    ROWS_EXISTS = "internal/rows/exists"
    ROWS_EXPLAIN = "internal/rows/explain"
    ROWS_EXPORT_CSV = "internal/rows/export_csv"
    ROWS_IMPORT_CSV = "internal/rows/import_csv"
    ROWS_INSERT = "internal/rows/insert"
    ROWS_INSERT_DEFAULTS = "internal/rows/insert_defaults"
    ROWS_SELECT = "internal/rows/select"
    ROWS_UPDATE = "internal/rows/update"
    SCHEMA_AVAILABLE = "internal/schema/available"
    SCHEMA_COLUMNS = "internal/schema/columns"
    SCHEMA_COLUMN_ADD = "internal/schema/column_add"
    SCHEMA_COLUMN_ALTER = "internal/schema/column_alter"
    SCHEMA_COLUMN_DROP = "internal/schema/column_drop"
    SCHEMA_COLUMN_DROP_DEFAULT = "internal/schema/column_drop_default"
    SCHEMA_COLUMN_NULLABLE = "internal/schema/column_nullable"
    SCHEMA_COLUMN_RENAME = "internal/schema/column_rename"
    SCHEMA_COLUMN_SET_DEFAULT = "internal/schema/column_set_default"
    SCHEMA_COLUMN_TYPE = "internal/schema/column_type"
    SCHEMA_COMMENT = "internal/schema/comment"
    SCHEMA_CONSTRAINTS = "internal/schema/constraints"
    SCHEMA_CONSTRAINT_ADD = "internal/schema/constraint_add"
    SCHEMA_CONSTRAINT_DROP = "internal/schema/constraint_drop"
    SCHEMA_DATABASES = "internal/schema/databases"
    SCHEMA_EXTENSIONS = "internal/schema/extensions"
    SCHEMA_EXTENSION_CREATE = "internal/schema/extension_create"
    SCHEMA_EXTENSION_DROP = "internal/schema/extension_drop"
    SCHEMA_INDEXES = "internal/schema/indexes"
    SCHEMA_INDEX_CREATE = "internal/schema/index_create"
    SCHEMA_INDEX_DROP = "internal/schema/index_drop"
    SCHEMA_SCHEMAS = "internal/schema/schemas"
    SCHEMA_SCHEMA_CREATE = "internal/schema/schema_create"
    SCHEMA_SCHEMA_DROP = "internal/schema/schema_drop"
    SCHEMA_TABLES = "internal/schema/tables"
    SCHEMA_TABLE_CREATE = "internal/schema/table_create"
    SCHEMA_TABLE_DROP = "internal/schema/table_drop"
    SCHEMA_TABLE_RENAME = "internal/schema/table_rename"
    SCHEMA_TABLE_TRUNCATE = "internal/schema/table_truncate"
    SCHEMA_VIEW_CREATE = "internal/schema/view_create"
    SCHEMA_VIEW_DEFINITION = "internal/schema/view_definition"
    SCHEMA_VIEW_DROP = "internal/schema/view_drop"
    SCHEMA_VIEW_REFRESH = "internal/schema/view_refresh"

    def __new__(cls, resource: QueryResourcePath, access: QueryAccess = QueryAccess.INTERNAL) -> Statement:
        member = str.__new__(cls, resource)
        member._value_ = resource
        member._access = access
        return member

    _access: QueryAccess

    @property
    def access(self) -> QueryAccess:
        return self._access

    @property
    def query_name(self) -> QueryName:
        return self.value.rpartition("/")[2]

    @property
    def text(self) -> QuerySql:
        return _load(self).text

    @property
    def sql(self) -> sql.SQL:
        return sql.SQL(self.text)


class SqlResourceRequest(BaseModel):
    model_config = CONTRACT_CONFIG

    statement: Statement


class SqlResourceResponse(BaseModel):
    model_config = CONTRACT_CONFIG

    text: QuerySql


@cache
def _load(statement: Statement) -> SqlResourceResponse:
    request = SqlResourceRequest(statement=statement)
    content = (
        resources.files("pgfacade.infrastructure.postgres.queries")
        .joinpath("sql", f"{request.statement.value}.sql")
        .read_text(encoding="utf-8")
    )
    return SqlResourceResponse(text=content)
