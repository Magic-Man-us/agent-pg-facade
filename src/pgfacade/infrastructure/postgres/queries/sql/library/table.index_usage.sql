-- description: Index scan counts and sizes for one table, least used first
-- param: table:table  Table to inspect
SELECT s.indexrelname AS index, s.idx_scan AS scans, s.idx_tup_read AS tuples_read, s.idx_tup_fetch AS tuples_fetched,
       pg_relation_size(s.indexrelid) AS size_bytes, i.indisunique AS is_unique, i.indisprimary AS is_primary,
       pg_get_indexdef(s.indexrelid) AS definition
FROM pg_stat_user_indexes s JOIN pg_index i ON i.indexrelid = s.indexrelid
WHERE s.relid = %(table_regclass)s::regclass
ORDER BY s.idx_scan, size_bytes DESC
