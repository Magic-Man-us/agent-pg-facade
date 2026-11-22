from __future__ import annotations

from enum import StrEnum, unique


@unique
class Operation(StrEnum):
    BATCH_RUN = "batch.run"
    COLUMN_ADD = "column.add"
    COLUMN_ALTER = "column.alter"
    COLUMN_DROP = "column.drop"
    COLUMN_RENAME = "column.rename"
    CONSTRAINT_ADD = "constraint.add"
    CONSTRAINT_DROP = "constraint.drop"
    DATABASE_LIST = "database.list"
    DIAG_ACTIVITY = "diag.activity"
    DIAG_LOCKS = "diag.locks"
    DIAG_TABLE_STATS = "diag.table_stats"
    DIAG_TOP_QUERIES = "diag.top_queries"
    DIAG_UNUSED_INDEXES = "diag.unused_indexes"
    EVENT_NOTIFY = "event.notify"
    EVENT_UNWATCH = "event.unwatch"
    EVENT_WAIT = "event.wait"
    EVENT_WATCH = "event.watch"
    EVENT_WATCHES = "event.watches"
    EXTENSION_CREATE = "extension.create"
    EXTENSION_DROP = "extension.drop"
    EXTENSION_LIST = "extension.list"
    INDEX_CREATE = "index.create"
    INDEX_DROP = "index.drop"
    LIFECYCLE_INSTALL = "lifecycle.install"
    LIFECYCLE_LIST = "lifecycle.list"
    LIFECYCLE_PREVIEW = "lifecycle.preview"
    LIFECYCLE_REMOVE = "lifecycle.remove"
    LIFECYCLE_ROW_TTL = "lifecycle.row_ttl"
    LIFECYCLE_RUN = "lifecycle.run"
    LIFECYCLE_RUNS = "lifecycle.runs"
    LIFECYCLE_SCHEDULE = "lifecycle.schedule"
    LIFECYCLE_TABLE_EXPIRY = "lifecycle.table_expiry"
    MAINT_ANALYZE = "maint.analyze"
    MAINT_BACKEND = "maint.backend"
    MAINT_REINDEX = "maint.reindex"
    MAINT_VACUUM = "maint.vacuum"
    MEMBERSHIP_GRANT = "membership.grant"
    MEMBERSHIP_REVOKE = "membership.revoke"
    MIGRATION_HISTORY = "migration.history"
    MIGRATION_INIT = "migration.init"
    MIGRATION_REVISION = "migration.revision"
    MIGRATION_RUN = "migration.run"
    MIGRATION_STATUS = "migration.status"
    PRIVILEGE_GRANT = "privilege.grant"
    PRIVILEGE_LIST = "privilege.list"
    PRIVILEGE_REVOKE = "privilege.revoke"
    QUERY_LIST = "query.list"
    QUERY_RELOAD = "query.reload"
    QUERY_RUN = "query.run"
    ROLE_ALTER = "role.alter"
    ROLE_CREATE = "role.create"
    ROLE_DROP = "role.drop"
    ROLE_GET = "role.get"
    ROLE_LIST = "role.list"
    ROLE_SET_PASSWORD = "role.set_password"
    ROWS_AGGREGATE = "rows.aggregate"
    ROWS_COUNT = "rows.count"
    ROWS_DELETE = "rows.delete"
    ROWS_EXISTS = "rows.exists"
    ROWS_EXPORT_CSV = "rows.export_csv"
    ROWS_GET = "rows.get"
    ROWS_IMPORT_CSV = "rows.import_csv"
    ROWS_INSERT = "rows.insert"
    ROWS_SELECT = "rows.select"
    ROWS_UPDATE = "rows.update"
    SCHEMA_CREATE = "schema.create"
    SCHEMA_DROP = "schema.drop"
    SCHEMA_LIST = "schema.list"
    SERVER_HEALTH = "server.health"
    SERVER_INFO = "server.info"
    SERVER_SETTINGS = "server.settings"
    SERVER_WHOAMI = "server.whoami"
    SQL_EXECUTE = "sql.execute"
    SQL_EXPLAIN = "sql.explain"
    SQL_QUERY = "sql.query"
    TABLE_COMMENT = "table.comment"
    TABLE_CREATE = "table.create"
    TABLE_DESCRIBE = "table.describe"
    TABLE_DROP = "table.drop"
    TABLE_LIST = "table.list"
    TABLE_RENAME = "table.rename"
    TABLE_TRUNCATE = "table.truncate"
    VIEW_CREATE = "view.create"
    VIEW_DROP = "view.drop"
    VIEW_REFRESH = "view.refresh"


