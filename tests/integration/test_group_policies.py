from __future__ import annotations

import pytest

from pgfacade import PgFacade, Principal
from pgfacade.authorization.models import AccessControlConfig, ExecutionIdentity
from pgfacade.contracts.requests import Batch, BatchInput
from pgfacade.contracts.rows import (
    RowsCount,
    RowsCountInput,
    RowsInsert,
    RowsInsertInput,
    RowsSelect,
    RowsSelectInput,
    SqlExecute,
    SqlExecuteInput,
)
from tests.conftest import make_settings, unique
from tests.support import allow, identity, successful


@pytest.mark.integration
async def test_real_role_binding_and_batch_profile_coherence(users: str) -> None:
    reader_role, writer_role = (unique("policy_reader"), unique("policy_writer"))
    async with PgFacade(make_settings()) as admin:
        await successful(admin.call(SqlExecute(input=SqlExecuteInput(sql=f'CREATE ROLE "{reader_role}" NOLOGIN'))))
        await successful(admin.call(SqlExecute(input=SqlExecuteInput(sql=f'CREATE ROLE "{writer_role}" NOLOGIN'))))
        try:
            await successful(admin.call(SqlExecute(input=SqlExecuteInput(sql=f'GRANT SELECT ON "{users}" TO "{reader_role}"'))))
            await successful(admin.call(SqlExecute(input=SqlExecuteInput(sql=f'GRANT SELECT, INSERT ON "{users}" TO "{writer_role}"'))))
            await successful(
                admin.call(SqlExecute(input=SqlExecuteInput(sql=f'GRANT USAGE, SELECT ON SEQUENCE "{users}_id_seq" TO "{writer_role}"')))
            )
            access = AccessControlConfig(
                execution_identities={
                    "reader": ExecutionIdentity(role=reader_role),
                    "writer": ExecutionIdentity(role=writer_role, read_only=False),
                },
                policies=(
                    allow(resource=f"public.{users}", priority=100),
                    allow("write", operation="rows.*", resource=f"public.{users}", profile="writer"),
                ),
            )
            async with PgFacade(make_settings(access_control=access)) as facade:
                person = facade.as_(Principal(name="person", identity=identity("team"), read_only=True))
                before = (await successful(person.call(RowsCount(input=RowsCountInput(table=users))))).count
                result = await successful(
                    person.call(
                        Batch(
                            input=BatchInput(
                                requests=[
                                    RowsSelect(input=RowsSelectInput(table=users)),
                                    RowsInsert(input=RowsInsertInput(table=users, rows=[{"email": "group-policy@example.test"}])),
                                ]
                            )
                        )
                    )
                )
                assert result.results[1].outcome.data.rowcount == 1
                assert (await successful(person.call(RowsCount(input=RowsCountInput(table=users))))).count == before + 1
                assert facade.principal.role is None
        finally:
            await successful(
                admin.call(SqlExecute(input=SqlExecuteInput(sql=f'REVOKE ALL ON "{users}" FROM "{reader_role}", "{writer_role}"')))
            )
            await successful(
                admin.call(SqlExecute(input=SqlExecuteInput(sql=f'REVOKE ALL ON SEQUENCE "{users}_id_seq" FROM "{writer_role}"')))
            )
            await successful(admin.call(SqlExecute(input=SqlExecuteInput(sql=f'DROP ROLE "{reader_role}"'))))
            await successful(admin.call(SqlExecute(input=SqlExecuteInput(sql=f'DROP ROLE "{writer_role}"'))))
