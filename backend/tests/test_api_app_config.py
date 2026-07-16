from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from novel_system.api.app import SUPPORTED_DATABASE_REVISION, create_app
from novel_system.db.base import Base
from novel_system.db.session import engine
from novel_system.settings import get_settings


def _stamp_database_revision(revision: str = SUPPORTED_DATABASE_REVISION) -> None:
    with engine().begin() as connection:
        connection.exec_driver_sql(
            "CREATE TABLE IF NOT EXISTS alembic_version "
            "(version_num VARCHAR(32) NOT NULL PRIMARY KEY)"
        )
        connection.exec_driver_sql("DELETE FROM alembic_version")
        connection.exec_driver_sql(
            "INSERT INTO alembic_version (version_num) VALUES (?)",
            (revision,),
        )


def test_create_app_respects_explicit_auto_create_tables_off(monkeypatch) -> None:
    calls: list[object] = []

    monkeypatch.setenv("NOVEL_SYSTEM_AUTO_CREATE_TABLES", "false")
    monkeypatch.setattr(Base.metadata, "create_all", lambda *args, **kwargs: calls.append((args, kwargs)))

    create_app()

    assert calls == []


def test_settings_read_does_not_create_vector_store_directory(monkeypatch, tmp_path) -> None:
    vector_dir = tmp_path / "not-initialized-yet"
    monkeypatch.setenv("NOVEL_SYSTEM_CHROMA_DIR", str(vector_dir))

    settings = get_settings(include_runtime_config=False)

    assert settings.vector_store_dir == vector_dir
    assert not vector_dir.exists()


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


def test_local_only_default_rejects_non_loopback_clients() -> None:
    with TestClient(
        create_app(),
        client=("203.0.113.10", 45123),
        raise_server_exceptions=False,
    ) as client:
        response = client.get("/api/v1/chapters")
        live = client.get("/live")

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "REMOTE_ACCESS_DISABLED"
    assert response.headers["X-Request-Id"].startswith("req_")
    assert live.status_code == 200
    assert live.json() == {"status": "live"}


def test_local_only_rejects_forwarded_requests_even_from_loopback_proxy() -> None:
    with TestClient(create_app()) as client:
        response = client.get(
            "/api/v1/chapters",
            headers={"X-Forwarded-For": "198.51.100.44"},
        )

    assert response.status_code == 403
    assert response.json()["error"]["details"]["forwarded_request_rejected"] is True


def test_remote_mode_requires_token_at_startup(monkeypatch) -> None:
    monkeypatch.setenv("NOVEL_SYSTEM_LOCAL_ONLY", "false")
    monkeypatch.delenv("NOVEL_SYSTEM_REMOTE_ACCESS_TOKEN", raising=False)

    with pytest.raises(RuntimeError, match="NOVEL_SYSTEM_REMOTE_ACCESS_TOKEN"):
        create_app()


def test_remote_mode_authenticates_every_non_health_request(monkeypatch) -> None:
    monkeypatch.setenv("NOVEL_SYSTEM_LOCAL_ONLY", "false")
    monkeypatch.setenv("NOVEL_SYSTEM_REMOTE_ACCESS_TOKEN", "remote-secret")
    _stamp_database_revision()
    with TestClient(create_app(), client=("203.0.113.11", 45124)) as client:
        denied = client.get("/api/v1/chapters")
        accepted = client.get(
            "/api/v1/chapters",
            headers={"X-Novel-Access-Token": "remote-secret"},
        )
        ready = client.get("/ready")

    assert denied.status_code == 401
    assert denied.json()["error"]["code"] == "REMOTE_ACCESS_TOKEN_REQUIRED"
    assert accepted.status_code == 200
    assert ready.status_code == 200
    assert ready.json() == {"status": "ready"}


def test_ready_rejects_database_without_alembic_version() -> None:
    with TestClient(create_app()) as client:
        response = client.get("/ready")

    assert response.status_code == 503
    error = response.json()["error"]
    assert error["code"] == "SERVICE_NOT_READY"
    assert error["details"]["reason"] == "database_probe_failed"
    assert error["details"]["expected_revision"] == SUPPORTED_DATABASE_REVISION


def test_ready_rejects_outdated_database_revision() -> None:
    _stamp_database_revision("20260716_0072")
    with TestClient(create_app()) as client:
        response = client.get("/ready")

    assert response.status_code == 503
    error = response.json()["error"]
    assert error["code"] == "SERVICE_NOT_READY"
    assert error["details"] == {
        "retryable": False,
        "reason": "schema_revision_mismatch",
        "expected_revision": SUPPORTED_DATABASE_REVISION,
        "current_revision": "20260716_0072",
    }


def test_ready_rejects_head_stamp_with_missing_runtime_table() -> None:
    _stamp_database_revision()
    with engine().begin() as connection:
        connection.exec_driver_sql("DROP TABLE author_preference_profiles")
    with TestClient(create_app()) as client:
        response = client.get("/ready")

    assert response.status_code == 503
    error = response.json()["error"]
    assert error["code"] == "SERVICE_NOT_READY"
    assert error["details"]["reason"] == "schema_tables_missing"
    assert error["details"]["missing_table_count"] == 1


def test_ready_rejects_head_stamp_with_missing_required_column() -> None:
    _stamp_database_revision()
    with engine().begin() as connection:
        connection.exec_driver_sql(
            "ALTER TABLE author_preference_profiles DROP COLUMN created_by"
        )
    with TestClient(create_app()) as client:
        response = client.get("/ready")

    assert response.status_code == 503
    error = response.json()["error"]
    assert error["code"] == "SERVICE_NOT_READY"
    assert error["details"] == {
        "retryable": False,
        "reason": "schema_columns_missing",
        "expected_revision": SUPPORTED_DATABASE_REVISION,
        "missing_table_count": 1,
        "missing_column_count": 1,
    }


def test_remote_mode_requires_token_for_loopback_proxy_peer(monkeypatch) -> None:
    monkeypatch.setenv("NOVEL_SYSTEM_LOCAL_ONLY", "false")
    monkeypatch.setenv("NOVEL_SYSTEM_REMOTE_ACCESS_TOKEN", "remote-secret")
    with TestClient(create_app()) as client:
        denied = client.get("/api/v1/chapters")
        accepted = client.get(
            "/api/v1/chapters",
            headers={"X-Novel-Access-Token": "remote-secret"},
        )

    assert denied.status_code == 401
    assert denied.json()["error"]["code"] == "REMOTE_ACCESS_TOKEN_REQUIRED"
    assert accepted.status_code == 200


def test_remote_mode_allows_cors_preflight_but_authenticates_real_request(monkeypatch) -> None:
    monkeypatch.setenv("NOVEL_SYSTEM_LOCAL_ONLY", "false")
    monkeypatch.setenv("NOVEL_SYSTEM_REMOTE_ACCESS_TOKEN", "remote-secret")
    with TestClient(create_app()) as client:
        preflight = client.options(
            "/api/v2/projects",
            headers={
                "Origin": "http://127.0.0.1:5174",
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "X-Novel-Access-Token",
            },
        )
        actual = client.get(
            "/api/v2/projects",
            headers={"Origin": "http://127.0.0.1:5174"},
        )

    assert preflight.status_code == 200
    assert preflight.headers["access-control-allow-origin"] == "http://127.0.0.1:5174"
    assert actual.status_code == 401
    assert actual.json()["error"]["code"] == "REMOTE_ACCESS_TOKEN_REQUIRED"
