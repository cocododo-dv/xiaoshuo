from __future__ import annotations

import copy
import math
from dataclasses import dataclass
from typing import Any, Mapping

from novel_system.services.hash_engine import normalize


@dataclass(slots=True)
class PromptSection:
    name: str
    label: str
    text: str
    status: str = "included"
    compressed_text: str | None = None

    @property
    def effective_text(self) -> str:
        if self.status == "compressed" and self.compressed_text is not None:
            return self.compressed_text
        return self.text


SECTION_SPECS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("chapter_goal", "Chapter Goal", ("chapter_goal",)),
    ("scene_card", "Scene Card", ("scene_card",)),
    ("character_contract", "Character Continuity Contract", ("character_contract",)),
    ("pov_voice", "POV Voice", ("voice_card",)),
    ("style_profile", "Style Feature Contract", ("style_profile", "style_feature_contract")),
    ("style_rules", "Style Rules", ("style_rule",)),
    ("banned_rules", "Banned Rules", ("banned_rule",)),
    ("open_foreshadow", "Open Foreshadow", ("foreshadow",)),
    ("similar_scene_context", "Similar Scene Context", ("similar_scene", "similar_scene_context")),
    ("style_observations", "Style Observations", ("style_observation", "style_observations")),
    ("calibration_lines", "Calibration Lines", ("calibration_line", "calibration_lines")),
    ("relation_digest", "Relation Digest", ("relation_card", "relation_digest")),
    ("world_rules", "World Rules", ("world_rule", "world_rules")),
    ("scene_memory_digest", "Previous Scene Memory", ("scene_memory", "scene_memory_digest")),
    ("scene_summary", "Scene Summary", ("scene_summary",)),
    ("chapter_summary", "Chapter Summary", ("chapter_summary",)),
)

CONTINUITY_DROP_ORDER: tuple[str, ...] = (
    "relation_digest",
    "world_rules",
    "scene_memory_digest",
)

CONTINUITY_POLICY: list[str] = [
    "drop_similar_scene_context",
    "drop_raw_style_rules_when_style_profile_exists",
    "compress_style_observations",
    "drop_calibration_lines",
    "drop_relation_world_memory_digests",
    "split_scene_recommendation",
]


def collect_prompt_sections(bundle_snapshot: Mapping[str, Any]) -> list[PromptSection]:
    inline_digests = bundle_snapshot.get("inline_digests")
    if not isinstance(inline_digests, Mapping):
        return []

    sections: list[PromptSection] = []
    for name, label, digest_keys in SECTION_SPECS:
        text = _first_text(inline_digests, digest_keys)
        if text is None:
            continue
        sections.append(PromptSection(name=name, label=label, text=text))
    return sections


