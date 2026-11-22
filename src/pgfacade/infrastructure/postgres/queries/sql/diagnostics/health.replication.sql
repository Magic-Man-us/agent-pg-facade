-- category: health
-- description: Streaming replication clients and their lag (run on the primary)
SELECT client_addr::text AS client, application_name, state, sync_state, pg_wal_lsn_diff(pg_current_wal_lsn(), replay_lsn) AS replay_lag_bytes, write_lag, flush_lag, replay_lag FROM pg_stat_replication ORDER BY 1