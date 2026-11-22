
SELECT e.extname AS name, e.extversion AS version, n.nspname AS schema_name,
       a.default_version AS available_version, true AS installed, a.comment
FROM pg_extension e
JOIN pg_namespace n ON n.oid = e.extnamespace
LEFT JOIN pg_available_extensions a ON a.name = e.extname
ORDER BY 1
