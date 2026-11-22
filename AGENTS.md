# Engineering guidance

Follow the [development guide](docs/development.md), including its [data ownership policy](docs/development.md#data-ownership).

- Always use typed standard-library dataclasses for trusted internal records; use `slots=True` and `frozen=True` when immutable.
- Use Pydantic v2 for boundary validation and serialization contracts, and `BaseSettings` for settings. Do not revalidate trusted internal calls.
- Keep services as ordinary classes and database resources as their native driver types.
- Define reusable constraints and coercion in semantic annotated aliases in the owning `types.py` module.
- Validate external data at entry, pass typed objects internally, and serialize through the owning boundary contract.
- Preserve shared typed application dispatch for HTTP and MCP transports.
- Keep runtime resources inside the installable package. Runnable examples own separate manifests and tests.
- Run `uv run --locked tox` for the standard checks. Database integration tests require a disposable database as described in the development guide.
