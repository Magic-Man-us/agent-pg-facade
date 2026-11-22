from __future__ import annotations

from dataclasses import dataclass

from psycopg import sql

from pgfacade.infrastructure.postgres.types import DatabaseParameters


@dataclass(frozen=True, slots=True)
class PreparedQuery:
    statement: sql.SQL | sql.Composed
    parameters: DatabaseParameters
