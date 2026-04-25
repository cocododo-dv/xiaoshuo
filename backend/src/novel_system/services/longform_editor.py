from __future__ import annotations

import hashlib
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from novel_system.db.models import LongformDiagnosticCard, ReviewItem
from novel_system.services.errors import DomainError
from novel_system.services.hash_engine import canonical_json
from novel_system.services.literary_quality import LiteraryQualityService
from novel_system.services.longform_control import LongformControlService
from novel_system.services.versioning.shared import now_iso

CARD_TYPES = {
    "character_arc_gap",
    "foreshadow_debt",
    "promise_without_payoff",
    "information_congestion",
    "theme_pressure_light",
    "relationship_turn_stall",
    "ending_drive_drop",
    "reference_leakage_risk",
}
CARD_STATUSES = {"open", "resolved", "dismissed", "published_guidance"}
CARD_ACTIONS = {"resolve": "resolved", "dismiss": "dismissed", "reopen": "open"}
GUIDANCE_SCOPES = {"global", "chapter", "scene", "character"}


class LongformEditorService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def overview(self) -> dict[str, Any]:
        dashboard = LongformControlService(self.session).dashboard()
        cards = self.list_cards()
        return {
            "dashboard": dashboard,
            "cards": {
                "summary": self._cards_summary(cards["items"]),
                "items": cards["items"],
            },
        }

    def diagnose(self) -> dict[str, Any]:
        dashboard = LongformControlService(self.session).dashboard()
        quality = LiteraryQualityService(self.session).overview(text_layer="author_draft_preferred")
        specs = self._candidate_specs(dashboard=dashboard, quality=quality)
        current_keyed_ids: set[str] = set()

        for spec in specs:
            card = self._upsert_card(spec)
            current_keyed_ids.add(card.card_id)

        open_cards = self.session.execute(
            select(LongformDiagnosticCard).where(LongformDiagnosticCard.status == "open")
        ).scalars().all()
        for card in open_cards:
            if card.card_id not in current_keyed_ids:
                card.status = "resolved"
                evidence = dict(card.evidence_json or {})
                evidence["resolved_by_refresh_at"] = now_iso()
                card.evidence_json = evidence

        self.session.flush()
        cards = self.list_cards()["items"]
        return {
            "summary": self._cards_summary(cards),
            "cards": cards,
            "dashboard_summary": dashboard.get("summary") or {},
        }

    def list_cards(
        self,
        *,
        status: str | None = None,
        card_type: str | None = None,
        chapter_id: str | None = None,
        scene_id: str | None = None,
    ) -> dict[str, Any]:
        if status and status not in CARD_STATUSES:
            raise DomainError("LONGFORM_CARD_STATUS_INVALID", "unsupported longform diagnostic card status", status_code=400)
        if card_type and card_type not in CARD_TYPES:
            raise DomainError("LONGFORM_CARD_TYPE_INVALID", "unsupported longform diagnostic card type", status_code=400)
        query = select(LongformDiagnosticCard)
        if status:
            query = query.where(LongformDiagnosticCard.status == status)
        if card_type:
            query = query.where(LongformDiagnosticCard.card_type == card_type)
        if chapter_id:
            query = query.where(LongformDiagnosticCard.chapter_id == chapter_id)
        if scene_id:
            query = query.where(LongformDiagnosticCard.scene_id == scene_id)
        rows = self.session.execute(
            query.order_by(
                LongformDiagnosticCard.status.asc(),
                LongformDiagnosticCard.severity.desc(),
                LongformDiagnosticCard.updated_at.desc(),
                LongformDiagnosticCard.card_id.asc(),
            )
        ).scalars().all()
        items = [self.serialize_card(row) for row in rows]
        return {"summary": self._cards_summary(items), "items": items}

    def card_action(self, card_id: str, *, action: str, note: str | None = None) -> dict[str, Any]:
        card = self._card(card_id)
        status = CARD_ACTIONS.get(action)
        if status is None:
            raise DomainError("LONGFORM_CARD_ACTION_INVALID", "action must be resolve, dismiss, or reopen", status_code=400)
        card.status = status
        evidence = dict(card.evidence_json or {})
        if note:
            evidence.setdefault("operator_notes", []).append(
                {"action": action, "note": str(note).strip(), "created_at": now_iso()}
            )
        card.evidence_json = evidence
        self.session.flush()
        return {"card": self.serialize_card(card)}

    def publish_guidance(
        self,
        card_id: str,
        *,
        scope_type: str,
        scope_ref_id: str | None,
        content: str,
    ) -> dict[str, Any]:
        card = self._card(card_id)
        if scope_type not in GUIDANCE_SCOPES:
            raise DomainError("LONGFORM_GUIDANCE_SCOPE_INVALID", "scope_type must be global, chapter, scene, or character", status_code=400)
        normalized_scope_ref = "global" if scope_type == "global" else _required_text(scope_ref_id, field="scope_ref_id")
        guidance_text = _required_text(content, field="content")
        guidance_id = f"lfguidance_{_short_hash({'card_id': card.card_id, 'scope_type': scope_type, 'scope_ref_id': normalized_scope_ref, 'content': guidance_text})}"
        review_id = f"review_{guidance_id}"
        payload = {
            "guidance_id": guidance_id,
            "card_id": card.card_id,
            "card_type": card.card_type,
            "scope_type": scope_type,
            "scope_ref_id": normalized_scope_ref,
            "content": guidance_text,
            "evidence": card.evidence_json or {},
            "recommendation": card.recommendation_json or {},
            "source_snapshot_hash": card.source_snapshot_hash,
        }
        review = self.session.get(ReviewItem, review_id)
        if review is None:
            review = ReviewItem(
                review_id=review_id,
                chapter_id=card.chapter_id,
                scene_id=card.scene_id,
                item_type="longform_structure_guidance",
                candidate_text=guidance_text,
                candidate_payload_json=payload,
                active_on_approve=1,
            )
            self.session.add(review)
        else:
            review.chapter_id = card.chapter_id
            review.scene_id = card.scene_id
            review.item_type = "longform_structure_guidance"
            review.candidate_text = guidance_text
            review.candidate_payload_json = payload
        card.status = "published_guidance"
        card.review_id = review.review_id
        card.guidance_id = guidance_id
        self.session.flush()
        self.session.refresh(review)
        return {"card": self.serialize_card(card), "review": self._serialize_review(review)}

    def _candidate_specs(self, *, dashboard: dict[str, Any], quality: dict[str, Any]) -> list[dict[str, Any]]:
        specs: list[dict[str, Any]] = []
        specs.extend(self._character_arc_gap_specs(dashboard))
        specs.extend(self._foreshadow_specs(dashboard))
        specs.extend(self._promise_specs(dashboard))
        specs.extend(self._information_specs(quality))
        specs.extend(self._ending_specs(quality))
        specs.extend(self._relationship_specs(dashboard))
        specs.extend(self._theme_specs(dashboard))
        return specs

    @staticmethod
    def _character_arc_gap_specs(dashboard: dict[str, Any]) -> list[dict[str, Any]]:
        specs: list[dict[str, Any]] = []
        seen: set[tuple[str, str]] = set()
        for row in dashboard.get("character_arc_timeline") or []:
            if not row.get("low_agency"):
                continue
            key = (str(row.get("character_id") or ""), str(row.get("scene_id") or ""))
            if key in seen:
                continue
            seen.add(key)
            character_id, scene_id = key
            specs.append(
                _spec(
                    card_type="character_arc_gap",
                    severity="major",
                    object_type="character",
                    object_id=character_id,
                    chapter_id=row.get("chapter_id"),
                    scene_id=scene_id,
                    character_id=character_id,
                    source_refs=[row.get("target_ref") or f"scene_card:{scene_id}"],
                    evidence={
                        "character_id": character_id,
                        "desire": row.get("desire") or "",
                        "choice_under_pressure": row.get("choice_under_pressure") or "",
                        "power_shift": row.get("power_shift") or "",
                        "issue": "character has low visible agency in this scene",
                    },
                    recommendation={
                        "action": "force_visible_choice",
                        "summary": "Give the character two incompatible options and make the chosen option cost something visible.",
                    },
                )
            )
        return specs

    @staticmethod
    def _foreshadow_specs(dashboard: dict[str, Any]) -> list[dict[str, Any]]:
        specs: list[dict[str, Any]] = []
        for row in dashboard.get("foreshadow_debts") or []:
            if row.get("debt_state") != "open":
                continue
            specs.append(
                _spec(
                    card_type="foreshadow_debt",
                    severity="major",
                    object_type="foreshadow",
                    object_id=row.get("foreshadow_id") or row.get("row_id"),
                    chapter_id=row.get("chapter_id"),
                    scene_id=row.get("scene_id"),
                    source_refs=[f"foreshadow_tracker:{row.get('row_id')}"],
                    evidence={
                        "text": row.get("text") or "",
                        "tracker_status": row.get("tracker_status") or "",
                        "created_at": row.get("created_at") or "",
                    },
                    recommendation={
                        "action": "assign_payoff_window",
                        "summary": "Decide whether to pay off, transform, or retire this hook in the next structural pass.",
                    },
                )
            )
        return specs

    @staticmethod
    def _promise_specs(dashboard: dict[str, Any]) -> list[dict[str, Any]]:
        specs: list[dict[str, Any]] = []
        for row in dashboard.get("promise_payoff") or []:
            if row.get("status") != "debt_open" and not row.get("open_hook_count"):
                continue
            chapter_id = row.get("chapter_id")
            specs.append(
                _spec(
                    card_type="promise_without_payoff",
                    severity="major",
                    object_type="chapter",
                    object_id=chapter_id,
                    chapter_id=chapter_id,
                    scene_id=None,
                    source_refs=[row.get("target_ref") or f"chapter:{chapter_id}"],
                    evidence={
                        "chapter_promise": row.get("chapter_promise") or "",
                        "ending_question": row.get("ending_question") or "",
                        "open_hook_count": row.get("open_hook_count") or 0,
                    },
                    recommendation={
                        "action": "write_payoff_contract",
                        "summary": "Name the promised answer and the chapter or scene where it will be paid, inverted, or intentionally deferred.",
                    },
                )
            )
        return specs

    @staticmethod
    def _information_specs(quality: dict[str, Any]) -> list[dict[str, Any]]:
        specs: list[dict[str, Any]] = []
        for item in quality.get("items") or []:
            risky_dimensions = [
                finding
                for finding in item.get("findings") or []
                if finding.get("dimension") in {"expository_dialogue", "model_voice", "no_choice_scene", "choice_pressure"}
            ]
            if not risky_dimensions:
                continue
            object_type = "scene" if item.get("object_type") == "scene" else "chapter"
            specs.append(
                _spec(
                    card_type="information_congestion",
                    severity="major",
                    object_type=object_type,
                    object_id=item.get("object_id"),
                    chapter_id=item.get("chapter_id"),
                    scene_id=item.get("scene_id"),
                    source_refs=[item.get("source_ref") or ""],
                    evidence={
                        "text_layer": item.get("text_layer"),
                        "source_ref": item.get("source_ref"),
                        "findings": risky_dimensions[:4],
                    },
                    recommendation={
                        "action": "move_information_into_pressure",
                        "summary": "Turn explanation into action, silence, contradiction, or partial answers under pressure.",
                    },
                )
            )
        return specs

    @staticmethod
    def _ending_specs(quality: dict[str, Any]) -> list[dict[str, Any]]:
        specs: list[dict[str, Any]] = []
        for item in quality.get("items") or []:
            risky_dimensions = [
                finding
                for finding in item.get("findings") or []
                if finding.get("dimension") in {"summary_ending", "ending_drive"}
            ]
            if not risky_dimensions:
                continue
            object_type = "scene" if item.get("object_type") == "scene" else "chapter"
            severity = "critical" if item.get("object_type") == "scene" else "major"
            specs.append(
                _spec(
                    card_type="ending_drive_drop",
                    severity=severity,
                    object_type=object_type,
                    object_id=item.get("object_id"),
                    chapter_id=item.get("chapter_id"),
                    scene_id=item.get("scene_id"),
                    source_refs=[item.get("source_ref") or ""],
                    evidence={
                        "text_layer": item.get("text_layer"),
                        "source_ref": item.get("source_ref"),
                        "findings": risky_dimensions[:3],
                    },
                    recommendation={
                        "action": "land_on_irreversible_action",
                        "summary": "Cut explanatory closure and end on action, reveal, departure, refusal, or object movement.",
                    },
                )
            )
        return specs

    @staticmethod
    def _relationship_specs(dashboard: dict[str, Any]) -> list[dict[str, Any]]:
        specs: list[dict[str, Any]] = []
        for row in dashboard.get("relation_tension_matrix") or []:
            scene_ids = row.get("scene_ids") or []
            pressure = row.get("unexploded_points") or []
            if scene_ids or pressure:
                continue
            pair = row.get("pair") or []
            object_id = "/".join(str(item) for item in pair) if isinstance(pair, list) else str(pair or "")
            if not object_id:
                continue
            specs.append(
                _spec(
                    card_type="relationship_turn_stall",
                    severity="minor",
                    object_type="relation",
                    object_id=object_id,
                    chapter_id=None,
                    scene_id=None,
                    source_refs=[row.get("target_ref") or ""],
                    evidence={"pair": pair, "tension_note": row.get("tension_note") or ""},
                    recommendation={
                        "action": "schedule_relationship_turn",
                        "summary": "Give this relationship a visible pressure event or remove it from the current structural promise.",
                    },
                )
            )
        return specs

    @staticmethod
    def _theme_specs(dashboard: dict[str, Any]) -> list[dict[str, Any]]:
        specs: list[dict[str, Any]] = []
        for row in dashboard.get("chapters") or []:
            if row.get("average_writer_score") is None or float(row.get("average_writer_score") or 1) >= 0.45:
                continue
            if row.get("open_revision_candidate_count") or row.get("requires_human_review_count"):
                chapter_id = row.get("chapter_id")
                specs.append(
                    _spec(
                        card_type="theme_pressure_light",
                        severity="minor",
                        object_type="chapter",
                        object_id=chapter_id,
                        chapter_id=chapter_id,
                        scene_id=None,
                        source_refs=[f"chapter:{chapter_id}"],
                        evidence={
                            "average_writer_score": row.get("average_writer_score"),
                            "open_revision_candidate_count": row.get("open_revision_candidate_count") or 0,
                            "requires_human_review_count": row.get("requires_human_review_count") or 0,
                        },
                        recommendation={
                            "action": "name_theme_pressure",
                            "summary": "State which value is being tested, then make the next scene force a cost around that value.",
                        },
                    )
                )
        return specs

    def _upsert_card(self, spec: dict[str, Any]) -> LongformDiagnosticCard:
        snapshot_hash = _snapshot_hash(spec)
        card_id = f"lfcard_{spec['card_type']}_{snapshot_hash[:16]}"
        card = self.session.get(LongformDiagnosticCard, card_id)
        if card is None:
            card = LongformDiagnosticCard(
                card_id=card_id,
                card_type=spec["card_type"],
                severity=spec["severity"],
                status="open",
                object_type=spec["object_type"],
                object_id=str(spec["object_id"] or spec["object_type"]),
                chapter_id=spec.get("chapter_id"),
                scene_id=spec.get("scene_id"),
                character_id=spec.get("character_id"),
                source_refs_json=spec["source_refs"],
                evidence_json=spec["evidence"],
                recommendation_json=spec["recommendation"],
                source_snapshot_hash=snapshot_hash,
            )
            self.session.add(card)
            return card

        card.severity = spec["severity"]
        card.source_refs_json = spec["source_refs"]
        card.evidence_json = spec["evidence"]
        card.recommendation_json = spec["recommendation"]
        card.chapter_id = spec.get("chapter_id")
        card.scene_id = spec.get("scene_id")
        card.character_id = spec.get("character_id")
        if card.status == "resolved":
            card.status = "open"
        return card

    def _card(self, card_id: str) -> LongformDiagnosticCard:
        card = self.session.get(LongformDiagnosticCard, card_id)
        if card is None:
            raise DomainError("LONGFORM_CARD_NOT_FOUND", f"longform diagnostic card {card_id} not found", status_code=404)
        return card

    @staticmethod
    def serialize_card(card: LongformDiagnosticCard) -> dict[str, Any]:
        return {
            "card_id": card.card_id,
            "card_type": card.card_type,
            "severity": card.severity,
            "status": card.status,
            "object_type": card.object_type,
            "object_id": card.object_id,
            "chapter_id": card.chapter_id,
            "scene_id": card.scene_id,
            "character_id": card.character_id,
            "source_refs": list(card.source_refs_json or []),
            "evidence": dict(card.evidence_json or {}),
            "recommendation": dict(card.recommendation_json or {}),
            "source_snapshot_hash": card.source_snapshot_hash,
            "review_id": card.review_id,
            "guidance_id": card.guidance_id,
            "created_at": card.created_at,
            "updated_at": card.updated_at,
        }

    @staticmethod
    def _serialize_review(review: ReviewItem) -> dict[str, Any]:
        return {
            "review_id": review.review_id,
            "item_type": review.item_type,
            "target_collection": review.target_collection,
            "status": review.status,
            "candidate_text": review.candidate_text,
            "candidate_payload_json": review.candidate_payload_json,
            "materialize_status": review.materialize_status,
            "approved_item_row_id": review.approved_item_row_id,
        }

    @staticmethod
    def _cards_summary(items: list[dict[str, Any]]) -> dict[str, Any]:
        return {
            "total_count": len(items),
            "open_count": sum(1 for item in items if item.get("status") == "open"),
            "resolved_count": sum(1 for item in items if item.get("status") == "resolved"),
            "dismissed_count": sum(1 for item in items if item.get("status") == "dismissed"),
            "published_guidance_count": sum(1 for item in items if item.get("status") == "published_guidance"),
            "critical_count": sum(1 for item in items if item.get("severity") == "critical"),
            "major_count": sum(1 for item in items if item.get("severity") == "major"),
        }


