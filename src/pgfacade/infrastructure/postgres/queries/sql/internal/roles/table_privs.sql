
SELECT grantee, privilege_type AS privilege, is_grantable = 'YES' AS grantable
FROM information_schema.role_table_grants
WHERE table_schema = %s AND table_name = %s
ORDER BY grantee, privilege_type
