-- category: size
-- description: Size of every database the connector can see
SELECT datname AS database, pg_size_pretty(pg_database_size(datname)) AS size, pg_database_size(datname) AS bytes FROM pg_database WHERE datallowconn ORDER BY 3 DESC