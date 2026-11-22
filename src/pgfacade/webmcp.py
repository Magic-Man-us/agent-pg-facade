from __future__ import annotations

import inspect
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from contextlib import asynccontextmanager
from typing import Annotated, Literal, Union

from fastmcp import FastMCP
from fastmcp.exceptions import DisabledError, NotFoundError
from fastmcp.exceptions import ValidationError as ToolValidationError
from fastmcp.server.dependencies import get_http_request
from fastmcp.server.http import StarletteWithLifespan
from fastmcp.server.middleware import CallNext, Middleware, MiddlewareContext
from fastmcp.tools import Tool, ToolResult
from mcp import types as mt
from pydantic import Field, JsonValue, ValidationError, create_model
from starlette.middleware import Middleware as ASGIMiddleware

from pgfacade import __version__
from pgfacade.application.context import ExecutionContext
from pgfacade.application.errors import NotFound, RequestValidationFailure, error_payload, failure
from pgfacade.application.registry import OpSpec
from pgfacade.application.types import ExecutionProvenance
from pgfacade.authorization.credentials import bearer_token
from pgfacade.authorization.providers import IdentityProvider, authenticate, configure_identity_provider
from pgfacade.configuration.settings import ANONYMOUS, PgSettings
from pgfacade.contracts.base import Contract, RequestContract
from pgfacade.contracts.enums import Operation, OperationHint
from pgfacade.contracts.envelopes import Failure
from pgfacade.contracts.requests import Batch
from pgfacade.contracts.schema import TableList, TableListInput
from pgfacade.contracts.types import NonEmptyItems
from pgfacade.infrastructure.startup import startup_command
from pgfacade.myapp import MyApp
from pgfacade.presentation.middleware import RequestBodyLimit
from pgfacade.shared.enums import McpTransport
from pgfacade.shared.types import McpHttpTransport, McpLifespanState

INSTRUCTIONS = """\
PostgreSQL access. Address tables as "table" (default schema) or "schema.table".
Start with pg_server_whoami to learn your role and permissions, and pg_table_describe before querying
an unfamiliar table. Filters (`where`) are objects tagged by `kind`: cmp {column, op, value},
in {column, values}, is_null {column}, between {column, low, high}, contains {column, value},
text_search {column, query}, and/or {filters}, not {filter}. `match` is an equality shorthand.
Each tool accepts {"request": {"kind": "operation.name", "input": {...}}}. Responses contain
matching kind and outcome.status="success" with data, or outcome.status="error" with a typed error.
Error results set isError. Reads are capped by max_rows; check `outcome.data.truncated`. Prefer structured tools over raw SQL.
Use pg_batch_run for multi-step atomic changes, pg_query_run for curated diagnostics, and
pg_migration_revision + pg_migration_run for schema changes in a tracked project.
"""


_TABLE_SUMMARY_LIMIT = 50


async def _table_summary(db: MyApp) -> str:
    response = await db.call(TableList(input=TableListInput(limit=_TABLE_SUMMARY_LIMIT)))
    if isinstance(response.outcome, Failure) or not response.outcome.data.items:
        return ""
    tables = response.outcome.data.items
    lines = [f"{t.schema_name}.{t.name} (~{t.est_rows} rows)" if t.est_rows >= 0 else f"{t.schema_name}.{t.name}" for t in tables]
    scope = f"first {_TABLE_SUMMARY_LIMIT} by name; pg_table_list returns all" if len(tables) == _TABLE_SUMMARY_LIMIT else "all"
    return f"\nTables when this session started ({scope}):\n" + "\n".join(lines) + "\n"


class _Errors(Middleware):
    async def on_call_tool(
        self, context: MiddlewareContext[mt.CallToolRequestParams], call_next: CallNext[mt.CallToolRequestParams, ToolResult]
    ) -> ToolResult:
        try:
            return await call_next(context)
        except ToolValidationError as exc:
            error = exc.__cause__
            failure_response = (
                error_payload(RequestValidationFailure(error))
                if isinstance(error, ValidationError)
                else failure(422, "Request validation failed")
            )
            return ToolResult(structured_content=failure_response, is_error=True)
        except (DisabledError, NotFoundError):
            return ToolResult(structured_content=error_payload(NotFound("Unknown or unavailable operation")), is_error=True)
        except Exception as exc:
            return ToolResult(structured_content=error_payload(exc), is_error=True)


async def resolve_mcp_context(settings: PgSettings, provider: IdentityProvider | None = None) -> ExecutionContext:
    try:
        request = get_http_request()
    except RuntimeError:
        if not settings.auth_enabled:
            # A stdio session with no configured keys is the process owner, the same trust as a direct library call.
            return ExecutionContext(principal=ANONYMOUS, provenance=ExecutionProvenance.MCP)
        key = settings.mcp_key.get_secret_value() if settings.mcp_key is not None else None
    else:
        key = bearer_token(dict(request.headers))
    return ExecutionContext(principal=await authenticate(settings, key, provider), provenance=ExecutionProvenance.MCP)


