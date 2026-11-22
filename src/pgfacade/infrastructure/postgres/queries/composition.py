"""Safe SQL composition: catalog-validated identifiers, typed bound parameters, filter trees."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import ClassVar, LiteralString

from psycopg import AsyncCursor, sql
from psycopg.rows import DictRow
from psycopg.types.json import Json, Jsonb
from pydantic import ConfigDict, JsonValue

from pgfacade.application.errors import InvalidRequest
from pgfacade.contracts.base import (
    And,
    Between,
    Cmp,
    Contains,
    Filter,
    Filtered,
    In,
    IsNull,
    Not,
    Or,
    OrderBy,
    Params,
    QueryResult,
    TextSearch,
)
from pgfacade.contracts.enums import AggregateFunction, CmpOp, NullOrder, TextSearchMode
from pgfacade.contracts.rows import Aggregate, DoNothing, DoUpdate, OnConflict
from pgfacade.contracts.types import MAX_IDENTIFIER_BYTES, Name, ResultLabel, RowInput, RowLimit, SqlStatement
from pgfacade.infrastructure.postgres.types import (
    BoundParameters,
    DatabaseValue,
    KnownPostgresTypeCategory,
    PostgresTypeCategory,
    PostgresTypeName,
    PrimaryKeyPosition,
    RelationKind,
    SqlCommandTag,
    SqlKeyword,
)
from pgfacade.shared.config import CONTRACT_CONFIG
from pgfacade.shared.types import SecurityFlag

_DML_TAGS = frozenset(SqlCommandTag)
_JSON_TYPE: LiteralString = "json"
_JSONB_TYPE: LiteralString = "jsonb"
_TSVECTOR_TYPE: LiteralString = "tsvector"
_CAST_FIX: dict[str, LiteralString] = {"character": "bpchar", "character[]": "bpchar[]", "bit": "varbit", "bit[]": "varbit[]"}
_CMP_OPS: dict[CmpOp, LiteralString] = {CmpOp.EQ: "=", CmpOp.NE: "<>", CmpOp.LT: "<", CmpOp.LTE: "<=", CmpOp.GT: ">", CmpOp.GTE: ">="}
_TEXT_OPS: dict[CmpOp, LiteralString] = {
    CmpOp.LIKE: "LIKE",
    CmpOp.ILIKE: "ILIKE",
    CmpOp.NOT_LIKE: "NOT LIKE",
    CmpOp.NOT_ILIKE: "NOT ILIKE",
    CmpOp.REGEX: "~",
    CmpOp.IREGEX: "~*",
}
_TSQUERY: dict[TextSearchMode, LiteralString] = {
    TextSearchMode.WEBSEARCH: "websearch_to_tsquery",
    TextSearchMode.PLAIN: "plainto_tsquery",
    TextSearchMode.PHRASE: "phraseto_tsquery",
}
_AGG: dict[AggregateFunction, LiteralString] = {
    AggregateFunction.COUNT: "count",
    AggregateFunction.SUM: "sum",
    AggregateFunction.AVG: "avg",
    AggregateFunction.MIN: "min",
    AggregateFunction.MAX: "max",
}
_NULLS: dict[NullOrder | None, LiteralString] = {NullOrder.FIRST: " NULLS FIRST", NullOrder.LAST: " NULLS LAST", None: ""}


@dataclass(frozen=True, slots=True)
class Column:
    __pydantic_config__: ClassVar[ConfigDict] = CONTRACT_CONFIG

    name: Name
    regtype: PostgresTypeName
    category: PostgresTypeCategory
    pk_pos: PrimaryKeyPosition | None
    relkind: RelationKind

    @property
    def is_array(self) -> SecurityFlag:
        return self.category == KnownPostgresTypeCategory.ARRAY

    @property
    def is_json(self) -> SecurityFlag:
        return self.regtype in (_JSON_TYPE, _JSONB_TYPE)

    @property
    def cast(self) -> sql.SQL:
        return sql.SQL(_CAST_FIX.get(self.regtype, self.regtype))

    def adapt(self, value: DatabaseValue) -> DatabaseValue:
        if value is None:
            return None
        if self.regtype == _JSON_TYPE:
            return Json(value)
        if self.regtype == _JSONB_TYPE or isinstance(value, dict):
            return Jsonb(value)
        return value


@dataclass(frozen=True, slots=True)
class TableMeta:
    schema_name: Name
    name: Name
    kind: RelationKind
    columns: Mapping[Name, Column]
    primary_key: tuple[Name, ...]

    @property
    def ident(self) -> sql.Identifier:
        return sql.Identifier(self.schema_name, self.name)

    @property
    def label(self) -> ResultLabel:
        return f"{self.schema_name}.{self.name}"


class Binder:
    """Collects positional params while composing SQL; validates columns against the table."""

    def __init__(self, meta: TableMeta) -> None:
        self.meta = meta
        self.params: BoundParameters = []

    def col(self, name: Name) -> sql.Identifier:
        if name not in self.meta.columns:
            raise InvalidRequest(f'column "{name}" does not exist on {self.meta.label}')
        return sql.Identifier(name)

    def value(self, column: Name, value: DatabaseValue) -> sql.Composable:
        self.col(column)
        c = self.meta.columns[column]
        self.params.append(c.adapt(value))
        if c.is_json:
            return sql.Placeholder()
        return sql.SQL("{}::{}").format(sql.Placeholder(), c.cast)

    def typed(self, value: DatabaseValue, pg_type: LiteralString) -> sql.Composable:
        self.params.append(value)
        return sql.SQL("{}::{}").format(sql.Placeholder(), sql.SQL(pg_type))


def text(statement: SqlStatement) -> sql.SQL:
    """Wrap caller-supplied SQL. Only for paths gated by the raw-SQL permission or curated catalogs."""
    return sql.SQL(statement)


def kw(word: SqlKeyword) -> sql.SQL:
    """Wrap a keyword chosen from a Literal type (already validated by Pydantic)."""
    return sql.SQL(word)


def flag(on: SecurityFlag, word: LiteralString) -> sql.SQL:
    return sql.SQL(word if on else "")


def adapt_params(params: Params) -> BoundParameters | dict[ResultLabel, DatabaseValue] | None:
    def wrap(v: JsonValue) -> DatabaseValue:
        return Jsonb(v) if isinstance(v, dict) else v

    if params is None:
        return None
    if isinstance(params, dict):
        return {k: wrap(v) for k, v in params.items()}
    return [wrap(v) for v in params]


def literal(value: JsonValue) -> sql.Composable:
    return sql.Literal(Jsonb(value) if isinstance(value, dict) else value)


# ---------------------------------------------------------------- filters, clauses


def filter_sql(f: Filter, b: Binder) -> sql.Composable:
    match f:
        case Cmp(column=column, op=op, value=value):
            ident = b.col(column)
            if value is None and op in (CmpOp.EQ, CmpOp.NE):
                return sql.SQL("{} IS NOT NULL" if op == CmpOp.NE else "{} IS NULL").format(ident)
            if op in _TEXT_OPS:
                return sql.SQL("{} {} {}").format(ident, sql.SQL(_TEXT_OPS[op]), b.typed(value, "text"))
            return sql.SQL("{} {} {}").format(ident, sql.SQL(_CMP_OPS[op]), b.value(column, value))
        case In(column=column, values=values, negate=negate):
            ident = b.col(column)
            if not values:
                return sql.SQL("TRUE" if negate else "FALSE")
            items = sql.SQL(", ").join([b.value(column, v) for v in values])
            return sql.SQL("{} NOT IN ({})" if negate else "{} IN ({})").format(ident, items)
        case IsNull(column=column, negate=negate):
            return sql.SQL("{} IS NOT NULL" if negate else "{} IS NULL").format(b.col(column))
        case Between(column=column, low=low, high=high):
            ident = b.col(column)
            lo = b.value(column, low)
            hi = b.value(column, high)
            return sql.SQL("{} BETWEEN {} AND {}").format(ident, lo, hi)
        case Contains(column=column, value=value):
            ident = b.col(column)
            target = b.meta.columns[column]
            if not (target.is_json or target.is_array):
                raise InvalidRequest(f'contains needs a jsonb or array column; "{column}" is {target.regtype}')
            return sql.SQL("{} @> {}").format(ident, b.value(column, value))
        case TextSearch(column=column, query=query, config=config, mode=mode):
            ident = b.col(column)
            if b.meta.columns[column].regtype == _TSVECTOR_TYPE:
                vector: sql.Composable = ident
            else:
                vector = sql.SQL("to_tsvector({}, {})").format(b.typed(config, "regconfig"), ident)
            tsq = sql.SQL("{}({}, {})").format(sql.SQL(_TSQUERY[mode]), b.typed(config, "regconfig"), b.typed(query, "text"))
            return sql.SQL("{} @@ {}").format(vector, tsq)
        case And(filters=filters):
            return sql.SQL("({})").format(sql.SQL(" AND ").join([filter_sql(x, b) for x in filters]))
        case Or(filters=filters):
            return sql.SQL("({})").format(sql.SQL(" OR ").join([filter_sql(x, b) for x in filters]))
        case Not(filter=inner):
            return sql.SQL("NOT ({})").format(filter_sql(inner, b))
    raise InvalidRequest(f"unsupported filter: {f!r}")


def where_sql(spec: Filtered, b: Binder) -> sql.Composable:
    parts = [filter_sql(f, b) for f in spec.where]
    parts += [filter_sql(Cmp(column=k, value=v), b) for k, v in spec.match.items()]
    return (sql.SQL(" WHERE ") + sql.SQL(" AND ").join(parts)) if parts else sql.SQL("")


def order_sql(order_by: Sequence[OrderBy], b: Binder, aliases: frozenset[ResultLabel] = frozenset()) -> sql.Composable:
    if not order_by:
        return sql.SQL("")
    parts = [
        sql.SQL("{} {}{}").format(
            sql.Identifier(o.column) if o.column in aliases else b.col(o.column),
            sql.SQL("DESC" if o.desc else "ASC"),
            sql.SQL(_NULLS[o.nulls]),
        )
        for o in order_by
    ]
    return sql.SQL(" ORDER BY ") + sql.SQL(", ").join(parts)


def returning_sql(columns: Sequence[Name], b: Binder) -> sql.Composable:
    if not columns:
        return sql.SQL("")
    if "*" in columns:
        return sql.SQL(" RETURNING *")
    return sql.SQL(" RETURNING ") + sql.SQL(", ").join([b.col(c) for c in columns])


def on_conflict_sql(oc: OnConflict | None, inserted: Sequence[Name], b: Binder) -> sql.Composable:
    match oc:
        case None:
            return sql.SQL("")
        case DoNothing(target=target):
            tgt = sql.SQL(" ({})").format(sql.SQL(", ").join([b.col(c) for c in target])) if target else sql.SQL("")
            return sql.SQL(" ON CONFLICT{} DO NOTHING").format(tgt)
        case DoUpdate(target=target, update=update):
            tgt = sql.SQL(", ").join([b.col(c) for c in target])
            cols = update if update is not None else [c for c in inserted if c not in target]
            if not cols:
                return sql.SQL(" ON CONFLICT ({}) DO NOTHING").format(tgt)
            sets = sql.SQL(", ").join([sql.SQL("{0} = EXCLUDED.{0}").format(b.col(c)) for c in cols])
            return sql.SQL(" ON CONFLICT ({}) DO UPDATE SET {}").format(tgt, sets)
    raise InvalidRequest(f"unsupported on_conflict: {oc!r}")


def aggregate_sql(a: Aggregate, b: Binder) -> sql.Composable:
    if a.column is None:
        return sql.SQL("count(*)")
    col = b.col(a.column)
    if a.fn == AggregateFunction.COUNT_DISTINCT:
        return sql.SQL("count(DISTINCT {})").format(col)
    return sql.SQL("{}({})").format(sql.SQL(_AGG[a.fn]), col)


def key_match(meta: TableMeta, key: JsonValue | Mapping[ResultLabel, JsonValue]) -> RowInput:
    if not meta.primary_key:
        raise InvalidRequest(f"{meta.label} has no primary key")
    if isinstance(key, Mapping):
        if set(key) != set(meta.primary_key):
            raise InvalidRequest(f"key must have exactly {list(meta.primary_key)}")
        return dict(key)
    if len(meta.primary_key) != 1:
        raise InvalidRequest(f"{meta.label} has composite key {list(meta.primary_key)}; pass an object")
    return {meta.primary_key[0]: key}


def truncate_name(name: Name) -> Name:
    while len(name.encode()) > MAX_IDENTIFIER_BYTES:
        name = name[:-1]
    return name


async def collect(cur: AsyncCursor[DictRow], limit: RowLimit | None) -> QueryResult:
    status = cur.statusmessage
    if cur.description is None:
        return QueryResult(rowcount=max(cur.rowcount, 0), status=status)
    rows = await cur.fetchall()
    truncated = limit is not None and len(rows) > limit
    if truncated:
        rows = rows[:limit]
    is_dml = status is not None and status.split(" ", 1)[0] in _DML_TAGS
    return QueryResult(
        columns=[d.name for d in cur.description],
        rows=rows,
        rowcount=cur.rowcount if is_dml else len(rows),
        truncated=truncated,
        status=status,
    )
