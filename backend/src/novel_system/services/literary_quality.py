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
    "repetitive_action",
    "expository_dialogue",
    "no_choice_scene",
    "summary_ending",
    "choice_pressure",
    "ending_drive",
    "template_action_reuse",
    "image_field_reuse",
    "syntax_monotony",
    "false_clarity",
    "valid_ambiguity",
)

DIMENSION_WEIGHTS = {
    "model_voice": 0.13,
    "image_homogeneity": 0.08,
    "repetitive_action": 0.08,
    "expository_dialogue": 0.12,
    "no_choice_scene": 0.10,
    "summary_ending": 0.10,
    "choice_pressure": 0.10,
    "ending_drive": 0.10,
    "template_action_reuse": 0.08,
    "image_field_reuse": 0.05,
    "syntax_monotony": 0.04,
    "false_clarity": 0.02,
    "valid_ambiguity": 0.00,
}

SEVERITY_RANK = {"blocking": 0, "revision": 1, "taste": 2, "info": 3}
QUALITY_TEXT_LAYERS = {
    "author_draft_preferred",
    "runtime",
    "runtime_final_scene",
    "chapter_memory_final",
    "chapter_assembled",
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

REPETITIVE_ACTION_TERMS = (
    "turned",
    "looked",
    "nodded",
    "smiled",
    "sighed",
    "stepped",
    "held",
    "opened",
    "closed",
    "转身",
    "看",
    "点头",
    "笑",
    "叹气",
    "走",
    "握",
    "打开",
    "关上",
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

ATMOSPHERIC_IMAGE_TERMS = (
    "moon",
    "shadow",
    "dark",
    "rain",
    "wind",
    "fog",
    "cold",
    "light",
    "月",
    "月光",
    "影",
    "阴影",
    "冷",
    "风",
    "雾",
    "雾气",
    "光",
)

FALSE_CLARITY_TERMS = (
    "she knew",
    "he knew",
    "finally understood",
    "suddenly realized",
    "everything became clear",
    "她知道",
    "他知道",
    "终于明白",
    "忽然意识到",
    "突然意识到",
    "真相必须",
    "一切都变得",
)


class LiteraryQualityService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def overview(
        self,
        *,
        text_layer: str = "author_draft_preferred",
        chapter_id: str | None = None,
        risk_type: str | None = None,
        min_severity: str | None = None,
    ) -> dict[str, Any]:
        if text_layer not in QUALITY_TEXT_LAYERS:
            raise DomainError("LITERARY_QUALITY_LAYER_INVALID", "unsupported literary quality text layer", status_code=400)
        _validate_quality_filters(risk_type=risk_type, min_severity=min_severity)

        items: list[dict[str, Any]] = []
        for chapter in self._chapters():
            if chapter_id and chapter.chapter_id != chapter_id:
                continue
            source = self._chapter_source(chapter, text_layer=text_layer)
            if source is not None:
                items.append(self._analyze_item("chapter", chapter.chapter_id, chapter.chapter_id, None, source))
        for scene in self._scenes():
            if chapter_id and scene.chapter_id != chapter_id:
                continue
            source = self._scene_source(scene, text_layer=text_layer)
            if source is not None:
                items.append(self._analyze_item("scene", scene.scene_id, scene.chapter_id, scene.scene_id, source))

        items = _filter_quality_items(items, risk_type=risk_type, min_severity=min_severity)
        mean_score = round(sum(item["score"] for item in items) / len(items), 4) if items else None
        risk_clusters = _risk_clusters(items, risk_type=risk_type, min_severity=min_severity)
        cross_scene_reuse = _cross_scene_reuse(items)
        return {
            "filters": {
                "text_layer": text_layer,
                "chapter_id": chapter_id,
                "risk_type": risk_type,
                "min_severity": min_severity,
            },
            "summary": {
                "object_count": len(items),
                "mean_score": mean_score,
                "high_risk_count": sum(1 for item in items if item["score"] < 0.72),
                "model_voice_count": sum(1 for item in items if item["signals"]["model_voice"]["risk"]),
                "risk_cluster_count": len(risk_clusters),
                "cross_scene_reuse_count": len(cross_scene_reuse),
            },
            "items": items,
            "risk_clusters": risk_clusters,
            "fingerprints": [
                {
                    "object_type": item["object_type"],
                    "object_id": item["object_id"],
                    "chapter_id": item["chapter_id"],
                    "scene_id": item["scene_id"],
                    "source_ref": item["source_ref"],
                    "fingerprint": item["fingerprint"],
                }
                for item in items
            ],
            "cross_scene_reuse": cross_scene_reuse,
            "recommended_next_action": _top_recommended_action(items),
        }

    def analyze_text(self, payload: dict[str, Any]) -> dict[str, Any]:
        content = payload.get("content")
        if not isinstance(content, str) or not content.strip():
            raise DomainError("LITERARY_QUALITY_TEXT_REQUIRED", "content is required", status_code=400)
        object_type = _optional_string(payload.get("object_type")) or "ad_hoc"
        object_id = _optional_string(payload.get("object_id")) or "scratch"
        chapter_id = _optional_string(payload.get("chapter_id")) or object_id
        scene_id = _optional_string(payload.get("scene_id"))
        item = self._analyze_item(
            object_type,
            object_id,
            chapter_id,
            scene_id,
            {
                "text_layer": "ad_hoc",
                "source_ref": _optional_string(payload.get("source_ref")) or f"ad_hoc:{object_id}",
                "content": content,
            },
        )
        return {
            **item,
            "content": content,
            "span_findings": _span_findings(content, item["findings"]),
            "risk_clusters": _risk_clusters([item]),
            "recommended_next_action": item["recommended_next_action"],
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
        findings = _enrich_findings(
            findings,
            object_type=object_type,
            object_id=object_id,
            chapter_id=chapter_id,
            scene_id=scene_id,
            source_ref=source["source_ref"],
        )
        fingerprint = fingerprint_literary_quality(text)
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
            "fingerprint": fingerprint,
            "recommended_next_action": _recommended_next_action(findings, signals),
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

    def _chapter_source(self, chapter: ChapterGoal, *, text_layer: str) -> dict[str, str] | None:
        if text_layer == "author_draft_preferred":
            draft = self._current_author_draft("chapter", chapter.chapter_id)
            if draft is not None:
                return {
                    "text_layer": "author_draft",
                    "source_ref": f"author_draft:{draft.draft_id}",
                    "content": draft.content or "",
                }
        if text_layer == "runtime_final_scene":
            return None

        if text_layer in {"author_draft_preferred", "runtime", "chapter_memory_final"}:
            memory = self._final_chapter_memory(chapter.chapter_id)
            if memory is not None:
                return {
                    "text_layer": "chapter_memory_final",
                    "source_ref": f"chapter_memory:{memory.row_id}",
                    "content": memory.content or "",
                }
            if text_layer == "chapter_memory_final":
                return None

        if text_layer in {"author_draft_preferred", "runtime", "chapter_assembled"}:
            assembled = self._assembled_chapter_text(chapter.chapter_id)
            if assembled:
                return {
                    "text_layer": "chapter_assembled",
                    "source_ref": f"chapter_assembled:{chapter.chapter_id}",
                    "content": assembled,
                }
        return None

    def _scene_source(self, scene: SceneCard, *, text_layer: str) -> dict[str, str] | None:
        if text_layer == "author_draft_preferred":
            draft = self._current_author_draft("scene", scene.scene_id)
            if draft is not None:
                return {
                    "text_layer": "author_draft",
                    "source_ref": f"author_draft:{draft.draft_id}",
                    "content": draft.content or "",
                }
        if text_layer not in {"author_draft_preferred", "runtime", "runtime_final_scene"}:
            return None

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
    _add_repetitive_action_signal(signals, findings, normalized)
    _add_template_action_reuse_signal(signals, findings, normalized)
    _add_image_field_reuse_signal(signals, findings, normalized)
    _add_syntax_monotony_signal(signals, findings, normalized)
    _add_false_clarity_signal(signals, findings, normalized)
    _add_valid_ambiguity_signal(signals, findings, normalized)
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


def fingerprint_literary_quality(text: str) -> dict[str, Any]:
    normalized = _compact_ws(text)
    sentences = _sentences(normalized)
    action_templates = Counter(_action_template(sentence) for sentence in sentences)
    action_templates.pop("", None)
    syntax_shapes = Counter(_syntax_pattern(sentence) for sentence in sentences)
    syntax_shapes.pop("", None)

    lowered = normalized.lower()
    image_fields: Counter[str] = Counter()
    for term in tuple(dict.fromkeys((*IMAGE_TERMS, *ATMOSPHERIC_IMAGE_TERMS))):
        if re.fullmatch(r"[a-z]+", term):
            count = len(re.findall(rf"\b{re.escape(term)}\b", lowered))
        else:
            count = lowered.count(term.lower())
        if count:
            image_fields[term] = count

    dialogue_exposition: Counter[str] = Counter()
    for dialogue in _dialogue_spans(normalized):
        for term in EXPOSITORY_DIALOGUE_TERMS:
            if term.lower() in dialogue.lower():
                dialogue_exposition[term] += 1

    return {
        "action_templates": _top_counter(action_templates, limit=8),
        "image_fields": _top_counter(image_fields, limit=10),
        "syntax_shapes": _top_counter(syntax_shapes, limit=8),
        "false_clarity": [term for term in FALSE_CLARITY_TERMS if term.lower() in lowered],
        "summary_ending": [term for term in SUMMARY_ENDING_TERMS if term.lower() in _ending_slice(normalized).lower()],
        "dialogue_exposition": _top_counter(dialogue_exposition, limit=6),
        "choice_pressure": [term for term in PRESSURE_TERMS if term.lower() in lowered],
    }


def _validate_quality_filters(*, risk_type: str | None, min_severity: str | None) -> None:
    if risk_type and risk_type not in QUALITY_DIMENSIONS:
        raise DomainError("LITERARY_QUALITY_RISK_TYPE_INVALID", "unsupported literary quality risk_type", status_code=400)
    if min_severity and min_severity not in SEVERITY_RANK:
        raise DomainError("LITERARY_QUALITY_SEVERITY_INVALID", "unsupported literary quality min_severity", status_code=400)


def _filter_quality_items(
    items: list[dict[str, Any]],
    *,
    risk_type: str | None,
    min_severity: str | None,
) -> list[dict[str, Any]]:
    threshold = SEVERITY_RANK[min_severity] if min_severity else None
    filtered: list[dict[str, Any]] = []
    for item in items:
        if risk_type and not item.get("signals", {}).get(risk_type, {}).get("risk"):
            continue
        if threshold is not None and not any(
            SEVERITY_RANK.get(finding.get("severity"), 99) <= threshold
            for finding in item.get("findings") or []
        ):
            continue
        filtered.append(item)
    return filtered


def _enrich_findings(
    findings: list[dict[str, str]],
    *,
    object_type: str,
    object_id: str,
    chapter_id: str,
    scene_id: str | None,
    source_ref: str,
) -> list[dict[str, Any]]:
    enriched: list[dict[str, Any]] = []
    for finding in findings:
        dimension = finding.get("dimension", "unknown")
        signal_id = f"quality:{object_type}:{object_id}:{dimension}"
        enriched.append(
            {
                **finding,
                "quality_signal_id": signal_id,
                "signal_id": signal_id,
                "object_type": object_type,
                "object_id": object_id,
                "chapter_id": chapter_id,
                "scene_id": scene_id,
                "source_ref": source_ref,
                "target_text_ref": source_ref,
            }
        )
    return enriched


def _span_findings(content: str, findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    spans: list[dict[str, Any]] = []
    for finding in findings:
        span = _locate_finding_span(content, str(finding.get("evidence_excerpt") or ""))
        if span is None:
            continue
        start, end, evidence = span
        spans.append(
            {
                "dimension": finding.get("dimension") or "unknown",
                "severity": finding.get("severity") or "revision",
                "start": start,
                "end": end,
                "evidence": evidence,
                "issue": finding.get("issue") or "",
                "recommended_action": finding.get("recommendation") or "",
                "quality_signal_id": finding.get("quality_signal_id"),
            }
        )
    return spans


def _locate_finding_span(content: str, evidence: str) -> tuple[int, int, str] | None:
    source = str(content or "")
    if not source:
        return None
    for fragment in _evidence_fragments(evidence):
        index = source.find(fragment)
        if index >= 0:
            return index, index + len(fragment), fragment
    compact_source = _compact_ws(source)
    if compact_source and compact_source in source:
        index = source.find(compact_source)
        return index, index + len(compact_source), compact_source
    fallback = source.strip()
    if not fallback:
        return None
    index = source.find(fallback)
    fragment = fallback[: min(len(fallback), 120)]
    return index, index + len(fragment), fragment


def _evidence_fragments(evidence: str) -> list[str]:
    raw = str(evidence or "").strip()
    candidates: list[str] = []
    if raw:
        candidates.append(raw)
        candidates.extend(part.strip() for part in raw.split(" / ") if part.strip())
    fragments: list[str] = []
    for candidate in candidates:
        if candidate and candidate not in fragments:
            fragments.append(candidate)
        trimmed = candidate.strip(" .。!?！？,，;；")
        if trimmed and trimmed not in fragments:
            fragments.append(trimmed)
    return sorted(fragments, key=len, reverse=True)


def _recommended_next_action(findings: list[dict[str, Any]], signals: dict[str, dict[str, Any]]) -> dict[str, Any]:
    if not findings:
        return {"action": "none", "label": "暂无动作", "reason": "未发现明显文学质量风险。"}
    priority = sorted(findings, key=lambda item: (SEVERITY_RANK.get(item.get("severity"), 99), item.get("dimension", "")))[0]
    dimension = priority.get("dimension") or "quality"
    action = "open_deepdesk_patch"
    label = "去深改台生成局部候选"
    return {
        "action": action,
        "label": label,
        "risk_type": dimension,
        "quality_signal_id": priority.get("quality_signal_id"),
        "target_text_ref": priority.get("target_text_ref"),
        "source_excerpt": priority.get("evidence_excerpt") or signals.get(dimension, {}).get("evidence") or "",
        "reason": priority.get("issue") or "",
        "recommendation": priority.get("recommendation") or "",
    }


def _top_recommended_action(items: list[dict[str, Any]]) -> dict[str, Any]:
    actions = [item.get("recommended_next_action") for item in items if item.get("recommended_next_action", {}).get("action") != "none"]
    if not actions:
        return {"action": "none", "label": "暂无动作", "reason": "当前列表没有明显文学质量风险。"}
    return actions[0]


def _risk_clusters(
    items: list[dict[str, Any]],
    *,
    risk_type: str | None = None,
    min_severity: str | None = None,
) -> list[dict[str, Any]]:
    threshold = SEVERITY_RANK[min_severity] if min_severity else None
    grouped: dict[str, dict[str, Any]] = {}
    for item in items:
        for finding in item.get("findings") or []:
            dimension = finding.get("dimension") or "unknown"
            if risk_type and dimension != risk_type:
                continue
            if threshold is not None and SEVERITY_RANK.get(finding.get("severity"), 99) > threshold:
                continue
            cluster = grouped.setdefault(
                dimension,
                {
                    "dimension": dimension,
                    "severity": finding.get("severity") or "revision",
                    "count": 0,
                    "object_refs": [],
                    "quality_signal_ids": [],
                    "representative_evidence": finding.get("evidence_excerpt") or "",
                    "recommendation": finding.get("recommendation") or "",
                },
            )
            cluster["count"] += 1
            ref = {
                "object_type": item["object_type"],
                "object_id": item["object_id"],
                "chapter_id": item["chapter_id"],
                "scene_id": item["scene_id"],
                "source_ref": item["source_ref"],
            }
            if ref not in cluster["object_refs"]:
                cluster["object_refs"].append(ref)
            signal_id = finding.get("quality_signal_id")
            if signal_id and signal_id not in cluster["quality_signal_ids"]:
                cluster["quality_signal_ids"].append(signal_id)
            if SEVERITY_RANK.get(finding.get("severity"), 99) < SEVERITY_RANK.get(cluster["severity"], 99):
                cluster["severity"] = finding.get("severity")
    return sorted(grouped.values(), key=lambda row: (-row["count"], SEVERITY_RANK.get(row["severity"], 99), row["dimension"]))


def _cross_scene_reuse(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str, str], dict[str, Any]] = {}
    for item in items:
        if item.get("object_type") != "scene":
            continue
        chapter_id = item.get("chapter_id") or ""
        fingerprint = item.get("fingerprint") or {}
        for cluster_type, key in (
            ("action_template", "action_templates"),
            ("image_field", "image_fields"),
            ("syntax_shape", "syntax_shapes"),
        ):
            for token_row in fingerprint.get(key) or []:
                token = token_row.get("value")
                if not token:
                    continue
                group = grouped.setdefault(
                    (chapter_id, cluster_type, token),
                    {
                        "chapter_id": chapter_id,
                        "cluster_type": cluster_type,
                        "token": token,
                        "count": 0,
                        "object_ids": [],
                        "source_refs": [],
                        "severity": "revision" if cluster_type != "image_field" else "taste",
                    },
                )
                group["count"] += int(token_row.get("count") or 0)
                if item["object_id"] not in group["object_ids"]:
                    group["object_ids"].append(item["object_id"])
                if item["source_ref"] not in group["source_refs"]:
                    group["source_refs"].append(item["source_ref"])
    rows = [row for row in grouped.values() if len(row["object_ids"]) >= 2]
    return sorted(rows, key=lambda row: (-row["count"], row["chapter_id"], row["cluster_type"], row["token"]))


def _top_counter(counter: Counter[str], *, limit: int) -> list[dict[str, Any]]:
    return [
        {"value": value, "count": count}
        for value, count in counter.most_common(limit)
        if value and count > 0
    ]


def _optional_string(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


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


def _add_repetitive_action_signal(
    signals: dict[str, dict[str, Any]],
    findings: list[dict[str, str]],
    text: str,
) -> None:
    counts = Counter()
    lowered = text.lower()
    for term in REPETITIVE_ACTION_TERMS:
        if re.fullmatch(r"[a-z]+", term):
            counts[term] = len(re.findall(rf"\b{re.escape(term)}\b", lowered))
        else:
            counts[term] = lowered.count(term.lower())
    term, count = max(counts.items(), key=lambda item: item[1]) if counts else ("", 0)
    if count < 4:
        signals["repetitive_action"] = {"risk": False, "score": 1.0, "evidence": ""}
        return
    evidence = _excerpt(text, term)
    signals["repetitive_action"] = {"risk": True, "score": 0.0, "evidence": evidence}
    findings.append(
        _finding(
            "repetitive_action",
            "revision",
            f"The same action beat repeats too often: {term}.",
            evidence,
            "Keep the strongest beat, then replace the others with a choice, object movement, silence, or changed blocking.",
        )
    )


def _add_template_action_reuse_signal(
    signals: dict[str, dict[str, Any]],
    findings: list[dict[str, str]],
    text: str,
) -> None:
    sentences = _sentences(text)
    templates = Counter(_action_template(sentence) for sentence in sentences)
    templates.pop("", None)
    template, count = max(templates.items(), key=lambda item: item[1]) if templates else ("", 0)
    if count < 3:
        signals["template_action_reuse"] = {"risk": False, "score": 1.0, "evidence": ""}
        return
    evidence = " / ".join(sentence for sentence in sentences if _action_template(sentence) == template)[:180]
    signals["template_action_reuse"] = {"risk": True, "score": 0.0, "evidence": evidence}
    findings.append(
        _finding(
            "template_action_reuse",
            "revision",
            "Action beats are repeating the same sentence template.",
            evidence,
            "Keep one beat, then vary blocking, object movement, silence, or relational pressure.",
        )
    )


def _add_image_field_reuse_signal(
    signals: dict[str, dict[str, Any]],
    findings: list[dict[str, str]],
    text: str,
) -> None:
    lowered = text.lower()
    hits: list[str] = []
    for term in ATMOSPHERIC_IMAGE_TERMS:
        count = len(re.findall(rf"\b{re.escape(term)}\b", lowered)) if re.fullmatch(r"[a-z]+", term) else lowered.count(term.lower())
        hits.extend([term] * count)
    if len(hits) < 4 or len(set(hits)) < 3:
        signals["image_field_reuse"] = {"risk": False, "score": 1.0, "evidence": ""}
        return
    evidence = _excerpt(text, hits[0])
    signals["image_field_reuse"] = {"risk": True, "score": 0.0, "evidence": evidence}
    findings.append(
        _finding(
            "image_field_reuse",
            "taste",
            f"The atmospheric image field is doing too much repeated work: {', '.join(sorted(set(hits))[:5])}.",
            evidence,
            "Let one image carry mood, and make the next beat change through an object, decision, or body position.",
        )
    )


def _add_syntax_monotony_signal(
    signals: dict[str, dict[str, Any]],
    findings: list[dict[str, str]],
    text: str,
) -> None:
    sentences = _sentences(text)
    patterns = Counter(_syntax_pattern(sentence) for sentence in sentences)
    patterns.pop("", None)
    pattern, count = max(patterns.items(), key=lambda item: item[1]) if patterns else ("", 0)
    if count < 3:
        signals["syntax_monotony"] = {"risk": False, "score": 1.0, "evidence": ""}
        return
    evidence = " / ".join(sentence for sentence in sentences if _syntax_pattern(sentence) == pattern)[:180]
    signals["syntax_monotony"] = {"risk": True, "score": 0.0, "evidence": evidence}
    findings.append(
        _finding(
            "syntax_monotony",
            "taste",
            "Several consecutive sentences use the same syntactic shape.",
            evidence,
            "Break the rhythm with a short sentence, a withheld response, or a sentence that starts from consequence instead of gesture.",
        )
    )


def _add_false_clarity_signal(
    signals: dict[str, dict[str, Any]],
    findings: list[dict[str, str]],
    text: str,
) -> None:
    term = _first_present_term(text, FALSE_CLARITY_TERMS)
    if not term:
        signals["false_clarity"] = {"risk": False, "score": 1.0, "evidence": ""}
        return
    evidence = _excerpt(text, term)
    signals["false_clarity"] = {"risk": True, "score": 0.0, "evidence": evidence}
    findings.append(
        _finding(
            "false_clarity",
            "revision",
            "The passage tells the reader what became clear instead of letting pressure reveal it.",
            evidence,
            "Cut the explanation and let a choice, refusal, object transfer, or silence create the reader's inference.",
        )
    )


def _add_valid_ambiguity_signal(
    signals: dict[str, dict[str, Any]],
    findings: list[dict[str, str]],
    text: str,
) -> None:
    signals["valid_ambiguity"] = {"risk": False, "score": 1.0, "evidence": ""}


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


def _sentences(text: str) -> list[str]:
    return [part.strip() for part in re.split(r"[。！？.!?]+", text) if part.strip()]


def _action_template(sentence: str) -> str:
    normalized = _compact_ws(sentence)
    lowered = normalized.lower()
    if re.search(r"^[^，。！？]{1,10}低头看着[^，。！？]*，[^。！？]*沉默了片刻", normalized):
        return "pronoun_looked_at_object_then_silence"
    for action in ("turned", "looked", "nodded", "smiled", "sighed", "转身", "低头", "看着", "点头", "笑", "叹气", "沉默"):
        if action in lowered:
            return f"action:{action}"
    return ""


def _syntax_pattern(sentence: str) -> str:
    normalized = _compact_ws(sentence)
    if not normalized:
        return ""
    if re.match(r"^[她他][^，,]{2,24}[，,][^，,]{2,24}$", normalized):
        return "pronoun_phrase_comma_phrase"
    comma_count = normalized.count("，") + normalized.count(",")
    length_bucket = min(len(normalized) // 12, 4)
    return f"comma:{comma_count}:len:{length_bucket}"


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
