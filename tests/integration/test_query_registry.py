from __future__ import annotations

import pytest

from pgfacade import MyApp
from pgfacade.contracts.queries import QueryRun, QueryRunInput
from pgfacade.contracts.rows import RowsInsert, RowsInsertInput, RowsSelect, RowsSelectInput
from pgfacade.contracts.schema import ColumnSpec, TableCreate, TableCreateInput, TableDrop, TableDropInput
from tests.conftest import unique
from tests.support import successful

pytestmark = pytest.mark.integration


async def test_registered_templates_quote_identifiers_and_bind_values(db: MyApp) -> None:
    table = f'{unique("quoted")}";--'
    column = 'value";--'
    value = "'); DROP TABLE registry_probe; --"
    await successful(db.call(TableCreate(input=TableCreateInput(table=table, columns=[ColumnSpec(name=column, type="text")]))))
    try:
        await successful(db.call(RowsInsert(input=RowsInsertInput(table=table, rows=[{column: value}]))))
        assert (await successful(db.call(RowsSelect(input=RowsSelectInput(table=table, columns=[column]))))).rows == [{column: value}]
        result = await successful(
            db.call(QueryRun(input=QueryRunInput(name="rows.distinct_values", params={"table": table, "column": column})))
        )
        assert result.rows[0]["value"] == value
    finally:
        await successful(db.call(TableDrop(input=TableDropInput(table=table))))
