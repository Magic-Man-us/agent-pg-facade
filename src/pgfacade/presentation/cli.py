"""CLI: `pgfacade api` (REST), `pgfacade mcp` (MCP over stdio or HTTP), `pgfacade check`, `pgfacade ops`, `pgfacade keygen`."""

from __future__ import annotations

import argparse
import asyncio
import secrets
import sys

import psycopg
from pydantic import ValidationError

from pgfacade.presentation.commands import (
    CLI_COMMAND_ADAPTER,
    DEFAULT_API_PORT,
    DEFAULT_MCP_PORT,
    DEFAULT_MCP_TRANSPORT,
    DEFAULT_SERVER_HOST,
)
from pgfacade.presentation.enums import CliOperation
from pgfacade.shared.types import DEFAULT_API_KEY_ENTROPY_BYTES, CommandArguments, McpTransport, PoolTimeoutSeconds

CHECK_TIMEOUT_S: PoolTimeoutSeconds = 10.0
CHECK_FAILED = 1


async def _check() -> int:
    from pgfacade.configuration.settings import PgSettings
    from pgfacade.contracts.admin import ServerInfoGet, ServerInfoGetInput
    from pgfacade.contracts.envelopes import Failure
    from pgfacade.contracts.schema import TableList, TableListInput
    from pgfacade.facade import PgFacade

    settings = PgSettings(pool_min=1, pool_max=1, pool_timeout_s=CHECK_TIMEOUT_S)
    try:
        # One direct attempt reports the driver's reason at once; the pool would retry and report only a timeout.
        probe = await psycopg.AsyncConnection.connect(settings.dsn.get_secret_value(), connect_timeout=int(CHECK_TIMEOUT_S))
        await probe.close()
        async with PgFacade(settings) as app:
            info = await app.call(ServerInfoGet(input=ServerInfoGetInput()))
            tables = await app.call(TableList(input=TableListInput()))
            tools = len(app.allowed_ops())
    except psycopg.Error as error:
        sys.stderr.write(f"Could not connect to the database in PGFACADE_DSN: {error}\n")
        return CHECK_FAILED
    if isinstance(info.outcome, Failure) or isinstance(tables.outcome, Failure):
        failed = info if isinstance(info.outcome, Failure) else tables
        sys.stderr.write(f"Connected, but {failed.kind} failed\n")
        return CHECK_FAILED
    server = info.outcome.data
    sys.stdout.write(f"Connected to {server.database} as {server.user} (PostgreSQL {server.server_version})\n")
    sys.stdout.write(f"Mode: {'read-only' if settings.read_only else 'read-write'}\n")
    sys.stdout.write(f"Tables visible: {len(tables.outcome.data.items)}\n")
    sys.stdout.write(f"Tools exposed: {tools}\n")
    return 0


def main(argv: CommandArguments | None = None) -> None:
    parser = argparse.ArgumentParser(prog="pgfacade")
    sub = parser.add_subparsers(dest="cmd", required=True)

    api = sub.add_parser(CliOperation.API, help="serve the REST API")
    api.add_argument("--host", default=DEFAULT_SERVER_HOST)
    api.add_argument("--port", default=DEFAULT_API_PORT)

    mcp = sub.add_parser(CliOperation.MCP, help="serve the MCP server")
    mcp.add_argument("--transport", choices=[McpTransport.STDIO, McpTransport.HTTP, McpTransport.SSE], default=DEFAULT_MCP_TRANSPORT)
    mcp.add_argument("--host", default=DEFAULT_SERVER_HOST)
    mcp.add_argument("--port", default=DEFAULT_MCP_PORT)

    sub.add_parser(CliOperation.OPS, help="list registered operations")
    sub.add_parser(CliOperation.KEYGEN, help="print a random API key for PGFACADE_KEYS")
    sub.add_parser(CliOperation.CHECK, help="connect to PGFACADE_DSN and report what an assistant will see")

    try:
        command = CLI_COMMAND_ADAPTER.validate_python(parser.parse_args(argv), from_attributes=True)
    except ValidationError:
        parser.error("Invalid command options: host must be nonempty and port must be an integer between 1 and 65535")

    if command.cmd == CliOperation.KEYGEN:
        sys.stdout.write(secrets.token_urlsafe(DEFAULT_API_KEY_ENTROPY_BYTES) + "\n")
    elif command.cmd == CliOperation.CHECK:
        sys.exit(asyncio.run(_check()))
    elif command.cmd == CliOperation.OPS:
        from pgfacade.application.registry import OPERATIONS

        width = max(len(op) for op in OPERATIONS)
        for spec in OPERATIONS.values():
            flags = ",".join(spec.perm.flags()) or "read"
            sys.stdout.write(f"{spec.op:<{width}}  {flags:<22} {spec.summary}\n")
    elif command.cmd == CliOperation.API:
        import uvicorn

        from pgfacade.webapp import create_app

        uvicorn.run(create_app(), host=command.host, port=command.port)
    elif command.cmd == CliOperation.MCP:
        if command.transport == McpTransport.STDIO:
            from pgfacade.webmcp import create_mcp

            create_mcp().run()
        else:
            import uvicorn

            from pgfacade.webmcp import create_mcp_http_app

            uvicorn.run(create_mcp_http_app(transport=command.transport), host=command.host, port=command.port)


if __name__ == "__main__":
    main()
