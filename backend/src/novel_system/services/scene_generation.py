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
from novel_system.services.llm_node_registry import get_llm_node_spec
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

# §6.3 multi-strategy diversification prompts for low-dispersion retry
_DIVERSIFICATION_PROMPT = (
    "[DIVERSIFICATION] 前一轮生成的候选在表达上高度相似。请刻意尝试不同的叙述入口：\n"
    "换一种感官开场（如果之前用了视觉，试听觉或触觉）、\n"
    "换一种时间结构（如果之前是顺叙，试倒叙或插叙的片段）、\n"
    "换一种节奏（如果之前是长句铺陈，试短句切入）。\n"
    "保持场景spec的所有结构要求不变，只改变'怎么去'。\n\n"
)
# §6.3 style emphasis rotation prefixes — rotate which style dimension the LLM focuses on
_STYLE_EMPHASIS_ROTATION: list[str] = [
    (
        "[风格强调·禁忌优先] 本次生成请特别关注参考风格中的禁忌模式——"
        "绝对避开被标记为禁忌的表达方式,并让'不做什么'成为本次风格选择的首要约束。\n\n"
    ),
    (
        "[风格强调·节奏指标优先] 本次生成请严格对齐风格参考中的硬指标锚点——"
        "句长分布、感官词频率、对话比例等量化基线。让数字说话,节奏先行。\n\n"
    ),
]


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


