# Tool reference

One tool per operation. A tool is registered only when the server permits its capability.

| Needs | Enabled by |
|---|---|
| read | always |
| write | read-only turned off |
| raw | `PGFACADE_ALLOW_RAW_SQL=true` |
| ddl | `PGFACADE_ALLOW_DDL=true` |
| admin | `PGFACADE_ALLOW_ADMIN=true` |
| migrate | `PGFACADE_ALLOW_MIGRATE=true` |
| listen | `PGFACADE_ALLOW_LISTEN=true` |

A tool that needs several capabilities needs all of them.

## batch

| Tool | Needs | Input | Returns | Purpose |
|---|---|---|---|---|
| `pg_batch_run` | read | `requests` (required) | `BatchResult` | Run several requests in order inside one transaction; any failure rolls back all of them. |

## server

| Tool | Needs | Input | Returns | Purpose |
|---|---|---|---|---|
| `pg_server_health` | read | none | `Health` | Round-trip latency and pool statistics. |
| `pg_server_info` | read | none | `ServerInfo` | Version, database, user and session role, uptime start, size, connections. |
| `pg_server_whoami` | read | none | `WhoAmI` | The principal this call runs as and its effective permissions. |
| `pg_server_settings` | admin | `pattern`, `limit` | `SettingInfoList` | pg_settings matching an ILIKE pattern, e.g. 'work_mem' or '%timeout%'. |

## diag

| Tool | Needs | Input | Returns | Purpose |
|---|---|---|---|---|
| `pg_diag_activity` | admin | `include_idle` | `QueryResult` | Client sessions from pg_stat_activity. |
| `pg_diag_locks` | admin | none | `QueryResult` | Blocked sessions paired with the sessions blocking them. |
| `pg_diag_top_queries` | admin | `limit` | `QueryResult` | Most expensive statements by total time (needs pg_stat_statements). |
| `pg_diag_table_stats` | admin | `schema_name`, `limit` | `QueryResult` | Live/dead rows, scans, writes, last vacuum/analyze per table. |
| `pg_diag_unused_indexes` | admin | `limit` | `QueryResult` | Non-unique indexes with zero scans since stats reset, largest first. |

## maint

| Tool | Needs | Input | Returns | Purpose |
|---|---|---|---|---|
| `pg_maint_backend` | admin | `action` (required), `pid` (required) | `Flag` | Cancel a backend's running query, or terminate its connection. |
| `pg_maint_vacuum` | write, admin | `table`, `full`, `analyze` | `Done` | VACUUM [FULL] [ANALYZE]; table=null means the whole database. |
| `pg_maint_analyze` | write, admin | `table` | `Done` | ANALYZE; table=null means the whole database. |
| `pg_maint_reindex` | write, admin | `kind` (required), `name` (required), `concurrently` | `Done` | REINDEX a table, index, or schema. |

## event

| Tool | Needs | Input | Returns | Purpose |
|---|---|---|---|---|
| `pg_event_notify` | write, listen | `channel` (required), `payload` | `Done` | pg_notify(channel, payload); delivered to listeners on commit. |
| `pg_event_wait` | listen | `channels` (required), `timeout_s`, `max_events` | `NotificationList` | Block up to timeout_s for notifications on channels (one-shot; for streaming use the SSE endpoint). |
| `pg_event_watch` | write, admin, listen | `table` (required), `events`, `channel`, `columns` | `WatchInfo` | Install a trigger that NOTIFYs a JSON change record for inserts/updates/deletes on a table. |
| `pg_event_unwatch` | write, admin, listen | `table` (required) | `Done` | Remove the change trigger from a table. |
| `pg_event_watches` | listen | none | `WatchInfoList` | Tables with change triggers installed. |

## lifecycle

