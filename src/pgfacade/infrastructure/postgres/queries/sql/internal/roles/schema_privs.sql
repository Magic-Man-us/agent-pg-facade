
SELECT CASE WHEN a.grantee = 0 THEN 'public' ELSE a.grantee::regrole::text END AS grantee,
       a.privilege_type AS privilege, a.is_grantable AS grantable
FROM pg_namespace n, aclexplode(n.nspacl) a
WHERE n.nspname = %s
ORDER BY 1, 2
