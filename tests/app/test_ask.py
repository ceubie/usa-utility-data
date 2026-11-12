"""Ask reports a configuration error and does not call a model."""

import socket

import pytest
from fastapi.testclient import TestClient

from app.backend.main import _HOST, create_app
from app.backend.settings import get_settings


def test_service_binds_to_loopback_only():
    assert _HOST == "127.0.0.1"


@pytest.mark.requires_release
def test_ask_returns_a_configuration_error_without_a_network_connection(monkeypatch: pytest.MonkeyPatch):
    for name in ("AZURE_OPENAI_ENDPOINT", "AZURE_OPENAI_DEPLOYMENT", "AZURE_OPENAI_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    get_settings.cache_clear()

    def refuse_connection(*_args, **_kwargs):
        raise AssertionError("network connection opened")

    with TestClient(create_app()) as client:
        monkeypatch.setattr(socket, "create_connection", refuse_connection)
        response = client.post(
            "/api/ask",
            json={"question": "Which water systems serve Travis County, Texas?"},
        )
    assert response.status_code == 200
    assert "event: error" in response.text
    assert "AZURE_OPENAI_ENDPOINT" in response.text
    assert "AZURE_OPENAI_DEPLOYMENT" in response.text
    assert "AZURE_OPENAI_API_KEY" in response.text
    get_settings.cache_clear()