| Tool | Needs | Input | Returns | Purpose |
|---|---|---|---|---|
| `pg_lifecycle_install` | write, admin | none | `Done` | Create the _pgfacade schema, policy table, and run_lifecycle() function (idempotent). |
| `pg_lifecycle_list` | admin | none | `LifecyclePolicyList` | All policies with last run outcome. |
| `pg_lifecycle_row_ttl` | write, admin | `table` (required), `column` (required), `ttl`, `action`, `archive_table`, `batch_size`, `add_column`, `enabled` | `RowTtlPolicy` | Expire rows once a timestamp column is older than ttl (or past, when ttl is null): delete them or move them to an archive. |
| `pg_lifecycle_table_expiry` | write, admin | `table` (required), `expires_at`, `expires_in`, `action`, `enabled` | `TableExpiryPolicy` | Truncate or drop a whole table at a point in time (or after an interval from now). |
| `pg_lifecycle_preview` | admin | `policy_id` (required) | `Count` | Count the rows a policy would touch right now, without changing anything. |
| `pg_lifecycle_remove` | write, admin | `policy_id` (required) | `Done` | Delete a policy by id. |
| `pg_lifecycle_run` | write, admin | `policy_id` | `LifecycleRunReport` | Apply one policy (or all) now. |
| `pg_lifecycle_runs` | admin | `policy_id`, `limit` | `LifecycleRunList` | Run history, newest first (kept for 30 days). |
| `pg_lifecycle_schedule` | write, admin | `cron` | `Done` | Schedule run_lifecycle() in pg_cron (cron expression), or unschedule with null. |

## migration

| Tool | Needs | Input | Returns | Purpose |
|---|---|---|---|---|
| `pg_migration_status` | migrate | none | `MigrationStatus` | Alembic state: current revision(s), heads, pending. |
| `pg_migration_init` | write, migrate | none | `MigrationStatus` | Create the migrations directory (env.py, versions/) if missing. |
| `pg_migration_history` | migrate | none | `RevisionInfoList` | All revisions oldest first with applied flags. |
| `pg_migration_revision` | write, migrate | `message` (required), `upgrade_sql`, `downgrade_sql` | `RevisionInfo` | Write a new revision file; SQL bodies are embedded as op.execute(). |
| `pg_migration_run` | write, migrate | `action` (required), `target` | `MigrationOutcome` | upgrade (default head), downgrade (default -1), or stamp (default head). |

## query

| Tool | Needs | Input | Returns | Purpose |
|---|---|---|---|---|
| `pg_query_list` | read | `category` | `QueryInfoList` | Catalog of curated queries with their parameters. |
| `pg_query_run` | read | `name` (required), `params`, `limit` | `QueryResult` | Run a curated query by name (rolled back, READ ONLY; needs no raw-SQL permission). |
| `pg_query_reload` | write | none | `Done` | Re-read the bundled library and PGFACADE_QUERIES_DIR *.sql files. |

## role

| Tool | Needs | Input | Returns | Purpose |
|---|---|---|---|---|
| `pg_role_list` | read | `include_system` | `RoleInfoList` | Roles (users) with attributes and memberships. |
| `pg_role_get` | read | `name` (required) | `RoleInfo` | One role with flags, limits, expiry, member_of and members. |
| `pg_role_create` | write, admin | `name` (required), `password`, `login`, `superuser`, `createdb`, `createrole`, `inherit`, `replication`, `bypassrls`, `connection_limit`, `valid_until`, `in_roles`, `comment` | `RoleInfo` | CREATE ROLE; login=true makes a user. Password is SCRAM-hashed client-side. |
| `pg_role_alter` | write, admin | `name` (required), `password`, `login`, `superuser`, `createdb`, `createrole`, `inherit`, `replication`, `bypassrls`, `connection_limit`, `valid_until`, `clear_valid_until`, `rename_to`, `comment` | `RoleInfo` | ALTER ROLE: only set fields change. |
| `pg_role_set_password` | write, admin | `name` (required), `password` (required) | `Done` | ALTER ROLE ... PASSWORD (SCRAM-hashed client-side). |
| `pg_role_drop` | write, admin | `name` (required), `if_exists`, `reassign_to` | `Done` | DROP ROLE; reassign_to moves owned objects to another role first (current database only). |

## membership

