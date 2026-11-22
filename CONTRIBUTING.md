# Contributing

## Set up

You need [uv](https://docs.astral.sh/uv/getting-started/installation/) and Python 3.12 or newer.

```sh
uv sync --locked
```

## Run the checks

```sh
uv run --locked tox
```

This runs lint, formatting, strict type checking, a build, and the tests that need no database.

The integration tests need a disposable PostgreSQL database. They create and drop their own tables, so never point them at a database you care about:

```sh
docker run -d --rm --name pgfacade-test -e POSTGRES_PASSWORD=test -e POSTGRES_DB=pgfacade_test -p 127.0.0.1:5433:5432 postgres:17
PGFACADE_TEST_DSN=postgresql://postgres:test@127.0.0.1:5433/pgfacade_test uv run --locked pytest
docker stop pgfacade-test
```

CI runs the full suite against PostgreSQL 17 on Python 3.12, 3.13, and 3.14.

## Make a change

- Read the [development guide](docs/development.md) first. It states where each kind of code lives and the typing rules.
- Add or change a test with every behavior change.
- Adding or changing an operation changes the generated reference pages in [plugin/skills/postgres/reference](plugin/skills/postgres/reference). The tests fail until they match the operation catalog.
- Use conventional commit messages: `feat:`, `fix:`, `refactor:`, `test:`, `docs:`, `build:`, `chore:`.
- Keep a pull request to one change.

## Report a problem

Open an issue for bugs and feature requests. Report vulnerabilities privately as described in the [security policy](SECURITY.md).
