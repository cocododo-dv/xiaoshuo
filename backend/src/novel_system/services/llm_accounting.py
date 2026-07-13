"""Durable accounting boundary for provider-backed LLM calls.

The caller session is deliberately committed before provider work.  Every
physical POST then uses short reservation, dispatch, and settlement
transactions; no database write transaction is held while waiting on the
network.
"""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import Any, Literal

from sqlalchemy import or_, select, update
from sqlalchemy.orm import Session

from novel_system.db.models import LlmCall, LlmCallAttempt, SceneRunState, utcnow
from novel_system.services.context_budget import estimate_tokens
from novel_system.services.llm_client import (
    LLMClient,
    LLMClientError,
    LLMRequest,
    LLMResponse,
)
from novel_system.services.llm_providers.base import LLMDispatchKind


MESSAGE_TOKEN_OVERHEAD = 4


@dataclass(frozen=True, slots=True)
class LLMCallContext:
    """Explicit durable ownership for one logical call; IDs are never guessed."""

    scope_type: str
    scope_id: str
    node_id: str
    step: str
    project_id: str | None = None
    scene_id: str | None = None
    chapter_id: str | None = None
    run_job_id: str | None = None
    execution_id: str | None = None
    execution_step_key: str | None = None

    def __post_init__(self) -> None:
        required = {
            "scope_type": self.scope_type,
            "scope_id": self.scope_id,
            "node_id": self.node_id,
            "step": self.step,
        }
        missing = [name for name, value in required.items() if not str(value).strip()]
        if missing:
            raise ValueError(f"LLMCallContext requires explicit {', '.join(missing)}")


@dataclass(frozen=True, slots=True)
class RequestUsageEstimate:
    estimated_input_tokens: int
    estimated_output_tokens: int
    estimated_tokens: int
    reserved_tokens: int


@dataclass(frozen=True, slots=True)
class NormalizedUsage:
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    usage_is_estimate: bool


@dataclass(frozen=True, slots=True)
class AccountingRecoveryResult:
    status: Literal["released", "failed"]
    error_code: str | None
    may_retry: bool


class LLMAccountingError(LLMClientError):
    pass


class LLMAccountingRejected(LLMAccountingError):
    pass


