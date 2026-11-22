from __future__ import annotations

from typing import Annotated, Literal, Self

from psycopg import ProgrammingError
from psycopg.conninfo import make_conninfo
from pydantic import AliasChoices, BaseModel, Field, model_validator
from pydantic_settings import (
    BaseSettings,
    InitSettingsSource,
    PydanticBaseSettingsSource,
    TomlConfigSettingsSource,
    YamlConfigSettingsSource,
)
from yaml import YAMLError

from pgfacade.configuration.enums import ConfigurationFormat, DatabaseBackend
from pgfacade.configuration.types import (
    ConfigurationPath,
    DatabaseDsn,
    DatabaseHost,
    DatabaseName,
    DatabasePassword,
    DatabasePort,
    DatabaseUser,
    SslMode,
)
from pgfacade.shared.config import CONTRACT_CONFIG, SOURCE_CONFIG
from pgfacade.shared.types import SettingsValues


class DsnDatabase(BaseModel):
    model_config = CONTRACT_CONFIG

    kind: Literal[DatabaseBackend.DSN] = DatabaseBackend.DSN
    dsn: DatabaseDsn

    @model_validator(mode="after")
    def _validate_dsn(self) -> Self:
        if not self.dsn.get_secret_value().strip():
            raise ValueError("Database DSN must not be empty")
        try:
            make_conninfo(self.dsn.get_secret_value())
        except ProgrammingError:
            raise ValueError("Database DSN must be a valid PostgreSQL connection string") from None
        return self

    @property
    def connection_dsn(self) -> DatabaseDsn:
        return self.dsn


class PostgresDatabase(BaseModel):
    model_config = CONTRACT_CONFIG

    kind: Literal[DatabaseBackend.POSTGRES] = DatabaseBackend.POSTGRES
    host: DatabaseHost = "/var/run/postgresql"
    port: DatabasePort = 5432
    dbname: DatabaseName = Field(validation_alias=AliasChoices("dbname", "name"))
    user: DatabaseUser = Field(validation_alias=AliasChoices("user", "username"))
    password: DatabasePassword | None = None
    sslmode: SslMode | None = None

    @property
    def connection_dsn(self) -> DatabaseDsn:
        parameters = self.model_dump(exclude={"kind", "password"}, exclude_none=True)
        if self.password is not None:
            parameters["password"] = self.password.get_secret_value()
        try:
            return DatabaseDsn(make_conninfo(**parameters))
        except ProgrammingError:
            raise ValueError("Database fields must form a valid PostgreSQL connection string") from None


DatabaseConfig = Annotated[DsnDatabase | PostgresDatabase, Field(discriminator="kind")]


class _FlatDatabaseSettings(BaseModel):
    model_config = SOURCE_CONFIG

    dsn: DatabaseDsn | None = None

    @classmethod
    def normalize(cls, values: SettingsValues) -> SettingsValues:
        source = cls.model_validate(values)
        if "dsn" not in source.model_fields_set:
            return values
        if "database" in values and values["database"] is not None:
            raise ValueError("A settings source must define either dsn or database, not both")
        database = DsnDatabase.model_validate(source.model_dump())
        return {name: value for name, value in values.items() if name != "dsn"} | {"database": database}


class CanonicalDatabaseSettingsSource(InitSettingsSource):
    def __init__(self, settings_cls: type[BaseSettings], source: PydanticBaseSettingsSource) -> None:
        super().__init__(settings_cls, {})
        self.source = source
        self.__name__ = type(source).__name__

    def __call__(self) -> SettingsValues:
        self.source._set_current_state(self.current_state)
        self.source._set_settings_sources_data(self.settings_sources_data)
        return _FlatDatabaseSettings.normalize(self.source())


class ConfigurationSelection(BaseModel):
    model_config = SOURCE_CONFIG

    config_file: ConfigurationPath | None = None


def configuration_source(settings_cls: type[BaseSettings], path: ConfigurationPath) -> PydanticBaseSettingsSource:
    if not path.is_file():
        raise ValueError(f"Configuration file {path} does not exist")
    suffix = path.suffix.lower()
    if suffix not in set(ConfigurationFormat):
        raise ValueError("Configuration files must use .toml, .yaml, or .yml")
    source: PydanticBaseSettingsSource
    try:
        if suffix == ConfigurationFormat.TOML:
            source = TomlConfigSettingsSource(settings_cls, toml_file=path)
        else:
            source = YamlConfigSettingsSource(settings_cls, yaml_file=path)
    except (ValueError, TypeError, AttributeError, OSError, YAMLError):
        raise ValueError("Unable to parse the selected configuration file") from None
    return source
