
SELECT pid, usename AS "user", datname AS database, application_name, client_addr::text AS client_addr,
       state, wait_event_type, wait_event, backend_start, xact_start, query_start,
       round(extract(epoch FROM now() - query_start)::numeric, 3)::float8 AS query_seconds,
       left(query, 2000) AS query
FROM pg_stat_activity
WHERE pid <> pg_backend_pid() AND backend_type = 'client backend' AND (%s OR state IS DISTINCT FROM 'idle')
ORDER BY query_start NULLS LAST
