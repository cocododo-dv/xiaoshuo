from __future__ import annotations

import re
from collections import Counter
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from novel_system.db.models import AuthorDraft, ChapterGoal, ChapterMemory, ChapterState, FinalScene, SceneCard, SceneRunState
from novel_system.services.errors import DomainError


QUALITY_DIMENSIONS: tuple[str, ...] = (
    "model_voice",
    "image_homogeneity",
    "expository_dialogue",
    "no_choice_scene",
    "summary_ending",
    "choice_pressure",
    "ending_drive",
)

DIMENSION_WEIGHTS = {
    "model_voice": 0.18,
    "image_homogeneity": 0.12,
    "expository_dialogue": 0.16,
    "no_choice_scene": 0.15,
    "summary_ending": 0.13,
    "choice_pressure": 0.13,
    "ending_drive": 0.13,
}

MODEL_VOICE_TERMS = (
    "suddenly realized",
    "somehow meaningful",
    "somehow",
    "for some reason",
    "couldn't help but",
    "as if fate",
    "everything changed forever",
    "忽然意识到",
    "突然意识到",
    "不知为何",
    "某种意义上",
    "仿佛命运",
    "气氛十分尴尬",
    "一切都变得",
)

EXPOSITORY_DIALOGUE_TERMS = (
    "as you know",
    "because",
    "let me explain",
    "the truth is",
    "i explain",
    "i must explain",
    "you need to know",
    "因为",
    "所以",
    "其实",
    "你知道",
    "我解释",
    "真相是",
    "这是为了",
)

CHOICE_TERMS = (
    "choose",
    "choice",
    "decide",
    "decision",
    "cannot both",
    "could not both",
    "either",
    " or ",
    "must",
    "had to",
    "cost",
    "pay",
    "risk",
    "give up",
    "refuse",
    "选择",
    "决定",
    "不能同时",
    "要么",
    "还是",
    "必须",
    "代价",
    "牺牲",
    "放弃",
)

PRESSURE_TERMS = (
    "cannot both",
    "could not both",
    "must choose",
    "had to choose",
    "at the cost",
    "risk",
    "or save",
    "or the",
    "pay",
    "give up",
    "不能同时",
    "只能",
    "必须选择",
    "代价",
    "冒险",
    "牺牲",
)

SUMMARY_ENDING_TERMS = (
    "in the end",
    "everything changed forever",
    "from then on",
    "she understood",
    "he understood",
    "finally realized",
    "all of this",
    "这一刻",
    "从此",
    "终于明白",
    "一切都",
    "他知道",
    "她知道",
)

ENDING_ACTION_TERMS = (
    "opened",
    "closed",
    "left",
    "took",
    "put",
    "handed",
    "raised",
    "fell",
    "scraped",
    "ran",
    "turned",
    "crossed",
    "stepped",
    "broke",
    "pressed",
    "held",
    "放",
    "推",
    "开",
    "关",
    "走",
    "递",
    "举",
    "落",
    "转身",
    "按",
    "握",
)

IMAGE_TERMS = (
    "moon",
    "fog",
    "shadow",
    "light",
    "dark",
    "rain",
    "wind",
    "blood",
    "fire",
    "mirror",
    "door",
    "key",
    "water",
    "hand",
    "eye",
    "window",
    "月",
    "雾",
    "影",
    "光",
    "雨",
    "风",
    "血",
    "火",
    "镜",
    "门",
    "钥匙",
    "手",
    "眼",
)


