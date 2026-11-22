from __future__ import annotations

from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from pgfacade import MyApp, PgSettings, Principal
from pgfacade.contracts.enums import ErrorCode
from pgfacade.contracts.envelopes import Failure
from pgfacade.contracts.types import ResultText
from pgfacade.webapp import create_app


@pytest.mark.parametrize("channel", [",,", "x" * 64, "é" * 32])
def test_invalid_stream_channels_fail_before_opening_a_database_connection(channel: ResultText, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = PgSettings(_env_file=None, allow_listen=True, keys={"test": Principal(listen=True)})
    facade = MyApp(settings)
    connection = Mock(side_effect=AssertionError("Invalid channels must not reach the database"))
    monkeypatch.setattr(facade, "dedicated", connection)
    client = TestClient(create_app(settings, facade), headers={"Authorization": "Bearer test"})
    response = client.get("/events/" + channel)
    assert response.status_code == 422
    error = Failure.model_validate_json(response.content).error
    assert error.code == ErrorCode.VALIDATION_ERROR
    assert error.details is not None
    assert error.details.issues
    connection.assert_not_called()
