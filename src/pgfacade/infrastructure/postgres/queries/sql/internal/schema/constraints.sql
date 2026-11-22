
SELECT conname AS name,
       CASE contype WHEN 'p' THEN 'primary_key' WHEN 'f' THEN 'foreign_key' WHEN 'u' THEN 'unique'
                    WHEN 'c' THEN 'check' WHEN 'x' THEN 'exclusion' WHEN 'n' THEN 'not_null'
                    ELSE contype::text END AS type,
       pg_get_constraintdef(oid) AS definition
FROM pg_constraint WHERE conrelid = to_regclass(%s)
ORDER BY contype, conname
