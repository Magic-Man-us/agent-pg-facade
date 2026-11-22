
SELECT queryid, calls, round(total_exec_time::numeric, 2)::float8 AS total_ms,
       round(mean_exec_time::numeric, 2)::float8 AS mean_ms, rows, left(query, 2000) AS query
FROM pg_stat_statements
ORDER BY total_exec_time DESC
LIMIT %s
