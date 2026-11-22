from __future__ import annotations

from pydantic import ConfigDict
from pydantic_settings import SettingsConfigDict

CONTRACT_CONFIG = ConfigDict(frozen=True, extra="forbid", hide_input_in_errors=True)

SOURCE_CONFIG = ConfigDict(frozen=True, extra="ignore", hide_input_in_errors=True)

SETTINGS_CONFIG = SettingsConfigDict(
    env_prefix="PGFACADE_",
    env_file=".env",
    env_nested_delimiter="__",
    extra="forbid",
    frozen=True,
    hide_input_in_errors=True,
)

COLLECTION_CONFIG = ConfigDict(frozen=True, hide_input_in_errors=True)
