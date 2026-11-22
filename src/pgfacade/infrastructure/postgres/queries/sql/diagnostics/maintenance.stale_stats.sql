-- category: maintenance
-- description: Tables never analyzed or not analyzed for a number of days
-- param: days:int=7 Staleness threshold in days
-- param: limit:int=50 Max rows
SELECT schemaname AS schema_name, relname AS table_name, n_live_tup AS live_rows, n_mod_since_analyze AS modified_since_analyze, greatest(last_analyze, last_autoanalyze) AS last_analyzed FROM pg_stat_user_tables WHERE greatest(last_analyze, last_autoanalyze) IS NULL OR greatest(last_analyze, last_autoanalyze) < now() - make_interval(days => %(days)s) ORDER BY n_mod_since_analyze DESC LIMIT %(limit)s