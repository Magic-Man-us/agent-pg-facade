-- category: index
-- description: Sequential vs index scan ratio per table (large tables with many seq scans want indexes)
-- param: min_rows:int=10000 Ignore smaller tables
-- param: limit:int=50 Max rows
SELECT schemaname AS schema_name, relname AS table_name, seq_scan, idx_scan, n_live_tup AS live_rows, round(100.0 * idx_scan / nullif(seq_scan + idx_scan, 0), 1) AS index_scan_percent FROM pg_stat_user_tables WHERE n_live_tup > %(min_rows)s ORDER BY seq_scan DESC LIMIT %(limit)s