@unique
class Outcome(StrEnum):
    SUCCESS = "success"
    ERROR = "error"


@unique
class ErrorCode(StrEnum):
    INVALID_REQUEST = "invalid_request"
    UNAUTHENTICATED = "unauthenticated"
    FORBIDDEN = "forbidden"
    NOT_FOUND = "not_found"
    METHOD_NOT_ALLOWED = "method_not_allowed"
    TIMEOUT = "timeout"
    CONFLICT = "conflict"
    REQUEST_TOO_LARGE = "request_too_large"
    VALIDATION_ERROR = "validation_error"
    UNAVAILABLE = "unavailable"
    INTERNAL_ERROR = "internal_error"


@unique
class StreamOperation(StrEnum):
    EVENT_STREAM = "event.stream"


@unique
class OperationHint(StrEnum):
    READ = "read"
    WRITE = "write"
    DESTRUCTIVE = "destructive"


@unique
class ParamType(StrEnum):
    INTEGER = "int"
    FLOAT = "float"
    TEXT = "text"
    BOOLEAN = "bool"
    TABLE = "table"
    COLUMN = "column"
    IDENTIFIER = "identifier"


@unique
class ErrorReason(StrEnum):
    CREDENTIAL_MISSING = "credential_missing"
    CREDENTIAL_INVALID = "credential_invalid"
    AUTHENTICATION_UNCONFIGURED = "authentication_unconfigured"
    IDENTITY_PROVIDER_UNCONFIGURED = "identity_provider_unconfigured"
    IDENTITY_PROVIDER_INVALID_RESPONSE = "identity_provider_invalid_response"
    IDENTITY_PROVIDER_UNAVAILABLE = "identity_provider_unavailable"
    POLICY_DENIED = "policy_denied"
    POLICY_NO_MATCH = "policy_no_match"
    IDENTITY_AMBIGUOUS = "identity_ambiguous"
    REQUEST_INVALID = "request_invalid"
    INPUT_INVALID = "input_invalid"
    RESPONSE_INVALID = "response_invalid"
    RESOURCE_NOT_FOUND = "resource_not_found"
    REQUEST_TIMEOUT = "request_timeout"
    REQUEST_TOO_LARGE = "request_too_large"
    METHOD_NOT_ALLOWED = "method_not_allowed"
    DATABASE_CONFLICT = "database_conflict"
    DATABASE_CONSTRAINT_VIOLATION = "database_constraint_violation"
    DATABASE_RESOURCE_NOT_FOUND = "database_resource_not_found"
    DATABASE_PERMISSION_DENIED = "database_permission_denied"
    DATABASE_TIMEOUT = "database_timeout"
    DATABASE_UNAVAILABLE = "database_unavailable"
    DATABASE_FAILURE = "database_failure"
    UNEXPECTED_FAILURE = "unexpected_failure"


@unique
class ErrorDetailKind(StrEnum):
    VALIDATION = "validation"
    DATABASE = "database"
    AUTHENTICATION = "authentication"
    AUTHORIZATION = "authorization"


@unique
class ValidationOrigin(StrEnum):
    REQUEST = "request"
    RESPONSE = "response"


@unique
class ValidationContextKind(StrEnum):
    TAG = "tag"
    BOUNDS = "bounds"


