-- category: index
-- description: Non-unique indexes with zero scans since the last stats reset
-- param: limit:int=50 Max rows
SELECT s.schemaname AS schema_name, s.relname AS table_name, s.indexrelname AS index_name, pg_size_pretty(pg_relation_size(s.indexrelid)) AS size, pg_relation_size(s.indexrelid) AS bytes FROM pg_stat_user_indexes s JOIN pg_index i ON i.indexrelid = s.indexrelid WHERE s.idx_scan = 0 AND NOT i.indisunique AND NOT i.indisprimary ORDER BY 5 DESC LIMIT %(limit)s