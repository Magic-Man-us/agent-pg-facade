# File configuration and group policies

PGFacade loads `.yaml`, `.yml`, and `.toml` through Pydantic Settings and validates one configuration contract. No Google identity, OAuth, directory, or membership lookup is implemented. Identity sources are a local mock and a deny-all stub, with an async interface for your implementation.

The existing deployed service stays in API-key mode. Group-policy mode is explicit: configure `access_control`. It never falls back to legacy API keys when an identity lookup fails. The current deployment checker targets the API-key production profile; mock configurations are for a separate development/test instance, not an automatic production authentication change.

## Load a configuration

```python
from pathlib import Path
from pgfacade import PgSettings

settings = PgSettings(config_file=Path("docs/examples/mock-access.yaml"))
```

Or select the file with `PGFACADE_CONFIG_FILE=/absolute/path/to/settings.yaml`. File loading only validates configuration; it does not connect to PostgreSQL or perform identity lookup.

Precedence is constructor values, environment, dotenv, selected file, secret files, then defaults. Database overrides follow that order across flat `dsn` and structured `database` representations. Define one representation per source; supplying both in the same source is rejected. Partial structured overrides can merge with another structured source; switching away from a DSN requires a complete structured variant.

Unknown fields, missing/unsupported files, malformed files, ambiguous database settings, invalid DSNs, and invalid policy references fail validation. Parse and credential errors are redacted. Keep real database passwords, mock tokens, and API keys in protected configuration outside source control.

### Database forms

```yaml
database:
  kind: postgres
  host: /var/run/postgresql
  port: 5432
  dbname: your_database
  user: your_connector
```

`username` aliases `user`; `name` aliases `dbname`. Optional `password` is a Pydantic secret and `sslmode` accepts PostgreSQL's defined modes. Connection strings are constructed with psycopg's connection-info builder, including credential escaping.

A complete DSN is also supported:

```yaml
database:
  kind: dsn
  dsn: "host=/var/run/postgresql dbname=your_database user=your_connector"
```

Existing `PGFACADE_DSN` and constructor `dsn` remain supported. Environment overrides are useful when a file contains policies but the deployment supplies database credentials separately.

## Mock identity source

[The YAML example](examples/mock-access.yaml) and [equivalent TOML example](examples/mock-access.toml) use deliberately public synthetic tokens and a separate development database. They describe the contract; provision development roles/tables and supply an authorized development database configuration before starting an instance. Do not reuse the demonstration tokens for real clients.

```yaml
access_control:
  identity:
    kind: mock
    records:
      - token: demo-reader-not-a-google-token
        identity:
          subject: mock-reader
          issuer: mock
          groups: [mock-report-readers]
```

The mock compares a presented bearer token to configured records and returns only the configured identity and groups. Unknown/missing tokens are denied. Google-looking JWTs are not decoded or trusted. Group, user, role, or connector headers supplied by callers cannot select identities or database credentials. Mock records must use the `mock` issuer.

Group IDs are opaque exact identifiers. The mock does not expand nested groups. Your future provider is responsible for returning the verified resolved groups.

## Policies and execution identities

Policies select a configured connector, operations, and resources for specified groups. An allow policy names a preconfigured database execution identity; a deny policy does not. The caller cannot choose its execution role.

```yaml
access_control:
  execution_identities:
    reports_reader:
      role: pgfacade_reader
      read_only: true
  policies:
    - id: notes-read
      effect: allow
      groups: [mock-report-readers]
      connector: local
      operations: [rows.select, rows.count]
      resources: [app.notes]
      execution_identity: reports_reader
```

Each instance currently has one connector, named by `connector_id` (default `local`), backed by its configured PostgreSQL pool. Multiple connector definitions or routing arbitrary client DSNs are not implemented. Separate trust levels still require separate connector identities or deployments.

Rules:

