from __future__ import annotations

import hashlib
import json
import re
import time
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from novel_system.db.models import AttemptTracker, LlmCall, SceneCard, SceneDraft, SceneRunState
from novel_system.services.context_budget import finalize_request_budget
from novel_system.services.errors import DomainError
from novel_system.services.hash_engine import canonical_json
from novel_system.services.llm_client import LLMClient, LLMRequest, LLMResponse, load_model_routing_config
from novel_system.services.system_config import load_llm_provider_runtime_configs
from novel_system.services.prompt_builder import PromptBuilder
from novel_system.settings import get_settings


@dataclass(slots=True)
class NeutralGenerationResult:
    row_id: str
    content: str
    llm_call_id: str
    bundle_id: str
    bundle_hash: str


@dataclass(slots=True)
class StyleGenerationResult:
    row_id: str
    content: str
    llm_call_id: str
    bundle_id: str
    bundle_hash: str


SCENE_SPLIT_RECOMMENDATION = "Split the scene and retry generation with a smaller continuity scope."
JSON_SCHEMA_INSTRUCTION = "Return JSON that matches the structured schema exactly."


def versioned_scene_artifact_id(prefix: str, scene_id: str, bundle: dict[str, Any]) -> str:
    bundle_id = str(bundle.get("bundle_id") or "")
    bundle_prefix = f"bundle_{scene_id}_"
    if bundle_id.startswith(bundle_prefix):
        return f"{prefix}_{scene_id}_{bundle_id[len(bundle_prefix):]}"
    if bundle_id == f"bundle_{scene_id}":
        return f"{prefix}_{scene_id}"
    bundle_hash = str(bundle.get("bundle_snapshot_hash") or "")
    suffix = bundle_hash[:12] if bundle_hash else hashlib.sha256(canonical_json(bundle).encode("utf-8")).hexdigest()[:12]
    return f"{prefix}_{scene_id}_{suffix}"


