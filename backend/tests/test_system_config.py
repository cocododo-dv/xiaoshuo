from __future__ import annotations

import httpx
from fastapi.testclient import TestClient
from sqlalchemy import select

from novel_system.api.app import create_app
from novel_system.db.models import LlmCall, SystemSecret
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
    assert "node_catalog" in payload
    assert payload["node_catalog"]["project_outline_plan"]["status"] == "active"
    assert payload["node_catalog"]["writer_deep_review"]["group"] == "deep_review"
    assert payload["node_catalog"]["scene_auto_rewrite"]["requires_llm"] is True
    assert payload["providers"] == {}
    assert payload["readiness"]["provider_count"] == 0
    assert payload["readiness"]["configured_route_count"] > 0
    assert payload["readiness"]["ready_route_count"] == 0
    assert payload["readiness"]["ready"] is False
    assert "project_outline_plan" in payload["missing_active_routes"]
    assert "writer_deep_review" in payload["missing_active_routes"]
    route = payload["node_routes"]["neutral_draft"]
    assert route["configured"] is True
    assert route["ready"] is False
    assert route["provider_missing"] is True


def test_llm_sync_missing_routes_populates_all_active_nodes(client, monkeypatch) -> None:
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

    response = client.post(
        "/api/v1/system-config/llm/node-routes/sync-missing",
        headers=ADMIN_HEADERS,
        json={"activate": True},
    )

    assert response.status_code == 200
    payload = response.json()["data"]
    assert "project_outline_plan" in payload["synced_node_ids"]
    assert "writer_deep_review" in payload["synced_node_ids"]
    assert "scene_auto_rewrite" in payload["synced_node_ids"]
    assert payload["snapshot"]["active"] is True

    overview = client.get("/api/v1/system-config/llm").json()["data"]
    assert overview["missing_active_routes"] == []
    assert overview["node_routes"]["project_outline_plan"]["ready"] is True
    assert overview["node_routes"]["writer_deep_review"]["provider_id"] == "local_qwen"
    assert overview["node_routes"]["scene_auto_rewrite"]["model"] == "Qwen3-14B-Q8_0.gguf"


def test_llm_call_audit_flags_offline_required_nodes(client, session) -> None:
    session.add(
        LlmCall(
            llm_call_id="llm_call_offline_scene_auto_rewrite_test",
            provider="offline_deterministic",
            model="scene-auto-rewrite-policy",
            node_id="scene_auto_rewrite",
            step="scene_auto_rewrite",
            scene_id="SC_AUDIT",
            chapter_id="CH_AUDIT",
            request_payload_summary={},
            response_payload_summary={"source": "offline_deterministic"},
            prompt_tokens=0,
            completion_tokens=0,
            total_tokens=0,
            latency_ms=0,
        )
    )
    session.add(
        LlmCall(
            llm_call_id="llm_call_live_project_outline_test",
            provider="fake",
            model="fake-model",
            node_id="project_outline_plan",
            step="project_outline_plan",
            request_payload_summary={},
            response_payload_summary={"source": "llm"},
            prompt_tokens=1,
            completion_tokens=1,
            total_tokens=2,
            latency_ms=1,
        )
    )
    session.commit()

    response = client.get("/api/v1/system-config/llm/calls/audit")

    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["offline_deterministic_required_count"] == 1
    assert payload["offline_deterministic_required_calls"][0]["node_id"] == "scene_auto_rewrite"
    matrix = {item["node_id"]: item for item in payload["required_node_matrix"]}
    assert matrix["project_outline_plan"]["success_count"] == 1
    assert matrix["scene_auto_rewrite"]["offline_deterministic_count"] == 1


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


