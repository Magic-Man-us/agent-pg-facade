-- category: index
-- description: Indexes with identical definitions apart from the name
SELECT array_agg(indexrelid::regclass::text ORDER BY indexrelid) AS indexes, indrelid::regclass::text AS table_name, pg_size_pretty(sum(pg_relation_size(indexrelid))) AS total_size FROM pg_index GROUP BY indrelid, indkey, indclass, indoption, indpred, indexprs, indisunique HAVING count(*) > 1 ORDER BY 2