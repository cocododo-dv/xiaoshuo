from __future__ import annotations

import logging
import math
import time
import uuid
from contextvars import ContextVar, Token
from dataclasses import dataclass
from typing import Any, Callable

from sqlalchemy.orm import Session

from novel_system.db.models import ChapterGoal, LlmCall, SceneCard, StoryProject, utcnow
from novel_system.services.context_budget import finalize_request_budget
from novel_system.services.llm_accounting import (
    LLMAccountingRejected,
    LLMCallContext,
    execute_accounted_call,
)
from novel_system.services.llm_client import (
    MAX_DEGRADE_HOPS,
    MAX_RETRY_BACKOFF_SECONDS,
    LLMClient,
    LLMRequest,
    LLMResponse,
    OnlineAccountedExecution,
    load_model_routing_config,
)
from novel_system.services.llm_node_registry import llm_node_route_fallbacks
from novel_system.services.system_config import load_llm_provider_runtime_configs
from novel_system.settings import get_settings


_LOGGER = logging.getLogger(__name__)

@dataclass(frozen=True, slots=True)
class _LLMExecutionRuntime:
    execution_id: str
    lease_renewer: Callable[..., Any] | None


_CURRENT_EXECUTION: ContextVar[_LLMExecutionRuntime | None] = ContextVar("llm_execution", default=None)


def begin_llm_execution(
    execution_id: str,
    *,
    lease_renewer: Callable[..., Any] | None = None,
) -> Token[_LLMExecutionRuntime | None]:
    return _CURRENT_EXECUTION.set(
        _LLMExecutionRuntime(execution_id=execution_id, lease_renewer=lease_renewer)
    )


def end_llm_execution(token: Token[_LLMExecutionRuntime | None]) -> None:
    _CURRENT_EXECUTION.reset(token)


def current_llm_execution_id() -> str | None:
    runtime = _CURRENT_EXECUTION.get()
    return runtime.execution_id if runtime is not None else None


def _execution_owner_lease_seconds(
    *,
    request_timeout_seconds: float | None,
    client: object | None = None,
) -> int:
    from novel_system.services.idempotency import owner_lease_grace_seconds, owner_lease_ttl_seconds

    default_ttl = owner_lease_ttl_seconds()
    if request_timeout_seconds is None:
        return default_ttl
    timeout_seconds = max(1, math.ceil(float(request_timeout_seconds)))
    physical_attempts = 1
    backoff_envelope = 0
    if isinstance(client, LLMClient):
        attempts_per_hop = max(1, int(client._max_retries) + 1)
        degrade_hops = MAX_DEGRADE_HOPS + 1
        physical_attempts = attempts_per_hop * degrade_hops
        if client._retry_backoff_seconds > 0:
            # Retry-After and jitter can dominate the configured exponential delay.
            # Reserve the capped upper bound for every retry in every degrade hop.
            backoff_envelope = math.ceil(
                degrade_hops
                * max(0, attempts_per_hop - 1)
                * MAX_RETRY_BACKOFF_SECONDS
                * 1.2
            )
    envelope = (
        physical_attempts * timeout_seconds
        + backoff_envelope
        + owner_lease_grace_seconds()
    )
    return max(default_ttl, envelope)


def _renew_execution_owner(
    *,
    request_timeout_seconds: float | None = None,
    client: object | None = None,
) -> bool:
    runtime = _CURRENT_EXECUTION.get()
    if runtime is None or runtime.lease_renewer is None:
        return False
    lease_seconds = _execution_owner_lease_seconds(
        request_timeout_seconds=request_timeout_seconds,
        client=client,
    )
    runtime.lease_renewer(lease_seconds=lease_seconds)
    return True

# 审计 P-15：llm_calls 审计载荷的单段文本上限。完整 prompt 由 prompt_hash 留痕、
# 生成正文由 SceneDraft/FinalScene 行持有——审计行只需可读证据，不承担全文存储。
AUDIT_TEXT_CAP = 4000

CONTINUITY_BUDGET_ERROR_CODE = "CONTINUITY_BUDGET_EXCEEDED"
CONTINUITY_BUDGET_MESSAGE = "Prompt still exceeds the safe continuity budget after deterministic compaction."
SCENE_SPLIT_RECOMMENDATION = "Split the scene and retry generation with a smaller continuity scope."
NODE_ROUTE_FALLBACKS: dict[str, tuple[str, ...]] = llm_node_route_fallbacks()

