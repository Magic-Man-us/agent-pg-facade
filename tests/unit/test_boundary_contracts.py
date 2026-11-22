from __future__ import annotations

import ast
from pathlib import Path

import pytest
from pydantic import ValidationError

import pgfacade
from pgfacade.configuration.settings import CredentialFileRequest, CredentialFileResponse, _read_credentials
from pgfacade.contracts.discovery import LivenessRequest, LivenessResponse, OperationDiscoveryRequest, OperationDiscoveryResponse
from pgfacade.infrastructure.postgres.queries.models import QueryFileRequest
from pgfacade.infrastructure.postgres.queries.registry import SqlResourceRequest, SqlResourceResponse, Statement


def test_empty_and_collection_boundaries_declare_models() -> None:
    assert LivenessRequest.model_validate({}).model_dump() == {}
    assert LivenessResponse.model_validate({"ok": True}).model_dump() == {"ok": True, "message": None}
    assert OperationDiscoveryRequest.model_validate({}).model_dump() == {}
    assert OperationDiscoveryResponse.model_validate_json("[]").root == []
    with pytest.raises(ValidationError):
        OperationDiscoveryRequest.model_validate({"unexpected": True})


def test_credential_file_has_request_and_response_contracts(tmp_path: Path) -> None:
    response = CredentialFileResponse.model_validate({"fixture-key": {"name": "reader", "read_only": True}})
    path = tmp_path / "credentials.json"
    path.write_text(response.model_dump_json(), encoding="utf-8")
    received = _read_credentials(CredentialFileRequest(path=path))
    assert received.root["fixture-key"].name == "reader"
    assert received.root["fixture-key"].read_only
    assert "fixture-key" not in repr(received)
    with pytest.raises(ValidationError):
        CredentialFileResponse.model_validate({"fixture-key": {"read_only": "invalid"}})


def test_sql_file_boundaries_validate_declared_requests_and_responses() -> None:
    request = SqlResourceRequest.model_validate({"statement": Statement.ROWS_SELECT.value})
    assert request.statement is Statement.ROWS_SELECT
    assert SqlResourceResponse(text=request.statement.text).text
    with pytest.raises(ValidationError):
        SqlResourceResponse(text="")
    with pytest.raises(ValidationError):
        QueryFileRequest.model_validate({"name": "custom.query", "source": "fixture"})


def test_closed_string_choices_use_enum_members_in_literal_fields() -> None:
    package = Path(pgfacade.__file__).parent
    violations = []
    for source in package.rglob("*.py"):
        for node in ast.walk(ast.parse(source.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Subscript) and isinstance(node.value, ast.Name) and node.value.id in {"Literal", "Tag"}:
                values = node.slice.elts if isinstance(node.slice, ast.Tuple) else [node.slice]
                if any(isinstance(value, ast.Constant) and isinstance(value.value, str) for value in values):
                    violations.append(f"{source.relative_to(package)}:{node.lineno}")
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "Tag":
                if any(isinstance(value, ast.Constant) and isinstance(value.value, str) for value in node.args):
                    violations.append(f"{source.relative_to(package)}:{node.lineno}")
            if isinstance(node, ast.keyword) and node.arg == "use_enum_values" and isinstance(node.value, ast.Constant):
                assert node.value.value is not True
    assert not violations, f"Closed string choices need StrEnum members: {violations}"
