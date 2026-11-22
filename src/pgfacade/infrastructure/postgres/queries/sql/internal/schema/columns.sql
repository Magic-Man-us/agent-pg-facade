
SELECT a.attname AS name, format_type(a.atttypid, a.atttypmod) AS type, NOT a.attnotnull AS nullable,
       pg_get_expr(d.adbin, d.adrelid) AS "default", a.attidentity <> '' AS identity,
       a.attgenerated <> '' AS generated, col_description(a.attrelid, a.attnum) AS comment
FROM pg_attribute a
LEFT JOIN pg_attrdef d ON d.adrelid = a.attrelid AND d.adnum = a.attnum
WHERE a.attrelid = to_regclass(%s) AND a.attnum > 0 AND NOT a.attisdropped
ORDER BY a.attnum
