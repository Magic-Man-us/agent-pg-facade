from __future__ import annotations

from pydantic import BaseModel, RootModel

from pgfacade.contracts.enums import Operation, OperationHint
from pgfacade.contracts.types import ResultText
from pgfacade.shared.config import COLLECTION_CONFIG, CONTRACT_CONFIG
from pgfacade.shared.types import HttpRoutePath, OperationSummary, PermissionFlags


class OperationDiscoveryRequest(BaseModel):
    model_config = CONTRACT_CONFIG


class OpInfo(BaseModel):
    model_config = CONTRACT_CONFIG

    op: Operation
    path: HttpRoutePath
    summary: OperationSummary
    hint: OperationHint
    perm: PermissionFlags


class OperationDiscoveryResponse(RootModel[list[OpInfo]]):
    model_config = COLLECTION_CONFIG


class LivenessRequest(BaseModel):
    model_config = CONTRACT_CONFIG


class LivenessResponse(BaseModel):
    model_config = CONTRACT_CONFIG

    ok: bool
    message: ResultText | None = None
