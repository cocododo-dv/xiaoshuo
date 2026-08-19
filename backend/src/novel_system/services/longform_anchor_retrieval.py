from __future__ import annotations

import hashlib
import json
import math
import re
import unicodedata
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from novel_system.db.models import ChapterGoal, LongformAnchor, SceneCard
from novel_system.services.scene_digest import scene_card_digest


_HARD_ANCHOR_KINDS = {"fact", "trait", "setting", "timeline"}
_LATIN_TOKEN_RE = re.compile(r"[a-z0-9_:-]+")
_CJK_RUN_RE = re.compile(r"[\u3400-\u9fff]+")


@dataclass(frozen=True, slots=True)
class AnchorSelection:
    anchors: list[LongformAnchor]
    selection_reasons: dict[str, str]
    query_hash: str
    strategy: str = "mandatory_plus_structural_lexical_v1"


class LongformAnchorRetriever:
    """Select long-form memory with deterministic, auditable relevance.

    Referenced contract anchors and pinned hard facts are mandatory.  The faded
    pool is not dumped wholesale into every prompt: it is recalled by a hybrid
    of catalog metadata (chapter/entity/source references) and Unicode-aware
    lexical n-grams.  This avoids pretending the project's deterministic local
    vector fallback is a semantic embedding while still making faded memory
    usable in the scene where it becomes relevant again.
    """

    def __init__(self, session: Session) -> None:
        self.session = session

    def select(
        self,
        *,
        project_id: str,
        chapter: ChapterGoal,
        scene: SceneCard,
        contract_constraints: list[dict[str, Any]],
        referenced_anchor_ids: set[str],
        retrieved_limit: int = 6,
    ) -> AnchorSelection:
        all_anchors = list(
            self.session.execute(
                select(LongformAnchor)
                .where(LongformAnchor.project_id == project_id)
                .order_by(LongformAnchor.created_at, LongformAnchor.anchor_id)
            ).scalars().all()
        )
        query = self._query_text(chapter, scene, contract_constraints)
        query_tokens = self._tokens(query)
        query_hash = hashlib.sha256(query.encode("utf-8")).hexdigest()

        mandatory: list[LongformAnchor] = []
        reasons: dict[str, str] = {}
        faded_pool: list[LongformAnchor] = []
        for anchor in all_anchors:
            if anchor.anchor_id in referenced_anchor_ids:
                mandatory.append(anchor)
                reasons[anchor.anchor_id] = "chapter_contract_reference"
            elif anchor.status == "pinned" and anchor.kind in _HARD_ANCHOR_KINDS:
                mandatory.append(anchor)
                reasons[anchor.anchor_id] = "pinned_hard_anchor"
            elif anchor.status == "faded" and anchor.kind in _HARD_ANCHOR_KINDS:
                faded_pool.append(anchor)

        scored: list[tuple[float, str, LongformAnchor]] = []
        for anchor in faded_pool:
            lexical = self._lexical_score(anchor, query, query_tokens)
            structural = self._structural_score(anchor, chapter, scene)
            if lexical <= 0 and structural <= 0:
                continue
            # Structural matches are deliberately stronger than fuzzy text.
            score = structural * 10.0 + lexical
            scored.append((score, anchor.anchor_id, anchor))
        scored.sort(key=lambda item: (-item[0], item[1]))

        retrieved: list[LongformAnchor] = []
        for score, _anchor_id, anchor in scored[: max(0, retrieved_limit)]:
            retrieved.append(anchor)
            reasons[anchor.anchor_id] = f"recalled_relevance:{score:.3f}"

        selected = [*mandatory, *retrieved]
        # A referenced anchor can also qualify through another lane; preserve
        # the stable database order for mandatory rows and score order for recall.
        deduped: list[LongformAnchor] = []
        seen: set[str] = set()
        for anchor in selected:
            if anchor.anchor_id in seen:
                continue
            seen.add(anchor.anchor_id)
            deduped.append(anchor)
        return AnchorSelection(
            anchors=deduped,
            selection_reasons=reasons,
            query_hash=query_hash,
        )

    @staticmethod
    def _query_text(
        chapter: ChapterGoal,
        scene: SceneCard,
        constraints: list[dict[str, Any]],
    ) -> str:
        constraint_text = "\n".join(
            str(item.get("text") or "")
            for item in constraints
            if isinstance(item, dict)
        )
        identities = " ".join(
            value
            for value in [
                scene.pov_character_id,
                *(scene.onstage_chars_json or []),
            ]
            if value
        )
        return "\n".join(
            part
            for part in (
                chapter.chapter_goal or "",
                json.dumps(chapter.narrative_json or {}, ensure_ascii=False, sort_keys=True),
                scene_card_digest(scene),
                identities,
                constraint_text,
            )
            if part
        )

    @classmethod
    def _lexical_score(
        cls,
        anchor: LongformAnchor,
        query: str,
        query_tokens: set[str],
    ) -> float:
        anchor_text = "\n".join(
            part for part in (anchor.text, anchor.note or "", anchor.source_ref or "") if part
        )
        anchor_tokens = cls._tokens(anchor_text)
        overlap = anchor_tokens & query_tokens
        if not overlap:
            return 0.0
        normalized_anchor = cls._normalize(anchor.text)
        normalized_query = cls._normalize(query)
        exact_bonus = 8.0 if normalized_anchor and normalized_anchor in normalized_query else 0.0
        weighted_overlap = sum(2.0 if cls._is_cjk_token(token) else 1.0 for token in overlap)
        normalization = math.sqrt(max(1, len(anchor_tokens)))
        return exact_bonus + weighted_overlap / normalization

    @classmethod
    def _structural_score(
        cls,
        anchor: LongformAnchor,
        chapter: ChapterGoal,
        scene: SceneCard,
    ) -> float:
        score = 0.0
        source = cls._normalize(anchor.source_ref or "")
        identity_values = {
            cls._normalize(value)
            for value in [scene.pov_character_id, *(scene.onstage_chars_json or [])]
            if value
        }
        if source and any(identity and identity in source for identity in identity_values):
            score += 3.0
        if source and cls._normalize(scene.scene_id) in source:
            score += 4.0
        if source and cls._normalize(chapter.chapter_id) in source:
            score += 2.0

        metadata = cls._note_metadata(anchor.note)
        chapter_hint = metadata.get("chapter")
        if chapter_hint is None:
            chapter_hint = metadata.get("ch")
        if chapter_hint is not None:
            expected_values = {
                str(chapter.chapter_id),
                str(chapter.display_order) if chapter.display_order is not None else "",
            }
            if str(chapter_hint) in expected_values:
                score += 4.0
        entity_hints = metadata.get("entity_ids") or metadata.get("characters") or []
        if isinstance(entity_hints, str):
            entity_hints = [entity_hints]
        if isinstance(entity_hints, list):
            normalized_hints = {cls._normalize(value) for value in entity_hints}
            score += 3.0 * len(identity_values & normalized_hints)
        return score

    @classmethod
    def _tokens(cls, value: str) -> set[str]:
        normalized = cls._normalize(value)
        tokens = set(_LATIN_TOKEN_RE.findall(normalized))
        for run in _CJK_RUN_RE.findall(normalized):
            if len(run) == 1:
                tokens.add(run)
                continue
            tokens.update(run[index : index + 2] for index in range(len(run) - 1))
        return tokens

    @staticmethod
    def _normalize(value: Any) -> str:
        return " ".join(
            unicodedata.normalize("NFKC", str(value or "")).casefold().split()
        )

    @staticmethod
    def _is_cjk_token(value: str) -> bool:
        return any("\u3400" <= char <= "\u9fff" for char in value)

    @staticmethod
    def _note_metadata(note: str | None) -> dict[str, Any]:
        try:
            parsed = json.loads(note or "{}")
        except (TypeError, ValueError):
            return {}
        if not isinstance(parsed, dict):
            return {}
        fe = parsed.get("fe")
        if isinstance(fe, dict):
            return {**parsed, **fe}
        return parsed
