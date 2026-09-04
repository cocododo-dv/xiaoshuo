"""回归：两处本应是领域错误、却被序列化/未包装成 500 的失败路径。

1. interop bundle-worksheet 预览/导入：pydantic ``model_validator`` 抛出的 ``ValueError``
   会留在 ``exc.errors()`` 的 ``ctx`` 里，直接塞进 ``DomainError.details`` 后信封无法
   ``json.dumps``，最终变成 500 INTERNAL_ERROR 而不是 400 BUNDLE_SNAPSHOT_SCHEMA_INVALID。
2. literary-eval live 运行：模型返回的 JSON 缺 ``scene_text`` 时抛裸 ``ValueError``，
   经路由变成 500，作者看不到是哪个字段缺失、也拿不到 llm_call_id。
"""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from novel_system.db.models import LlmCall
from novel_system.services.errors import DomainError
from novel_system.services.literary_eval import LLMLiteraryCaseGenerator, load_literary_eval_suite
from novel_system.services.llm_client import LLMResponse, ModelRoutingConfig, ProviderRuntimeConfig, TaskModelConfig
from tests.accounted_llm_fakes import AccountedGenerateMixin


def _mismatched_worksheet_yaml() -> str:
    # envelope.scene_id 与 snapshot.scene_id 故意不一致，触发 contracts/bundle.py 的
    # validate_snapshot_identity model_validator（抛 ValueError，而非字段级错误）。
    payload = {
        "bundle_id": "bundle_fix_mismatch",
        "scene_id": "CH001_SC01",
        "chapter_id": "CH001",
        "hash_contract_version": "BSHASH_v1",
        "hash_alg": "sha256",
        "execution_mode": "P1_scripted",
        "created_by_action": "bundle_worksheet_import",
        "snapshot": {
            "contract_version": "BSHASH_v1",
            "stage_allowlist_name": "bundle_build_allowlist_v1",
            "scene_id": "CH001_SC02",
            "chapter_id": "CH001",
            "source_version_refs": {"chapter_goal": "CH001", "scene_card": "CH001_SC02"},
            "resolved_ref_ids": {"relation_ids": [], "world_rule_ids": [], "open_foreshadow_ids": []},
            "ordered_injections": [
                {"slot": "chapter_goal", "ref_id": "CH001", "digest_key": "chapter_goal"},
            ],
            "inline_digests": {"chapter_goal": "close the chapter"},
        },
    }
    return yaml.safe_dump(payload, sort_keys=False, allow_unicode=True)


def _assert_schema_invalid_envelope(response) -> None:
    assert response.status_code == 400, response.text
    body = response.json()
    assert body["ok"] is False
    assert body["error"]["code"] == "BUNDLE_SNAPSHOT_SCHEMA_INVALID"
    errors = body["error"]["details"]["errors"]
    assert isinstance(errors, list) and errors
    first = errors[0]
    assert "snapshot.scene_id must match envelope.scene_id" in first["msg"]
    assert first["type"] == "value_error"
    assert isinstance(first["loc"], list)
    # 不得回显不可序列化的 ctx / 整份 worksheet input。
    assert "ctx" not in first
    assert "input" not in first
    assert "url" not in first


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/interop/preview/bundle-worksheet",
        "/api/v1/interop/import/bundle-worksheet",
    ],
)
def test_interop_worksheet_model_validator_failure_is_400_domain_error(client: TestClient, path: str) -> None:
    # import 路由要求幂等键(缺了会先 400 IDEMPOTENCY_KEY_REQUIRED,到不了 worksheet 解析);
    # preview 忽略该头,两条路径统一带上即可。
    response = client.post(
        path,
        json={"worksheet_yaml": _mismatched_worksheet_yaml()},
        headers={"X-Idempotency-Key": f"fix-interop-schema-{uuid.uuid4().hex}"},
    )
    _assert_schema_invalid_envelope(response)


def _one_case_suite():
    return load_literary_eval_suite(
        {
            "suite_id": "fix_missing_scene_text",
            "cases": [
                {
                    "case_id": "case_one",
                    "title": "Case one",
                    "prompt": "Write one scene.",
                }
            ],
        }
    )


