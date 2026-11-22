---
name: postgres
description: Query and inspect a PostgreSQL database through the PGFacade tools (pg_table_describe, pg_rows_select, pg_rows_aggregate, pg_query_run, ...). Use when the user asks about data in their database, table structure, row counts, recent rows, duplicates, or database size and health, or asks to insert, update, or delete rows.
---

# Working with PostgreSQL through PGFacade

The `postgres` MCP server exposes one typed tool per database operation. Tool names start with `pg_`. Which tools exist depends on what the user enabled; a tool that is not listed is not permitted.

## Call shape

Every tool takes one `request` argument with the operation `kind` and a typed `input`:

```json
{"request": {"kind": "rows.count", "input": {"table": "public.orders"}}}
```

The tool `pg_rows_count` takes kind `rows.count`: drop `pg_`, turn the first `_` into a `.`.

Every response has the same envelope:

```json
{"kind": "rows.count", "outcome": {"status": "success", "data": {"count": 3}}}
```

On failure `outcome.status` is `"error"` and `outcome.error` carries `code`, `reason`, `message`, and `status`. Read those fields; do not parse the message.

Address tables as `schema.table`, or `table` for the default schema.

## Order of work

1. `pg_server_whoami` once per session: the database role, whether it is read-only, and which capabilities are on.
2. Find the table. The server's instructions list the tables that existed when the session started, with estimated row counts, so check there first. Call `pg_table_list` when the list is absent, cut off at 50, or may be stale; each entry adds `total_bytes`, `kind`, and `comment`.
3. `pg_table_describe` before the first query on a table: columns with types, primary key, constraints, indexes, and the view definition.
4. Query with the narrowest tool that answers the question (next section).

## Pick the cheapest tool

| Question | Tool | Returns |
|---|---|---|
| How many rows match? | `pg_rows_count` | `{count}` |
| Does any row match? | `pg_rows_exists` | a boolean flag |
| One row by primary key | `pg_rows_get` | `{row}` or `{row: null}` |
| Totals, averages, min/max, group by | `pg_rows_aggregate` | rows of aggregates |
| Rows themselves | `pg_rows_select` | `columns`, `rows`, `rowcount`, `truncated` |
| Newest rows, counts per day, duplicates, orphans, distinct values | `pg_query_run` | rows |
| Many rows for a file | `pg_rows_export_csv` | CSV text |

Never select rows in order to count or sum them. The database does that in one call with `pg_rows_count` or `pg_rows_aggregate`, and the rows never enter the conversation.

## Selecting rows

```json
{"request": {"kind": "rows.select", "input": {
  "table": "public.orders",
  "columns": ["id", "status", "total"],
  "where": [{"kind": "cmp", "column": "status", "op": "eq", "value": "paid"}],
  "order_by": [{"column": "created_at", "desc": true}],
  "limit": 20
}}}
```

- Always pass `columns` and `limit`. Without `columns` every column comes back; without `limit` up to 1000 rows do.
- `truncated: true` means more rows matched than were returned. Page with `offset` and a stable `order_by` (the primary key).
- `with_total: true` adds the full match count as `total`, at the cost of a second query. Ask for it only when the total is needed.
- `match` is shorthand for equality: `"match": {"status": "paid"}`.
- `distinct: true` removes duplicate rows.

## Filters

`where` is a list of filter objects, combined with AND. Each has a `kind`:

| kind | Fields | Meaning |
|---|---|---|
| `cmp` | `column`, `op`, `value` | compare; `op` is `eq` `ne` `lt` `lte` `gt` `gte` `like` `ilike` `not_like` `not_ilike` `regex` `iregex` |
| `in` | `column`, `values`, `negate` | value in a list |
| `is_null` | `column`, `negate` | null check |
| `between` | `column`, `low`, `high` | inclusive range |
| `contains` | `column`, `value` | jsonb or array containment |
| `text_search` | `column`, `query`, `mode`, `config` | full-text search; `mode` is `websearch`, `plain`, or `phrase` |
| `and` / `or` | `filters` | combine a list of filters |
| `not` | `filter` | negate one filter |

Filter on indexed columns when the table is large; `pg_table_describe` lists the indexes. A leading-wildcard `like`, a `regex`, or a `text_search` on a plain text column scans the whole table.

## Aggregating

```json
{"request": {"kind": "rows.aggregate", "input": {
  "table": "public.orders",
  "aggregates": [{"fn": "count", "alias": "orders"}, {"fn": "sum", "column": "total", "alias": "revenue"}],
  "group_by": ["status"],
  "order_by": [{"column": "revenue", "desc": true}]
}}}
```

`fn` is `count`, `count_distinct`, `sum`, `avg`, `min`, or `max`. `count` without a `column` counts rows. `order_by` may name an alias.

## Curated queries

`pg_query_run` runs a named, parameterized query. `pg_query_list` returns the ones this session may run, with their parameters. The row and table queries need no extra permission:

```json
{"request": {"kind": "query.run", "input": {"name": "rows.recent", "params": {"table": "public.orders", "column": "created_at", "limit": 10}}}}
```

The full list is in [reference/queries.md](reference/queries.md).

## Several steps at once

`pg_batch_run` runs a list of requests in one transaction and one round trip. Any failure rolls back all of them. Use it for multi-step changes that must apply together, and for a handful of related reads.

```json
{"request": {"kind": "batch.run", "input": {"requests": [
  {"kind": "rows.count", "input": {"table": "public.orders"}},
  {"kind": "rows.count", "input": {"table": "public.customers"}}
]}}}
```

Batches cannot be nested.

## Writing

The write tools exist only when the user turned read-only off. `pg_rows_update` and `pg_rows_delete` refuse to run without a filter unless `allow_all` is `true`; set it only when the user asked to change every row. Before a write that affects many rows, run `pg_rows_count` with the same filter and tell the user the number.

## Limits

- 1000 rows per read, 100,000 rows per CSV export.
- 30 seconds per statement. A timeout returns `code: "timeout"`; narrow the filter or aggregate instead of retrying the same call.
- 1 MiB per request.

## Errors

| Code | What to do |
|---|---|
| `forbidden` | The operation or table is not permitted. Tell the user which capability is missing; do not retry or look for another route. |
| `not_found` | The table, column, or query name is wrong. Check with `pg_table_list` or `pg_table_describe`. |
| `validation_error` | The request shape is wrong. `error.details.issues` names each field path and problem. |
| `conflict` | A constraint or concurrent change blocked the write. |
| `timeout` | The statement ran too long. Narrow it. |
| `unavailable` | The database is unreachable. Report it. |

Every tool, its input fields, and the permission it needs: [reference/tools.md](reference/tools.md).
