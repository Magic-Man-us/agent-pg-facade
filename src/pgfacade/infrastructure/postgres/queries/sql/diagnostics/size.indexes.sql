-- category: size
-- description: Largest indexes with scan counts
-- param: limit:int=50 Max rows
SELECT s.schemaname AS schema_name, s.relname AS table_name, s.indexrelname AS index_name, pg_size_pretty(pg_relation_size(s.indexrelid)) AS size, s.idx_scan AS scans, pg_relation_size(s.indexrelid) AS bytes FROM pg_stat_user_indexes s ORDER BY pg_relation_size(s.indexrelid) DESC LIMIT %(limit)s