def test_system_config_rejects_oauth2_in_model_routing_yaml(client, monkeypatch) -> None:
    monkeypatch.setenv("NOVEL_SYSTEM_ADMIN_TOKEN", "admin-token")
    monkeypatch.setenv("NOVEL_SYSTEM_CONFIG_SECRET", "config-secret")
    models_yaml = """
task_routing:
  neutral_draft:
    provider: gemini
    model: gemini-2.5-pro
    temperature: 0.2
    max_output_tokens: 1000
    response_format: json_object
    credential_mode: oauth2
retry_budget: {}
job_runtime: {}
""".strip()

    response = client.post(
        "/api/v1/system-config/drafts",
        headers=ADMIN_HEADERS,
        json={"category": "models", "yaml_raw": models_yaml},
    )

    assert response.status_code == 422
    payload = response.json()["error"]
    assert payload["code"] == "CONFIG_VALIDATION_FAILED"
    assert "unsupported credential_mode oauth2" in payload["message"]


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
    assert overview_payload["default_provider_id"] == "openai_primary"
    assert overview_payload["providers"]["openai_primary"]["secret"]["configured"] is True
    assert overview_payload["node_routes"]["neutral_draft"]["provider_id"] == "openai_primary"
    assert overview_payload["node_routes"]["neutral_draft"]["ready"] is True
    assert overview_payload["node_routes"]["style_draft"]["model"] == "gpt-5.4"
    assert overview_payload["node_routes"]["style_patch"]["configured"] is False
    assert overview_payload["readiness"]["ready"] is False
    assert "project_outline_plan" in overview_payload["missing_active_routes"]
    assert "style_patch" in overview_payload["missing_active_routes"]
    assert overview_payload["readiness"]["ready_route_count"] >= 2
    assert overview_payload["readiness"]["blocked_route_count"] > 0

    routing_config = load_model_routing_config()
    assert routing_config.node_routing["neutral_draft"].provider_id == "openai_primary"
    assert routing_config.node_routing["neutral_draft"].reasoning_level == "medium"
    assert routing_config.node_routing["style_draft"].reasoning_level == "high"
    assert "style_patch" not in routing_config.node_routing


def test_llm_provider_default_can_be_changed_without_leaking_secret(client, monkeypatch) -> None:
    monkeypatch.setenv("NOVEL_SYSTEM_ADMIN_TOKEN", "admin-token")
    monkeypatch.setenv("NOVEL_SYSTEM_CONFIG_SECRET", "config-secret")

    for provider_id, api_key in (("openai_primary", "sk-primary-secret"), ("openai_backup", "sk-backup-secret")):
        response = client.post(
            "/api/v1/system-config/llm/providers",
            headers=ADMIN_HEADERS,
            json={
                "provider_id": provider_id,
                "provider_type": "openai",
                "account_id": "acct_ops",
                "base_url": "https://api.openai.example/v1",
                "enabled": True,
                "credential_mode": "api_key",
                "api_mode": "responses",
                "models": ["gpt-5.4"],
                "api_key": api_key,
            },
        )
        assert response.status_code == 200

    default_response = client.post(
        "/api/v1/system-config/llm/providers/openai_backup/default",
        headers=ADMIN_HEADERS,
    )

    assert default_response.status_code == 200
    assert "sk-primary-secret" not in default_response.text
    assert "sk-backup-secret" not in default_response.text
    payload = default_response.json()["data"]
    assert payload["default_provider_id"] == "openai_backup"
    assert payload["snapshot"]["active"] is True

    overview = client.get("/api/v1/system-config/llm")
    assert overview.status_code == 200
    assert overview.json()["data"]["default_provider_id"] == "openai_backup"


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


def test_llm_config_rejects_oauth2_credential_mode(client, monkeypatch) -> None:
    monkeypatch.setenv("NOVEL_SYSTEM_ADMIN_TOKEN", "admin-token")
    monkeypatch.setenv("NOVEL_SYSTEM_CONFIG_SECRET", "config-secret")

    response = client.post(
        "/api/v1/system-config/llm/providers",
        headers=ADMIN_HEADERS,
        json={
            "provider_id": "gemini_oauth",
            "provider_type": "gemini",
            "account_id": "acct_google",
            "base_url": "https://generativelanguage.googleapis.com/v1beta",
            "enabled": True,
            "credential_mode": "oauth2",
            "api_mode": "chat",
            "models": ["gemini-2.5-pro"],
        },
    )

    assert response.status_code == 422
    payload = response.json()["error"]
    assert payload["code"] == "CONFIG_PROVIDER_INVALID"
    assert "unsupported credential_mode oauth2" in payload["message"]


