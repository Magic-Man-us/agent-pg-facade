from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, Field, TypeAdapter

from pgfacade.presentation.enums import CliOperation
from pgfacade.shared.config import CONTRACT_CONFIG
from pgfacade.shared.types import McpCliTransport, McpTransport, ServerHost, ServerPort

DEFAULT_SERVER_HOST: ServerHost = "127.0.0.1"
DEFAULT_API_PORT: ServerPort = 8000
DEFAULT_MCP_PORT: ServerPort = 8001
DEFAULT_MCP_TRANSPORT: McpCliTransport = McpTransport.STDIO


class ApiCommand(BaseModel):
    model_config = CONTRACT_CONFIG

    cmd: Literal[CliOperation.API] = CliOperation.API
    host: ServerHost = DEFAULT_SERVER_HOST
    port: ServerPort = DEFAULT_API_PORT


class McpCommand(BaseModel):
    model_config = CONTRACT_CONFIG

    cmd: Literal[CliOperation.MCP] = CliOperation.MCP
    transport: McpCliTransport = DEFAULT_MCP_TRANSPORT
    host: ServerHost = DEFAULT_SERVER_HOST
    port: ServerPort = DEFAULT_MCP_PORT


class OpsCommand(BaseModel):
    model_config = CONTRACT_CONFIG

    cmd: Literal[CliOperation.OPS] = CliOperation.OPS


class KeygenCommand(BaseModel):
    model_config = CONTRACT_CONFIG

    cmd: Literal[CliOperation.KEYGEN] = CliOperation.KEYGEN


CliCommand = Annotated[ApiCommand | McpCommand | OpsCommand | KeygenCommand, Field(discriminator="cmd")]
CLI_COMMAND_ADAPTER = TypeAdapter(CliCommand)
