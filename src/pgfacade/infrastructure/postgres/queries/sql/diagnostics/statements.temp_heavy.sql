-- category: statements
-- description: Statements spilling the most to temporary files (work_mem candidates)
-- requires: pg_stat_statements
-- param: limit:int=20 Max rows
SELECT calls, pg_size_pretty(temp_blks_written * current_setting('block_size')::bigint) AS temp_written, round(mean_exec_time::numeric, 2) AS mean_ms, left(query, 400) AS query FROM pg_stat_statements WHERE temp_blks_written > 0 ORDER BY temp_blks_written DESC LIMIT %(limit)s