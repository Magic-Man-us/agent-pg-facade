from __future__ import annotations

import pytest
from pydantic import TypeAdapter, ValidationError

from pgfacade import Forbidden, InvalidRequest, PgFacade, PgSettings, Principal
from pgfacade.authorization.engine import PolicyEngine
from pgfacade.authorization.models import (
    AccessControlConfig,
    AuthorizationContext,
    DenyPolicy,
    Identity,
    MockIdentityConfig,
    MockIdentityRecord,
)
from pgfacade.authorization.types import ResourcePattern
from pgfacade.contracts.admin import ServerWhoAmI, ServerWhoAmIInput
from pgfacade.contracts.enums import ErrorCode
from pgfacade.contracts.queries import QueryRun, QueryRunInput
from pgfacade.contracts.requests import Batch, BatchInput
from pgfacade.contracts.requests import Request as OperationRequest
from pgfacade.contracts.rows import (
    RowsCount,
    RowsCountInput,
    RowsInsert,
    RowsInsertInput,
    RowsSelect,
    RowsSelectInput,
    SqlQuery,
    SqlQueryInput,
)
from pgfacade.contracts.schema import TableDescribe, TableDescribeInput
from tests.support import _DENY, allow, config, fails, identity, successful


@pytest.fixture
def context() -> AuthorizationContext:
    return AuthorizationContext(connector="local", default_schema="app")


def test_default_deny_and_exact_group_membership(context: AuthorizationContext) -> None:
    engine = PolicyEngine(config(allow()))
    for subject in (identity(), identity("other"), identity("team-child")):
        with pytest.raises(Forbidden):
            engine.authorize(RowsSelect(input=RowsSelectInput(table="reports")), subject, context)
    assert engine.authorize(RowsSelect(input=RowsSelectInput(table="reports")), identity("team"), context).profile.role == "app_reader"


def test_explicit_deny_overrides_high_priority_allow(context: AuthorizationContext) -> None:
    engine = PolicyEngine(config(allow(priority=100), _DENY))
    with pytest.raises(Forbidden, match="explicitly denies"):
        engine.authorize(RowsSelect(input=RowsSelectInput(table="app.reports")), identity("team"), context)


def test_connector_and_resource_scope_are_enforced(context: AuthorizationContext) -> None:
    engine = PolicyEngine(config(allow()))
    for request in (RowsSelect(input=RowsSelectInput(table="private.reports")), RowsSelect(input=RowsSelectInput(table="app.other"))):
        with pytest.raises(Forbidden):
            engine.authorize(request, identity("team"), context)
    foreign = AuthorizationContext(connector="other", default_schema="app")
    with pytest.raises(Forbidden):
        engine.authorize(RowsSelect(input=RowsSelectInput(table="app.reports")), identity("team"), foreign)


def test_schema_wildcard_is_bounded_and_quoted_identifiers_fail_closed(context: AuthorizationContext) -> None:
    engine = PolicyEngine(config(allow(operation="rows.*", resource="app.*")))
    assert engine.authorize(RowsCount(input=RowsCountInput(table="app.reports")), identity("team"), context).execution_identity == "reader"
    for table in ("private.reports", 'app."reports"'):
        with pytest.raises(Forbidden):
            engine.authorize(RowsSelect(input=RowsSelectInput(table=table)), identity("team"), context)
    for table in ("app.a.b", ".reports"):
        with pytest.raises(ValidationError):
            RowsSelect(input=RowsSelectInput(table=table))


def test_read_only_profile_cannot_authorize_a_write(context: AuthorizationContext) -> None:
    engine = PolicyEngine(config(allow(operation="rows.*")))
    with pytest.raises(Forbidden):
        engine.authorize(RowsInsert(input=RowsInsertInput(table="reports", rows=[{"note": "blocked"}])), identity("team"), context)