class _NoSceneTextClient(AccountedGenerateMixin):
    def __init__(self, *_args, **_kwargs) -> None:
        pass

    def generate(self, request):
        # 合法 JSON 对象，但字段名错了：模型把正文放在 text 而不是 scene_text。
        return LLMResponse(
            request_id="provider-no-scene-text",
            provider="fake-provider",
            model=request.model,
            text='{"text": "a scene without the contract field"}',
            structured_output={"text": "a scene without the contract field"},
            response_format=request.response_format,
            raw_response={},
            usage={"input_tokens": 2, "output_tokens": 1, "total_tokens": 3},
            raw_usage={"input_tokens": 2, "output_tokens": 1, "total_tokens": 3},
            usage_present=True,
            usage_complete=True,
        )


def test_llm_literary_case_generator_missing_scene_text_raises_domain_error(session) -> None:
    case = _one_case_suite().cases[0]
    generator = LLMLiteraryCaseGenerator(
        _NoSceneTextClient(),
        session=session,
        eval_run_id="literary_eval_fix_schema",
        model="fake-model",
    )

    with pytest.raises(DomainError) as excinfo:
        generator(case)

    exc = excinfo.value
    assert exc.code == "LITERARY_EVAL_LLM_RESPONSE_INVALID_SCHEMA"
    assert exc.status_code == 409
    assert exc.details["missing_field"] == "scene_text"
    assert exc.details["case_id"] == "case_one"
    assert exc.details["error_code"] == "LLM_RESPONSE_INVALID_SCHEMA"
    assert exc.details["llm_call_id"]
    # 老调用方/测试按 ValueError 捕获，契约需保留。
    assert isinstance(exc, ValueError)
    assert "missing scene_text" in str(exc)

    call = session.get(LlmCall, exc.details["llm_call_id"])
    assert call is not None
    assert call.accounting_status == "failed"
    assert call.error_code == "LLM_RESPONSE_INVALID_SCHEMA"


def test_literary_eval_run_api_missing_scene_text_returns_domain_error(
    client: TestClient,
    session,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    report_path = tmp_path / "latest.json"
    monkeypatch.setenv("NOVEL_SYSTEM_LITERARY_EVAL_REPORT_PATH", str(report_path))
    monkeypatch.setenv("NOVEL_SYSTEM_LLM_ENABLED", "true")
    monkeypatch.setenv("NOVEL_SYSTEM_LLM_PROVIDER", "openai_compatible")
    monkeypatch.setenv("NOVEL_SYSTEM_LLM_BASE_URL", "http://127.0.0.1:8080/v1")
    monkeypatch.delenv("NOVEL_SYSTEM_LLM_API_KEY", raising=False)

    from novel_system.api.routes import literary_eval as route_module

    task_config = TaskModelConfig(
        provider="openai_compatible",
        provider_id="local_fake",
        model="fake-model",
        temperature=0.2,
        max_output_tokens=200,
        response_format="json_object",
        api_mode="chat",
        credential_mode="none",
    )
    monkeypatch.setattr(
        route_module,
        "load_model_routing_config",
        lambda: ModelRoutingConfig(
            node_routing={"literary_eval_live": task_config},
            task_routing={},
            retry_budget={},
            job_runtime={},
        ),
    )
    monkeypatch.setattr(
        route_module,
        "load_llm_provider_runtime_configs",
        lambda: {
            "local_fake": ProviderRuntimeConfig(
                provider_id="local_fake",
                provider_type="openai_compatible",
                base_url="http://127.0.0.1:8080/v1",
                credential_mode="none",
                enabled=True,
                models=("fake-model",),
            )
        },
    )
    monkeypatch.setattr(route_module, "LLMClient", _NoSceneTextClient)

    response = client.post("/api/v1/literary-eval/run", json={"mode": "live"})

    assert response.status_code == 409, response.text
    body = response.json()
    assert body["ok"] is False
    assert body["error"]["code"] == "LITERARY_EVAL_LLM_RESPONSE_INVALID_SCHEMA"
    details = body["error"]["details"]
    assert details["missing_field"] == "scene_text"
    assert details["node_id"] == "literary_eval_live"
    assert details["llm_call_id"].startswith("llm_eval_")
    # 失败的调用仍然被记账，且不会写出半成品报告。
    call = session.get(LlmCall, details["llm_call_id"])
    assert call is not None
    assert call.accounting_status == "failed"
    assert not report_path.exists()
