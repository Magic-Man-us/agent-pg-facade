from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import cast

import pytest

from pgfacade import MyApp, PgSettings
from pgfacade.application.errors import InvalidRequest, error_payload
from pgfacade.application.operations.queries import query_run
from pgfacade.contracts.queries import QueryRun, QueryRunInput
from pgfacade.infrastructure.postgres.engine import Conn
from pgfacade.infrastructure.postgres.queries.loader import parse_query_file, query_definitions
from pgfacade.infrastructure.postgres.queries.models import Param, QueryDefinition, QueryFileRequest
from pgfacade.infrastructure.postgres.queries.types import ParamType, QuerySql
from pgfacade.shared.types import SecurityFlag

PRIVATE_VALUE = "synthetic-private-query-value"
PRIVATE_SOURCE = "/synthetic-private-directory/query.sql"


@pytest.mark.parametrize(
    "header",
    [f"-- param: {PRIVATE_VALUE}", f"-- param: flag:bool={PRIVATE_VALUE}"],
)
def test_invalid_query_headers_do_not_echo_defaults_or_server_paths(header: QuerySql) -> None:
    with pytest.raises(InvalidRequest) as caught:
        parse_query_file(QueryFileRequest(text=f"{header}\nSELECT 1", name=PRIVATE_VALUE, source=PRIVATE_SOURCE))
    failure = error_payload(caught.value)
    assert "parameter declaration" in failure.error.message
    assert PRIVATE_VALUE not in failure.model_dump_json()
    assert PRIVATE_SOURCE not in failure.model_dump_json()


def test_empty_query_files_do_not_expose_server_paths() -> None:
    with pytest.raises(InvalidRequest) as caught:
        parse_query_file(QueryFileRequest(text="-- description: Empty", name=PRIVATE_VALUE, source=PRIVATE_SOURCE))
    failure = error_payload(caught.value)
    assert "no SQL statement" in failure.error.message
    assert PRIVATE_SOURCE not in failure.model_dump_json()


async def test_template_errors_do_not_echo_template_identifiers_or_query_names(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    query = QueryDefinition(
        category="custom",
        description="",
        sql=f"SELECT {{{PRIVATE_VALUE}}}",
        params={"identifier": Param(type=ParamType.IDENTIFIER, required=True)},
    )
    application = MyApp(PgSettings(_env_file=None))

    @asynccontextmanager
    async def transaction(*, read_only: SecurityFlag, rollback: SecurityFlag) -> AsyncIterator[Conn]:
        assert read_only and rollback
        # Identifier-only preparation does not use a live database connection.
        yield cast(Conn, None)

    monkeypatch.setattr(application, "tx", transaction)
    monkeypatch.setitem(query_definitions(None), PRIVATE_VALUE, query)
    with pytest.raises(InvalidRequest) as caught:
        await query_run(
            application,
            QueryRun(input=QueryRunInput(name=PRIVATE_VALUE, params={"identifier": "safe"})),
        )
    failure = error_payload(caught.value)
    assert "invalid identifier placeholders" in failure.error.message
    assert PRIVATE_VALUE not in failure.model_dump_json()