- No matching allow means deny. Any matching explicit deny wins, regardless of priority.
- Group IDs match exactly. Operations accept exact names, an area wildcard such as `rows.*`, or `*`.
- Table resources are `schema.table`, `schema.*`, or `*`. Identifiers are simple ASCII PostgreSQL identifiers, each at most 63 characters. Bare table requests use `default_schema`.
- `@connector` scopes `server.health` and `server.whoami`.
- Higher allow priority wins. Equal-priority complete grants selecting different execution identities are denied as ambiguous.
- A batch needs one execution identity that permits every child operation/resource. For each candidate, the strongest grant for each child is considered; its weakest child priority determines that candidate's precedence. The selected identity stays pinned through the transaction. A deny on a child or `batch.run` envelope rejects the whole batch before execution.
- Group batches default to at most 100 operations, configurable from 1 to 1000 with `max_batch_operations`.
- Server-wide capability/read-only limits and PostgreSQL grants remain in force.

The first policy-enabled surface covers structured `rows.*`, connector health/whoami, and atomic batches. Raw SQL, query-library execution, DDL, administration, migrations, events, and other metadata operations are rejected for group identities even if a policy contains `*`. Their complete resource plans need explicit support before they can be authorized safely.

`GET /ops` lists eligible operation types; each concrete target is checked on every call. Table policy checks cover the requested relation, not every effect of trusted views, triggers, defaults, foreign-key cascades, or security-definer functions. Database/schema administrators remain trusted. Use database grants, views, column privileges, or RLS for finer data boundaries.

## Supply your identity lookup

```python
from pathlib import Path
from pgfacade import PgSettings, Unauthenticated
from pgfacade.authorization.models import Identity
from pgfacade.shared.types import ApiKey
from pgfacade.webapp import create_app


class MyIdentitySource:
    async def lookup(self, credential: ApiKey) -> Identity:
        raise Unauthenticated("Identity source has not been connected")


settings = PgSettings(config_file=Path("settings.yaml"))
app = create_app(settings, identity_provider=MyIdentitySource())
```

Set `access_control.identity.kind` to `stub` when injecting a provider. The built-in stub denies every lookup. Your provider must authenticate the credential and obtain groups from your trusted sources before returning `Identity`; Pydantic validates structure, not the truth of group membership. Unavailable or invalid identity sources should raise `Unauthenticated`. The async hook is also accepted by `create_mcp`.

Direct Python library calls without an authenticated group identity remain trusted connector calls. Network transports always authenticate before dispatch. Policies and file configuration are loaded at startup; restart a separately configured instance after changes. There is no Google SDK, token verification implementation, external membership cache, or directory request in this feature.

## Wait for a listener command

An optional command runs before the REST or MCP server opens its database connection:

```yaml
startup_command:
  argv: [/usr/bin/python3, -u, /opt/your-listener/start.py]
  ready_marker: READY
  timeout_s: 30
  stop_timeout_s: 5
```

Equivalent TOML:

```toml
[startup_command]
argv = ["/usr/bin/python3", "-u", "/opt/your-listener/start.py"]
ready_marker = "READY"
timeout_s = 30
stop_timeout_s = 5
```

The server combines stdout and stderr and waits for a complete line equal to `READY`, ignoring surrounding whitespace. `NOT READY` does not match. The command must flush the line; Python's `-u` disables output buffering. It may exit successfully after emitting readiness, or stay running. Output is continuously consumed and discarded, including after readiness. Lines before readiness are limited to 64 KiB. Command output and arguments are not included in startup errors.

Timeout, early exit without readiness, and oversized output lines fail startup. Shutdown or failed startup terminates and reaps the owned local process group. Remote services started by the command require their own lifecycle management. `READY` is the command's declaration; it does not independently verify a remote listener. PostgreSQL's normal connection check follows the command gate.

Arguments are passed directly to an executable without a shell. This is trusted operator configuration, never a request parameter. Omit `startup_command` to launch nothing. The existing service has no startup command configured. Commands run under the service account and its existing systemd filesystem and network restrictions; executable paths must be accessible there.
