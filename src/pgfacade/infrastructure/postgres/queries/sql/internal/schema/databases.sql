
SELECT d.datname AS name, pg_get_userbyid(d.datdba) AS owner, pg_encoding_to_char(d.encoding) AS encoding,
       CASE WHEN has_database_privilege(d.datname, 'CONNECT') THEN pg_database_size(d.datname) END AS size_bytes,
       d.datistemplate AS is_template, d.datallowconn AS allow_connections
FROM pg_database d ORDER BY 1
