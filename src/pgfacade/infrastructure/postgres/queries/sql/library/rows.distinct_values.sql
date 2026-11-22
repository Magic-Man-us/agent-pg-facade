-- description: Distinct values of a column with their frequencies
-- param: table:table    Table to inspect
-- param: column:column  Column to profile
-- param: limit:int=100  Values to return
SELECT {column} AS value, count(*) AS n
FROM {table}
GROUP BY 1 ORDER BY n DESC, 1 NULLS LAST LIMIT %(limit)s
