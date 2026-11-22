from __future__ import annotations

import ast
import re
from importlib import resources
from importlib.resources.abc import Traversable
from pathlib import Path

import pytest
from pydantic import TypeAdapter, ValidationError

import pgfacade
from pgfacade import PgFacade, PgSettings
from pgfacade.contracts.enums import ErrorCode
from pgfacade.contracts.queries import QueryList, QueryListInput, QueryRun, QueryRunInput
from pgfacade.infrastructure.postgres.queries.loader import query_definitions
from pgfacade.infrastructure.postgres.queries.registry import Statement
from pgfacade.infrastructure.postgres.queries.types import QueryAccess, QueryName
from tests.support import fails, successful


@pytest.mark.parametrize("statement", Statement)
def test_registered_statement_resources_are_in_the_installed_package(statement: Statement) -> None:
    assert statement.text.strip()
    assert statement.sql.as_string() == statement.text


def test_every_packaged_sql_resource_has_one_registered_name() -> None:
    pending: list[tuple[QueryName, Traversable]] = [("", resources.files("pgfacade.infrastructure.postgres.queries").joinpath("sql"))]
    found = set()
    while pending:
        prefix, directory = pending.pop()
        for entry in directory.iterdir():
            name = f"{prefix}{entry.name}"
            if entry.is_dir():
                pending.append((f"{name}/", entry))
            elif entry.name.endswith(".sql"):
                found.add(name.removesuffix(".sql"))
    registered = {statement.value for statement in Statement}
    assert found == registered
    assert len(registered) == len(Statement.__members__)


def test_exposed_query_names_are_unique_and_internal_access_is_the_default() -> None:
    exposed = [statement.query_name for statement in Statement if statement.access != QueryAccess.INTERNAL]
    assert len(exposed) == len(set(exposed))
    assert Statement.ROWS_SELECT.access is QueryAccess.INTERNAL
    assert Statement.DIAGNOSTIC_HEALTH_CONNECTIONS.access is QueryAccess.ADMIN
    assert Statement.LIBRARY_ROWS_RECENT.access is QueryAccess.PUBLIC


@pytest.mark.parametrize("name", ["internal/schema/not_registered", "../internal/schema/table_drop", "internal/../../outside"])
def test_unknown_statement_names_are_rejected(name: QueryName) -> None:
    with pytest.raises(ValidationError):
        TypeAdapter(Statement).validate_python(name)


async def test_only_explicit_public_queries_are_discoverable_and_invocable() -> None:
    db = PgFacade(PgSettings(_env_file=None, allow_admin=True))
    names = {item.name for item in (await successful(db.call(QueryList(input=QueryListInput())))).items}
    approved = {statement.query_name for statement in Statement if statement.access != QueryAccess.INTERNAL}
    assert names == set(query_definitions(None)) == approved
    for statement in Statement:
        assert statement.value not in names
        with fails(code=ErrorCode.NOT_FOUND):
            await successful(db.call(QueryRun(input=QueryRunInput(name=statement.value))))


async def test_custom_catalog_overrides_cannot_replace_internal_statements(tmp_path: Path) -> None:
    original = Statement.SCHEMA_TABLE_DROP.text
    (tmp_path / "schema.table_drop.sql").write_text("SELECT 1 AS override", encoding="utf-8")
    db = PgFacade(PgSettings(_env_file=None, queries_dir=tmp_path))
    names = {item.name for item in (await successful(db.call(QueryList(input=QueryListInput())))).items}
    assert "schema.table_drop" in names
    assert Statement.SCHEMA_TABLE_DROP.text == original
    assert query_definitions(tmp_path)["schema.table_drop"].sql == "SELECT 1 AS override"


def test_fixed_sql_statements_stay_out_of_handlers_and_connection_engine() -> None:
    package = Path(pgfacade.__file__).parent
    sources = [*package.joinpath("application/operations").glob("*.py"), package / "infrastructure/postgres/engine.py"]
    commands = re.compile(
        "^\\s*(SELECT|INSERT|UPDATE|DELETE|CREATE|ALTER|DROP|SET|RESET|WITH|VACUUM|ANALYZE|REINDEX|LISTEN|NOTIFY|GRANT|REVOKE|TRUNCATE|COPY|EXPLAIN|REFRESH|REASSIGN|COMMENT)\\b",
        re.IGNORECASE,
    )
    violations = []
    for source in sources:
        for node in ast.walk(ast.parse(source.read_text(encoding="utf-8"))):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            if node.func.attr not in {"SQL", "execute", "read", "fetch", "stream", "ddl"} or not node.args:
                continue
            argument = node.args[0]
            if isinstance(argument, ast.JoinedStr) and argument.values:
                argument = argument.values[0]
            if isinstance(argument, ast.Constant) and isinstance(argument.value, str) and commands.match(argument.value):
                violations.append(f"{source.relative_to(package)}:{node.lineno}")
    assert not violations, f"Register fixed SQL statements in the query package: {violations}"


def test_registered_sql_resources_have_runtime_owners() -> None:
    package = Path(pgfacade.__file__).parent
    registry = package / "infrastructure/postgres/queries/registry.py"
    references = {
        node.attr
        for source in package.rglob("*.py")
        if source != registry
        for node in ast.walk(ast.parse(source.read_text(encoding="utf-8")))
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "Statement"
    }
    assert {statement.name for statement in Statement if statement.access == QueryAccess.INTERNAL} <= references
