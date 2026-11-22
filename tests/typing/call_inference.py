from __future__ import annotations

from typing import assert_type

from pgfacade import MyApp
from pgfacade.contracts.base import Count, QueryResult
from pgfacade.contracts.envelopes import ResponseEnvelope
from pgfacade.contracts.requests import Batch, BatchInput, BatchResult
from pgfacade.contracts.rows import RowsCount, RowsCountInput, RowsSelect, RowsSelectInput
from pgfacade.contracts.schema import TableDescribe, TableDescribeInput, TableDetail


async def check_inferred_results(db: MyApp) -> None:
    assert_type(await db.call(RowsSelect(input=RowsSelectInput(table="items"))), ResponseEnvelope[QueryResult])
    assert_type(await db.call(RowsCount(input=RowsCountInput(table="items"))), ResponseEnvelope[Count])
    assert_type(await db.call(TableDescribe(input=TableDescribeInput(table="items"))), ResponseEnvelope[TableDetail])
    assert_type(
        await db.call(Batch(input=BatchInput(requests=[RowsCount(input=RowsCountInput(table="items"))]))), ResponseEnvelope[BatchResult]
    )
