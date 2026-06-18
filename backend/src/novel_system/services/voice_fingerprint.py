"""Structured voice fingerprint — blueprint §11.

Multi-layer schema for per-character voice identity:
  Syntax → Vocabulary → Pragmatic → Special markers
Hard constraint: "remove the character name, reader should still know who's speaking"
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class SyntaxLayer:
    avg_sentence_length: str = "medium (10-20 chars)"
    sentence_patterns: list[str] = field(default_factory=list)
    completeness: str = "complete"


@dataclass(slots=True)
class VocabularyLayer:
    domain_preferences: list[str] = field(default_factory=list)
    catchphrases: list[str] = field(default_factory=list)
    banned_words: list[str] = field(default_factory=list)
    formality: str = "mixed"


@dataclass(slots=True)
class PragmaticLayer:
    directness: str = "direct"
    information_density: str = "dense"
    discourse_strategy: str = ""


@dataclass(slots=True)
class SpecialMarkers:
    speech_defects: list[str] = field(default_factory=list)
    dialect_markers: list[str] = field(default_factory=list)
    verbal_habits: list[str] = field(default_factory=list)


@dataclass(slots=True)
class VoiceFingerprint:
    character_id: str
    syntax: SyntaxLayer = field(default_factory=SyntaxLayer)
    vocabulary: VocabularyLayer = field(default_factory=VocabularyLayer)
    pragmatic: PragmaticLayer = field(default_factory=PragmaticLayer)
    special: SpecialMarkers = field(default_factory=SpecialMarkers)


_LIST_KEYS_SYNTAX_PATTERNS = (
    "sentence_patterns", "句式特征", "句型偏好",
)
_LIST_KEYS_DOMAIN = (
    "domain_preferences", "领域词汇", "专业术语", "vocabulary_domain",
)
_LIST_KEYS_CATCHPHRASES = (
    "catchphrases", "口头禅", "verbal_tics", "口癖",
)
_LIST_KEYS_BANNED = (
    "banned_words", "禁用词汇", "forbidden_words", "不会说的词",
)
_LIST_KEYS_DEFECTS = (
    "speech_defects", "语病", "口吃", "speech_impediment",
)
_LIST_KEYS_DIALECT = (
    "dialect_markers", "方言标记", "dialect", "方言",
)
_LIST_KEYS_HABITS = (
    "verbal_habits", "语言习惯", "speech_habits", "说话习惯",
)


def extract_fingerprint_from_bible(
    character_id: str,
    bible_json: dict[str, Any] | None,
) -> VoiceFingerprint:
    bible = bible_json or {}

    syntax = SyntaxLayer(
        avg_sentence_length=_str_field(bible, ("avg_sentence_length", "平均句长", "sentence_length"), "medium (10-20 chars)"),
        sentence_patterns=_list_field(bible, _LIST_KEYS_SYNTAX_PATTERNS),
        completeness=_str_field(bible, ("completeness", "句式完整性"), "complete"),
    )

    vocabulary = VocabularyLayer(
        domain_preferences=_list_field(bible, _LIST_KEYS_DOMAIN),
        catchphrases=_list_field(bible, _LIST_KEYS_CATCHPHRASES),
        banned_words=_list_field(bible, _LIST_KEYS_BANNED),
        formality=_str_field(bible, ("formality", "正式程度", "语体"), "mixed"),
    )

    pragmatic = PragmaticLayer(
        directness=_str_field(bible, ("directness", "直接性", "说话方式"), "direct"),
        information_density=_str_field(bible, ("information_density", "信息密度"), "dense"),
        discourse_strategy=_str_field(bible, ("discourse_strategy", "话语策略", "对话策略"), ""),
    )

    special = SpecialMarkers(
        speech_defects=_list_field(bible, _LIST_KEYS_DEFECTS),
        dialect_markers=_list_field(bible, _LIST_KEYS_DIALECT),
        verbal_habits=_list_field(bible, _LIST_KEYS_HABITS),
    )

    return VoiceFingerprint(
        character_id=character_id,
        syntax=syntax,
        vocabulary=vocabulary,
        pragmatic=pragmatic,
        special=special,
    )


def format_voice_fingerprint_prompt(fp: VoiceFingerprint) -> str:
    lines = [
        f"## Voice Fingerprint (§11 — character-level speech identity: {fp.character_id})",
        "",
        "### Syntax layer",
        f"- Average sentence length: {fp.syntax.avg_sentence_length}",
        f"- Sentence completeness: {fp.syntax.completeness}",
    ]
    if fp.syntax.sentence_patterns:
        lines.append(f"- Sentence patterns: {'; '.join(fp.syntax.sentence_patterns)}")

    lines.extend(["", "### Vocabulary layer", f"- Formality: {fp.vocabulary.formality}"])
    if fp.vocabulary.domain_preferences:
        lines.append(f"- Domain vocabulary: {', '.join(fp.vocabulary.domain_preferences)}")
    if fp.vocabulary.catchphrases:
        lines.append(f"- Catchphrases / verbal tics: {', '.join(fp.vocabulary.catchphrases)}")
    if fp.vocabulary.banned_words:
        lines.append(f"- Words this character would NEVER use: {', '.join(fp.vocabulary.banned_words)}")

    lines.extend([
        "",
        "### Pragmatic layer",
        f"- Directness: {fp.pragmatic.directness}",
        f"- Information density: {fp.pragmatic.information_density}",
    ])
    if fp.pragmatic.discourse_strategy:
        lines.append(f"- Discourse strategy: {fp.pragmatic.discourse_strategy}")

    has_special = fp.special.speech_defects or fp.special.dialect_markers or fp.special.verbal_habits
    if has_special:
        lines.extend(["", "### Special markers"])
        if fp.special.speech_defects:
            lines.append(f"- Speech defects: {', '.join(fp.special.speech_defects)}")
        if fp.special.dialect_markers:
            lines.append(f"- Dialect markers: {', '.join(fp.special.dialect_markers)}")
        if fp.special.verbal_habits:
            lines.append(f"- Verbal habits: {', '.join(fp.special.verbal_habits)}")

    lines.extend([
        "",
        "**Hard constraint**: remove the character name from all dialogue. "
        "Can you still tell who is speaking? If not, sharpen the voice.",
    ])
    return "\n".join(lines)


def format_voice_fingerprint_for_qc(fp: VoiceFingerprint) -> str:
    lines = [
        f"## Voice Authenticity Checklist — {fp.character_id}",
        "",
        "Verify each point against the generated dialogue:",
    ]

    lines.append(f"- [ ] Sentence length matches target: {fp.syntax.avg_sentence_length}")
    if fp.syntax.completeness != "complete":
        lines.append(f"- [ ] Sentence completeness is '{fp.syntax.completeness}' (not all grammatically complete)")
    if fp.syntax.sentence_patterns:
        for p in fp.syntax.sentence_patterns[:3]:
            lines.append(f"- [ ] Uses pattern: {p}")

    lines.append(f"- [ ] Formality level is '{fp.vocabulary.formality}'")
    if fp.vocabulary.catchphrases:
        lines.append(f"- [ ] At least one catchphrase appears naturally: {', '.join(fp.vocabulary.catchphrases[:3])}")
    if fp.vocabulary.banned_words:
        lines.append(f"- [ ] None of the banned words are used: {', '.join(fp.vocabulary.banned_words[:5])}")
    if fp.vocabulary.domain_preferences:
        lines.append(f"- [ ] Domain vocabulary is present: {', '.join(fp.vocabulary.domain_preferences[:3])}")

    lines.append(f"- [ ] Directness matches: {fp.pragmatic.directness}")
    if fp.pragmatic.discourse_strategy:
        lines.append(f"- [ ] Discourse strategy visible: {fp.pragmatic.discourse_strategy}")

    if fp.special.speech_defects:
        for d in fp.special.speech_defects[:2]:
            lines.append(f"- [ ] Speech defect rendered: {d}")
    if fp.special.dialect_markers:
        lines.append(f"- [ ] Dialect markers present: {', '.join(fp.special.dialect_markers[:3])}")
    if fp.special.verbal_habits:
        for h in fp.special.verbal_habits[:2]:
            lines.append(f"- [ ] Verbal habit rendered: {h}")

    lines.extend([
        "",
        "**Blind test**: with character names removed, is this voice distinguishable "
        "from every other character's dialogue in the scene?",
    ])
    return "\n".join(lines)


def _str_field(d: dict[str, Any], keys: tuple[str, ...], default: str) -> str:
    for k in keys:
        val = d.get(k)
        if isinstance(val, str) and val.strip():
            return val.strip()
    return default


def _list_field(d: dict[str, Any], keys: tuple[str, ...]) -> list[str]:
    for k in keys:
        val = d.get(k)
        if isinstance(val, list):
            return [str(v) for v in val if v][:10]
        if isinstance(val, str) and val.strip():
            import re
            return [s.strip() for s in re.split(r"[,;，；、]", val) if s.strip()][:10]
    return []
