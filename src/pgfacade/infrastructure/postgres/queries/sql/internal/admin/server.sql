
SELECT current_setting('server_version') AS server_version, version() AS version,
       current_database() AS database, session_user AS "user", current_user AS session_role,
       pg_postmaster_start_time() AS started_at,
       pg_database_size(current_database()) AS database_bytes,
       (SELECT count(*) FROM pg_stat_activity WHERE datname = current_database())::int AS connections,
       current_setting('max_connections')::int AS max_connections, pg_is_in_recovery() AS in_recovery
