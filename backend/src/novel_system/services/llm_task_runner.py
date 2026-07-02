from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from typing import Any, Callable

from sqlalchemy.orm import Session

from novel_system.db.models import LlmCall
from novel_system.services.context_budget import finalize_request_budget
from novel_system.services.llm_client import LLMClient, LLMRequest, LLMResponse, load_model_routing_config
from novel_system.services.llm_node_registry import llm_node_route_fallbacks
from novel_system.services.system_config import load_llm_provider_runtime_configs
from novel_system.settings import get_settings


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
    ) -> LLMNodeResult:
        llm_call_id = f"llm_call_{scene_id}_{uuid.uuid4().hex[:12]}"
        started_at = time.perf_counter()
        task_config: Any | None = None
        request: LLMRequest | None = None
        request_summary: dict[str, Any] = {}

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
                )
                raise LLMNodeContinuityError(
                    llm_call_id=llm_call_id,
                    request_summary=request_summary,
                    response_summary=response_summary,
                    continuity_warning=continuity_warning,
                )

            response = self._client(offline_client_factory=offline_client_factory).generate(request)
        except LLMNodeExecutionError:
            raise
        except Exception as exc:
            error_code = getattr(exc, "code", exc.__class__.__name__)
            response_summary = _error_summary(exc)
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

        return self._client(offline_client_factory=_offline_unavailable).generate(request)

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
    ) -> None:
        self.session.add(
            LlmCall(
                llm_call_id=llm_call_id,
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
                scene_id=scene_id,
                chapter_id=chapter_id,
                request_payload_summary=request_summary,
                response_payload_summary=response_summary,
                prompt_tokens=response.usage.get("input_tokens", 0) if response is not None else 0,
                completion_tokens=response.usage.get("output_tokens", 0) if response is not None else 0,
                total_tokens=response.usage.get("total_tokens", 0) if response is not None else 0,
                latency_ms=int((time.perf_counter() - started_at) * 1000),
                finish_reason=response.finish_reason if response is not None else None,
                error_code=error_code,
            )
        )
        self.session.flush()


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
