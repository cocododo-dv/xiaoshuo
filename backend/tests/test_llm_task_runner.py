from __future__ import annotations

import json

import pytest
from sqlalchemy import select

from novel_system.db.models import LlmCall
from novel_system.services.llm_client import (
    LLMHTTPError,
    LLMRequest,
    LLMResponse,
    ModelRoutingConfig,
    TaskModelConfig,
)
from novel_system.services.llm_task_runner import LLMNodeContinuityError, LLMNodeExecutionError, LLMNodeRunner
from novel_system.settings import Settings


def _prompt(target_input_tokens: int = 400) -> dict:
    return {
        "template_name": "neutral_draft",
        "template_version": "test",
        "system_prompt": "system prompt",
        "user_prompt": "Scene ID: CH100_SC01\nReturn JSON.",
        "structured_schema": {"type": "object"},
        "prompt_hash": "prompt_hash_test",
        "token_budget": {
            "target_input_tokens": target_input_tokens,
            "estimated_input_tokens": 0,
            "remaining_input_tokens": target_input_tokens,
            "included_sections": [],
            "compressed_sections": [],
            "omitted_sections": [],
            "section_status": {},
            "continuity_policy": [],
            "split_scene_recommended": False,
            "stop_reason": None,
            "continuity_warning": None,
        },
    }


def _routing_config() -> ModelRoutingConfig:
    task_config = TaskModelConfig(
        provider="openai_compatible",
        model="fake-model",
        temperature=0.2,
        max_output_tokens=120,
        response_format="json_object",
        provider_id="provider_primary",
        account_id="account_a",
        reasoning_level="medium",
        api_mode="responses",
        credential_mode="api_key",
    )
    return ModelRoutingConfig(
        node_routing={"neutral_draft": task_config},
        task_routing={"neutral_draft": task_config},
        retry_budget={},
        job_runtime={},
    )


def _live_settings() -> Settings:
    return Settings(
        database_url="sqlite:///test.db",
        vector_backend="memory",
        vector_store_dir=__import__("pathlib").Path(".vector_store_test"),
        llm_provider="openai_compatible",
        llm_base_url="http://127.0.0.1:8080/v1",
        llm_api_key=None,
        llm_timeout_seconds=30.0,
        llm_enabled=True,
    )


class RecordingClient:
    def __init__(self) -> None:
        self.requests: list[LLMRequest] = []

    def generate(self, request: LLMRequest) -> LLMResponse:
        self.requests.append(request)
        payload = {"scene_text": "generated scene"}
        return LLMResponse(
            request_id="resp_success",
            provider="fake-provider",
            model="fake-model",
            text=json.dumps(payload),
            structured_output=payload,
            response_format="json_object",
            raw_response={"id": "resp_success", "model": "fake-model"},
            usage={"input_tokens": 11, "output_tokens": 7, "total_tokens": 18},
            finish_reason="stop",
            attempt_count=2,
            max_retries=3,
            retryable=False,
        )


class FailingClient:
    def generate(self, request: LLMRequest) -> LLMResponse:
        raise LLMHTTPError(
            "LLM_HTTP_REQUEST_FAILED",
            "provider connection failed",
            retryable=True,
            details={"attempt_count": 3, "max_retries": 2},
        )


def test_llm_node_runner_builds_request_and_persists_successful_call(session) -> None:
    client = RecordingClient()
    runner = LLMNodeRunner(session, llm_client=client, routing_config=_routing_config())

    result = runner.run(
        scene_id="CH100_SC01",
        chapter_id="CH100",
        bundle_id="bundle_CH100_SC01",
        bundle_hash="bundle_hash_CH100_SC01",
        node_id="neutral_draft",
        step="neutral_draft",
        prompt=_prompt(),
        user_prompt="Scene ID: CH100_SC01\nReturn JSON.",
        offline_client_factory=lambda: client,
    )
    session.commit()

    stored_call = session.execute(select(LlmCall)).scalars().one()

    assert result.llm_call_id == stored_call.llm_call_id
    assert client.requests[0].node_id == "neutral_draft"
    assert client.requests[0].provider_id == "provider_primary"
    assert stored_call.error_code is None
    assert stored_call.request_payload_summary["template_name"] == "neutral_draft"
    assert stored_call.request_payload_summary["token_budget"]["estimated_input_tokens"] > 0
    assert stored_call.request_payload_summary["bundle_id"] == "bundle_CH100_SC01"
    assert stored_call.response_payload_summary["request_id"] == "resp_success"
    assert stored_call.response_payload_summary["attempt_count"] == 2
    assert stored_call.response_payload_summary["max_retries"] == 3
    assert stored_call.response_payload_summary["retryable"] is False