def apply_context_budget(
    *,
    system_prompt: str,
    task_prompt: str,
    bundle_snapshot: Mapping[str, Any],
    sections: list[PromptSection],
    max_input_tokens: int,
) -> dict[str, Any]:
    budget = {
        "target_input_tokens": max_input_tokens,
        "estimated_input_tokens": 0,
        "remaining_input_tokens": 0,
        "included_sections": [],
        "compressed_sections": [],
        "omitted_sections": [],
        "section_status": {},
        "continuity_policy": list(CONTINUITY_POLICY),
        "split_scene_recommended": False,
        "stop_reason": None,
        "continuity_warning": None,
    }
    section_lookup = {section.name: section for section in sections}

    if _rendered_prompt_tokens(
        system_prompt=system_prompt,
        task_prompt=task_prompt,
        bundle_snapshot=bundle_snapshot,
        sections=sections,
        split_scene_recommended=False,
    ) > max_input_tokens:
        similar_scene = section_lookup.get("similar_scene_context")
        if similar_scene is not None:
            similar_scene.status = "omitted"

        if _rendered_prompt_tokens(
            system_prompt=system_prompt,
            task_prompt=task_prompt,
            bundle_snapshot=bundle_snapshot,
            sections=sections,
            split_scene_recommended=False,
        ) > max_input_tokens:
            style_rules = section_lookup.get("style_rules")
            style_profile = section_lookup.get("style_profile")
            if style_rules is not None and style_profile is not None:
                style_rules.status = "omitted"

        if _rendered_prompt_tokens(
            system_prompt=system_prompt,
            task_prompt=task_prompt,
            bundle_snapshot=bundle_snapshot,
            sections=sections,
            split_scene_recommended=False,
        ) > max_input_tokens:
            style_observations = section_lookup.get("style_observations")
            if style_observations is not None:
                style_observations.compressed_text = _compress_style_observations(style_observations.text)
                style_observations.status = "compressed"

        if _rendered_prompt_tokens(
            system_prompt=system_prompt,
            task_prompt=task_prompt,
            bundle_snapshot=bundle_snapshot,
            sections=sections,
            split_scene_recommended=False,
        ) > max_input_tokens:
            calibration_lines = section_lookup.get("calibration_lines")
            if calibration_lines is not None:
                _apply_compressed_text(calibration_lines, _compress_calibration_lines(calibration_lines.text))

        for section_name in CONTINUITY_DROP_ORDER:
            if _rendered_prompt_tokens(
                system_prompt=system_prompt,
                task_prompt=task_prompt,
                bundle_snapshot=bundle_snapshot,
                sections=sections,
                split_scene_recommended=False,
            ) <= max_input_tokens:
                break
            section = section_lookup.get(section_name)
            if section is not None:
                _apply_compressed_text(section, _compress_continuity_digest(section.text))

        if _rendered_prompt_tokens(
            system_prompt=system_prompt,
            task_prompt=task_prompt,
            bundle_snapshot=bundle_snapshot,
            sections=sections,
            split_scene_recommended=False,
        ) > max_input_tokens:
            budget["split_scene_recommended"] = True
            budget["stop_reason"] = "split_scene_recommended"

    _finalize_budget(
        budget=budget,
        system_prompt=system_prompt,
        task_prompt=task_prompt,
        bundle_snapshot=bundle_snapshot,
        sections=sections,
    )
    budget["continuity_warning"] = _build_continuity_warning(budget)
    user_prompt = render_user_prompt(
        task_prompt=task_prompt,
        bundle_snapshot=bundle_snapshot,
        sections=sections,
        budget=budget,
    )
    return {
        "budget": budget,
        "user_prompt": user_prompt,
        "continuity_warning": budget["continuity_warning"],
    }


def finalize_request_budget(
    *,
    system_prompt: str,
    user_prompt: str,
    base_budget: Mapping[str, Any],
) -> dict[str, Any]:
    budget = copy.deepcopy(dict(base_budget))
    budget["estimated_input_tokens"] = estimate_tokens(system_prompt) + estimate_tokens(user_prompt)
    budget["remaining_input_tokens"] = budget["target_input_tokens"] - budget["estimated_input_tokens"]
    if budget["estimated_input_tokens"] > budget["target_input_tokens"]:
        budget["split_scene_recommended"] = True
        budget["stop_reason"] = "split_scene_recommended"
    budget["continuity_warning"] = _build_continuity_warning(budget)
    return {
        "budget": budget,
        "continuity_warning": budget["continuity_warning"],
    }


def render_user_prompt(
    *,
    task_prompt: str,
    bundle_snapshot: Mapping[str, Any],
    sections: list[PromptSection],
    budget: Mapping[str, Any],
) -> str:
    prompt_parts = [
        task_prompt,
        "",
        f"Scene ID: {bundle_snapshot.get('scene_id', '')}",
        f"Chapter ID: {bundle_snapshot.get('chapter_id', '')}",
        f"Bundle Contract: {bundle_snapshot.get('contract_version', '')}",
        f"Stage Allowlist: {bundle_snapshot.get('stage_allowlist_name', '')}",
    ]
    if budget.get("split_scene_recommended"):
        prompt_parts.extend(
            [
                "",
                "Split-scene recommendation: continuity still exceeds the configured prompt budget after deterministic compaction.",
            ]
        )

    for section in sections:
        if section.status == "omitted":
            continue
        heading = section.label
        if section.status == "compressed":
            heading = f"{heading} (compressed)"
        prompt_parts.extend(["", f"## {heading}", section.effective_text])

    prompt_parts.extend(["", "Return JSON that matches the structured schema exactly."])
    return "\n".join(prompt_parts).strip()


