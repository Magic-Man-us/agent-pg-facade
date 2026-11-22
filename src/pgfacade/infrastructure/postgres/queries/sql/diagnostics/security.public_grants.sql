-- category: security
-- description: Tables where PUBLIC holds privileges
SELECT table_schema AS schema_name, table_name, array_agg(privilege_type ORDER BY privilege_type) AS privileges FROM information_schema.role_table_grants WHERE grantee = 'PUBLIC' AND table_schema !~ '^pg_' AND table_schema <> 'information_schema' GROUP BY 1, 2 ORDER BY 1, 2