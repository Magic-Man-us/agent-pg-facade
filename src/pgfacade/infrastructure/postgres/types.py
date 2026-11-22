from __future__ import annotations

from collections.abc import Mapping, Sequence
from enum import StrEnum, unique
from typing import Annotated

from pydantic import Field

from pgfacade.contracts.types import ResultLabel
from pgfacade.shared.types import FloatValue, IntegerValue

# Driver parameters include native Python values and driver-owned adaptation wrappers.
DatabaseValue = object
BoundParameters = list[DatabaseValue]
DatabaseParameters = Sequence[DatabaseValue] | Mapping[ResultLabel, DatabaseValue] | None
PostgresTypeName = Annotated[str, Field(min_length=1, description="PostgreSQL catalog type name")]
MonotonicSeconds = Annotated[FloatValue, Field(ge=0, description="Monotonic clock reading in seconds")]
SqlKeyword = Annotated[str, Field(description="SQL keyword selected from a validated operation")]
PostgresTypeCategory = Annotated[str, Field(min_length=1, max_length=1, description="PostgreSQL type category")]
PrimaryKeyPosition = Annotated[IntegerValue, Field(ge=0, description="Position of a column within its primary key")]


@unique
class RelationKind(StrEnum):
    TABLE = "r"
    INDEX = "i"
    SEQUENCE = "S"
    TOAST = "t"
    VIEW = "v"
    MATERIALIZED_VIEW = "m"
    COMPOSITE = "c"
    FOREIGN_TABLE = "f"
    PARTITIONED_TABLE = "p"
    PARTITIONED_INDEX = "I"


@unique
class KnownPostgresTypeCategory(StrEnum):
    ARRAY = "A"
    BOOLEAN = "B"
    COMPOSITE = "C"
    DATETIME = "D"
    ENUM = "E"
    GEOMETRIC = "G"
    NETWORK = "I"
    NUMERIC = "N"
    PSEUDO = "P"
    RANGE = "R"
    STRING = "S"
    TIMESPAN = "T"
    USER_DEFINED = "U"
    BIT_STRING = "V"
    UNKNOWN = "X"
    INTERNAL = "Z"


@unique
class SqlCommandTag(StrEnum):
    INSERT = "INSERT"
    UPDATE = "UPDATE"
    DELETE = "DELETE"
    MERGE = "MERGE"
    COPY = "COPY"
