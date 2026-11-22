
SELECT name, coalesce(installed_version, default_version) AS version, NULL::text AS schema_name,
       default_version AS available_version, installed_version IS NOT NULL AS installed, comment
FROM pg_available_extensions ORDER BY 1
