"""Reflexion-style auto-critique pass — blueprint §8.

Independent 'editor' that reviews generated text against an AI-taste checklist
and produces targeted rewrite directives. Runs AFTER best-of-N selection,
BEFORE soft QC — giving the model a chance to self-correct before external QC.

Rule-based mode (``auto_critique``) is a pure-function service; no LLM calls.
LLM-augmented mode (``llm_auto_critique``) merges rule-based findings with a
semantic critic LLM pass for deeper, context-aware feedback.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

from novel_system.services.literary_quality import (
    ADVERSARIAL_DIMS,
    analyze_literary_quality,
)

CRITIQUE_THRESHOLD = 0.3

CRITIQUE_DIMS: tuple[str, ...] = (
    "perception_filter",
    "model_voice",
    "false_clarity",
    "over_explained_motive",
    "expository_dialogue",
    "syntax_monotony",
    "self_repetition",
    "decorative_imagery",
    "false_poetic_closure",
    "dialogue_as_report",
    "template_action_reuse",
    "repetitive_action",
    "image_homogeneity",
    "image_field_reuse",
    # §4/§8: cost & conflict dimensions (previously existed but not in critique loop)
    "painless_scene",
    "no_choice_scene",
    "choice_pressure",
    # §8: new conflict-too-clean detector
    "conflict_too_clean",
)

_DIRECTIVE_MAP: dict[str, str] = {
    "perception_filter": (
        "Remove perception filter words (她觉得/他看到/她意识到/她感到). "
        "Show directly, don't filter through character awareness."
    ),
    "model_voice": (
        "Reduce generic AI-prose patterns. Make word choices specific and unexpected."
    ),
    "false_clarity": (
        "Remove false emotional clarity. Characters should not neatly understand "
        "their own feelings mid-scene."
    ),
    "over_explained_motive": (
        "Cut explicit motive explanations. Let actions speak for themselves."
    ),
    "expository_dialogue": (
        "Characters are lecturing. Make dialogue serve character, not exposition."
    ),
    "syntax_monotony": (
        "Vary sentence structures. Current rhythm is too regular — "
        "mix short/long, fragment/complex."
    ),
    "self_repetition": (
        "Repeated expressions from previous scenes detected. Find fresh alternatives."
    ),
    "decorative_imagery": (
        "Imagery is decorative, not functional. Every image should carry narrative meaning."
    ),
    "false_poetic_closure": (
        "Ending wraps up too neatly. Leave productive ambiguity or unresolved tension."
    ),
    "dialogue_as_report": (
        "Dialogue reads like a report. Characters should withhold, deflect, or reveal "
        "through subtext, not state facts plainly."
    ),
    "template_action_reuse": (
        "Action descriptions use template phrases. Replace with specific, observed detail."
    ),
    "repetitive_action": (
        "Same physical actions repeat across passages. Vary the repertoire."
    ),
    "image_homogeneity": (
        "Sensory imagery draws from a narrow field. Introduce contrast across senses."
    ),
    "image_field_reuse": (
        "Same image domain reused. Reach into a different sensory or metaphoric field."
    ),
    "painless_scene": (
        "Scene lacks cost or consequence. Every meaningful choice must cost something — "
        "a relationship strained, a secret exposed, comfort sacrificed. "
        "Add what the character loses by acting."
    ),
    "no_choice_scene": (
        "Scene has no moment of choice. Characters drift through events without deciding. "
        "Force a fork: the character must choose, and the choice must be visible."
    ),
    "choice_pressure": (
        "Choice lacks pressure. The character decides too easily — no competing desires, "
        "no time constraint, no cost either way. Add what makes this choice hard."
    ),
    "conflict_too_clean": (
        "Conflict resolves too cleanly. Characters should NOT understand each other "
        "this quickly. Leave residual friction: an unspoken resentment, a half-lie "
        "accepted, or agreement that costs something the character didn't want to give. "
        "Real conflict leaves scars even when it 'resolves'."
    ),
}


@dataclass(slots=True)
class CritiqueResult:
    should_rewrite: bool
    directives: list[str] = field(default_factory=list)
    dimension_scores: dict[str, float] = field(default_factory=dict)
    flagged_dimensions: list[str] = field(default_factory=list)


def auto_critique(
    text: str,
    *,
    skip_critique: bool = False,
    threshold: float = CRITIQUE_THRESHOLD,
    previous_scenes_text: str | None = None,
) -> CritiqueResult:
    """Run adversarial-metric critique and return rewrite directives.

    Parameters
    ----------
    text:
        The style-draft content to critique.
    skip_critique:
        If True (transition scenes), return an empty pass-through result.
    threshold:
        Dimensions with score **at or below** this value are flagged.
        Score semantics: 1.0 = clean, 0.0 = fully triggered.
    previous_scenes_text:
        Optional prior-scene text for self-repetition context (not used
        by this function directly — the underlying ``analyze_literary_quality``
        operates on the single text; cross-scene repetition is handled by the
        separate ``self_repetition`` module wired through ``external_signals``).
    """
    if skip_critique or not text or not text.strip():
        return CritiqueResult(should_rewrite=False)

    signals, _ = analyze_literary_quality(text)

    dimension_scores: dict[str, float] = {}
    flagged: list[str] = []
    directives: list[str] = []

    for dim in CRITIQUE_DIMS:
        sig = signals.get(dim)
        if sig is None:
            continue
        score = sig.get("score", 1.0)
        dimension_scores[dim] = score
        if score <= threshold:
            flagged.append(dim)
            directive = _DIRECTIVE_MAP.get(dim)
            if directive:
                evidence = sig.get("evidence", "")
                if evidence:
                    directives.append(f"{directive} (evidence: {evidence[:120]})")
                else:
                    directives.append(directive)

    return CritiqueResult(
        should_rewrite=len(directives) > 0,
        directives=directives,
        dimension_scores=dimension_scores,
        flagged_dimensions=flagged,
    )


def format_critique_brief(result: CritiqueResult) -> list[str]:
    """Format critique directives as a rewrite brief list (compatible with patch/rewrite APIs)."""
    if not result.should_rewrite:
        return []
    header = (
        "## Auto-Critique (reflexion pass — blueprint §8)\n"
        "The following AI-taste issues were detected. Revise accordingly:\n"
    )
    return [header] + result.directives


# ---------------------------------------------------------------------------
# LLM critic — blueprint §8 "independent editor role"
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class SceneContext:
    """Context for the LLM critic to make richer judgments."""
    scene_goal: str = ""
    tension_target: int | None = None
    character_briefs: list[dict[str, str]] = field(default_factory=list)
    cost_requirement: str = ""


CRITIC_SYSTEM_PROMPT: str = """\
You are an independent fiction editor.  Your role is to perform a semantic
critique of a scene draft.  You are NOT the writer — you are a cold reader
who checks whether the scene actually achieves its dramatic goals on the page.

