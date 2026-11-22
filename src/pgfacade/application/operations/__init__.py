"""Importing this package registers every handler. Order is irrelevant; each module self-registers via @op."""

from pgfacade.application.operations import admin, events, lifecycle, migrations, queries, roles, rows, schema  # noqa: F401
