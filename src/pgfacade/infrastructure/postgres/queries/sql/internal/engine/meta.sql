
SELECT a.attname AS name, a.atttypid::regtype::text AS regtype, t.typcategory AS category,
       array_position(i.indkey::int2[], a.attnum) AS pk_pos, c.relkind::text AS relkind
FROM pg_attribute a
JOIN pg_class c ON c.oid = a.attrelid
JOIN pg_type t ON t.oid = a.atttypid
LEFT JOIN pg_index i ON i.indrelid = a.attrelid AND i.indisprimary
WHERE a.attrelid = to_regclass(%s) AND a.attnum > 0 AND NOT a.attisdropped
ORDER BY a.attnum