def _tool_for(spec: OpSpec, app: MyApp, resolve_context: Callable[[], Awaitable[ExecutionContext]]) -> Callable[..., Awaitable[ToolResult]]:
    async def tool(request: RequestContract[Contract]) -> ToolResult:
        try:
            context = await resolve_context()
        except Exception as error:
            return ToolResult(structured_content=error_payload(error), is_error=True)
        result = await app.call(request, context)
        return ToolResult(structured_content=result, is_error=isinstance(result.outcome, Failure))

    # FastMCP discovers concrete schemas through the runtime operation catalog.
    tool.__signature__ = inspect.Signature(  # type: ignore[attr-defined]
        [inspect.Parameter("request", inspect.Parameter.KEYWORD_ONLY, annotation=spec.request)], return_annotation=spec.envelope
    )
    tool.__annotations__ = {"request": spec.request, "return": spec.envelope}
    tool.__name__ = f"pg_{spec.area}_{spec.action}"
    tool.__doc__ = spec.summary
    return tool


def _batch_parameters(specs: Sequence[OpSpec]) -> dict[str, JsonValue]:
    """Advertise only the operations this server exposes; the Batch contract embeds the whole catalog."""
    children = tuple(spec.request for spec in specs if spec.op != Operation.BATCH_RUN)
    # Pydantic builds a union from a runtime tuple only through typing.Union.
    child = Annotated[Union[children], Field(discriminator="kind")]  # type: ignore[valid-type]  # noqa: UP007
    batch_input = create_model("BatchInput", __base__=Contract, requests=(NonEmptyItems[child], ...))
    batch = create_model(
        "Batch",
        __base__=Contract,
        __doc__=Batch.__doc__,
        kind=(Literal[Operation.BATCH_RUN], Operation.BATCH_RUN),  # type: ignore[arg-type]  # Runtime literal field.
        input=(batch_input, ...),
    )
    return create_model("BatchArguments", __base__=Contract, request=(batch, ...)).model_json_schema()


def create_mcp(settings: PgSettings | None = None, db: MyApp | None = None, identity_provider: IdentityProvider | None = None) -> FastMCP:
    settings = settings or (db.settings if db is not None else PgSettings())
    if db is not None and db.settings != settings:
        raise ValueError("The supplied facade must use the server settings")
    provider = configure_identity_provider(settings, identity_provider)
    db = db or MyApp(settings)
    discovery = ExecutionContext(principal=ANONYMOUS, provenance=ExecutionProvenance.MCP)

    @asynccontextmanager
    async def lifespan(_: FastMCP) -> AsyncIterator[McpLifespanState]:
        async with startup_command(settings.startup_command), db:
            if not settings.auth_enabled:
                # Keyless sessions have one local principal, so its table list is safe to send before authentication.
                mcp.instructions = INSTRUCTIONS + await _table_summary(db)
            yield {}

    mcp = FastMCP(
        "postgres",
        instructions=INSTRUCTIONS,
        version=__version__,
        lifespan=lifespan,
        middleware=[_Errors()],
        dereference_schemas=False,
    )

    async def resolve_context() -> ExecutionContext:
        return await resolve_mcp_context(settings, provider)

    specs = db.allowed_ops(discovery)
    writable = any(spec.perm.write for spec in specs)
    for spec in specs:
        # A batch can do only what its children can, so it is a read on a server that exposes no write operation.
        hint = OperationHint.READ if spec.op == Operation.BATCH_RUN and not writable else spec.hint
        tool = Tool.from_function(
            _tool_for(spec, db, resolve_context),
            name=f"pg_{spec.area}_{spec.action}",
            annotations=mt.ToolAnnotations(
                read_only_hint=hint == OperationHint.READ,
                destructive_hint=hint == OperationHint.DESTRUCTIVE,
                idempotent_hint=spec.idempotent or hint == OperationHint.READ,
                open_world_hint=False,
            ),
            tags={spec.area},
            output_schema=spec.envelope.model_json_schema(mode="serialization"),
        )
        if spec.op == Operation.BATCH_RUN:
            tool.parameters = _batch_parameters(specs)
        mcp.add_tool(tool)

    return mcp


def create_mcp_http_app(
    settings: PgSettings | None = None,
    db: MyApp | None = None,
    identity_provider: IdentityProvider | None = None,
    *,
    transport: McpHttpTransport = McpTransport.HTTP,
) -> StarletteWithLifespan:
    settings = settings or (db.settings if db is not None else PgSettings())
    if not settings.auth_enabled:
        raise ValueError("API keys or access_control must be configured before starting a server")
    server = create_mcp(settings, db, identity_provider)
    middleware = ASGIMiddleware(RequestBodyLimit, max_bytes=settings.max_request_bytes, timeout_s=settings.request_read_timeout_s)
    return server.http_app(
        transport=transport.value,  # type: ignore[arg-type]  # FastMCP declares the same wire values as string literals.
        middleware=[middleware],
    )
