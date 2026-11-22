-- description: Rows whose timestamp column is at or after a point in time
-- param: table:table              Table to read
-- param: since:text               ISO-8601 timestamp, e.g. 2026-01-01T00:00:00Z
-- param: column:column=created_at Timestamp column to compare
SELECT * FROM {table} WHERE {column} >= %(since)s::timestamptz ORDER BY {column}
