from __future__ import annotations

import httpx
from fastapi.testclient import TestClient
from sqlalchemy import select

from novel_system.api.app import create_app
from novel_system.db.models import SystemSecret
from novel_system.services.system_config import load_llm_provider_runtime_configs
from novel_system.services.settings_helpers import llm_generation_mode
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


def test_system_config_local_setup_mode_allows_loopback_writes_without_admin_token(monkeypatch) -> None:
    monkeypatch.delenv("NOVEL_SYSTEM_ADMIN_TOKEN", raising=False)
    monkeypatch.setenv("NOVEL_SYSTEM_CONFIG_SECRET", "config-secret")

    with TestClient(create_app(), client=("127.0.0.1", 50000)) as local_client:
        response = local_client.post(
            "/api/v1/system-config/llm/providers",
            json={
                "provider_id": "local_qwen",
                "provider_type": "openai_compatible",
                "account_id": "local",
                "base_url": "http://127.0.0.1:8080/v1/chat/completions",
                "credential_mode": "none",
                "api_mode": "chat",
                "models": ["Qwen3-14B-Q8_0.gguf"],
            },
        )

    assert response.status_code == 200
    provider = response.json()["data"]["provider"]
    assert provider["provider_id"] == "local_qwen"
    assert provider["base_url"] == "http://127.0.0.1:8080/v1"
    assert provider["credential_mode"] == "none"


def test_no_key_local_provider_counts_as_live_generation_mode(monkeypatch) -> None:
    monkeypatch.delenv("NOVEL_SYSTEM_ADMIN_TOKEN", raising=False)
    monkeypatch.setenv("NOVEL_SYSTEM_CONFIG_SECRET", "config-secret")
    monkeypatch.delenv("NOVEL_SYSTEM_LLM_API_KEY", raising=False)

    with TestClient(create_app(), client=("127.0.0.1", 50000)) as local_client:
        response = local_client.post(
            "/api/v1/system-config/llm/providers",
            json={
                "provider_id": "local_qwen",
                "provider_type": "openai_compatible",
                "account_id": "local",
                "base_url": "http://127.0.0.1:8080/v1",
                "credential_mode": "none",
                "api_mode": "responses",
                "models": ["Qwen3-14B-Q8_0.gguf"],
                "enabled": True,
            },
        )

    assert response.status_code == 200
    assert get_settings().llm_enabled is True
    assert get_settings().llm_api_key is None
    assert llm_generation_mode() == "live"


def test_llm_overview_marks_default_routes_without_provider_as_not_ready(client) -> None:
    response = client.get("/api/v1/system-config/llm")

    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["providers"] == {}
    assert payload["readiness"]["provider_count"] == 0
    assert payload["readiness"]["configured_route_count"] > 0
    assert payload["readiness"]["ready_route_count"] == 0
    assert payload["readiness"]["ready"] is False
    route = payload["node_routes"]["neutral_draft"]
    assert route["configured"] is True
    assert route["ready"] is False
    assert route["provider_missing"] is True


