from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from importlib.resources.abc import Traversable
from pathlib import Path

from pydantic import ValidationError

from pgfacade.application.errors import InvalidRequest
from pgfacade.infrastructure.postgres.queries.models import Param, QueryDefinition, QueryFileRequest
from pgfacade.infrastructure.postgres.queries.registry import Statement
from pgfacade.infrastructure.postgres.queries.types import (
    BUILTIN_QUERY_SOURCE,
    QueryAccess,
    QueryHeaderName,
    QueryHeaderValue,
    QueryLine,
    QueryName,
    QueryParameterName,
    QuerySource,
)

_HEADER = re.compile(r"^\s*--\s*(\w+)\s*:\s*(.*?)\s*$")
_PARAM = re.compile(r"^(?P<name>\w+)\s*:\s*(?P<type>\w+)\s*(?:=\s*(?P<default>\S+))?\s*(?P<desc>.*)$")


def parse_query_file(request: QueryFileRequest) -> QueryDefinition:
    """Parse the comment header + SQL body of a library file."""
    text, name, source = request.text, request.name, request.source
    fields: dict[QueryHeaderName, QueryHeaderValue] = {}
    params: dict[QueryParameterName, Param] = {}
    body: list[QueryLine] = []
    in_header = True
    for line in text.splitlines():
        m = _HEADER.match(line) if in_header else None
        if m is None:
            if in_header and not line.strip():
                continue
            in_header = False
            body.append(line)
            continue
        key, value = m.group(1).lower(), m.group(2)
        if key != "param":
            fields[key] = value
            continue
        pm = _PARAM.match(value)
        if pm is None:
            raise InvalidRequest("Invalid query parameter declaration; expected 'name:type[=default] description'")
        raw = pm.group("default")
        try:
            params[pm.group("name")] = Param.model_validate(
                {"type": pm.group("type"), "default": raw, "description": pm.group("desc").strip(), "required": raw is None}
            )
        except ValidationError:
            raise InvalidRequest("Invalid query parameter declaration; expected 'name:type[=default] description'") from None
    sql = "\n".join(body).strip()
    if not sql:
        raise InvalidRequest("Query file has no SQL statement after its header")
    return QueryDefinition(
        category=fields.get("category") or name.partition(".")[0],
        description=fields.get("description", ""),
        sql=sql,
        params=params,
        requires=fields.get("requires") or None,
        source=source,
    )


def _load_dir(
    entries: Iterable[Traversable | Path], source_of: Callable[[Traversable | Path], QuerySource]
) -> dict[QueryName, QueryDefinition]:
    out: dict[QueryName, QueryDefinition] = {}
    for entry in sorted(entries, key=lambda e: e.name):
        if entry.name.endswith(".sql"):
            name = entry.name[:-4]
            out[name] = parse_query_file(QueryFileRequest(text=entry.read_text(), name=name, source=source_of(entry)))
    return out


_cache: dict[Path | None, dict[QueryName, QueryDefinition]] = {}


def query_definitions(queries_dir: Path | None) -> dict[QueryName, QueryDefinition]:
    if queries_dir not in _cache:
        merged = {
            statement.query_name: parse_query_file(
                QueryFileRequest(text=statement.text, name=statement.query_name, source=BUILTIN_QUERY_SOURCE)
            )
            for statement in Statement
            if statement.access != QueryAccess.INTERNAL
        }
        if queries_dir is not None and queries_dir.is_dir():
            merged.update(_load_dir(queries_dir.iterdir(), lambda e: str(e)))
        _cache[queries_dir] = merged
    return _cache[queries_dir]


def reload() -> None:
    _cache.clear()
