from __future__ import annotations

import ast
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from pydantic import BaseModel, ValidationError

import pgfacade
from pgfacade import PgFacade, PgSettings, Principal
from pgfacade.application.operations import lifecycle
from pgfacade.contracts.enums import ErrorCode, ParamType
from pgfacade.contracts.envelopes import Failure
from pgfacade.contracts.events import EventWatchInput
from pgfacade.contracts.lifecycle import (
    LIFECYCLE_POLICY_ADAPTER,
    LifecycleRowTtl,
    LifecycleRowTtlInput,
    LifecycleRunInput,
    LifecycleScheduleInput,
    LifecycleTableExpiryInput,
    RowAgeInput,
)
from pgfacade.contracts.schema import ConstraintAdd, ViewCreateInput
from pgfacade.contracts.types import RequestValues
from pgfacade.infrastructure.postgres.engine import Conn
from pgfacade.infrastructure.postgres.queries.composition import TableMeta
from pgfacade.infrastructure.postgres.queries.models import Param, QueryDefinition
from pgfacade.infrastructure.postgres.queries.preparation import prepare_query
from pgfacade.infrastructure.postgres.types import RelationKind
from pgfacade.shared.types import SecurityFlag


async def test_each_table_parameter_keeps_its_own_identifier_and_regclass(monkeypatch: pytest.MonkeyPatch) -> None:
    app = PgFacade(PgSettings(_env_file=None))
    tables = {
        "public.orders": TableMeta(schema_name="public", name="orders", kind=RelationKind.TABLE, columns={}, primary_key=()),
        "sales.customers": TableMeta(schema_name="sales", name="customers", kind=RelationKind.TABLE, columns={}, primary_key=()),
    }
    lookup = AsyncMock(side_effect=lambda connection, name: tables[name])
    monkeypatch.setattr(app, "table", lookup)
    query = QueryDefinition(
        category="custom",
        description="Two independent table parameters",
        sql="SELECT * FROM {left} JOIN {right} ON TRUE",
        params={"left": Param(type=ParamType.TABLE, required=True), "right": Param(type=ParamType.TABLE, required=True)},
    )
    prepared = await prepare_query(app, None, query, {"left": "public.orders", "right": "sales.customers"})
    assert prepared.statement.as_string() == 'SELECT * FROM "public"."orders" JOIN "sales"."customers" ON TRUE'
    assert prepared.parameters == {"left_regclass": '"public"."orders"', "right_regclass": '"sales"."customers"'}
    assert lookup.await_count == 2


def test_ambiguous_column_scope_fails_when_query_definition_is_loaded() -> None:
    with pytest.raises(ValidationError, match="Column parameters require one table"):
        QueryDefinition(
            category="custom",
            description="",
            sql="SELECT {column} FROM {left} JOIN {right} ON TRUE",
            params={
                "left": Param(type=ParamType.TABLE, required=True),
                "right": Param(type=ParamType.TABLE, required=True),
                "column": Param(type=ParamType.COLUMN, required=True),
            },
        )


@pytest.mark.parametrize(("allow_ddl", "principal_ddl"), [(False, True), (True, False)])
async def test_lifecycle_column_creation_requires_server_and_principal_ddl(
    monkeypatch: pytest.MonkeyPatch, allow_ddl: SecurityFlag, principal_ddl: SecurityFlag
) -> None:
    connection = AsyncMock()

    @asynccontextmanager
    async def transaction(**options: object) -> AsyncGenerator[Conn, None]:
        yield connection

    app = PgFacade(PgSettings(_env_file=None, allow_admin=True, allow_ddl=allow_ddl)).as_(
        Principal(name="admin", admin=True, ddl=principal_ddl)
    )
    monkeypatch.setattr(app, "tx", transaction)
    monkeypatch.setattr(
        app,
        "table",
        AsyncMock(
            return_value=TableMeta(
                schema_name="public",
                name="items",
                kind=RelationKind.TABLE,
                columns={},
                primary_key=(),
            )
        ),
    )
    monkeypatch.setattr(lifecycle, "_require_installed", AsyncMock())
    response = await app.call(
        LifecycleRowTtl(input=LifecycleRowTtlInput(table="items", expiry=RowAgeInput(column="expires", ttl="1 day", add_column=True)))
    )
    assert isinstance(response.outcome, Failure)
    assert response.outcome.error.code is ErrorCode.FORBIDDEN
    connection.execute.assert_not_awaited()


