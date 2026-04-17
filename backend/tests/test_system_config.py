from __future__ import annotations

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
