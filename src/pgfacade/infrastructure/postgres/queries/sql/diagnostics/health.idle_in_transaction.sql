-- category: health
-- description: Sessions idle inside an open transaction (they hold locks and block vacuum)
-- param: seconds:float=60.0 Threshold in seconds
SELECT pid, usename AS "user", datname AS database, application_name, round(extract(epoch FROM now() - state_change)::numeric, 1) AS idle_seconds, left(query, 500) AS last_query FROM pg_stat_activity WHERE state = 'idle in transaction' AND now() - state_change > make_interval(secs => %(seconds)s) ORDER BY state_change