| Tool | Needs | Input | Returns | Purpose |
|---|---|---|---|---|
| `pg_membership_grant` | write, admin | `role` (required), `members` (required), `admin_option` | `Done` | GRANT group role TO members. |
| `pg_membership_revoke` | write, admin | `role` (required), `members` (required), `admin_option` | `Done` | REVOKE group role FROM members. |

## privilege

| Tool | Needs | Input | Returns | Purpose |
|---|---|---|---|---|
| `pg_privilege_grant` | write, admin | `privileges` (required), `on` (required), `target` (required), `roles` (required), `with_grant_option` | `Done` | GRANT privileges on an object (or ALL ... IN SCHEMA) to roles. |
| `pg_privilege_revoke` | write, admin | `privileges` (required), `on` (required), `target` (required), `roles` (required), `with_grant_option`, `cascade` | `Done` | REVOKE privileges (same shape as grant). |
| `pg_privilege_list` | read | `kind` (required), `target` (required) | `PrivilegeInfoList` | Who holds which privileges on a table or schema. |

## rows

| Tool | Needs | Input | Returns | Purpose |
|---|---|---|---|---|
| `pg_rows_select` | read | `order_by`, `limit`, `where`, `match`, `table` (required), `columns`, `offset`, `distinct`, `with_total` | `QueryResult` | Select rows with filters, ordering, and pagination. |
| `pg_rows_get` | read | `table` (required), `key` (required), `columns` | `Row` | Fetch one row by primary key (scalar for single-column keys, object for composite). |
| `pg_rows_count` | read | `where`, `match`, `table` (required) | `Count` | Count rows matching filters. |
| `pg_rows_exists` | read | `where`, `match`, `table` (required) | `Flag` | Whether any row matches the filters. |
| `pg_rows_aggregate` | read | `order_by`, `limit`, `where`, `match`, `table` (required), `aggregates` (required), `group_by` | `QueryResult` | count/count_distinct/sum/avg/min/max with optional GROUP BY; order_by may use aggregate names. |
| `pg_rows_insert` | write | `table` (required), `rows` (required), `on_conflict`, `returning` | `QueryResult` | Insert rows; on_conflict do_update = upsert, do_nothing = insert-ignore. |
| `pg_rows_update` | write | `where`, `match`, `table` (required), `values` (required), `returning`, `allow_all` | `QueryResult` | Update rows matching filters. Refused without filters unless allow_all. |
| `pg_rows_delete` | write | `where`, `match`, `table` (required), `returning`, `allow_all` | `QueryResult` | Delete rows matching filters. Refused without filters unless allow_all. |
| `pg_rows_export_csv` | read | `order_by`, `limit`, `where`, `match`, `table` (required), `columns`, `header` | `Text` | COPY matching rows to CSV text (capped by max_export_rows). |
| `pg_rows_import_csv` | write | `table` (required), `data` (required), `columns`, `header`, `delimiter` | `QueryResult` | COPY CSV text into a table. |

## sql

| Tool | Needs | Input | Returns | Purpose |
|---|---|---|---|---|
| `pg_sql_query` | raw | `sql` (required), `params` | `QueryResult` | Run ONE read-only statement in a READ ONLY transaction that is always rolled back. |
| `pg_sql_execute` | write, raw | `sql` (required), `params` | `QueryResult` | Run ONE write or DDL statement; auto-committed. |
| `pg_sql_explain` | raw | `sql` (required), `params`, `analyze` | `Plan` | EXPLAIN (FORMAT JSON); analyze executes inside a read-only, rolled-back transaction. |

## schema

| Tool | Needs | Input | Returns | Purpose |
|---|---|---|---|---|
| `pg_schema_list` | read | none | `SchemaInfoList` | Non-system schemas with owner and table counts. |
| `pg_schema_create` | write, ddl | `name` (required), `owner`, `if_not_exists` | `Done` | CREATE SCHEMA, optionally owned by another role. |
| `pg_schema_drop` | write, ddl | `name` (required), `if_exists`, `cascade` | `Done` | DROP SCHEMA; cascade drops everything inside. |

## table