def test_llm_node_runner_falls_back_for_scene_blueprint_when_active_config_is_older(session) -> None:
    client = RecordingClient()
    runner = LLMNodeRunner(session, llm_client=client, routing_config=_routing_config())

    result = runner.run(
        scene_id="CH100_SC01",
        chapter_id="CH100",
        bundle_id="scene_blueprint_source_CH100_SC01",
        bundle_hash="bundle_hash_CH100_SC01",
        node_id="scene_blueprint",
        step="scene_blueprint",
        prompt={**_prompt(), "template_name": "scene_blueprint"},
        user_prompt="Scene ID: CH100_SC01\nReturn a scene blueprint JSON object.",
        offline_client_factory=lambda: client,
    )
    session.commit()

    stored_call = session.execute(select(LlmCall)).scalars().one()

    assert result.llm_call_id == stored_call.llm_call_id
    assert client.requests[0].node_id == "scene_blueprint"
    assert client.requests[0].provider_id == "provider_primary"
    assert stored_call.node_id == "scene_blueprint"
    assert stored_call.request_payload_summary["provider_id"] == "provider_primary"


def test_llm_node_runner_live_mode_blocks_missing_direct_node_route(session) -> None:
    client = RecordingClient()
    runner = LLMNodeRunner(
        session,
        llm_client=client,
        routing_config=_routing_config(),
        settings=_live_settings(),
    )

    with pytest.raises(LLMNodeExecutionError) as exc_info:
        runner.run(
            scene_id="CH100_SC01",
            chapter_id="CH100",
            bundle_id="scene_blueprint_source_CH100_SC01",
            bundle_hash="bundle_hash_CH100_SC01",
            node_id="scene_blueprint",
            step="scene_blueprint",
            prompt={**_prompt(), "template_name": "scene_blueprint"},
            user_prompt="Scene ID: CH100_SC01\nReturn a scene blueprint JSON object.",
            offline_client_factory=lambda: client,
        )

    assert client.requests == []
    assert exc_info.value.error_code == "LLM_ROUTE_NOT_CONFIGURED"
    assert "scene_blueprint" in exc_info.value.message


def test_llm_node_runner_live_mode_does_not_inherit_legacy_stylize_route(session) -> None:
    client = RecordingClient()
    stylize_config = TaskModelConfig(
        provider="openai_compatible",
        model="fake-style-model",
        temperature=0.7,
        max_output_tokens=120,
        response_format="json_object",
        provider_id="provider_primary",
        reasoning_level="medium",
        api_mode="responses",
    )
    runner = LLMNodeRunner(
        session,
        llm_client=client,
        routing_config=ModelRoutingConfig(
            node_routing={},
            task_routing={"stylize": stylize_config},
            retry_budget={},
            job_runtime={},
        ),
        settings=_live_settings(),
    )

    with pytest.raises(LLMNodeExecutionError) as exc_info:
        runner.run(
            scene_id="CH100_SC01",
            chapter_id="CH100",
            bundle_id="bundle_CH100_SC01",
            bundle_hash="bundle_hash_CH100_SC01",
            node_id="style_draft",
            step="style_draft",
            prompt={**_prompt(), "template_name": "style_draft"},
            user_prompt="Scene ID: CH100_SC01\nReturn a stylized scene JSON object.",
            offline_client_factory=lambda: client,
        )

    assert client.requests == []
    assert exc_info.value.error_code == "LLM_ROUTE_NOT_CONFIGURED"
    assert "style_draft" in exc_info.value.message


