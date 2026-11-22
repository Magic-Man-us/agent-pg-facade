from __future__ import annotations

from argparse import Namespace
from unittest.mock import Mock

import pytest
from pydantic import ValidationError

from pgfacade.presentation.cli import main
from pgfacade.presentation.commands import CLI_COMMAND_ADAPTER, ApiCommand, CheckCommand, KeygenCommand, McpCommand, OpsCommand
from pgfacade.shared.types import CommandArgument, CommandArguments, ServerHost, ServerPort


@pytest.mark.parametrize(
    ("namespace", "expected"),
    [
        (Namespace(cmd="api", host="localhost", port="8080"), ApiCommand(host="localhost", port=8080)),
        (Namespace(cmd="mcp", transport="sse", host="localhost", port="8081"), McpCommand(transport="sse", host="localhost", port=8081)),
        (Namespace(cmd="ops"), OpsCommand()),
        (Namespace(cmd="keygen"), KeygenCommand()),
        (Namespace(cmd="check"), CheckCommand()),
    ],
)
def test_cli_adapter_validates_namespace(namespace: Namespace, expected: object) -> None:
    command = CLI_COMMAND_ADAPTER.validate_python(namespace, from_attributes=True)
    assert command == expected
    assert CLI_COMMAND_ADAPTER.validate_json(command.model_dump_json()) == command


@pytest.mark.parametrize("port", ["zero", "0", "65536", "-1", "123.5"])
def test_cli_port_rejected_by_model(port: CommandArgument) -> None:
    with pytest.raises(ValidationError):
        CLI_COMMAND_ADAPTER.validate_python(Namespace(cmd="api", host="localhost", port=port), from_attributes=True)


@pytest.mark.parametrize("arguments", [["api", "--port", "secret-input"], ["mcp", "--port", "65536"], ["api", "--host", ""]])
def test_invalid_cli_options_exit_without_echoing_values(arguments: CommandArguments, capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        main(arguments)
    assert exc.value.code == 2
    error = capsys.readouterr().err
    assert "Invalid command options" in error
    assert "secret-input" not in error


@pytest.mark.parametrize("arguments", [["--help"], ["api", "--help"], ["mcp", "--help"]])
def test_help_keeps_successful_exit(arguments: CommandArguments, capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        main(arguments)
    assert exc.value.code == 0
    assert "usage:" in capsys.readouterr().out


@pytest.mark.parametrize(
    "arguments,host,port", [(["api"], "127.0.0.1", 8000), (["api", "--host", "localhost", "--port", "9000"], "localhost", 9000)]
)
def test_api_dispatch_uses_validated_options(
    arguments: CommandArguments, host: ServerHost, port: ServerPort, monkeypatch: pytest.MonkeyPatch
) -> None:
    create_app = Mock()
    run = Mock()
    monkeypatch.setattr("pgfacade.webapp.create_app", create_app)
    monkeypatch.setattr("uvicorn.run", run)
    main(arguments)
    create_app.assert_called_once_with()
    run.assert_called_once_with(create_app.return_value, host=host, port=port)


@pytest.mark.parametrize("transport", ["http", "sse"])
def test_mcp_http_dispatch_preserves_transport_and_default_port(transport: CommandArgument, monkeypatch: pytest.MonkeyPatch) -> None:
    create_app = Mock()
    run = Mock()
    monkeypatch.setattr("pgfacade.webmcp.create_mcp_http_app", create_app)
    monkeypatch.setattr("uvicorn.run", run)
    main(["mcp", "--transport", transport])
    create_app.assert_called_once_with(transport=transport)
    run.assert_called_once_with(create_app.return_value, host="127.0.0.1", port=8001)


def test_mcp_default_dispatch_uses_stdio(monkeypatch: pytest.MonkeyPatch) -> None:
    create_mcp = Mock()
    monkeypatch.setattr("pgfacade.webmcp.create_mcp", create_mcp)
    main(["mcp"])
    create_mcp.assert_called_once_with()
    create_mcp.return_value.run.assert_called_once_with()


def test_check_reports_an_unreachable_database_and_fails(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setenv("PGFACADE_DSN", "postgresql://nobody:synthetic-private-password@127.0.0.1:9/absent")
    with pytest.raises(SystemExit) as exc:
        main(["check"])
    assert exc.value.code == 1
    captured = capsys.readouterr()
    assert captured.err.startswith("Could not connect to the database in PGFACADE_DSN:")
    assert "synthetic-private-password" not in captured.err + captured.out