def test_llm_config_supports_cliproxy_openai_compatible_relay_with_api_key(client, session, monkeypatch) -> None:
    monkeypatch.setenv("NOVEL_SYSTEM_ADMIN_TOKEN", "admin-token")
    monkeypatch.setenv("NOVEL_SYSTEM_CONFIG_SECRET", "config-secret")

    provider_response = client.post(
        "/api/v1/system-config/llm/providers",
        headers=ADMIN_HEADERS,
        json={
            "provider_id": "cli_proxy",
            "provider_type": "openai_compatible",
            "account_id": "relay",
            "base_url": "http://127.0.0.1:8317/v1/models",
            "enabled": True,
            "credential_mode": "api_key",
            "api_mode": "chat",
            "models": ["gpt-5"],
            "api_key": "cliproxy-secret",
        },
    )

    assert provider_response.status_code == 200
    provider = provider_response.json()["data"]["provider"]
    assert provider["provider_id"] == "cli_proxy"
    assert provider["provider_type"] == "openai_compatible"
    assert provider["base_url"] == "http://127.0.0.1:8317/v1"
    assert provider["credential_mode"] == "api_key"
    assert provider["secret"]["configured"] is True
    assert "cliproxy-secret" not in provider_response.text

    stored_secret = session.execute(
        select(SystemSecret).where(SystemSecret.secret_id == "llm_provider:cli_proxy:api_key")
    ).scalars().one()
    assert stored_secret.secret_type == "api_key"
    assert stored_secret.metadata_json["provider_id"] == "cli_proxy"
    assert "cliproxy-secret" not in stored_secret.encrypted_value

    def fake_models(url: str, *, headers: dict[str, str], timeout: float, trust_env: bool):
        assert url == "http://127.0.0.1:8317/v1/models"
        assert headers == {"Authorization": "Bearer cliproxy-secret"}
        assert timeout == 30.0
        assert trust_env is False
        return httpx.Response(200, json={"data": [{"id": "gpt-5"}]})

    def fake_completion(url: str, *, headers: dict[str, str], json: dict, timeout: float, trust_env: bool):
        assert url == "http://127.0.0.1:8317/v1/chat/completions"
        assert headers == {"Authorization": "Bearer cliproxy-secret"}
        assert timeout == 30.0
        assert trust_env is False
        assert json["model"] == "gpt-5"
        assert json["stream"] is False
        return httpx.Response(200, json={"choices": [{"message": {"content": "pong"}}]})

    monkeypatch.setattr("novel_system.services.system_config.httpx.get", fake_models)
    monkeypatch.setattr("novel_system.services.system_config.httpx.post", fake_completion)

    probe_response = client.post(
        "/api/v1/system-config/llm/providers/cli_proxy/probe",
        headers=ADMIN_HEADERS,
        json={"model": "gpt-5", "check_completion": True},
    )

    assert probe_response.status_code == 200
    probe = probe_response.json()["data"]
    assert probe["ok"] is True
    assert probe["checks"]["connection"]["ok"] is True
    assert probe["checks"]["model"]["ok"] is True
    assert probe["checks"]["completion"]["ok"] is True


def test_llm_provider_probe_bypasses_system_proxy_for_loopback_base_url(client, monkeypatch) -> None:
    monkeypatch.setenv("NOVEL_SYSTEM_ADMIN_TOKEN", "admin-token")

    def fake_models(url: str, *, headers: dict[str, str], timeout: float, trust_env: bool):
        assert url == "http://127.0.0.1:7861/v1/models"
        assert headers == {}
        assert timeout == 10.0
        assert trust_env is False
        return httpx.Response(200, json={"data": [{"id": "relay-model"}]})

    monkeypatch.setattr("novel_system.services.system_config.httpx.get", fake_models)

    response = client.post(
        "/api/v1/system-config/test-provider",
        headers=ADMIN_HEADERS,
        json={
            "provider": "openai_compatible",
            "base_url": "http://127.0.0.1:7861/v1",
            "credential_mode": "none",
            "model": "relay-model",
            "check_completion": False,
        },
    )

    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["ok"] is True
    assert payload["checks"]["connection"]["ok"] is True
    assert payload["checks"]["model"]["ok"] is True


def test_llm_provider_probe_normalizes_proxy_alias_model_ids(client, monkeypatch) -> None:
    monkeypatch.setenv("NOVEL_SYSTEM_ADMIN_TOKEN", "admin-token")

    def fake_models(url: str, *, headers: dict[str, str], timeout: float, trust_env: bool):
        assert url == "http://127.0.0.1:7861/v1/models"
        return httpx.Response(
            200,
            json={
                "data": [
                    {"id": "gemini-2.5-pro"},
                    {"id": "假流式/gemini-2.5-pro"},
                    {"id": "流式抗截断/gemini-2.5-pro"},
                    {"id": "流式抗截断/gemini-2.5-pro-max"},
                ]
            },
        )

    monkeypatch.setattr("novel_system.services.system_config.httpx.get", fake_models)

    response = client.post(
        "/api/v1/system-config/test-provider",
        headers=ADMIN_HEADERS,
        json={
            "provider": "openai_compatible",
            "base_url": "http://127.0.0.1:7861/v1",
            "credential_mode": "none",
            "check_completion": False,
        },
    )

    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["available_models"] == ["gemini-2.5-pro", "gemini-2.5-pro-max"]