@unique
class ValidationConstraintKind(StrEnum):
    GT = "gt"
    GE = "ge"
    LT = "lt"
    LE = "le"
    MULTIPLE_OF = "multiple_of"
    MIN_LENGTH = "min_length"
    MAX_LENGTH = "max_length"
    EXPECTED_LENGTH = "expected_length"
    ACTUAL_LENGTH = "actual_length"
    MAX_DIGITS = "max_digits"
    DECIMAL_PLACES = "decimal_places"
    WHOLE_DIGITS = "whole_digits"


@unique
class DatabaseErrorCategory(StrEnum):
    CONFLICT = "conflict"
    CONSTRAINT = "constraint"
    NOT_FOUND = "not_found"
    PERMISSION = "permission"
    TIMEOUT = "timeout"
    UNAVAILABLE = "unavailable"
    FAILURE = "failure"


@unique
class KnownValidationCode(StrEnum):
    MISSING = "missing"
    EXTRA_FORBIDDEN = "extra_forbidden"
    UNION_TAG_INVALID = "union_tag_invalid"
    UNION_TAG_NOT_FOUND = "union_tag_not_found"
    LITERAL_ERROR = "literal_error"
    ENUM = "enum"
    INT_TYPE = "int_type"
    INT_PARSING = "int_parsing"
    INT_FROM_FLOAT = "int_from_float"
    FLOAT_TYPE = "float_type"
    FLOAT_PARSING = "float_parsing"
    BOOL_TYPE = "bool_type"
    BOOL_PARSING = "bool_parsing"
    STRING_TYPE = "string_type"
    STRING_PATTERN_MISMATCH = "string_pattern_mismatch"
    LIST_TYPE = "list_type"
    TUPLE_TYPE = "tuple_type"
    DICT_TYPE = "dict_type"
    MODEL_TYPE = "model_type"
    FINITE_NUMBER = "finite_number"
    JSON_INVALID = "json_invalid"


@unique
class FilterKind(StrEnum):
    CMP = "cmp"
    IN = "in"
    IS_NULL = "is_null"
    BETWEEN = "between"
    CONTAINS = "contains"
    TEXT_SEARCH = "text_search"
    AND = "and"
    OR = "or"
    NOT = "not"


@unique
class CmpOp(StrEnum):
    EQ = "eq"
    NE = "ne"
    LT = "lt"
    LTE = "lte"
    GT = "gt"
    GTE = "gte"
    LIKE = "like"
    ILIKE = "ilike"
    NOT_LIKE = "not_like"
    NOT_ILIKE = "not_ilike"
    REGEX = "regex"
    IREGEX = "iregex"


@unique
class TextSearchMode(StrEnum):
    WEBSEARCH = "websearch"
    PLAIN = "plain"
    PHRASE = "phrase"


@unique
class NullOrder(StrEnum):
    FIRST = "first"
    LAST = "last"


@unique
class AggregateFunction(StrEnum):
    COUNT = "count"
    COUNT_DISTINCT = "count_distinct"
    SUM = "sum"
    AVG = "avg"
    MIN = "min"
    MAX = "max"


@unique
class ConflictKind(StrEnum):
    DO_NOTHING = "do_nothing"
    DO_UPDATE = "do_update"


@unique
class BackendAction(StrEnum):
    CANCEL = "cancel"
    TERMINATE = "terminate"


@unique
class MaintenanceKind(StrEnum):
    TABLE = "table"
    INDEX = "index"
    SCHEMA = "schema"


@unique
class Privilege(StrEnum):
    SELECT = "select"
    INSERT = "insert"
    UPDATE = "update"
    DELETE = "delete"
    TRUNCATE = "truncate"
    REFERENCES = "references"
    TRIGGER = "trigger"
    USAGE = "usage"
    CREATE = "create"
    CONNECT = "connect"
    TEMPORARY = "temporary"
    EXECUTE = "execute"
    ALL = "all"