def estimate_tokens(text: str) -> int:
    normalized_text = _normalize_text(text)
    if not normalized_text:
        return 0
    return max(1, math.ceil(len(normalized_text) / 4))


def _finalize_budget(
    *,
    budget: dict[str, Any],
    system_prompt: str,
    task_prompt: str,
    bundle_snapshot: Mapping[str, Any],
    sections: list[PromptSection],
) -> None:
    budget["included_sections"] = []
    budget["compressed_sections"] = []
    budget["omitted_sections"] = []
    budget["section_status"] = {}
    budget["estimated_input_tokens"] = _rendered_prompt_tokens(
        system_prompt=system_prompt,
        task_prompt=task_prompt,
        bundle_snapshot=bundle_snapshot,
        sections=sections,
        split_scene_recommended=bool(budget["split_scene_recommended"]),
    )
    budget["remaining_input_tokens"] = budget["target_input_tokens"] - budget["estimated_input_tokens"]
    for section in sections:
        budget["section_status"][section.name] = {
            "label": section.label,
            "status": section.status,
            "estimated_tokens": estimate_tokens(section.effective_text) if section.status != "omitted" else 0,
        }
        if section.status == "included":
            budget["included_sections"].append(section.name)
        elif section.status == "compressed":
            budget["compressed_sections"].append(section.name)
        elif section.status == "omitted":
            budget["omitted_sections"].append(section.name)


def _build_continuity_warning(budget: Mapping[str, Any]) -> dict[str, Any] | None:
    if not budget.get("split_scene_recommended"):
        return None
    return {
        "code": "continuity_budget_exceeded",
        "message": "Prompt still exceeds the safe input budget after deterministic continuity compaction.",
        "recommended_action": "split_scene",
        "requires_scene_split": True,
        "compressed_sections": list(budget.get("compressed_sections", [])),
        "omitted_sections": list(budget.get("omitted_sections", [])),
        "estimated_input_tokens": int(budget.get("estimated_input_tokens", 0)),
        "target_input_tokens": int(budget.get("target_input_tokens", 0)),
    }


def _rendered_prompt_tokens(
    *,
    system_prompt: str,
    task_prompt: str,
    bundle_snapshot: Mapping[str, Any],
    sections: list[PromptSection],
    split_scene_recommended: bool,
) -> int:
    rendered_prompt = render_user_prompt(
        task_prompt=task_prompt,
        bundle_snapshot=bundle_snapshot,
        sections=sections,
        budget={"split_scene_recommended": split_scene_recommended},
    )
    return estimate_tokens(system_prompt) + estimate_tokens(rendered_prompt)


def _compress_style_observations(text: str) -> str:
    blocks = _split_blocks(text)
    if len(blocks) > 3:
        return "\n\n".join(blocks[:3])
    tokens = _normalize_text(text).split()
    if len(tokens) <= 24:
        return _normalize_text(text)
    return " ".join(tokens[:24]) + " ..."


def _compress_calibration_lines(text: str) -> str:
    blocks = _split_blocks(text)
    if len(blocks) <= 1:
        return _normalize_text(text)
    return blocks[0]


def _compress_continuity_digest(text: str) -> str:
    blocks = _split_blocks(text)
    if len(blocks) > 1:
        return "\n\n".join(blocks[:1])
    tokens = _normalize_text(text).split()
    if len(tokens) <= 12:
        return _normalize_text(text)
    return " ".join(tokens[:12]) + " ..."


def _first_text(inline_digests: Mapping[str, Any], digest_keys: tuple[str, ...]) -> str | None:
    for digest_key in digest_keys:
        value = inline_digests.get(digest_key)
        if isinstance(value, str) and value.strip():
            return _normalize_text(value)
    return None


def _normalize_text(text: str) -> str:
    normalized = normalize(text)
    if not isinstance(normalized, str):
        raise ValueError("text must normalize to a string")
    return normalized


def _split_blocks(text: str) -> list[str]:
    return [block.strip() for block in _normalize_text(text).split("\n\n") if block.strip()]


def _apply_compressed_text(section: PromptSection, compressed_text: str) -> None:
    if _normalize_text(compressed_text) == _normalize_text(section.text):
        return
    section.compressed_text = compressed_text
    section.status = "compressed"
