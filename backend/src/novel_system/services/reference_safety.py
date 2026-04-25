from __future__ import annotations

import re
from collections import Counter
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from novel_system.db.models import ReferenceBook, ReferenceBookSegment, ReferenceProfile
from novel_system.services.errors import DomainError
from novel_system.services.source_safety import scan_source_safety


class ReferenceSafetyService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def overview(self) -> dict[str, Any]:
        profiles = self.session.execute(
            select(ReferenceProfile).order_by(ReferenceProfile.created_at.desc(), ReferenceProfile.profile_id.desc())
        ).scalars().all()
        items = [self.serialize_profile(profile) for profile in profiles]
        return {
            "summary": {
                "profile_count": len(items),
                "ready_profile_count": sum(1 for item in items if item["status"] == "ready"),
                "profile_with_safety_count": sum(1 for item in items if item["source_safety"]["ready"]),
            },
            "items": items,
        }

    def extract_profile(self, book_id: str) -> dict[str, Any]:
        book = self.session.get(ReferenceBook, book_id)
        if book is None:
            raise DomainError("REFERENCE_BOOK_NOT_FOUND", f"reference book {book_id} not found", status_code=404)
        profile = self._latest_profile(book_id)
        if profile is None:
            raise DomainError("REFERENCE_PROFILE_NOT_FOUND", f"reference profile for {book_id} not found", status_code=404)
        segments = self.session.execute(
            select(ReferenceBookSegment)
            .where(ReferenceBookSegment.book_id == book_id)
            .order_by(ReferenceBookSegment.segment_index.asc(), ReferenceBookSegment.segment_id.asc())
        ).scalars().all()
        source_safety = build_reference_safety_profile(
            [segment.text or "" for segment in segments if segment.segment_kind != "boilerplate"],
            profile_id=profile.profile_id,
            book_id=book_id,
        )
        payload = dict(profile.profile_json or {})
        payload["source_safety"] = source_safety
        profile.profile_json = payload
        self.session.flush()
        return {"book": self._serialize_book(book), "profile": self.serialize_profile(profile)}

    def scan_text(
        self,
        *,
        text: str,
        source_profile_ids: list[str] | None = None,
        object_ref: str | None = None,
    ) -> dict[str, Any]:
        profile_ids = [item for item in (source_profile_ids or []) if isinstance(item, str) and item.strip()]
        profiles = []
        if profile_ids:
            profiles = self.session.execute(
                select(ReferenceProfile).where(ReferenceProfile.profile_id.in_(profile_ids))
            ).scalars().all()
        safety_profiles = []
        for profile in profiles:
            source_safety = (profile.profile_json or {}).get("source_safety")
            if isinstance(source_safety, dict):
                safety_profiles.append(source_safety)
        result = scan_source_safety(
            text or "",
            source_profile_ids=profile_ids,
            reference_safety_profiles=safety_profiles,
        )
        result["object_ref"] = object_ref
        result["profile_count"] = len(safety_profiles)
        return result

    def _latest_profile(self, book_id: str) -> ReferenceProfile | None:
        return self.session.execute(
            select(ReferenceProfile)
            .where(ReferenceProfile.book_id == book_id)
            .order_by(ReferenceProfile.created_at.desc(), ReferenceProfile.profile_id.desc())
        ).scalars().first()

    @staticmethod
    def serialize_profile(profile: ReferenceProfile) -> dict[str, Any]:
        source_safety = (profile.profile_json or {}).get("source_safety")
        if not isinstance(source_safety, dict):
            source_safety = {"ready": False, "protected_terms": [], "distinctive_phrases": [], "scene_bridges": []}
        return {
            "profile_id": profile.profile_id,
            "book_id": profile.book_id,
            "run_id": profile.run_id,
            "title": profile.title,
            "status": profile.status,
            "profile_json": profile.profile_json or {},
            "source_safety": source_safety,
            "created_at": profile.created_at,
            "updated_at": profile.updated_at,
        }

    @staticmethod
    def _serialize_book(book: ReferenceBook) -> dict[str, Any]:
        return {
            "book_id": book.book_id,
            "title": book.title,
            "author_label": book.author_label,
            "status": book.status,
            "total_chars": book.total_chars,
            "total_segments": book.total_segments,
        }


def build_reference_safety_profile(texts: list[str], *, profile_id: str, book_id: str) -> dict[str, Any]:
    normalized_segments = [_compact_ws(text) for text in texts if _compact_ws(text)]
    joined = "\n".join(normalized_segments)
    protected_terms = _unique(
        [
            *_proper_name_terms(joined),
            *_distinctive_compound_terms(joined),
        ],
        limit=40,
    )
    distinctive_phrases = _distinctive_phrases(joined)
    scene_bridges = _scene_bridges(normalized_segments)
    return {
        "ready": True,
        "profile_id": profile_id,
        "book_id": book_id,
        "protected_terms": protected_terms,
        "distinctive_phrases": distinctive_phrases,
        "scene_bridges": scene_bridges,
        "summary": {
            "protected_term_count": len(protected_terms),
            "distinctive_phrase_count": len(distinctive_phrases),
            "scene_bridge_count": len(scene_bridges),
        },
    }


def _proper_name_terms(text: str) -> list[str]:
    terms = re.findall(r"\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)+\b", text)
    cjk_terms = re.findall(r"[\u4e00-\u9fff]{2,6}(?:[·・][\u4e00-\u9fff]{2,6})?", text)
    return [*terms, *cjk_terms]


def _distinctive_compound_terms(text: str) -> list[str]:
    words = re.findall(r"\b[a-zA-Z][a-zA-Z-]{2,}\b", text)
    compounds: list[str] = []
    for index in range(len(words) - 1):
        left = words[index]
        right = words[index + 1]
        if left.lower() in COMMON_WORDS or right.lower() in COMMON_WORDS:
            continue
        compounds.append(f"{left} {right}")
    return compounds


def _distinctive_phrases(text: str) -> list[str]:
    words = [word.lower() for word in re.findall(r"\b[a-zA-Z][a-zA-Z-]{2,}\b", text)]
    phrases: list[str] = []
    for size in (2, 3, 4):
        grams = Counter(" ".join(words[index : index + size]) for index in range(max(0, len(words) - size + 1)))
        for phrase, count in grams.most_common(40):
            if count < 1:
                continue
            if any(part in COMMON_WORDS for part in phrase.split()):
                continue
            phrases.append(phrase)
    return _unique(phrases, limit=40)


def _scene_bridges(segments: list[str]) -> list[dict[str, Any]]:
    bridges: list[dict[str, Any]] = []
    for index, segment in enumerate(segments[:24]):
        terms = _unique([*_proper_name_terms(segment), *_distinctive_compound_terms(segment)], limit=8)
        phrases = _distinctive_phrases(segment)[:8]
        tokens = _unique([*terms, *phrases], limit=10)
        if len(tokens) < 2:
            continue
        bridges.append(
            {
                "bridge_id": f"bridge_{index + 1:03d}",
                "tokens": tokens,
                "evidence_preview": segment[:180],
                "risk_note": "Do not reuse this combination of entity, object, setting, and action.",
            }
        )
    return bridges


def _unique(values: list[str], *, limit: int) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = _compact_ws(value)
        if len(text) < 4:
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        result.append(text)
        if len(result) >= limit:
            break
    return result


def _compact_ws(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


COMMON_WORDS = {
    "and",
    "the",
    "with",
    "through",
    "while",
    "before",
    "after",
    "into",
    "from",
    "that",
    "this",
    "itself",
    "said",
    "carried",
    "crossed",
}
