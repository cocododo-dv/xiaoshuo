from __future__ import annotations

import json

import pytest
from sqlalchemy import select

from novel_system.db.models import (
    ChapterGoal,
    LlmCall,
    LlmCallAttempt,
    SceneCard,
    SceneRunState,
    StoryProject,
)
from novel_system.db.session import SessionLocal
from novel_system.services.llm_client import (
    LLMHTTPError,
    LLMRequest,
    LLMResponse,
    ModelRoutingConfig,
    OnlineAccountedExecution,
    TaskModelConfig,
)
from novel_system.services.errors import DomainError
from novel_system.services.llm_task_runner import (
    LLMNodeContinuityError,
    LLMNodeExecutionError,
    LLMNodeRunner,
    begin_llm_execution,
    end_llm_execution,
)
from novel_system.services.scene_run_checkpoint import SceneRunCheckpointService
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


def _offline_settings() -> Settings:
    return Settings(
        database_url="sqlite:///test.db",
        vector_backend="memory",
        vector_store_dir=__import__("pathlib").Path(".vector_store_test"),
        llm_provider="openai_compatible",
        llm_base_url="http://127.0.0.1:8080/v1",
        llm_api_key=None,
        llm_timeout_seconds=30.0,
        llm_enabled=False,
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


class _SimulatedProcessCrash(BaseException):
    pass


class _AccountedRecordingClient(OnlineAccountedExecution):
    def __init__(self) -> None:
        self.post_count = 0

    def generate_accounted(self, request: LLMRequest, *, accounting_hook) -> LLMResponse:  # noqa: ANN001
        handle = accounting_hook.before_dispatch(request=request, dispatch_kind="initial")
        self.post_count += 1
        payload = {"scene_text": f"accounted scene {self.post_count}"}
        response = LLMResponse(
            request_id=f"accounted-{self.post_count}",
            provider="fake-provider",
            model="fake-model",
            text=json.dumps(payload),
            structured_output=payload,
            response_format="json_object",
            raw_response={"id": f"accounted-{self.post_count}", "model": "fake-model"},
            usage={"input_tokens": 11, "output_tokens": 7, "total_tokens": 18},
            raw_usage={"input_tokens": 11, "output_tokens": 7, "total_tokens": 18},
            usage_present=True,
            usage_complete=True,
            finish_reason="stop",
        )
        accounting_hook.after_response(
            handle,
            request=request,
            response=response,
            latency_ms=1,
        )
        return response


class _UnsupportedDurableOnlineClient:
    def __init__(self) -> None:
        self.provider_io_count = 0

    def generate(self, _request: LLMRequest) -> LLMResponse:
        self.provider_io_count += 1
        raise AssertionError("unsupported client must be rejected before provider I/O")


def _seed_durable_runner_scene(session) -> None:
    session.add(StoryProject(project_id="PROJECT_RUNNER", title="runner", outline_text="outline"))
    session.add(
        ChapterGoal(
            chapter_id="CH_RUNNER",
            project_id="PROJECT_RUNNER",
            planned_scene_count=1,
            chapter_goal="durable accounting",
        )
    )
    session.add(
        SceneCard(
            scene_id="CH_RUNNER_SC01",
            chapter_id="CH_RUNNER",
            project_id="PROJECT_RUNNER",
            scene_seq=1,
            scene_goal="survive a process crash",
            beats_json=["reserve", "dispatch", "settle"],
        )
    )
    session.add(
        SceneRunState(
            scene_id="CH_RUNNER_SC01",
            scene_status="ready",
            active_execution_id="exec-runner",
            run_execution_status="active",
            scene_token_budget=10_000,
            provider_attempt_budget=5,
        )
    )
    session.commit()


def _run_durable_runner(session, client, *, execution_id: str = "exec-runner"):
    token = begin_llm_execution(execution_id)
    try:
        return LLMNodeRunner(
            session,
            llm_client=client,
            routing_config=_routing_config(),
            settings=_live_settings(),
        ).run(
            scene_id="CH_RUNNER_SC01",
            chapter_id="CH_RUNNER",
            bundle_id="bundle-runner",
            bundle_hash="sha256:runner",
            node_id="neutral_draft",
            step="neutral_draft",
            prompt=_prompt(),
            user_prompt="Scene ID: CH_RUNNER_SC01\nReturn JSON.",
            offline_client_factory=lambda: client,
            execution_step_key="neutral_draft",
        )
    finally:
        end_llm_execution(token)


def test_durable_runner_recovers_crash_after_reservation_and_retries_once(session) -> None:
    _seed_durable_runner_scene(session)
    client = _AccountedRecordingClient()
    runner = LLMNodeRunner(
        session,
        llm_client=client,
        routing_config=_routing_config(),
        settings=_live_settings(),
    )

    def crash_after_reservation(stage: str, _attempt_id: str) -> None:
        if stage == "reservation_committed":
            raise _SimulatedProcessCrash()

    runner._accounting_lifecycle_observer = crash_after_reservation
    token = begin_llm_execution("exec-runner")
    try:
        with pytest.raises(_SimulatedProcessCrash):
            runner.run(
                scene_id="CH_RUNNER_SC01",
                chapter_id="CH_RUNNER",
                bundle_id="bundle-runner",
                bundle_hash="sha256:runner",
                node_id="neutral_draft",
                step="neutral_draft",
                prompt=_prompt(),
                user_prompt="Scene ID: CH_RUNNER_SC01\nReturn JSON.",
                offline_client_factory=lambda: client,
                execution_step_key="neutral_draft",
            )
    finally:
        end_llm_execution(token)

    recovery = SessionLocal()
    try:
        parent = recovery.execute(select(LlmCall)).scalar_one()
        attempt = recovery.execute(select(LlmCallAttempt)).scalar_one()
        state = recovery.get(SceneRunState, "CH_RUNNER_SC01")
        assert client.post_count == 0
        assert parent.accounting_status == "reserved"
        assert attempt.accounting_status == "reserved"
        assert attempt.request_dispatched_at is None
        assert state.scene_tokens_reserved == attempt.reserved_tokens > 0

        outcome = SceneRunCheckpointService(recovery).reconcile_step_output(
            scene_id="CH_RUNNER_SC01",
            execution_id="exec-runner",
            execution_step_key="neutral_draft",
            output_exists=False,
        )
        recovery.expire_all()
        parent = recovery.get(LlmCall, parent.llm_call_id)
        attempt = recovery.get(LlmCallAttempt, attempt.attempt_id)
        state = recovery.get(SceneRunState, "CH_RUNNER_SC01")
        assert outcome == "retry"
        assert parent.accounting_status == "released"
        assert attempt.accounting_status == "released"
        assert state.scene_tokens_reserved == 0
        assert state.provider_attempts_used == 0
        assert state.scene_tokens_used == 0
    finally:
        recovery.close()

    retry_session = SessionLocal()
    try:
        result = _run_durable_runner(retry_session, client)
        assert result.response.structured_output == {"scene_text": "accounted scene 1"}
        assert client.post_count == 1
    finally:
        retry_session.close()


def test_durable_runner_recovers_dispatch_crash_and_blocks_resend(session) -> None:
    _seed_durable_runner_scene(session)
    client = _AccountedRecordingClient()
    runner = LLMNodeRunner(
        session,
        llm_client=client,
        routing_config=_routing_config(),
        settings=_live_settings(),
    )

    def crash_after_dispatch(stage: str, _attempt_id: str) -> None:
        if stage == "dispatch_committed":
            raise _SimulatedProcessCrash()

    runner._accounting_lifecycle_observer = crash_after_dispatch
    token = begin_llm_execution("exec-runner")
    try:
        with pytest.raises(_SimulatedProcessCrash):
            runner.run(
                scene_id="CH_RUNNER_SC01",
                chapter_id="CH_RUNNER",
                bundle_id="bundle-runner",
                bundle_hash="sha256:runner",
                node_id="neutral_draft",
                step="neutral_draft",
                prompt=_prompt(),
                user_prompt="Scene ID: CH_RUNNER_SC01\nReturn JSON.",
                offline_client_factory=lambda: client,
                execution_step_key="neutral_draft",
            )
    finally:
        end_llm_execution(token)

    recovery = SessionLocal()
    try:
        parent = recovery.execute(select(LlmCall)).scalar_one()
        attempt = recovery.execute(select(LlmCallAttempt)).scalar_one()
        state = recovery.get(SceneRunState, "CH_RUNNER_SC01")
        assert parent.accounting_status == "reserved"
        assert attempt.request_dispatched_at is not None
        assert state.scene_tokens_reserved == attempt.reserved_tokens > 0
        assert state.provider_attempts_used == 1

        with pytest.raises(DomainError) as missing:
            SceneRunCheckpointService(recovery).reconcile_step_output(
                scene_id="CH_RUNNER_SC01",
                execution_id="exec-runner",
                execution_step_key="neutral_draft",
                output_exists=False,
            )
        assert missing.value.code == "RUN_CHECKPOINT_OUTPUT_MISSING"
        recovery.expire_all()
        parent = recovery.get(LlmCall, parent.llm_call_id)
        attempt = recovery.get(LlmCallAttempt, attempt.attempt_id)
        state = recovery.get(SceneRunState, "CH_RUNNER_SC01")
        assert parent.accounting_status == "failed"
        assert parent.error_code == "RUN_CHECKPOINT_OUTPUT_MISSING"
        assert attempt.accounting_status == "failed"
        assert state.scene_tokens_reserved == 0
        assert state.provider_attempts_used == 1
        assert state.scene_tokens_used == attempt.estimated_tokens > 0
    finally:
        recovery.close()

    posts_before_retry = client.post_count
    retry_session = SessionLocal()
    try:
        with pytest.raises(LLMNodeExecutionError) as blocked:
            _run_durable_runner(retry_session, client)
        assert blocked.value.error_code == "RUN_CHECKPOINT_OUTPUT_MISSING"
        assert blocked.value.llm_call_id == parent.llm_call_id
        assert client.post_count == posts_before_retry
    finally:
        retry_session.close()


def test_durable_runner_settled_parent_blocks_resend_before_output_checkpoint(session) -> None:
    _seed_durable_runner_scene(session)
    client = _AccountedRecordingClient()
    with pytest.raises(_SimulatedProcessCrash):
        result = _run_durable_runner(session, client)
        assert result.response.structured_output == {"scene_text": "accounted scene 1"}
        raise _SimulatedProcessCrash()

    recovery = SessionLocal()
    try:
        parent = recovery.execute(select(LlmCall)).scalar_one()
        attempt = recovery.execute(select(LlmCallAttempt)).scalar_one()
        state = recovery.get(SceneRunState, "CH_RUNNER_SC01")
        assert parent.accounting_status == "settled"
        assert attempt.accounting_status == "settled"
        assert state.scene_tokens_reserved == 0
        assert state.provider_attempts_used == 1
        assert state.scene_tokens_used == 18
        with pytest.raises(DomainError) as missing:
            SceneRunCheckpointService(recovery).reconcile_step_output(
                scene_id="CH_RUNNER_SC01",
                execution_id="exec-runner",
                execution_step_key="neutral_draft",
                output_exists=False,
            )
        assert missing.value.code == "RUN_CHECKPOINT_OUTPUT_MISSING"
    finally:
        recovery.close()

    retry_session = SessionLocal()
    try:
        with pytest.raises(LLMNodeExecutionError) as blocked:
            _run_durable_runner(retry_session, client)
        assert blocked.value.error_code == "LLM_ACCOUNTING_EXECUTION_STEP_EXISTS"
        assert blocked.value.llm_call_id == parent.llm_call_id
        assert client.post_count == 1
    finally:
        retry_session.close()


def test_durable_runner_rejects_unsupported_online_client_before_provider_io(session) -> None:
    _seed_durable_runner_scene(session)
    client = _UnsupportedDurableOnlineClient()

    with pytest.raises(LLMNodeExecutionError) as rejected:
        _run_durable_runner(session, client)

    assert rejected.value.error_code == "LLM_ACCOUNTING_HOOK_UNSUPPORTED"
    assert client.provider_io_count == 0
    parent = session.execute(select(LlmCall)).scalar_one()
    assert parent.llm_call_id == rejected.value.llm_call_id
    assert parent.request_dispatched_at is None
    assert parent.accounting_status == "rejected"


def test_explicit_accounted_client_with_disabled_settings_still_uses_durable_accounting(session) -> None:
    _seed_durable_runner_scene(session)
    client = _AccountedRecordingClient()
    runner = LLMNodeRunner(
        session,
        llm_client=client,
        routing_config=_routing_config(),
        settings=_offline_settings(),
    )
    token = begin_llm_execution("exec-runner")
    try:
        result = runner.run(
            scene_id="CH_RUNNER_SC01",
            chapter_id="CH_RUNNER",
            bundle_id="bundle-runner",
            bundle_hash="sha256:runner",
            node_id="neutral_draft",
            step="neutral_draft",
            prompt=_prompt(),
            user_prompt="Scene ID: CH_RUNNER_SC01\nReturn JSON.",
            offline_client_factory=lambda: client,
            execution_step_key="neutral_draft",
        )
    finally:
        end_llm_execution(token)

    assert client.post_count == 1
    parent = session.execute(select(LlmCall)).scalar_one()
    attempt = session.execute(select(LlmCallAttempt)).scalar_one()
    assert result.llm_call_id == parent.llm_call_id
    assert parent.accounting_status == "settled"
    assert attempt.accounting_status == "settled"


def test_durable_online_intent_with_missing_scene_fails_before_provider_io(session) -> None:
    client = RecordingClient()
    runner = LLMNodeRunner(
        session,
        llm_client=client,
        routing_config=_routing_config(),
        settings=_live_settings(),
    )
    token = begin_llm_execution("exec-missing-scene")
    try:
        with pytest.raises(LLMNodeExecutionError) as rejected:
            runner.run(
                scene_id="MISSING_SCENE",
                chapter_id="MISSING_CHAPTER",
                bundle_id="bundle-runner",
                bundle_hash="sha256:runner",
                node_id="neutral_draft",
                step="neutral_draft",
                prompt=_prompt(),
                user_prompt="Return JSON.",
                offline_client_factory=lambda: client,
                execution_step_key="neutral_draft",
            )
    finally:
        end_llm_execution(token)

    assert rejected.value.error_code == "LLM_ACCOUNTING_CONTEXT_INVALID"
    assert client.requests == []
    assert session.execute(select(LlmCall)).scalars().all() == []


@pytest.mark.parametrize("missing_field", ["project", "execution", "step"])
def test_durable_online_intent_rejects_incomplete_accounting_context_before_provider(
    session,
    missing_field: str,
) -> None:
    if missing_field == "project":
        session.add(
            ChapterGoal(
                chapter_id="CH_NO_PROJECT",
                planned_scene_count=1,
                chapter_goal="missing project",
            )
        )
        session.add(
            SceneCard(
                scene_id="CH_NO_PROJECT_SC01",
                chapter_id="CH_NO_PROJECT",
                scene_seq=1,
                scene_goal="must reject",
                beats_json=[],
            )
        )
        session.add(
            SceneRunState(
                scene_id="CH_NO_PROJECT_SC01",
                scene_status="ready",
                active_execution_id="exec-context",
                run_execution_status="active",
                scene_token_budget=10_000,
                provider_attempt_budget=5,
            )
        )
        session.commit()
        scene_id = "CH_NO_PROJECT_SC01"
        chapter_id = "CH_NO_PROJECT"
    else:
        _seed_durable_runner_scene(session)
        scene_id = "CH_RUNNER_SC01"
        chapter_id = "CH_RUNNER"

    client = _AccountedRecordingClient()
    runner = LLMNodeRunner(
        session,
        llm_client=client,
        routing_config=_routing_config(),
        settings=_live_settings(),
    )
    execution_id = "" if missing_field == "execution" else "exec-context"
    step = "" if missing_field == "step" else "neutral_draft"
    token = begin_llm_execution(execution_id)
    try:
        with pytest.raises(LLMNodeExecutionError) as rejected:
            runner.run(
                scene_id=scene_id,
                chapter_id=chapter_id,
                bundle_id="bundle-runner",
                bundle_hash="sha256:runner",
                node_id="neutral_draft",
                step=step,
                prompt=_prompt(),
                user_prompt="Return JSON.",
                offline_client_factory=lambda: client,
                execution_step_key=step,
            )
    finally:
        end_llm_execution(token)

    assert rejected.value.error_code == "LLM_ACCOUNTING_CONTEXT_INVALID"
    assert client.post_count == 0
    assert session.execute(select(LlmCall)).scalars().all() == []


def test_unexpected_request_build_failure_is_not_masked_by_accounted_branch_flag(
    session,
    monkeypatch,
) -> None:
    runner = LLMNodeRunner(
        session,
        llm_client=_UnsupportedDurableOnlineClient(),
        routing_config=_routing_config(),
        settings=_live_settings(),
    )

    def fail_request_build(*_args, **_kwargs):  # noqa: ANN002, ANN003, ANN202
        raise RuntimeError("unexpected request construction failure")

    monkeypatch.setattr(runner, "_build_request", fail_request_build)
    token = begin_llm_execution("exec-request-build-fault")
    try:
        with pytest.raises(LLMNodeExecutionError) as failed:
            runner.run(
                scene_id="missing-scene",
                chapter_id="missing-chapter",
                bundle_id="bundle-runner",
                bundle_hash="sha256:runner",
                node_id="neutral_draft",
                step="neutral_draft",
                prompt=_prompt(),
                user_prompt="Return JSON.",
                offline_client_factory=_UnsupportedDurableOnlineClient,
                execution_step_key="neutral_draft",
            )
    finally:
        end_llm_execution(token)

    assert failed.value.error_code == "RuntimeError"
    assert isinstance(failed.value.original_error, RuntimeError)
    assert str(failed.value.original_error) == "unexpected request construction failure"


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
