
SELECT r.rolname AS name, r.rolcanlogin AS login, r.rolsuper AS superuser, r.rolcreatedb AS createdb,
       r.rolcreaterole AS createrole, r.rolinherit AS inherit, r.rolreplication AS replication,
       r.rolbypassrls AS bypassrls, r.rolconnlimit AS connection_limit,
       CASE WHEN r.rolvaliduntil = 'infinity' THEN NULL ELSE r.rolvaliduntil END AS valid_until,
       coalesce((SELECT array_agg(g.rolname ORDER BY g.rolname) FROM pg_auth_members m JOIN pg_roles g ON g.oid = m.roleid
                 WHERE m.member = r.oid), ARRAY[]::text[]) AS member_of,
       coalesce((SELECT array_agg(u.rolname ORDER BY u.rolname) FROM pg_auth_members m JOIN pg_roles u ON u.oid = m.member
                 WHERE m.roleid = r.oid), ARRAY[]::text[]) AS members,
       shobj_description(r.oid, 'pg_authid') AS comment
FROM pg_roles r
WHERE __COND__
ORDER BY r.rolname
