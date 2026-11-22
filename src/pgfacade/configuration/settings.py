"""Runtime configuration. Env vars use the PGFACADE_ prefix; .env is loaded if present.

Access model
------------
The pool connects as one connector database user (the DSN user). Callers present an API key;
each key maps to a Principal that names a Postgres role. Every request runs under
`SET LOCAL ROLE <role>`, so Postgres privileges (GRANTs, RLS, ownership) decide what the caller
can do. The connector must be a member of every mapped role:

    CREATE ROLE pgfacade_svc LOGIN PASSWORD '...' NOINHERIT;
    GRANT app_reader, app_writer TO pgfacade_svc;

Per-principal flags are application-level guardrails on top. A key with `sql: true` can run arbitrary
SQL as its role, which includes SET ROLE to any role the connector is a member of; give raw SQL
only to keys you would trust with all of them. REST and MCP require API keys or an explicit access_control configuration.
Group policies bind verified identities to configured execution roles; identity sources
currently provide only local mock records and a deny-all stub.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field, RootModel, SecretStr, TypeAdapter, ValidationError, model_validator
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource

from pgfacade.authorization.models import AccessControlConfig, Identity
from pgfacade.authorization.types import ConnectorId, DatabaseIdentifier, ExecutionIdentityId
from pgfacade.configuration.database import (
    CanonicalDatabaseSettingsSource,
    ConfigurationSelection,
    DatabaseConfig,
    DsnDatabase,
    configuration_source,
)
from pgfacade.configuration.types import ConfigurationPath, CredentialReprFields, DatabaseDsn
from pgfacade.infrastructure.startup import StartupCommand
from pgfacade.shared.config import COLLECTION_CONFIG, CONTRACT_CONFIG, SETTINGS_CONFIG, SOURCE_CONFIG
from pgfacade.shared.types import (
    DEFAULT_REQUEST_BYTE_LIMIT,
    DEFAULT_REQUEST_READ_TIMEOUT,
    ApplicationName,
    CredentialMap,
    CredentialPath,
    DefaultSchema,
    EventWaitSeconds,
    ExportRowLimit,
    LifecycleChannel,
    LifecycleSweepSeconds,
    LockTimeoutMilliseconds,
    McpCredential,
    MigrationsDirectory,
    PoolMaximum,
    PoolMinimum,
    PoolTimeoutSeconds,
    PrincipalName,
    PrincipalRole,
    QueriesDirectory,
    ReadRowLimit,
    RequestByteLimit,
    RequestReadTimeout,
    SchemaCacheTtlSeconds,
    SecurityFlag,
    SettingsValues,
    StatementTimeoutMilliseconds,
)

META_SCHEMA = "_pgfacade"


class Principal(BaseModel):
    """Authenticated caller and the database permissions bound to its request."""

    model_config = CONTRACT_CONFIG

    name: PrincipalName = Field("anonymous", description="Label for logs and server.whoami")
    role: PrincipalRole | None = Field(None, description="Postgres role to SET ROLE to; None runs as the connector user")
    identity: Identity | None = None
    execution_identity: ExecutionIdentityId | None = None
    read_only: SecurityFlag = False
    ddl: SecurityFlag = Field(False, description="Structured DDL (schemas, tables, columns, indexes, views)")
    sql: SecurityFlag = Field(False, description="Raw SQL and SQL-bodied objects (views, CHECK, USING)")
    admin: SecurityFlag = Field(False, description="Roles, grants, backends, maintenance, lifecycle policies, watches")
    migrate: SecurityFlag = Field(False, description="Alembic migrations (run as the connector user, not the role)")
    listen: SecurityFlag = Field(False, description="LISTEN for notifications; table watches carry row contents, so grant deliberately")


ANONYMOUS = Principal(name="library", ddl=True, sql=True, admin=True, migrate=True, listen=True)
_POLICY_SCHEMA = TypeAdapter(DatabaseIdentifier)


class CredentialFileRequest(BaseModel):
    model_config = CONTRACT_CONFIG

    path: CredentialPath


class CredentialFileResponse(RootModel[CredentialMap[Principal]]):
    model_config = COLLECTION_CONFIG

    def __repr_args__(self) -> CredentialReprFields:
        # RootModel always includes root in its repr, even when Field(repr=False) is set.
        return ()


def _read_credentials(request: CredentialFileRequest) -> CredentialFileResponse:
    return CredentialFileResponse.model_validate_json(request.path.read_bytes())


class _SettingsSources(BaseModel):
    model_config = SOURCE_CONFIG

    database: DatabaseConfig | None = None
    dsn: DatabaseDsn | None = None
    keys_file: CredentialPath | None = None
    keys: CredentialMap[Principal] = Field(default_factory=dict, repr=False, exclude=True)


class PgSettings(BaseSettings):
    model_config = SETTINGS_CONFIG

    config_file: ConfigurationPath | None = None
    startup_command: StartupCommand | None = None
    database: DatabaseConfig | None = None
    connector_id: ConnectorId = "local"
    access_control: AccessControlConfig | None = None
    dsn: DatabaseDsn = SecretStr("postgresql://postgres@localhost:5432/postgres")
    default_schema: DefaultSchema = "public"
    application_name: ApplicationName = "pgfacade"

    pool_min: PoolMinimum = 1
    pool_max: PoolMaximum = 10
    pool_timeout_s: PoolTimeoutSeconds = 30.0

    statement_timeout_ms: StatementTimeoutMilliseconds = 30_000
    lock_timeout_ms: LockTimeoutMilliseconds = 5_000
    schema_cache_ttl_s: SchemaCacheTtlSeconds = 60.0

    max_rows: ReadRowLimit = 1_000
    max_export_rows: ExportRowLimit = 100_000
    max_request_bytes: RequestByteLimit = DEFAULT_REQUEST_BYTE_LIMIT
    request_read_timeout_s: RequestReadTimeout = DEFAULT_REQUEST_READ_TIMEOUT
    max_wait_s: EventWaitSeconds = 60.0

    # Server-wide caps. A principal can never exceed these.
    read_only: SecurityFlag = False
    allow_raw_sql: SecurityFlag = False
    allow_ddl: SecurityFlag = False
    allow_admin: SecurityFlag = False
    allow_migrate: SecurityFlag = False
    allow_listen: SecurityFlag = False

    # Access keys. PGFACADE_KEYS='{"<key>": {"name": "ci", "role": "app_writer"}}'
    keys: CredentialMap[Principal] = Field(default_factory=dict, repr=False, exclude=True)
    keys_file: CredentialPath | None = Field(None, description="JSON file with the same shape as keys; merged in")
    mcp_key: McpCredential | None = None
    migrations_dir: MigrationsDirectory = Path("migrations")
    lifecycle_sweep_s: LifecycleSweepSeconds = 0
    lifecycle_channel: LifecycleChannel = "pgfacade_lifecycle"
    queries_dir: QueriesDirectory | None = None

    # Pydantic requires the complete source-hook signature.
    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        selection = ConfigurationSelection.model_validate(dotenv_settings() | env_settings() | init_settings())
        sources: tuple[PydanticBaseSettingsSource, ...] = (init_settings, env_settings, dotenv_settings)
        if selection.config_file is not None:
            sources += (configuration_source(settings_cls, selection.config_file),)
        return tuple(CanonicalDatabaseSettingsSource(settings_cls, source) for source in (*sources, file_secret_settings))

    @model_validator(mode="before")
    @classmethod
    def _assemble_keys(cls, values: SettingsValues) -> SettingsValues:
        try:
            sources = _SettingsSources.model_validate(values)
        except ValidationError:
            raise ValueError("Database or API key configuration is invalid") from None
        merged: CredentialMap[Principal] = {}
        if sources.keys_file is not None:
            if not sources.keys_file.is_file():
                raise ValueError(f"PGFACADE_KEYS_FILE {sources.keys_file} does not exist")
            try:
                merged.update(_read_credentials(CredentialFileRequest(path=sources.keys_file)).root)
            except ValidationError:
                raise ValueError("PGFACADE_KEYS_FILE must contain a valid API key to principal mapping") from None
        merged.update(sources.keys)
        prepared = values | {"keys": merged}
        if sources.database is not None and "dsn" not in sources.model_fields_set:
            prepared |= {"dsn": sources.database.connection_dsn}
        return prepared

    @model_validator(mode="after")
    def _check_pool_limits(self) -> PgSettings:
        if self.pool_min > self.pool_max:
            raise ValueError("pool_min must not exceed pool_max")
        try:
            DsnDatabase(dsn=self.dsn)
        except ValidationError:
            raise ValueError("Database DSN must be a nonempty valid PostgreSQL connection string") from None
        if self.access_control is not None:
            try:
                _POLICY_SCHEMA.validate_python(self.default_schema)
            except ValidationError:
                raise ValueError("Group-policy default_schema must be a simple PostgreSQL identifier") from None
        return self

    @property
    def auth_enabled(self) -> SecurityFlag:
        return bool(self.keys) or self.access_control is not None
