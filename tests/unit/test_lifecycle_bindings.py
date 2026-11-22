from __future__ import annotations

import re
from datetime import UTC, datetime

import pytest
from pydantic import TypeAdapter, ValidationError

from pgfacade.contracts.lifecycle import (
    LIFECYCLE_POLICY_ADAPTER,
    ArchiveRows,
    ArchiveRowsInput,
    DeleteRows,
    LifecyclePolicyList,
    LifecycleRowTtlInput,
    LifecycleRunInput,
    LifecycleScheduleInput,
    LifecycleTableExpiryInput,
    NoSchedule,
    RowAge,
    RowAgeInput,
    RowDeadline,
    RowDeadlineInput,
    RowTtlPolicy,
    TableExpiryPolicy,
)
from pgfacade.infrastructure.postgres.queries import Statement
from pgfacade.infrastructure.postgres.queries import lifecycle as lifecycle_sql
from pgfacade.infrastructure.postgres.queries.composition import TableMeta
from pgfacade.infrastructure.postgres.types import RelationKind

_NOW = datetime(2026, 1, 1, tzinfo=UTC)
_TABLE = TableMeta(schema_name="app", name="notes", kind=RelationKind.TABLE, columns={}, primary_key=())
_PLACEHOLDER = re.compile(r"%\((\w+)\)s")


def _stored(**columns: object) -> dict[str, object]:
    """A row of _pgfacade.lifecycle_policies as `SELECT *` returns it: every kind's columns, mostly null."""
    row: dict[str, object] = {
        "id": 1,
        "schema_name": "app",
        "table_name": "notes",
        "column_name": None,
        "ttl": None,
        "expires_at": None,
        "archive_table": None,
        "batch_size": 5000,
        "enabled": True,
        "created_at": _NOW,
        "last_run_at": None,
        "last_rows": None,
        "last_error": None,
    }
    return row | columns


def test_age_policy_binds_its_ttl_and_no_archive() -> None:
    rule = LifecycleRowTtlInput(table="app.notes", expiry=RowAgeInput(column="created_at", ttl="7 days"), batch_size=10)
    assert lifecycle_sql.upsert_row_ttl(_TABLE, rule, None).parameters == {
        "schema_name": "app",
        "table_name": "notes",
        "column_name": "created_at",
        "ttl": "7 days",
        "action": "delete",
        "archive_table": None,
        "batch_size": 10,
        "enabled": True,
    }


def test_deadline_policy_binds_its_column_without_a_ttl() -> None:
    rule = LifecycleRowTtlInput(table="app.notes", expiry=RowDeadlineInput(column="expires_at"), action=ArchiveRowsInput(), enabled=False)
    parameters = lifecycle_sql.upsert_row_ttl(_TABLE, rule, "app.notes_archive").parameters
    assert isinstance(parameters, dict)
    assert parameters["column_name"] == "expires_at" and parameters["ttl"] is None
    assert parameters["action"] == "archive" and parameters["archive_table"] == "app.notes_archive"
    assert parameters["enabled"] is False


def test_table_expiry_binds_the_resolved_time() -> None:
    rule = LifecycleTableExpiryInput.model_validate({"table": "app.notes", "expiry": {"kind": "in", "interval": "1 day"}, "action": "drop"})
    assert lifecycle_sql.upsert_table_expiry(_TABLE, rule, _NOW).parameters == {
        "schema_name": "app",
        "table_name": "notes",
        "expires_at": _NOW,
        "action": "drop",
        "enabled": True,
    }


@pytest.mark.parametrize(
    ("statement", "parameters"),
    [
        (
            Statement.LIFECYCLE_UPSERT_ROW_TTL,
            lifecycle_sql.upsert_row_ttl(
                _TABLE, LifecycleRowTtlInput(table="app.notes", expiry=RowDeadlineInput(column="expires_at")), None
            ).parameters,
        ),
        (
            Statement.LIFECYCLE_UPSERT_TABLE_EXPIRY,
            lifecycle_sql.upsert_table_expiry(
                _TABLE, LifecycleTableExpiryInput.model_validate({"table": "app.notes", "expiry": {"kind": "at", "time": _NOW}}), _NOW
            ).parameters,
        ),
    ],
)
def test_upsert_statements_bind_exactly_their_placeholders(statement: Statement, parameters: dict[str, object]) -> None:
    assert set(_PLACEHOLDER.findall(statement.text)) == set(parameters)