# Advisory ad-hoc passes (run_task) borrow an existing *registered* route instead of a
# dedicated node, so they never pollute active node_routing nor trip the sync-activation
# guard (which would reject a routeless pseudo-node with a missing provider_id). The
# borrowed node sits in the same provider/model tier as the conceptual task.
_AD_HOC_ROUTE_ALIASES: dict[str, str] = {
    "auto_critique_llm": "soft_qc",          # §8 independent LLM editor critic
    "narrative_event_extract": "extraction",  # §2 prose event extraction
}


@dataclass(slots=True)
class LLMNodeResult:
    llm_call_id: str
    request: LLMRequest
    response: LLMResponse
    request_summary: dict[str, Any]


class LLMNodeExecutionError(Exception):
    def __init__(
        self,
        *,
        llm_call_id: str,
        error_code: str,
        message: str,
        request_summary: dict[str, Any],
        response_summary: dict[str, Any],
        original_error: Exception | None = None,
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.llm_call_id = llm_call_id
        self.error_code = error_code
        self.message = message
        self.request_summary = request_summary
        self.response_summary = response_summary
        self.original_error = original_error
        self.retryable = retryable


class LLMNodeContinuityError(LLMNodeExecutionError):
    def __init__(
        self,
        *,
        llm_call_id: str,
        request_summary: dict[str, Any],
        response_summary: dict[str, Any],
        continuity_warning: dict[str, Any],
    ) -> None:
        super().__init__(
            llm_call_id=llm_call_id,
            error_code=CONTINUITY_BUDGET_ERROR_CODE,
            message=CONTINUITY_BUDGET_MESSAGE,
            request_summary=request_summary,
            response_summary=response_summary,
            retryable=False,
        )
        self.continuity_warning = continuity_warning


class LLMNodeRunner:
    def __init__(
        self,
        session: Session,
        *,
        llm_client: Any | None = None,
        routing_config: Any | None = None,
        settings: Any | None = None,
    ) -> None:
        self.session = session
        self.settings = settings or get_settings()
        self._llm_client = llm_client
        self._routing_config = routing_config
        self._provider_configs: dict[str, Any] | None = None
        self._accounting_lifecycle_observer: Callable[[str, str], None] | None = None

    def run(
        self,
        *,
        scene_id: str,
        chapter_id: str,
        bundle_id: str,
        bundle_hash: str,
        node_id: str,
        step: str,
        prompt: dict[str, Any],
        user_prompt: str,
        offline_client_factory: Callable[[], Any],
        source_draft_row_id: str | None = None,
        source_draft_content: str | None = None,
        temperature_override: float | None = None,
        execution_step_key: str | None = None,
    ) -> LLMNodeResult:
        llm_call_id = f"llm_call_{scene_id}_{uuid.uuid4().hex[:12]}"
        started_at = time.perf_counter()
        task_config: Any | None = None
        request: LLMRequest | None = None
        request_summary: dict[str, Any] = {}
        dispatch_started = False
        accounted_execution = False

        try:
            try:
                task_config = self.task_config(node_id)
            except KeyError as exc:
                # 不论 llm_enabled 与否都给统一的引导错误:离线模式缺路由同样是
                # 配置缺口;旧的裸 KeyError 审计行(error_code="KeyError")对排障无用,
                # 且运行时配置读取瞬时失败时会被误判为离线而落入该分支。
                request_summary = {
                    "node_id": node_id,
                    "template_name": _template_name(prompt, node_id),
                    "template_version": _template_version(prompt),
                    "bundle_id": bundle_id,
                    "bundle_hash": bundle_hash,
                    "source_draft_row_id": source_draft_row_id,
                    "recommended_action": "Configure this node in System Config > LLM node routes, or run sync-missing.",
                }
                response_summary = {
                    "message": f"LLM node route is not configured: {node_id}",
                    "node_id": node_id,
                    "error_code": "LLM_ROUTE_NOT_CONFIGURED",
                    "retryable": False,
                    "recommended_action": "Open System Config > LLM and sync missing active node routes.",
                }
                self._persist_call(
                    llm_call_id=llm_call_id,
                    scene_id=scene_id,
                    chapter_id=chapter_id,
                    step=step,
                    request=None,
                    task_config=None,
                    prompt=prompt,
                    request_summary=request_summary,
                    response_summary=response_summary,
                    started_at=started_at,
                    error_code="LLM_ROUTE_NOT_CONFIGURED",
                    execution_step_key=execution_step_key,
                )
                raise LLMNodeExecutionError(
                    llm_call_id=llm_call_id,
                    error_code="LLM_ROUTE_NOT_CONFIGURED",
                    message=f"LLM node route is not configured: {node_id}",
                    request_summary=request_summary,
                    response_summary=response_summary,
                    original_error=exc,
                    retryable=False,
                ) from exc
            request = self._build_request(prompt, user_prompt=user_prompt, node_id=node_id, task_config=task_config, temperature_override=temperature_override)
            final_budget = finalize_request_budget(
                system_prompt=request.messages[0]["content"],
                user_prompt=request.messages[1]["content"],
                base_budget=prompt["token_budget"],
            )
            request_summary = self._request_summary(
                prompt=prompt,
                request=request,
                task_config=task_config,
                final_budget=final_budget,
                bundle_id=bundle_id,
                bundle_hash=bundle_hash,
                source_draft_row_id=source_draft_row_id,
                source_draft_content=source_draft_content,
            )
            continuity_warning = final_budget["continuity_warning"]
            if _requires_scene_split(continuity_warning):
                response_summary = {
                    "message": CONTINUITY_BUDGET_MESSAGE,
                    "continuity_warning": continuity_warning,
                    "recommended_action": SCENE_SPLIT_RECOMMENDATION,
                    "attempt_count": 0,
                    "max_retries": 0,
                    "retryable": False,
                    "details": {"continuity_warning": continuity_warning},
                }
                self._persist_call(
                    llm_call_id=llm_call_id,
                    scene_id=scene_id,
                    chapter_id=chapter_id,
                    step=step,
                    request=request,
                    task_config=task_config,
                    prompt=prompt,
                    request_summary=request_summary,
                    response_summary=response_summary,
                    started_at=started_at,
                    error_code=CONTINUITY_BUDGET_ERROR_CODE,
                    execution_step_key=execution_step_key,
                )
                raise LLMNodeContinuityError(
                    llm_call_id=llm_call_id,
                    request_summary=request_summary,
                    response_summary=response_summary,
                    continuity_warning=continuity_warning,
                )

            client = self._client(offline_client_factory=offline_client_factory)
            runtime = _CURRENT_EXECUTION.get()
            accounted_execution = runtime is not None and (
                self.settings.llm_enabled or isinstance(client, OnlineAccountedExecution)
            )
            accounted_context = (
                self._durable_online_context(
                    runtime=runtime,
                    scene_id=scene_id,
                    chapter_id=chapter_id,
                    node_id=node_id,
                    step=step,
                    execution_step_key=execution_step_key or step,
                )
                if accounted_execution
                else None
            )
            _renew_execution_owner(
                request_timeout_seconds=request.timeout_seconds or self.settings.llm_timeout_seconds,
                client=client,
            )
            # Provider I/O must never hold an open database transaction. The owner
            # renewal above is fenced and committed before dispatch.
            self.session.commit()
            try:
                if accounted_context is not None:
                    response = execute_accounted_call(
                        self.session,
                        client,
                        request,
                        accounted_context,
                        llm_call_id=llm_call_id,
                        _lifecycle_observer=self._accounting_lifecycle_observer,
                    )
                else:
                    dispatch_started = True
                    response = client.generate(request)
            finally:
                _renew_execution_owner()
                self.session.commit()
        except LLMNodeExecutionError:
            raise
        except Exception as exc:
            error_code = getattr(exc, "code", exc.__class__.__name__)
            response_summary = _error_summary(exc)
            if accounted_execution:
                details = getattr(exc, "details", None)
                if isinstance(details, dict) and details.get("llm_call_id"):
                    llm_call_id = str(details["llm_call_id"])
            else:
                self._persist_call(
                    llm_call_id=llm_call_id,
                    scene_id=scene_id,
                    chapter_id=chapter_id,
                    step=step,
                    request=request,
                    task_config=task_config,
                    prompt=prompt,
                    request_summary=request_summary,
                    response_summary=response_summary,
                    started_at=started_at,
                    error_code=error_code,
                    execution_step_key=execution_step_key,
                    dispatch_started=dispatch_started,
                )
            raise LLMNodeExecutionError(
                llm_call_id=llm_call_id,
                error_code=error_code,
                message=str(exc),
                request_summary=request_summary,
                response_summary=response_summary,
                original_error=exc,
                retryable=bool(getattr(exc, "retryable", False)),
            ) from exc

        response_summary = {
            "request_id": response.request_id,
            "response_format": response.response_format,
            # 生成正文的权威存储是 SceneDraft/FinalScene；审计行内的结构化输出做有界截断
            "structured_output": _truncate_audit_payload(response.structured_output),
            "attempt_count": response.attempt_count,
            "max_retries": response.max_retries,
            "retryable": response.retryable,
        }
        if accounted_execution:
            llm_call_id = response.llm_call_id or llm_call_id
            self._supplement_accounted_audit(
                llm_call_id,
                request_summary=request_summary,
                response_summary=response_summary,
            )
        else:
            self._persist_call(
                llm_call_id=llm_call_id,
                scene_id=scene_id,
                chapter_id=chapter_id,
                step=step,
                request=request,
                task_config=task_config,
                prompt=prompt,
                request_summary=request_summary,
                response_summary=response_summary,
                started_at=started_at,
                error_code=None,
                response=response,
                execution_step_key=execution_step_key,
                dispatch_started=dispatch_started,
            )
        return LLMNodeResult(
            llm_call_id=llm_call_id,
            request=request,
            response=response,
            request_summary=request_summary,
        )

    def run_task(
        self,
        *,
        task_name: str,
        prompt_text: str,
        system_prompt: str,
        temperature_override: float | None = None,
    ) -> LLMResponse:
        """Ad-hoc single-shot LLM call for auxiliary advisory passes (§8 LLM critic,
        §2 prose event extraction).

        Unlike ``run``, this is NOT persisted as a scene draft and never blocks the
        pipeline: callers must opt-in (guard on settings) and wrap the call so that any
        raised exception degrades to a no-op. The offline factory is intentionally
        unavailable — a misconfigured/disabled call fails fast into the caller's
        try/except rather than silently returning stub text.
        """
        route_node = _AD_HOC_ROUTE_ALIASES.get(task_name, task_name)
        task_config = self.task_config(route_node)
        prompt = {"system_prompt": system_prompt, "token_budget": {}}
        request = self._build_request(
            prompt,
            user_prompt=prompt_text,
            node_id=route_node,
            task_config=task_config,
            temperature_override=temperature_override,
        )

        def _offline_unavailable() -> Any:
            raise RuntimeError("run_task requires an enabled LLM client (advisory pass)")

        client = self._client(offline_client_factory=_offline_unavailable)
        _renew_execution_owner(
            request_timeout_seconds=request.timeout_seconds or self.settings.llm_timeout_seconds,
            client=client,
        )
        self.session.commit()
        try:
            return client.generate(request)
        finally:
            _renew_execution_owner()
            self.session.commit()

    def task_config(self, node_id: str) -> Any:
        routing = self._routing()
        node_routing = getattr(routing, "node_routing", None)
        if isinstance(node_routing, dict) and node_id in node_routing:
            return node_routing[node_id]
        task_routing = getattr(routing, "task_routing", {})
        if node_id in task_routing:
            return task_routing[node_id]
        if self.settings.llm_enabled:
            raise KeyError(node_id)
        if node_id in {"style_draft", "style_patch"} and "stylize" in task_routing:
            return task_routing["stylize"]
        for fallback_node_id in NODE_ROUTE_FALLBACKS.get(node_id, ()):
            if isinstance(node_routing, dict) and fallback_node_id in node_routing:
                return node_routing[fallback_node_id]
            if fallback_node_id in task_routing:
                return task_routing[fallback_node_id]
        raise KeyError(node_id)

    def _routing(self) -> Any:
        if self._routing_config is None:
            self._routing_config = load_model_routing_config()
        return self._routing_config

    @staticmethod
    def _build_request(
        prompt: dict[str, Any],
        *,
        user_prompt: str,
        node_id: str,
        task_config: Any,
        temperature_override: float | None = None,
    ) -> LLMRequest:
        return LLMRequest(
            model=task_config.model,
            messages=[
                {"role": "system", "content": prompt["system_prompt"]},
                {"role": "user", "content": user_prompt},
            ],
            temperature=temperature_override if temperature_override is not None else task_config.temperature,
            max_output_tokens=task_config.max_output_tokens,
            response_format=task_config.response_format,
            provider=task_config.provider,
            timeout_seconds=getattr(task_config, "timeout_seconds", None),
            node_id=node_id,
            provider_id=getattr(task_config, "provider_id", None),
            account_id=getattr(task_config, "account_id", None),
            reasoning_level=getattr(task_config, "reasoning_level", "medium"),
            response_schema=_response_schema(prompt, node_id=node_id),
            api_mode=getattr(task_config, "api_mode", "responses"),
            credential_mode=getattr(task_config, "credential_mode", None),
            provider_options=getattr(task_config, "provider_options", {}),
            # §7 anti-mean sampling — read decoding-level penalties from task routing config
            frequency_penalty=getattr(task_config, "frequency_penalty", None),
            presence_penalty=getattr(task_config, "presence_penalty", None),
            top_p=getattr(task_config, "top_p", None),
        )

    @staticmethod
    def _request_summary(
        *,
        prompt: dict[str, Any],
        request: LLMRequest,
        task_config: Any,
        final_budget: dict[str, Any],
        bundle_id: str,
        bundle_hash: str,
        source_draft_row_id: str | None,
        source_draft_content: str | None,
    ) -> dict[str, Any]:
        summary = {
            "template_name": _template_name(prompt, request.node_id or "llm_node"),
            "template_version": _template_version(prompt),
            "messages": [
                {**message, "content": _truncate_audit_text(message.get("content"))}
                for message in request.messages
            ],
            "temperature": request.temperature,
            "max_output_tokens": request.max_output_tokens,
            "response_format": request.response_format,
            "provider": request.provider,
            "provider_id": request.provider_id,
            "account_id": request.account_id,
            "model_profile": getattr(task_config, "model_profile", None),
            "reasoning_level": request.reasoning_level,
            "credential_mode": request.credential_mode,
            "token_budget": final_budget["budget"],
            "continuity_warning": final_budget["continuity_warning"],
            "bundle_id": bundle_id,
            "bundle_hash": bundle_hash,
        }
        if source_draft_row_id is not None:
            summary["source_draft_row_id"] = source_draft_row_id
        if source_draft_content is not None:
            # 全文由 SceneDraft 行持有（row_id 已在上一键留痕），审计行只存有界摘录
            summary["source_draft_content"] = _truncate_audit_text(source_draft_content)
        return summary

    def _client(self, *, offline_client_factory: Callable[[], Any]) -> Any:
        if self._llm_client is not None:
            return self._llm_client
        if not self.settings.llm_enabled:
            return offline_client_factory()
        return LLMClient(
            provider=self.settings.llm_provider,
            base_url=self.settings.llm_base_url,
            api_key=self.settings.llm_api_key,
            timeout_seconds=self.settings.llm_timeout_seconds,
            retry_backoff_seconds=self._retry_backoff_seconds(),
            provider_configs=self._runtime_provider_configs(),
        )

    def _durable_online_context(
        self,
        *,
        runtime: _LLMExecutionRuntime,
        scene_id: str,
        chapter_id: str,
        node_id: str,
        step: str,
        execution_step_key: str,
    ) -> LLMCallContext:
        def reject(field: str, message: str) -> None:
            raise LLMAccountingRejected(
                "LLM_ACCOUNTING_CONTEXT_INVALID",
                message,
                details={"missing_or_invalid_field": field},
            )

        if not str(runtime.execution_id).strip():
            reject("execution_id", "durable online execution requires a stable execution id")
        if not str(scene_id).strip():
            reject("scene_id", "durable online execution requires a scene id")
        if not str(step).strip() or not str(execution_step_key).strip():
            reject("execution_step_key", "durable online execution requires a stable step key")
        scene = self.session.get(SceneCard, scene_id)
        if scene is None:
            reject("scene_id", "durable online execution scene does not exist")
        resolved_chapter_id = scene.chapter_id
        if not str(resolved_chapter_id).strip() or chapter_id != resolved_chapter_id:
            reject("chapter_id", "durable online execution chapter does not match its scene")
        chapter = self.session.get(ChapterGoal, resolved_chapter_id)
        project_id = scene.project_id or (chapter.project_id if chapter is not None else None)
        if not str(project_id or "").strip():
            reject("project_id", "durable online execution requires a project-owned scene")
        return LLMCallContext(
            scope_type="scene",
            scope_id=scene.scene_id,
            project_id=project_id,
            scene_id=scene.scene_id,
            chapter_id=resolved_chapter_id,
            node_id=node_id,
            step=step,
            execution_id=runtime.execution_id,
            execution_step_key=execution_step_key,
            provider_execution_mode="online",
        )

    def _supplement_accounted_audit(
        self,
        llm_call_id: str,
        *,
        request_summary: dict[str, Any],
        response_summary: dict[str, Any],
    ) -> None:
        parent = self.session.get(LlmCall, llm_call_id)
        if parent is None:
            raise RuntimeError(f"accounted llm call {llm_call_id} disappeared after settlement")
        parent.request_payload_summary = {
            **dict(parent.request_payload_summary or {}),
            **request_summary,
        }
        parent.response_payload_summary = {
            **dict(parent.response_payload_summary or {}),
            **response_summary,
        }
        self.session.commit()

    def _retry_backoff_seconds(self) -> float:
        """生产默认 1.5s 指数退避;models 配置 job_runtime.llm_retry_backoff_seconds 可调。"""
        try:
            value = self._routing().job_runtime.get("llm_retry_backoff_seconds")
            if value is not None:
                return max(0.0, float(value))
        except Exception:
            pass
        return 1.5

    def _runtime_provider_configs(self) -> dict[str, Any]:
        if self._provider_configs is None:
            self._provider_configs = load_llm_provider_runtime_configs()
        return self._provider_configs

    def _persist_call(
        self,
        *,
        llm_call_id: str,
        scene_id: str,
        chapter_id: str,
        step: str,
        request: LLMRequest | None,
        task_config: Any | None,
        prompt: dict[str, Any],
        request_summary: dict[str, Any],
        response_summary: dict[str, Any],
        started_at: float,
        error_code: str | None,
        response: LLMResponse | None = None,
        execution_step_key: str | None = None,
        dispatch_started: bool = False,
    ) -> None:
        settled_at = utcnow()
        dispatched = dispatch_started or response is not None
        charged_tokens = (
            int(response.usage.get("total_tokens", 0) or 0)
            if response is not None and response.usage
            else 0
        )
        scope_type, scope_id = self._resolve_scope(
            scene_id=scene_id,
            chapter_id=chapter_id,
            node_id=getattr(request, "node_id", None) if request is not None else step,
        )
        self.session.add(
            LlmCall(
                llm_call_id=llm_call_id,
                scope_type=scope_type,
                scope_id=scope_id,
                provider=response.provider if response is not None else getattr(task_config, "provider", None),
                provider_id=getattr(request, "provider_id", None) if request is not None else getattr(task_config, "provider_id", None),
                account_id=getattr(request, "account_id", None) if request is not None else getattr(task_config, "account_id", None),
                model=response.model if response is not None else getattr(task_config, "model", None),
                node_id=getattr(request, "node_id", None) if request is not None else step,
                reasoning_level=getattr(request, "reasoning_level", None) if request is not None else getattr(task_config, "reasoning_level", None),
                native_reasoning_json=response.native_reasoning if response is not None else None,
                credential_mode=getattr(request, "credential_mode", None) if request is not None else getattr(task_config, "credential_mode", None),
                prompt_hash=prompt.get("prompt_hash") if isinstance(prompt, dict) else None,
                step=step,
                execution_id=(runtime.execution_id if (runtime := _CURRENT_EXECUTION.get()) is not None else None),
                execution_step_key=execution_step_key or step,
                scene_id=scene_id,
                chapter_id=chapter_id,
                estimated_tokens=charged_tokens,
                reserved_tokens=charged_tokens,
                budget_charged_tokens=charged_tokens,
                usage_is_estimate=False if response is not None else True,
                request_payload_summary=request_summary,
                response_payload_summary=response_summary,
                prompt_tokens=response.usage.get("input_tokens", 0) if response is not None else 0,
                completion_tokens=response.usage.get("output_tokens", 0) if response is not None else 0,
                total_tokens=response.usage.get("total_tokens", 0) if response is not None else 0,
                latency_ms=(
                    0
                    if error_code == CONTINUITY_BUDGET_ERROR_CODE and not dispatched
                    else int((time.perf_counter() - started_at) * 1000)
                ),
                finish_reason=response.finish_reason if response is not None else None,
                error_code=error_code,
                accounting_status=("settled" if response is not None else "failed" if dispatched else "rejected"),
                request_dispatched_at=settled_at if dispatched else None,
                settled_at=settled_at,
            )
        )
        # Wave 3（治理 §5.5/§5.8）：场景生命周期 token 结算——凡带 scene_id 且存在
        # 运行态行的调用（成功/失败）都累计入 scene_tokens_used；usage 缺失记 0。
        try:
            from novel_system.services.scene_budget import record_usage

            record_usage(
                self.session,
                scene_id,
                response.usage.get("total_tokens", 0) if response is not None and response.usage else 0,
            )
        except Exception:
            _LOGGER.warning("scene token accounting degraded for %s", scene_id, exc_info=True)
        self.session.flush()

    def _resolve_scope(
        self,
        *,
        scene_id: str,
        chapter_id: str,
        node_id: str,
    ) -> tuple[str, str]:
        if scene_id and self.session.get(SceneCard, scene_id) is not None:
            return "scene", scene_id
        if chapter_id and self.session.get(ChapterGoal, chapter_id) is not None:
            return "chapter", chapter_id
        project_candidates = [chapter_id]
        if scene_id.startswith("project_"):
            project_candidates.append(scene_id.removeprefix("project_"))
        else:
            project_candidates.append(scene_id)
        for project_id in project_candidates:
            if project_id and self.session.get(StoryProject, project_id) is not None:
                return "project", project_id
        return "system", node_id or "legacy"


def _truncate_audit_text(value: Any) -> Any:
    """审计 P-15：单段文本超上限则截断并加标记；非字符串原样返回。"""
    if isinstance(value, str) and len(value) > AUDIT_TEXT_CAP:
        return value[:AUDIT_TEXT_CAP] + f"…[audit truncated, total {len(value)} chars]"
    return value


def _truncate_audit_payload(payload: Any) -> Any:
    """对结构化输出的字符串值做有界截断（浅一层即可——scene_text 等都在顶层）。"""
    if isinstance(payload, dict):
        return {key: _truncate_audit_text(value) for key, value in payload.items()}
    return _truncate_audit_text(payload)


def _requires_scene_split(continuity_warning: Any) -> bool:
    return isinstance(continuity_warning, dict) and bool(continuity_warning.get("requires_scene_split"))


def _response_schema(prompt: dict[str, Any], *, node_id: str) -> dict[str, Any]:
    return {"name": _template_name(prompt, node_id), "schema": prompt.get("structured_schema", {})}


def _template_name(prompt: dict[str, Any], fallback: str) -> str:
    value = prompt.get("template_name")
    if isinstance(value, str) and value.strip():
        return value.strip()
    return fallback


def _template_version(prompt: dict[str, Any]) -> str:
    value = prompt.get("template_version")
    if isinstance(value, str) and value.strip():
        return value.strip()
    return "unknown"


def _error_summary(exc: Exception) -> dict[str, Any]:
    details = getattr(exc, "details", None)
    details = details if isinstance(details, dict) else {}
    retryable = bool(getattr(exc, "retryable", False))
    summary = {
        "message": str(exc),
        "details": details,
        "retryable": retryable,
    }
    if "attempt_count" in details:
        summary["attempt_count"] = details["attempt_count"]
    if "max_retries" in details:
        summary["max_retries"] = details["max_retries"]
    return summary
