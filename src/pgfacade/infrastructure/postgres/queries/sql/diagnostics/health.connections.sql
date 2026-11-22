-- category: health
-- description: Connections by state and user against max_connections
SELECT coalesce(usename, '<background>') AS "user", coalesce(state, backend_type) AS state, count(*) AS n, current_setting('max_connections')::int AS max_connections FROM pg_stat_activity GROUP BY 1, 2 ORDER BY 3 DESC