def test_preview_binds_a_ttl_only_for_age_policies() -> None:
    age = RowTtlPolicy.model_validate(_stored(kind="row_ttl", column_name="created_at", ttl="7 days", action="delete"))
    deadline = RowTtlPolicy.model_validate(_stored(kind="row_ttl", column_name="expires_at", action="delete"))
    assert lifecycle_sql.preview(age).parameters == ["7 days"]
    assert lifecycle_sql.preview(deadline).parameters == []


def test_stored_age_row_reads_as_nested_variants() -> None:
    row = _stored(kind="row_ttl", column_name="created_at", ttl="7 days", action="archive", archive_table="app.notes_archive")
    policy = LIFECYCLE_POLICY_ADAPTER.validate_python(row)
    assert isinstance(policy, RowTtlPolicy)
    assert policy.expiry == RowAge(column="created_at", ttl="7 days")
    assert policy.action == ArchiveRows(table="app.notes_archive")
    wire = LIFECYCLE_POLICY_ADAPTER.dump_python(policy, mode="json")
    assert wire["expiry"] == {"kind": "age", "column": "created_at", "ttl": "7 days"}
    assert wire["action"] == {"kind": "archive", "table": "app.notes_archive"}
    assert not {"column_name", "ttl", "archive_table", "expires_at"} & set(wire)
    assert LIFECYCLE_POLICY_ADAPTER.validate_json(LIFECYCLE_POLICY_ADAPTER.dump_json(policy)) == policy


def test_stored_deadline_row_has_no_ttl_to_report() -> None:
    policy = RowTtlPolicy.model_validate(_stored(kind="row_ttl", column_name="expires_at", action="delete"))
    assert policy.expiry == RowDeadline(column="expires_at") and policy.action == DeleteRows()
    assert policy.model_dump(mode="json")["expiry"] == {"kind": "deadline", "column": "expires_at"}


def test_stored_table_expiry_row_drops_row_only_columns() -> None:
    policy = LIFECYCLE_POLICY_ADAPTER.validate_python(_stored(kind="table_expiry", expires_at=_NOW, action="truncate"))
    assert isinstance(policy, TableExpiryPolicy)
    assert set(policy.model_dump()) == {
        "id",
        "kind",
        "schema_name",
        "table_name",
        "expires_at",
        "action",
        "enabled",
        "created_at",
        "last_run_at",
        "last_rows",
        "last_error",
    }
    assert LIFECYCLE_POLICY_ADAPTER.validate_json(LIFECYCLE_POLICY_ADAPTER.dump_json(policy)) == policy


@pytest.mark.parametrize(
    "row",
    [
        _stored(kind="row_ttl", column_name="created_at", action="archive"),
        _stored(kind="row_ttl", action="delete"),
        _stored(kind="row_ttl", column_name="created_at", action="truncate"),
        _stored(kind="table_expiry", action="truncate"),
        _stored(kind="table_expiry", expires_at=_NOW, action="delete"),
    ],
    ids=["archive-without-table", "row-ttl-without-column", "row-ttl-table-action", "expiry-without-time", "expiry-row-action"],
)
def test_inconsistent_stored_rows_are_rejected(row: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        LIFECYCLE_POLICY_ADAPTER.validate_python(row)


def test_wire_policies_reject_flat_storage_fields() -> None:
    policy = RowTtlPolicy.model_validate(_stored(kind="row_ttl", column_name="created_at", ttl="7 days", action="delete"))
    with pytest.raises(ValidationError):
        RowTtlPolicy.model_validate(policy.model_dump() | {"ttl": "1 day"})


def test_every_lifecycle_choice_publishes_its_discriminator() -> None:
    def mapping(model: type, field: str) -> set[str]:
        return set(TypeAdapter(model).json_schema()["properties"][field]["discriminator"]["mapping"])

    assert mapping(LifecycleRowTtlInput, "expiry") == {"age", "deadline"}
    assert mapping(LifecycleRowTtlInput, "action") == {"delete", "archive"}
    assert mapping(LifecycleTableExpiryInput, "expiry") == {"at", "in"}
    assert mapping(LifecycleRunInput, "target") == {"all", "policy"}
    assert mapping(LifecycleScheduleInput, "schedule") == {"cron", "off"}
    assert mapping(RowTtlPolicy, "expiry") == {"age", "deadline"}
    assert mapping(RowTtlPolicy, "action") == {"delete", "archive"}
    assert mapping(LifecyclePolicyList, "schedule") == {"cron", "off"}
    assert LifecyclePolicyList(items=[], installed=False).schedule == NoSchedule()
