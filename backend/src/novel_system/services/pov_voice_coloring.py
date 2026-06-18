"""POV voice coloring — blueprint §2 deep POV requirement.

When the viewpoint character changes, the narration style should shift:
same event narrated from different POV characters should use different
word choices, rhythms, and attention focus. This is 自由间接引语 (free
indirect discourse).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class PovColoringDirective:
    pov_character_id: str
    narration_guidance: str
    attention_focus: list[str]
    vocabulary_tone: str
    rhythm_hint: str


_ARCHETYPE_TRAITS: dict[str, dict[str, Any]] = {
    "warrior": {
        "attention": ["threats", "exits", "weapons", "tactical advantages", "body language signaling danger"],
        "tone": "direct, clipped, tactile",
        "rhythm": "short decisive sentences; action verbs over state verbs",
    },
    "scholar": {
        "attention": ["patterns", "anomalies", "historical parallels", "word choices of others"],
        "tone": "precise, analytical, layered",
        "rhythm": "complex sentences with subordinate clauses; measured pacing",
    },
    "healer": {
        "attention": ["injuries", "symptoms", "emotional states", "breathing patterns", "skin color"],
        "tone": "gentle, observant, empathetic",
        "rhythm": "flowing contemplative sentences; sensory detail weighted toward touch and smell",
    },
    "politician": {
        "attention": ["power dynamics", "unspoken agendas", "alliances", "who defers to whom"],
        "tone": "calculating, layered with subtext",
        "rhythm": "sentences that withhold as much as they reveal; ironic undertones",
    },
    "child": {
        "attention": ["colors", "sounds", "emotions on faces", "things that are unfair or confusing"],
        "tone": "concrete, immediate, emotionally transparent",
        "rhythm": "short simple sentences punctuated by sudden long wondering ones",
    },
}

_ROLE_KEYWORD_MAP: dict[str, str] = {
    "军": "warrior", "将": "warrior", "兵": "warrior", "侠": "warrior", "武": "warrior",
    "剑": "warrior", "战": "warrior", "knight": "warrior", "soldier": "warrior",
    "医": "healer", "药": "healer", "治": "healer", "heal": "healer", "doctor": "healer",
    "书": "scholar", "学": "scholar", "师": "scholar", "谋": "scholar", "scholar": "scholar",
    "官": "politician", "王": "politician", "臣": "politician", "相": "politician",
    "孩": "child", "童": "child", "幼": "child", "child": "child",
}


def build_pov_coloring(
    pov_character_id: str,
    voice_card_content: str | None,
    character_bible_json: dict[str, Any] | None,
) -> PovColoringDirective:
    bible = character_bible_json or {}
    voice = voice_card_content or ""

    archetype = _detect_archetype(pov_character_id, voice, bible)
    traits = _ARCHETYPE_TRAITS.get(archetype, {})

    attention = list(traits.get("attention", []))
    bible_focus = _extract_attention_from_bible(bible)
    if bible_focus:
        attention = bible_focus + [a for a in attention if a not in bible_focus]

    vocab_tone = _extract_vocabulary_tone(voice, bible) or traits.get("tone", "neutral, grounded")
    rhythm = _extract_rhythm_hint(voice, bible) or traits.get("rhythm", "varied sentence lengths; natural pacing")

    guidance = _build_narration_guidance(pov_character_id, voice, bible, vocab_tone)

    return PovColoringDirective(
        pov_character_id=pov_character_id,
        narration_guidance=guidance,
        attention_focus=attention[:6],
        vocabulary_tone=vocab_tone,
        rhythm_hint=rhythm,
    )


def format_pov_coloring_prompt(directive: PovColoringDirective) -> str:
    lines = [
        "## POV Voice Coloring (自由间接引语)",
        f"Viewpoint character: **{directive.pov_character_id}**",
        "",
        directive.narration_guidance,
        "",
        "**Attention focus** — this character instinctively notices:",
    ]
    for focus in directive.attention_focus:
        lines.append(f"  - {focus}")

    lines.extend([
        "",
        f"**Vocabulary & tone**: {directive.vocabulary_tone}",
        f"**Sentence rhythm**: {directive.rhythm_hint}",
        "",
        f"Even in third-person narration, the prose should feel filtered through "
        f"{directive.pov_character_id}'s consciousness. "
        f"Test: remove the character name — can the reader still tell whose POV this is?",
    ])
    return "\n".join(lines)


def _build_narration_guidance(
    character_id: str,
    voice: str,
    bible: dict[str, Any],
    vocab_tone: str,
) -> str:
    parts = [
        f"The narration should reflect {character_id}'s worldview and perception patterns.",
        "Word choices, rhythm, and what details are noticed should be consistent "
        "with this character's personality and background.",
    ]

    occupation = bible.get("occupation") or bible.get("role") or bible.get("职业")
    if occupation:
        parts.append(f"This character's background as {occupation} colors how they interpret the world.")

    fear = bible.get("core_fear") or bible.get("核心恐惧")
    need = bible.get("core_need") or bible.get("核心需求")
    if fear:
        parts.append(f"Underlying fear ({fear}) subtly biases perception — what they dread, they notice first.")
    if need:
        parts.append(f"Core need ({need}) shapes what they seek in every interaction.")

    if voice:
        voice_snippet = voice[:300].strip()
        if voice_snippet:
            parts.append(f"Voice card reference (for narration tone, not just dialogue): {voice_snippet}")

    return " ".join(parts)


def _detect_archetype(character_id: str, voice: str, bible: dict[str, Any]) -> str:
    search_text = " ".join([
        character_id,
        str(bible.get("role", "")),
        str(bible.get("occupation", "")),
        str(bible.get("职业", "")),
        str(bible.get("summary", "")),
        voice[:200],
    ]).lower()

    for keyword, archetype in _ROLE_KEYWORD_MAP.items():
        if keyword in search_text:
            return archetype
    return ""


def _extract_attention_from_bible(bible: dict[str, Any]) -> list[str]:
    result: list[str] = []
    for key in ("perception_habits", "attention_focus", "感知习惯", "注意力焦点"):
        val = bible.get(key)
        if isinstance(val, list):
            result.extend(str(v) for v in val[:4])
        elif isinstance(val, str) and val.strip():
            result.extend(s.strip() for s in re.split(r"[,;，；、]", val) if s.strip())
    return result[:6]


def _extract_vocabulary_tone(voice: str, bible: dict[str, Any]) -> str:
    for key in ("vocabulary_tone", "语言风格", "speech_style", "说话风格"):
        val = bible.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()[:100]
    if voice:
        tone_match = re.search(r"(?:tone|语气|风格)[：:]\s*(.+?)(?:\n|$)", voice, re.IGNORECASE)
        if tone_match:
            return tone_match.group(1).strip()[:100]
    return ""


def _extract_rhythm_hint(voice: str, bible: dict[str, Any]) -> str:
    for key in ("rhythm_hint", "句式特征", "sentence_style"):
        val = bible.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()[:120]
    if voice:
        rhythm_match = re.search(r"(?:rhythm|节奏|句式)[：:]\s*(.+?)(?:\n|$)", voice, re.IGNORECASE)
        if rhythm_match:
            return rhythm_match.group(1).strip()[:120]
    return ""