class OfflineNeutralClient:
    def generate(self, request: LLMRequest) -> LLMResponse:
        scene_id = _extract_scene_id(request)
        structured_output = {
            "scene_text": (
                f"Offline neutral draft for {scene_id}. The scene advances clearly, preserves continuity, "
                "and satisfies the compiled bundle constraints."
            ),
            "continuity_notes": ["offline deterministic fallback"],
        }
        return LLMResponse(
            request_id=f"offline_{scene_id}",
            provider="offline_deterministic",
            model=request.model,
            text=json.dumps(structured_output, ensure_ascii=False),
            structured_output=structured_output,
            response_format=request.response_format,
            raw_response={
                "id": f"offline_{scene_id}",
                "model": request.model,
                "usage": {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
                "finish_reason": "offline_fallback",
            },
            usage={"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
            finish_reason="offline_fallback",
        )


class OfflineStyleClient:
    def __init__(self, *, patch_mode: bool = False) -> None:
        self.patch_mode = patch_mode

    def generate(self, request: LLMRequest) -> LLMResponse:
        scene_id = _extract_scene_id(request)
        if self.patch_mode:
            scene_text = (
                f"Offline patched draft for {scene_id}. The prose keeps the approved facts and applies "
                "the requested micro-edits with a sharper cadence."
            )
            notes_key = "patch_notes"
        else:
            scene_text = (
                f"Offline style draft for {scene_id}. The prose keeps the approved facts while shifting "
                "into a more vivid, stylized cadence."
            )
            notes_key = "style_notes"
        structured_output = {
            "scene_text": scene_text,
            notes_key: ["offline deterministic fallback"],
        }
        return LLMResponse(
            request_id=f"offline_style_{scene_id}_{'patch' if self.patch_mode else 'draft'}",
            provider="offline_deterministic",
            model=request.model,
            text=json.dumps(structured_output, ensure_ascii=False),
            structured_output=structured_output,
            response_format=request.response_format,
            raw_response={
                "id": f"offline_style_{scene_id}_{'patch' if self.patch_mode else 'draft'}",
                "model": request.model,
                "usage": {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
                "finish_reason": "offline_fallback",
            },
            usage={"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
            finish_reason="offline_fallback",
        )


class SceneGenerationService:
    def __init__(self, session: Session, *, llm_client: Any | None = None) -> None:
        self.session = session
        self.settings = get_settings()
        self._llm_client = llm_client
        self._prompt_builder_instance: PromptBuilder | None = None
        self._routing_config_cache: Any | None = None

    def generate_neutral_draft(self, scene_id: str, bundle: dict[str, Any]) -> NeutralGenerationResult:
        scene = self.session.get(SceneCard, scene_id)
        state = self.session.get(SceneRunState, scene_id)
        llm_call_id = f"llm_call_{scene_id}_{uuid.uuid4().hex[:12]}"
        started_at = time.perf_counter()
        prompt: dict[str, Any] | None = None
        task_config: Any | None = None
        request_summary: dict[str, Any] = {}

        try:
            prompt = self._prompt_builder().build(bundle["snapshot"], "neutral_draft")
            task_config = self._task_config("neutral_draft")
            request = LLMRequest(
                model=task_config.model,
                messages=[
                    {"role": "system", "content": prompt["system_prompt"]},
                    {"role": "user", "content": prompt["user_prompt"]},
                ],
                temperature=task_config.temperature,
                max_output_tokens=task_config.max_output_tokens,
                response_format=task_config.response_format,
                provider=task_config.provider,
                node_id="neutral_draft",
                provider_id=getattr(task_config, "provider_id", None),
                account_id=getattr(task_config, "account_id", None),
                reasoning_level=getattr(task_config, "reasoning_level", "medium"),
                api_mode=getattr(task_config, "api_mode", "responses"),
                credential_mode=getattr(task_config, "credential_mode", None),
                provider_options=getattr(task_config, "provider_options", {}),
            )
            final_budget = finalize_request_budget(
                system_prompt=request.messages[0]["content"],
                user_prompt=request.messages[1]["content"],
                base_budget=prompt["token_budget"],
            )
            request_summary = {
                "template_name": prompt["template_name"],
                "template_version": prompt["template_version"],
                "messages": request.messages,
                "temperature": request.temperature,
                "max_output_tokens": request.max_output_tokens,
                "response_format": request.response_format,
                "provider": request.provider,
                "provider_id": request.provider_id,
                "account_id": request.account_id,
                "reasoning_level": request.reasoning_level,
                "credential_mode": request.credential_mode,
                "token_budget": final_budget["budget"],
                "continuity_warning": final_budget["continuity_warning"],
            }
            self._raise_if_scene_split_required(final_budget["continuity_warning"])
            response = self._client().generate(request)
            neutral_content = _extract_scene_text(response)
        except Exception as exc:
            self._persist_generation_failure(
                scene=scene,
                state=state,
                bundle=bundle,
                llm_call_id=llm_call_id,
                step="neutral_draft",
                started_at=started_at,
                task_config=task_config,
                prompt=prompt,
                request_summary=request_summary,
                exc=exc,
            )
            raise

        self.session.add(
            LlmCall(
                llm_call_id=llm_call_id,
                provider=response.provider,
                provider_id=request.provider_id,
                account_id=request.account_id,
                model=response.model,
                node_id=request.node_id,
                reasoning_level=request.reasoning_level,
                native_reasoning_json=response.native_reasoning,
                credential_mode=request.credential_mode,
                prompt_hash=prompt["prompt_hash"],
                step="neutral_draft",
                scene_id=scene_id,
                chapter_id=scene.chapter_id,
                request_payload_summary=request_summary,
                response_payload_summary={
                    "request_id": response.request_id,
                    "response_format": response.response_format,
                    "structured_output": response.structured_output,
                },
                prompt_tokens=response.usage.get("input_tokens", 0),
                completion_tokens=response.usage.get("output_tokens", 0),
                total_tokens=response.usage.get("total_tokens", 0),
                latency_ms=int((time.perf_counter() - started_at) * 1000),
                finish_reason=response.finish_reason,
                error_code=None,
            )
        )
        self.session.flush()

        neutral_row_id = versioned_scene_artifact_id("draft_neutral", scene_id, bundle)
        self.session.add(
            SceneDraft(
                row_id=neutral_row_id,
                scene_id=scene_id,
                chapter_id=scene.chapter_id,
                stage="neutral_draft",
                content=neutral_content,
                source_bundle_id=bundle["bundle_id"],
                source_bundle_hash=bundle["bundle_snapshot_hash"],
                generation_llm_call_id=llm_call_id,
            )
        )
        self.session.flush()

        self.session.add(
            AttemptTracker(
                scene_id=scene_id,
                chapter_id=scene.chapter_id,
                step="neutral_draft",
                status="completed",
                source_bundle_id=bundle["bundle_id"],
                details_json={"row_id": neutral_row_id},
            )
        )
        self.session.flush()

        state.current_neutral_draft_row_id = neutral_row_id
        state.current_bundle_id = bundle["bundle_id"]
        state.current_bundle_hash = bundle["bundle_snapshot_hash"]
        state.total_attempt_count += 1
        self.session.flush()

        return NeutralGenerationResult(
            row_id=neutral_row_id,
            content=neutral_content,
            llm_call_id=llm_call_id,
            bundle_id=bundle["bundle_id"],
            bundle_hash=bundle["bundle_snapshot_hash"],
        )

    def generate_style_draft(
        self,
        scene_id: str,
        bundle: dict[str, Any],
        *,
        neutral_draft_row_id: str,
        neutral_content: str,
    ) -> StyleGenerationResult:
        scene = self.session.get(SceneCard, scene_id)
        state = self.session.get(SceneRunState, scene_id)
        return self._run_style_generation(
            scene=scene,
            state=state,
            bundle=bundle,
            row_id=versioned_scene_artifact_id("draft_style", scene_id, bundle),
            stage="style_draft",
            llm_step="style_draft",
            neutral_content=neutral_content,
            source_label="Approved Neutral Draft",
            source_row_id=neutral_draft_row_id,
            extra_instruction="Apply the style prompt template without changing the approved facts.",
            source_draft_row_id=neutral_draft_row_id,
            source_draft_content=neutral_content,
            client_kind="style",
            attempt_details_extra={"source_neutral_draft_row_id": neutral_draft_row_id},
        )

    def generate_style_patch(
        self,
        scene_id: str,
        bundle: dict[str, Any],
        *,
        source_style_draft_row_id: str,
        source_style_content: str,
        rewrite_brief: list[str],
        source_qc_report_id: str,
    ) -> StyleGenerationResult:
        scene = self.session.get(SceneCard, scene_id)
        state = self.session.get(SceneRunState, scene_id)
        result = self._run_style_generation(
            scene=scene,
            state=state,
            bundle=bundle,
            row_id=versioned_scene_artifact_id("draft_style_patch", scene_id, bundle),
            stage="style_patch",
            llm_step="soft_patch",
            neutral_content=source_style_content,
            source_label="Current Style Draft",
            source_row_id=source_style_draft_row_id,
            extra_instruction="Apply only the controlled patch brief; do not rewrite the full scene.",
            patch_brief=rewrite_brief,
            source_draft_row_id=source_style_draft_row_id,
            source_draft_content=source_style_content,
            client_kind="patch",
            attempt_details_extra={
                "source_qc_report_id": source_qc_report_id,
                "source_style_draft_row_id": source_style_draft_row_id,
                "rewrite_brief": rewrite_brief,
            },
        )
        state.soft_patch_count += 1
        return result

    def _run_style_generation(
        self,
        *,
        scene: SceneCard,
        state: SceneRunState,
        bundle: dict[str, Any],
        row_id: str,
        stage: str,
        llm_step: str,
        neutral_content: str,
        source_label: str,
        source_row_id: str,
        extra_instruction: str,
        source_draft_row_id: str,
        source_draft_content: str,
        client_kind: str,
        patch_brief: list[str] | None = None,
        attempt_details_extra: dict[str, Any] | None = None,
    ) -> StyleGenerationResult:
        llm_call_id = f"llm_call_{scene.scene_id}_{uuid.uuid4().hex[:12]}"
        started_at = time.perf_counter()
        prompt: dict[str, Any] | None = None
        task_config: Any | None = None
        request: LLMRequest | None = None
        request_summary: dict[str, Any] = {}

        try:
            prompt = self._prompt_builder().build(bundle["snapshot"], "style_draft")
            request = self._build_style_request(
                prompt,
                neutral_content=neutral_content,
                source_label=source_label,
                source_row_id=source_row_id,
                extra_instruction=extra_instruction,
                patch_brief=patch_brief,
            )
            task_config = self._task_config("style_patch" if patch_brief else "style_draft")
            final_budget = finalize_request_budget(
                system_prompt=request.messages[0]["content"],
                user_prompt=request.messages[1]["content"],
                base_budget=prompt["token_budget"],
            )
            request_summary = {
                "template_name": prompt["template_name"],
                "template_version": prompt["template_version"],
                "messages": request.messages,
                "temperature": request.temperature,
                "max_output_tokens": request.max_output_tokens,
                "response_format": request.response_format,
                "provider": request.provider,
                "provider_id": request.provider_id,
                "account_id": request.account_id,
                "reasoning_level": request.reasoning_level,
                "credential_mode": request.credential_mode,
                "token_budget": final_budget["budget"],
                "continuity_warning": final_budget["continuity_warning"],
                "source_draft_row_id": source_draft_row_id,
                "source_draft_content": source_draft_content,
            }
            self._raise_if_scene_split_required(final_budget["continuity_warning"])
            response = self._client(kind=client_kind).generate(request)
            style_content = _extract_scene_text(response)
        except Exception as exc:
            self._persist_generation_failure(
                scene=scene,
                state=state,
                bundle=bundle,
                llm_call_id=llm_call_id,
                step=llm_step,
                started_at=started_at,
                task_config=task_config,
                prompt=prompt,
                request_summary=request_summary,
                exc=exc,
                source_draft_row_id=source_draft_row_id,
            )
            raise

        self.session.add(
            LlmCall(
                llm_call_id=llm_call_id,
                provider=response.provider,
                provider_id=request.provider_id,
                account_id=request.account_id,
                model=response.model,
                node_id=request.node_id,
                reasoning_level=request.reasoning_level,
                native_reasoning_json=response.native_reasoning,
                credential_mode=request.credential_mode,
                prompt_hash=prompt["prompt_hash"],
                step=llm_step,
                scene_id=scene.scene_id,
                chapter_id=scene.chapter_id,
                request_payload_summary=request_summary,
                response_payload_summary={
                    "request_id": response.request_id,
                    "response_format": response.response_format,
                    "structured_output": response.structured_output,
                },
                prompt_tokens=response.usage.get("input_tokens", 0),
                completion_tokens=response.usage.get("output_tokens", 0),
                total_tokens=response.usage.get("total_tokens", 0),
                latency_ms=int((time.perf_counter() - started_at) * 1000),
                finish_reason=response.finish_reason,
                error_code=None,
            )
        )
        self.session.flush()

        self.session.add(
            SceneDraft(
                row_id=row_id,
                scene_id=scene.scene_id,
                chapter_id=scene.chapter_id,
                stage=stage,
                content=style_content,
                source_bundle_id=bundle["bundle_id"],
                source_bundle_hash=bundle["bundle_snapshot_hash"],
                generation_llm_call_id=llm_call_id,
            )
        )
        self.session.flush()

        self.session.add(
            AttemptTracker(
                scene_id=scene.scene_id,
                chapter_id=scene.chapter_id,
                step=llm_step,
                status="completed",
                source_bundle_id=bundle["bundle_id"],
                details_json={
                    "row_id": row_id,
                    "llm_call_id": llm_call_id,
                    "source_draft_row_id": source_draft_row_id,
                    **(attempt_details_extra or {}),
                },
            )
        )
        self.session.flush()

        state.current_style_draft_row_id = row_id
        state.current_bundle_id = bundle["bundle_id"]
        state.current_bundle_hash = bundle["bundle_snapshot_hash"]
        self.session.flush()

        return StyleGenerationResult(
            row_id=row_id,
            content=style_content,
            llm_call_id=llm_call_id,
            bundle_id=bundle["bundle_id"],
            bundle_hash=bundle["bundle_snapshot_hash"],
        )

    def _build_style_request(
        self,
        prompt: dict[str, Any],
        *,
        neutral_content: str,
        source_label: str,
        source_row_id: str,
        extra_instruction: str,
        patch_brief: list[str] | None = None,
    ) -> LLMRequest:
        user_prompt = self._build_style_user_prompt(
            prompt["user_prompt"],
            neutral_content=neutral_content,
            source_label=source_label,
            source_row_id=source_row_id,
            extra_instruction=extra_instruction,
            patch_brief=patch_brief,
        )
        node_id = "style_patch" if patch_brief else "style_draft"
        task_config = self._task_config(node_id)
        return LLMRequest(
            model=task_config.model,
            messages=[
                {"role": "system", "content": prompt["system_prompt"]},
                {"role": "user", "content": user_prompt},
            ],
            temperature=task_config.temperature,
            max_output_tokens=task_config.max_output_tokens,
            response_format=task_config.response_format,
            provider=task_config.provider,
            node_id=node_id,
            provider_id=getattr(task_config, "provider_id", None),
            account_id=getattr(task_config, "account_id", None),
            reasoning_level=getattr(task_config, "reasoning_level", "medium"),
            api_mode=getattr(task_config, "api_mode", "responses"),
            credential_mode=getattr(task_config, "credential_mode", None),
            provider_options=getattr(task_config, "provider_options", {}),
        )

    @staticmethod
    def _build_style_user_prompt(
        base_prompt: str,
        *,
        neutral_content: str,
        source_label: str,
        source_row_id: str,
        extra_instruction: str,
        patch_brief: list[str] | None = None,
    ) -> str:
        prompt_parts = [
            base_prompt,
            "",
            f"## {source_label}",
            neutral_content,
            "",
            f"Source Draft Row ID: {source_row_id}",
            extra_instruction,
        ]
        if patch_brief:
            prompt_parts.extend(
                [
                    "",
                    "## Patch Brief",
                    "\n".join(f"- {item}" for item in patch_brief),
                ]
            )
        if JSON_SCHEMA_INSTRUCTION not in base_prompt:
            prompt_parts.extend(["", JSON_SCHEMA_INSTRUCTION])
        return "\n".join(prompt_parts).strip()

    @staticmethod
    def _raise_if_scene_split_required(continuity_warning: Any) -> None:
        if not isinstance(continuity_warning, dict) or not continuity_warning.get("requires_scene_split"):
            return
        raise DomainError(
            "CONTINUITY_BUDGET_EXCEEDED",
            "Prompt still exceeds the safe continuity budget after deterministic compaction.",
            status_code=409,
            details={
                "continuity_warning": continuity_warning,
                "recommended_action": SCENE_SPLIT_RECOMMENDATION,
            },
        )

    def _client(self, *, kind: str = "neutral") -> Any:
        if self._llm_client is not None:
            return self._llm_client
        if not self.settings.llm_enabled:
            if kind == "neutral":
                return OfflineNeutralClient()
            if kind == "patch":
                return OfflineStyleClient(patch_mode=True)
            return OfflineStyleClient()
        return LLMClient(
            provider=self.settings.llm_provider,
            base_url=self.settings.llm_base_url,
            api_key=self.settings.llm_api_key,
            timeout_seconds=self.settings.llm_timeout_seconds,
            provider_configs=load_llm_provider_runtime_configs(),
        )

    def _prompt_builder(self) -> PromptBuilder:
        if self._prompt_builder_instance is None:
            self._prompt_builder_instance = PromptBuilder()
        return self._prompt_builder_instance

    def _routing_config(self) -> Any:
        if self._routing_config_cache is None:
            self._routing_config_cache = load_model_routing_config()
        return self._routing_config_cache

    def _task_config(self, node_id: str) -> Any:
        routing = self._routing_config()
        node_routing = getattr(routing, "node_routing", None)
        if isinstance(node_routing, dict) and node_id in node_routing:
            return node_routing[node_id]
        task_routing = getattr(routing, "task_routing", {})
        if node_id in task_routing:
            return task_routing[node_id]
        if node_id in {"style_draft", "style_patch"} and "stylize" in task_routing:
            return task_routing["stylize"]
        raise KeyError(node_id)

    def _persist_generation_failure(
        self,
        *,
        scene: SceneCard,
        state: SceneRunState,
        bundle: dict[str, Any],
        llm_call_id: str,
        step: str,
        started_at: float,
        task_config: Any | None,
        prompt: dict[str, Any] | None,
        request_summary: dict[str, Any],
        exc: Exception,
        source_draft_row_id: str | None = None,
    ) -> None:
        error_code = getattr(exc, "code", exc.__class__.__name__)
        self.session.add(
            LlmCall(
                llm_call_id=llm_call_id,
                provider=getattr(task_config, "provider", None),
                provider_id=getattr(task_config, "provider_id", None),
                account_id=getattr(task_config, "account_id", None),
                model=getattr(task_config, "model", None),
                node_id=step,
                reasoning_level=getattr(task_config, "reasoning_level", None),
                native_reasoning_json=None,
                credential_mode=getattr(task_config, "credential_mode", None),
                prompt_hash=prompt["prompt_hash"] if prompt is not None else None,
                step=step,
                scene_id=scene.scene_id,
                chapter_id=scene.chapter_id,
                request_payload_summary=request_summary,
                response_payload_summary=_error_summary(exc),
                prompt_tokens=0,
                completion_tokens=0,
                total_tokens=0,
                latency_ms=int((time.perf_counter() - started_at) * 1000),
                finish_reason=None,
                error_code=error_code,
            )
        )
        self.session.flush()
        details_json: dict[str, Any] = {
            "llm_call_id": llm_call_id,
            "error_code": error_code,
            "message": str(exc),
        }
        if prompt is not None:
            details_json["template_name"] = prompt["template_name"]
            details_json["template_version"] = prompt["template_version"]
        if source_draft_row_id is not None:
            details_json["source_draft_row_id"] = source_draft_row_id
        self.session.add(
            AttemptTracker(
                scene_id=scene.scene_id,
                chapter_id=scene.chapter_id,
                step=step,
                status="failed",
                source_bundle_id=bundle["bundle_id"],
                details_json=details_json,
            )
        )
        state.current_bundle_id = bundle["bundle_id"]
        state.current_bundle_hash = bundle["bundle_snapshot_hash"]
        state.total_attempt_count += 1
        self.session.flush()


def _extract_scene_text(response: LLMResponse) -> str:
    structured_output = response.structured_output or {}
    scene_text = structured_output.get("scene_text")
    if isinstance(scene_text, str) and scene_text.strip():
        return scene_text.strip()
    raise ValueError("neutral_draft response missing scene_text")


def _extract_scene_id(request: LLMRequest) -> str:
    for message in request.messages:
        content = message.get("content", "")
        match = re.search(r"Scene ID:\s*([A-Za-z0-9_:-]+)", content)
        if match:
            return match.group(1)
    digest = hashlib.sha256(canonical_json({"messages": request.messages}).encode("utf-8")).hexdigest()
    return f"scene_{digest[:8]}"


def _error_summary(exc: Exception) -> dict[str, Any]:
    details = getattr(exc, "details", None)
    return {
        "message": str(exc),
        "details": details if isinstance(details, dict) else {},
    }
