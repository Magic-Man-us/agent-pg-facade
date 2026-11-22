-- category: security
-- description: Row-level security enabled/forced per table, with policy counts
-- param: all_tables:bool=false Include tables without RLS
SELECT n.nspname AS schema_name, c.relname AS table_name, c.relrowsecurity AS rls_enabled, c.relforcerowsecurity AS rls_forced, (SELECT count(*) FROM pg_policy p WHERE p.polrelid = c.oid)::int AS policies FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace WHERE c.relkind IN ('r','p') AND n.nspname !~ '^pg_' AND n.nspname <> 'information_schema' AND (c.relrowsecurity OR %(all_tables)s) ORDER BY 1, 2