def test_llm_config_normalizes_host_only_openai_compatible_base_url_to_v1(client, monkeypatch) -> None:
    monkeypatch.setenv("NOVEL_SYSTEM_ADMIN_TOKEN", "admin-token")
    monkeypatch.setenv("NOVEL_SYSTEM_CONFIG_SECRET", "config-secret")

    provider_response = client.post(
        "/api/v1/system-config/llm/providers",
        headers=ADMIN_HEADERS,
        json={
            "provider_id": "cli_proxy",
            "provider_type": "openai_compatible",
            "account_id": "relay",
            "base_url": "http://127.0.0.1:8317",
            "enabled": True,
            "credential_mode": "api_key",
            "api_mode": "chat",
            "models": ["gemini-3.1-pro-preview"],
            "api_key": "cliproxy-secret",
        },
    )

    assert provider_response.status_code == 200
    assert provider_response.json()["data"]["provider"]["base_url"] == "http://127.0.0.1:8317/v1"

    overview = client.get("/api/v1/system-config/llm")
    assert overview.status_code == 200
    assert overview.json()["data"]["providers"]["cli_proxy"]["base_url"] == "http://127.0.0.1:8317/v1"


def test_llm_provider_probe_uses_active_llm_timeout_seconds(client, monkeypatch) -> None:
    monkeypatch.setenv("NOVEL_SYSTEM_ADMIN_TOKEN", "admin-token")
    monkeypatch.setenv("NOVEL_SYSTEM_CONFIG_SECRET", "config-secret")

    draft_response = client.post(
        "/api/v1/system-config/drafts",
        headers=ADMIN_HEADERS,
        json={
            "category": "api",
            "yaml_raw": """
llm:
  enabled: true
  timeout_seconds: 180
  default_provider_id: local_qwen
  providers:
    local_qwen:
      provider_type: openai_compatible
      account_id: local
      base_url: "https://local-llm.test"
      enabled: true
      credential_mode: none
      api_mode: chat
      models:
        - "qwen3:14b"
""".lstrip(),
        },
    )
    assert draft_response.status_code == 200
    snapshot_id = draft_response.json()["data"]["snapshot"]["snapshot_id"]

    activate_response = client.post(
        f"/api/v1/system-config/{snapshot_id}/activate",
        headers=ADMIN_HEADERS,
    )
    assert activate_response.status_code == 200

    def fake_models(url: str, *, headers: dict[str, str], timeout: float, trust_env: bool):
        assert url == "https://local-llm.test/v1/models"
        assert headers == {}
        assert timeout == 180.0
        assert trust_env is True
        return httpx.Response(200, json={"data": [{"id": "qwen3:14b"}]})

    def fake_completion(url: str, *, headers: dict[str, str], json: dict, timeout: float, trust_env: bool):
        assert url == "https://local-llm.test/v1/chat/completions"
        assert headers == {}
        assert timeout == 180.0
        assert trust_env is True
        assert json["model"] == "qwen3:14b"
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
    assert payload["checks"]["completion"]["ok"] is True


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

    def fake_models(url: str, *, headers: dict[str, str], timeout: float, trust_env: bool):
        assert url == "https://local-llm.test/v1/models"
        assert headers == {}
        assert timeout == 30.0
        assert trust_env is True
        return httpx.Response(200, json={"data": [{"id": "qwen3:14b"}]})

    def fake_completion(url: str, *, headers: dict[str, str], json: dict, timeout: float, trust_env: bool):
        assert url == "https://local-llm.test/v1/chat/completions"
        assert headers == {}
        assert timeout == 30.0
        assert trust_env is True
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
    assert payload["available_models"] == ["qwen3:14b"]
    assert payload["checks"]["connection"]["ok"] is True
    assert payload["checks"]["model"]["ok"] is True
    assert payload["checks"]["completion"]["ok"] is True
    assert payload["checks"]["model"]["requested_model"] == "qwen3:14b"
    assert "qwen3:14b" in payload["message"]