@unique
class GrantTarget(StrEnum):
    TABLE = "table"
    SEQUENCE = "sequence"
    SCHEMA = "schema"
    DATABASE = "database"
    FUNCTION = "function"
    ALL_TABLES_IN_SCHEMA = "all_tables_in_schema"
    ALL_SEQUENCES_IN_SCHEMA = "all_sequences_in_schema"
    ALL_FUNCTIONS_IN_SCHEMA = "all_functions_in_schema"


@unique
class OnDelete(StrEnum):
    CASCADE = "cascade"
    RESTRICT = "restrict"
    SET_NULL = "set null"
    SET_DEFAULT = "set default"
    NO_ACTION = "no action"


@unique
class TableOrder(StrEnum):
    NAME = "name"
    SIZE = "size"


@unique
class ConstraintKind(StrEnum):
    UNIQUE = "unique"
    PRIMARY_KEY = "primary_key"
    FOREIGN_KEY = "foreign_key"
    CHECK = "check"


@unique
class IndexMethod(StrEnum):
    BTREE = "btree"
    HASH = "hash"
    GIN = "gin"
    GIST = "gist"
    BRIN = "brin"


@unique
class LifecycleKind(StrEnum):
    ROW_TTL = "row_ttl"
    TABLE_EXPIRY = "table_expiry"


@unique
class LifecycleAction(StrEnum):
    DELETE = "delete"
    ARCHIVE = "archive"
    TRUNCATE = "truncate"
    DROP = "drop"


@unique
class DefaultExpr(StrEnum):
    NOW = "now()"
    CURRENT_TIMESTAMP = "current_timestamp"
    CURRENT_DATE = "current_date"
    GEN_RANDOM_UUID = "gen_random_uuid()"


@unique
class WatchEvent(StrEnum):
    INSERT = "insert"
    UPDATE = "update"
    DELETE = "delete"


@unique
class MigrationAction(StrEnum):
    UPGRADE = "upgrade"
    DOWNGRADE = "downgrade"
    STAMP = "stamp"


@unique
class OperationStatus(StrEnum):
    INSTALLED = "INSTALLED"
    SCHEDULED = "SCHEDULED"
    RELOADED = "RELOADED"


@unique
class RelationType(StrEnum):
    TABLE = "table"
    PARTITIONED_TABLE = "partitioned_table"
    VIEW = "view"
    MATERIALIZED_VIEW = "materialized_view"
    FOREIGN_TABLE = "foreign_table"
    INDEX = "i"
    SEQUENCE = "S"
    TOAST = "t"
    COMPOSITE = "c"
    PARTITIONED_INDEX = "I"


@unique
class ConstraintType(StrEnum):
    PRIMARY_KEY = "primary_key"
    FOREIGN_KEY = "foreign_key"
    UNIQUE = "unique"
    CHECK = "check"
    EXCLUSION = "exclusion"
    NOT_NULL = "not_null"
    TRIGGER = "t"


@unique
class SettingContext(StrEnum):
    INTERNAL = "internal"
    POSTMASTER = "postmaster"
    SIGHUP = "sighup"
    SUPERUSER_BACKEND = "superuser-backend"
    BACKEND = "backend"
    SUPERUSER = "superuser"
    USER = "user"


@unique
class GrantedPrivilege(StrEnum):
    SELECT = "SELECT"
    INSERT = "INSERT"
    UPDATE = "UPDATE"
    DELETE = "DELETE"
    TRUNCATE = "TRUNCATE"
    REFERENCES = "REFERENCES"
    TRIGGER = "TRIGGER"
    CREATE = "CREATE"
    CONNECT = "CONNECT"
    TEMPORARY = "TEMPORARY"
    EXECUTE = "EXECUTE"
    USAGE = "USAGE"
    SET = "SET"
    ALTER_SYSTEM = "ALTER SYSTEM"
    MAINTAIN = "MAINTAIN"
