from __future__ import annotations

from pydantic import BaseModel

from pgfacade.contracts.types import Name
from pgfacade.infrastructure.postgres.queries.composition import Column
from pgfacade.shared.config import CONTRACT_CONFIG


class TableMetadataRequest(BaseModel):
    model_config = CONTRACT_CONFIG

    schema_name: Name
    table_name: Name


class TableMetadataResponse(BaseModel):
    model_config = CONTRACT_CONFIG

    columns: list[Column]