def author_note_instruction(author_note: str | None) -> str:
    """FE-ALIGN G3：作者改写指令 → 风格生成提示词附加段（空 note 不产生任何变化）。"""
    note = str(author_note or "").strip()[:500]
    if not note:
        return ""
    return (
        "\n\n## Author Rewrite Instruction (highest priority, from the author)\n"
        f"{note}\n"
        "Apply this instruction while still honoring the approved facts and structure above."
    )


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

        prompt = self._inject_style_reference(prompt, scene, task_type="scene_generation", bundle=bundle)

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
        # 治理 §4.3：latest_valid 与 current_* 分轨——重写/失败路径清 current_* 时该指针保留
        state.latest_valid_draft_row_id = neutral_row_id
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
        author_note: str | None = None,
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
            extra_instruction=(
                "Apply the style prompt template without changing the approved facts."
                + author_note_instruction(author_note)
            ),
            source_draft_row_id=neutral_draft_row_id,
            source_draft_content=neutral_content,
            client_kind="style",
            attempt_details_extra={"source_neutral_draft_row_id": neutral_draft_row_id},
        )

    def generate_style_draft_candidates(
        self,
        scene_id: str,
        bundle: dict[str, Any],
        *,
        neutral_draft_row_id: str,
        neutral_content: str,
        author_note: str | None = None,
        n_candidates: int = 3,
    ) -> list[StyleGenerationResult]:
        """Generate N style-draft candidates sorted by adversarial quality (best first)."""
        from novel_system.services.literary_quality import adversarial_rank_score, get_dimension_weights

        scene = self.session.get(SceneCard, scene_id)
        state = self.session.get(SceneRunState, scene_id)

        # §6 dynamic quality weights — project-level style profile can shift
        # which adversarial dimensions matter most for this particular work.
        _project_weights = get_dimension_weights(
            scene.project_id, self.session,
        ) if scene and scene.project_id else None

        try:
            task_config = self._llm_runner.task_config("style_draft")
            base_temp = task_config.temperature
        except KeyError:
            base_temp = 0.7

        if n_candidates <= 1:
            temperatures = [base_temp]
        else:
            spread = 0.05
            temperatures = [
                round(base_temp + spread * (2 * i / (n_candidates - 1) - 1), 3)
                for i in range(n_candidates)
            ]
            temperatures = [max(0.0, min(2.0, t)) for t in temperatures]

        candidates: list[tuple[StyleGenerationResult, float]] = []
        for idx, temp in enumerate(temperatures):
            cand_row_id = versioned_scene_artifact_id("draft_style_cand", scene_id, bundle) + f"_{idx}"
            try:
                result = self._run_style_generation(
                    scene=scene,
                    state=state,
                    bundle=bundle,
                    row_id=cand_row_id,
                    stage="style_draft",
                    llm_step="style_draft",
                    neutral_content=neutral_content,
                    source_label="Approved Neutral Draft",
                    source_row_id=neutral_draft_row_id,
                    extra_instruction=(
                        "Apply the style prompt template without changing the approved facts."
                        + author_note_instruction(author_note)
                    ),
                    source_draft_row_id=neutral_draft_row_id,
                    source_draft_content=neutral_content,
                    client_kind="style",
                    temperature_override=temp,
                    attempt_details_extra={
                        "source_neutral_draft_row_id": neutral_draft_row_id,
                        "candidate_index": idx,
                        "temperature_override": temp,
                        "n_candidates": n_candidates,
                    },
                )
                score = adversarial_rank_score(result.content, weights=_project_weights)
                candidates.append((result, score))
            except (DomainError, LLMNodeExecutionError):
                _LOGGER.warning("candidate %d/%d failed for scene %s", idx + 1, n_candidates, scene_id)
                continue

        if not candidates:
            return [self.generate_style_draft(
                scene_id, bundle,
                neutral_draft_row_id=neutral_draft_row_id,
                neutral_content=neutral_content,
                author_note=author_note,
            )]

        candidates.sort(key=lambda pair: pair[1], reverse=True)

        if len(candidates) >= 2:
            dispersion = _candidate_dispersion([c.content for c, _ in candidates])
            _LOGGER.info(
                "best-of-N dispersion=%.3f for scene %s (%d candidates)",
                dispersion, scene_id, len(candidates),
            )
            if dispersion < 0.15:
                _LOGGER.warning(
                    "low candidate dispersion (%.3f) for scene %s — retrying with wider temperature spread (§6.3)",
                    dispersion, scene_id,
                )
                # §6.3: low dispersion means sampling didn't explore the tail — retry with +0.1 spread
                wider_spread = 0.15
                wider_temps = [
                    round(base_temp + wider_spread * (2 * i / (n_candidates - 1) - 1), 3)
                    for i in range(n_candidates)
                ]
                wider_temps = [max(0.0, min(2.0, t)) for t in wider_temps]
                retry_candidates: list[tuple[StyleGenerationResult, float]] = []
                for idx, temp in enumerate(wider_temps):
                    retry_row_id = versioned_scene_artifact_id("draft_style_cand", scene_id, bundle) + f"_retry_{idx}"
                    try:
                        result = self._run_style_generation(
                            scene=scene, state=state, bundle=bundle,
                            row_id=retry_row_id, stage="style_draft", llm_step="style_draft",
                            neutral_content=neutral_content, source_label="Approved Neutral Draft",
                            source_row_id=neutral_draft_row_id,
                            extra_instruction=(
                                "Apply the style prompt template without changing the approved facts."
                                + author_note_instruction(author_note)
                            ),
                            source_draft_row_id=neutral_draft_row_id,
                            source_draft_content=neutral_content,
                            client_kind="style", temperature_override=temp,
                            attempt_details_extra={
                                "source_neutral_draft_row_id": neutral_draft_row_id,
                                "candidate_index": idx, "temperature_override": temp,
                                "n_candidates": n_candidates, "dispersion_retry": True,
                            },
                        )
                        retry_candidates.append((result, adversarial_rank_score(result.content, weights=_project_weights)))
                    except (DomainError, LLMNodeExecutionError):
                        _LOGGER.warning("dispersion retry candidate %d failed for scene %s", idx, scene_id)
                if retry_candidates:
                    all_candidates = candidates + retry_candidates
                    all_candidates.sort(key=lambda pair: pair[1], reverse=True)
                    candidates = all_candidates
                    retry_dispersion = _candidate_dispersion([c.content for c, _ in candidates])
                    _LOGGER.info(
                        "post-retry dispersion=%.3f for scene %s (%d total candidates)",
                        retry_dispersion, scene_id, len(candidates),
                    )

                # §6.3 multi-strategy diversification: when temperature widening alone
                # doesn't break the attractor basin, apply prompt variation and style
                # emphasis rotation to generate 2 additional exploratory candidates.
                post_temp_dispersion = _candidate_dispersion([c.content for c, _ in candidates])
                if post_temp_dispersion < 0.15:
                    _LOGGER.warning(
                        "dispersion still low (%.3f) after temperature retry for scene %s "
                        "— applying multi-strategy diversification (§6.3 enhanced)",
                        post_temp_dispersion, scene_id,
                    )
                    diversify_candidates: list[tuple[StyleGenerationResult, float]] = []
                    # Strategy 1: prompt variation — inject a diversification instruction
                    # that nudges the LLM to explore different sensory openings, time
                    # structures, and rhythmic patterns.
                    div_row_id = (
                        versioned_scene_artifact_id("draft_style_cand", scene_id, bundle)
                        + "_div_prompt"
                    )
                    try:
                        result = self._run_style_generation(
                            scene=scene, state=state, bundle=bundle,
                            row_id=div_row_id, stage="style_draft", llm_step="style_draft",
                            neutral_content=neutral_content, source_label="Approved Neutral Draft",
                            source_row_id=neutral_draft_row_id,
                            extra_instruction=(
                                "Apply the style prompt template without changing the approved facts."
                                + author_note_instruction(author_note)
                            ),
                            source_draft_row_id=neutral_draft_row_id,
                            source_draft_content=neutral_content,
                            client_kind="style",
                            temperature_override=round(base_temp + 0.10, 3),
                            extra_system_prefix=_DIVERSIFICATION_PROMPT,
                            attempt_details_extra={
                                "source_neutral_draft_row_id": neutral_draft_row_id,
                                "candidate_index": "div_prompt",
                                "temperature_override": round(base_temp + 0.10, 3),
                                "n_candidates": n_candidates,
                                "diversification_strategy": "prompt_variation",
                            },
                        )
                        diversify_candidates.append((result, adversarial_rank_score(result.content, weights=_project_weights)))
                    except (DomainError, LLMNodeExecutionError):
                        _LOGGER.warning("prompt-variation candidate failed for scene %s", scene_id)

                    # Strategy 2: style emphasis rotation — if a style profile is bound,
                    # prepend an emphasis instruction that shifts the LLM's attention to a
                    # different style dimension (forbidden patterns or metric anchors)
                    # compared to the balanced default.
                    for rot_idx, emphasis_prefix in enumerate(_STYLE_EMPHASIS_ROTATION):
                        div_style_row_id = (
                            versioned_scene_artifact_id("draft_style_cand", scene_id, bundle)
                            + f"_div_style_{rot_idx}"
                        )
                        try:
                            result = self._run_style_generation(
                                scene=scene, state=state, bundle=bundle,
                                row_id=div_style_row_id, stage="style_draft", llm_step="style_draft",
                                neutral_content=neutral_content, source_label="Approved Neutral Draft",
                                source_row_id=neutral_draft_row_id,
                                extra_instruction=(
                                    "Apply the style prompt template without changing the approved facts."
                                    + author_note_instruction(author_note)
                                ),
                                source_draft_row_id=neutral_draft_row_id,
                                source_draft_content=neutral_content,
                                client_kind="style",
                                temperature_override=round(base_temp + 0.05 * (rot_idx + 1), 3),
                                extra_system_prefix=emphasis_prefix,
                                attempt_details_extra={
                                    "source_neutral_draft_row_id": neutral_draft_row_id,
                                    "candidate_index": f"div_style_{rot_idx}",
                                    "temperature_override": round(base_temp + 0.05 * (rot_idx + 1), 3),
                                    "n_candidates": n_candidates,
                                    "diversification_strategy": "style_emphasis_rotation",
                                    "emphasis_index": rot_idx,
                                },
                            )
                            diversify_candidates.append((result, adversarial_rank_score(result.content, weights=_project_weights)))
                        except (DomainError, LLMNodeExecutionError):
                            _LOGGER.warning(
                                "style-emphasis-rotation candidate %d failed for scene %s",
                                rot_idx, scene_id,
                            )

                    if diversify_candidates:
                        all_candidates = candidates + diversify_candidates
                        all_candidates.sort(key=lambda pair: pair[1], reverse=True)
                        candidates = all_candidates
                        final_div_dispersion = _candidate_dispersion([c.content for c, _ in candidates])
                        _LOGGER.info(
                            "post-diversification dispersion=%.3f for scene %s "
                            "(%d total candidates, %d from multi-strategy)",
                            final_div_dispersion, scene_id, len(candidates),
                            len(diversify_candidates),
                        )

        best_result = candidates[0][0]
        state.current_style_draft_row_id = best_result.row_id
        state.latest_valid_draft_row_id = best_result.row_id
        state.current_bundle_id = bundle["bundle_id"]
        state.current_bundle_hash = bundle["bundle_snapshot_hash"]
        # §6 Defect D: persist dispersion score for author-facing quality signal
        if len(candidates) >= 2:
            final_dispersion = _candidate_dispersion([c.content for c, _ in candidates])
            state.candidate_dispersion_score = round(final_dispersion, 4)
        self.session.flush()

        return [result for result, _ in candidates]

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

    def generate_long_form_continuation(
        self,
        scene_id: str,
        bundle: dict[str, Any],
        *,
        source_draft_row_id: str,
        source_content: str,
        target_continuation_chars: int,
    ) -> StyleGenerationResult:
        scene = self.session.get(SceneCard, scene_id)
        state = self.session.get(SceneRunState, scene_id)
        fallback_llm_call_id = f"llm_call_{scene_id}_{uuid.uuid4().hex[:12]}"
        started_at = time.perf_counter()
        prompt: dict[str, Any] | None = None

        try:
            prompt = self._prompt_builder().build(bundle["snapshot"], "long_form_continuation")
        except Exception as exc:
            self._persist_generation_failure(
                scene=scene,
                state=state,
                bundle=bundle,
                llm_call_id=fallback_llm_call_id,
                step="long_form_continuation",
                started_at=started_at,
                task_config=None,
                prompt=prompt,
                request_summary={},
                exc=exc,
                source_draft_row_id=source_draft_row_id,
            )
            raise

        node_spec = get_llm_node_spec("long_form_continuation")
        refresh_every_chars = int(getattr(node_spec, "refresh_every_chars", 0) or 0)
        target_chars = max(1, int(target_continuation_chars))
        segment_count = 1
        if refresh_every_chars > 0:
            segment_count = max(1, (target_chars + refresh_every_chars - 1) // refresh_every_chars)
        # 立项 C §12 — 首段注入用源稿尾部作 RAG query;后续每段按已生成正文刷新(防漂移)
        active_prompt = self._inject_style_reference(
            prompt, scene, task_type="long_form_continuation",
            context_text=(source_content or "")[-2000:],
        )
        continuation_parts: list[str] = []
        llm_call_ids: list[str] = []

        for segment_index in range(segment_count):
            existing_continuation = "".join(continuation_parts)
            user_prompt = self._build_long_form_continuation_user_prompt(
                active_prompt["user_prompt"],
                source_content=source_content,
                source_row_id=source_draft_row_id,
                existing_continuation=existing_continuation,
            )
            try:
                node_result = self._llm_runner.run(
                    scene_id=scene.scene_id,
                    chapter_id=scene.chapter_id,
                    bundle_id=bundle["bundle_id"],
                    bundle_hash=bundle["bundle_snapshot_hash"],
                    node_id="long_form_continuation",
                    step="long_form_continuation",
                    prompt=active_prompt,
                    user_prompt=user_prompt,
                    offline_client_factory=OfflineStyleClient,
                    source_draft_row_id=source_draft_row_id,
                    source_draft_content=(
                        f"{source_content}\n\n{existing_continuation}".strip()
                        if existing_continuation
                        else source_content
                    ),
                )
                continuation_parts.append(_extract_scene_text(node_result.response))
                llm_call_ids.append(node_result.llm_call_id)
            except LLMNodeExecutionError as exc:
                self._record_runner_failure_attempt(
                    scene=scene,
                    state=state,
                    bundle=bundle,
                    step="long_form_continuation",
                    prompt=active_prompt,
                    exc=exc,
                    source_draft_row_id=source_draft_row_id,
                )
                self._raise_original_runner_error(exc)
            if segment_index + 1 < segment_count:
                # 防漂移:用累计已生成正文尾部重做 RAG 召回 → 样例随上下文变化
                accumulated = "".join(continuation_parts)
                active_prompt = self._inject_style_reference(
                    prompt, scene, task_type="long_form_continuation",
                    context_text=(f"{source_content}\n{accumulated}".strip())[-2000:],
                )

        content = "".join(continuation_parts)
        row_id = versioned_scene_artifact_id("draft_long_form_continuation", scene_id, bundle)
        self.session.add(
            SceneDraft(
                row_id=row_id,
                scene_id=scene.scene_id,
                chapter_id=scene.chapter_id,
                stage="long_form_continuation",
                content=content,
                source_bundle_id=bundle["bundle_id"],
                source_bundle_hash=bundle["bundle_snapshot_hash"],
                generation_llm_call_id=llm_call_ids[-1] if llm_call_ids else None,
            )
        )
        self.session.flush()

        self.session.add(
            AttemptTracker(
                scene_id=scene.scene_id,
                chapter_id=scene.chapter_id,
                step="long_form_continuation",
                status="completed",
                source_bundle_id=bundle["bundle_id"],
                details_json={
                    "row_id": row_id,
                    "llm_call_id": llm_call_ids[-1] if llm_call_ids else None,
                    "segment_count": len(continuation_parts),
                    "llm_call_ids": llm_call_ids,
                    "source_draft_row_id": source_draft_row_id,
                    "refresh_every_chars": refresh_every_chars,
                    "target_continuation_chars": target_chars,
                },
            )
        )
        self.session.flush()

        state.current_style_draft_row_id = row_id
        state.latest_valid_draft_row_id = row_id
        state.current_bundle_id = bundle["bundle_id"]
        state.current_bundle_hash = bundle["bundle_snapshot_hash"]
        self.session.flush()

        return StyleGenerationResult(
            row_id=row_id,
            content=content,
            llm_call_id=llm_call_ids[-1] if llm_call_ids else "",
            bundle_id=bundle["bundle_id"],
            bundle_hash=bundle["bundle_snapshot_hash"],
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
        temperature_override: float | None = None,
        extra_system_prefix: str | None = None,
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

        prompt = self._inject_style_reference(prompt, scene, task_type="scene_generation", bundle=bundle)

        # §6.3 diversification: prepend caller-supplied system prefix (prompt variation / style emphasis)
        if extra_system_prefix and prompt is not None:
            injected = dict(prompt)
            injected["system_prompt"] = extra_system_prefix + (prompt.get("system_prompt") or "")
            prompt = injected

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
                temperature_override=temperature_override,
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
        state.latest_valid_draft_row_id = row_id
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
        # 每个触发去模板的候选（source_row_id 已带 _{idx}/_retry_{idx}）必须派生唯一的去模板稿 row_id，
        # 否则 Best-of-N 下 ≥2 个候选都触发反模板闸时，第二条 SceneDraft 撞主键 → IntegrityError → 整跑崩溃。
        # SceneDraft.row_id 为 opaque 主键、不被下游解析，故追加 source_row_id 的短哈希后缀即可（唯一且长度有界）。
        source_suffix = hashlib.sha1(source_row_id.encode("utf-8")).hexdigest()[:10]
        row_id = f"{versioned_scene_artifact_id('draft_style_de_template', scene.scene_id, bundle)}_{source_suffix}"
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
        state.latest_valid_draft_row_id = row_id
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

    @staticmethod
    def _build_long_form_continuation_user_prompt(
        base_prompt: str,
        *,
        source_content: str,
        source_row_id: str,
        existing_continuation: str,
    ) -> str:
        prompt_parts = [
            base_prompt,
            "",
            "## Source Draft",
            source_content,
            "",
            f"Source Draft Row ID: {source_row_id}",
            "Continue directly from the source draft without restarting the scene or summarizing prior beats.",
        ]
        if existing_continuation.strip():
            prompt_parts.extend(
                [
                    "",
                    "## Continuation Written So Far",
                    existing_continuation,
                    "Continue immediately after the text above. Do not repeat or paraphrase the same beats.",
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
        bundle: dict[str, Any] | None = None,
        context_text: str | None = None,
    ) -> dict[str, Any] | None:
        """PR-8 §5.1 — 把 active StyleProfile 注入到 prompt["system_prompt"] 头部。

        无 binding / project_id / profile 时 no-op;注入失败时 warn log 降级,
        不阻断 LLM 生成。

        立项 C §12 — ``context_text``(续写最新正文)透传给 Strategy C(RAG),
        作为三粒度检索 query;长文续写循环按 refresh 周期刷新此值 → 召回随上下文变化
        (防漂移)。其余策略忽略此参数。
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
            svc = InjectionService(self.session)
            # §9 Defect B: read drift_ptype_priority from bundle (set by bundle_builder
            # when drift guidance includes structured dimension data) so the few-shot
            # selection prioritizes exemplars relevant to drifted dimensions ("show > tell")
            if bundle and isinstance(bundle, dict):
                drift_priority = (bundle.get("inline_digests") or {}).get("_drift_ptype_priority")
                if drift_priority and isinstance(drift_priority, list):
                    svc.drift_ptype_priority = drift_priority
            # 立项 C — RAG 检索 query 来源(续写防漂移按最新正文重召回)
            if context_text:
                svc.context_text = context_text
            fragments = svc.fragments_for(
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


def _candidate_dispersion(texts: list[str]) -> float:
    """Measure pairwise surface dissimilarity of candidate texts (0=identical, 1=fully disjoint).

    Blueprint §6.3: dispersion is a necessary condition for surprise — if candidates
    are highly similar, sampling hasn't explored the tail.
    Uses character-level 4-gram Jaccard distance averaged over all pairs.
    """
    if len(texts) < 2:
        return 1.0

    def _char_ngrams(text: str, n: int = 4) -> set[str]:
        return {text[i:i + n] for i in range(max(0, len(text) - n + 1))}

    ngram_sets = [_char_ngrams(t) for t in texts]
    distances: list[float] = []
    for i in range(len(ngram_sets)):
        for j in range(i + 1, len(ngram_sets)):
            a, b = ngram_sets[i], ngram_sets[j]
            union = len(a | b)
            if union == 0:
                distances.append(0.0)
            else:
                distances.append(1.0 - len(a & b) / union)
    return sum(distances) / len(distances) if distances else 0.0


def _extract_scene_text(response: LLMResponse) -> str:
    structured_output = response.structured_output or {}
    scene_text = structured_output.get("scene_text")
    if isinstance(scene_text, str) and scene_text.strip():
        return scene_text.strip()
    # 中性/风格/补丁/续写各路径共用此提取器，消息不指认具体 stage（审计 P-17）
    raise ValueError("llm generation response missing scene_text")


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
