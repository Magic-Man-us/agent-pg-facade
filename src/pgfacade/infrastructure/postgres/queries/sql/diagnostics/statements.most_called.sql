-- category: statements
-- description: Most frequently executed statements
-- requires: pg_stat_statements
-- param: limit:int=20 Max rows
SELECT calls, round(mean_exec_time::numeric, 3) AS mean_ms, rows, left(query, 400) AS query FROM pg_stat_statements ORDER BY calls DESC LIMIT %(limit)s