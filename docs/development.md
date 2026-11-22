# Development

```sh
uv sync --locked
uv run --locked tox
uv run --locked tox -e py -- -q
```

The standard environments are `py`, `lint`, `type`, and `build`. Tests install a wheel; mypy checks the owning package's [source](../src/). Select an interpreter with `py312, py313, py314`. Interpreter setup failures are reported rather than skipped.

| Location | Owner |
| --- | --- |
| [src/pgfacade/](../src/pgfacade/) | Runtime code and resources shipped with the library |
| [tests/unit/](../tests/unit/) | Isolated models, clients, policies, and helpers |
| [tests/integration/](../tests/integration/) | Assembled transports, applications, and external services |
| [tests/conftest.py](../tests/conftest.py) | Shared test fixtures |
| [docs/](./) | Documentation and non-executable configuration samples |
| [deploy/](../deploy/) | Host or container deployment assets |

## Package organization

The package groups code by responsibility. Public imports such as `from pgfacade import MyApp, PgSettings` remain the entry point for library callers.

| Package | Responsibility |
| --- | --- |
| [application](../src/pgfacade/application/) | Trusted execution context, operation metadata, handlers, and failures |
| [contracts](../src/pgfacade/contracts/) | All public request/result models, wire envelopes, scalar aliases, and enums |
| [authorization](../src/pgfacade/authorization/) | Credential checks, identity providers, and group-policy decisions |
| [configuration](../src/pgfacade/configuration/) | Settings sources and database configuration variants |
| [infrastructure](../src/pgfacade/infrastructure/) | PostgreSQL engine, statements, query resources, and startup processes |
| [webapp.py](../src/pgfacade/webapp.py) | FastAPI application and REST routes |
| [webmcp.py](../src/pgfacade/webmcp.py) | FastMCP server for stdio and MCP HTTP |
| [presentation](../src/pgfacade/presentation/) | CLI and transport middleware |
| [shared](../src/pgfacade/shared/) | Reusable scalar types and model configuration presets |

Keep operation handlers in `application/operations/`. All SQL builders, composition helpers, and resources live in `infrastructure/postgres/queries/`. Handlers own permissions, transactions, execution, and response conversion; they do not construct SQL. Put transport parsing and serialization in `presentation/`; database connection and cursor handling belongs in `infrastructure/postgres/`. The console entry point is `pgfacade.presentation.cli:main`; `python -m pgfacade` delegates to it.

## SQL ownership

[queries/registry.py](../src/pgfacade/infrastructure/postgres/queries/registry.py) registers shipped SQL statements as `Statement` members. SQL files live under [queries/sql/](../src/pgfacade/infrastructure/postgres/queries/sql/), grouped by domain. Use `Statement.ROWS_SELECT.sql.format(...)` for composition or `.text` for a fixed statement. Values remain separate bound parameters; identifiers use `psycopg.sql.Identifier`.

The `Statement` registry also owns exposure: `QueryAccess.INTERNAL` is the default; public and admin queries are explicitly marked on their enum members. `query.list` and `query.run` derive their definitions from those registrations. SQL comment headers own descriptions, categories, parameter contracts, and extension requirements. Admin requirements remain attached to registered names when custom files override their SQL.

To add a statement, add its SQL resource and `Statement` member, compose it in the owning query-builder module, and call that builder from a typed handler registered with `@op`. Mark a curated read `QueryAccess.PUBLIC` or `QueryAccess.ADMIN` and declare its parameters in the SQL header. Curated reads run in read-only transactions that roll back. Arbitrary SQL remains separately permission gated and disabled by default.

```python
from pgfacade.infrastructure.postgres.queries import Statement

statement = Statement.ROWS_SELECT.sql
text = Statement.ADMIN_PING.text
```

Python, HTTP, and MCP invoke `MyApp.call(request)`. Its `singledispatchmethod` selects the typed operation handler; that handler references `Statement` resources. The SQL registry contains resources and metadata, never a second handler dispatcher.

[contracts/requests.py](../src/pgfacade/contracts/requests.py) owns request unions, response models, and batch schemas independently of handler registration. Domain request and result models live beside their validators under [contracts/](../src/pgfacade/contracts/).

[queries/models.py](../src/pgfacade/infrastructure/postgres/queries/models.py) owns query-file parameter validation; [queries/loader.py](../src/pgfacade/infrastructure/postgres/queries/loader.py) loads trusted operator query files. A custom `queries_dir` can override public query names; it cannot override internal statement resources. Keep that directory unwritable by API callers. Migration files remain trusted executable input outside this registry.

Custom files declare metadata before the SQL body:

```sql
-- description: Recent rows
-- category: custom
-- param: table:table Table to inspect
-- param: limit:int=50 Maximum rows
SELECT * FROM {table} LIMIT %(limit)s
```