def test_llm_provider_probe_uses_configured_responses_protocol(client, monkeypatch) -> None:
    monkeypatch.setenv("NOVEL_SYSTEM_ADMIN_TOKEN", "admin-token")
    monkeypatch.setenv("NOVEL_SYSTEM_CONFIG_SECRET", "config-secret")

    provider_response = client.post(
        "/api/v1/system-config/llm/providers",
        headers=ADMIN_HEADERS,
        json={
            "provider_id": "gcli2api",
            "provider_type": "openai",
            "account_id": "relay",
            "base_url": "http://127.0.0.1:7861/v1",
            "credential_mode": "api_key",
            "api_key": "relay-key",
            "api_mode": "responses",
            "models": ["gemini-3.1-pro-preview"],
        },
    )
    assert provider_response.status_code == 200, provider_response.text

    def fake_models(url: str, *, headers: dict[str, str], timeout: float, trust_env: bool):
        assert url == "http://127.0.0.1:7861/v1/models"
        return httpx.Response(200, json={"data": [{"id": "gemini-3.1-pro-preview"}]})

    def fake_completion(url: str, *, headers: dict[str, str], json: dict, timeout: float, trust_env: bool):
        assert url == "http://127.0.0.1:7861/v1/responses"
        assert json["model"] == "gemini-3.1-pro-preview"
        assert "input" in json
        return httpx.Response(404, json={"detail": "Not Found"})

    monkeypatch.setattr("novel_system.services.system_config.httpx.get", fake_models)
    monkeypatch.setattr("novel_system.services.system_config.httpx.post", fake_completion)

    probe_response = client.post(
        "/api/v1/system-config/llm/providers/gcli2api/probe",
        headers=ADMIN_HEADERS,
        json={"model": "gemini-3.1-pro-preview", "check_completion": True},
    )

    assert probe_response.status_code == 200
    payload = probe_response.json()["data"]
    assert payload["ok"] is False
    assert payload["checks"]["completion"]["endpoint"] == "/responses"
    assert payload["checks"]["completion"]["api_mode"] == "responses"
    assert payload["checks"]["completion"]["next_action"] == "switch_provider_api_mode_to_chat_or_use_responses_compatible_provider"
    assert "Responses API" in payload["message"]
    assert "chat" in payload["message"]


def test_llm_provider_probe_accepts_completion_when_models_endpoint_is_unavailable(client, monkeypatch) -> None:
    monkeypatch.setenv("NOVEL_SYSTEM_ADMIN_TOKEN", "admin-token")
    monkeypatch.setenv("NOVEL_SYSTEM_CONFIG_SECRET", "config-secret")

    provider_response = client.post(
        "/api/v1/system-config/llm/providers",
        headers=ADMIN_HEADERS,
        json={
            "provider_id": "cli_proxy",
            "provider_type": "openai_compatible",
            "account_id": "relay",
            "base_url": "http://127.0.0.1:8317/v1",
            "enabled": True,
            "credential_mode": "api_key",
            "api_mode": "chat",
            "models": ["gemini-3.1-pro-preview"],
            "api_key": "cliproxy-secret",
        },
    )
    assert provider_response.status_code == 200

    def fake_models(url: str, *, headers: dict[str, str], timeout: float, trust_env: bool):
        assert url == "http://127.0.0.1:8317/v1/models"
        assert headers == {"Authorization": "Bearer cliproxy-secret"}
        assert timeout == 30.0
        assert trust_env is False
        return httpx.Response(404, text="404 page not found")

    def fake_completion(url: str, *, headers: dict[str, str], json: dict, timeout: float, trust_env: bool):
        assert url == "http://127.0.0.1:8317/v1/chat/completions"
        assert headers == {"Authorization": "Bearer cliproxy-secret"}
        assert timeout == 30.0
        assert trust_env is False
        assert json["model"] == "gemini-3.1-pro-preview"
        assert json["stream"] is False
        return httpx.Response(200, json={"choices": [{"message": {"content": "pong"}}]})

    monkeypatch.setattr("novel_system.services.system_config.httpx.get", fake_models)
    monkeypatch.setattr("novel_system.services.system_config.httpx.post", fake_completion)

    probe_response = client.post(
        "/api/v1/system-config/llm/providers/cli_proxy/probe",
        headers=ADMIN_HEADERS,
        json={"model": "gemini-3.1-pro-preview", "check_completion": True},
    )

    assert probe_response.status_code == 200
    probe = probe_response.json()["data"]
    assert probe["ok"] is True
    assert probe["checks"]["connection"]["ok"] is False
    assert probe["checks"]["completion"]["ok"] is True
    assert probe["checks"]["completion"]["model"] == "gemini-3.1-pro-preview"
    assert "gemini-3.1-pro-preview" in probe["message"]


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

    def fake_models(url: str, *, headers: dict[str, str], timeout: float, trust_env: bool):
        assert trust_env is True
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
    assert payload["available_models"] == ["qwen3:14b", "llama3.1:8b"]
    assert payload["checks"]["connection"]["ok"] is True
    assert payload["checks"]["model"]["ok"] is False
    assert payload["checks"]["model"]["requested_model"] == "Qwen3 14B"
    assert payload["checks"]["model"]["available_models"] == ["qwen3:14b", "llama3.1:8b"]
    assert "Qwen3 14B" in payload["message"]
    assert "qwen3:14b" in payload["message"]


