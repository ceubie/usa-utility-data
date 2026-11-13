"""The proxy identity check does not need release data."""

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.backend.main import _proxy_identity
from app.backend.settings import get_settings, repository_root


def _app() -> FastAPI:
    app = FastAPI()
    app.middleware("http")(_proxy_identity)
    app.get("/api/ping")(lambda: {"ok": True})
    return app


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("REQUIRE_AUTH", "1")
    monkeypatch.setenv("PROXY_SHARED_SECRET", "local-proxy-secret")
    get_settings.cache_clear()
    with TestClient(_app()) as test_client:
        yield test_client
    get_settings.cache_clear()


def test_a_request_without_the_proxy_identity_is_refused(client: TestClient):
    assert client.get("/api/ping").status_code == 401
    assert client.get("/api/ping", headers={"x-proxy-secret": "local-proxy-secret"}).status_code == 401
    assert client.get("/api/ping", headers={"x-forwarded-user": "   ", "x-proxy-secret": "local-proxy-secret"}).status_code == 401
    assert client.get("/api/ping", headers={"x-forwarded-user": "cole", "x-proxy-secret": "wrong"}).status_code == 401


def test_a_request_with_the_proxy_identity_and_secret_is_served(client: TestClient):
    response = client.get("/api/ping", headers={"x-forwarded-user": "cole", "x-proxy-secret": "local-proxy-secret"})
    assert response.status_code == 200
    assert response.json() == {"ok": True}


def test_empty_secret_refuses_when_auth_required_and_zero_allows_passthrough(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("REQUIRE_AUTH", "1")
    monkeypatch.setenv("PROXY_SHARED_SECRET", "")
    get_settings.cache_clear()
    try:
        with TestClient(_app()) as test_client:
            assert test_client.get("/api/ping", headers={"x-forwarded-user": "cole"}).status_code == 401
        monkeypatch.setenv("REQUIRE_AUTH", "0")
        get_settings.cache_clear()
        with TestClient(_app()) as test_client:
            assert test_client.get("/api/ping").status_code == 200
    finally:
        get_settings.cache_clear()


def test_caddyfiles_bind_loopback_hosts_disable_admin_and_strip_identity_headers():
    deploy_dir: Path = repository_root() / "deploy"
    for name in ("Caddyfile", "Caddyfile.login"):
        text = (deploy_dir / name).read_text(encoding="utf-8")
        assert "admin off" in text
        assert "http://127.0.0.1:8080, http://localhost:8080 {" in text
        assert "\n:8080 {" not in text
        assert "request_header -X-Forwarded-User" in text
        assert "request_header -X-Proxy-Secret" in text
    login = (deploy_dir / "Caddyfile.login").read_text(encoding="utf-8")
    assert "basic_auth {" in login
    assert "header_up X-Forwarded-User {http.auth.user.id}" in login
    assert "header_up X-Proxy-Secret {$PROXY_SHARED_SECRET}" in login
