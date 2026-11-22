"""pgfacade: one typed Call over Postgres, served over REST and MCP."""

from __future__ import annotations

__version__ = "0.5.0"

from pgfacade.application.context import ExecutionContext  # noqa: E402
from pgfacade.application.errors import Forbidden, InvalidRequest, NotFound, PgFacadeError, Timeout, Unauthenticated
from pgfacade.application.registry import REGISTRY, OpSpec, Perm  # noqa: E402
from pgfacade.configuration.settings import ANONYMOUS, PgSettings, Principal  # noqa: E402
from pgfacade.contracts.base import RequestContract
from pgfacade.contracts.enums import ErrorCode, Operation, Outcome  # noqa: E402
from pgfacade.contracts.envelopes import ApiError, Failure, ResponseEnvelope, Success  # noqa: E402
from pgfacade.myapp import MyApp  # noqa: E402

__all__ = [
    "ANONYMOUS",
    "ApiError",
    "ErrorCode",
    "Operation",
    "Outcome",
    "Failure",
    "RequestContract",
    "ResponseEnvelope",
    "Success",
    "Forbidden",
    "InvalidRequest",
    "NotFound",
    "OpSpec",
    "Perm",
    "MyApp",
    "ExecutionContext",
    "PgFacadeError",
    "PgSettings",
    "Principal",
    "REGISTRY",
    "Timeout",
    "Unauthenticated",
    "__version__",
]
