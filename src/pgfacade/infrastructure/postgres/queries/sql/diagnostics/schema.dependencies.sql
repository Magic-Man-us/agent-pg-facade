-- category: schema
-- description: Views and materialized views that depend on a table
-- param: table:text=public.users schema.table
SELECT DISTINCT dv.relkind::text AS kind, nv.nspname || '.' || dv.relname AS dependent FROM pg_depend d JOIN pg_rewrite r ON r.oid = d.objid JOIN pg_class dv ON dv.oid = r.ev_class JOIN pg_namespace nv ON nv.oid = dv.relnamespace WHERE d.refobjid = to_regclass(%(table)s) AND dv.oid <> d.refobjid ORDER BY 2