Your critique dimensions (check each one):

1. **Character consistency** — Does any character act in a way that
   contradicts their established personality, knowledge, or emotional state?
   Flag specific lines where the character seems to break voice.

2. **Earned emotion** — Is every emotional beat set up by prior action,
   pressure, or revealed information?  Flag any emotion that appears without
   a visible cause or that escalates faster than the scene has earned.

3. **Conflict credibility** — Does the central conflict of the scene resolve
   too easily, without the character paying a real cost?  A conflict that
   evaporates, gets talked away, or is solved by coincidence is a problem.

4. **Information dumping** — Is exposition delivered through dialogue ("as
   you know" patterns), internal monologue dumps, or narrator asides that
   stop the scene?  The reader should learn facts through pressure, not
   lecture.

5. **Show vs. tell** — Does the draft describe an emotional state
   ("she felt angry") instead of rendering it through action, body
   language, dialogue subtext, or environmental reaction?

6. **Pacing** — Given the scene's tension target, is the pacing
   appropriate?  A high-tension scene that lingers on atmospheric
   description is too slow; a quiet aftermath scene that rushes through
   reflection is too fast.

Respond in JSON with this exact schema:

{
  "should_rewrite": true/false,
  "issues": [
    {
      "dimension": "<one of: character_consistency | earned_emotion | conflict_credibility | information_dumping | show_vs_tell | pacing>",
      "directive": "<specific rewrite instruction for the writer>",
      "evidence": "<quote or paraphrase of the problematic passage>"
    }
  ]
}

Rules:
- Only report genuine problems.  Do not pad the list.
- If the scene is clean, return {"should_rewrite": false, "issues": []}.
- Keep each directive actionable and under 80 words.
- Quote or closely paraphrase the offending text in "evidence".
- Do NOT suggest style preferences — only flag craft failures.
- "dimension" must be exactly one of the six values listed above, lowercase with underscores — do not invent a new dimension name.
- Return ONLY the JSON object above: no markdown fences, no prose before or after it.
"""

CRITIC_TASK_PROMPT_TEMPLATE: str = """\
## Scene context

{scene_context_block}

## Scene text to critique

{text}
"""

_LLM_CRITIC_DIMENSIONS = frozenset({
    "character_consistency", "earned_emotion", "conflict_credibility",
    "information_dumping", "show_vs_tell", "pacing",
})


def llm_auto_critique(
    text: str,
    scene_context: SceneContext | None = None,
    *,
    session: Any | None = None,
    llm_runner: Any | None = None,
    skip_critique: bool = False,
) -> CritiqueResult:
    """Run the hybrid rule-based + LLM critique pipeline.

    Always runs the rule-based pass.  When *llm_runner* is provided and
    *skip_critique* is ``False``, also calls an LLM critic and merges
    the results (deduplicated by dimension).
    """
    rule_result = auto_critique(text, skip_critique=skip_critique)

    if skip_critique or llm_runner is None:
        return rule_result

    context_block = _format_scene_context(scene_context)
    task_prompt = CRITIC_TASK_PROMPT_TEMPLATE.format(
        scene_context_block=context_block,
        text=text,
    )

    try:
        response = llm_runner.run_task(
            task_name="auto_critique_llm",
            prompt_text=task_prompt,
            system_prompt=CRITIC_SYSTEM_PROMPT,
        )
    except Exception:
        logger.warning("LLM critic call failed; returning rule-only result", exc_info=True)
        return rule_result

    llm_parsed = _parse_llm_response(response)
    llm_issues = llm_parsed.get("issues") or []
    llm_should_rewrite = bool(llm_parsed.get("should_rewrite", False))

    # Merge: rule-based first, then LLM (deduplicated by dimension)
    merged_directives = list(rule_result.directives)
    seen_dims = {d for d in rule_result.flagged_dimensions}
    for issue in llm_issues:
        dim = issue.get("dimension", "llm_general")
        if dim not in _LLM_CRITIC_DIMENSIONS:
            dim = "llm_general"
        if dim not in seen_dims:
            directive_text = issue.get("directive", "")
            evidence = issue.get("evidence", "")
            if directive_text:
                entry = f"[LLM·{dim}] {directive_text}"
                if evidence:
                    entry += f" (evidence: {evidence[:120]})"
                merged_directives.append(entry)
                seen_dims.add(dim)

    return CritiqueResult(
        should_rewrite=rule_result.should_rewrite or llm_should_rewrite,
        directives=merged_directives,
        dimension_scores=rule_result.dimension_scores,
        flagged_dimensions=list(seen_dims),
    )


def _format_scene_context(ctx: SceneContext | None) -> str:
    if ctx is None:
        return "(No scene context provided.)"
    parts: list[str] = []
    if ctx.scene_goal:
        parts.append(f"- **Scene goal**: {ctx.scene_goal}")
    if ctx.tension_target is not None:
        parts.append(f"- **Tension target**: {ctx.tension_target}/10")
    if ctx.cost_requirement:
        parts.append(f"- **Cost requirement**: {ctx.cost_requirement}")
    if ctx.character_briefs:
        for brief in ctx.character_briefs:
            name = brief.get("name", "Unknown")
            traits = brief.get("traits", "")
            line = f"- **Character — {name}**: traits={traits}"
            emotional_state = brief.get("emotional_state", "")
            if emotional_state:
                line += f"; emotional_state={emotional_state}"
            parts.append(line)
    return "\n".join(parts) if parts else "(No scene context provided.)"


def _parse_llm_response(response: Any) -> dict[str, Any]:
    """Extract JSON from an LLM response object."""
    try:
        if hasattr(response, "structured_output") and response.structured_output:
            return response.structured_output
        raw = getattr(response, "text", "") or ""
        # Strip markdown code fences if present
        raw = raw.strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[-1]
            if raw.endswith("```"):
                raw = raw[:-3]
        return json.loads(raw.strip())
    except (json.JSONDecodeError, TypeError, AttributeError):
        logger.warning("Failed to parse LLM critic response", exc_info=True)
        return {}
