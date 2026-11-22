from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

import pytest
from fastapi.testclient import TestClient

from pgfacade import PgSettings
from pgfacade.authorization.models import MockIdentityConfig
from pgfacade.contracts.admin import ServerWhoAmI, ServerWhoAmIInput, WhoAmI
from pgfacade.contracts.rows import RowsDelete, RowsDeleteInput, RowsSelect, RowsSelectInput, SqlQuery, SqlQueryInput
from pgfacade.shared.types import ApiKey
from pgfacade.webapp import create_app

EXAMPLES = Path(__file__).resolve().parents[2] / "docs/examples"
READER_TOKEN = "demo-reader-not-a-google-token"
WRITER_TOKEN = "demo-writer-not-a-google-token"
ExampleFormat = Literal["yaml", "toml"]


@pytest.fixture(autouse=True)
def isolated_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in os.environ:
        if name.startswith("PGFACADE_"):
            monkeypatch.delenv(name)


def example_settings(format: ExampleFormat) -> PgSettings:
    return PgSettings(_env_file=None, config_file=EXAMPLES / f"mock-access.{format}")


def test_documented_formats_have_identical_effective_configuration_and_tokens() -> None:
    yaml = example_settings("yaml")
    toml = example_settings("toml")
    assert yaml.model_dump(exclude={"config_file"}) == toml.model_dump(exclude={"config_file"})
    for settings in (yaml, toml):
        assert settings.access_control is not None
        source = settings.access_control.identity
        assert isinstance(source, MockIdentityConfig)
        assert tuple(record.token.get_secret_value() for record in source.records) == (READER_TOKEN, WRITER_TOKEN)
        assert tuple(record.identity.subject for record in source.records) == ("mock-reader", "mock-writer")
        assert tuple(record.identity.groups for record in source.records) == (
            frozenset({"mock-report-readers"}),
            frozenset({"mock-report-writers"}),
        )
        assert READER_TOKEN not in repr(settings)
        assert WRITER_TOKEN not in repr(settings)


@pytest.mark.parametrize("format", ["yaml", "toml"])
@pytest.mark.parametrize("token", [READER_TOKEN, WRITER_TOKEN])
def test_example_http_credentials_select_the_configured_identity_and_role(format: ExampleFormat, token: ApiKey) -> None:
    client = TestClient(create_app(example_settings(format)))
    response = client.post(
        "/call", json=ServerWhoAmI(input=ServerWhoAmIInput()).model_dump(mode="json"), headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 200
    identity = WhoAmI.model_validate(response.json()["outcome"]["data"])
    assert identity.principal == ("Demo reader" if token == READER_TOKEN else "Demo writer")
    assert identity.role == "pgfacade_reader"
    assert identity.read_only
    assert not any((identity.sql, identity.ddl, identity.admin, identity.migrate, identity.listen))
    assert token not in response.text


@pytest.mark.parametrize("format", ["yaml", "toml"])
@pytest.mark.parametrize("token", [READER_TOKEN, WRITER_TOKEN])
def test_example_http_policy_denies_protected_deletes_and_unlisted_resources(format: ExampleFormat, token: ApiKey) -> None:
    client = TestClient(create_app(example_settings(format)))
    requests = (
        RowsDelete(input=RowsDeleteInput(table="app.notes", allow_all=True)),
        RowsSelect(input=RowsSelectInput(table="app.private_notes")),
        SqlQuery(input=SqlQueryInput(sql="SELECT 1")),
    )
    for request in requests:
        response = client.post("/call", json=request.model_dump(mode="json"), headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 403
        assert token not in response.text


@pytest.mark.parametrize("format", ["yaml", "toml"])
def test_example_http_rejects_credentials_and_group_header_spoofing(format: ExampleFormat) -> None:
    client = TestClient(create_app(example_settings(format)))
    response = client.post(
        "/call",
        json=ServerWhoAmI(input=ServerWhoAmIInput()).model_dump(mode="json"),
        headers={"Authorization": "Bearer unknown-example-credential", "X-Google-Groups": "mock-report-writers"},
    )
    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"
