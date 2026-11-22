-- category: statements
-- description: Statements by total execution time
-- requires: pg_stat_statements
-- param: limit:int=20 Max rows
SELECT calls, round(total_exec_time::numeric, 1) AS total_ms, round(mean_exec_time::numeric, 2) AS mean_ms, rows, left(query, 400) AS query FROM pg_stat_statements ORDER BY total_exec_time DESC LIMIT %(limit)s