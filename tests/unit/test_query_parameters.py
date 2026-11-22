from __future__ import annotations

import pytest
from pydantic import ValidationError

from pgfacade import InvalidRequest
from pgfacade.application.errors import RequestValidationFailure, error_payload
from pgfacade.infrastructure.postgres.queries.loader import parse_query_file
from pgfacade.infrastructure.postgres.queries.models import Param, QueryDefinition, QueryFileRequest
from pgfacade.infrastructure.postgres.queries.types import ParameterValue, ParamType


@pytest.mark.parametrize(
    ("kind", "raw", "expected"),
    [
        ("int", "42", 42),
        ("float", "1.5", 1.5),
        ("bool", "true", True),
        ("bool", "off", False),
        ("bool", "no", False),
        ("bool", "0", False),
        ("text", "hello", "hello"),
        ("table", "public.notes", "public.notes"),
    ],
)
def test_parameter_models_coerce_declared_scalar_types(kind: ParamType, raw: ParameterValue, expected: ParameterValue) -> None:
    query = QueryDefinition(category="custom", description="", sql="SELECT %(value)s", params={"value": Param(type=kind, required=True)})
    result = query.validate_parameters({"value": raw}, name="custom.scalar")
    assert result == {"value": expected}
    assert type(result["value"]) is type(expected)


@pytest.mark.parametrize(
    ("kind", "raw"),
    [
        ("bool", "not-a-boolean"),
        ("bool", 2),
        ("int", True),
        ("int", 1.5),
        ("float", True),
        ("float", float("nan")),
        ("float", float("inf")),
        ("text", 3),
        ("table", 123),
        ("identifier", ""),
    ],
)
def test_parameters_reject_misleading_values(kind: ParamType, raw: ParameterValue) -> None:
    query = QueryDefinition(category="custom", description="", sql="SELECT 1", params={"value": Param(type=kind, required=True)})
    with pytest.raises(InvalidRequest, match=f"must be {kind}"):
        query.validate_parameters({"value": raw}, name="custom.scalar")


def test_parameter_defaults_and_required_values_share_validation() -> None:
    query = parse_query_file(
        QueryFileRequest(
            text="-- param: table:table=public.notes Table\n-- param: enabled:bool=off Flag\n-- param: count:int=2 Count\nSELECT 1",
            name="custom.defaults",
            source="builtin",
        )
    )
    assert query.validate_parameters({}, name="custom.defaults") == {"table": "public.notes", "enabled": False, "count": 2}
    assert query.params["enabled"].model_dump() == {"type": "bool", "default": False, "description": "Flag", "required": False}
    schema = query.parameter_model.model_json_schema()
    assert schema["additionalProperties"] is False
    assert schema["properties"]["enabled"]["anyOf"][0]["type"] == "boolean"


@pytest.mark.parametrize("header", ["-- param: flag:bool=nonsense", "-- param: n:int=2.5", "-- param: x:unknown=1"])
def test_query_files_reject_invalid_types_and_defaults(header: str) -> None:
    with pytest.raises(InvalidRequest, match="Invalid query parameter declaration"):
        parse_query_file(QueryFileRequest(text=f"{header}\nSELECT 1", name="custom.bad", source="builtin"))


def test_required_and_unknown_parameters_are_rejected() -> None:
    query = QueryDefinition(category="custom", description="", sql="SELECT 1", params={"table": Param(type="table", required=True)})
    with pytest.raises(InvalidRequest, match="needs param 'table'"):
        query.validate_parameters({}, name="custom.required")
    with pytest.raises(InvalidRequest, match="must be table"):
        query.validate_parameters({"table": None}, name="custom.required")
    with pytest.raises(InvalidRequest, match="unknown params"):
        query.validate_parameters({"table": "notes", "unknown": True}, name="custom.required")


def test_parameter_names_cannot_shadow_model_methods_or_be_dropped() -> None:
    query = QueryDefinition(
        category="custom",
        description="",
        sql="SELECT 1",
        params={"model_dump": Param(type="int", required=True), "_private": Param(type="bool", default=False)},
    )
    assert query.validate_parameters({"model_dump": "12"}, name="custom.names") == {"model_dump": 12, "_private": False}


def test_catalog_models_reject_unknown_fields_and_validate_defaults() -> None:
    with pytest.raises(ValidationError):
        Param.model_validate({"type": "int", "default": True})
    with pytest.raises(ValidationError):
        Param.model_validate({"type": "bool", "unexpected": True})
    with pytest.raises(ValidationError):
        QueryDefinition.model_validate({"category": "custom", "description": "", "sql": "SELECT 1", "unexpected": True})


def test_parameter_validation_returns_safe_typed_issues() -> None:
    query = QueryDefinition(category="custom", description="", sql="SELECT %(count)s", params={"count": Param(type="int", required=True)})
    with pytest.raises(RequestValidationFailure) as captured:
        query.validate_parameters({"count": "synthetic-private-value"}, name="custom.count")
    failure = error_payload(captured.value)
    assert failure.error.status == 422
    assert failure.error.code == "validation_error"
    assert failure.error.message == "Request validation failed"
    assert failure.error.details is not None
    assert failure.error.details.issues[0].path == ("count",)
    assert failure.error.details.issues[0].code == "int_parsing"
    assert "synthetic-private-value" not in failure.model_dump_json()
