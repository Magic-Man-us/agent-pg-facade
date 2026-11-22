from __future__ import annotations

from pathlib import Path

import pytest
from psycopg.conninfo import conninfo_to_dict
from pydantic import ValidationError

from pgfacade.configuration.database import PostgresDatabase
from pgfacade.configuration.settings import PgSettings


@pytest.mark.parametrize("suffix", [".yaml", ".yml", ".toml"])
def test_explicit_config_file_loads_typed_database(suffix: str, tmp_path: Path) -> None:
    config = tmp_path / f"settings{suffix}"
    if suffix == ".toml":
        config.write_text(
            'connector_id = "reports"\n[database]\nkind = "postgres"\nhost = "/var/run/postgresql"\nname = "reports"\nusername = "reader"\n'
        )
    else:
        config.write_text(
            "connector_id: reports\ndatabase:\n  kind: postgres\n  host: /var/run/postgresql\n  name: reports\n  username: reader\n"
        )
    settings = PgSettings(_env_file=None, config_file=config)
    assert settings.connector_id == "reports"
    assert conninfo_to_dict(settings.dsn.get_secret_value()) == {
        "host": "/var/run/postgresql",
        "port": "5432",
        "dbname": "reports",
        "user": "reader",
    }


def test_structured_database_escapes_credentials_in_model() -> None:
    database = PostgresDatabase.model_validate(
        {
            "dbname": "odd database",
            "user": "odd user",
            "password": "quote' back\\slash space",
            "sslmode": "verify-full",
        }
    )
    parameters = conninfo_to_dict(database.connection_dsn.get_secret_value())
    assert parameters["password"] == "quote' back\\slash space"
    assert parameters["dbname"] == "odd database"
    assert parameters["user"] == "odd user"
    assert parameters["sslmode"] == "verify-full"
    assert "quote'" not in repr(database)


