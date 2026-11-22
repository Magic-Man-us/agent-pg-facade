
SELECT n.nspname AS schema_name, c.relname AS table_name, pg_get_triggerdef(t.oid) AS definition
FROM pg_trigger t
JOIN pg_class c ON c.oid = t.tgrelid
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE t.tgname = '_pgfacade_watch' AND NOT t.tgisinternal
ORDER BY 1, 2
