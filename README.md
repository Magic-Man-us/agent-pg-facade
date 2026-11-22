# PGFacade

A typed PostgreSQL API shared by REST, MCP, and Python callers. Requests are Pydantic models discriminated by `kind`; PostgreSQL grants and the caller's principal determine access.

For deployment instructions, see the [deployment guide](deploy/README.md).

## API contract: version 0.5

Python, HTTP, and MCP share the application-owned operation contract:

```json
{"kind":"rows.count","input":{"table":"app.notes"}}
```

```json
{"kind":"rows.count","outcome":{"status":"success","data":{"count":3}}}
```

```json
{"kind":"rows.count","outcome":{"status":"error","error":{"code":"forbidden","reason":"policy_denied","message":"Operation is forbidden","status":403,"sqlstate":null,"details":{"kind":"authorization","reason":"policy_denied"}}}}
```

HTTP `POST /call` and generated operation routes accept the operation directly. MCP tools take it as their typed `request` argument. HTTP uses the application error's status; MCP marks failed outcomes with `isError`. Authentication and protocol failures use a standalone error outcome because no operation has executed.

`GET /ops` returns permitted operation metadata. `/docs` contains generated schemas; `/healthz` is local liveness metadata.

## Permissions

Each API key maps to a `Principal`. Every database operation applies its mapped role with `SET LOCAL ROLE`. Runtime roles must not own tables or inherit the schema-owner role. The server-wide capability flags cap each principal's permissions; all optional capabilities default off. Network server startup requires API keys or explicit group-policy configuration.

| Capability | Default | Purpose |
|---|---|---|
| `read_only` | false | Deny writes for the server or principal |
| `allow_raw_sql` | false | Raw SQL and SQL-bodied objects |
| `allow_ddl` | false | Structured schema changes |
| `allow_admin` | false | Roles, maintenance, lifecycle management, diagnostics |
| `allow_migrate` | false | Alembic migrations |
| `allow_listen` | false | Notification sending, listening, and watches |
| `lifecycle_sweep_s` | 0 | Background lifecycle execution |

The restricted deployment has separate reader and writer database roles and no administrator privileges. Named keys may share a database role but should not share credential values. The key-file loader validates its contents and excludes credentials from normal settings representations and error messages. Keys are loaded at startup; changes require a restart.

A connector that can switch between several roles holds their combined authority. Raw SQL must be restricted to callers trusted with that authority. PostgreSQL's normal public catalog visibility remains. Separate applications with different trust levels need separate connectors and deployments.

## Python

```python
from pgfacade import ExecutionContext, MyApp, PgSettings, Success
from pgfacade.contracts.rows import RowsSelect, RowsSelectInput

async with MyApp(PgSettings()) as app:
    request = RowsSelect(input=RowsSelectInput(table="app.notes", limit=20))
    response = await app.call(request, ExecutionContext())
    if isinstance(response.outcome, Success):
        page = response.outcome.data
    else:
        error = response.outcome.error
```

A concrete request infers its response: `RowsSelect` returns `ResponseEnvelope[QueryResult]`. `ExecutionContext` carries the trusted principal and transport provenance. HTTP and MCP construct it after authentication; clients cannot supply it in request JSON.

`transaction()` and `Batch` group operations. Batch children use the same request and response envelopes; a child failure rolls back the transaction and becomes the outer failure. Migrations, backend cancellation, and query-cache reload are rejected inside transactions and batches.

The curated query library provides parameterized row/table queries without raw SQL permission. Built-in server diagnostics require administrator permission. Custom SQL files are trusted server code and must not be writable by API callers.

## Development

See [development setup](docs/development.md). Run the standard checks with `uv run --locked tox`.

```sh
uv sync --locked
uv run --locked tox
./deploy/test
```

The first test command runs database-independent tests and skips explicitly marked integration cases. [deploy/test](deploy/test) creates a unique scratch database, runs the full suite as the PostgreSQL OS account, and cleans up. It never targets the application database. It requires local PostgreSQL, system Python 3.12, `uv`, and noninteractive sudo.

Before updating the running service:

```sh
./deploy/test && ./deploy/update
```

[deploy/update](deploy/update) builds a frozen source snapshot, installs a versioned release, checks the host and API, and rolls back failed activation. It does not pull Git changes or modify credentials.

## Code map

`MyApp`, defined in [myapp.py](src/pgfacade/myapp.py), applies shared policy and dispatches concrete requests through `functools.singledispatchmethod`. [webmcp.py](src/pgfacade/webmcp.py) owns the FastMCP server; [webapp.py](src/pgfacade/webapp.py) owns the FastAPI application; CLI and middleware live in presentation; PostgreSQL and process resources live in infrastructure. Import the public facade, settings, enums, and envelopes from `pgfacade`; use the owning package for specialized models and integrations.

| Path | Responsibility |
|---|---|
| [contracts](src/pgfacade/contracts) | Typed operation requests, results, enums, and envelopes |
| [application](src/pgfacade/application) | Execution context, operation metadata, handlers, and application errors |
| [authorization](src/pgfacade/authorization) | Principals' identities, credential checks, providers, and group policies |
| [configuration](src/pgfacade/configuration) | Runtime settings, database variants, and configuration sources |
| [infrastructure](src/pgfacade/infrastructure) | PostgreSQL pools, transactions, SQL composition, query resources, and startup processes |
| [webapp.py](src/pgfacade/webapp.py) | Single FastAPI factory and REST routes |
| [webmcp.py](src/pgfacade/webmcp.py) | Single FastMCP factory for stdio and MCP HTTP |
| [presentation](src/pgfacade/presentation) | CLI commands and request middleware |
| [shared](src/pgfacade/shared) | Shared scalar types and Pydantic configuration presets |
| [deploy](deploy) | Service units, updates, checks, backups, recovery |

The deployed service starts REST only. MCP HTTP tool calls authenticate independently; protocol discovery is not authenticated. See the [security verification record](deploy/SECURITY.md) for tested boundaries and remaining operational requirements.

For embedded MCP HTTP servers, use `pgfacade.webmcp.create_mcp_http_app()`; `create_mcp()` supplies the stdio and in-memory server. REST and the MCP HTTP app enforce `max_request_bytes` and `request_read_timeout_s`. The MCP CLI installs the same limits for both HTTP and SSE transports.

## Group-policy prototype and YAML/TOML settings

[File configuration and group policies](docs/access-control.md) documents the mock/stub identity interface, group-scoped rules, database configuration, and provider injection. Both YAML and TOML use Pydantic Settings. No Google lookup is implemented. The existing production API-key profile is unchanged unless `access_control` is explicitly configured.

An optional `startup_command` waits for a complete `READY` line from either stdout or stderr before opening the database. See [listener command configuration](docs/access-control.md#wait-for-a-listener-command).
