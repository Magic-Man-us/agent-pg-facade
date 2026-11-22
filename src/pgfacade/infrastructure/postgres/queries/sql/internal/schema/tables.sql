
SELECT n.nspname AS schema_name, c.relname AS name,
       CASE c.relkind WHEN 'r' THEN 'table' WHEN 'p' THEN 'partitioned_table' WHEN 'v' THEN 'view'
                      WHEN 'm' THEN 'materialized_view' WHEN 'f' THEN 'foreign_table' ELSE c.relkind::text END AS kind,
       pg_get_userbyid(c.relowner) AS owner,
       greatest(c.reltuples, 0)::bigint AS est_rows,
       pg_total_relation_size(c.oid) AS total_bytes,
       obj_description(c.oid, 'pg_class') AS comment
FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE {cond}
ORDER BY {order}{limit}
