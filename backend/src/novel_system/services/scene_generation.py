from __future__ import annotations

import hashlib
import json
import logging
import re
import time
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from novel_system.db.models import AttemptTracker, LlmCall, SceneCard, SceneDraft, SceneRunState
from novel_system.services.errors import DomainError
from novel_system.services.hash_engine import canonical_json
from novel_system.services.literary_quality import DIMENSION_WEIGHTS, QUALITY_DIMENSIONS, analyze_literary_quality
from novel_system.services.llm_client import LLMRequest, LLMResponse
from novel_system.services.llm_task_runner import (
    CONTINUITY_BUDGET_ERROR_CODE,
    CONTINUITY_BUDGET_MESSAGE,
    SCENE_SPLIT_RECOMMENDATION,
    LLMNodeContinuityError,
    LLMNodeExecutionError,
    LLMNodeRunner,
)
from novel_system.services.prompt_builder import PromptBuilder
from novel_system.services.style_reference.injection import (
    InjectionService,
    ordered_character_ids,
)

_LOGGER = logging.getLogger(__name__)


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


JSON_SCHEMA_INSTRUCTION = "Return JSON that matches the structured schema exactly."
ANTI_TEMPLATE_GATE_DIMENSIONS = {
    "template_action_reuse",
    "image_field_reuse",
    "syntax_monotony",
    "false_clarity",
    "summary_ending",
    "expository_dialogue",
}


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
                f"Offline style draft for {scene_id}. The protagonist must choose between immediate disclosure "
                "and protecting someone at risk, pays a concrete cost by handing over leverage, and turns toward "
                "the next visible danger."
            )
            notes_key = "rewrite_notes" if request.node_id == "scene_literary_rewrite" else "style_notes"
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
    def __init__(
        self,
        session: Session,
        *,
        llm_client: Any | None = None,
        llm_runner: LLMNodeRunner | None = None,
    ) -> None:
        self.session = session
        self._llm_runner = llm_runner or LLMNodeRunner(session, llm_client=llm_client)
        self._prompt_builder_instance: PromptBuilder | None = None

    def generate_neutral_draft(self, scene_id: str, bundle: dict[str, Any]) -> NeutralGenerationResult:
        scene = self.session.get(SceneCard, scene_id)
        state = self.session.get(SceneRunState, scene_id)
        fallback_llm_call_id = f"llm_call_{scene_id}_{uuid.uuid4().hex[:12]}"
        started_at = time.perf_counter()
        prompt: dict[str, Any] | None = None

        try:
            prompt = self._prompt_builder().build(bundle["snapshot"], "neutral_draft")
        except Exception as exc:
            self._persist_generation_failure(
                scene=scene,
                state=state,
                bundle=bundle,
                llm_call_id=fallback_llm_call_id,
                step="neutral_draft",
                started_at=started_at,
                task_config=None,
                prompt=prompt,
                request_summary={},
                exc=exc,
            )
            raise

        prompt = self._inject_style_reference(prompt, scene, task_type="scene_generation")

        try:
            node_result = self._llm_runner.run(
                scene_id=scene_id,
                chapter_id=scene.chapter_id,
                bundle_id=bundle["bundle_id"],
                bundle_hash=bundle["bundle_snapshot_hash"],
                node_id="neutral_draft",
                step="neutral_draft",
                prompt=prompt,
                user_prompt=prompt["user_prompt"],
                offline_client_factory=OfflineNeutralClient,
            )
            response = node_result.response
            neutral_content = _extract_scene_text(response)
        except LLMNodeExecutionError as exc:
            self._record_runner_failure_attempt(
                scene=scene,
                state=state,
                bundle=bundle,
                step="neutral_draft",
                prompt=prompt,
                exc=exc,
            )
            self._raise_original_runner_error(exc)

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
                generation_llm_call_id=node_result.llm_call_id,
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
                details_json={"row_id": neutral_row_id, "llm_call_id": node_result.llm_call_id},
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
            llm_call_id=node_result.llm_call_id,
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

    def generate_near_final_rewrite(
        self,
        scene_id: str,
        bundle: dict[str, Any],
        *,
        source_draft_row_id: str,
        source_content: str,
        revision_brief: list[str],
        source_evaluation_id: str,
    ) -> StyleGenerationResult:
        scene = self.session.get(SceneCard, scene_id)
        state = self.session.get(SceneRunState, scene_id)
        return self._run_style_generation(
            scene=scene,
            state=state,
            bundle=bundle,
            row_id=versioned_scene_artifact_id("draft_near_final_rewrite", scene_id, bundle),
            stage="near_final_rewrite",
            llm_step="scene_literary_rewrite",
            neutral_content=source_content,
            source_label="Near-Final Draft Under Review",
            source_row_id=source_draft_row_id,
            extra_instruction=(
                "Rewrite the full scene under the same facts. Treat the brief below as a literary rewrite brief, "
                "not a local patch request."
            ),
            patch_brief=revision_brief,
            source_draft_row_id=source_draft_row_id,
            source_draft_content=source_content,
            client_kind="style",
            attempt_details_extra={
                "source_evaluation_id": source_evaluation_id,
                "source_style_draft_row_id": source_draft_row_id,
                "rewrite_brief": revision_brief,
            },
        )

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
        fallback_llm_call_id = f"llm_call_{scene.scene_id}_{uuid.uuid4().hex[:12]}"
        started_at = time.perf_counter()
        prompt: dict[str, Any] | None = None

        try:
            template_name = "scene_literary_rewrite" if llm_step == "scene_literary_rewrite" else "style_draft"
            prompt = self._prompt_builder().build(bundle["snapshot"], template_name)
        except Exception as exc:
            self._persist_generation_failure(
                scene=scene,
                state=state,
                bundle=bundle,
                llm_call_id=fallback_llm_call_id,
                step=llm_step,
                started_at=started_at,
                task_config=None,
                prompt=prompt,
                request_summary={},
                exc=exc,
                source_draft_row_id=source_draft_row_id,
            )
            raise

        prompt = self._inject_style_reference(prompt, scene, task_type="scene_generation")

        user_prompt = self._build_style_user_prompt(
            prompt["user_prompt"],
            neutral_content=neutral_content,
            source_label=source_label,
            source_row_id=source_row_id,
            extra_instruction=extra_instruction,
            patch_brief=patch_brief,
        )
        node_id = "style_patch" if llm_step == "soft_patch" else llm_step
        try:
            node_result = self._llm_runner.run(
                scene_id=scene.scene_id,
                chapter_id=scene.chapter_id,
                bundle_id=bundle["bundle_id"],
                bundle_hash=bundle["bundle_snapshot_hash"],
                node_id=node_id,
                step=llm_step,
                prompt=prompt,
                user_prompt=user_prompt,
                offline_client_factory=lambda: OfflineStyleClient(patch_mode=client_kind == "patch"),
                source_draft_row_id=source_draft_row_id,
                source_draft_content=source_draft_content,
            )
            style_content = _extract_scene_text(node_result.response)
        except LLMNodeExecutionError as exc:
            self._record_runner_failure_attempt(
                scene=scene,
                state=state,
                bundle=bundle,
                step=llm_step,
                prompt=prompt,
                exc=exc,
                source_draft_row_id=source_draft_row_id,
            )
            self._raise_original_runner_error(exc)

        self.session.add(
            SceneDraft(
                row_id=row_id,
                scene_id=scene.scene_id,
                chapter_id=scene.chapter_id,
                stage=stage,
                content=style_content,
                source_bundle_id=bundle["bundle_id"],
                source_bundle_hash=bundle["bundle_snapshot_hash"],
                generation_llm_call_id=node_result.llm_call_id,
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
                    "llm_call_id": node_result.llm_call_id,
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

        if stage == "style_draft":
            quality_gate = _anti_template_quality_gate(style_content, scene_id=scene.scene_id, chapter_id=scene.chapter_id)
            if quality_gate["triggered"]:
                de_template_result = self._run_de_template_pass(
                    scene=scene,
                    state=state,
                    bundle=bundle,
                    prompt=prompt,
                    source_row_id=row_id,
                    source_content=style_content,
                    quality_gate=quality_gate,
                )
                if de_template_result is not None:
                    return de_template_result

        return StyleGenerationResult(
            row_id=row_id,
            content=style_content,
            llm_call_id=node_result.llm_call_id,
            bundle_id=bundle["bundle_id"],
            bundle_hash=bundle["bundle_snapshot_hash"],
        )

    def _run_de_template_pass(
        self,
        *,
        scene: SceneCard,
        state: SceneRunState,
        bundle: dict[str, Any],
        prompt: dict[str, Any],
        source_row_id: str,
        source_content: str,
        quality_gate: dict[str, Any],
    ) -> StyleGenerationResult | None:
        row_id = versioned_scene_artifact_id("draft_style_de_template", scene.scene_id, bundle)
        user_prompt = self._build_style_user_prompt(
            prompt["user_prompt"],
            neutral_content=source_content,
            source_label="Style Draft Requiring De-template Pass",
            source_row_id=source_row_id,
            extra_instruction=(
                "Apply exactly one controlled de-template rewrite pass. Preserve facts, names, chronology, "
                "required objects, and ending function. Remove repeated gesture templates, false-clarity phrasing, "
                "summary endings, and exposition-first dialogue."
            ),
            patch_brief=_de_template_rewrite_brief(quality_gate),
            patch_heading="De-template Rewrite Brief",
        )
        try:
            node_result = self._llm_runner.run(
                scene_id=scene.scene_id,
                chapter_id=scene.chapter_id,
                bundle_id=bundle["bundle_id"],
                bundle_hash=bundle["bundle_snapshot_hash"],
                node_id="style_patch",
                step="de_template",
                prompt=prompt,
                user_prompt=user_prompt,
                offline_client_factory=lambda: OfflineStyleClient(patch_mode=True),
                source_draft_row_id=source_row_id,
                source_draft_content=source_content,
            )
            rewritten_content = _extract_scene_text(node_result.response)
        except LLMNodeExecutionError as exc:
            self._record_runner_failure_attempt(
                scene=scene,
                state=state,
                bundle=bundle,
                step="de_template",
                prompt=prompt,
                exc=exc,
                source_draft_row_id=source_row_id,
            )
            return None

        self.session.add(
            SceneDraft(
                row_id=row_id,
                scene_id=scene.scene_id,
                chapter_id=scene.chapter_id,
                stage="de_template",
                content=rewritten_content,
                source_bundle_id=bundle["bundle_id"],
                source_bundle_hash=bundle["bundle_snapshot_hash"],
                generation_llm_call_id=node_result.llm_call_id,
            )
        )
        self.session.flush()

        self.session.add(
            AttemptTracker(
                scene_id=scene.scene_id,
                chapter_id=scene.chapter_id,
                step="de_template",
                status="completed",
                source_bundle_id=bundle["bundle_id"],
                details_json={
                    "row_id": row_id,
                    "llm_call_id": node_result.llm_call_id,
                    "source_style_draft_row_id": source_row_id,
                    "quality_gate": quality_gate,
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
            content=rewritten_content,
            llm_call_id=node_result.llm_call_id,
            bundle_id=bundle["bundle_id"],
            bundle_hash=bundle["bundle_snapshot_hash"],
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
        patch_heading: str = "Patch Brief",
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
                    f"## {patch_heading}",
                    "\n".join(f"- {item}" for item in patch_brief),
                ]
            )
        if JSON_SCHEMA_INSTRUCTION not in base_prompt:
            prompt_parts.extend(["", JSON_SCHEMA_INSTRUCTION])
        return "\n".join(prompt_parts).strip()

    def _prompt_builder(self) -> PromptBuilder:
        if self._prompt_builder_instance is None:
            self._prompt_builder_instance = PromptBuilder()
        return self._prompt_builder_instance

    def _inject_style_reference(
        self,
        prompt: dict[str, Any] | None,
        scene: SceneCard | None,
        *,
        task_type: str = "scene_generation",
    ) -> dict[str, Any] | None:
        """PR-8 §5.1 — 把 active StyleProfile 注入到 prompt["system_prompt"] 头部。

        无 binding / project_id / profile 时 no-op;注入失败时 warn log 降级,
        不阻断 LLM 生成。
        """
        if prompt is None or scene is None:
            return prompt
        project_id = getattr(scene, "project_id", None)
        # PR-14/18 — character scope 用 pov ∪ onstage 匹配集(pov 优先)
        character_ids = ordered_character_ids(
            getattr(scene, "pov_character_id", None),
            getattr(scene, "onstage_chars_json", None),
        )
        # PR-15 — scene scope 用 scene_id 匹配(优先级最高)
        scene_id = getattr(scene, "scene_id", None)
        if not project_id and not character_ids and not scene_id:
            return prompt
        try:
            fragments = InjectionService(self.session).fragments_for(
                project_id, task_type, character_ids=character_ids, scene_id=scene_id,
            )
            prefix = fragments.to_system_prompt_prefix()
        except Exception as exc:  # noqa: BLE001
            _LOGGER.warning(
                "style_reference injection skipped for scene %s task %s: %s",
                scene.scene_id, task_type, exc,
            )
            return prompt
        if not prefix:
            return prompt
        injected = dict(prompt)
        injected["system_prompt"] = prefix + (prompt.get("system_prompt") or "")
        return injected

    def _record_runner_failure_attempt(
        self,
        *,
        scene: SceneCard,
        state: SceneRunState,
        bundle: dict[str, Any],
        step: str,
        prompt: dict[str, Any],
        exc: LLMNodeExecutionError,
        source_draft_row_id: str | None = None,
    ) -> None:
        details_json: dict[str, Any] = {
            "llm_call_id": exc.llm_call_id,
            "error_code": exc.error_code,
            "message": exc.message,
            "retryable": exc.retryable,
        }
        if prompt is not None:
            details_json["template_name"] = prompt.get("template_name")
            details_json["template_version"] = prompt.get("template_version")
        if source_draft_row_id is not None:
            details_json["source_draft_row_id"] = source_draft_row_id
        if isinstance(exc, LLMNodeContinuityError):
            details_json["continuity_warning"] = exc.continuity_warning
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

    @staticmethod
    def _raise_original_runner_error(exc: LLMNodeExecutionError) -> None:
        if isinstance(exc, LLMNodeContinuityError):
            raise DomainError(
                CONTINUITY_BUDGET_ERROR_CODE,
                CONTINUITY_BUDGET_MESSAGE,
                status_code=409,
                details={
                    "continuity_warning": exc.continuity_warning,
                    "recommended_action": SCENE_SPLIT_RECOMMENDATION,
                },
            ) from exc
        if exc.original_error is not None:
            raise exc.original_error
        raise exc

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
                prompt_hash=prompt.get("prompt_hash") if isinstance(prompt, dict) else None,
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
            details_json["template_name"] = prompt.get("template_name")
            details_json["template_version"] = prompt.get("template_version")
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


def _anti_template_quality_gate(text: str, *, scene_id: str, chapter_id: str) -> dict[str, Any]:
    signals, findings = analyze_literary_quality(text)
    score = round(sum(signals[dimension]["score"] * DIMENSION_WEIGHTS[dimension] for dimension in QUALITY_DIMENSIONS), 4)
    risky_findings = [
        {
            **finding,
            "quality_signal_id": f"quality:scene:{scene_id}:{finding.get('dimension')}",
            "scene_id": scene_id,
            "chapter_id": chapter_id,
        }
        for finding in findings
        if finding.get("dimension") in ANTI_TEMPLATE_GATE_DIMENSIONS
    ]
    triggered = bool(risky_findings)
    return {
        "triggered": triggered,
        "rewrite_pass": 1 if triggered else 0,
        "score": score,
        "risk_dimensions": [finding["dimension"] for finding in risky_findings],
        "quality_signal_ids": [finding["quality_signal_id"] for finding in risky_findings],
        "findings": risky_findings,
    }


def _de_template_rewrite_brief(quality_gate: dict[str, Any]) -> list[str]:
    brief = [
        "Run no more than this one de-template pass; do not add another rewrite loop.",
        "Keep the same plot facts, speaker identities, core choice, cost, and final hook.",
    ]
    for finding in quality_gate.get("findings", [])[:5]:
        signal_id = finding.get("quality_signal_id", "quality:unknown")
        issue = finding.get("issue") or "anti-template risk"
        evidence = finding.get("evidence_excerpt") or ""
        recommendation = finding.get("recommendation") or ""
        brief.append(f"{signal_id}: {issue}")
        if evidence:
            brief.append(f"Evidence: {evidence}")
        if recommendation:
            brief.append(f"Fix: {recommendation}")
    return brief


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
