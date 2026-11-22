-- category: health
-- description: Client queries running longer than a threshold
-- param: seconds:float=30.0 Threshold in seconds
SELECT pid, usename AS "user", datname AS database, state, round(extract(epoch FROM now() - query_start)::numeric, 1) AS seconds, wait_event_type, wait_event, left(query, 500) AS query FROM pg_stat_activity WHERE backend_type = 'client backend' AND state <> 'idle' AND pid <> pg_backend_pid() AND now() - query_start > make_interval(secs => %(seconds)s) ORDER BY query_start