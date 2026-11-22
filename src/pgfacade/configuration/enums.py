from __future__ import annotations

from enum import StrEnum


class DatabaseBackend(StrEnum):
    DSN = "dsn"
    POSTGRES = "postgres"


class SslMode(StrEnum):
    DISABLE = "disable"
    ALLOW = "allow"
    PREFER = "prefer"
    REQUIRE = "require"
    VERIFY_CA = "verify-ca"
    VERIFY_FULL = "verify-full"


class ConfigurationFormat(StrEnum):
    TOML = ".toml"
    YAML = ".yaml"
    YML = ".yml"