class LiteraryQualityService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def overview(self, *, text_layer: str = "author_draft_preferred") -> dict[str, Any]:
        if text_layer not in {"author_draft_preferred", "runtime"}:
            raise DomainError("LITERARY_QUALITY_LAYER_INVALID", "unsupported literary quality text layer", status_code=400)

        items: list[dict[str, Any]] = []
        for chapter in self._chapters():
            source = self._chapter_source(chapter, prefer_author_draft=text_layer == "author_draft_preferred")
            if source is not None:
                items.append(self._analyze_item("chapter", chapter.chapter_id, chapter.chapter_id, None, source))
        for scene in self._scenes():
            source = self._scene_source(scene, prefer_author_draft=text_layer == "author_draft_preferred")
            if source is not None:
                items.append(self._analyze_item("scene", scene.scene_id, scene.chapter_id, scene.scene_id, source))

        mean_score = round(sum(item["score"] for item in items) / len(items), 4) if items else None
        return {
            "summary": {
                "object_count": len(items),
                "mean_score": mean_score,
                "high_risk_count": sum(1 for item in items if item["score"] < 0.72),
                "model_voice_count": sum(1 for item in items if item["signals"]["model_voice"]["risk"]),
            },
            "items": items,
        }

    def _analyze_item(
        self,
        object_type: str,
        object_id: str,
        chapter_id: str,
        scene_id: str | None,
        source: dict[str, str],
    ) -> dict[str, Any]:
        text = source["content"] or ""
        signals, findings = analyze_literary_quality(text)
        score = round(sum(signals[dimension]["score"] * DIMENSION_WEIGHTS[dimension] for dimension in QUALITY_DIMENSIONS), 4)
        return {
            "object_type": object_type,
            "object_id": object_id,
            "chapter_id": chapter_id,
            "scene_id": scene_id,
            "text_layer": source["text_layer"],
            "source_ref": source["source_ref"],
            "score": score,
            "signals": signals,
            "findings": findings,
        }

    def _chapters(self) -> list[ChapterGoal]:
        return self.session.execute(
            select(ChapterGoal)
            .where(ChapterGoal.trashed_flag == 0)
            .order_by(ChapterGoal.chapter_id.asc())
        ).scalars().all()

    def _scenes(self) -> list[SceneCard]:
        return self.session.execute(
            select(SceneCard)
            .where(SceneCard.trashed_flag == 0)
            .order_by(SceneCard.chapter_id.asc(), SceneCard.scene_seq.asc(), SceneCard.scene_id.asc())
        ).scalars().all()

    def _chapter_source(self, chapter: ChapterGoal, *, prefer_author_draft: bool) -> dict[str, str] | None:
        if prefer_author_draft:
            draft = self._current_author_draft("chapter", chapter.chapter_id)
            if draft is not None:
                return {
                    "text_layer": "author_draft",
                    "source_ref": f"author_draft:{draft.draft_id}",
                    "content": draft.content or "",
                }

        memory = self._final_chapter_memory(chapter.chapter_id)
        if memory is not None:
            return {
                "text_layer": "chapter_memory_final",
                "source_ref": f"chapter_memory:{memory.row_id}",
                "content": memory.content or "",
            }

        assembled = self._assembled_chapter_text(chapter.chapter_id)
        if assembled:
            return {
                "text_layer": "chapter_assembled",
                "source_ref": f"chapter_assembled:{chapter.chapter_id}",
                "content": assembled,
            }
        return None

    def _scene_source(self, scene: SceneCard, *, prefer_author_draft: bool) -> dict[str, str] | None:
        if prefer_author_draft:
            draft = self._current_author_draft("scene", scene.scene_id)
            if draft is not None:
                return {
                    "text_layer": "author_draft",
                    "source_ref": f"author_draft:{draft.draft_id}",
                    "content": draft.content or "",
                }

        final_scene = self._final_scene(scene.scene_id)
        if final_scene is None:
            return None
        return {
            "text_layer": "runtime_final_scene",
            "source_ref": f"final_scene:{final_scene.row_id}",
            "content": final_scene.content or "",
        }

    def _current_author_draft(self, object_type: str, object_id: str) -> AuthorDraft | None:
        return self.session.execute(
            select(AuthorDraft)
            .where(
                AuthorDraft.object_type == object_type,
                AuthorDraft.object_id == object_id,
                AuthorDraft.status == "current",
            )
            .order_by(AuthorDraft.updated_at.desc(), AuthorDraft.draft_id.desc())
        ).scalars().first()

    def _final_scene(self, scene_id: str) -> FinalScene | None:
        state = self.session.get(SceneRunState, scene_id)
        if state is not None and state.current_final_scene_row_id:
            pointed = self.session.get(FinalScene, state.current_final_scene_row_id)
            if pointed is not None and pointed.scene_id == scene_id:
                return pointed
        return self.session.execute(
            select(FinalScene)
            .where(FinalScene.scene_id == scene_id)
            .order_by(FinalScene.created_at.desc(), FinalScene.row_id.desc())
        ).scalars().first()

    def _final_chapter_memory(self, chapter_id: str) -> ChapterMemory | None:
        state = self.session.get(ChapterState, chapter_id)
        if state is not None and state.last_final_memory_row_id:
            pointed = self.session.get(ChapterMemory, state.last_final_memory_row_id)
            if pointed is not None and pointed.chapter_id == chapter_id and pointed.aggregate_stage == "final":
                return pointed
        return self.session.execute(
            select(ChapterMemory)
            .where(
                ChapterMemory.chapter_id == chapter_id,
                ChapterMemory.aggregate_stage == "final",
                ChapterMemory.active_flag == 1,
            )
            .order_by(ChapterMemory.created_at.desc(), ChapterMemory.row_id.desc())
        ).scalars().first()

    def _assembled_chapter_text(self, chapter_id: str) -> str:
        parts: list[str] = []
        scenes = self.session.execute(
            select(SceneCard)
            .where(SceneCard.chapter_id == chapter_id, SceneCard.trashed_flag == 0)
            .order_by(SceneCard.scene_seq.asc(), SceneCard.scene_id.asc())
        ).scalars().all()
        for scene in scenes:
            final_scene = self._final_scene(scene.scene_id)
            if final_scene is not None and final_scene.content:
                parts.append(final_scene.content)
        return "\n\n".join(parts)


