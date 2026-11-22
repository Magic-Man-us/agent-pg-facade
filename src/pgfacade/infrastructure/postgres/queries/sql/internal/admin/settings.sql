
SELECT name, setting AS value, unit, category, context, short_desc AS description
FROM pg_settings WHERE name ILIKE %s ORDER BY name LIMIT %s
