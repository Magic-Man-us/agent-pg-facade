from __future__ import annotations

from pydantic import BaseModel, Field

from pgfacade.shared.config import CONTRACT_CONFIG
from pgfacade.shared.types import ApiKey


class IdentityLookupRequest(BaseModel):
    model_config = CONTRACT_CONFIG

    credential: ApiKey = Field(repr=False)
