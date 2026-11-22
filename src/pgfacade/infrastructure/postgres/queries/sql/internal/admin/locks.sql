
SELECT blocked.pid AS blocked_pid, blocked.usename AS blocked_user,
       round(extract(epoch FROM now() - blocked.query_start)::numeric, 3)::float8 AS blocked_seconds,
       left(blocked.query, 1000) AS blocked_query,
       blocking.pid AS blocking_pid, blocking.usename AS blocking_user, blocking.state AS blocking_state,
       left(blocking.query, 1000) AS blocking_query
FROM pg_stat_activity blocked
CROSS JOIN LATERAL unnest(pg_blocking_pids(blocked.pid)) AS b(pid)
JOIN pg_stat_activity blocking ON blocking.pid = b.pid
ORDER BY blocked_seconds DESC NULLS LAST