def _spec(
    *,
    card_type: str,
    severity: str,
    object_type: str,
    object_id: Any,
    chapter_id: Any,
    scene_id: Any,
    source_refs: list[Any],
    evidence: dict[str, Any],
    recommendation: dict[str, Any],
    character_id: Any = None,
) -> dict[str, Any]:
    return {
        "card_type": card_type,
        "severity": severity,
        "object_type": object_type,
        "object_id": str(object_id or object_type),
        "chapter_id": str(chapter_id) if chapter_id else None,
        "scene_id": str(scene_id) if scene_id else None,
        "character_id": str(character_id) if character_id else None,
        "source_refs": [str(ref) for ref in source_refs if str(ref or "").strip()],
        "evidence": evidence,
        "recommendation": recommendation,
    }


def _snapshot_hash(spec: dict[str, Any]) -> str:
    payload = {
        "card_type": spec["card_type"],
        "object_type": spec["object_type"],
        "object_id": spec["object_id"],
        "chapter_id": spec.get("chapter_id"),
        "scene_id": spec.get("scene_id"),
        "character_id": spec.get("character_id"),
        "source_refs": spec.get("source_refs") or [],
        "evidence": spec.get("evidence") or {},
    }
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def _short_hash(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()[:16]


def _required_text(value: str | None, *, field: str) -> str:
    if isinstance(value, str) and value.strip():
        return value.strip()
    raise DomainError("LONGFORM_GUIDANCE_INVALID", f"missing {field}", status_code=400)
