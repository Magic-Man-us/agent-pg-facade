from __future__ import annotations

import ast
from pathlib import Path

import pytest
from pydantic import TypeAdapter, ValidationError

import pgfacade
from pgfacade.contracts.admin import SettingInfo
from pgfacade.contracts.base import Cmp, Done, Filter, OrderBy, TextSearch
from pgfacade.contracts.enums import (
    CmpOp,
    ConstraintType,
    FilterKind,
    GrantedPrivilege,
    LifecycleAction,
    NullOrder,
    OnDelete,
    OperationHint,
    OperationStatus,
    ParamType,
    RelationType,
    SettingContext,
    StreamOperation,
    TextSearchMode,
    WatchEvent,
)
from pgfacade.contracts.events import EventWatchInput
from pgfacade.contracts.lifecycle import DeleteRows, LifecycleRowTtlInput, RowAgeInput
from pgfacade.contracts.queries import QueryParam
from pgfacade.contracts.roles import PrivilegeInfo
from pgfacade.contracts.rows import RowsSelect
from pgfacade.contracts.schema import ConstraintInfo, ForeignRef, TableInfo
from pgfacade.contracts.streaming import EventStreamInput, EventStreamRequest


def test_nested_filter_choices_keep_enum_members_and_wire_strings() -> None:
    request = RowsSelect.model_validate(
        {"kind": "rows.select", "input": {"table": "items", "where": [{"kind": "cmp", "column": "score", "op": "gte", "value": 1}]}}
    )
    comparison = request.input.where[0]
    assert isinstance(comparison, Cmp)
    assert comparison.kind is FilterKind.CMP
    assert comparison.op is CmpOp.GTE
    assert request.model_dump(mode="json")["input"]["where"] == [{"kind": "cmp", "column": "score", "op": "gte", "value": 1}]
    assert RowsSelect.model_validate_json(request.model_dump_json()) == request
    assert TypeAdapter(Filter).json_schema()["discriminator"]["mapping"].keys() == {member.value for member in FilterKind}


def test_default_choices_are_enum_members_without_call_site_coercion() -> None:
    assert Cmp(column="score", value=1).op is CmpOp.EQ
    assert TextSearch(column="body", query="hello").mode is TextSearchMode.WEBSEARCH
    assert OrderBy(column="score", nulls="last").nulls is NullOrder.LAST
    assert EventWatchInput(table="items").events == [WatchEvent.INSERT, WatchEvent.UPDATE, WatchEvent.DELETE]
    assert all(isinstance(event, WatchEvent) for event in EventWatchInput(table="items").events)
    assert LifecycleRowTtlInput(table="items", expiry=RowAgeInput(column="created_at", ttl="7 days")).action == DeleteRows()
    assert DeleteRows().kind is LifecycleAction.DELETE
    assert ForeignRef(table="parent", column="id", on_delete="cascade").on_delete is OnDelete.CASCADE


def test_stream_kinds_and_application_statuses_are_declared_once() -> None:
    request = EventStreamRequest(input=EventStreamInput(channels=["events"]))
    assert request.kind is StreamOperation.EVENT_STREAM
    assert request.model_dump(mode="json")["kind"] == "event.stream"
    assert Done(status="INSTALLED").status is OperationStatus.INSTALLED
    assert Done(status="CREATE TABLE").status == "CREATE TABLE"
    assert OperationHint.DESTRUCTIVE.value == "destructive"
    assert QueryParam(name="count", type="int", required=False, default=2, description="Rows").type is ParamType.INTEGER


def test_domain_literals_only_reference_enum_members() -> None:
    package = Path(pgfacade.__file__).parent
    files = [
        *package.joinpath("contracts").glob("*.py"),
        *package.joinpath("application/operations").glob("*.py"),
        package / "contracts/streaming.py",
    ]
    violations = []
    for file in files:
        for node in ast.walk(ast.parse(file.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Subscript) and isinstance(node.value, ast.Name) and node.value.id == "Literal":
                values = node.slice.elts if isinstance(node.slice, ast.Tuple) else [node.slice]
                if any(isinstance(value, ast.Constant) and isinstance(value.value, str) for value in values):
                    violations.append(f"{file.name}:{node.lineno}")
    assert not violations


def test_catalog_descriptions_preserve_all_known_relation_and_constraint_wire_values() -> None:
    for kind in RelationType:
        value = TableInfo.model_validate(
            {"schema_name": "app", "name": "items", "kind": kind.value, "owner": "owner", "est_rows": 0, "total_bytes": 0}
        )
        assert value.kind is kind
        assert value.model_dump(mode="json")["kind"] == kind.value
    for kind in ConstraintType:
        value = ConstraintInfo.model_validate({"name": "constraint", "type": kind.value, "definition": "definition"})
        assert value.type is kind
        assert value.model_dump(mode="json")["type"] == kind.value


@pytest.mark.parametrize("context", SettingContext)
def test_setting_contexts_preserve_enum_identity_and_wire_values(context: SettingContext) -> None:
    value = SettingInfo.model_validate(
        {"name": "setting", "value": "value", "category": "category", "context": context.value, "description": "description"}
    )
    assert value.context is context
    assert value.model_dump(mode="json")["context"] == context.value
    assert SettingInfo.model_validate_json(value.model_dump_json()) == value


@pytest.mark.parametrize("privilege", GrantedPrivilege)
def test_granted_privileges_keep_upstream_uppercase_labels(privilege: GrantedPrivilege) -> None:
    value = PrivilegeInfo.model_validate({"grantee": "role", "privilege": privilege.value, "grantable": False})
    assert value.privilege is privilege
    assert value.model_dump(mode="json")["privilege"] == privilege.value
    assert PrivilegeInfo.model_validate_json(value.model_dump_json()) == value


def test_catalog_choices_reject_unknown_contexts_and_noncanonical_privileges() -> None:
    with pytest.raises(ValidationError):
        SettingInfo.model_validate(
            {"name": "setting", "value": "value", "category": "category", "context": "unknown", "description": "description"}
        )
    with pytest.raises(ValidationError):
        PrivilegeInfo.model_validate({"grantee": "role", "privilege": "select", "grantable": False})
    assert GrantedPrivilege.MAINTAIN.value == "MAINTAIN"
