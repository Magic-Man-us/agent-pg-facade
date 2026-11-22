from __future__ import annotations

from pgfacade.application.operations.events import default_channel


def test_short_generated_channel_preserves_the_existing_name() -> None:
    assert default_channel("public", "notes") == "pgfacade:public.notes"


def test_generated_channel_fits_postgres_utf8_identifier_limit() -> None:
    channel = default_channel("界" * 20, "表" * 20)
    assert len(channel.encode()) <= 63
    assert channel == default_channel("界" * 20, "表" * 20)


def test_long_shared_prefixes_generate_distinct_channels() -> None:
    schema = "s" * 63
    first = default_channel(schema, "table_one")
    second = default_channel(schema, "table_two")
    assert first != second
    assert len(first.encode()) <= 63
    assert len(second.encode()) <= 63
