-- category: maintenance
-- description: Tables with the highest dead-tuple ratio (vacuum candidates)
-- param: min_dead:int=1000 Ignore tables with fewer dead rows
-- param: limit:int=50 Max rows
SELECT schemaname AS schema_name, relname AS table_name, n_live_tup AS live_rows, n_dead_tup AS dead_rows, round(n_dead_tup::numeric / nullif(n_live_tup + n_dead_tup, 0), 3) AS dead_ratio, last_vacuum, last_autovacuum FROM pg_stat_user_tables WHERE n_dead_tup > %(min_dead)s ORDER BY dead_ratio DESC NULLS LAST LIMIT %(limit)s