def estimate_request_usage(request: LLMRequest) -> RequestUsageEstimate:
    contents = [str(message.get("content") or "") for message in request.messages]
    wire_segments = list(contents)
    if request.wire_response_format and request.response_schema is not None:
        wire_segments.append(
            json.dumps(
                request.response_schema,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
        )
    overhead = MESSAGE_TOKEN_OVERHEAD * len(contents)
    estimated_input = sum(estimate_tokens(content) for content in wire_segments) + overhead
    estimated_output = max(0, int(request.max_output_tokens))
    estimated_total = estimated_input + estimated_output
    # One token cannot contain less than one UTF-8 byte.  This intentionally
    # over-reserves multilingual prompts while still being deterministic.
    utf8_upper_bound = sum(len(content.encode("utf-8")) for content in wire_segments) + overhead
    reserved = max(estimated_total, utf8_upper_bound + estimated_output)
    return RequestUsageEstimate(
        estimated_input_tokens=estimated_input,
        estimated_output_tokens=estimated_output,
        estimated_tokens=estimated_total,
        reserved_tokens=reserved,
    )


def normalize_response_usage(response: LLMResponse, request: LLMRequest) -> NormalizedUsage:
    if response.provider == "offline_deterministic" and _is_explicit_zero_usage(response.usage):
        return NormalizedUsage(0, 0, 0, False)

    if response.usage_complete is True:
        actual = _normalize_raw_usage(response.raw_usage)
        if actual is not None:
            return actual

    request_estimate = estimate_request_usage(request)
    completion_estimate = estimate_tokens(response.text)
    total = request_estimate.estimated_input_tokens + completion_estimate
    return NormalizedUsage(
        prompt_tokens=request_estimate.estimated_input_tokens,
        completion_tokens=completion_estimate,
        total_tokens=max(1, total),
        usage_is_estimate=True,
    )


def _begin_claim_transaction(session: Session) -> None:
    """Serialize the absent-row execution-step claim on file-backed SQLite."""

    bind = session.get_bind()
    if bind.dialect.name == "sqlite":
        session.connection().exec_driver_sql("BEGIN IMMEDIATE")


def _execution_step_conflict(existing_call: LlmCall) -> LLMAccountingError:
    if (
        existing_call.request_dispatched_at is not None
        and existing_call.accounting_status in {"reserved", "failed"}
    ) or existing_call.error_code == "RUN_CHECKPOINT_OUTPUT_MISSING":
        return LLMAccountingError(
            "RUN_CHECKPOINT_OUTPUT_MISSING",
            "this execution step may already have reached the provider; automatic resend is blocked",
        )
    if existing_call.accounting_status == "usage_exceeds_reservation":
        return LLMAccountingError(
            "LLM_USAGE_EXCEEDS_RESERVATION",
            "this execution step exceeded its reservation; automatic resend is blocked",
        )
    if existing_call.accounting_status == "reserved":
        return LLMAccountingError(
            "LLM_ACCOUNTING_EXECUTION_STEP_IN_PROGRESS",
            "this execution step already has an active accounting claim",
        )
    return LLMAccountingError(
        "LLM_ACCOUNTING_EXECUTION_STEP_EXISTS",
        f"this execution step already has a {existing_call.accounting_status} provider call",
    )


def _reserve_scene_capacity(session: Session, scene_id: str | None, reserved_tokens: int) -> bool:
    if scene_id is None:
        return False
    result = session.execute(
        update(SceneRunState)
        .where(
            SceneRunState.scene_id == scene_id,
            SceneRunState.provider_attempts_used < SceneRunState.provider_attempt_budget,
            or_(
                SceneRunState.scene_token_budget.is_(None),
                SceneRunState.scene_tokens_used
                + SceneRunState.scene_tokens_reserved
                + reserved_tokens
                <= SceneRunState.scene_token_budget,
            ),
            or_(
                SceneRunState.run_execution_status.is_(None),
                SceneRunState.run_execution_status != "usage_exceeds_reservation",
            ),
        )
        .values(scene_tokens_reserved=SceneRunState.scene_tokens_reserved + reserved_tokens)
        .execution_options(synchronize_session=False)
    )
    if result.rowcount == 1:
        return True
    session.rollback()
    error = _scene_gate_error(session, scene_id, reserved_tokens=reserved_tokens)
    session.rollback()
    if error is None:
        return False
    raise error


def _scene_gate_error(
    session: Session,
    scene_id: str,
    *,
    reserved_tokens: int,
) -> LLMAccountingRejected | None:
    state = session.execute(
        select(
            SceneRunState.provider_attempts_used,
            SceneRunState.provider_attempt_budget,
            SceneRunState.scene_token_budget,
            SceneRunState.scene_tokens_used,
            SceneRunState.scene_tokens_reserved,
            SceneRunState.run_execution_status,
        ).where(SceneRunState.scene_id == scene_id)
    ).one_or_none()
    if state is None:
        return None
    if state.run_execution_status == "usage_exceeds_reservation":
        return LLMAccountingRejected(
            "LLM_USAGE_EXCEEDS_RESERVATION",
            "scene accounting is blocked after provider usage exceeded its reservation",
        )
    if state.provider_attempts_used >= state.provider_attempt_budget:
        return LLMAccountingRejected(
            "LLM_PROVIDER_ATTEMPT_BUDGET_EXHAUSTED",
            "provider attempt budget exhausted before dispatch",
        )
    if (
        state.scene_token_budget is not None
        and state.scene_tokens_used + state.scene_tokens_reserved + reserved_tokens
        > state.scene_token_budget
    ):
        return LLMAccountingRejected(
            "LLM_SCENE_TOKEN_BUDGET_EXHAUSTED",
            "scene token budget exhausted before dispatch",
        )
    return LLMAccountingRejected(
        "LLM_PROVIDER_ATTEMPT_BUDGET_EXHAUSTED",
        "provider attempt claim lost a concurrent budget race",
    )


def _consume_scene_provider_attempt(session: Session, scene_id: str | None) -> bool:
    if scene_id is None:
        return False
    result = session.execute(
        update(SceneRunState)
        .where(
            SceneRunState.scene_id == scene_id,
            SceneRunState.provider_attempts_used < SceneRunState.provider_attempt_budget,
            or_(
                SceneRunState.run_execution_status.is_(None),
                SceneRunState.run_execution_status != "usage_exceeds_reservation",
            ),
        )
        .values(provider_attempts_used=SceneRunState.provider_attempts_used + 1)
        .execution_options(synchronize_session=False)
    )
    return result.rowcount == 1


def _release_scene_reservation(session: Session, scene_id: str | None, reserved_tokens: int) -> None:
    if scene_id is None:
        return
    result = session.execute(
        update(SceneRunState)
        .where(
            SceneRunState.scene_id == scene_id,
            SceneRunState.scene_tokens_reserved >= reserved_tokens,
        )
        .values(scene_tokens_reserved=SceneRunState.scene_tokens_reserved - reserved_tokens)
        .execution_options(synchronize_session=False)
    )
    if result.rowcount == 0 and session.scalar(
        select(SceneRunState.scene_id).where(SceneRunState.scene_id == scene_id)
    ) is not None:
        raise LLMAccountingError(
            "LLM_ACCOUNTING_SCENE_RESERVATION_CORRUPT",
            "scene reservation is smaller than the amount being released",
        )
    if result.rowcount not in {0, 1}:
        raise LLMAccountingError(
            "LLM_ACCOUNTING_SCENE_RESERVATION_CORRUPT",
            "scene reservation release affected an unexpected number of rows",
        )


def _settle_scene_usage(
    session: Session,
    scene_id: str | None,
    *,
    reserved_tokens: int,
    actual_tokens: int,
    usage_exceeds_reservation: bool,
) -> None:
    if scene_id is None:
        return
    values: dict[str, Any] = {
        "scene_tokens_reserved": SceneRunState.scene_tokens_reserved - reserved_tokens,
        "scene_tokens_used": SceneRunState.scene_tokens_used + actual_tokens,
    }
    if usage_exceeds_reservation:
        values["run_execution_status"] = "usage_exceeds_reservation"
    result = session.execute(
        update(SceneRunState)
        .where(
            SceneRunState.scene_id == scene_id,
            SceneRunState.scene_tokens_reserved >= reserved_tokens,
        )
        .values(**values)
        .execution_options(synchronize_session=False)
    )
    if result.rowcount == 0 and session.scalar(
        select(SceneRunState.scene_id).where(SceneRunState.scene_id == scene_id)
    ) is not None:
        raise LLMAccountingError(
            "LLM_ACCOUNTING_SCENE_SETTLEMENT_CORRUPT",
            "scene reservation is smaller than the amount being settled",
        )
    if result.rowcount not in {0, 1}:
        raise LLMAccountingError(
            "LLM_ACCOUNTING_SCENE_SETTLEMENT_CORRUPT",
            "scene settlement affected an unexpected number of rows",
        )


def execute_accounted_call(
    session: Session,
    client: object,
    request: LLMRequest,
    context: LLMCallContext,
    *,
    llm_call_id: str | None = None,
    _lifecycle_observer: Callable[[str, str], None] | None = None,
) -> LLMResponse:
    """Execute the single production provider boundary and durably account it."""

    # Pending business state is the prerequisite for the call and must survive
    # any later provider or post-processing failure.
    session.commit()
    call_id = llm_call_id or f"llmcall_{uuid.uuid4().hex}"
    request_estimate = estimate_request_usage(request)
    _begin_claim_transaction(session)
    if context.execution_id and context.execution_step_key:
        existing_step_calls = list(
            session.scalars(
                select(LlmCall)
                .where(
                    LlmCall.execution_id == context.execution_id,
                    LlmCall.execution_step_key == context.execution_step_key,
                )
                .order_by(LlmCall.created_at)
            )
        )
        for existing_call in existing_step_calls:
            if (
                existing_call.accounting_status in {"released", "rejected"}
                and existing_call.request_dispatched_at is None
            ):
                continue
            session.rollback()
            raise _execution_step_conflict(existing_call)
    if session.get(LlmCall, call_id) is not None:
        session.rollback()
        raise LLMAccountingError(
            "LLM_ACCOUNTING_CALL_EXISTS",
            f"llm call {call_id} already exists",
        )
    parent = LlmCall(
        llm_call_id=call_id,
        provider=request.provider,
        provider_id=request.provider_id,
        account_id=request.account_id,
        model=request.model,
        node_id=context.node_id,
        reasoning_level=request.reasoning_level,
        credential_mode=request.credential_mode,
        prompt_hash=_prompt_hash(request),
        step=context.step,
        project_id=context.project_id,
        scene_id=context.scene_id,
        chapter_id=context.chapter_id,
        request_payload_summary=_request_summary(request),
        scope_type=context.scope_type,
        scope_id=context.scope_id,
        run_job_id=context.run_job_id,
        execution_id=context.execution_id,
        execution_step_key=context.execution_step_key,
        estimated_tokens=0,
        reserved_tokens=0,
        budget_charged_tokens=0,
        usage_is_estimate=True,
        accounting_status="reserved",
    )
    session.add(parent)
    session.commit()

    hook = _LedgerAttemptHook(
        session,
        call_id=call_id,
        context=context,
        lifecycle_observer=_lifecycle_observer,
    )
    started_at = time.perf_counter()
    try:
        if isinstance(client, LLMClient):
            response = client.generate(request, accounting_hook=hook)
        else:
            response = client.generate(request)  # type: ignore[attr-defined]
        response = replace(response, llm_call_id=call_id)

        if hook.attempt_count == 0:
            _settle_without_physical_attempt(
                session,
                call_id=call_id,
                request=request,
                response=response,
                request_estimate=request_estimate,
            )
        _finalize_parent_success(
            session,
            call_id=call_id,
            response=response,
            latency_ms=_elapsed_ms(started_at),
        )
        return response
    except Exception as exc:
        _finalize_parent_failure(
            session,
            call_id=call_id,
            request_estimate=request_estimate,
            error=exc,
            latency_ms=_elapsed_ms(started_at),
        )
        raise


class _LedgerAttemptHook:
    def __init__(
        self,
        session: Session,
        *,
        call_id: str,
        context: LLMCallContext,
        lifecycle_observer: Callable[[str, str], None] | None = None,
    ) -> None:
        self._session = session
        self._call_id = call_id
        self._context = context
        self._lifecycle_observer = lifecycle_observer
        self.attempt_count = 0

    def before_dispatch(self, *, request: LLMRequest, dispatch_kind: LLMDispatchKind) -> object:
        estimate = estimate_request_usage(request)
        ordinal = self.attempt_count
        attempt_id = f"llmattempt_{uuid.uuid4().hex}"
        scene_tracked = _reserve_scene_capacity(
            self._session,
            self._context.scene_id,
            estimate.reserved_tokens,
        )

        attempt = LlmCallAttempt(
            attempt_id=attempt_id,
            llm_call_id=self._call_id,
            provider_attempt_no=ordinal,
            dispatch_kind=dispatch_kind,
            request_max_output_tokens=request.max_output_tokens,
            estimated_tokens=estimate.estimated_tokens,
            reserved_tokens=estimate.reserved_tokens,
            budget_charged_tokens=0,
            usage_is_estimate=True,
            accounting_status="reserved",
        )
        self._session.add(attempt)
        parent = self._session.get(LlmCall, self._call_id)
        assert parent is not None
        parent.estimated_tokens += estimate.estimated_tokens
        parent.reserved_tokens += estimate.reserved_tokens
        self._session.commit()  # reservation transaction
        self._observe("reservation_committed", attempt_id)

        if scene_tracked and not _consume_scene_provider_attempt(
            self._session,
            self._context.scene_id,
        ):
            self._session.rollback()
            gate_error = _scene_gate_error(
                self._session,
                str(self._context.scene_id),
                reserved_tokens=0,
            ) or LLMAccountingRejected(
                "LLM_PROVIDER_ATTEMPT_BUDGET_EXHAUSTED",
                "provider attempt claim failed before dispatch",
            )
            _release_scene_reservation(
                self._session,
                self._context.scene_id,
                estimate.reserved_tokens,
            )
            attempt = self._session.get(LlmCallAttempt, attempt_id)
            assert attempt is not None
            attempt.accounting_status = "rejected"
            attempt.settled_at = utcnow()
            attempt.error_code = gate_error.code
            attempt.error_text = str(gate_error)
            _aggregate_parent(self._session, self._call_id)
            self._session.commit()
            raise gate_error

        dispatched_at = utcnow()
        attempt = self._session.get(LlmCallAttempt, attempt_id)
        assert attempt is not None
        attempt.request_dispatched_at = dispatched_at
        parent = self._session.get(LlmCall, self._call_id)
        assert parent is not None
        parent.request_dispatched_at = parent.request_dispatched_at or dispatched_at
        self._session.commit()  # dispatch transaction, immediately before POST
        self._observe("dispatch_committed", attempt_id)
        self.attempt_count += 1
        return attempt_id

    def after_response(
        self,
        handle: object,
        *,
        request: LLMRequest,
        response: LLMResponse,
        latency_ms: int,
    ) -> None:
        usage = normalize_response_usage(response, request)
        self._settle_attempt(
            str(handle),
            usage=usage,
            provider_request_id=response.request_id,
            latency_ms=latency_ms,
            error_code=None,
            error_text=None,
            succeeded=True,
        )

    def after_error(
        self,
        handle: object,
        *,
        request: LLMRequest,
        error: BaseException,
        raw_response: dict[str, Any] | None,
        provider_request_id: str | None,
        latency_ms: int,
    ) -> None:
        usage = _usage_for_failed_attempt(request, raw_response)
        self._settle_attempt(
            str(handle),
            usage=usage,
            provider_request_id=provider_request_id,
            latency_ms=latency_ms,
            error_code=getattr(error, "code", error.__class__.__name__),
            error_text=str(error),
            succeeded=False,
        )

    def _observe(self, stage: str, attempt_id: str) -> None:
        if self._lifecycle_observer is not None:
            self._lifecycle_observer(stage, attempt_id)

    def _settle_attempt(
        self,
        attempt_id: str,
        *,
        usage: NormalizedUsage,
        provider_request_id: str | None,
        latency_ms: int,
        error_code: str | None,
        error_text: str | None,
        succeeded: bool,
    ) -> None:
        attempt = self._session.get(LlmCallAttempt, attempt_id)
        assert attempt is not None
        charged = min(usage.total_tokens, attempt.reserved_tokens)
        exceeds = usage.total_tokens > attempt.reserved_tokens
        attempt.provider_request_id = provider_request_id
        attempt.prompt_tokens = usage.prompt_tokens
        attempt.completion_tokens = usage.completion_tokens
        attempt.total_tokens = usage.total_tokens
        attempt.budget_charged_tokens = charged
        attempt.usage_is_estimate = usage.usage_is_estimate
        attempt.accounting_status = (
            "usage_exceeds_reservation" if exceeds else ("settled" if succeeded else "failed")
        )
        attempt.settled_at = utcnow()
        attempt.latency_ms = max(0, latency_ms)
        attempt.error_code = error_code
        attempt.error_text = error_text
        _settle_scene_usage(
            self._session,
            self._context.scene_id,
            reserved_tokens=attempt.reserved_tokens,
            actual_tokens=usage.total_tokens,
            usage_exceeds_reservation=exceeds,
        )
        _aggregate_parent(self._session, self._call_id)
        self._session.commit()


def _settle_without_physical_attempt(
    session: Session,
    *,
    call_id: str,
    request: LLMRequest,
    response: LLMResponse,
    request_estimate: RequestUsageEstimate,
) -> None:
    usage = normalize_response_usage(response, request)
    parent = session.get(LlmCall, call_id)
    assert parent is not None
    parent.prompt_tokens = usage.prompt_tokens
    parent.completion_tokens = usage.completion_tokens
    parent.total_tokens = usage.total_tokens
    parent.estimated_tokens = 0 if response.provider == "offline_deterministic" else request_estimate.estimated_tokens
    parent.reserved_tokens = 0 if response.provider == "offline_deterministic" else max(
        request_estimate.reserved_tokens,
        usage.total_tokens,
    )
    parent.budget_charged_tokens = usage.total_tokens
    parent.usage_is_estimate = usage.usage_is_estimate
    session.commit()


def _aggregate_parent(session: Session, call_id: str) -> None:
    parent = session.get(LlmCall, call_id)
    assert parent is not None
    attempts = list(
        session.scalars(
            select(LlmCallAttempt)
            .where(LlmCallAttempt.llm_call_id == call_id)
            .order_by(LlmCallAttempt.provider_attempt_no)
        )
    )
    parent.estimated_tokens = sum(row.estimated_tokens for row in attempts)
    parent.reserved_tokens = sum(row.reserved_tokens for row in attempts)
    parent.budget_charged_tokens = sum(row.budget_charged_tokens for row in attempts)
    parent.prompt_tokens = sum(row.prompt_tokens for row in attempts)
    parent.completion_tokens = sum(row.completion_tokens for row in attempts)
    parent.total_tokens = sum(row.total_tokens for row in attempts)
    parent.latency_ms = sum(row.latency_ms for row in attempts)
    parent.usage_is_estimate = any(row.usage_is_estimate for row in attempts)


def _usage_overage_tokens(session: Session, call_id: str) -> int:
    return sum(
        max(0, total_tokens - reserved_tokens)
        for total_tokens, reserved_tokens in session.execute(
            select(LlmCallAttempt.total_tokens, LlmCallAttempt.reserved_tokens).where(
                LlmCallAttempt.llm_call_id == call_id
            )
        )
    )


def _finalize_parent_success(
    session: Session,
    *,
    call_id: str,
    response: LLMResponse,
    latency_ms: int,
) -> None:
    parent = session.get(LlmCall, call_id)
    assert parent is not None
    parent.provider = response.provider
    parent.model = response.model
    parent.native_reasoning_json = response.native_reasoning
    usage_overage_tokens = _usage_overage_tokens(session, call_id)
    parent.response_payload_summary = {
        "request_id": response.request_id,
        "finish_reason": response.finish_reason,
        "text_chars": len(response.text),
        "usage_present": response.usage_present,
        "usage_complete": response.usage_complete,
        "usage_overage_tokens": usage_overage_tokens,
    }
    parent.finish_reason = response.finish_reason
    parent.latency_ms = max(parent.latency_ms or 0, latency_ms)
    parent.settled_at = utcnow()
    parent.accounting_status = (
        "usage_exceeds_reservation"
        if _has_exceeded_attempt(session, call_id)
        else "settled"
    )
    session.commit()


def _finalize_parent_failure(
    session: Session,
    *,
    call_id: str,
    request_estimate: RequestUsageEstimate,
    error: BaseException,
    latency_ms: int,
) -> None:
    session.rollback()
    parent = session.get(LlmCall, call_id)
    if parent is None:
        return
    _settle_open_attempts_for_failure(
        session,
        parent=parent,
        error=error,
    )
    attempts = list(session.scalars(select(LlmCallAttempt).where(LlmCallAttempt.llm_call_id == call_id)))
    rejected_before_dispatch = isinstance(error, LLMAccountingRejected) and not any(
        attempt.request_dispatched_at is not None for attempt in attempts
    )
    if attempts:
        _aggregate_parent(session, call_id)
    elif rejected_before_dispatch:
        parent.estimated_tokens = 0
        parent.reserved_tokens = 0
        parent.budget_charged_tokens = 0
        parent.prompt_tokens = 0
        parent.completion_tokens = 0
        parent.total_tokens = 0
        parent.usage_is_estimate = True
    else:
        parent.estimated_tokens = request_estimate.estimated_tokens
        parent.reserved_tokens = request_estimate.reserved_tokens
        parent.budget_charged_tokens = min(
            request_estimate.estimated_tokens,
            request_estimate.reserved_tokens,
        )
        parent.prompt_tokens = request_estimate.estimated_input_tokens
        parent.completion_tokens = request_estimate.estimated_output_tokens
        parent.total_tokens = request_estimate.estimated_tokens
        parent.usage_is_estimate = True
    parent.error_code = getattr(error, "code", error.__class__.__name__)
    parent.latency_ms = max(parent.latency_ms or 0, latency_ms)
    parent.settled_at = utcnow()
    usage_overage_tokens = _usage_overage_tokens(session, call_id)
    if usage_overage_tokens:
        summary = dict(parent.response_payload_summary or {})
        summary["usage_overage_tokens"] = usage_overage_tokens
        parent.response_payload_summary = summary
        parent.accounting_status = "usage_exceeds_reservation"
    else:
        parent.accounting_status = "rejected" if rejected_before_dispatch else "failed"
    session.commit()


def _settle_open_attempts_for_failure(
    session: Session,
    *,
    parent: LlmCall,
    error: BaseException,
) -> None:
    open_attempts = list(
        session.scalars(
            select(LlmCallAttempt).where(
                LlmCallAttempt.llm_call_id == parent.llm_call_id,
                LlmCallAttempt.accounting_status == "reserved",
            )
        )
    )
    for attempt in open_attempts:
        if attempt.request_dispatched_at is None:
            attempt.accounting_status = "released"
            attempt.settled_at = utcnow()
            _release_scene_reservation(session, parent.scene_id, attempt.reserved_tokens)
            continue
        completion_tokens = min(attempt.request_max_output_tokens, attempt.estimated_tokens)
        attempt.prompt_tokens = max(0, attempt.estimated_tokens - completion_tokens)
        attempt.completion_tokens = completion_tokens
        attempt.total_tokens = attempt.estimated_tokens
        attempt.budget_charged_tokens = min(attempt.estimated_tokens, attempt.reserved_tokens)
        attempt.usage_is_estimate = True
        attempt.accounting_status = "failed"
        attempt.error_code = getattr(error, "code", error.__class__.__name__)
        attempt.error_text = str(error)
        attempt.settled_at = utcnow()
        _settle_scene_usage(
            session,
            parent.scene_id,
            reserved_tokens=attempt.reserved_tokens,
            actual_tokens=attempt.estimated_tokens,
            usage_exceeds_reservation=False,
        )


def mark_postprocess_failure(
    session: Session,
    llm_call_id: str,
    *,
    error_code: str,
    error_text: str | None = None,
) -> None:
    """Mark caller-side parsing/validation failure on the existing parent row."""

    parent = session.get(LlmCall, llm_call_id)
    if parent is None:
        raise KeyError(f"unknown llm call {llm_call_id}")
    usage_overage_tokens = _usage_overage_tokens(session, llm_call_id)
    parent.accounting_status = (
        "usage_exceeds_reservation" if usage_overage_tokens else "failed"
    )
    parent.error_code = error_code
    summary = dict(parent.response_payload_summary or {})
    if usage_overage_tokens:
        summary["usage_overage_tokens"] = usage_overage_tokens
    if error_text:
        summary["postprocess_error"] = error_text
    parent.response_payload_summary = summary
    parent.settled_at = parent.settled_at or utcnow()
    session.commit()


def recover_incomplete_call(session: Session, llm_call_id: str) -> AccountingRecoveryResult:
    """Resolve a call left ``reserved`` by process interruption.

    An undispatched reservation is free to release.  Once dispatch was durably
    recorded, provider outcome is unknowable, so recovery charges the estimate
    and blocks automatic resend.
    """

    session.commit()
    parent = session.get(LlmCall, llm_call_id)
    if parent is None:
        raise KeyError(f"unknown llm call {llm_call_id}")
    attempts = list(
        session.scalars(
            select(LlmCallAttempt)
            .where(LlmCallAttempt.llm_call_id == llm_call_id)
            .order_by(LlmCallAttempt.provider_attempt_no)
        )
    )
    if parent.accounting_status != "reserved":
        raise LLMAccountingError(
            "LLM_ACCOUNTING_CALL_NOT_RECOVERABLE",
            f"llm call {llm_call_id} is already {parent.accounting_status}",
        )

    dispatched = any(attempt.request_dispatched_at is not None for attempt in attempts)
    if not dispatched:
        for attempt in attempts:
            if attempt.accounting_status != "reserved":
                continue
            attempt.accounting_status = "released"
            attempt.budget_charged_tokens = 0
            attempt.settled_at = utcnow()
            _release_scene_reservation(session, parent.scene_id, attempt.reserved_tokens)
        _aggregate_parent(session, llm_call_id)
        parent.accounting_status = "released"
        parent.error_code = None
        parent.settled_at = utcnow()
        session.commit()
        return AccountingRecoveryResult(status="released", error_code=None, may_retry=True)

    for attempt in attempts:
        if attempt.accounting_status != "reserved":
            continue
        if attempt.request_dispatched_at is None:
            attempt.accounting_status = "released"
            attempt.budget_charged_tokens = 0
            attempt.settled_at = utcnow()
            _release_scene_reservation(session, parent.scene_id, attempt.reserved_tokens)
            continue
        charged = min(attempt.estimated_tokens, attempt.reserved_tokens)
        completion_tokens = min(attempt.request_max_output_tokens, attempt.estimated_tokens)
        attempt.prompt_tokens = max(0, attempt.estimated_tokens - completion_tokens)
        attempt.completion_tokens = completion_tokens
        attempt.total_tokens = attempt.estimated_tokens
        attempt.budget_charged_tokens = charged
        attempt.usage_is_estimate = True
        attempt.accounting_status = "failed"
        attempt.error_code = "RUN_CHECKPOINT_OUTPUT_MISSING"
        attempt.error_text = "provider request was dispatched but no durable output checkpoint exists"
        attempt.settled_at = utcnow()
        _settle_scene_usage(
            session,
            parent.scene_id,
            reserved_tokens=attempt.reserved_tokens,
            actual_tokens=attempt.estimated_tokens,
            usage_exceeds_reservation=False,
        )

    _aggregate_parent(session, llm_call_id)
    parent.accounting_status = "failed"
    parent.error_code = "RUN_CHECKPOINT_OUTPUT_MISSING"
    parent.settled_at = utcnow()
    session.commit()
    return AccountingRecoveryResult(
        status="failed",
        error_code="RUN_CHECKPOINT_OUTPUT_MISSING",
        may_retry=False,
    )


def _usage_for_failed_attempt(
    request: LLMRequest,
    raw_response: dict[str, Any] | None,
) -> NormalizedUsage:
    raw_usage = _extract_raw_usage(raw_response)
    actual = _normalize_raw_usage(raw_usage)
    if actual is not None:
        return actual
    estimate = estimate_request_usage(request)
    return NormalizedUsage(
        prompt_tokens=estimate.estimated_input_tokens,
        completion_tokens=estimate.estimated_output_tokens,
        total_tokens=estimate.estimated_tokens,
        usage_is_estimate=True,
    )


def _normalize_raw_usage(raw_usage: dict[str, Any] | None) -> NormalizedUsage | None:
    if raw_usage is None:
        return None
    key_sets = (
        ("input_tokens", "output_tokens", "total_tokens"),
        ("prompt_tokens", "completion_tokens", "total_tokens"),
        ("promptTokenCount", "candidatesTokenCount", "totalTokenCount"),
        ("prompt_eval_count", "eval_count", None),
    )
    for prompt_key, completion_key, total_key in key_sets:
        if prompt_key not in raw_usage and completion_key not in raw_usage:
            continue
        prompt = _usage_int(raw_usage.get(prompt_key))
        completion = _usage_int(raw_usage.get(completion_key))
        if prompt is None or completion is None:
            return None
        expected_total = prompt + completion
        if total_key is not None and total_key in raw_usage:
            total = _usage_int(raw_usage.get(total_key))
            if total is None or total != expected_total:
                return None
        return NormalizedUsage(prompt, completion, expected_total, False)
    return None


def _usage_int(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if value < 0 or int(value) != value:
        return None
    return int(value)


def _extract_raw_usage(body: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(body, dict):
        return None
    for key in ("usage", "usageMetadata"):
        value = body.get(key)
        if isinstance(value, dict):
            return dict(value)
    if "prompt_eval_count" in body or "eval_count" in body:
        return {
            key: body.get(key)
            for key in ("prompt_eval_count", "eval_count")
            if key in body
        }
    return None


def _is_explicit_zero_usage(usage: dict[str, Any]) -> bool:
    return usage == {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}


def _has_exceeded_attempt(session: Session, call_id: str) -> bool:
    return session.scalar(
        select(LlmCallAttempt.attempt_id)
        .where(
            LlmCallAttempt.llm_call_id == call_id,
            LlmCallAttempt.accounting_status == "usage_exceeds_reservation",
        )
        .limit(1)
    ) is not None


def _prompt_hash(request: LLMRequest) -> str:
    canonical = json.dumps(request.messages, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _request_summary(request: LLMRequest) -> dict[str, Any]:
    return {
        "message_count": len(request.messages),
        "message_chars": sum(len(str(message.get("content") or "")) for message in request.messages),
        "max_output_tokens": request.max_output_tokens,
        "response_format": request.response_format,
        "api_mode": request.api_mode,
    }


def _elapsed_ms(started_at: float) -> int:
    return max(0, int((time.perf_counter() - started_at) * 1000))
