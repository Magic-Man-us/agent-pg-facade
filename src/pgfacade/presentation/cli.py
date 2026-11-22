"""CLI: `pgfacade api` (REST), `pgfacade mcp` (MCP over stdio or HTTP), `pgfacade ops`, `pgfacade keygen`."""

from __future__ import annotations

import argparse
import secrets
import sys

from pydantic import ValidationError

from pgfacade.presentation.commands import (
    CLI_COMMAND_ADAPTER,
    DEFAULT_API_PORT,
    DEFAULT_MCP_PORT,
    DEFAULT_MCP_TRANSPORT,
    DEFAULT_SERVER_HOST,
)
from pgfacade.presentation.enums import CliOperation
from pgfacade.shared.types import DEFAULT_API_KEY_ENTROPY_BYTES, CommandArguments, McpTransport


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

    try:
        command = CLI_COMMAND_ADAPTER.validate_python(parser.parse_args(argv), from_attributes=True)
    except ValidationError:
        parser.error("Invalid command options: host must be nonempty and port must be an integer between 1 and 65535")

    if command.cmd == CliOperation.KEYGEN:
        sys.stdout.write(secrets.token_urlsafe(DEFAULT_API_KEY_ENTROPY_BYTES) + "\n")
    elif command.cmd == CliOperation.OPS:
        from pgfacade.application.registry import REGISTRY

        width = max(len(op) for op in REGISTRY)
        for spec in REGISTRY.values():
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
