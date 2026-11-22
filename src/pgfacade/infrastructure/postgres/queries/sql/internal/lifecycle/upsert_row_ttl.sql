
INSERT INTO _pgfacade.lifecycle_policies
    (kind, schema_name, table_name, column_name, ttl, action, archive_table, batch_size, enabled)
VALUES ('row_ttl', %(schema_name)s, %(table_name)s, %(column_name)s, %(ttl)s::interval,
        %(action)s, %(archive_table)s, %(batch_size)s, %(enabled)s)
ON CONFLICT (kind, schema_name, table_name, column_name) DO UPDATE
   SET ttl = EXCLUDED.ttl, action = EXCLUDED.action, archive_table = EXCLUDED.archive_table,
       batch_size = EXCLUDED.batch_size, enabled = EXCLUDED.enabled, last_error = NULL
RETURNING *, ttl::text AS ttl
