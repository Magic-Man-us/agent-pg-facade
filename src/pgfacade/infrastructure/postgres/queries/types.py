from __future__ import annotations

from enum import StrEnum
from typing import Annotated

from pydantic import Field

from pgfacade.contracts.enums import ParamType as ParamType
from pgfacade.contracts.types import QueryCategory as QueryCategory
from pgfacade.contracts.types import QueryDescription as QueryDescription
from pgfacade.contracts.types import QueryName as QueryName
from pgfacade.contracts.types import QueryParameterName as QueryParameterName
from pgfacade.contracts.types import QuerySource as QuerySource
from pgfacade.shared.types import FloatValue, IntegerValue


class QueryAccess(StrEnum):
    INTERNAL = "internal"
    PUBLIC = "public"
    ADMIN = "admin"


class ParameterValidationCode(StrEnum):
    EXTRA_FORBIDDEN = "extra_forbidden"
    MISSING = "missing"


ParameterInteger = IntegerValue
ParameterFloat = FloatValue
ParameterText = Annotated[str, Field(description="Text query parameter")]
ParameterBoolean = Annotated[bool, Field(description="Boolean query parameter")]
ParameterIdentifier = Annotated[str, Field(min_length=1, description="Quoted SQL identifier parameter")]
ParameterValue = Annotated[str | int | float | bool | None, Field(description="Validated scalar query parameter")]
QueryResourcePath = Annotated[str, Field(min_length=1, description="Packaged SQL resource path")]
QuerySql = Annotated[str, Field(min_length=1)]
BUILTIN_QUERY_SOURCE: QuerySource = "builtin"
QueryExtension = Annotated[str, Field(min_length=1)]

QueryHeaderName = Annotated[str, Field(description="Curated SQL metadata header name")]
QueryHeaderValue = Annotated[str, Field(description="Curated SQL metadata header value")]
QueryLine = Annotated[str, Field(description="One line of a curated SQL file")]
