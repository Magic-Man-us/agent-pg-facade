-- category: statements
-- description: Slowest statements on average (with a minimum call count)
-- requires: pg_stat_statements
-- param: min_calls:int=10 Ignore rarely-run statements
-- param: limit:int=20 Max rows
SELECT calls, round(mean_exec_time::numeric, 2) AS mean_ms, round(total_exec_time::numeric, 1) AS total_ms, rows, left(query, 400) AS query FROM pg_stat_statements WHERE calls >= %(min_calls)s ORDER BY mean_exec_time DESC LIMIT %(limit)s