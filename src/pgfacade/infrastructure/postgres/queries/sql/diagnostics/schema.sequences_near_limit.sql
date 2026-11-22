-- category: schema
-- description: Sequences that have used more than a percentage of their range
-- param: percent:float=50.0 Report sequences above this percent
SELECT schemaname AS schema_name, sequencename AS sequence_name, last_value, max_value, round(100.0 * last_value / max_value, 2) AS percent_used FROM pg_sequences WHERE last_value IS NOT NULL AND 100.0 * last_value / max_value > %(percent)s ORDER BY 5 DESC