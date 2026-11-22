from __future__ import annotations

from dataclasses import dataclass

from pgfacade.application.types import ExecutionProvenance
from pgfacade.configuration.settings import ANONYMOUS, Principal


@dataclass(frozen=True, slots=True)
class ExecutionContext:
    principal: Principal = ANONYMOUS
    provenance: ExecutionProvenance = ExecutionProvenance.PYTHON