def test_config_file_environment_and_constructor_precedence(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config = tmp_path / "settings.toml"
    config.write_text('application_name = "file"\n[database]\nkind = "dsn"\ndsn = "dbname=file user=file"\n')
    dotenv = tmp_path / "runtime.env"
    dotenv.write_text('PGFACADE_APPLICATION_NAME=dotenv\nPGFACADE_DSN="dbname=dotenv user=dotenv"\n')
    monkeypatch.setenv("PGFACADE_CONFIG_FILE", str(config))
    settings = PgSettings(_env_file=dotenv)
    assert settings.application_name == "dotenv"
    assert settings.dsn.get_secret_value() == "dbname=dotenv user=dotenv"
    monkeypatch.setenv("PGFACADE_APPLICATION_NAME", "environment")
    monkeypatch.setenv("PGFACADE_DSN", "dbname=environment user=environment")
    settings = PgSettings(_env_file=dotenv, application_name="constructor")
    assert settings.application_name == "constructor"
    assert settings.dsn.get_secret_value() == "dbname=environment user=environment"
    settings = PgSettings(_env_file=dotenv, dsn="dbname=constructor user=constructor")
    assert settings.dsn.get_secret_value() == "dbname=constructor user=constructor"


def test_config_selection_can_be_set_in_dotenv(tmp_path: Path) -> None:
    config = tmp_path / "settings.toml"
    config.write_text('application_name = "from-file"\n')
    dotenv = tmp_path / "runtime.env"
    dotenv.write_text(f"PGFACADE_CONFIG_FILE={config}\n")
    assert PgSettings(_env_file=dotenv).application_name == "from-file"


def test_constructor_file_selection_overrides_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    first = tmp_path / "first.toml"
    second = tmp_path / "second.yaml"
    first.write_text('application_name = "first"\n')
    second.write_text("application_name: second\n")
    monkeypatch.setenv("PGFACADE_CONFIG_FILE", str(first))
    assert PgSettings(_env_file=None, config_file=second).application_name == "second"


@pytest.mark.parametrize("suffix", [".yaml", ".toml"])
def test_missing_or_unsupported_config_file_fails_closed(suffix: str, tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="does not exist"):
        PgSettings(_env_file=None, config_file=tmp_path / f"missing{suffix}")
    unsupported = tmp_path / "settings.json"
    unsupported.write_text("{}")
    with pytest.raises(ValueError, match=".toml, .yaml, or .yml"):
        PgSettings(_env_file=None, config_file=unsupported)


@pytest.mark.parametrize("suffix", [".yaml", ".toml"])
def test_empty_config_file_uses_safe_defaults(suffix: str, tmp_path: Path) -> None:
    config = tmp_path / f"empty{suffix}"
    config.write_text("")
    settings = PgSettings(_env_file=None, config_file=config)
    assert not settings.auth_enabled
    assert not settings.allow_raw_sql
    assert settings.access_control is None


@pytest.mark.parametrize("suffix", [".yaml", ".toml"])
def test_unknown_config_fields_are_rejected(suffix: str, tmp_path: Path) -> None:
    config = tmp_path / f"unknown{suffix}"
    config.write_text("misspelled_option: true\n" if suffix == ".yaml" else "misspelled_option = true\n")
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        PgSettings(_env_file=None, config_file=config)


@pytest.mark.parametrize(
    ("suffix", "contents"),
    [
        (".yaml", "database: [secret-password-sentinel\n"),
        (".toml", 'password = "secret-password-sentinel\n'),
        (".yaml", '!!python/object/apply:os.system ["secret-password-sentinel"]'),
        (".yaml", "- secret-password-sentinel\n"),
    ],
)
def test_malformed_file_errors_do_not_disclose_contents(suffix: str, contents: str, tmp_path: Path) -> None:
    config = tmp_path / f"invalid{suffix}"
    config.write_text(contents)
    with pytest.raises(ValueError) as error:
        PgSettings(_env_file=None, config_file=config)
    assert "secret-password-sentinel" not in str(error.value)


def test_database_config_requires_a_discriminator(tmp_path: Path) -> None:
    config = tmp_path / "settings.yaml"
    config.write_text("database:\n  user: reader\n  dbname: reports\n")
    with pytest.raises(ValidationError):
        PgSettings(_env_file=None, config_file=config)


def test_database_unknown_fields_and_invalid_dsn_are_redacted(tmp_path: Path) -> None:
    config = tmp_path / "settings.yaml"
    config.write_text('database:\n  kind: dsn\n  dsn: "secret-password-sentinel"\n')
    with pytest.raises(ValidationError) as error:
        PgSettings(_env_file=None, config_file=config)
    assert "secret-password-sentinel" not in str(error.value)


def test_mock_access_control_is_typed_from_yaml(tmp_path: Path) -> None:
    config = tmp_path / "settings.yaml"
    config.write_text("""access_control:
  identity:
    kind: mock
    records:
      - token: synthetic-reader
        identity:
          subject: mock-reader
          groups: [reports-group]
  execution_identities:
    reader:
      role: pgfacade_reader
      read_only: true
  policies:
    - id: reports
      effect: allow
      groups: [reports-group]
      connector: local
      operations: [rows.select]
      resources: [app.reports]
      execution_identity: reader
""")
    settings = PgSettings(_env_file=None, config_file=config)
    assert settings.auth_enabled
    assert settings.access_control is not None
    assert settings.access_control.identity.kind == "mock"
    assert settings.access_control.identity.records[0].identity.groups == frozenset({"reports-group"})
    assert "synthetic-reader" not in repr(settings)


def test_nested_environment_database_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PGFACADE_DATABASE__KIND", "postgres")
    monkeypatch.setenv("PGFACADE_DATABASE__DBNAME", "reports")
    monkeypatch.setenv("PGFACADE_DATABASE__USER", "reader")
    settings = PgSettings(_env_file=None)
    assert conninfo_to_dict(settings.dsn.get_secret_value())["dbname"] == "reports"


@pytest.mark.parametrize("dsn", ["", "   "])
def test_nested_database_dsn_cannot_fall_back_to_connection_defaults(dsn: str) -> None:
    with pytest.raises(ValidationError):
        PgSettings(_env_file=None, database={"kind": "dsn", "dsn": dsn})


def test_policy_schema_is_checked_at_the_configuration_boundary() -> None:
    with pytest.raises(ValidationError, match="default_schema must be a simple"):
        PgSettings(_env_file=None, default_schema="ambiguous.schema", access_control={})
    assert PgSettings(_env_file=None, default_schema="ambiguous.schema").default_schema == "ambiguous.schema"


@pytest.mark.parametrize("dsn", ["", "   ", "malformed-secret-password-sentinel"])
def test_flat_dsn_is_validated_without_disclosing_values(dsn: str) -> None:
    with pytest.raises(ValidationError) as error:
        PgSettings(_env_file=None, dsn=dsn)
    assert "malformed-secret-password-sentinel" not in str(error.value)


def test_environment_dsn_override_is_validated(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PGFACADE_DSN", "bad-secret-password-sentinel")
    with pytest.raises(ValidationError) as error:
        PgSettings(_env_file=None)
    assert "bad-secret-password-sentinel" not in str(error.value)


def test_constructor_database_beats_environment_flat_dsn(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PGFACADE_DSN", "dbname=environment user=environment")
    settings = PgSettings(_env_file=None, database={"kind": "postgres", "dbname": "constructor", "user": "constructor"})
    assert conninfo_to_dict(settings.dsn.get_secret_value())["dbname"] == "constructor"


def test_file_database_beats_lower_priority_flat_secret(tmp_path: Path) -> None:
    config = tmp_path / "settings.yaml"
    config.write_text("""database:
  kind: postgres
  dbname: from_file
  user: reader
""")
    secrets = tmp_path / "secrets"
    secrets.mkdir()
    (secrets / "PGFACADE_DSN").write_text("dbname=secret user=secret")
    settings = PgSettings(_env_file=None, _secrets_dir=secrets, config_file=config)
    assert conninfo_to_dict(settings.dsn.get_secret_value())["dbname"] == "from_file"


def test_partial_nested_environment_overrides_structured_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config = tmp_path / "settings.yaml"
    config.write_text("""database:
  kind: postgres
  host: original
  dbname: reports
  user: reader
""")
    monkeypatch.setenv("PGFACADE_DATABASE__HOST", "replacement")
    settings = PgSettings(_env_file=None, config_file=config)
    assert conninfo_to_dict(settings.dsn.get_secret_value())["host"] == "replacement"


def test_one_source_rejects_both_database_representations() -> None:
    with pytest.raises(ValueError, match="either dsn or database"):
        PgSettings(_env_file=None, dsn="dbname=one", database={"kind": "dsn", "dsn": "dbname=two"})


def test_partial_structured_override_of_dsn_variant_fails_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config = tmp_path / "settings.yaml"
    config.write_text("""database:
  kind: dsn
  dsn: "dbname=reports user=reader"
""")
    monkeypatch.setenv("PGFACADE_DATABASE__HOST", "replacement")
    with pytest.raises(ValidationError):
        PgSettings(_env_file=None, config_file=config)
