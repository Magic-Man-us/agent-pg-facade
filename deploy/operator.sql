\set ON_ERROR_STOP on

BEGIN;
CREATE ROLE pgfacade_operator LOGIN INHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS CONNECTION LIMIT 4 PASSWORD NULL;
GRANT pgfacade_reader TO pgfacade_operator WITH ADMIN FALSE, INHERIT TRUE, SET FALSE;
ALTER ROLE pgfacade_operator SET statement_timeout = '10s';
ALTER ROLE pgfacade_operator SET lock_timeout = '2s';
ALTER ROLE pgfacade_operator SET idle_in_transaction_session_timeout = '30s';
ALTER ROLE pgfacade_operator SET temp_file_limit = '128MB';
ALTER ROLE pgfacade_operator SET default_transaction_read_only = on;
GRANT CONNECT ON DATABASE pgfacade TO pgfacade_operator;
ALTER ROLE pgfacade_operator IN DATABASE pgfacade SET search_path = pg_catalog, app;
COMMIT;
