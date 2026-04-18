from __future__ import annotations

import httpx
from sqlalchemy import select

from novel_system.db.models import SystemSecret
from novel_system.services.system_config import load_llm_provider_runtime_configs
from novel_system.services.llm_client import load_model_routing_config
from novel_system.services.prompt_builder import PromptBuilder
from novel_system.settings import get_settings


ADMIN_HEADERS = {"X-Admin-Token": "admin-token", "X-Operator-Ref": "ops.config"}


def test_system_config_read_includes_repo_defaults_without_admin_token(client) -> None:
    response = client.get("/api/v1/system-config")

    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["runtime"]["admin_configured"] is False
    assert payload["runtime"]["secret_configured"] is False
    assert payload["categories"]["models"]["source"] == "repo_default"
    assert "task_routing" in payload["categories"]["models"]["parsed"]
    assert payload["categories"]["api"]["secrets"]["llm_api_key"]["configured"] is False


def test_system_config_write_requires_admin_token(client, monkeypatch) -> None:
    monkeypatch.setenv("NOVEL_SYSTEM_ADMIN_TOKEN", "admin-token")
    monkeypatch.setenv("NOVEL_SYSTEM_CONFIG_SECRET", "config-secret")

    response = client.post(
        "/api/v1/system-config/drafts",
        json={"category": "models", "yaml_raw": "task_routing: {}\nretry_budget: {}\njob_runtime: {}\n"},
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "ADMIN_TOKEN_REQUIRED"


def test_api_config_draft_encrypts_secret_and_active_snapshot_feeds_settings(client, monkeypatch) -> None:
    monkeypatch.setenv("NOVEL_SYSTEM_ADMIN_TOKEN", "admin-token")
    monkeypatch.setenv("NOVEL_SYSTEM_CONFIG_SECRET", "config-secret")
    monkeypatch.delenv("NOVEL_SYSTEM_LLM_API_KEY", raising=False)
    yaml_raw = """
llm:
  provider: openai_compatible
  base_url: https://llm.example.test/v1
  enabled: true
  timeout_seconds: 12.5
""".strip()

    draft_response = client.post(
        "/api/v1/system-config/drafts",
        headers=ADMIN_HEADERS,
        json={"category": "api", "yaml_raw": yaml_raw, "secrets": {"llm_api_key": "super-secret-key"}},
    )
    assert draft_response.status_code == 200
    draft = draft_response.json()["data"]["snapshot"]
    assert draft["validation"]["ok"] is True
    assert "super-secret-key" not in draft_response.text
    assert draft_response.json()["data"]["secrets"]["llm_api_key"]["configured"] is True

    activate_response = client.post(f"/api/v1/system-config/{draft['snapshot_id']}/activate", headers=ADMIN_HEADERS)
    assert activate_response.status_code == 200
    assert activate_response.json()["data"]["snapshot"]["active"] is True

    read_response = client.get("/api/v1/system-config")
    assert read_response.status_code == 200
    assert "super-secret-key" not in read_response.text
    api_payload = read_response.json()["data"]["categories"]["api"]
    assert api_payload["source"] == "database_active"
    assert api_payload["secrets"]["llm_api_key"]["configured"] is True

    settings = get_settings()
    assert settings.llm_provider == "openai_compatible"
    assert settings.llm_base_url == "https://llm.example.test/v1"
    assert settings.llm_enabled is True
    assert settings.llm_timeout_seconds == 12.5
    assert settings.llm_api_key == "super-secret-key"


def test_active_model_and_prompt_snapshots_feed_runtime_loaders(client, monkeypatch) -> None:
    monkeypatch.setenv("NOVEL_SYSTEM_ADMIN_TOKEN", "admin-token")
    monkeypatch.setenv("NOVEL_SYSTEM_CONFIG_SECRET", "config-secret")
    models_yaml = """
task_routing:
  neutral_draft:
    provider: openai_compatible
    model: custom-neutral
    temperature: 0.3
    max_output_tokens: 321
    response_format: json_object
retry_budget:
  total_attempt_budget: 2
job_runtime:
  verify_lease_ttl_seconds: 99
""".strip()
    prompts_yaml = """
templates:
  neutral_draft:
    version: custom.v1
    input_token_budget: 500
    system_prompt: "Custom system prompt"
    task_prompt: "Custom task prompt"
    structured_schema:
      type: object
      additionalProperties: false
      required:
        - scene_text
      properties:
        scene_text:
          type: string
""".strip()

    model_draft = client.post(
        "/api/v1/system-config/drafts",
        headers=ADMIN_HEADERS,
        json={"category": "models", "yaml_raw": models_yaml},
    ).json()["data"]["snapshot"]
    prompt_draft = client.post(
        "/api/v1/system-config/drafts",
        headers=ADMIN_HEADERS,
        json={"category": "prompts", "yaml_raw": prompts_yaml},
    ).json()["data"]["snapshot"]
    assert client.post(f"/api/v1/system-config/{model_draft['snapshot_id']}/activate", headers=ADMIN_HEADERS).status_code == 200
    assert client.post(f"/api/v1/system-config/{prompt_draft['snapshot_id']}/activate", headers=ADMIN_HEADERS).status_code == 200

    routing_config = load_model_routing_config()
    assert routing_config.task_routing["neutral_draft"].model == "custom-neutral"
    assert routing_config.task_routing["neutral_draft"].max_output_tokens == 321

    prompt = PromptBuilder().build(
        {
            "scene_id": "CH001_SC01",
            "chapter_id": "CH001",
            "inline_digests": {
                "chapter_goal": "Goal",
                "scene_card": "Scene",
            },
        },
        "neutral_draft",
    )
    assert prompt["template_version"] == "custom.v1"
    assert prompt["system_prompt"] == "Custom system prompt"


def test_system_config_rejects_invalid_models_yaml(client, monkeypatch) -> None:
    monkeypatch.setenv("NOVEL_SYSTEM_ADMIN_TOKEN", "admin-token")
    monkeypatch.setenv("NOVEL_SYSTEM_CONFIG_SECRET", "config-secret")

    response = client.post(
        "/api/v1/system-config/drafts",
        headers=ADMIN_HEADERS,
        json={"category": "models", "yaml_raw": "task_routing: []\nretry_budget: {}\njob_runtime: {}\n"},
    )

    assert response.status_code == 422
    payload = response.json()["error"]
    assert payload["code"] == "CONFIG_VALIDATION_FAILED"
    assert "task_routing must be a mapping" in payload["message"]


def test_llm_config_provider_secret_and_node_routes_do_not_leak_credentials(client, session, monkeypatch) -> None:
    monkeypatch.setenv("NOVEL_SYSTEM_ADMIN_TOKEN", "admin-token")
    monkeypatch.setenv("NOVEL_SYSTEM_CONFIG_SECRET", "config-secret")

    provider_response = client.post(
        "/api/v1/system-config/llm/providers",
        headers=ADMIN_HEADERS,
        json={
            "provider_id": "openai_primary",
            "provider_type": "openai",
            "account_id": "acct_ops",
            "base_url": "https://api.openai.example/v1",
            "enabled": True,
            "credential_mode": "api_key",
            "api_mode": "responses",
            "models": ["gpt-5.4", "gpt-5.4-mini"],
            "api_key": "sk-secret-openai",
        },
    )

    assert provider_response.status_code == 200
    assert "sk-secret-openai" not in provider_response.text
    provider_payload = provider_response.json()["data"]["provider"]
    assert provider_payload["provider_id"] == "openai_primary"
    assert provider_payload["secret"]["configured"] is True
    assert provider_payload["secret"]["hint"].startswith("sk-")

    stored_secret = session.execute(
        select(SystemSecret).where(SystemSecret.secret_id == "llm_provider:openai_primary:api_key")
    ).scalars().one()
    assert stored_secret.secret_type == "api_key"
    assert stored_secret.metadata_json["provider_id"] == "openai_primary"
    assert "sk-secret-openai" not in stored_secret.encrypted_value

    route_response = client.post(
        "/api/v1/system-config/llm/node-routes",
        headers=ADMIN_HEADERS,
        json={
            "activate": True,
            "node_routing": {
                "neutral_draft": {
                    "provider": "openai",
                    "provider_id": "openai_primary",
                    "account_id": "acct_ops",
                    "model": "gpt-5.4",
                    "temperature": 0.25,
                    "max_output_tokens": 3200,
                    "response_format": "json_object",
                    "reasoning_level": "medium",
                    "api_mode": "responses",
                },
                "style_draft": {
                    "provider": "openai",
                    "provider_id": "openai_primary",
                    "account_id": "acct_ops",
                    "model": "gpt-5.4",
                    "temperature": 0.65,
                    "max_output_tokens": 5000,
                    "response_format": "json_object",
                    "reasoning_level": "high",
                    "api_mode": "responses",
                },
            },
            "retry_budget": {"total_attempt_budget": 4},
            "job_runtime": {},
        },
    )

    assert route_response.status_code == 200
    route_payload = route_response.json()["data"]
    assert route_payload["snapshot"]["active"] is True
    assert route_payload["snapshot"]["parsed"]["node_routing"]["neutral_draft"]["reasoning_level"] == "medium"

    overview = client.get("/api/v1/system-config/llm")
    assert overview.status_code == 200
    overview_payload = overview.json()["data"]
    assert "sk-secret-openai" not in overview.text
    assert overview_payload["providers"]["openai_primary"]["secret"]["configured"] is True
    assert overview_payload["node_routes"]["neutral_draft"]["provider_id"] == "openai_primary"
    assert overview_payload["node_routes"]["style_patch"]["model"] == "gpt-5.4"

    routing_config = load_model_routing_config()
    assert routing_config.node_routing["neutral_draft"].provider_id == "openai_primary"
    assert routing_config.node_routing["neutral_draft"].reasoning_level == "medium"
    assert routing_config.node_routing["style_patch"].reasoning_level == "high"


def test_llm_config_oauth_start_is_gemini_only_and_uses_signed_state(client, monkeypatch) -> None:
    monkeypatch.setenv("NOVEL_SYSTEM_ADMIN_TOKEN", "admin-token")
    monkeypatch.setenv("NOVEL_SYSTEM_CONFIG_SECRET", "config-secret")

    response = client.post(
        "/api/v1/system-config/llm/oauth/gemini/start",
        headers=ADMIN_HEADERS,
        json={
            "provider_id": "gemini_oauth",
            "account_id": "acct_google",
            "client_id": "google-client-id",
            "redirect_uri": "http://127.0.0.1:8000/api/v1/system-config/llm/oauth/callback",
            "scopes": ["https://www.googleapis.com/auth/cloud-platform"],
        },
    )

    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["provider_type"] == "gemini"
    assert payload["provider_id"] == "gemini_oauth"
    assert "accounts.google.com" in payload["authorization_url"]
    assert "state=" in payload["authorization_url"]
    assert payload["state"]

    unsupported = client.post(
        "/api/v1/system-config/llm/oauth/openai/start",
        headers=ADMIN_HEADERS,
        json={
            "provider_id": "openai_oauth",
            "account_id": "acct_openai",
            "client_id": "unused",
            "redirect_uri": "http://127.0.0.1/callback",
        },
    )

    assert unsupported.status_code == 422
    assert unsupported.json()["error"]["code"] == "CONFIG_OAUTH_UNSUPPORTED"


def test_llm_config_oauth_callback_exchanges_code_and_saves_server_secret(
    client,
    session,
    monkeypatch,
) -> None:
    monkeypatch.setenv("NOVEL_SYSTEM_ADMIN_TOKEN", "admin-token")
    monkeypatch.setenv("NOVEL_SYSTEM_CONFIG_SECRET", "config-secret")

    start_response = client.post(
        "/api/v1/system-config/llm/oauth/gemini/start",
        headers=ADMIN_HEADERS,
        json={
            "provider_id": "gemini_oauth",
            "account_id": "acct_google",
            "client_id": "google-client-id",
            "client_secret": "google-client-secret",
            "redirect_uri": "http://127.0.0.1:8000/api/v1/system-config/llm/oauth/callback",
            "scopes": ["https://www.googleapis.com/auth/cloud-platform"],
        },
    )
    assert start_response.status_code == 200
    state = start_response.json()["data"]["state"]

    def fake_token_exchange(url: str, *, data: dict, timeout: float):
        assert url == "https://oauth2.googleapis.com/token"
        assert timeout == 20.0
        assert data["code"] == "auth-code"
        assert data["client_id"] == "google-client-id"
        assert data["client_secret"] == "google-client-secret"
        assert data["grant_type"] == "authorization_code"
        return httpx.Response(
            200,
            json={
                "access_token": "ya29.access-token",
                "refresh_token": "1//refresh-token",
                "expires_in": 3600,
                "token_type": "Bearer",
            },
        )

    monkeypatch.setattr("novel_system.services.system_config.httpx.post", fake_token_exchange)

    callback_response = client.get(
        "/api/v1/system-config/llm/oauth/callback",
        params={"state": state, "code": "auth-code"},
    )

    assert callback_response.status_code == 200
    assert "ya29.access-token" not in callback_response.text
    assert "1//refresh-token" not in callback_response.text
    payload = callback_response.json()["data"]
    assert payload["provider"]["provider_id"] == "gemini_oauth"
    assert payload["provider"]["credential_mode"] == "oauth2"
    assert payload["provider"]["secret"]["configured"] is True
    assert payload["provider"]["secret"]["secret_type"] == "oauth2"
    assert payload["provider"]["secret"]["expires_at"]

    session.expire_all()
    token_secret = session.execute(
        select(SystemSecret).where(SystemSecret.secret_id == "llm_provider:gemini_oauth:oauth2")
    ).scalars().one()
    assert token_secret.secret_type == "oauth2"
    assert token_secret.metadata_json["account_id"] == "acct_google"
    assert "ya29.access-token" not in token_secret.encrypted_value
    assert (
        session.execute(
            select(SystemSecret).where(SystemSecret.secret_id == "llm_provider:gemini_oauth:oauth_pending")
        ).scalar_one_or_none()
        is None
    )

    runtime_configs = load_llm_provider_runtime_configs()
    assert runtime_configs["gemini_oauth"].credential_mode == "oauth2"
    assert runtime_configs["gemini_oauth"].access_token == "ya29.access-token"
    assert runtime_configs["gemini_oauth"].refresh_token == "1//refresh-token"
