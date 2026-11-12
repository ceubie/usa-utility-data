"""The proxy identity check does not need release data."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.backend.main import _proxy_identity
from app.backend.settings import get_settings


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("REQUIRE_AUTH", "1")
    monkeypatch.setenv("PROXY_SHARED_SECRET", "local-proxy-secret")
    get_settings.cache_clear()
    app = FastAPI()
    app.middleware("http")(_proxy_identity)
    app.get("/api/ping")(lambda: {"ok": True})
    with TestClient(app) as test_client:
        yield test_client
    get_settings.cache_clear()


def test_a_request_without_the_proxy_identity_is_refused(client: TestClient):
    assert client.get("/api/ping").status_code == 401
    assert client.get("/api/ping", headers={"x-proxy-secret": "local-proxy-secret"}).status_code == 401
    assert client.get("/api/ping", headers={"x-forwarded-user": "cole", "x-proxy-secret": "wrong"}).status_code == 401


def test_a_request_with_the_proxy_identity_and_secret_is_served(client: TestClient):
    response = client.get("/api/ping", headers={"x-forwarded-user": "cole", "x-proxy-secret": "local-proxy-secret"})
    assert response.status_code == 200
    assert response.json() == {"ok": True}
