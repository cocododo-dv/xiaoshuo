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


@dataclass(slots=True)
class CausalLink:
    """One link in the reverse causal chain."""
    step_index: int
    description: str
    why_necessary: str
    character_state_before: str
    character_state_after: str
    depends_on_index: int | None = None


@dataclass(slots=True)
class ReverseCausalSkeleton:
    controlling_idea: str
    ending_state: str
    chain: list[CausalLink] = field(default_factory=list)

    @property
    def opening_state(self) -> str | None:
        return self.chain[0].character_state_before if self.chain else None

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
) -> ReverseCausalSkeleton:
    """Build a reverse causal skeleton from ending to beginning.

    This is the offline/deterministic builder. When LLM is enabled, a separate
    LLM-powered version can refine the chain by asking "for this step to be
    credible, what must have happened before?"

    Args:
        controlling_idea: The one-sentence theme judgment (e.g., "残缺本身也可以是完整的")
        ending_description: What happens at the ending
        major_turning_points: Optional list of dicts with 'description' and 'why' keys,
            ordered from ending backward toward opening.
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
        ))

    skeleton.chain.append(CausalLink(
        step_index=len(skeleton.chain),
        description=ending_description,
        why_necessary=f"终局证明控制性理念: {controlling_idea}",
        character_state_before=skeleton.chain[-1].character_state_after if skeleton.chain else "",
        character_state_after="controlling idea proven",
        depends_on_index=len(skeleton.chain) - 1,
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

    def format_for_prompt(self) -> str:
        """Format unresolved prerequisites as a prompt-injectable warning."""
        return format_causal_readiness_warning(self)


def refine_skeleton_with_llm(
    skeleton: ReverseCausalSkeleton,
    *,
    llm_runner: Any | None = None,
) -> list[CausalGap]:
    """§4 逆向因果骨架 LLM 精炼: ask "for this step to be credible, what must precede it?".

    Opt-in (same pattern as llm_auto_critique / check_consistency_llm): when no
    llm_runner is supplied, returns no gaps (the deterministic builder stands alone).
    Returns ADVISORY gaps for the author to act on — does not mutate the skeleton, so a
    hallucinating refiner can never silently rewrite the causal spine.
    """
    if llm_runner is None or not skeleton.chain:
        return []

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
    scene_index: int,
    *,
    completed_scenes: list[int],
    strict: bool = False,
) -> CausalReadiness:
    """Check if all causal prerequisites for scene *scene_index* are satisfied.

    Walks the skeleton chain to find which :class:`CausalLink` entries are
    prerequisites for the given scene.  A link is a prerequisite when:

    1. Its ``step_index`` is less than *scene_index*, **and**
    2. There exists a later link whose ``depends_on_index`` equals its
       ``step_index`` and that later link's ``step_index`` equals
       *scene_index* — **or** the link is a transitive dependency of such
       a link.

    In the simpler (and more common) linear-chain case every link with
    ``step_index < scene_index`` is a prerequisite.

    A prerequisite is *satisfied* when its ``step_index`` appears in
    *completed_scenes*.

    Args:
        skeleton: The reverse causal skeleton for the project.
        scene_index: The scene about to be generated.
        completed_scenes: Indices of scenes already completed.
        strict: When True, unresolved prerequisites make the result
                *blocking* (``ready=False``).  When False the result is
                advisory (``ready=True``) even if prerequisites remain.

    Returns:
        :class:`CausalReadiness` with pass/block status and the list of
        unresolved prerequisites rendered as :class:`CausalGap` instances.
    """
    if not skeleton.chain:
        return CausalReadiness(ready=True, unresolved=[], blocking=False)

    completed = set(completed_scenes)

    # Build a quick index: step_index → CausalLink
    by_index: dict[int, CausalLink] = {
        link.step_index: link for link in skeleton.chain
    }

    # Collect direct prerequisite step indices for *scene_index* by walking
    # the dependency edges backward.
    prereq_indices: set[int] = set()

    def _collect_prereqs(idx: int) -> None:
        link = by_index.get(idx)
        if link is None or link.depends_on_index is None:
            return
        dep = link.depends_on_index
        if dep not in prereq_indices:
            prereq_indices.add(dep)
            _collect_prereqs(dep)

    # If *scene_index* itself is in the chain, walk its explicit deps.
    if scene_index in by_index:
        _collect_prereqs(scene_index)
    else:
        # scene_index not explicitly in the chain — treat every earlier
        # step as a prerequisite (linear-chain fallback).
        prereq_indices = {
            link.step_index for link in skeleton.chain
            if link.step_index < scene_index
        }

    # Also include any link that has step_index < scene_index whose
    # depends_on_index points to a link with step_index < scene_index,
    # when those links are not yet captured (handles chains where the
    # target scene is not the direct dependent but inherits the causal
    # need transitively through the linear ordering).
    for link in skeleton.chain:
        if link.step_index < scene_index:
            prereq_indices.add(link.step_index)

    # Determine which prerequisites are unresolved.
    unresolved: list[CausalGap] = []
    for idx in sorted(prereq_indices):
        if idx in completed:
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
    )


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