| Tool | Needs | Input | Returns | Purpose |
|---|---|---|---|---|
| `pg_table_list` | read | `schema_name`, `order`, `limit` | `TableInfoList` | Tables, views and materialized views with owner, row estimate and size. |
| `pg_table_describe` | read | `table` (required) | `TableDetail` | Columns, primary key, constraints, indexes, and view definition. |
| `pg_table_create` | write, ddl | `table` (required), `columns` (required), `primary_key`, `if_not_exists`, `comment` | `Done` | CREATE TABLE. Column-level primary_key, or table-level primary_key for composite keys. |
| `pg_table_drop` | write, ddl | `table` (required), `if_exists`, `cascade` | `Done` | DROP TABLE. |
| `pg_table_rename` | write, ddl | `table` (required), `new_name` (required) | `Done` | Rename a table within its schema. |
| `pg_table_truncate` | write, ddl | `table` (required), `restart_identity`, `cascade` | `Done` | Remove all rows. |
| `pg_table_comment` | write, ddl | `table` (required), `comment` (required), `column` | `Done` | Set (or clear with null) the comment on a table or one column. |

## column

| Tool | Needs | Input | Returns | Purpose |
|---|---|---|---|---|
| `pg_column_add` | write, ddl | `table` (required), `column` (required), `if_not_exists` | `Done` | ALTER TABLE ADD COLUMN. |
| `pg_column_alter` | write, ddl | `table` (required), `column` (required), `type`, `using`, `default`, `default_expr`, `drop_default`, `nullable`, `comment` | `Done` | Change type (optionally with USING), default, nullability, or comment. |
| `pg_column_rename` | write, ddl | `table` (required), `column` (required), `new_name` (required) | `Done` | Rename a column. |
| `pg_column_drop` | write, ddl | `table` (required), `column` (required), `if_exists`, `cascade` | `Done` | Drop a column and its data. |

## constraint

| Tool | Needs | Input | Returns | Purpose |
|---|---|---|---|---|
| `pg_constraint_add` | write, ddl | one of several shapes selected by `kind`; see the tool schema | `Done` | Add a unique, primary key, foreign key, or check constraint. |
| `pg_constraint_drop` | write, ddl | `table` (required), `name` (required), `if_exists`, `cascade` | `Done` | Drop a constraint by name. |

## index

| Tool | Needs | Input | Returns | Purpose |
|---|---|---|---|---|
| `pg_index_create` | write, ddl | `table` (required), `columns` (required), `name`, `unique`, `method`, `concurrently`, `if_not_exists` | `Done` | CREATE INDEX (btree/hash/gin/gist/brin). gin suits jsonb, arrays, tsvector. |
| `pg_index_drop` | write, ddl | `index` (required), `if_exists`, `concurrently`, `cascade` | `Done` | DROP INDEX. |

## view

| Tool | Needs | Input | Returns | Purpose |
|---|---|---|---|---|
| `pg_view_create` | write, raw, ddl | `name` (required), `query` (required), `materialized`, `replace`, `with_data` | `Done` | CREATE [MATERIALIZED] VIEW from a SELECT (needs sql permission). |
| `pg_view_drop` | write, ddl | `name` (required), `materialized`, `if_exists`, `cascade` | `Done` | DROP [MATERIALIZED] VIEW. |
| `pg_view_refresh` | write | `name` (required), `concurrently` | `Done` | REFRESH MATERIALIZED VIEW; concurrently needs a unique index on the view. |

## extension

| Tool | Needs | Input | Returns | Purpose |
|---|---|---|---|---|
| `pg_extension_list` | read | `available` | `ExtensionInfoList` | Installed extensions, or with available=true everything the server could install. |
| `pg_extension_create` | write, ddl | `name` (required), `schema_name`, `version`, `cascade` | `Done` | CREATE EXTENSION IF NOT EXISTS. |
| `pg_extension_drop` | write, ddl | `name` (required), `if_exists`, `cascade` | `Done` | DROP EXTENSION. |

## database

| Tool | Needs | Input | Returns | Purpose |
|---|---|---|---|---|
| `pg_database_list` | read | none | `DatabaseInfoList` | Databases on this server with owner, encoding and size. |
