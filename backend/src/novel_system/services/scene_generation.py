from __future__ import annotations

import hashlib
import json
import logging
import re
import time
import uuid
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Callable

from sqlalchemy.orm import Session

from novel_system.db.models import AttemptTracker, LlmCall, SceneCard, SceneDraft, SceneRunState
from novel_system.services.errors import DomainError
from novel_system.services.author_instructions import render_author_note_instruction
from novel_system.services.hash_engine import canonical_json
from novel_system.services.literary_quality import DIMENSION_WEIGHTS, QUALITY_DIMENSIONS, analyze_literary_quality
from novel_system.services.llm_audit import sanitize_audit_summary
from novel_system.services.llm_client import LLMRequest, LLMResponse
from novel_system.services.llm_accounting import LLMAccountingRejected
from novel_system.services.llm_node_registry import get_llm_node_spec
from novel_system.services.llm_task_runner import (
    CONTINUITY_BUDGET_ERROR_CODE,
    CONTINUITY_BUDGET_MESSAGE,
    SCENE_SPLIT_RECOMMENDATION,
    LLMNodeContinuityError,
    LLMNodeExecutionError,
    LLMNodeRunner,
    current_llm_execution_id,
)
from novel_system.services.prompt_builder import PromptBuilder
from novel_system.services.style_reference.injection import (
    InjectionService,
    ordered_character_ids,
)

_LOGGER = logging.getLogger(__name__)
_PRE_DISPATCH_ACCOUNTING_REJECTIONS = frozenset(
    {
        "LLM_SCENE_TOKEN_BUDGET_UNINITIALIZED",
        "LLM_SCENE_TOKEN_BUDGET_EXHAUSTED",
        "LLM_BUSINESS_ATTEMPT_BUDGET_EXHAUSTED",
        "LLM_PROVIDER_ATTEMPT_BUDGET_EXHAUSTED",
        "LLM_SCENE_CALL_IN_FLIGHT",
        "LLM_ACCOUNTING_INTEGRITY_BLOCKED",
    }
)


def _counts_as_business_attempt(exc: Exception) -> bool:
    """A pre-dispatch accounting rejection is evidence, not a generation attempt."""
    original = getattr(exc, "original_error", None)
    code = str(getattr(exc, "error_code", None) or getattr(exc, "code", None) or "")
    original_code = str(
        getattr(original, "error_code", None) or getattr(original, "code", None) or ""
    )
    return not (
        isinstance(exc, LLMAccountingRejected)
        or isinstance(original, LLMAccountingRejected)
        or code in _PRE_DISPATCH_ACCOUNTING_REJECTIONS
        or original_code in _PRE_DISPATCH_ACCOUNTING_REJECTIONS
    )


class SceneGenerationPostprocessError(ValueError):
    """Stable typed failure emitted after a provider call settled successfully."""

    def __init__(self, *, llm_call_id: str | None, message: str) -> None:
        super().__init__(message)
        self.llm_call_id = llm_call_id
        self.code = "SCENE_GENERATION_RESPONSE_INVALID"
        self.error_code = self.code


@dataclass(slots=True)
class NeutralGenerationResult:
    row_id: str
    content: str
    llm_call_id: str
    bundle_id: str
    bundle_hash: str
    execution_step_key: str | None = None
    artifact_execution_id: str | None = None


@dataclass(slots=True)
class StyleGenerationResult:
    row_id: str
    content: str
    llm_call_id: str
    bundle_id: str
    bundle_hash: str
    execution_step_key: str | None = None
    artifact_execution_id: str | None = None


@dataclass(slots=True)
class LongFormContinuationSegmentResult:
    segment_index: int
    row_id: str
    content: str
    llm_call_id: str
    bundle_id: str
    bundle_hash: str
    execution_step_key: str
    artifact_execution_id: str | None = None


JSON_SCHEMA_INSTRUCTION = "Return JSON that matches the structured schema exactly."
ANTI_TEMPLATE_GATE_DIMENSIONS = {
    "template_action_reuse",
    "image_field_reuse",
    "syntax_monotony",
    "false_clarity",
    "summary_ending",
    "expository_dialogue",
}


