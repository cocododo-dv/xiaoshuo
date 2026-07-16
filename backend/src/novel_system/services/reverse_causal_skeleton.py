"""Reverse causal skeleton — blueprint §4.

"从终局状态反向推导——要让结局可信，倒数第二步必须是什么？继续反推到第一章。
产出的不是大纲（'会发生什么'），而是因果链（'为什么后面的事件必须发生'）。"

This module provides:
1. A data model for causal chain links (CausalLink)
2. A builder that constructs a reverse chain from controlling idea + ending
3. Integration with the snowflake planner to validate causal coherence
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from novel_system.services.llm_accounting import LLMAccountingRejected, LLMCallContext


@dataclass(slots=True)
class CausalLink:
    """One link in the reverse causal chain."""
    step_index: int
    description: str
    why_necessary: str
    character_state_before: str
    character_state_after: str
    depends_on_index: int | None = None
    scene_id: str | None = None


@dataclass(slots=True)
class ReverseCausalSkeleton:
    controlling_idea: str
    ending_state: str
    chain: list[CausalLink] = field(default_factory=list)

    @property
    def opening_state(self) -> str | None:
        return self.chain[0].character_state_before if self.chain else None

    @property
    def scene_anchor_mode(self) -> str:
        """Return how scene anchors may be used for readiness evaluation.

        A chain is intentionally all-or-nothing: complete anchors select stable
        ``scene_id`` evaluation, no anchors select the legacy ordinal fallback,
        and partial anchors are invalid rather than silently mixing both models.
        """
        anchored_count = sum(1 for link in self.chain if _normalized_scene_id(link.scene_id))
        if anchored_count == 0:
            return "ordinal_fallback"
        if anchored_count == len(self.chain):
            return "scene_id"
        return "partial"

    def validate_chain_integrity(self) -> list[str]:
        """Check that each link's before-state matches the previous link's after-state."""
        issues: list[str] = []
        for i in range(1, len(self.chain)):
            prev_after = self.chain[i - 1].character_state_after
            curr_before = self.chain[i].character_state_before
            if prev_after and curr_before and prev_after != curr_before:
                issues.append(
                    f"State mismatch at step {i}: previous ends with '{prev_after}' "
                    f"but step {i} begins with '{curr_before}'"
                )
        return issues


def build_reverse_skeleton(
    controlling_idea: str,
    ending_description: str,
    major_turning_points: list[dict[str, str]] | None = None,
    *,
    ending_scene_id: str | None = None,
) -> ReverseCausalSkeleton:
    """Build a reverse causal skeleton from ending to beginning.

    This is the offline/deterministic builder. When LLM is enabled, a separate
    LLM-powered version can refine the chain by asking "for this step to be
    credible, what must have happened before?"

    Args:
        controlling_idea: The one-sentence theme judgment (e.g., "残缺本身也可以是完整的")
        ending_description: What happens at the ending
        major_turning_points: Optional list of dicts with 'description' and 'why' keys,
            ordered from ending backward toward opening. Each point may carry a
            ``scene_id`` anchor.
        ending_scene_id: Optional stable scene anchor for the ending link.
    """
    skeleton = ReverseCausalSkeleton(
        controlling_idea=controlling_idea,
        ending_state=ending_description,
    )

    if not major_turning_points:
        skeleton.chain.append(CausalLink(
            step_index=0,
            description=ending_description,
            why_necessary=f"This is the ending that proves the controlling idea: {controlling_idea}",
            character_state_before="approaching final confrontation",
            character_state_after="controlling idea proven through action",
            scene_id=ending_scene_id,
        ))
        return skeleton

    for i, point in enumerate(reversed(major_turning_points)):
        desc = point.get("description", "")
        why = point.get("why", f"必须发生才能使第 {i + 1} 步可信")
        skeleton.chain.append(CausalLink(
            step_index=i,
            description=desc,
            why_necessary=why,
            character_state_before=point.get("state_before", ""),
            character_state_after=point.get("state_after", ""),
            depends_on_index=i - 1 if i > 0 else None,
            scene_id=point.get("scene_id"),
        ))

    skeleton.chain.append(CausalLink(
        step_index=len(skeleton.chain),
        description=ending_description,
        why_necessary=f"终局证明控制性理念: {controlling_idea}",
        character_state_before=skeleton.chain[-1].character_state_after if skeleton.chain else "",
        character_state_after="controlling idea proven",
        depends_on_index=len(skeleton.chain) - 1,
        scene_id=ending_scene_id,
    ))

    return skeleton


_REFINE_SYSTEM_PROMPT = (
    "你是因果结构编辑。给定一条从终局反推的因果链，你的任务是找出链条中的"
    "因果缺口——即某一步要可信，前一步却没有为它提供充分的前提。"
    "对每个缺口，提出需要在两步之间补充的、最小且必要的前置事件。"
    "规则：(1) 只补因果必需的前置，不扩写情节；(2) 不臆造与控制性理念无关的内容；"
    "(3) 严格输出 JSON，无额外文字。"
    'JSON 格式：{"gaps": [{"after_step": 整数, "missing_premise": "需要补充的前置事件", '
    '"why": "为什么没有它下一步不可信"}]}'
)

_REFINE_TASK_TEMPLATE = (
    "控制性理念：{controlling_idea}\n终局：{ending_state}\n\n"
    "当前因果链（从开端到终局）：\n{chain_block}\n\n"
    "请找出因果缺口并仅输出 JSON。若链条因果自洽，输出 {{\"gaps\": []}}。"
)


@dataclass(slots=True)
class CausalGap:
    """An LLM-identified causal gap between two adjacent links."""
    after_step: int
    missing_premise: str
    why: str


@dataclass(slots=True, frozen=True)
class CausalDiagnostic:
    """Machine-readable explanation of how readiness was (or was not) evaluated."""

    code: str
    message: str
    context: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "context": dict(self.context),
        }


@dataclass(slots=True)
class CausalReadiness:
    """Result of a causal prerequisite check for a specific scene.

    Returned by :func:`validate_scene_causal_readiness`.
    ``ready`` is True when the scene may proceed (either all prerequisites are
    met or ``strict`` mode was off).  ``blocking`` is True only when
    ``strict=True`` *and* unresolved prerequisites exist.
    """
    ready: bool
    unresolved: list[CausalGap]
    blocking: bool
    diagnostics: list[CausalDiagnostic] = field(default_factory=list)

    def format_for_prompt(self) -> str:
        """Format unresolved prerequisites as a prompt-injectable warning."""
        return format_causal_readiness_warning(self)


def refine_skeleton_with_llm(
    skeleton: ReverseCausalSkeleton,
    *,
    llm_runner: Any | None = None,
    llm_context: LLMCallContext | None = None,
) -> list[CausalGap]:
    """§4 逆向因果骨架 LLM 精炼: ask "for this step to be credible, what must precede it?".

    Opt-in (same pattern as llm_auto_critique / check_consistency_llm): when no
    llm_runner is supplied, returns no gaps (the deterministic builder stands alone).
    Returns ADVISORY gaps for the author to act on — does not mutate the skeleton, so a
    hallucinating refiner can never silently rewrite the causal spine.
    """
    if llm_runner is None or not skeleton.chain:
        return []
    if llm_context is None:
        raise LLMAccountingRejected(
            "LLM_ACCOUNTING_CONTEXT_REQUIRED",
            "causal skeleton refinement requires explicit accounting context",
        )

    chain_lines: list[str] = []
    for link in skeleton.chain:
        state = (
            f"（{link.character_state_before} → {link.character_state_after}）"
            if link.character_state_before or link.character_state_after else ""
        )
        chain_lines.append(f"  步骤{link.step_index}: {link.description} {state}".rstrip())
    task_prompt = _REFINE_TASK_TEMPLATE.format(
        controlling_idea=skeleton.controlling_idea,
        ending_state=skeleton.ending_state,
        chain_block="\n".join(chain_lines),
    )
    try:
        response = llm_runner.run_task(
            task_name="causal_skeleton_refine",
            prompt_text=task_prompt,
            system_prompt=_REFINE_SYSTEM_PROMPT,
            context=llm_context,
        )
    except Exception:
        return []
    return _parse_causal_gaps(response)


def _parse_causal_gaps(response: Any) -> list[CausalGap]:
    import json as _json

    if response is None:
        return []
    raw = response if isinstance(response, str) else (
        getattr(response, "text", None) or getattr(response, "content", None) or ""
    )
    raw = (raw or "").strip()
    if "```" in raw and raw.count("```") >= 2:
        raw = raw.replace("```json", "```").split("```")[1]
    start, end = raw.find("{"), raw.rfind("}")
    if start < 0 or end <= start:
        return []
    try:
        parsed = _json.loads(raw[start:end + 1])
    except (ValueError, TypeError):
        return []
    out: list[CausalGap] = []
    for item in parsed.get("gaps") or []:
        if not isinstance(item, dict):
            continue
        premise = str(item.get("missing_premise") or "").strip()
        if not premise:
            continue
        try:
            after = int(item.get("after_step", 0))
        except (ValueError, TypeError):
            after = 0
        out.append(CausalGap(
            after_step=after,
            missing_premise=premise,
            why=str(item.get("why") or ""),
        ))
    return out


def format_causal_gaps_for_prompt(gaps: list[CausalGap]) -> str:
    """Render advisory causal gaps as an author-facing planning note."""
    if not gaps:
        return ""
    lines = ["## 因果缺口（LLM 建议，需作者确认）"]
    for gap in gaps:
        lines.append(f"  - 在步骤 {gap.after_step} 之后补充：{gap.missing_premise}")
        if gap.why:
            lines.append(f"    原因：{gap.why}")
    return "\n".join(lines)


def format_skeleton_for_prompt(skeleton: ReverseCausalSkeleton) -> str:
    """Format the reverse causal skeleton as a prompt section for planning."""
    lines = ["## Reverse Causal Skeleton (ending → opening)"]
    lines.append(f"Controlling Idea: {skeleton.controlling_idea}")
    lines.append(f"Ending: {skeleton.ending_state}")
    lines.append("")
    for link in skeleton.chain:
        arrow = "→" if link.depends_on_index is not None else "⊙"
        lines.append(f"  {arrow} Step {link.step_index}: {link.description}")
        lines.append(f"    Why: {link.why_necessary}")
        if link.character_state_before:
            lines.append(f"    State: {link.character_state_before} → {link.character_state_after}")
    issues = skeleton.validate_chain_integrity()
    if issues:
        lines.append("\n⚠ Chain integrity issues:")
        for issue in issues:
            lines.append(f"  - {issue}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Causal readiness gate — scene-level prerequisite check
# ---------------------------------------------------------------------------

def validate_scene_causal_readiness(
    skeleton: ReverseCausalSkeleton,
    scene_index: int | None = None,
    *,
    completed_scenes: list[int] | None = None,
    scene_id: str | None = None,
    completed_scene_ids: list[str] | None = None,
    strict: bool = False,
) -> CausalReadiness:
    """Check causal prerequisites using one unambiguous addressing model.

    Fully anchored chains are evaluated by ``scene_id``. Legacy chains with
    zero anchors retain ordinal behavior and emit an observable fallback
    diagnostic. Partially anchored chains are not evaluated: mixing scene IDs
    and ordinals would make the result depend on accidental catalog order.
    """
    if not skeleton.chain:
        return CausalReadiness(ready=True, unresolved=[], blocking=False)

    anchor_mode = skeleton.scene_anchor_mode
    if anchor_mode == "partial":
        anchored_steps = [
            link.step_index for link in skeleton.chain
            if _normalized_scene_id(link.scene_id)
        ]
        unanchored_steps = [
            link.step_index for link in skeleton.chain
            if not _normalized_scene_id(link.scene_id)
        ]
        return _diagnostic_only_readiness(
            CausalDiagnostic(
                code="CAUSAL_ANCHORS_PARTIAL",
                message=(
                    "causal readiness was not evaluated because scene anchors "
                    "must cover either every causal link or none"
                ),
                context={
                    "anchored_step_indices": anchored_steps,
                    "unanchored_step_indices": unanchored_steps,
                    "total_links": len(skeleton.chain),
                },
            )
        )

    if anchor_mode == "scene_id":
        return _validate_anchored_scene_readiness(
            skeleton,
            scene_id=scene_id,
            completed_scene_ids=completed_scene_ids,
            strict=strict,
        )

    fallback_diagnostic = CausalDiagnostic(
        code="CAUSAL_READINESS_ORDINAL_FALLBACK",
        message="legacy causal skeleton has no scene_id anchors; ordinal compatibility mode was used",
        context={"total_links": len(skeleton.chain)},
    )
    if scene_index is None or completed_scenes is None:
        return _diagnostic_only_readiness(
            CausalDiagnostic(
                code="CAUSAL_ORDINAL_CONTEXT_MISSING",
                message="ordinal fallback could not run because ordinal scene context was incomplete",
                context={
                    "scene_index_present": scene_index is not None,
                    "completed_scenes_present": completed_scenes is not None,
                },
            ),
            fallback_diagnostic,
        )

    return _evaluate_readiness_by_step(
        skeleton,
        target_step_index=scene_index,
        completed_step_indices=set(completed_scenes),
        strict=strict,
        diagnostics=[fallback_diagnostic],
    )


def _validate_anchored_scene_readiness(
    skeleton: ReverseCausalSkeleton,
    *,
    scene_id: str | None,
    completed_scene_ids: list[str] | None,
    strict: bool,
) -> CausalReadiness:
    normalized_anchor_pairs = [
        (_normalized_scene_id(link.scene_id), link)
        for link in skeleton.chain
    ]
    anchors = [anchor for anchor, _link in normalized_anchor_pairs if anchor is not None]
    duplicate_anchors = sorted({anchor for anchor in anchors if anchors.count(anchor) > 1})
    if duplicate_anchors:
        return _diagnostic_only_readiness(
            CausalDiagnostic(
                code="CAUSAL_ANCHORS_DUPLICATE",
                message="causal readiness was not evaluated because scene_id anchors are not unique",
                context={"duplicate_scene_ids": duplicate_anchors},
            )
        )

    normalized_target = _normalized_scene_id(scene_id)
    if normalized_target is None or completed_scene_ids is None:
        return _diagnostic_only_readiness(
            CausalDiagnostic(
                code="CAUSAL_ANCHORED_CONTEXT_MISSING",
                message="scene_id readiness could not run because anchored scene context was incomplete",
                context={
                    "scene_id_present": normalized_target is not None,
                    "completed_scene_ids_present": completed_scene_ids is not None,
                },
            )
        )

    link_by_scene_id = {
        anchor: link for anchor, link in normalized_anchor_pairs if anchor is not None
    }
    target_link = link_by_scene_id.get(normalized_target)
    if target_link is None:
        return _diagnostic_only_readiness(
            CausalDiagnostic(
                code="CAUSAL_SCENE_NOT_ANCHORED",
                message="current scene is not represented by the fully anchored causal skeleton",
                context={"scene_id": normalized_target},
            )
        )

    completed_ids = {
        normalized
        for completed_scene_id in completed_scene_ids
        if (normalized := _normalized_scene_id(completed_scene_id)) is not None
    }
    completed_step_indices = {
        link.step_index
        for anchor, link in normalized_anchor_pairs
        if anchor in completed_ids
    }
    return _evaluate_readiness_by_step(
        skeleton,
        target_step_index=target_link.step_index,
        completed_step_indices=completed_step_indices,
        strict=strict,
        diagnostics=[],
    )


def _evaluate_readiness_by_step(
    skeleton: ReverseCausalSkeleton,
    *,
    target_step_index: int,
    completed_step_indices: set[int],
    strict: bool,
    diagnostics: list[CausalDiagnostic],
) -> CausalReadiness:

    by_index: dict[int, CausalLink] = {
        link.step_index: link for link in skeleton.chain
    }
    prereq_indices = _prerequisite_step_indices(
        skeleton,
        target_step_index=target_step_index,
        by_index=by_index,
    )

    unresolved: list[CausalGap] = []
    for idx in sorted(prereq_indices):
        if idx in completed_step_indices:
            continue
        link = by_index.get(idx)
        desc = link.description if link else f"step {idx}"
        why = link.why_necessary if link else ""
        unresolved.append(CausalGap(
            after_step=idx,
            missing_premise=desc,
            why=why,
        ))

    blocking = strict and len(unresolved) > 0
    return CausalReadiness(
        ready=not blocking,
        unresolved=unresolved,
        blocking=blocking,
        diagnostics=diagnostics,
    )


def _prerequisite_step_indices(
    skeleton: ReverseCausalSkeleton,
    *,
    target_step_index: int,
    by_index: dict[int, CausalLink],
) -> set[int]:
    prereq_indices: set[int] = set()

    def _collect_prereqs(idx: int) -> None:
        link = by_index.get(idx)
        if link is None or link.depends_on_index is None:
            return
        dependency = link.depends_on_index
        if dependency not in prereq_indices:
            prereq_indices.add(dependency)
            _collect_prereqs(dependency)

    if target_step_index in by_index:
        _collect_prereqs(target_step_index)
    else:
        prereq_indices = {
            link.step_index
            for link in skeleton.chain
            if link.step_index < target_step_index
        }

    # Preserve the historical linear-chain behavior in both addressing modes.
    for link in skeleton.chain:
        if link.step_index < target_step_index:
            prereq_indices.add(link.step_index)
    return prereq_indices


def _diagnostic_only_readiness(
    *diagnostics: CausalDiagnostic,
) -> CausalReadiness:
    return CausalReadiness(
        ready=True,
        unresolved=[],
        blocking=False,
        diagnostics=list(diagnostics),
    )


def _normalized_scene_id(scene_id: Any) -> str | None:
    if not isinstance(scene_id, str):
        return None
    normalized = scene_id.strip()
    return normalized or None


def format_causal_readiness_warning(readiness: CausalReadiness) -> str:
    """Render unresolved causal prerequisites as a prompt-injectable warning.

    Returns an empty string when there are no unresolved items, matching the
    convention used by :func:`format_causal_gaps_for_prompt`.
    """
    if not readiness.unresolved:
        return ""
    severity = "CAUSAL BLOCK" if readiness.blocking else "CAUSAL WARNING"
    lines = [f"[{severity}] 本场景有未满足的因果前提："]
    for gap in readiness.unresolved:
        detail = f"步骤{gap.after_step}中{gap.missing_premise}"
        if gap.why:
            detail += f"（{gap.why}）"
        detail += "尚未完成"
        lines.append(f"  - {detail}")
    if readiness.blocking:
        lines.append("生成被阻断——请先完成上述前置场景。")
    else:
        lines.append("请注意不要预设这些事件已发生。")
    return "\n".join(lines)
