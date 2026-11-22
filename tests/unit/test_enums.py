from __future__ import annotations

from enum import StrEnum

from pydantic import TypeAdapter

from pgfacade import OPERATIONS, ErrorCode, Operation, Outcome, Perm, ResponseEnvelope, Success
from pgfacade.application.errors import Forbidden, error_payload
from pgfacade.contracts.base import Count
from pgfacade.contracts.envelopes import ApiError, Failure
from pgfacade.contracts.requests import REQUEST_TYPES, Request, parse_request
from pgfacade.contracts.rows import RowsSelect


def test_operation_enum_covers_registry_and_every_request_discriminator() -> None:
    assert issubclass(Operation, StrEnum)
    assert set(Operation) == set(OPERATIONS)
    assert len(REQUEST_TYPES) == len(Operation)
    for request_model in REQUEST_TYPES:
        field = request_model.model_fields["kind"]
        operation = field.default
        assert isinstance(operation, Operation)
        assert OPERATIONS[operation].request is request_model
        adapter = TypeAdapter(field.annotation)
        assert adapter.validate_python(operation.value) is operation
        assert adapter.validate_python(operation) is operation
        assert adapter.dump_json(operation) == f'"{operation.value}"'.encode()


def test_request_accepts_wire_strings_and_enum_members_with_identical_json() -> None:
    wire = parse_request({"kind": "rows.select", "input": {"table": "app.notes"}})
    enum = parse_request({"kind": Operation.ROWS_SELECT, "input": {"table": "app.notes"}})
    assert wire.kind is enum.kind is Operation.ROWS_SELECT
    assert isinstance(wire, RowsSelect)
    assert wire == enum
    assert wire.model_dump_json() == enum.model_dump_json()
    assert wire.model_dump(mode="json")["kind"] == "rows.select"


def test_request_schema_preserves_string_discriminator_mapping() -> None:
    schema = TypeAdapter(Request).json_schema()
    mapping = schema["discriminator"]["mapping"]
    assert set(mapping) == {operation.value for operation in Operation}
    assert schema["$defs"]["RowsSelect"]["properties"]["kind"]["const"] == "rows.select"


def test_outcomes_and_error_codes_are_enum_members_with_unchanged_wire_values() -> None:
    assert issubclass(Outcome, StrEnum)
    assert issubclass(ErrorCode, StrEnum)
    success = ResponseEnvelope[Count].model_validate_json('{"kind":"rows.count","outcome":{"status":"success","data":{"count":3}}}')
    assert isinstance(success.outcome, Success)
    assert success.outcome.status is Outcome.SUCCESS
    assert success.model_dump_json() == '{"kind":"rows.count","outcome":{"status":"success","data":{"count":3}}}'
    failure = error_payload(Forbidden("Denied"))
    assert failure.status is Outcome.ERROR
    assert failure.error.code is ErrorCode.FORBIDDEN
    restored = ResponseEnvelope[Count](kind=Operation.ROWS_COUNT, outcome=failure)
    assert isinstance(restored.outcome, Failure)
    assert restored.outcome.error.code is ErrorCode.FORBIDDEN
    assert restored.model_dump(mode="json")["outcome"]["error"]["code"] == "forbidden"


def test_response_schema_preserves_discriminators_and_error_code_vocabulary() -> None:
    schema = ResponseEnvelope[Count].model_json_schema()
    assert set(schema["properties"]["outcome"]["discriminator"]["mapping"]) == {"success", "error"}
    assert schema["$defs"]["Failure"]["properties"]["status"]["const"] == "error"
    assert set(ApiError.model_json_schema()["$defs"]["ErrorCode"]["enum"]) == {code.value for code in ErrorCode}


def test_permission_union_preserves_capabilities_and_metadata() -> None:
    write_scope = Perm(write=True, ddl=True, listen=True)
    administrative_scope = Perm(raw=True, admin=True, migrate=True)
    combined = write_scope | administrative_scope

    assert combined.as_tuple() == (True, True, True, True, True, True)
    assert tuple(combined.flags()) == ("write", "raw", "ddl", "admin", "migrate", "listen")
    assert all(combined.flags().values())
    assert write_scope.flags() == {"write": True, "ddl": True, "listen": True}
    assert administrative_scope.flags() == {"raw": True, "admin": True, "migrate": True}
    assert Perm().flags() == {}
