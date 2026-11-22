# Curated queries

Run with `pg_query_run`, passing `name` and `params`. Each runs read-only and is rolled back.
Queries marked admin need `PGFACADE_ALLOW_ADMIN=true`. `pg_query_list` returns the ones the current session may run.

## health

| Name | Needs | Parameters | Purpose |
|---|---|---|---|
| `health.cache_hit_ratio` | admin | none | Buffer cache hit ratio for heap and index reads (aim above 0.99) |
| `health.checkpoints` | admin | none | Checkpoint and background writer counters since the last stats reset |
| `health.connections` | admin | none | Connections by state and user against max_connections |
| `health.idle_in_transaction` | admin | `seconds` | Sessions idle inside an open transaction (they hold locks and block vacuum) |
| `health.lock_waits` | admin | none | Who is waiting on whom |
| `health.long_running` | admin | `seconds` | Client queries running longer than a threshold |
| `health.replication` | admin | none | Streaming replication clients and their lag (run on the primary) |

## index

| Name | Needs | Parameters | Purpose |
|---|---|---|---|
| `index.duplicates` | admin | none | Indexes with identical definitions apart from the name |
| `index.missing_fk` | admin | none | Foreign key columns without a supporting index (slow deletes and joins) |
| `index.unused` | admin | `limit` | Non-unique indexes with zero scans since the last stats reset |
| `index.usage_by_table` | admin | `min_rows`, `limit` | Sequential vs index scan ratio per table (large tables with many seq scans want indexes) |

## maintenance

| Name | Needs | Parameters | Purpose |
|---|---|---|---|
| `maintenance.bloat` | admin | `min_dead`, `limit` | Tables with the highest dead-tuple ratio (vacuum candidates) |
| `maintenance.stale_stats` | admin | `days`, `limit` | Tables never analyzed or not analyzed for a number of days |
| `maintenance.vacuum_needed` | admin | `limit` | Tables past autovacuum's threshold that have not been vacuumed yet |
| `maintenance.wraparound` | admin | none | Transaction ID age per database (freeze before autovacuum_freeze_max_age) |

## rows

| Name | Needs | Parameters | Purpose |
|---|---|---|---|
| `rows.count_by_day` | read | `table`, `column`, `days` | Row counts per day over the last N days |
| `rows.distinct_values` | read | `table`, `column`, `limit` | Distinct values of a column with their frequencies |
| `rows.duplicates` | read | `table`, `column`, `min_count` | Values that appear more than once in a column, largest groups first |
| `rows.orphans` | read | `table`, `column`, `parent`, `parent_column` | Child rows whose reference has no matching parent row |
| `rows.recent` | read | `table`, `column`, `limit` | Newest rows of a table by a timestamp column |
| `rows.since` | read | `table`, `since`, `column` | Rows whose timestamp column is at or after a point in time |

## schema

| Name | Needs | Parameters | Purpose |
|---|---|---|---|
| `schema.columns_by_type` | admin | `pattern`, `limit` | Find columns by name pattern across all user tables |
| `schema.dependencies` | admin | `table` | Views and materialized views that depend on a table |
| `schema.no_primary_key` | admin | none | Tables without a primary key |
| `schema.sequences_near_limit` | admin | `percent` | Sequences that have used more than a percentage of their range |

## security

| Name | Needs | Parameters | Purpose |
|---|---|---|---|
| `security.expiring_roles` | admin | `days` | Login roles whose password expires within a number of days (or already has) |
| `security.public_grants` | admin | none | Tables where PUBLIC holds privileges |
| `security.rls_status` | admin | `all_tables` | Row-level security enabled/forced per table, with policy counts |
| `security.superusers` | admin | none | Roles with superuser, or that can create roles or bypass RLS |

## size

| Name | Needs | Parameters | Purpose |
|---|---|---|---|
| `size.database` | admin | none | Size of every database the connector can see |
| `size.indexes` | admin | `limit` | Largest indexes with scan counts |
| `size.schemas` | admin | none | Total relation size per schema in the current database |
| `size.tables` | admin | `limit` | Largest tables with table, index, and toast breakdown |

## statements

| Name | Needs | Parameters | Purpose |
|---|---|---|---|
| `statements.most_called` | admin, `pg_stat_statements` extension | `limit` | Most frequently executed statements |
| `statements.temp_heavy` | admin, `pg_stat_statements` extension | `limit` | Statements spilling the most to temporary files (work_mem candidates) |
| `statements.top_mean_time` | admin, `pg_stat_statements` extension | `min_calls`, `limit` | Slowest statements on average (with a minimum call count) |
| `statements.top_total_time` | admin, `pg_stat_statements` extension | `limit` | Statements by total execution time |

## table

| Name | Needs | Parameters | Purpose |
|---|---|---|---|
| `table.column_stats` | read | `table` | Planner statistics per column: null fraction, distinct estimate, most common values |
| `table.foreign_keys` | read | `table` | Foreign keys from and to one table |
| `table.index_usage` | read | `table` | Index scan counts and sizes for one table, least used first |