def test_equal_priority_profiles_are_ambiguous_and_explicit_priority_selects_one(context: AuthorizationContext) -> None:
    request = RowsSelect(input=RowsSelectInput(table="reports"))
    subject = identity("team")
    ambiguous = PolicyEngine(config(allow(), allow("audit", profile="auditor")))
    with pytest.raises(Forbidden, match="ambiguous"):
        ambiguous.authorize(request, subject, context)
    selected = PolicyEngine(config(allow(priority=2), allow("audit", profile="auditor")))
    decision = selected.authorize(request, subject, context)
    assert decision.execution_identity == "reader" and decision.matched_policies == ("read",)


def test_batch_uses_one_profile_and_pins_it_for_inner_reads(context: AuthorizationContext) -> None:
    engine = PolicyEngine(config(allow(priority=100), allow("write", operation="rows.*", profile="writer")))
    batch = Batch(
        input=BatchInput(
            requests=[
                RowsSelect(input=RowsSelectInput(table="reports")),
                RowsInsert(input=RowsInsertInput(table="reports", rows=[{"note": "ok"}])),
            ]
        )
    )
    decision = engine.authorize(batch, identity("team"), context)
    assert decision.execution_identity == "writer"
    pinned = AuthorizationContext(connector="local", default_schema="app", execution_identity="writer")
    assert engine.authorize(RowsSelect(input=RowsSelectInput(table="reports")), identity("team"), pinned).execution_identity == "writer"


def test_batch_cannot_combine_independent_database_identities(context: AuthorizationContext) -> None:
    engine = PolicyEngine(config(allow(resource="app.first"), allow("second", resource="app.second", profile="auditor")))
    batch = Batch(
        input=BatchInput(requests=[RowsSelect(input=RowsSelectInput(table="first")), RowsSelect(input=RowsSelectInput(table="second"))])
    )
    with pytest.raises(Forbidden, match="one execution identity"):
        engine.authorize(batch, identity("team"), context)


def test_explicit_batch_deny_is_enforced(context: AuthorizationContext) -> None:
    denied = DenyPolicy.model_validate(_DENY.model_dump() | {"operations": ("batch.run",), "resources": ("@connector",)})
    engine = PolicyEngine(config(allow(), denied))
    with pytest.raises(Forbidden, match="explicitly denies"):
        engine.authorize(Batch(input=BatchInput(requests=[RowsSelect(input=RowsSelectInput(table="reports"))])), identity("team"), context)
    assert engine.discover("batch.run", identity("team"), context) == ()


@pytest.mark.parametrize(
    "operation_request",
    [
        SqlQuery(input=SqlQueryInput(sql="SELECT 1")),
        QueryRun(input=QueryRunInput(name="rows.recent", params={"table": "app.reports"})),
        TableDescribe(input=TableDescribeInput(table="app.reports")),
    ],
)
def test_wildcard_does_not_authorize_operations_without_resource_plans(
    operation_request: OperationRequest, context: AuthorizationContext
) -> None:
    engine = PolicyEngine(config(allow(operation="*", resource="*", profile="writer")))
    with pytest.raises(Forbidden, match="does not support"):
        engine.authorize(operation_request, identity("team"), context)
    assert engine.discover(operation_request.kind, identity("team"), context) == ()


def test_discovery_respects_connector_resources_denies_and_read_only_profiles(context: AuthorizationContext) -> None:
    engine = PolicyEngine(config(allow(operation="*", resource="app.*")))
    assert engine.discover("rows.select", identity("team"), context)
    assert not engine.discover("server.health", identity("team"), context)
    assert not engine.discover("rows.insert", identity("team"), context)
    denied = PolicyEngine(config(allow(), _DENY))
    assert denied.discover("rows.select", identity("team"), context) == ()


