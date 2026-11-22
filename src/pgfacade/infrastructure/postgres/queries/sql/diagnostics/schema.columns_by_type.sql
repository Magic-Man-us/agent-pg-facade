-- category: schema
-- description: Find columns by name pattern across all user tables
-- param: pattern:text=%id% ILIKE pattern on the column name
-- param: limit:int=200 Max rows
SELECT table_schema AS schema_name, table_name, column_name, data_type, is_nullable = 'YES' AS nullable FROM information_schema.columns WHERE table_schema !~ '^pg_' AND table_schema <> 'information_schema' AND column_name ILIKE %(pattern)s ORDER BY 1, 2, ordinal_position LIMIT %(limit)s