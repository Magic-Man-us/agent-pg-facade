-- description: Values that appear more than once in a column, largest groups first
-- param: table:table      Table to inspect
-- param: column:column    Column that should be unique
-- param: min_count:int=2  Minimum group size to report
SELECT {column} AS value, count(*) AS n
FROM {table}
GROUP BY 1 HAVING count(*) >= %(min_count)s
ORDER BY n DESC, 1