def analyze_literary_quality(text: str) -> tuple[dict[str, dict[str, Any]], list[dict[str, str]]]:
    normalized = _compact_ws(text)
    signals: dict[str, dict[str, Any]] = {}
    findings: list[dict[str, str]] = []

    _add_term_signal(
        signals,
        findings,
        "model_voice",
        normalized,
        MODEL_VOICE_TERMS,
        issue="Possible model voice or generic emotional shortcut.",
        recommendation="Replace abstract realization with a concrete choice, gesture, or sensory consequence.",
    )
    _add_image_signal(signals, findings, normalized)
    _add_expository_dialogue_signal(signals, findings, normalized)
    _add_absence_signal(
        signals,
        findings,
        "no_choice_scene",
        normalized,
        CHOICE_TERMS,
        issue="The passage does not show a clear choice on the page.",
        recommendation="Give the character two incompatible options and make one option visibly cost something.",
    )
    _add_summary_ending_signal(signals, findings, normalized)
    _add_absence_signal(
        signals,
        findings,
        "choice_pressure",
        normalized,
        PRESSURE_TERMS,
        issue="The choice lacks visible pressure or price.",
        recommendation="State the tradeoff through action: what is lost, risked, or refused because of the choice.",
    )
    _add_ending_drive_signal(signals, findings, normalized)

    for dimension in QUALITY_DIMENSIONS:
        signals.setdefault(dimension, {"risk": False, "score": 1.0, "evidence": ""})
    return signals, findings


def _add_term_signal(
    signals: dict[str, dict[str, Any]],
    findings: list[dict[str, str]],
    dimension: str,
    text: str,
    terms: tuple[str, ...],
    *,
    issue: str,
    recommendation: str,
) -> None:
    term = _first_present_term(text, terms)
    if term:
        evidence = _excerpt(text, term)
        signals[dimension] = {"risk": True, "score": 0.0, "evidence": evidence}
        findings.append(_finding(dimension, "revision", issue, evidence, recommendation))
        return
    signals[dimension] = {"risk": False, "score": 1.0, "evidence": ""}


def _add_absence_signal(
    signals: dict[str, dict[str, Any]],
    findings: list[dict[str, str]],
    dimension: str,
    text: str,
    terms: tuple[str, ...],
    *,
    issue: str,
    recommendation: str,
) -> None:
    if _first_present_term(text, terms):
        signals[dimension] = {"risk": False, "score": 1.0, "evidence": ""}
        return
    evidence = _excerpt(text, "")
    signals[dimension] = {"risk": True, "score": 0.0, "evidence": evidence}
    findings.append(_finding(dimension, "revision", issue, evidence, recommendation))


def _add_expository_dialogue_signal(
    signals: dict[str, dict[str, Any]],
    findings: list[dict[str, str]],
    text: str,
) -> None:
    for dialogue in _dialogue_spans(text):
        term = _first_present_term(dialogue, EXPOSITORY_DIALOGUE_TERMS)
        if term:
            evidence = _excerpt(dialogue, term)
            signals["expository_dialogue"] = {"risk": True, "score": 0.0, "evidence": evidence}
            findings.append(
                _finding(
                    "expository_dialogue",
                    "revision",
                    "Dialogue is carrying explanation instead of pressure or subtext.",
                    evidence,
                    "Move the fact into gesture, silence, contradiction, or a partial answer.",
                )
            )
            return
    signals["expository_dialogue"] = {"risk": False, "score": 1.0, "evidence": ""}


