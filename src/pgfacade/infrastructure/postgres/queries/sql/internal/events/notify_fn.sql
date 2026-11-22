
CREATE SCHEMA IF NOT EXISTS _pgfacade;
CREATE OR REPLACE FUNCTION _pgfacade.notify_change() RETURNS trigger LANGUAGE plpgsql AS $fn$
DECLARE
    channel text := TG_ARGV[0];
    cols    text[] := CASE WHEN TG_NARGS > 1 AND TG_ARGV[1] <> '' THEN string_to_array(TG_ARGV[1], ',') END;
    rec     jsonb;
    payload jsonb;
BEGIN
    rec := CASE WHEN TG_OP = 'DELETE' THEN to_jsonb(OLD) ELSE to_jsonb(NEW) END;
    IF cols IS NOT NULL THEN
        SELECT coalesce(jsonb_object_agg(key, value), '{}'::jsonb) INTO rec FROM jsonb_each(rec) WHERE key = ANY (cols);
    END IF;
    payload := jsonb_build_object('op', lower(TG_OP), 'schema', TG_TABLE_SCHEMA, 'table', TG_TABLE_NAME,
                                  'at', now(), 'row', rec);
    IF octet_length(payload::text) > 7900 THEN
        payload := (payload - 'row') || jsonb_build_object('truncated', true);
    END IF;
    PERFORM pg_notify(channel, payload::text);
    RETURN NULL;
END
$fn$;
