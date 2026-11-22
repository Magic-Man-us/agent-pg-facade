from __future__ import annotations

from enum import StrEnum

import pytest
from pydantic import TypeAdapter, ValidationError

from pgfacade.application.context import ExecutionContext
from pgfacade.application.types import ExecutionProvenance
from pgfacade.authorization.enums import IdentitySource, PolicyEffect
from pgfacade.authorization.models import IdentityConfig, Policy
from pgfacade.configuration.database import DatabaseConfig
from pgfacade.configuration.enums import DatabaseBackend, SslMode
from pgfacade.infrastructure.postgres.queries.loader import parse_query_file
from pgfacade.infrastructure.postgres.queries.models import QueryFileRequest
from pgfacade.infrastructure.postgres.queries.types import ParamType
from pgfacade.presentation.commands import CLI_COMMAND_ADAPTER
from pgfacade.presentation.enums import CliOperation
from pgfacade.shared.types import McpTransport, PermissionName


def test_cli_boundary_preserves_command_and_transport_enum_instances() -> None:
    command = CLI_COMMAND_ADAPTER.validate_python({"cmd": "mcp", "transport": "http"})
    assert command.cmd is CliOperation.MCP
    assert command.transport is McpTransport.HTTP
    assert command.model_dump(mode="json")["cmd"] == "mcp"
    assert command.model_dump(mode="json")["transport"] == "http"
    with pytest.raises(ValidationError):
        CLI_COMMAND_ADAPTER.validate_python({"cmd": "mcp", "transport": "unknown"})


def test_database_boundary_preserves_backend_and_ssl_enum_instances() -> None:
    database = TypeAdapter(DatabaseConfig).validate_python(
        {"kind": "postgres", "user": "fixture", "dbname": "fixture", "sslmode": "verify-full"}
    )
    assert database.kind is DatabaseBackend.POSTGRES
    assert database.sslmode is SslMode.VERIFY_FULL
    assert database.model_dump(mode="json")["sslmode"] == "verify-full"


def test_identity_and_policy_discriminators_are_enum_members() -> None:
    identity = TypeAdapter(IdentityConfig).validate_python({"kind": "stub"})
    assert identity.kind is IdentitySource.STUB
    policy = TypeAdapter(Policy).validate_python(
        {"effect": "deny", "id": "blocked", "groups": ["team"], "connector": "local", "operations": ["rows.*"], "resources": ["app.*"]}
    )
    assert policy.effect is PolicyEffect.DENY
    assert policy.model_dump(mode="json")["effect"] == "deny"


def test_query_header_parameters_keep_their_declared_enum_types() -> None:
    query = parse_query_file(QueryFileRequest(text="-- param: enabled:bool=off Flag\nSELECT 1", name="custom.flag", source="fixture"))
    assert query.params["enabled"].type is ParamType.BOOLEAN
    assert query.validate_parameters({}, name="custom.flag") == {"enabled": False}
    assert query.model_dump(mode="json")["params"]["enabled"]["type"] == "bool"


def test_trusted_defaults_and_permission_names_use_enum_members() -> None:
    assert ExecutionContext().provenance is ExecutionProvenance.PYTHON
    assert issubclass(ExecutionProvenance, StrEnum)
    assert issubclass(PermissionName, StrEnum)
