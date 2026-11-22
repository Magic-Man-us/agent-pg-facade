-- category: security
-- description: Roles with superuser, or that can create roles or bypass RLS
SELECT rolname AS role, rolsuper AS superuser, rolcreaterole AS createrole, rolcreatedb AS createdb, rolbypassrls AS bypassrls, rolcanlogin AS login FROM pg_roles WHERE rolsuper OR rolcreaterole OR rolbypassrls ORDER BY 1