def test_configuration_rejects_duplicate_ids_unknown_profiles_and_mock_google_issuers() -> None:
    with pytest.raises(ValidationError, match="unique"):
        config(allow(), allow())
    with pytest.raises(ValidationError, match="unknown execution identity"):
        config(allow(profile="missing"))
    with pytest.raises(ValidationError, match="mock issuer"):
        MockIdentityConfig(records=[MockIdentityRecord(token="synthetic", identity=Identity(subject="user", issuer="google"))])


async def test_core_binds_profile_without_mutating_base_or_exposing_disabled_ops() -> None:
    access = config(
        allow(operation="server.whoami", resource="@connector", profile="writer"), allow("rows", operation="rows.*", profile="writer")
    )
    settings = PgSettings(_env_file=None, access_control=access)
    base = PgFacade(settings)
    subject = Principal(name="person", identity=identity("team"), read_only=True)
    bound = base.as_(subject)
    result = await successful(bound.call(ServerWhoAmI(input=ServerWhoAmIInput())))
    assert result.role == "app_writer" and (not result.read_only)
    assert bound.principal.role is None and base.principal.identity is None
    operations = {operation.op for operation in bound.allowed_ops()}
    assert "rows.insert" in operations and "sql.query" not in operations and ("query.run" not in operations)


async def test_core_server_read_only_cap_overrides_group_write_policy() -> None:
    access = config(allow(operation="rows.*", profile="writer"))
    bound = PgFacade(PgSettings(_env_file=None, access_control=access, read_only=True)).as_(Principal(identity=identity("team")))
    with fails(match="server is read-only", code=ErrorCode.FORBIDDEN):
        await successful(bound.call(RowsInsert(input=RowsInsertInput(table="app.reports", rows=[{"note": "blocked"}]))))
    assert "rows.insert" not in {operation.op for operation in bound.allowed_ops()}


async def test_group_batch_limit_rejects_before_resource_planning_or_database_access() -> None:
    access = AccessControlConfig.model_validate(config(allow()).model_dump() | {"max_batch_operations": 1})
    bound = PgFacade(PgSettings(_env_file=None, access_control=access)).as_(Principal(identity=identity("team")))
    batch = Batch(
        input=BatchInput(requests=[RowsSelect(input=RowsSelectInput(table="reports")), SqlQuery(input=SqlQueryInput(sql="SELECT 1"))])
    )
    with fails(match="group operation limit", code=ErrorCode.INVALID_REQUEST):
        await successful(bound.call(batch))


async def test_manual_unselected_group_transaction_is_rejected_before_database_access() -> None:
    bound = PgFacade(PgSettings(_env_file=None, access_control=config(allow()))).as_(Principal(identity=identity("team")))
    with pytest.raises(InvalidRequest, match="batch.run"):
        async with bound.transaction():
            pytest.fail("Transaction should not open")


@pytest.mark.parametrize("credential", [" ", "line\nbreak", "two words"])
def test_mock_credentials_reject_whitespace_without_disclosure(credential: str) -> None:
    with pytest.raises(ValidationError) as error:
        MockIdentityRecord(token=credential, identity=Identity(subject="person"))
    assert "input_value" not in str(error.value)
    if credential.strip():
        assert credential not in str(error.value)


@pytest.mark.parametrize("qualified", [False, True])
def test_truncated_table_names_are_rejected_at_the_request_boundary(qualified: bool) -> None:
    requested = "s" * 63 + "suffix"
    if qualified:
        requested = "app." + requested
    with pytest.raises(ValidationError):
        RowsSelect(input=RowsSelectInput(table=requested))


def test_long_schema_names_are_rejected_before_postgres_truncation() -> None:
    with pytest.raises(ValidationError):
        RowsSelect(input=RowsSelectInput(table=f"{'s' * 64}.reports"))


@pytest.mark.parametrize("pattern", ["app." + "t" * 64, "s" * 64 + ".reports", "s" * 64 + ".*"])
def test_policy_resource_components_fit_postgres_identifiers(pattern: str) -> None:
    with pytest.raises(ValidationError):
        TypeAdapter(ResourcePattern).validate_python(pattern)