def test_llm_oauth_routes_are_removed(client, monkeypatch) -> None:
    monkeypatch.setenv("NOVEL_SYSTEM_ADMIN_TOKEN", "admin-token")
    monkeypatch.setenv("NOVEL_SYSTEM_CONFIG_SECRET", "config-secret")

    start_response = client.post(
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
    callback_response = client.get(
        "/api/v1/system-config/llm/oauth/callback",
        params={"state": "legacy-state", "code": "auth-code"},
    )

    assert start_response.status_code == 404
    assert callback_response.status_code == 404


def test_llm_overview_marks_route_not_ready_when_secret_cannot_be_decrypted(
    client, session, monkeypatch
) -> None:
    """BUG-001 回归: config.secret 轮换后旧密文 InvalidToken,运行期 LLM 调用 100%
    失败"未提供令牌",但就绪侧若只看"secret 是否存在"会报假阳性(ready=true)。

    修复要求:secret 存在但无法用当前 config.secret 解密时,provider 不就绪、route
    ready=false、active_provider_count=0,且 readiness_reason 能与"未配置密钥"区分。
    """
    import base64
    import hashlib

    from cryptography.fernet import Fernet

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
            "models": ["gpt-5.4"],
            "api_key": "sk-secret-openai",
        },
    )
    assert provider_response.status_code == 200

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
            },
            "retry_budget": {"total_attempt_budget": 4},
            "job_runtime": {},
        },
    )
    assert route_response.status_code == 200

    # --- 健康基线(可解密 secret 不得被判死)---
    healthy = client.get("/api/v1/system-config/llm").json()["data"]
    healthy_secret = healthy["providers"]["openai_primary"]["secret"]
    assert healthy_secret["configured"] is True
    assert healthy["node_routes"]["neutral_draft"]["ready"] is True
    assert healthy["readiness"]["active_provider_count"] == 1

    # --- 模拟 config.secret 轮换: 把旧密文换成"用不同密钥加密的合法 Fernet token",
    #     当前 config-secret 解不出 → InvalidToken(等价线上 .codex-run/config.secret 被重生)---
    rotated_key = base64.urlsafe_b64encode(hashlib.sha256(b"rotated-different-secret").digest())
    undecryptable = Fernet(rotated_key).encrypt(b"sk-secret-openai").decode("utf-8")
    stored_secret = session.execute(
        select(SystemSecret).where(SystemSecret.secret_id == "llm_provider:openai_primary:api_key")
    ).scalars().one()
    stored_secret.encrypted_value = undecryptable
    session.add(stored_secret)
    session.commit()

    overview = client.get("/api/v1/system-config/llm")
    assert overview.status_code == 200
    payload = overview.json()["data"]
    route = payload["node_routes"]["neutral_draft"]
    secret_status = payload["providers"]["openai_primary"]["secret"]

    # 核心:解密失败时就绪侧不得报假阳性(修前此行红:ready 仍为 True)
    assert route["ready"] is False
    # secret"仍存在"但"不可解密"——三态不再被压成两态
    assert secret_status["configured"] is True
    assert secret_status["decryptable"] is False
    # 与"未配置密钥(secret_missing)"可区分
    assert route["readiness_reason"] == "secret_decrypt_failed"
    assert payload["readiness"]["active_provider_count"] == 0
    assert payload["readiness"]["ready"] is False

    # 回归:健康基线快照里 decryptable 为 True(正常路径未被误判)
    assert healthy_secret["decryptable"] is True
