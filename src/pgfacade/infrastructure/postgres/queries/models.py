from __future__ import annotations

from functools import cached_property
from typing import Any

from pydantic import (
    BaseModel,
    Field,
    JsonValue,
    TypeAdapter,
    ValidationError,
    ValidationInfo,
    create_model,
    field_validator,
    model_validator,
)

from pgfacade.application.errors import RequestValidationFailure
from pgfacade.infrastructure.postgres.queries.types import (
    BUILTIN_QUERY_SOURCE,
    ParameterBoolean,
    ParameterFloat,
    ParameterIdentifier,
    ParameterInteger,
    ParameterText,
    ParameterValidationCode,
    ParameterValue,
    ParamType,
    QueryCategory,
    QueryDescription,
    QueryExtension,
    QueryName,
    QueryParameterName,
    QuerySource,
    QuerySql,
)
from pgfacade.shared.config import CONTRACT_CONFIG
from pgfacade.shared.types import SecurityFlag

IDENTIFIER_TYPES = frozenset({ParamType.TABLE, ParamType.COLUMN, ParamType.IDENTIFIER})
# Runtime query headers select annotations for dynamically generated Pydantic models.
_PARAMETER_TYPES: dict[ParamType, Any] = {
    ParamType.INTEGER: ParameterInteger,
    ParamType.FLOAT: ParameterFloat,
    ParamType.TEXT: ParameterText,
    ParamType.BOOLEAN: ParameterBoolean,
}
_PARAMETER_TYPES.update(
    {ParamType.TABLE: ParameterIdentifier, ParamType.COLUMN: ParameterIdentifier, ParamType.IDENTIFIER: ParameterIdentifier}
)
_PARAMETER_ADAPTERS: dict[ParamType, TypeAdapter[ParameterValue]] = {
    kind: TypeAdapter(annotation) for kind, annotation in _PARAMETER_TYPES.items()
}


class Param(BaseModel):
    model_config = CONTRACT_CONFIG

    type: ParamType
    default: ParameterValue = None
    description: QueryDescription = ""
    required: SecurityFlag = False

    @field_validator("default", mode="before")
    @classmethod
    def _coerce_default(cls, value: JsonValue, info: ValidationInfo) -> JsonValue:
        kind = info.data.get("type")
        if value is None or kind not in _PARAMETER_ADAPTERS:
            return value
        if kind in IDENTIFIER_TYPES | {ParamType.TEXT} and isinstance(value, str):
            value = value.strip("'\"")
        return _PARAMETER_ADAPTERS[kind].validate_python(value)


class QueryDefinition(BaseModel):
    model_config = CONTRACT_CONFIG

    category: QueryCategory
    description: QueryDescription
    sql: QuerySql
    params: dict[QueryParameterName, Param] = Field(default_factory=dict)
    requires: QueryExtension | None = None
    source: QuerySource = BUILTIN_QUERY_SOURCE

    @model_validator(mode="after")
    def validate_column_scope(self) -> QueryDefinition:
        table_count = sum(param.type == ParamType.TABLE for param in self.params.values())
        if table_count > 1 and any(param.type == ParamType.COLUMN for param in self.params.values()):
            raise ValueError("Column parameters require one table parameter; use identifiers for multi-table queries")
        return self

    @property
    def has_identifiers(self) -> SecurityFlag:
        return any(p.type in IDENTIFIER_TYPES for p in self.params.values())

    @cached_property
    def parameter_model(self) -> type[BaseModel]:
        # SQL files define parameter names and annotations only when the catalog loads.
        fields: dict[QueryParameterName, Any] = {}
        for index, (name, spec) in enumerate(self.params.items()):
            annotation = _PARAMETER_TYPES[spec.type]
            if not spec.required:
                annotation = annotation | None
            fields[f"parameter_{index}"] = (
                annotation,
                Field(alias=name, default=... if spec.required else spec.default, validate_default=True),
            )
        return create_model("QueryParameters", __config__=CONTRACT_CONFIG, **fields)

    def validate_parameters(
        self, given: dict[QueryParameterName, JsonValue], *, name: QueryName
    ) -> dict[QueryParameterName, ParameterValue]:
        try:
            return self.parameter_model.model_validate(given).model_dump(by_alias=True)
        except ValidationError as exc:
            error = exc.errors(include_input=False)[0]
            parameter = str(error["loc"][0])
            if error["type"] == ParameterValidationCode.EXTRA_FORBIDDEN:
                raise RequestValidationFailure(exc, f"unknown params for {name}: {sorted(set(given) - set(self.params))}") from None
            spec = self.params[parameter]
            if error["type"] == ParameterValidationCode.MISSING:
                raise RequestValidationFailure(exc, f"query {name!r} needs param {parameter!r} ({spec.type})") from None
            raise RequestValidationFailure(exc, f"param {parameter!r} must be {spec.type}") from None


class QueryFileRequest(BaseModel):
    model_config = CONTRACT_CONFIG

    text: QuerySql
    name: QueryName
    source: QuerySource
