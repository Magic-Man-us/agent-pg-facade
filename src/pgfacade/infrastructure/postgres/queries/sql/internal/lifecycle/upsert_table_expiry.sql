
INSERT INTO _pgfacade.lifecycle_policies (kind, schema_name, table_name, expires_at, action, enabled)
VALUES ('table_expiry', %(schema_name)s, %(table_name)s, %(expires_at)s, %(action)s, %(enabled)s)
ON CONFLICT (kind, schema_name, table_name, column_name) DO UPDATE
   SET expires_at = EXCLUDED.expires_at, action = EXCLUDED.action, enabled = EXCLUDED.enabled, last_error = NULL
RETURNING *, ttl::text AS ttl
