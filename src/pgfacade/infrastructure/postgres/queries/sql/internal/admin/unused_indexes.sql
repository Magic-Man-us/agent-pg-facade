
SELECT s.schemaname AS schema_name, s.relname AS table_name, s.indexrelname AS index_name,
       s.idx_scan AS scans, pg_relation_size(s.indexrelid) AS size_bytes
FROM pg_stat_user_indexes s JOIN pg_index i ON i.indexrelid = s.indexrelid
WHERE s.idx_scan = 0 AND NOT i.indisunique AND NOT i.indisprimary
ORDER BY pg_relation_size(s.indexrelid) DESC
LIMIT %s
