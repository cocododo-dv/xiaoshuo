"""Three-layer character psychology model — blueprint §11.

Layers:
  Surface  — observable behavior (speech style, body language, social default)
  Middle   — psychological drivers (core need, core fear, coping mechanism)
  Deep     — subconscious / authored intent (childhood wound, inner contradiction, growth direction)

The deep layer is supplied by the human author and should INFORM generated behavior
but never be stated explicitly in the prose.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class SurfaceLayer:
    speech_style: str
    body_language: list[str]
    social_default: str


@dataclass(slots=True)
class MiddleLayer:
    core_need: str
    core_fear: str
    coping_mechanism: str


@dataclass(slots=True)
class DeepLayer:
    childhood_wound: str
    inner_contradiction: str
    growth_direction: str


@dataclass(slots=True)
class CharacterPsychology:
    character_id: str
    surface: SurfaceLayer
    middle: MiddleLayer
    deep: DeepLayer


def extract_psychology_from_bible(
    character_id: str,
    bible_json: dict[str, Any] | None,
) -> CharacterPsychology:
    b = bible_json or {}

    speech_style = _first(b, "speech_style", "说话方式", "说话风格") or "not specified"
    body_raw = _first(b, "body_language", "肢体语言", "肢体语言习惯")
    body_language = _to_list(body_raw) if body_raw else []
    social_default = _first(b, "social_default", "社交默认", "社交默认模式") or "neutral"

    core_need = _first(b, "core_need", "核心需求") or "not specified"
    core_fear = _first(b, "core_fear", "核心恐惧") or "not specified"
    coping = _first(b, "coping_mechanism", "应对机制", "coping") or "not specified"

    wound = _first(b, "childhood_wound", "童年创伤", "wound") or "not specified"
    contradiction = _first(b, "inner_contradiction", "内在矛盾") or "not specified"
    growth = _first(b, "growth_direction", "成长方向") or "not specified"

    return CharacterPsychology(
        character_id=character_id,
        surface=SurfaceLayer(
            speech_style=speech_style,
            body_language=body_language,
            social_default=social_default,
        ),
        middle=MiddleLayer(
            core_need=core_need,
            core_fear=core_fear,
            coping_mechanism=coping,
        ),
        deep=DeepLayer(
            childhood_wound=wound,
            inner_contradiction=contradiction,
            growth_direction=growth,
        ),
    )


def format_psychology_prompt(
    psych: CharacterPsychology,
    *,
    tension_level: int | None = None,
) -> str:
    lines = [
        f"## Character Psychology Model (§11 — {psych.character_id})",
        "",
        "### Surface Layer (observable behavior)",
        f"- Speech style: {psych.surface.speech_style}",
    ]
    if psych.surface.body_language:
        lines.append(f"- Body language habits: {', '.join(psych.surface.body_language)}")
    lines.append(f"- Social default mode: {psych.surface.social_default}")

    lines.extend([
        "",
        "### Middle Layer (psychological drivers — shape decisions and reactions)",
        f"- Core need: {psych.middle.core_need}",
        f"- Core fear: {psych.middle.core_fear}",
        f"- Coping mechanism: {psych.middle.coping_mechanism}",
    ])

    if tension_level is not None and tension_level >= 7:
        lines.append(
            "  ⚠ HIGH TENSION — the coping mechanism is under extreme stress. "
            "Show it cracking, failing, or being abandoned under pressure."
        )

    lines.extend([
        "",
        "### Deep Layer (author's private design — NEVER state directly)",
        f"- Childhood wound: {psych.deep.childhood_wound}",
        f"- Inner contradiction: {psych.deep.inner_contradiction}",
        f"- Growth direction: {psych.deep.growth_direction}",
        "",
        "Deep layer drives behavior but is NEVER explained or named in the text. "
        "The character does not understand their own wound — the reader discovers it "
        "through accumulated actions, not through narration or dialogue.",
    ])

    return "\n".join(lines)


def _first(d: dict[str, Any], *keys: str) -> str | None:
    for k in keys:
        val = d.get(k)
        if isinstance(val, str) and val.strip():
            return val.strip()
        if isinstance(val, list) and val:
            return ", ".join(str(v) for v in val)
    return None


def _to_list(val: Any) -> list[str]:
    if isinstance(val, list):
        return [str(v).strip() for v in val if str(v).strip()]
    if isinstance(val, str):
        return [s.strip() for s in re.split(r"[,;，；、/]", val) if s.strip()]
    return []
