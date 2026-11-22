
SELECT i.relname AS name, pg_get_indexdef(x.indexrelid) AS definition, x.indisunique AS is_unique,
       x.indisprimary AS is_primary, pg_relation_size(x.indexrelid) AS size_bytes
FROM pg_index x JOIN pg_class i ON i.oid = x.indexrelid
WHERE x.indrelid = to_regclass(%s)
ORDER BY i.relname
