-- description: Planner statistics per column: null fraction, distinct estimate, most common values
-- param: table:table  Table to inspect
SELECT s.attname AS column, s.null_frac, s.n_distinct, s.avg_width, s.most_common_vals::text AS most_common_vals,
       s.most_common_freqs, s.correlation
FROM pg_stats s
JOIN pg_class c ON c.relname = s.tablename
JOIN pg_namespace n ON n.oid = c.relnamespace AND n.nspname = s.schemaname
WHERE c.oid = %(table_regclass)s::regclass
ORDER BY s.attname
