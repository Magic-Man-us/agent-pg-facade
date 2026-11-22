-- category: security
-- description: Login roles whose password expires within a number of days (or already has)
-- param: days:int=30 Window in days
SELECT rolname AS role, rolvaliduntil AS valid_until FROM pg_roles WHERE rolcanlogin AND rolvaliduntil IS NOT NULL AND rolvaliduntil < now() + make_interval(days => %(days)s) ORDER BY 2