def _add_image_signal(
    signals: dict[str, dict[str, Any]],
    findings: list[dict[str, str]],
    text: str,
) -> None:
    counts = Counter()
    lowered = text.lower()
    for term in IMAGE_TERMS:
        if re.fullmatch(r"[a-z]+", term):
            counts[term] = len(re.findall(rf"\b{re.escape(term)}\b", lowered))
        else:
            counts[term] = lowered.count(term.lower())
    term, count = max(counts.items(), key=lambda item: item[1]) if counts else ("", 0)
    if count >= 3:
        evidence = _excerpt(text, term)
        signals["image_homogeneity"] = {"risk": True, "score": 0.0, "evidence": evidence}
        findings.append(
            _finding(
                "image_homogeneity",
                "taste",
                f"The same image field repeats too often: {term}.",
                evidence,
                "Keep one anchor image, then vary texture through action, object, temperature, sound, or spatial detail.",
            )
        )
        return
    signals["image_homogeneity"] = {"risk": False, "score": 1.0, "evidence": ""}


def _add_summary_ending_signal(
    signals: dict[str, dict[str, Any]],
    findings: list[dict[str, str]],
    text: str,
) -> None:
    ending = _ending_slice(text)
    term = _first_present_term(ending, SUMMARY_ENDING_TERMS)
    if term:
        evidence = _excerpt(ending, term)
        signals["summary_ending"] = {"risk": True, "score": 0.0, "evidence": evidence}
        findings.append(
            _finding(
                "summary_ending",
                "revision",
                "The ending explains the effect instead of landing on an action or image.",
                evidence,
                "Cut the summarizing sentence and end on the last irreversible action.",
            )
        )
        return
    signals["summary_ending"] = {"risk": False, "score": 1.0, "evidence": ""}


def _add_ending_drive_signal(
    signals: dict[str, dict[str, Any]],
    findings: list[dict[str, str]],
    text: str,
) -> None:
    ending = _ending_slice(text)
    has_action = _first_present_term(ending, ENDING_ACTION_TERMS)
    if has_action and not signals.get("summary_ending", {}).get("risk"):
        signals["ending_drive"] = {"risk": False, "score": 1.0, "evidence": ""}
        return
    evidence = _excerpt(ending, "")
    signals["ending_drive"] = {"risk": True, "score": 0.0, "evidence": evidence}
    findings.append(
        _finding(
            "ending_drive",
            "revision",
            "The final beat does not push the reader into the next scene.",
            evidence,
            "End with a new action, object movement, arrival, departure, reveal, or refusal.",
        )
    )


def _finding(dimension: str, severity: str, issue: str, evidence: str, recommendation: str) -> dict[str, str]:
    return {
        "dimension": dimension,
        "severity": severity,
        "issue": issue,
        "evidence_excerpt": evidence,
        "recommendation": recommendation,
    }


def _first_present_term(text: str, terms: tuple[str, ...]) -> str:
    lowered = text.lower()
    for term in terms:
        normalized_term = term.lower()
        if normalized_term.strip() and normalized_term in lowered:
            return term
    return ""


def _dialogue_spans(text: str) -> list[str]:
    spans = re.findall(r'"([^"]+)"', text, flags=re.DOTALL)
    spans.extend(re.findall(r"“([^”]+)”", text, flags=re.DOTALL))
    spans.extend(re.findall(r"「([^」]+)」", text, flags=re.DOTALL))
    return [_compact_ws(span) for span in spans if span.strip()]


def _ending_slice(text: str) -> str:
    normalized = _compact_ws(text)
    if len(normalized) <= 180:
        return normalized
    return normalized[-180:]


def _excerpt(text: str, needle: str) -> str:
    normalized = _compact_ws(text)
    if not normalized:
        return ""
    if not needle:
        return normalized[:180]
    index = normalized.lower().find(needle.lower())
    if index < 0:
        return normalized[:180]
    start = max(0, index - 70)
    end = min(len(normalized), index + len(needle) + 70)
    return normalized[start:end]


def _compact_ws(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()
