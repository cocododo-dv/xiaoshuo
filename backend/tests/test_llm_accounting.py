from __future__ import annotations

import importlib
import json
import threading
from dataclasses import replace

import httpx
import pytest

from novel_system.db.models import LlmCall, LlmCallAttempt, SceneDraft, SceneRunState
from novel_system.db.session import SessionLocal
from novel_system.services.llm_client import LLMClient, LLMRequest, LLMResponse


def _accounting_module():
    return importlib.import_module("novel_system.services.llm_accounting")


def _request(*, max_output_tokens: int = 64) -> LLMRequest:
    return LLMRequest(
        model="test-model",
        messages=[
            {"role": "system", "content": "Return JSON."},
            {"role": "user", "content": "写一个短场景。"},
        ],
        temperature=0,
        max_output_tokens=max_output_tokens,
        response_format="json_object",
        provider="openai_compatible",
        node_id="neutral_draft",
    )


def _context(accounting):
    return accounting.LLMCallContext(
        scope_type="project",
        scope_id="project-1",
        node_id="neutral_draft",
        step="draft",
        project_id="project-1",
        execution_id="execution-1",
        execution_step_key="neutral_draft",
    )


def _scene_context(accounting, scene_id: str):
    return accounting.LLMCallContext(
        scope_type="scene",
        scope_id=scene_id,
        node_id="neutral_draft",
        step="draft",
        project_id="project-1",
        chapter_id="chapter-1",
        scene_id=scene_id,
        execution_id="execution-1",
        execution_step_key="neutral_draft",
    )


def test_request_estimate_includes_message_overhead_output_and_utf8_reservation() -> None:
    accounting = _accounting_module()

    estimate = accounting.estimate_request_usage(_request(max_output_tokens=80))

    assert estimate.estimated_input_tokens > 0
    assert estimate.estimated_output_tokens == 80
    assert estimate.estimated_tokens == estimate.estimated_input_tokens + 80
    assert estimate.reserved_tokens >= estimate.estimated_tokens
    assert estimate.reserved_tokens >= (
        sum(len(message["content"].encode("utf-8")) for message in _request().messages)
        + accounting.MESSAGE_TOKEN_OVERHEAD * len(_request().messages)
        + 80
    )


def test_request_estimate_includes_wire_response_schema_in_first_reservation() -> None:
    accounting = _accounting_module()
    schema = {
        "name": "large_payload",
        "schema": {
            "type": "object",
            "properties": {"scene_text": {"type": "string", "description": "正文约束" * 100}},
        },
    }
    request = replace(_request(max_output_tokens=80), response_schema=schema)

    estimate = accounting.estimate_request_usage(request)
    schema_bytes = len(
        json.dumps(schema, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    )
    message_bytes = sum(len(message["content"].encode("utf-8")) for message in request.messages)

    assert estimate.reserved_tokens >= (
        schema_bytes
        + message_bytes
        + accounting.MESSAGE_TOKEN_OVERHEAD * len(request.messages)
        + request.max_output_tokens
    )


def test_real_client_missing_raw_usage_is_estimated_and_never_charged_as_zero(session) -> None:
    accounting = _accounting_module()

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "id": "resp-without-usage",
                "model": "test-model",
                "output_text": '{"scene_text":"ok"}',
            },
        )

    client = LLMClient(
        provider="openai_compatible",
        base_url="https://example.test/v1",
        api_key="test-key",
        timeout_seconds=5,
        max_retries=0,
        transport=httpx.MockTransport(handler),
    )

    response = accounting.execute_accounted_call(
        session,
        client,
        _request(),
        _context(accounting),
    )

    session.expire_all()
    call = session.query(LlmCall).one()
    attempt = session.query(LlmCallAttempt).one()
    assert response.usage_present is False
    assert response.usage_complete is False
    assert call.usage_is_estimate is True
    assert call.total_tokens and call.total_tokens > 0
    assert call.budget_charged_tokens > 0
    assert attempt.usage_is_estimate is True
    assert attempt.total_tokens > 0


