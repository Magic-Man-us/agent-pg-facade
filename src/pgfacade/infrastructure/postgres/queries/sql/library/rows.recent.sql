-- description: Newest rows of a table by a timestamp column
-- param: table:table              Table to read
-- param: column:column=created_at Timestamp column to order by
-- param: limit:int=50             Rows to return
SELECT * FROM {table} ORDER BY {column} DESC NULLS LAST LIMIT %(limit)s
