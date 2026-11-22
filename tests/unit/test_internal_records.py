from __future__ import annotations

from dataclasses import FrozenInstanceError, fields, is_dataclass

import pytest
from pydantic import ValidationError

from pgfacade import ExecutionContext, Perm
from pgfacade.application.registry import REGISTRY
from pgfacade.authorization.models import AuthorizationContext, AuthorizationDecision, ExecutionIdentity, OperationTarget
from pgfacade.contracts.enums import Operation
from pgfacade.infrastructure.postgres.models import TableMetadataResponse
from pgfacade.infrastructure.postgres.queries.composition import Column, TableMeta
from pgfacade.infrastructure.postgres.types import KnownPostgresTypeCategory, RelationKind


def test_catalog_row_adapter_validates_and_coerces_into_column_record() -> None:
    response = TableMetadataResponse.model_validate(
        {"columns": [{"name": "id", "regtype": "integer", "category": "N", "pk_pos": "1", "relkind": "r"}]}
    )
    column = response.columns[0]
    assert is_dataclass(column)
    assert column.pk_pos == 1
    assert TableMetadataResponse.model_validate_json(response.model_dump_json()) == response
    assert column.cast.as_string() == "integer"


@pytest.mark.parametrize(
    "row",
    [
        {"name": "id", "regtype": "integer", "category": "N", "pk_pos": True, "relkind": "r"},
        {"name": "id", "regtype": "integer", "category": "N", "pk_pos": -1, "relkind": "r"},
        {"name": "id", "regtype": "integer", "category": "N", "pk_pos": 1, "relkind": "too-long"},
        {"name": "id", "regtype": "integer", "category": "N", "pk_pos": 1},
        {"name": "id", "regtype": "integer", "category": "N", "pk_pos": 1, "relkind": "r", "extra": True},
    ],
)
def test_catalog_row_adapter_rejects_invalid_database_metadata(row: object) -> None:
    with pytest.raises(ValidationError):
        TableMetadataResponse.model_validate({"columns": [row]})


def test_internal_records_are_frozen_and_slotted() -> None:
    column = Column(name="id", regtype="integer", category=KnownPostgresTypeCategory.NUMERIC, pk_pos=1, relkind=RelationKind.TABLE)
    table = TableMeta(schema_name="app", name="notes", kind=RelationKind.TABLE, columns={column.name: column}, primary_key=(column.name,))
    context = AuthorizationContext(connector="local", default_schema="app")
    target = OperationTarget(operation=Operation.ROWS_SELECT, resource="app.notes")
    decision = AuthorizationDecision(execution_identity="reader", profile=ExecutionIdentity(role="reader"))
    for record in (column, table, context, target, decision, ExecutionContext(), Perm(), REGISTRY[Operation.ROWS_SELECT]):
        assert is_dataclass(record)
        assert set(type(record).__slots__) == {field.name for field in fields(record)}
    assert table.ident.as_string() == '"app"."notes"'
    assert table.label == "app.notes"
    with pytest.raises(FrozenInstanceError):
        column.name = "changed"  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        context.connector = "changed"  # type: ignore[misc]
