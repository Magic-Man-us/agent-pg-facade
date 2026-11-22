from __future__ import annotations

from pathlib import Path
from typing import Annotated

from pydantic import Field, SecretStr

from pgfacade.configuration.enums import SslMode as SslMode
from pgfacade.shared.types import IntegerValue

ConfigurationPath = Annotated[Path, Field(description="Explicit local YAML or TOML settings file")]
DatabaseHost = Annotated[
    str, Field(min_length=1, max_length=2048, pattern=r"^[^\r\n\x00]+$", description="PostgreSQL host or Unix socket directory")
]
DatabasePort = Annotated[IntegerValue, Field(ge=1, le=65535, description="PostgreSQL port")]
DatabaseName = Annotated[str, Field(min_length=1, max_length=63, description="PostgreSQL database name")]
DatabaseUser = Annotated[str, Field(min_length=1, max_length=63, description="PostgreSQL login role")]


DatabaseDsn = Annotated[SecretStr, Field(min_length=1, description="PostgreSQL connection string")]
DatabasePassword = Annotated[SecretStr, Field(description="PostgreSQL connection password")]

CredentialReprFields = tuple[()]
