from __future__ import annotations

from fastapi.testclient import TestClient

from novel_system.api.app import create_app
from novel_system.db.base import Base


def test_create_app_respects_explicit_auto_create_tables_off(monkeypatch) -> None:
    calls: list[object] = []

    monkeypatch.setenv("NOVEL_SYSTEM_AUTO_CREATE_TABLES", "false")
    monkeypatch.setattr(Base.metadata, "create_all", lambda *args, **kwargs: calls.append((args, kwargs)))

    create_app()

    assert calls == []


def test_cors_defaults_to_local_dev_origins_without_wildcard_credentials(monkeypatch) -> None:
    monkeypatch.delenv("NOVEL_SYSTEM_CORS_ORIGINS", raising=False)
    app = create_app()

    with TestClient(app) as client:
        response = client.options(
            "/api/v2/projects",
            headers={
                "Origin": "http://127.0.0.1:5173",
                "Access-Control-Request-Method": "GET",
            },
        )
        disallowed = client.options(
            "/api/v2/projects",
            headers={
                "Origin": "https://example.invalid",
                "Access-Control-Request-Method": "GET",
            },
        )

    assert response.headers["access-control-allow-origin"] == "http://127.0.0.1:5173"
    assert disallowed.headers.get("access-control-allow-origin") != "*"


def test_unhandled_errors_return_request_id_without_leaking_exception_text() -> None:
    app = create_app()

    @app.get("/boom-for-test")
    def boom_for_test():
        raise RuntimeError("secret database password leaked here")

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/boom-for-test")

    payload = response.json()
    assert response.status_code == 500
    assert payload["error"]["code"] == "INTERNAL_ERROR"
    assert payload["error"]["message"] == "internal server error"
    assert "secret database password" not in response.text
    assert payload["request_id"].startswith("req_")
