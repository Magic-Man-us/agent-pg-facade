
SELECT schemaname AS schema_name, relname AS name, n_live_tup AS live_rows, n_dead_tup AS dead_rows,
       seq_scan, idx_scan, n_tup_ins AS inserts, n_tup_upd AS updates, n_tup_del AS deletes,
       last_vacuum, last_autovacuum, last_analyze, last_autoanalyze
FROM pg_stat_user_tables
WHERE (%s::text IS NULL OR schemaname = %s)
ORDER BY n_live_tup DESC
LIMIT %s
