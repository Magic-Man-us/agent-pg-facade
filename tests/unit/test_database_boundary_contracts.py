from __future__ import annotations

from dataclasses import is_dataclass

import pytest
from pydantic import ValidationError

from pgfacade.infrastructure.postgres.models import TableMetadataRequest, TableMetadataResponse
from pgfacade.infrastructure.postgres.types import RelationKind


def test_metadata_request_serializes_validated_identifier_fields() -> None:
    request = TableMetadataRequest.model_validate({"schema_name": "app", "table_name": 'odd"table'})
    assert TableMetadataRequest.model_validate_json(request.model_dump_json()) == request
    with pytest.raises(ValidationError):
        TableMetadataRequest.model_validate({"schema_name": "app", "table_name": "bad\x00name"})
    with pytest.raises(ValidationError):
        TableMetadataRequest.model_validate({"schema_name": "app", "table_name": "items", "extra": True})


def test_metadata_response_owns_catalog_row_validation_and_serialization() -> None:
    response = TableMetadataResponse.model_validate(
        {"columns": [{"name": "id", "regtype": "integer", "category": "N", "pk_pos": "1", "relkind": "r"}]}
    )
    column = response.columns[0]
    assert is_dataclass(column)
    assert column.pk_pos == 1
    assert column.relkind is RelationKind.TABLE
    assert response.model_dump(mode="json")["columns"][0]["relkind"] == "r"
    assert TableMetadataResponse.model_validate_json(response.model_dump_json()) == response


def test_custom_postgresql_type_categories_remain_open_codes() -> None:
    response = TableMetadataResponse.model_validate(
        {"columns": [{"name": "custom", "regtype": "custom_type", "category": "Y", "pk_pos": None, "relkind": "r"}]}
    )
    assert response.columns[0].category == "Y"
    assert not response.columns[0].is_array


def test_unknown_relation_kinds_are_rejected_at_the_database_boundary() -> None:
    with pytest.raises(ValidationError):
        TableMetadataResponse.model_validate(
            {"columns": [{"name": "id", "regtype": "integer", "category": "N", "pk_pos": 1, "relkind": "?"}]}
        )


def test_declared_comparison_choice_stays_separate_from_bound_values() -> None:
    from pgfacade.contracts.base import Cmp
    from pgfacade.contracts.enums import CmpOp
    from pgfacade.infrastructure.postgres.queries.composition import Binder, TableMeta, filter_sql

    column = TableMetadataResponse.model_validate(
        {"columns": [{"name": "id", "regtype": "integer", "category": "N", "pk_pos": 1, "relkind": "r"}]}
    ).columns[0]
    meta = TableMeta(schema_name="app", name="items", kind=RelationKind.TABLE, columns={column.name: column}, primary_key=(column.name,))
    binder = Binder(meta)
    comparison = Cmp(column="id", op=CmpOp.GTE, value=3)
    statement = filter_sql(comparison, binder)
    assert comparison.op is CmpOp.GTE
    assert statement.as_string() == '"id" >= %s::integer'
    assert binder.params == [3]
