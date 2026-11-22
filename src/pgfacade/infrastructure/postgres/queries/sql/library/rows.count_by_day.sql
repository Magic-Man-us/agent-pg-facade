-- description: Row counts per day over the last N days
-- param: table:table              Table to count
-- param: column:column=created_at Timestamp column to bucket
-- param: days:int=30              Window in days
SELECT date_trunc('day', {column})::date AS day, count(*) AS n
FROM {table}
WHERE {column} >= now() - %(days)s * interval '1 day'
GROUP BY 1 ORDER BY 1
