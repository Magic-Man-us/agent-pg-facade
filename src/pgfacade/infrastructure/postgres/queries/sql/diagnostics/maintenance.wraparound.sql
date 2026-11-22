-- category: maintenance
-- description: Transaction ID age per database (freeze before autovacuum_freeze_max_age)
SELECT datname AS database, age(datfrozenxid) AS xid_age, current_setting('autovacuum_freeze_max_age')::bigint AS freeze_max_age, round(100.0 * age(datfrozenxid) / current_setting('autovacuum_freeze_max_age')::bigint, 1) AS percent_to_forced_vacuum FROM pg_database ORDER BY 2 DESC