-- description: Foreign keys from and to one table
-- param: table:table  Table to inspect
SELECT con.conname AS constraint, con.conrelid::regclass::text AS from_table,
       (SELECT array_agg(a.attname ORDER BY k.ord) FROM unnest(con.conkey) WITH ORDINALITY k(attnum, ord)
        JOIN pg_attribute a ON a.attrelid = con.conrelid AND a.attnum = k.attnum) AS from_columns,
       con.confrelid::regclass::text AS to_table,
       (SELECT array_agg(a.attname ORDER BY k.ord) FROM unnest(con.confkey) WITH ORDINALITY k(attnum, ord)
        JOIN pg_attribute a ON a.attrelid = con.confrelid AND a.attnum = k.attnum) AS to_columns,
       CASE con.confdeltype WHEN 'c' THEN 'cascade' WHEN 'n' THEN 'set null' WHEN 'd' THEN 'set default'
                            WHEN 'r' THEN 'restrict' ELSE 'no action' END AS on_delete
FROM pg_constraint con
WHERE con.contype = 'f' AND (con.conrelid = %(table_regclass)s::regclass OR con.confrelid = %(table_regclass)s::regclass)
ORDER BY 2, 1
