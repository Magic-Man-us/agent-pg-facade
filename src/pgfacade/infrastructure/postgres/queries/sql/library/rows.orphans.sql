-- description: Child rows whose reference has no matching parent row
-- param: table:table              Child table
-- param: column:column            Child column holding the reference
-- param: parent:identifier        Parent table ("table" or "schema.table")
-- param: parent_column:identifier Parent column being referenced
SELECT c.*
FROM {table} c
LEFT JOIN {parent} p ON p.{parent_column} = c.{column}
WHERE c.{column} IS NOT NULL AND p.{parent_column} IS NULL