def _continuation_text_hash(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def _continuation_json_hash(payload: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def _seal_continuation_descriptor(descriptor: dict[str, Any]) -> dict[str, Any]:
    sealed = deepcopy(descriptor)
    sealed.pop("descriptor_hash", None)
    sealed["descriptor_hash"] = _continuation_json_hash(sealed)
    return sealed

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


def _progressive_top_up_variants(base_temp: float) -> list[tuple[float, str | None, str]]:
    """Wave 3（§5.5）渐进补候选的变体轮换：温度加宽 → 发散提示 → 风格侧重轮换。

    返回 (temperature, extra_system_prefix, strategy_label) 序列；补候选按序取用，
    每次只补 1 个。
    """
    variants: list[tuple[float, str | None, str]] = [
        (round(min(2.0, base_temp + 0.15), 3), None, "temperature_widen"),
        (round(min(2.0, base_temp + 0.10), 3), _DIVERSIFICATION_PROMPT, "prompt_variation"),
    ]
    for idx, prefix in enumerate(_STYLE_EMPHASIS_ROTATION):
        variants.append(
            (round(min(2.0, base_temp + 0.05 * (idx + 1)), 3), prefix, f"style_emphasis_{idx}")
        )
    return variants


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
    """Backward-compatible renderer; bundle injection now carries it to every stage."""
    return render_author_note_instruction(author_note)


def _author_note_instruction_for_bundle(
    bundle: dict[str, Any],
    author_note: str | None,
) -> str:
    note = str(author_note or "").strip()
    frozen = str(
        ((bundle.get("snapshot") or {}).get("inline_digests") or {}).get(
            "author_instruction"
        )
        or ""
    )
    return "" if note == frozen else author_note_instruction(author_note)


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

    def generate_neutral_draft(
        self,
        scene_id: str,
        bundle: dict[str, Any],
        *,
        author_note: str | None = None,
    ) -> NeutralGenerationResult:
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
                execution_step_key="neutral_draft",
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
                user_prompt=prompt["user_prompt"]
                + _author_note_instruction_for_bundle(bundle, author_note),
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
            execution_step_key="neutral_draft",
        )

    def generate_style_draft(
        self,
        scene_id: str,
        bundle: dict[str, Any],
        *,
        neutral_draft_row_id: str,
        neutral_content: str,
        author_note: str | None = None,
        resume_base: StyleGenerationResult | None = None,
        product_callback: Callable[[str, str, StyleGenerationResult, dict[str, Any]], None] | None = None,
        step_reconciler: Callable[[str], None] | None = None,
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
                + _author_note_instruction_for_bundle(bundle, author_note)
            ),
            source_draft_row_id=neutral_draft_row_id,
            source_draft_content=neutral_content,
            client_kind="style",
            execution_step_key="style_draft:0",
            attempt_details_extra={"source_neutral_draft_row_id": neutral_draft_row_id},
            product_slot_key="initial:0",
            product_slot_order=0,
            resume_base=resume_base,
            product_callback=product_callback,
            step_reconciler=step_reconciler,
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
        max_candidates: int | None = None,
        resume_candidates: list[StyleGenerationResult] | None = None,
        candidate_checkpoint: Callable[[int, StyleGenerationResult], None] | None = None,
        step_reconciler: Callable[[str], None] | None = None,
        resume_bases: dict[str, StyleGenerationResult] | None = None,
        resume_products: dict[str, StyleGenerationResult] | None = None,
        product_callback: Callable[[str, str, StyleGenerationResult, dict[str, Any]], None] | None = None,
    ) -> list[StyleGenerationResult]:
        """Generate N style-draft candidates sorted by adversarial quality (best first).

        Wave 3（治理 §5.5）：低分散补救为**渐进补候选**——初始 n_candidates，
        分散度 <0.15 时在预算允许下逐个补到 max_candidates（关键 3→5、标准
        2→3），不再一次生成后整批无上限重试。
        """
        from novel_system.services.literary_quality import adversarial_rank_score, get_dimension_weights

        scene = self.session.get(SceneCard, scene_id)
        state = self.session.get(SceneRunState, scene_id)

        # §6 dynamic quality weights — project-level style profile can shift
        # which adversarial dimensions matter most for this particular work.
        _project_weights = get_dimension_weights(
            scene.project_id, self.session,
        ) if scene and scene.project_id else None
        if scene is not None:
            try:
                from novel_system.services.quality_strategy import QualityStrategyResolver

                resolved_strategy = QualityStrategyResolver(self.session).resolve_for_scene(scene)
                if resolved_strategy.matched_policy_id is not None:
                    _project_weights = resolved_strategy.weights
            except Exception:
                # Ranking is fail-soft for the single-candidate path.  The N>1
                # authorization itself fails closed in Orchestrator.
                pass

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

        durable_products = dict(resume_products or {})
        durable_bases = dict(resume_bases or {})
        if not durable_products:
            durable_products.update(
                (f"initial:{index}", candidate)
                for index, candidate in enumerate(resume_candidates or [])
            )
        candidates: list[tuple[StyleGenerationResult, float]] = [
            (candidate, adversarial_rank_score(candidate.content, weights=_project_weights))
            for candidate in durable_products.values()
        ]
        for idx, temp in enumerate(temperatures):
            slot_key = f"initial:{idx}"
            if slot_key in durable_products:
                continue
            cand_row_id = versioned_scene_artifact_id("draft_style_cand", scene_id, bundle) + f"_{idx}"
            try:
                if step_reconciler is not None and slot_key not in durable_bases:
                    step_reconciler(f"style_draft:{idx}")
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
                        + _author_note_instruction_for_bundle(bundle, author_note)
                    ),
                    source_draft_row_id=neutral_draft_row_id,
                    source_draft_content=neutral_content,
                    client_kind="style",
                    temperature_override=temp,
                    execution_step_key=f"style_draft:{idx}",
                    attempt_details_extra={
                        "source_neutral_draft_row_id": neutral_draft_row_id,
                        "candidate_index": idx,
                        "temperature_override": temp,
                        "n_candidates": n_candidates,
                    },
                    product_slot_key=slot_key,
                    product_slot_order=idx,
                    resume_base=durable_bases.get(slot_key),
                    product_callback=product_callback,
                    step_reconciler=step_reconciler,
                )
                score = adversarial_rank_score(result.content, weights=_project_weights)
                candidates.append((result, score))
                if candidate_checkpoint is not None:
                    candidate_checkpoint(idx, result)
            except (DomainError, LLMNodeExecutionError):
                _LOGGER.warning("candidate %d/%d failed for scene %s", idx + 1, n_candidates, scene_id)
                if candidate_checkpoint is not None or product_callback is not None:
                    raise
                continue

        if not candidates:
            return [self.generate_style_draft(
                scene_id, bundle,
                neutral_draft_row_id=neutral_draft_row_id,
                neutral_content=neutral_content,
                author_note=author_note,
                product_callback=product_callback,
                step_reconciler=step_reconciler,
            )]

        candidates.sort(key=lambda pair: pair[1], reverse=True)

        # Wave 3（§5.5）：渐进补候选——每次只补 1 个（温度加宽 / 发散提示 /
        # 风格侧重轮换作为逐个变体来源），每步过预算闸，补到上限或分散达标即停。
        candidate_cap = max(n_candidates, max_candidates or n_candidates)
        if len(candidates) >= 2 and candidate_cap > len(candidates):
            from novel_system.services.scene_budget import budget_unit, can_spend

            variants = _progressive_top_up_variants(base_temp)
            known_top_up_indices = {
                int(slot_key.rsplit(":", 1)[-1])
                for slot_key in {*durable_products, *durable_bases}
                if slot_key.startswith("topup:") and slot_key.rsplit(":", 1)[-1].isdigit()
            }
            pending_top_up_indices = sorted(
                index
                for index in known_top_up_indices
                if f"topup:{index}" in durable_bases and f"topup:{index}" not in durable_products
            )
            top_up_index = max(known_top_up_indices, default=0)
            while len(candidates) < candidate_cap:
                dispersion = _candidate_dispersion([c.content for c, _ in candidates])
                pending_top_up_index = pending_top_up_indices.pop(0) if pending_top_up_indices else None
                if pending_top_up_index is None and dispersion >= 0.15:
                    break
                if pending_top_up_index is None and not can_spend(state, budget_unit(state)):
                    _LOGGER.warning(
                        "budget exhausted — stop progressive candidate top-up for scene %s "
                        "(dispersion=%.3f, %d candidates)",
                        scene_id, dispersion, len(candidates),
                    )
                    break
                if pending_top_up_index is None:
                    top_up_index += 1
                else:
                    top_up_index = pending_top_up_index
                temp, prefix, strategy = variants[(top_up_index - 1) % len(variants)]
                _LOGGER.warning(
                    "low candidate dispersion (%.3f) for scene %s — progressive top-up #%d via %s (§5.5)",
                    dispersion, scene_id, top_up_index, strategy,
                )
                top_up_row_id = (
                    versioned_scene_artifact_id("draft_style_cand", scene_id, bundle)
                    + f"_topup_{top_up_index}"
                )
                slot_key = f"topup:{top_up_index}"
                try:
                    if step_reconciler is not None and slot_key not in durable_bases:
                        step_reconciler(f"style_draft:topup:{top_up_index}")
                    result = self._run_style_generation(
                        scene=scene, state=state, bundle=bundle,
                        row_id=top_up_row_id, stage="style_draft", llm_step="style_draft",
                        neutral_content=neutral_content, source_label="Approved Neutral Draft",
                        source_row_id=neutral_draft_row_id,
                        extra_instruction=(
                            "Apply the style prompt template without changing the approved facts."
                            + _author_note_instruction_for_bundle(bundle, author_note)
                        ),
                        source_draft_row_id=neutral_draft_row_id,
                        source_draft_content=neutral_content,
                        client_kind="style",
                        temperature_override=temp,
                        execution_step_key=f"style_draft:topup:{top_up_index}",
                        extra_system_prefix=prefix,
                        attempt_details_extra={
                            "source_neutral_draft_row_id": neutral_draft_row_id,
                            "candidate_index": f"topup_{top_up_index}",
                            "temperature_override": temp,
                            "n_candidates": n_candidates,
                            "max_candidates": candidate_cap,
                            "diversification_strategy": strategy,
                            "progressive_top_up": True,
                        },
                        product_slot_key=slot_key,
                        product_slot_order=n_candidates + top_up_index - 1,
                        resume_base=durable_bases.get(slot_key),
                        product_callback=product_callback,
                        step_reconciler=step_reconciler,
                    )
                    candidates.append((result, adversarial_rank_score(result.content, weights=_project_weights)))
                    if candidate_checkpoint is not None:
                        candidate_checkpoint(len(candidates) - 1, result)
                except (DomainError, LLMNodeExecutionError):
                    # 失败即停：不无上限重试（Wave 3 项 5）
                    _LOGGER.warning("progressive top-up #%d failed for scene %s — stop", top_up_index, scene_id)
                    if candidate_checkpoint is not None or product_callback is not None:
                        raise
                    break
            candidates.sort(key=lambda pair: pair[1], reverse=True)

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
        execution_step_key: str = "soft_patch:0",
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
            execution_step_key=execution_step_key,
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
        execution_step_key: str = "near_final_rewrite:0",
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
            execution_step_key=execution_step_key,
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
        segment_checkpoint: Callable[
            [int, LongFormContinuationSegmentResult, dict[str, Any]], None
        ] | None = None,
        step_reconciler: Callable[[str], None] | None = None,
        resume_segments: list[LongFormContinuationSegmentResult] | None = None,
        resume_cumulative_descriptor: dict[str, Any] | None = None,
    ) -> StyleGenerationResult:
        """Generate a continuation as independently durable segments.

        The service deliberately never commits. A production caller must provide
        ``segment_checkpoint`` plus ``step_reconciler`` and commit each segment
        row, attempt ledger and its cumulative descriptor in the same transaction.
        Calls without a callback retain the legacy single-transaction behavior for
        tests/tools only.
        """
        has_checkpoint_callback = segment_checkpoint is not None
        has_step_reconciler = step_reconciler is not None
        has_resume_input = bool(resume_segments) or bool(resume_cumulative_descriptor)
        if (
            has_checkpoint_callback != has_step_reconciler
            or (has_resume_input and not (has_checkpoint_callback and has_step_reconciler))
        ):
            raise DomainError(
                "RUN_CHECKPOINT_CORRUPT",
                "durable continuation requires a checkpoint callback and step reconciler pair",
                status_code=409,
            )
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
        parameters = {
            "source_draft_row_id": source_draft_row_id,
            "source_content_hash": _continuation_text_hash(source_content),
            "bundle_id": bundle["bundle_id"],
            "bundle_hash": bundle["bundle_snapshot_hash"],
            "target_continuation_chars": target_chars,
            "refresh_every_chars": refresh_every_chars,
            "segment_count": segment_count,
        }
        parameters_hash = _continuation_json_hash(parameters)
        resumed, cumulative_descriptor = self._load_long_form_resume_segments(
            scene=scene,
            bundle=bundle,
            parameters=parameters,
            parameters_hash=parameters_hash,
            resume_segments=resume_segments,
            resume_cumulative_descriptor=resume_cumulative_descriptor,
            require_durable_owner=segment_checkpoint is not None or resume_segments is not None,
        )
        continuation_parts = [segment.content for segment in resumed]
        all_segments = list(resumed)
        active_prompt = self._inject_style_reference(
            prompt, scene, task_type="long_form_continuation",
            context_text=(source_content or "")[-2000:],
        )
        for completed_index in range(len(continuation_parts)):
            if completed_index + 1 < segment_count:
                accumulated = "".join(continuation_parts[: completed_index + 1])
                active_prompt = self._inject_style_reference(
                    prompt,
                    scene,
                    task_type="long_form_continuation",
                    context_text=(f"{source_content}\n{accumulated}".strip())[-2000:],
                )

        for segment_index in range(len(resumed), segment_count):
            execution_step_key = f"long_form_continuation:{segment_index}"
            existing_continuation = "".join(continuation_parts)
            user_prompt = self._build_long_form_continuation_user_prompt(
                active_prompt["user_prompt"],
                source_content=source_content,
                source_row_id=source_draft_row_id,
                existing_continuation=existing_continuation,
            )
            if step_reconciler is not None:
                step_reconciler(execution_step_key)
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
                    execution_step_key=execution_step_key,
                )
                segment_content = _extract_scene_text(node_result.response)
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
            prior_cumulative_hash = _continuation_text_hash(existing_continuation)
            continuation_parts.append(segment_content)
            cumulative_content = "".join(continuation_parts)
            segment_result = self._persist_long_form_segment(
                scene=scene,
                bundle=bundle,
                segment_index=segment_index,
                segment_content=segment_content,
                llm_call_id=node_result.llm_call_id,
                source_draft_row_id=source_draft_row_id,
                source_content_hash=parameters["source_content_hash"],
                prior_cumulative_hash=prior_cumulative_hash,
                cumulative_hash=_continuation_text_hash(cumulative_content),
                parameters_hash=parameters_hash,
            )
            all_segments.append(segment_result)
            cumulative_descriptor["segments"].append(
                self._long_form_segment_descriptor(
                    segment_result,
                    source_draft_row_id=source_draft_row_id,
                    source_content_hash=parameters["source_content_hash"],
                    prior_cumulative_hash=prior_cumulative_hash,
                    cumulative_hash=_continuation_text_hash(cumulative_content),
                    parameters_hash=parameters_hash,
                )
            )
            cumulative_descriptor["cumulative_content_hash"] = _continuation_text_hash(cumulative_content)
            cumulative_descriptor = _seal_continuation_descriptor(cumulative_descriptor)
            if segment_checkpoint is not None:
                if not isinstance(segment_result.artifact_execution_id, str):
                    raise DomainError(
                        "RUN_CHECKPOINT_CORRUPT",
                        "durable continuation callback requires an execution owner",
                        status_code=409,
                    )
                segment_checkpoint(segment_index, segment_result, deepcopy(cumulative_descriptor))
            if segment_index + 1 < segment_count:
                # 防漂移:用累计已生成正文尾部重做 RAG 召回 → 样例随上下文变化
                accumulated = "".join(continuation_parts)
                active_prompt = self._inject_style_reference(
                    prompt, scene, task_type="long_form_continuation",
                    context_text=(f"{source_content}\n{accumulated}".strip())[-2000:],
                )

        if len(all_segments) != segment_count:
            raise DomainError("RUN_CHECKPOINT_CORRUPT", "continuation segment prefix is incomplete", status_code=409)
        return self._persist_long_form_final(
            scene=scene,
            state=state,
            bundle=bundle,
            segments=all_segments,
            cumulative_descriptor=cumulative_descriptor,
            parameters=parameters,
            parameters_hash=parameters_hash,
        )

    def _persist_long_form_final(
        self,
        *,
        scene: SceneCard,
        state: SceneRunState,
        bundle: dict[str, Any],
        segments: list[LongFormContinuationSegmentResult],
        cumulative_descriptor: dict[str, Any],
        parameters: dict[str, Any],
        parameters_hash: str,
    ) -> StyleGenerationResult:
        content = "".join(segment.content for segment in segments)
        llm_call_ids = [segment.llm_call_id for segment in segments]
        if (
            len(segments) != parameters["segment_count"]
            or cumulative_descriptor.get("cumulative_content_hash") != _continuation_text_hash(content)
            or cumulative_descriptor.get("parameters_hash") != parameters_hash
            or cumulative_descriptor.get("parameters") != parameters
        ):
            raise DomainError("RUN_CHECKPOINT_CORRUPT", "continuation final does not match its segment ledger", status_code=409)
        row_id = versioned_scene_artifact_id("draft_long_form_continuation", scene.scene_id, bundle)
        existing = self.session.get(SceneDraft, row_id)
        if existing is None:
            self.session.add(
                SceneDraft(
                    row_id=row_id,
                    scene_id=scene.scene_id,
                    chapter_id=scene.chapter_id,
                    stage="long_form_continuation",
                    content=content,
                    source_bundle_id=bundle["bundle_id"],
                    source_bundle_hash=bundle["bundle_snapshot_hash"],
                    generation_llm_call_id=llm_call_ids[-1],
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
                        "content_hash": _continuation_text_hash(content),
                        "llm_call_id": llm_call_ids[-1],
                        "segment_count": len(segments),
                        "llm_call_ids": llm_call_ids,
                        "source_draft_row_id": parameters["source_draft_row_id"],
                        "source_content_hash": parameters["source_content_hash"],
                        "refresh_every_chars": parameters["refresh_every_chars"],
                        "target_continuation_chars": parameters["target_continuation_chars"],
                        "parameters_hash": parameters_hash,
                        "cumulative_descriptor_hash": cumulative_descriptor["descriptor_hash"],
                    },
                )
            )
            self.session.flush()
            existing = self.session.get(SceneDraft, row_id)
        final_attempts = []
        for attempt in self.session.query(AttemptTracker).filter_by(
            scene_id=scene.scene_id,
            step="long_form_continuation",
            status="completed",
            source_bundle_id=bundle["bundle_id"],
        ):
            details = attempt.details_json or {}
            if details.get("row_id") == row_id and details.get("segment_index") is None:
                final_attempts.append(attempt)
        details = final_attempts[0].details_json if len(final_attempts) == 1 else {}
        if (
            existing is None
            or existing.scene_id != scene.scene_id
            or existing.stage != "long_form_continuation"
            or existing.content != content
            or existing.source_bundle_id != bundle["bundle_id"]
            or existing.source_bundle_hash != bundle["bundle_snapshot_hash"]
            or existing.generation_llm_call_id != llm_call_ids[-1]
            or len(final_attempts) != 1
            or details.get("content_hash") != _continuation_text_hash(content)
            or details.get("llm_call_ids") != llm_call_ids
            or details.get("parameters_hash") != parameters_hash
            or details.get("cumulative_descriptor_hash") != cumulative_descriptor["descriptor_hash"]
        ):
            raise DomainError("RUN_CHECKPOINT_CORRUPT", "continuation final identity/hash mismatch", status_code=409)
        state.current_style_draft_row_id = row_id
        state.latest_valid_draft_row_id = row_id
        state.current_bundle_id = bundle["bundle_id"]
        state.current_bundle_hash = bundle["bundle_snapshot_hash"]
        self.session.flush()
        return StyleGenerationResult(
            row_id=row_id,
            content=content,
            llm_call_id=llm_call_ids[-1],
            bundle_id=bundle["bundle_id"],
            bundle_hash=bundle["bundle_snapshot_hash"],
            execution_step_key=segments[-1].execution_step_key,
            artifact_execution_id=segments[-1].artifact_execution_id,
        )

    def _persist_long_form_segment(
        self,
        *,
        scene: SceneCard,
        bundle: dict[str, Any],
        segment_index: int,
        segment_content: str,
        llm_call_id: str,
        source_draft_row_id: str,
        source_content_hash: str,
        prior_cumulative_hash: str,
        cumulative_hash: str,
        parameters_hash: str,
    ) -> LongFormContinuationSegmentResult:
        execution_step_key = f"long_form_continuation:{segment_index}"
        row_id = (
            versioned_scene_artifact_id("draft_long_form_continuation_segment", scene.scene_id, bundle)
            + f"_{segment_index}"
        )
        self.session.add(
            SceneDraft(
                row_id=row_id,
                scene_id=scene.scene_id,
                chapter_id=scene.chapter_id,
                stage="long_form_continuation_segment",
                content=segment_content,
                source_bundle_id=bundle["bundle_id"],
                source_bundle_hash=bundle["bundle_snapshot_hash"],
                generation_llm_call_id=llm_call_id,
            )
        )
        self.session.flush()
        owner = current_llm_execution_id()
        self.session.add(
            AttemptTracker(
                scene_id=scene.scene_id,
                chapter_id=scene.chapter_id,
                step="long_form_continuation",
                status="completed",
                source_bundle_id=bundle["bundle_id"],
                details_json={
                    "row_id": row_id,
                    "llm_call_id": llm_call_id,
                    "segment_index": segment_index,
                    "source_draft_row_id": source_draft_row_id,
                    "source_content_hash": source_content_hash,
                    "prior_cumulative_hash": prior_cumulative_hash,
                    "cumulative_hash": cumulative_hash,
                    "parameters_hash": parameters_hash,
                    "execution_step_key": execution_step_key,
                    "artifact_execution_id": owner,
                },
            )
        )
        self.session.flush()
        return LongFormContinuationSegmentResult(
            segment_index=segment_index,
            row_id=row_id,
            content=segment_content,
            llm_call_id=llm_call_id,
            bundle_id=bundle["bundle_id"],
            bundle_hash=bundle["bundle_snapshot_hash"],
            execution_step_key=execution_step_key,
            artifact_execution_id=owner,
        )

    @staticmethod
    def _long_form_segment_descriptor(
        segment: LongFormContinuationSegmentResult,
        *,
        source_draft_row_id: str,
        source_content_hash: str,
        prior_cumulative_hash: str,
        cumulative_hash: str,
        parameters_hash: str,
    ) -> dict[str, Any]:
        return {
            "segment_index": segment.segment_index,
            "row_id": segment.row_id,
            "content_hash": _continuation_text_hash(segment.content),
            "source_draft_row_id": source_draft_row_id,
            "source_content_hash": source_content_hash,
            "prior_cumulative_hash": prior_cumulative_hash,
            "cumulative_hash": cumulative_hash,
            "bundle_id": segment.bundle_id,
            "bundle_hash": segment.bundle_hash,
            "llm_call_id": segment.llm_call_id,
            "execution_step_key": segment.execution_step_key,
            "artifact_execution_id": segment.artifact_execution_id,
            "parameters_hash": parameters_hash,
        }

    def _load_long_form_resume_segments(
        self,
        *,
        scene: SceneCard,
        bundle: dict[str, Any],
        parameters: dict[str, Any],
        parameters_hash: str,
        resume_segments: list[LongFormContinuationSegmentResult] | None,
        resume_cumulative_descriptor: dict[str, Any] | None,
        require_durable_owner: bool,
    ) -> tuple[list[LongFormContinuationSegmentResult], dict[str, Any]]:
        if resume_segments is None and resume_cumulative_descriptor is None:
            descriptor = {
                "version": 1,
                "parameters": deepcopy(parameters),
                "parameters_hash": parameters_hash,
                "segments": [],
                "cumulative_content_hash": _continuation_text_hash(""),
            }
            return [], _seal_continuation_descriptor(descriptor)
        if not isinstance(resume_segments, list) or not isinstance(resume_cumulative_descriptor, dict):
            raise DomainError(
                "RUN_CHECKPOINT_CORRUPT",
                "continuation resume segments and descriptor must be supplied together",
                status_code=409,
            )
        descriptor = deepcopy(resume_cumulative_descriptor)
        supplied_hash = descriptor.get("descriptor_hash")
        if (
            not isinstance(supplied_hash, str)
            or _seal_continuation_descriptor(descriptor).get("descriptor_hash") != supplied_hash
            or descriptor.get("version") != 1
            or descriptor.get("parameters") != parameters
            or descriptor.get("parameters_hash") != parameters_hash
            or not isinstance(descriptor.get("segments"), list)
            or len(descriptor["segments"]) != len(resume_segments)
            or len(resume_segments) > parameters["segment_count"]
        ):
            raise DomainError("RUN_CHECKPOINT_CORRUPT", "continuation resume descriptor is invalid", status_code=409)
        accumulated = ""
        for index, (segment, segment_descriptor) in enumerate(
            zip(resume_segments, descriptor["segments"], strict=True)
        ):
            if not isinstance(segment, LongFormContinuationSegmentResult) or not isinstance(segment_descriptor, dict):
                raise DomainError("RUN_CHECKPOINT_CORRUPT", "continuation segment cursor is invalid", status_code=409)
            expected_row_id = (
                versioned_scene_artifact_id("draft_long_form_continuation_segment", scene.scene_id, bundle)
                + f"_{index}"
            )
            expected_step_key = f"long_form_continuation:{index}"
            prior_hash = _continuation_text_hash(accumulated)
            accumulated += segment.content
            cumulative_hash = _continuation_text_hash(accumulated)
            expected_descriptor = self._long_form_segment_descriptor(
                segment,
                source_draft_row_id=parameters["source_draft_row_id"],
                source_content_hash=parameters["source_content_hash"],
                prior_cumulative_hash=prior_hash,
                cumulative_hash=cumulative_hash,
                parameters_hash=parameters_hash,
            )
            row = self.session.get(SceneDraft, segment.row_id)
            if row is None:
                raise DomainError(
                    "RUN_CHECKPOINT_OUTPUT_MISSING",
                    "durable continuation segment is missing",
                    status_code=409,
                    details={"row_id": segment.row_id},
                )
            if (
                segment.segment_index != index
                or segment.row_id != expected_row_id
                or segment.execution_step_key != expected_step_key
                or segment.bundle_id != bundle["bundle_id"]
                or segment.bundle_hash != bundle["bundle_snapshot_hash"]
                or segment_descriptor != expected_descriptor
                or row.scene_id != scene.scene_id
                or row.stage != "long_form_continuation_segment"
                or row.content != segment.content
                or row.source_bundle_id != bundle["bundle_id"]
                or row.source_bundle_hash != bundle["bundle_snapshot_hash"]
                or row.generation_llm_call_id != segment.llm_call_id
            ):
                raise DomainError("RUN_CHECKPOINT_CORRUPT", "continuation segment identity/hash mismatch", status_code=409)
            self._validate_long_form_segment_ledgers(
                scene=scene,
                bundle=bundle,
                segment=segment,
                descriptor=segment_descriptor,
                require_durable_owner=require_durable_owner,
            )
        if descriptor.get("cumulative_content_hash") != _continuation_text_hash(accumulated):
            raise DomainError("RUN_CHECKPOINT_CORRUPT", "continuation cumulative hash mismatch", status_code=409)
        return list(resume_segments), descriptor

    def _validate_long_form_segment_ledgers(
        self,
        *,
        scene: SceneCard,
        bundle: dict[str, Any],
        segment: LongFormContinuationSegmentResult,
        descriptor: dict[str, Any],
        require_durable_owner: bool,
    ) -> None:
        owner = segment.artifact_execution_id
        current_owner = current_llm_execution_id()
        call = self.session.get(LlmCall, segment.llm_call_id)
        if (
            (require_durable_owner and not isinstance(owner, str))
            or (current_owner is not None and owner != current_owner)
            or call is None
            or call.scene_id != scene.scene_id
            or call.step != "long_form_continuation"
            or call.execution_id != owner
            or call.execution_step_key != segment.execution_step_key
            or not isinstance(call.provider, str)
            or not call.provider
            or not isinstance(call.model, str)
            or not call.model
            or call.accounting_status != "settled"
            or call.request_dispatched_at is None
            or any(
                not isinstance(value, int) or value < 0
                for value in (
                    call.estimated_tokens,
                    call.reserved_tokens,
                    call.budget_charged_tokens,
                    call.prompt_tokens,
                    call.completion_tokens,
                    call.total_tokens,
                )
            )
            or call.budget_charged_tokens > call.reserved_tokens
            or call.total_tokens != call.prompt_tokens + call.completion_tokens
        ):
            raise DomainError("RUN_CHECKPOINT_CORRUPT", "continuation segment call ledger is invalid", status_code=409)
        matching_attempts = []
        for attempt in self.session.query(AttemptTracker).filter_by(
            scene_id=scene.scene_id,
            step="long_form_continuation",
            status="completed",
            source_bundle_id=bundle["bundle_id"],
        ):
            details = attempt.details_json or {}
            if (
                details.get("row_id") == segment.row_id
                and details.get("llm_call_id") == segment.llm_call_id
                and details.get("segment_index") == segment.segment_index
                and details.get("source_draft_row_id") == descriptor["source_draft_row_id"]
                and details.get("source_content_hash") == descriptor["source_content_hash"]
                and details.get("prior_cumulative_hash") == descriptor["prior_cumulative_hash"]
                and details.get("cumulative_hash") == descriptor["cumulative_hash"]
                and details.get("parameters_hash") == descriptor["parameters_hash"]
                and details.get("execution_step_key") == segment.execution_step_key
                and details.get("artifact_execution_id") == owner
            ):
                matching_attempts.append(attempt)
        if len(matching_attempts) != 1:
            raise DomainError("RUN_CHECKPOINT_CORRUPT", "continuation segment attempt ledger is invalid", status_code=409)

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
        execution_step_key: str | None = None,
        product_slot_key: str | None = None,
        product_slot_order: int | None = None,
        resume_base: StyleGenerationResult | None = None,
        product_callback: Callable[[str, str, StyleGenerationResult, dict[str, Any]], None] | None = None,
        step_reconciler: Callable[[str], None] | None = None,
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
                execution_step_key=execution_step_key,
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
        if resume_base is None:
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
                    execution_step_key=execution_step_key,
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
            base_result = StyleGenerationResult(
                row_id=row_id,
                content=style_content,
                llm_call_id=node_result.llm_call_id,
                bundle_id=bundle["bundle_id"],
                bundle_hash=bundle["bundle_snapshot_hash"],
                execution_step_key=execution_step_key,
            )
            if product_callback is not None and product_slot_key is not None:
                product_callback(
                    product_slot_key,
                    "base",
                    base_result,
                    {
                        "slot_order": product_slot_order,
                        "source_neutral_draft_row_id": source_draft_row_id,
                        "gate_decision": None,
                        "source_base_row_id": None,
                    },
                )
        else:
            if (
                resume_base.row_id != row_id
                or resume_base.bundle_id != bundle["bundle_id"]
                or resume_base.bundle_hash != bundle["bundle_snapshot_hash"]
                or resume_base.execution_step_key != execution_step_key
            ):
                raise DomainError(
                    "RUN_CHECKPOINT_CORRUPT",
                    "resumed style base does not match its locked work item",
                    status_code=409,
                )
            base_result = resume_base
            style_content = resume_base.content

        if stage == "style_draft":
            quality_gate = _anti_template_quality_gate(style_content, scene_id=scene.scene_id, chapter_id=scene.chapter_id)
            if quality_gate["triggered"]:
                de_template_step_key = f"{execution_step_key}:de_template" if execution_step_key else None
                if step_reconciler is not None and de_template_step_key is not None:
                    step_reconciler(de_template_step_key)
                de_template_result, de_template_outcome = self._run_de_template_pass(
                    scene=scene,
                    state=state,
                    bundle=bundle,
                    prompt=prompt,
                    source_row_id=row_id,
                    source_content=style_content,
                    quality_gate=quality_gate,
                    execution_step_key=de_template_step_key,
                )
                if de_template_result is not None:
                    if product_callback is not None and product_slot_key is not None:
                        product_callback(
                            product_slot_key,
                            "final",
                            de_template_result,
                            {
                                "slot_order": product_slot_order,
                                "source_neutral_draft_row_id": source_draft_row_id,
                                "gate_decision": quality_gate,
                                "source_base_row_id": base_result.row_id,
                                "de_template_outcome": de_template_outcome,
                            },
                        )
                    return de_template_result
            if product_callback is not None and product_slot_key is not None:
                product_callback(
                    product_slot_key,
                    "final",
                    base_result,
                    {
                        "slot_order": product_slot_order,
                        "source_neutral_draft_row_id": source_draft_row_id,
                        "gate_decision": quality_gate,
                        "source_base_row_id": base_result.row_id,
                        "de_template_outcome": (
                            de_template_outcome
                            if quality_gate["triggered"]
                            else {"status": "not_required"}
                        ),
                    },
                )

        return base_result

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
        execution_step_key: str | None,
    ) -> tuple[StyleGenerationResult | None, dict[str, Any]]:
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
                execution_step_key=execution_step_key,
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
            call = self.session.get(LlmCall, exc.llm_call_id)
            return None, {
                "status": "failed",
                "llm_call_id": exc.llm_call_id,
                "execution_step_key": execution_step_key,
                "artifact_execution_id": call.execution_id if call is not None else current_llm_execution_id(),
                "accounting_status": call.accounting_status if call is not None else None,
                "error_code": exc.error_code,
            }

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

        return (
            StyleGenerationResult(
                row_id=row_id,
                content=rewritten_content,
                llm_call_id=node_result.llm_call_id,
                bundle_id=bundle["bundle_id"],
                bundle_hash=bundle["bundle_snapshot_hash"],
                execution_step_key=execution_step_key,
            ),
            {
                "status": "completed",
                "llm_call_id": node_result.llm_call_id,
                "execution_step_key": execution_step_key,
                "artifact_execution_id": current_llm_execution_id(),
                "accounting_status": "settled",
            },
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
            "business_attempt_consumed": _counts_as_business_attempt(exc),
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
        if _counts_as_business_attempt(exc):
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
        execution_step_key: str | None = None,
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
                scope_type="scene",
                scope_id=scene.scene_id,
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
                execution_id=current_llm_execution_id(),
                execution_step_key=execution_step_key,
                estimated_tokens=0,
                reserved_tokens=0,
                budget_charged_tokens=0,
                accounting_status="rejected",
                request_payload_summary=sanitize_audit_summary(request_summary),
                response_payload_summary=sanitize_audit_summary(_error_summary(exc)),
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
            "execution_step_key": execution_step_key,
            "business_attempt_consumed": _counts_as_business_attempt(exc),
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
        if _counts_as_business_attempt(exc):
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
    raise SceneGenerationPostprocessError(
        llm_call_id=getattr(response, "llm_call_id", None),
        message="llm generation response missing scene_text",
    )


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