def test_llm_node_route_activation_requires_existing_provider_binding(client, monkeypatch) -> None:
    monkeypatch.setenv("NOVEL_SYSTEM_ADMIN_TOKEN", "admin-token")
    monkeypatch.setenv("NOVEL_SYSTEM_CONFIG_SECRET", "config-secret")

    response = client.post(
        "/api/v1/system-config/llm/node-routes",
        headers=ADMIN_HEADERS,
        json={
            "activate": True,
            "node_routing": {
                "style_draft": {
                    "provider": "openai_compatible",
                    "provider_id": "missing_qwen",
                    "model": "Qwen3-14B-Q8_0.gguf",
                    "temperature": 0.2,
                    "max_output_tokens": 3000,
                    "response_format": "json_object",
                    "reasoning_level": "medium",
                    "api_mode": "chat",
                    "credential_mode": "none",
                }
            },
            "retry_budget": {},
            "job_runtime": {},
        },
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "CONFIG_ROUTE_PROVIDER_MISSING"
    assert "missing_qwen" in response.json()["error"]["message"]


def test_llm_node_route_activation_requires_ready_provider_secret(client, monkeypatch) -> None:
    monkeypatch.setenv("NOVEL_SYSTEM_ADMIN_TOKEN", "admin-token")
    monkeypatch.setenv("NOVEL_SYSTEM_CONFIG_SECRET", "config-secret")

    provider_response = client.post(
        "/api/v1/system-config/llm/providers",
        headers=ADMIN_HEADERS,
        json={
            "provider_id": "openai_no_secret",
            "provider_type": "openai",
            "base_url": "https://api.openai.example/v1",
            "enabled": True,
            "credential_mode": "api_key",
            "api_mode": "responses",
            "models": ["gpt-5.4"],
        },
    )
    assert provider_response.status_code == 200
    assert provider_response.json()["data"]["provider"]["secret"]["configured"] is False

    response = client.post(
        "/api/v1/system-config/llm/node-routes",
        headers=ADMIN_HEADERS,
        json={
            "activate": True,
            "node_routing": {
                "neutral_draft": {
                    "provider": "openai",
                    "provider_id": "openai_no_secret",
                    "model": "gpt-5.4",
                    "temperature": 0.2,
                    "max_output_tokens": 3000,
                    "response_format": "json_object",
                    "reasoning_level": "medium",
                    "api_mode": "responses",
                }
            },
            "retry_budget": {},
            "job_runtime": {},
        },
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "CONFIG_ROUTE_PROVIDER_NOT_READY"
    assert "openai_no_secret" in response.json()["error"]["message"]


def test_llm_overview_marks_route_model_missing_when_provider_models_change(client, monkeypatch) -> None:
    monkeypatch.setenv("NOVEL_SYSTEM_ADMIN_TOKEN", "admin-token")
    monkeypatch.setenv("NOVEL_SYSTEM_CONFIG_SECRET", "config-secret")

    provider_response = client.post(
        "/api/v1/system-config/llm/providers",
        headers=ADMIN_HEADERS,
        json={
            "provider_id": "local_qwen",
            "provider_type": "openai_compatible",
            "base_url": "http://127.0.0.1:8080/v1",
            "enabled": True,
            "credential_mode": "none",
            "api_mode": "chat",
            "models": ["Qwen3-14B-Q8_0.gguf"],
        },
    )
    assert provider_response.status_code == 200

    route_response = client.post(
        "/api/v1/system-config/llm/node-routes",
        headers=ADMIN_HEADERS,
        json={
            "activate": True,
            "node_routing": {
                "style_draft": {
                    "provider": "openai_compatible",
                    "provider_id": "local_qwen",
                    "model": "Qwen3-14B-Q8_0.gguf",
                    "temperature": 0.2,
                    "max_output_tokens": 3000,
                    "response_format": "json_object",
                    "reasoning_level": "medium",
                    "api_mode": "chat",
                    "credential_mode": "none",
                }
            },
            "retry_budget": {},
            "job_runtime": {},
        },
    )
    assert route_response.status_code == 200

    provider_update = client.post(
        "/api/v1/system-config/llm/providers",
        headers=ADMIN_HEADERS,
        json={
            "provider_id": "local_qwen",
            "provider_type": "openai_compatible",
            "base_url": "http://127.0.0.1:8080/v1",
            "enabled": True,
            "credential_mode": "none",
            "api_mode": "chat",
            "models": ["AnotherLocalModel"],
        },
    )
    assert provider_update.status_code == 200

    overview = client.get("/api/v1/system-config/llm")
    payload = overview.json()["data"]
    assert payload["node_routes"]["style_draft"]["ready"] is False
    assert payload["node_routes"]["style_draft"]["model_missing"] is True
    assert payload["readiness"]["ready"] is False
    assert payload["readiness"]["blocked_route_count"] >= 1


def test_system_config_local_setup_mode_rejects_non_loopback_writes(monkeypatch) -> None:
    monkeypatch.delenv("NOVEL_SYSTEM_ADMIN_TOKEN", raising=False)
    monkeypatch.setenv("NOVEL_SYSTEM_CONFIG_SECRET", "config-secret")

    with TestClient(create_app(), client=("192.0.2.42", 50000)) as remote_client:
        response = remote_client.post(
            "/api/v1/system-config/llm/providers",
            json={
                "provider_id": "local_qwen",
                "provider_type": "openai_compatible",
                "base_url": "http://127.0.0.1:8080/v1",
                "credential_mode": "none",
                "models": ["Qwen3-14B-Q8_0.gguf"],
            },
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
    assert overview_payload["node_routes"]["neutral_draft"]["ready"] is True
    assert overview_payload["node_routes"]["style_patch"]["model"] == "gpt-5.4"
    assert overview_payload["readiness"]["ready"] is True
    assert overview_payload["readiness"]["blocked_route_count"] == 0

    routing_config = load_model_routing_config()
    assert routing_config.node_routing["neutral_draft"].provider_id == "openai_primary"
    assert routing_config.node_routing["neutral_draft"].reasoning_level == "medium"
    assert routing_config.node_routing["style_patch"].reasoning_level == "high"


def test_llm_config_supports_local_openai_compatible_without_secret(client, session, monkeypatch) -> None:
    monkeypatch.setenv("NOVEL_SYSTEM_ADMIN_TOKEN", "admin-token")
    monkeypatch.setenv("NOVEL_SYSTEM_CONFIG_SECRET", "config-secret")

    overview_response = client.get("/api/v1/system-config/llm")
    assert overview_response.status_code == 200
    catalog = overview_response.json()["data"]["provider_catalog"]
    assert catalog["openai_compatible"]["label"] == "本地 / OpenAI 兼容"
    assert "none" in catalog["openai_compatible"]["credential_modes"]
    assert catalog["openai_compatible"]["default_base_url"] == "http://127.0.0.1:11434/v1"

    provider_response = client.post(
        "/api/v1/system-config/llm/providers",
        headers=ADMIN_HEADERS,
        json={
            "provider_id": "local_ollama",
            "provider_type": "openai_compatible",
            "account_id": "local",
            "base_url": "http://127.0.0.1:11434/v1",
            "enabled": True,
            "credential_mode": "none",
            "api_mode": "chat",
            "models": ["qwen2.5:7b"],
        },
    )

    assert provider_response.status_code == 200
    payload = provider_response.json()["data"]["provider"]
    assert payload["provider_type"] == "openai_compatible"
    assert payload["credential_mode"] == "none"
    assert payload["secret"]["configured"] is False
    assert payload["secret"]["secret_type"] == "none"

    stored_secret = session.execute(
        select(SystemSecret).where(SystemSecret.secret_id == "llm_provider:local_ollama:api_key")
    ).scalars().first()
    assert stored_secret is None


def test_llm_provider_probe_verifies_local_model_listing_and_completion(client, monkeypatch) -> None:
    monkeypatch.setenv("NOVEL_SYSTEM_ADMIN_TOKEN", "admin-token")
    monkeypatch.setenv("NOVEL_SYSTEM_CONFIG_SECRET", "config-secret")

    provider_response = client.post(
        "/api/v1/system-config/llm/providers",
        headers=ADMIN_HEADERS,
        json={
            "provider_id": "local_qwen",
            "provider_type": "openai_compatible",
            "account_id": "local",
            "base_url": "https://local-llm.test/v1/chat/completions",
            "credential_mode": "none",
            "api_mode": "chat",
            "models": ["qwen3:14b"],
        },
    )
    assert provider_response.status_code == 200
    assert provider_response.json()["data"]["provider"]["base_url"] == "https://local-llm.test/v1"

    def fake_models(url: str, *, headers: dict[str, str], timeout: float):
        assert url == "https://local-llm.test/v1/models"
        assert headers == {}
        assert timeout == 10.0
        return httpx.Response(200, json={"data": [{"id": "qwen3:14b"}]})

    def fake_completion(url: str, *, headers: dict[str, str], json: dict, timeout: float):
        assert url == "https://local-llm.test/v1/chat/completions"
        assert headers == {}
        assert timeout == 10.0
        assert json["model"] == "qwen3:14b"
        assert json["messages"][0]["content"] == "ping"
        return httpx.Response(200, json={"choices": [{"message": {"content": "pong"}}]})

    monkeypatch.setattr("novel_system.services.system_config.httpx.get", fake_models)
    monkeypatch.setattr("novel_system.services.system_config.httpx.post", fake_completion)

    response = client.post(
        "/api/v1/system-config/llm/providers/local_qwen/probe",
        headers=ADMIN_HEADERS,
        json={"model": "qwen3:14b", "check_completion": True},
    )

    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["ok"] is True
    assert payload["checks"]["connection"]["ok"] is True
    assert payload["checks"]["model"]["ok"] is True
    assert payload["checks"]["completion"]["ok"] is True
    assert payload["checks"]["model"]["requested_model"] == "qwen3:14b"
    assert "qwen3:14b" in payload["message"]


def test_llm_provider_probe_reports_available_models_when_local_name_does_not_match(client, monkeypatch) -> None:
    monkeypatch.setenv("NOVEL_SYSTEM_ADMIN_TOKEN", "admin-token")
    monkeypatch.setenv("NOVEL_SYSTEM_CONFIG_SECRET", "config-secret")

    provider_response = client.post(
        "/api/v1/system-config/llm/providers",
        headers=ADMIN_HEADERS,
        json={
            "provider_id": "local_qwen",
            "provider_type": "openai_compatible",
            "account_id": "local",
            "base_url": "https://local-llm.test/v1",
            "credential_mode": "none",
            "api_mode": "chat",
            "models": ["Qwen3 14B"],
        },
    )
    assert provider_response.status_code == 200

    def fake_models(url: str, *, headers: dict[str, str], timeout: float):
        return httpx.Response(200, json={"data": [{"id": "qwen3:14b"}, {"id": "llama3.1:8b"}]})

    monkeypatch.setattr("novel_system.services.system_config.httpx.get", fake_models)

    response = client.post(
        "/api/v1/system-config/llm/providers/local_qwen/probe",
        headers=ADMIN_HEADERS,
        json={"model": "Qwen3 14B", "check_completion": True},
    )

    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["ok"] is False
    assert payload["checks"]["connection"]["ok"] is True
    assert payload["checks"]["model"]["ok"] is False
    assert payload["checks"]["model"]["requested_model"] == "Qwen3 14B"
    assert payload["checks"]["model"]["available_models"] == ["qwen3:14b", "llama3.1:8b"]
    assert "Qwen3 14B" in payload["message"]
    assert "qwen3:14b" in payload["message"]


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