def test_explicit_offline_zero_usage_settles_parent_without_physical_attempt(session) -> None:
    accounting = _accounting_module()
    scene_id = "scene-offline"
    session.add(
        SceneRunState(
            scene_id=scene_id,
            scene_token_budget=100,
            provider_attempt_budget=5,
        )
    )
    session.commit()

    class OfflineClient:
        def generate(self, request: LLMRequest) -> LLMResponse:
            return LLMResponse(
                request_id="offline-1",
                provider="offline_deterministic",
                model=request.model,
                text='{"scene_text":"offline"}',
                structured_output={"scene_text": "offline"},
                response_format=request.response_format,
                raw_response={"id": "offline-1"},
                usage={"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
                finish_reason="offline_fallback",
            )

    response = accounting.execute_accounted_call(
        session,
        OfflineClient(),
        _request(),
        _scene_context(accounting, scene_id),
    )

    session.expire_all()
    call = session.query(LlmCall).one()
    assert response.provider == "offline_deterministic"
    assert call.accounting_status == "settled"
    assert call.total_tokens == 0
    assert call.budget_charged_tokens == 0
    assert call.usage_is_estimate is False
    assert session.query(LlmCallAttempt).count() == 0
    run_state = session.get(SceneRunState, scene_id)
    assert run_state.provider_attempts_used == 0
    assert run_state.scene_tokens_reserved == 0
    assert run_state.scene_tokens_used == 0


def _response_with_raw_usage(raw_usage, *, complete: bool) -> LLMResponse:
    return LLMResponse(
        request_id="usage-case",
        provider="openai_compatible",
        model="test-model",
        text='{"scene_text":"some generated text"}',
        structured_output={"scene_text": "some generated text"},
        response_format="json_object",
        raw_response={"usage": raw_usage} if raw_usage is not None else {},
        usage={"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
        raw_usage=raw_usage,
        usage_present=raw_usage is not None,
        usage_complete=complete,
    )


def test_complete_provider_usage_is_actual_and_persisted_without_estimate(session) -> None:
    accounting = _accounting_module()

    client = LLMClient(
        provider="openai_compatible",
        base_url="https://example.test/v1",
        api_key="test-key",
        timeout_seconds=5,
        max_retries=0,
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(
                200,
                json={
                    "id": "actual-usage",
                    "model": "test-model",
                    "output_text": '{"scene_text":"ok"}',
                    "usage": {"input_tokens": 13, "output_tokens": 7, "total_tokens": 20},
                },
            )
        ),
    )

    accounting.execute_accounted_call(session, client, _request(), _context(accounting))

    session.expire_all()
    parent = session.query(LlmCall).one()
    attempt = session.query(LlmCallAttempt).one()
    assert (attempt.prompt_tokens, attempt.completion_tokens, attempt.total_tokens) == (13, 7, 20)
    assert attempt.usage_is_estimate is False
    assert (parent.prompt_tokens, parent.completion_tokens, parent.total_tokens) == (13, 7, 20)
    assert parent.usage_is_estimate is False


@pytest.mark.parametrize(
    ("raw_usage", "complete"),
    [
        (None, False),
        ({"input_tokens": 9}, False),
        ({"output_tokens": 3}, False),
        ({"input_tokens": 9, "output_tokens": 3, "total_tokens": 99}, False),
        ({"input_tokens": "nine", "output_tokens": 3, "total_tokens": 3}, False),
        ({"input_tokens": -1, "output_tokens": 3, "total_tokens": 2}, False),
    ],
)
def test_missing_partial_inconsistent_or_invalid_usage_falls_back_conservatively(
    raw_usage,
    complete: bool,
) -> None:
    accounting = _accounting_module()

    usage = accounting.normalize_response_usage(
        _response_with_raw_usage(raw_usage, complete=complete),
        _request(),
    )

    assert usage.usage_is_estimate is True
    assert usage.prompt_tokens > 0
    assert usage.completion_tokens > 0
    assert usage.total_tokens == usage.prompt_tokens + usage.completion_tokens


def test_provider_failure_persists_failed_attempt_and_parent_with_conservative_charge(session) -> None:
    accounting = _accounting_module()

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timeout", request=request)

    client = LLMClient(
        provider="openai_compatible",
        base_url="https://example.test/v1",
        api_key="test-key",
        timeout_seconds=5,
        max_retries=0,
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(Exception, match="timed out"):
        accounting.execute_accounted_call(session, client, _request(), _context(accounting))

    session.expire_all()
    parent = session.query(LlmCall).one()
    attempt = session.query(LlmCallAttempt).one()
    assert attempt.accounting_status == "failed"
    assert attempt.error_code == "LLM_REQUEST_TIMEOUT"
    assert attempt.usage_is_estimate is True
    assert attempt.total_tokens > 0
    assert attempt.budget_charged_tokens == attempt.total_tokens
    assert parent.accounting_status == "failed"
    assert parent.error_code == "LLM_REQUEST_TIMEOUT"
    assert parent.total_tokens == attempt.total_tokens
    assert parent.budget_charged_tokens == attempt.budget_charged_tokens


def test_transport_retry_aggregates_each_physical_attempt_exactly_once(session) -> None:
    accounting = _accounting_module()
    post_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal post_count
        post_count += 1
        if post_count == 1:
            raise httpx.ReadTimeout("timeout", request=request)
        return httpx.Response(
            200,
            json={
                "id": "retry-ok",
                "model": "test-model",
                "output_text": '{"scene_text":"ok"}',
                "usage": {"input_tokens": 11, "output_tokens": 5, "total_tokens": 16},
            },
        )

    client = LLMClient(
        provider="openai_compatible",
        base_url="https://example.test/v1",
        api_key="test-key",
        timeout_seconds=5,
        max_retries=1,
        transport=httpx.MockTransport(handler),
    )

    accounting.execute_accounted_call(session, client, _request(), _context(accounting))

    session.expire_all()
    parent = session.query(LlmCall).one()
    attempts = session.query(LlmCallAttempt).order_by(LlmCallAttempt.provider_attempt_no).all()
    assert post_count == 2
    assert [row.dispatch_kind for row in attempts] == ["initial", "transport_retry"]
    assert [row.accounting_status for row in attempts] == ["failed", "settled"]
    assert parent.total_tokens == sum(row.total_tokens for row in attempts)
    assert parent.budget_charged_tokens == sum(row.budget_charged_tokens for row in attempts)
    assert parent.reserved_tokens == sum(row.reserved_tokens for row in attempts)
    assert parent.usage_is_estimate is True
    assert parent.accounting_status == "settled"


def test_missing_text_degrade_uses_new_larger_reservation_and_aggregates_actual_usage(session) -> None:
    accounting = _accounting_module()
    post_count = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal post_count
        post_count += 1
        if post_count == 1:
            return httpx.Response(
                200,
                json={
                    "id": "missing-text",
                    "model": "test-model",
                    "usage": {"input_tokens": 9, "output_tokens": 2, "total_tokens": 11},
                },
            )
        return httpx.Response(
            200,
            json={
                "id": "degrade-ok",
                "model": "test-model",
                "output_text": '{"scene_text":"ok"}',
                "usage": {"input_tokens": 10, "output_tokens": 4, "total_tokens": 14},
            },
        )

    client = LLMClient(
        provider="openai_compatible",
        base_url="https://example.test/v1",
        api_key="test-key",
        timeout_seconds=5,
        max_retries=0,
        transport=httpx.MockTransport(handler),
    )

    accounting.execute_accounted_call(session, client, _request(), _context(accounting))

    session.expire_all()
    parent = session.query(LlmCall).one()
    attempts = session.query(LlmCallAttempt).order_by(LlmCallAttempt.provider_attempt_no).all()
    assert [row.dispatch_kind for row in attempts] == ["initial", "missing_text_degrade"]
    assert [row.request_max_output_tokens for row in attempts] == [64, 128]
    assert attempts[1].reserved_tokens > attempts[0].reserved_tokens
    assert [row.total_tokens for row in attempts] == [11, 14]
    assert parent.total_tokens == 25
    assert parent.budget_charged_tokens == 25
    assert parent.usage_is_estimate is False


def test_structured_degrade_recomputes_reservation_for_rewritten_messages(session) -> None:
    accounting = _accounting_module()
    post_count = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal post_count
        post_count += 1
        if post_count == 1:
            return httpx.Response(500, text="guided_grammar compile error")
        return httpx.Response(
            200,
            json={
                "id": "schema-degrade-ok",
                "model": "test-model",
                "output_text": '{"scene_text":"ok"}',
                "usage": {"input_tokens": 10, "output_tokens": 4, "total_tokens": 14},
            },
        )

    client = LLMClient(
        provider="openai_compatible",
        base_url="https://example.test/v1",
        api_key="test-key",
        timeout_seconds=5,
        max_retries=0,
        transport=httpx.MockTransport(handler),
    )
    request = replace(
        _request(),
        response_schema={
            "name": "scene_payload",
            "schema": {
                "type": "object",
                "properties": {"scene_text": {"type": "string", "description": "正文" * 40}},
                "required": ["scene_text"],
            },
        },
    )

    accounting.execute_accounted_call(session, client, request, _context(accounting))

    attempts = session.query(LlmCallAttempt).order_by(LlmCallAttempt.provider_attempt_no).all()
    assert post_count == 2
    assert [row.dispatch_kind for row in attempts] == ["initial", "transport_retry"]
    assert attempts[1].reserved_tokens > attempts[0].reserved_tokens


def test_provider_attempt_budget_rejects_second_post_without_erasing_first_charge(session) -> None:
    accounting = _accounting_module()
    scene_id = "scene-attempt-budget"
    session.add(
        SceneRunState(
            scene_id=scene_id,
            scene_token_budget=10_000,
            provider_attempt_budget=1,
        )
    )
    session.commit()
    post_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal post_count
        post_count += 1
        raise httpx.ReadTimeout("timeout", request=request)

    client = LLMClient(
        provider="openai_compatible",
        base_url="https://example.test/v1",
        api_key="test-key",
        timeout_seconds=5,
        max_retries=1,
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(Exception) as exc_info:
        accounting.execute_accounted_call(
            session,
            client,
            _request(),
            _scene_context(accounting, scene_id),
        )

    assert getattr(exc_info.value, "code", None) == "LLM_PROVIDER_ATTEMPT_BUDGET_EXHAUSTED"
    session.expire_all()
    run_state = session.get(SceneRunState, scene_id)
    parent = session.query(LlmCall).one()
    attempts = session.query(LlmCallAttempt).all()
    assert post_count == 1
    assert run_state.provider_attempts_used == 1
    assert len(attempts) == 1
    assert attempts[0].accounting_status == "failed"
    assert parent.accounting_status == "failed"
    assert parent.budget_charged_tokens == attempts[0].budget_charged_tokens > 0


def test_token_budget_rejection_before_dispatch_has_no_post_attempt_or_charge(session) -> None:
    accounting = _accounting_module()
    scene_id = "scene-token-budget"
    session.add(
        SceneRunState(
            scene_id=scene_id,
            scene_token_budget=1,
            provider_attempt_budget=5,
        )
    )
    session.commit()
    post_count = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal post_count
        post_count += 1
        return httpx.Response(500)

    client = LLMClient(
        provider="openai_compatible",
        base_url="https://example.test/v1",
        api_key="test-key",
        timeout_seconds=5,
        max_retries=0,
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(Exception) as exc_info:
        accounting.execute_accounted_call(
            session,
            client,
            _request(),
            _scene_context(accounting, scene_id),
        )

    assert getattr(exc_info.value, "code", None) == "LLM_SCENE_TOKEN_BUDGET_EXHAUSTED"
    session.expire_all()
    run_state = session.get(SceneRunState, scene_id)
    parent = session.query(LlmCall).one()
    assert post_count == 0
    assert run_state.provider_attempts_used == 0
    assert run_state.scene_tokens_reserved == 0
    assert session.query(LlmCallAttempt).count() == 0
    assert parent.accounting_status == "rejected"
    assert parent.budget_charged_tokens == 0


def test_pending_business_write_is_precommitted_and_survives_provider_failure(session) -> None:
    accounting = _accounting_module()
    session.add(
        SceneDraft(
            row_id="business-before-provider",
            scene_id="scene-1",
            chapter_id="chapter-1",
            stage="neutral",
            content="already generated business text",
            source_bundle_id="bundle-1",
            source_bundle_hash="hash-1",
        )
    )
    session.flush()

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timeout", request=request)

    client = LLMClient(
        provider="openai_compatible",
        base_url="https://example.test/v1",
        api_key="test-key",
        timeout_seconds=5,
        max_retries=0,
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(Exception):
        accounting.execute_accounted_call(session, client, _request(), _context(accounting))
    session.rollback()

    with SessionLocal() as verifier:
        assert verifier.get(SceneDraft, "business-before-provider") is not None
        assert verifier.query(LlmCall).one().accounting_status == "failed"


def test_network_wait_holds_no_caller_write_lock_and_second_session_can_commit(session) -> None:
    accounting = _accounting_module()
    session.add(
        SceneDraft(
            row_id="caller-pending",
            scene_id="scene-1",
            chapter_id="chapter-1",
            stage="neutral",
            content="caller text",
            source_bundle_id="bundle-1",
            source_bundle_hash="hash-1",
        )
    )
    session.flush()

    def handler(_request: httpx.Request) -> httpx.Response:
        with SessionLocal() as concurrent:
            concurrent.add(
                SceneDraft(
                    row_id="concurrent-during-provider",
                    scene_id="scene-2",
                    chapter_id="chapter-1",
                    stage="neutral",
                    content="concurrent text",
                    source_bundle_id="bundle-2",
                    source_bundle_hash="hash-2",
                )
            )
            concurrent.commit()
        return httpx.Response(
            200,
            json={
                "id": "lock-free-ok",
                "model": "test-model",
                "output_text": '{"scene_text":"ok"}',
                "usage": {"input_tokens": 10, "output_tokens": 4, "total_tokens": 14},
            },
        )

    client = LLMClient(
        provider="openai_compatible",
        base_url="https://example.test/v1",
        api_key="test-key",
        timeout_seconds=5,
        max_retries=0,
        transport=httpx.MockTransport(handler),
    )

    accounting.execute_accounted_call(session, client, _request(), _context(accounting))

    with SessionLocal() as verifier:
        assert verifier.get(SceneDraft, "caller-pending") is not None
        assert verifier.get(SceneDraft, "concurrent-during-provider") is not None
        assert verifier.query(LlmCall).one().accounting_status == "settled"


def test_response_exposes_stable_call_id_and_postprocess_failure_reuses_parent(session) -> None:
    accounting = _accounting_module()
    client = LLMClient(
        provider="openai_compatible",
        base_url="https://example.test/v1",
        api_key="test-key",
        timeout_seconds=5,
        max_retries=0,
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(
                200,
                json={
                    "id": "postprocess-ok",
                    "model": "test-model",
                    "output_text": '{"scene_text":"ok"}',
                    "usage": {"input_tokens": 10, "output_tokens": 4, "total_tokens": 14},
                },
            )
        ),
    )

    response = accounting.execute_accounted_call(
        session,
        client,
        _request(),
        _context(accounting),
        llm_call_id="stable-call-id",
    )
    accounting.mark_postprocess_failure(
        session,
        response.llm_call_id,
        error_code="CALLER_SCHEMA_INVALID",
        error_text="missing scene field",
    )

    session.expire_all()
    parent = session.query(LlmCall).one()
    assert response.llm_call_id == "stable-call-id"
    assert parent.llm_call_id == "stable-call-id"
    assert parent.accounting_status == "failed"
    assert parent.error_code == "CALLER_SCHEMA_INVALID"
    assert parent.budget_charged_tokens == 14
    assert session.query(LlmCallAttempt).count() == 1


class _SimulatedProcessCrash(BaseException):
    pass


def test_recovery_releases_reserved_but_undispatched_attempt_and_allows_retry(session) -> None:
    accounting = _accounting_module()
    scene_id = "scene-reservation-crash"
    session.add(
        SceneRunState(
            scene_id=scene_id,
            scene_token_budget=10_000,
            provider_attempt_budget=5,
        )
    )
    session.commit()
    post_count = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal post_count
        post_count += 1
        return httpx.Response(
            200,
            json={
                "id": "after-recovery",
                "model": "test-model",
                "output_text": '{"scene_text":"ok"}',
                "usage": {"input_tokens": 10, "output_tokens": 4, "total_tokens": 14},
            },
        )

    client = LLMClient(
        provider="openai_compatible",
        base_url="https://example.test/v1",
        api_key="test-key",
        timeout_seconds=5,
        max_retries=0,
        transport=httpx.MockTransport(handler),
    )

    def crash_after_reservation(stage: str, _attempt_id: str) -> None:
        if stage == "reservation_committed":
            raise _SimulatedProcessCrash()

    with pytest.raises(_SimulatedProcessCrash):
        accounting.execute_accounted_call(
            session,
            client,
            _request(),
            _scene_context(accounting, scene_id),
            llm_call_id="reservation-crash-call",
            _lifecycle_observer=crash_after_reservation,
        )

    session.expire_all()
    attempt = session.query(LlmCallAttempt).one()
    assert post_count == 0
    assert attempt.accounting_status == "reserved"
    assert attempt.request_dispatched_at is None
    assert session.get(SceneRunState, scene_id).scene_tokens_reserved == attempt.reserved_tokens

    result = accounting.recover_incomplete_call(session, "reservation-crash-call")

    session.expire_all()
    assert result.status == "released"
    assert result.error_code is None
    assert result.may_retry is True
    assert session.get(LlmCall, "reservation-crash-call").accounting_status == "released"
    assert session.query(LlmCallAttempt).one().accounting_status == "released"
    assert session.get(SceneRunState, scene_id).scene_tokens_reserved == 0
    assert session.get(SceneRunState, scene_id).provider_attempts_used == 0

    accounting.execute_accounted_call(
        session,
        client,
        _request(),
        _scene_context(accounting, scene_id),
        llm_call_id="reservation-crash-retry",
    )
    assert post_count == 1


def test_recovery_charges_dispatched_unknown_attempt_and_same_call_is_not_resent(session) -> None:
    accounting = _accounting_module()
    scene_id = "scene-dispatch-crash"
    session.add(
        SceneRunState(
            scene_id=scene_id,
            scene_token_budget=10_000,
            provider_attempt_budget=5,
        )
    )
    session.commit()
    post_count = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal post_count
        post_count += 1
        return httpx.Response(500)

    client = LLMClient(
        provider="openai_compatible",
        base_url="https://example.test/v1",
        api_key="test-key",
        timeout_seconds=5,
        max_retries=0,
        transport=httpx.MockTransport(handler),
    )

    def crash_after_dispatch(stage: str, _attempt_id: str) -> None:
        if stage == "dispatch_committed":
            raise _SimulatedProcessCrash()

    with pytest.raises(_SimulatedProcessCrash):
        accounting.execute_accounted_call(
            session,
            client,
            _request(),
            _scene_context(accounting, scene_id),
            llm_call_id="dispatch-crash-call",
            _lifecycle_observer=crash_after_dispatch,
        )

    session.expire_all()
    attempt = session.query(LlmCallAttempt).one()
    assert post_count == 0
    assert attempt.accounting_status == "reserved"
    assert attempt.request_dispatched_at is not None
    assert session.get(SceneRunState, scene_id).provider_attempts_used == 1

    result = accounting.recover_incomplete_call(session, "dispatch-crash-call")

    session.expire_all()
    parent = session.get(LlmCall, "dispatch-crash-call")
    attempt = session.query(LlmCallAttempt).one()
    run_state = session.get(SceneRunState, scene_id)
    assert result.status == "failed"
    assert result.error_code == "RUN_CHECKPOINT_OUTPUT_MISSING"
    assert result.may_retry is False
    assert parent.accounting_status == "failed"
    assert parent.error_code == "RUN_CHECKPOINT_OUTPUT_MISSING"
    assert attempt.accounting_status == "failed"
    assert attempt.budget_charged_tokens == attempt.estimated_tokens > 0
    assert parent.budget_charged_tokens == attempt.budget_charged_tokens
    assert run_state.scene_tokens_reserved == 0
    assert run_state.scene_tokens_used == attempt.budget_charged_tokens

    with pytest.raises(Exception) as exc_info:
        accounting.execute_accounted_call(
            session,
            client,
            _request(),
            _scene_context(accounting, scene_id),
            llm_call_id="dispatch-crash-new-call-same-execution-step",
        )
    assert getattr(exc_info.value, "code", None) == "RUN_CHECKPOINT_OUTPUT_MISSING"
    assert post_count == 0


def test_non_object_provider_response_conservatively_settles_child_without_reservation_leak(session) -> None:
    accounting = _accounting_module()
    scene_id = "scene-invalid-provider-response"
    session.add(
        SceneRunState(
            scene_id=scene_id,
            scene_token_budget=10_000,
            provider_attempt_budget=5,
        )
    )
    session.commit()
    client = LLMClient(
        provider="openai_compatible",
        base_url="https://example.test/v1",
        api_key="test-key",
        timeout_seconds=5,
        max_retries=0,
        transport=httpx.MockTransport(lambda _request: httpx.Response(200, json=["invalid"])),
    )

    with pytest.raises(Exception) as exc_info:
        accounting.execute_accounted_call(
            session,
            client,
            _request(),
            _scene_context(accounting, scene_id),
        )

    assert getattr(exc_info.value, "code", None) == "LLM_RESPONSE_INVALID"
    session.expire_all()
    parent = session.query(LlmCall).one()
    attempt = session.query(LlmCallAttempt).one()
    run_state = session.get(SceneRunState, scene_id)
    assert parent.accounting_status == "failed"
    assert attempt.accounting_status == "failed"
    assert attempt.error_code == "LLM_RESPONSE_INVALID"
    assert attempt.budget_charged_tokens == attempt.estimated_tokens > 0
    assert run_state.scene_tokens_reserved == 0
    assert run_state.scene_tokens_used == attempt.total_tokens


def test_settled_execution_step_cannot_create_a_second_parent_or_post_again(session) -> None:
    accounting = _accounting_module()
    post_count = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal post_count
        post_count += 1
        return httpx.Response(
            200,
            json={
                "id": f"success-{post_count}",
                "model": "test-model",
                "output_text": '{"scene_text":"ok"}',
                "usage": {"input_tokens": 10, "output_tokens": 4, "total_tokens": 14},
            },
        )

    client = LLMClient(
        provider="openai_compatible",
        base_url="https://example.test/v1",
        api_key="test-key",
        timeout_seconds=5,
        max_retries=0,
        transport=httpx.MockTransport(handler),
    )
    context = _context(accounting)

    accounting.execute_accounted_call(session, client, _request(), context, llm_call_id="first-parent")
    with pytest.raises(Exception) as exc_info:
        accounting.execute_accounted_call(session, client, _request(), context, llm_call_id="second-parent")

    assert getattr(exc_info.value, "code", None) == "LLM_ACCOUNTING_EXECUTION_STEP_EXISTS"
    assert post_count == 1
    assert session.query(LlmCall).count() == 1


def test_usage_over_reservation_charges_actual_to_scene_and_blocks_later_dispatch(session) -> None:
    accounting = _accounting_module()
    scene_id = "scene-usage-over-reservation"
    session.add(
        SceneRunState(
            scene_id=scene_id,
            scene_token_budget=None,
            provider_attempt_budget=5,
        )
    )
    session.commit()
    post_count = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal post_count
        post_count += 1
        return httpx.Response(
            200,
            json={
                "id": "over-reservation",
                "model": "test-model",
                "output_text": '{"scene_text":"ok"}',
                "usage": {"input_tokens": 10_000, "output_tokens": 10_000, "total_tokens": 20_000},
            },
        )

    client = LLMClient(
        provider="openai_compatible",
        base_url="https://example.test/v1",
        api_key="test-key",
        timeout_seconds=5,
        max_retries=0,
        transport=httpx.MockTransport(handler),
    )
    first_context = _scene_context(accounting, scene_id)

    accounting.execute_accounted_call(session, client, _request(), first_context, llm_call_id="overage-call")

    session.expire_all()
    parent = session.get(LlmCall, "overage-call")
    attempt = session.query(LlmCallAttempt).one()
    run_state = session.get(SceneRunState, scene_id)
    assert parent.accounting_status == "usage_exceeds_reservation"
    assert attempt.accounting_status == "usage_exceeds_reservation"
    assert attempt.total_tokens == 20_000
    assert attempt.budget_charged_tokens == attempt.reserved_tokens < attempt.total_tokens
    assert parent.response_payload_summary["usage_overage_tokens"] == (
        attempt.total_tokens - attempt.reserved_tokens
    )
    assert run_state.scene_tokens_used == 20_000

    accounting.mark_postprocess_failure(
        session,
        "overage-call",
        error_code="CALLER_SCHEMA_INVALID",
        error_text="scene_text failed caller validation",
    )
    session.expire_all()
    parent = session.get(LlmCall, "overage-call")
    assert parent.accounting_status == "usage_exceeds_reservation"
    assert parent.error_code == "CALLER_SCHEMA_INVALID"
    assert parent.response_payload_summary["postprocess_error"] == (
        "scene_text failed caller validation"
    )

    second_context = replace(first_context, execution_id="execution-2")
    with pytest.raises(Exception) as exc_info:
        accounting.execute_accounted_call(
            session,
            client,
            _request(),
            second_context,
            llm_call_id="blocked-after-overage",
        )
    assert getattr(exc_info.value, "code", None) == "LLM_USAGE_EXCEEDS_RESERVATION"
    assert post_count == 1


def test_failed_provider_response_with_overage_keeps_parent_child_audit_consistent(session) -> None:
    accounting = _accounting_module()
    scene_id = "scene-failed-overage"
    session.add(
        SceneRunState(
            scene_id=scene_id,
            scene_token_budget=None,
            provider_attempt_budget=5,
        )
    )
    session.commit()
    client = LLMClient(
        provider="openai_compatible",
        base_url="https://example.test/v1",
        api_key="test-key",
        timeout_seconds=5,
        max_retries=0,
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(
                500,
                json={
                    "id": "failed-overage",
                    "error": {"message": "provider failed after consuming tokens"},
                    "usage": {"input_tokens": 12_000, "output_tokens": 8_000, "total_tokens": 20_000},
                },
            )
        ),
    )

    with pytest.raises(Exception) as exc_info:
        accounting.execute_accounted_call(
            session,
            client,
            _request(),
            _scene_context(accounting, scene_id),
            llm_call_id="failed-overage-call",
        )
    assert getattr(exc_info.value, "code", None) == "LLM_HTTP_RETRYABLE_FAILURE"

    session.expire_all()
    parent = session.get(LlmCall, "failed-overage-call")
    attempt = session.query(LlmCallAttempt).one()
    run_state = session.get(SceneRunState, scene_id)
    assert attempt.accounting_status == "usage_exceeds_reservation"
    assert parent.accounting_status == "usage_exceeds_reservation"
    assert parent.error_code == "LLM_HTTP_RETRYABLE_FAILURE"
    assert parent.total_tokens == attempt.total_tokens == 20_000
    assert parent.response_payload_summary["usage_overage_tokens"] == (
        attempt.total_tokens - attempt.reserved_tokens
    )
    assert run_state.scene_tokens_used == 20_000
    assert run_state.run_execution_status == "usage_exceeds_reservation"


def test_concurrent_scene_budget_gate_has_one_post_winner_and_no_lost_counts(session) -> None:
    accounting = _accounting_module()
    scene_id = "scene-concurrent-budget"
    session.add(
        SceneRunState(
            scene_id=scene_id,
            scene_token_budget=10_000,
            provider_attempt_budget=1,
        )
    )
    session.commit()

    start = threading.Barrier(3)
    both_reserved = threading.Barrier(2)
    post_lock = threading.Lock()
    post_count = 0
    outcomes: list[tuple[str, str | None]] = []

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal post_count
        with post_lock:
            post_count += 1
        return httpx.Response(
            200,
            json={
                "id": "concurrent-winner",
                "model": "test-model",
                "output_text": '{"scene_text":"ok"}',
                "usage": {"input_tokens": 10, "output_tokens": 4, "total_tokens": 14},
            },
        )

    def worker(worker_no: int) -> None:
        client = LLMClient(
            provider="openai_compatible",
            base_url="https://example.test/v1",
            api_key="test-key",
            timeout_seconds=5,
            max_retries=0,
            transport=httpx.MockTransport(handler),
        )
        with SessionLocal() as worker_session:
            context = replace(
                _scene_context(accounting, scene_id),
                execution_id=f"concurrent-execution-{worker_no}",
            )
            start.wait()

            def hold_after_both_reservations(stage: str, _attempt_id: str) -> None:
                if stage == "reservation_committed":
                    both_reserved.wait(timeout=10)

            try:
                accounting.execute_accounted_call(
                    worker_session,
                    client,
                    _request(),
                    context,
                    llm_call_id=f"concurrent-call-{worker_no}",
                    _lifecycle_observer=hold_after_both_reservations,
                )
            except Exception as exc:  # noqa: BLE001 - assertion records normalized domain code
                outcomes.append(("error", getattr(exc, "code", None)))
            else:
                outcomes.append(("success", None))

    threads = [threading.Thread(target=worker, args=(worker_no,)) for worker_no in (1, 2)]
    for thread in threads:
        thread.start()
    start.wait()
    for thread in threads:
        thread.join(timeout=10)
        assert not thread.is_alive()

    session.expire_all()
    run_state = session.get(SceneRunState, scene_id)
    assert sorted(outcomes) == [
        ("error", "LLM_PROVIDER_ATTEMPT_BUDGET_EXHAUSTED"),
        ("success", None),
    ]
    assert post_count == 1
    assert run_state.provider_attempts_used == 1
    assert run_state.scene_tokens_reserved == 0
    assert run_state.scene_tokens_used == 14
    attempts = session.query(LlmCallAttempt).all()
    assert len(attempts) == 2
    assert sorted(attempt.accounting_status for attempt in attempts) == ["rejected", "settled"]


def test_concurrent_same_execution_step_has_one_parent_and_never_double_posts(session) -> None:
    accounting = _accounting_module()
    entered_provider = threading.Event()
    release_provider = threading.Event()
    post_count = 0
    first_errors: list[BaseException] = []

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal post_count
        post_count += 1
        entered_provider.set()
        assert release_provider.wait(timeout=10)
        return httpx.Response(
            200,
            json={
                "id": "execution-winner",
                "model": "test-model",
                "output_text": '{"scene_text":"ok"}',
                "usage": {"input_tokens": 10, "output_tokens": 4, "total_tokens": 14},
            },
        )

    client = LLMClient(
        provider="openai_compatible",
        base_url="https://example.test/v1",
        api_key="test-key",
        timeout_seconds=12,
        max_retries=0,
        transport=httpx.MockTransport(handler),
    )
    context = _context(accounting)

    def first_worker() -> None:
        with SessionLocal() as worker_session:
            try:
                accounting.execute_accounted_call(
                    worker_session,
                    client,
                    _request(),
                    context,
                    llm_call_id="execution-first",
                )
            except BaseException as exc:  # noqa: BLE001 - forwarded to main assertion
                first_errors.append(exc)

    thread = threading.Thread(target=first_worker)
    thread.start()
    assert entered_provider.wait(timeout=10)

    with SessionLocal() as competing_session:
        with pytest.raises(Exception) as exc_info:
            accounting.execute_accounted_call(
                competing_session,
                client,
                _request(),
                context,
                llm_call_id="execution-second",
            )
    assert getattr(exc_info.value, "code", None) == "RUN_CHECKPOINT_OUTPUT_MISSING"
    release_provider.set()
    thread.join(timeout=10)
    assert not thread.is_alive()
    assert first_errors == []

    session.expire_all()
    assert post_count == 1
    assert session.query(LlmCall).count() == 1
    assert session.query(LlmCallAttempt).count() == 1
