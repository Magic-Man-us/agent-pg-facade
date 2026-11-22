from __future__ import annotations

from pgfacade.contracts.lifecycle import LifecyclePolicyWrite, LifecycleRowTtl, LifecycleRowTtlInput


def test_row_ttl_expiry_column_reaches_the_database_binding() -> None:
    request = LifecycleRowTtl(input=LifecycleRowTtlInput(table="app.notes", column="expires_at", ttl=None))
    values = LifecyclePolicyWrite.model_validate(
        request.input.model_dump() | {"kind": "row_ttl", "schema_name": "app", "table_name": "notes"}
    ).model_dump()
    assert values["column_name"] == "expires_at"
    assert values["ttl"] is None
    assert "column" not in values