Identifier parameters (`table`, `column`, `identifier`) use `{name}`; value parameters use `%(name)s`. Each table parameter resolves its own relation and also binds `%(name_regclass)s` as its quoted relation name. Column parameters use the single table parameter; multi-table definitions use identifier parameters for column references. Double literal braces in templates that declare identifiers.

Set `PGFACADE_TEST_DSN` to a disposable scratch database for database integration tests. Only tests explicitly marked as database-dependent are skipped when it is absent. CI provides PostgreSQL.

## Data ownership

Always use typed standard-library dataclasses for trusted internal domain records, execution contexts,
registry entries, metadata, and state. Use `slots=True`; use `frozen=True` for immutable records.
Services remain ordinary classes; connections, cursors, locks, and tasks retain their native types.

Use Pydantic v2 for boundary validation and serialization: API requests/responses/errors, settings,
raw database/file input, and messages. Use `BaseSettings` for settings and shared `ConfigDict` presets
from [shared/config.py](../src/pgfacade/shared/config.py) for boundary models. Define reusable constraints
and coercion in semantic aliases in the owning `types.py`.

Validate raw input once with `model_validate*()` or a reusable `TypeAdapter`, then pass typed values
internally without repeating validation. Adapters support model unions and subordinate fields; they never replace request/response models. Boundary DTOs retain their responsibility when passed internally; do not create identical
duplicate records merely to cross a function call. Serialize at egress with the boundary model or adapter.

Operation requests carry their result type through `RequestContract[Result]`.
[myapp.py](../src/pgfacade/myapp.py) owns `MyApp.call(request, context)` and its
`singledispatchmethod` executor. The catalog describes operations and does not execute handlers.
Startup checks compare concrete registrations, catalog contracts, and the request union.
Request subclasses inherit their registered base handler; inheritance resolving a different
operation handler is rejected before policy or execution.

Requests use `kind` and typed `input`; responses use matching `kind` and a typed `outcome`
discriminated by `status`. Python, HTTP, and [webmcp.py](../src/pgfacade/webmcp.py) share these
outcomes. Blocking Alembic operations run in worker threads. Batches and background lifecycle
workflows invoke the facade; streaming uses the application-owned `stream_events` interface.
Group-scoped event streaming remains unsupported and fails closed.

A transaction-bound view belongs to the task that opened it. Keep its calls in that task;
independent tasks use the shared facade and borrow separate pooled connections.

Follow the [error contract standard](errors.md) for exception classes, structured reasons and details,
status mapping, cancellation, privacy, and Python/HTTP/MCP parity tests.

Local build cache keys include package source, runtime resources, and package metadata.

Test malformed input and serialized output at boundaries. Test state and behavior for internal records. Measure representative workloads before claiming a performance improvement.

Keep generated environments and caches outside the importable package. Git ignores `.venv/`, `.tox/`, caches, and `dist/`. Do not create empty support folders to match another repository.

Every boundary operation declares explicit Pydantic request and response models, including empty requests, acknowledgments, scalar/collection results, and stream items/errors. Trusted internal calls remain dataclass-based. Closed-set string values always use `StrEnum`; discriminator fields use `Literal[SpecificStrEnum.MEMBER]` and callable branches use `Tag(SpecificStrEnum.MEMBER)`. Field selectors such as `discriminator="kind"`, human text, and open-ended semantic strings are permitted.
## Tool metadata consistency

MCP annotations are built directly on each tool registration. The catalog owns operation
classification and independent idempotency metadata; annotations never grant permissions or
change retry behavior. Overwrites, renames, revocations, replacements, and removals are
non-additive and use the destructive hint. Query-cache reload is a repeat-safe mutation;
other mutations retain conservative non-idempotent defaults unless explicitly declared.
Database tools retain a closed-domain annotation rather than copying the open-world value
used by an external service API.

`sql.explain`, including `analyze=true`, executes in a read-only transaction that rolls back,
matching the advertised read-only tool behavior and the raw-query transaction policy.
Analyzing a statement that would write persistent data is rejected by PostgreSQL.

## Transport entry points

`pgfacade.webapp:create_app` is the single FastAPI factory.
`pgfacade.webmcp:create_mcp` is the single FastMCP factory; its HTTP/SSE wrapper calls
that same factory. Both accept the shared `MyApp` and delegate typed operation calls to it.
The CLI, service unit, and tests import those canonical modules. Implementation paths
`pgfacade.mcpapp` and `pgfacade.presentation.http` have been replaced by these entry points.

CI runs the PostgreSQL matrix for pull requests and pushes to `main`. Feature-branch pushes
are covered by the pull request run, avoiding a duplicate copy of the same matrix.