def test_llm_node_runner_falls_back_for_scene_literary_rewrite_when_active_config_is_older(session) -> None:
    client = RecordingClient()
    runner = LLMNodeRunner(session, llm_client=client, routing_config=_routing_config())

    result = runner.run(
        scene_id="CH100_SC01",
        chapter_id="CH100",
        bundle_id="rewrite_source_CH100_SC01",
        bundle_hash="bundle_hash_CH100_SC01",
        node_id="scene_literary_rewrite",
        step="scene_literary_rewrite",
        prompt={**_prompt(), "template_name": "scene_literary_rewrite"},
        user_prompt="Scene ID: CH100_SC01\nReturn a rewritten scene JSON object.",
        offline_client_factory=lambda: client,
    )
    session.commit()

    stored_call = session.execute(select(LlmCall)).scalars().one()

    assert result.llm_call_id == stored_call.llm_call_id
    assert client.requests[0].node_id == "scene_literary_rewrite"
    assert client.requests[0].provider_id == "provider_primary"
    assert stored_call.node_id == "scene_literary_rewrite"
    assert stored_call.request_payload_summary["provider_id"] == "provider_primary"


def test_llm_node_runner_persists_failed_provider_call_with_retry_metadata(session) -> None:
    runner = LLMNodeRunner(session, llm_client=FailingClient(), routing_config=_routing_config())

    with pytest.raises(LLMNodeExecutionError) as exc_info:
        runner.run(
            scene_id="CH100_SC01",
            chapter_id="CH100",
            bundle_id="bundle_CH100_SC01",
            bundle_hash="bundle_hash_CH100_SC01",
            node_id="neutral_draft",
            step="neutral_draft",
            prompt=_prompt(),
            user_prompt="Scene ID: CH100_SC01\nReturn JSON.",
            offline_client_factory=lambda: FailingClient(),
        )
    session.commit()

    stored_call = session.execute(select(LlmCall)).scalars().one()

    assert exc_info.value.llm_call_id == stored_call.llm_call_id
    assert exc_info.value.error_code == "LLM_HTTP_REQUEST_FAILED"
    assert exc_info.value.retryable is True
    assert stored_call.error_code == "LLM_HTTP_REQUEST_FAILED"
    assert stored_call.response_payload_summary["retryable"] is True
    assert stored_call.response_payload_summary["attempt_count"] == 3
    assert stored_call.response_payload_summary["max_retries"] == 2
    assert stored_call.response_payload_summary["details"]["attempt_count"] == 3
    assert stored_call.response_payload_summary["details"]["max_retries"] == 2


def test_llm_node_runner_persists_continuity_failure_before_provider_call(session) -> None:
    client = RecordingClient()
    runner = LLMNodeRunner(session, llm_client=client, routing_config=_routing_config())

    with pytest.raises(LLMNodeContinuityError) as exc_info:
        runner.run(
            scene_id="CH100_SC01",
            chapter_id="CH100",
            bundle_id="bundle_CH100_SC01",
            bundle_hash="bundle_hash_CH100_SC01",
            node_id="neutral_draft",
            step="neutral_draft",
            prompt=_prompt(target_input_tokens=20),
            user_prompt=" ".join(["oversized prompt"] * 100),
            offline_client_factory=lambda: client,
        )
    session.commit()

    stored_call = session.execute(select(LlmCall)).scalars().one()

    assert client.requests == []
    assert exc_info.value.llm_call_id == stored_call.llm_call_id
    assert exc_info.value.continuity_warning["requires_scene_split"] is True
    assert stored_call.error_code == "CONTINUITY_BUDGET_EXCEEDED"
    assert stored_call.request_payload_summary["continuity_warning"]["requires_scene_split"] is True
    assert stored_call.response_payload_summary["attempt_count"] == 0
    assert stored_call.response_payload_summary["max_retries"] == 0
    assert stored_call.response_payload_summary["retryable"] is False
    assert stored_call.response_payload_summary["continuity_warning"]["requires_scene_split"] is True