@pytest.mark.parametrize(
    ("model", "value"),
    [
        (LifecycleTableExpiryInput, {"table": "items"}),
        (LifecycleTableExpiryInput, {"table": "items", "expiry": {"kind": "at", "time": "2026-01-01T00:00:00Z", "interval": "1 day"}}),
        (LifecycleTableExpiryInput, {"table": "items", "expires_in": "1 day"}),
        (LifecycleRowTtlInput, {"table": "items", "expiry": {"kind": "deadline", "column": "expires", "ttl": "1 day"}}),
        (LifecycleRowTtlInput, {"table": "items", "expiry": {"kind": "deadline", "column": "expires", "add_column": True}}),
        (LifecycleRowTtlInput, {"table": "items", "expiry": {"kind": "age", "column": "created"}}),
        (LifecycleRowTtlInput, {"table": "items", "expiry": {"column": "created", "ttl": "1 day"}}),
        (
            LifecycleRowTtlInput,
            {"table": "items", "expiry": {"kind": "age", "column": "c", "ttl": "1 day"}, "action": {"kind": "delete", "table": "a"}},
        ),
        (LifecycleRunInput, {}),
        (LifecycleRunInput, {"target": {"kind": "all", "policy_id": 1}}),
        (LifecycleRunInput, {"target": {"kind": "policy"}}),
        (LifecycleScheduleInput, {"schedule": {"kind": "off", "expression": "* * * * *"}}),
        (LifecycleScheduleInput, {"schedule": {"kind": "cron"}}),
        (LifecycleScheduleInput, {"cron": None}),
        (ViewCreateInput, {"name": "v", "query": "SELECT 1", "materialized": True, "replace": True}),
        (EventWatchInput, {"table": "items", "events": []}),
    ],
)
def test_invalid_operation_shapes_fail_in_the_receiving_model(model: type[BaseModel], value: RequestValues) -> None:
    with pytest.raises(ValidationError):
        model.model_validate(value)


def test_constraint_variants_reject_irrelevant_fields_and_publish_discriminators() -> None:
    with pytest.raises(ValidationError):
        ConstraintAdd.model_validate({"input": {"table": "items", "kind": "unique", "columns": ["id"], "expression": "id > 0"}})
    request = ConstraintAdd.model_validate({"input": {"table": "items", "kind": "check", "expression": "id > 0"}})
    assert request.input.expression == "id > 0"
    schema = ConstraintAdd.model_json_schema()["properties"]["input"]
    assert set(schema["discriminator"]["mapping"]) == {"unique", "primary_key", "foreign_key", "check"}


def test_lifecycle_policy_variants_reject_incompatible_actions() -> None:
    with pytest.raises(ValidationError):
        LIFECYCLE_POLICY_ADAPTER.validate_python(
            {
                "id": 1,
                "kind": "row_ttl",
                "schema_name": "public",
                "table_name": "items",
                "column_name": "expires",
                "action": "drop",
                "batch_size": 1,
                "enabled": True,
                "created_at": "2026-01-01T00:00:00Z",
            }
        )
    assert set(LIFECYCLE_POLICY_ADAPTER.json_schema()["discriminator"]["mapping"]) == {"row_ttl", "table_expiry"}


def test_operation_handlers_do_not_construct_sql_or_define_boundary_models() -> None:
    package = Path(pgfacade.__file__).parent
    violations = []
    for source in package.joinpath("application/operations").glob("*.py"):
        for node in ast.walk(ast.parse(source.read_text())):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name):
                if node.func.value.id == "sql" and node.func.attr in {"SQL", "Identifier", "Literal", "Placeholder"}:
                    violations.append(f"{source.name}:{node.lineno}")
            if isinstance(node, ast.ClassDef):
                violations.append(f"{source.name}:{node.lineno}:class {node.name}")
    assert not violations
    assert not package.joinpath("models").exists()
