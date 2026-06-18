"""Event-sourcing reconciliation: detect drift between NarrativeEvent
log projections and entity table state.

Blueprint §2 declares the event log as the single source of truth.
Entity tables (StoryCharacter, LibraryEntity) are convenience caches.
This service replays the event log via NarrativeEventLog and compares
projected state against entity table state to detect divergence.
"""
from __future__ import annotations

import json
import logging
import uuid
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from novel_system.db.models import (
    LibraryEntity,
    NarrativeEvent,
    ReconcileFault,
    ReviewItem,
    StoryCharacter,
)
from novel_system.services.narrative_event_log import NarrativeEventLog

logger = logging.getLogger(__name__)


class DriftFinding:
    """A single state drift between event log and entity table."""

    def __init__(
        self,
        entity_type: str,
        entity_id: str,
        fact_key: str,
        event_log_value: str,
        entity_table_value: Optional[str],
        scene_seq: int,
        severity: str = "warn",
    ):
        self.entity_type = entity_type
        self.entity_id = entity_id
        self.fact_key = fact_key
        self.event_log_value = event_log_value
        self.entity_table_value = entity_table_value
        self.scene_seq = scene_seq
        self.severity = severity  # "warn" or "block"

    def to_dict(self) -> dict:
        return {
            "entity_type": self.entity_type,
            "entity_id": self.entity_id,
            "fact_key": self.fact_key,
            "event_log_value": self.event_log_value,
            "entity_table_value": self.entity_table_value,
            "scene_seq": self.scene_seq,
            "severity": self.severity,
        }


# Hard facts that should never drift — blocking severity
BLOCKING_FACT_KEYS = {"alive", "missing_limb", "location"}
# Soft facts — warning severity
ADVISORY_FACT_KEYS = {"physical_state", "has_item", "appearance", "ability"}


class EventReconciliationService:
    """Detect drift between NarrativeEvent log and entity tables.

    The NarrativeEvent log is the single source of truth (§2 of the design
    blueprint). Entity tables (StoryCharacter, LibraryEntity) are convenience
    caches. This service delegates replay to NarrativeEventLog and compares
    projected state against entity table state to detect divergence.
    """

    def __init__(self, session: Session):
        self.session = session
        self._event_log = NarrativeEventLog(session)

    def reconcile_project(
        self,
        project_id: str,
        *,
        up_to_scene_seq: Optional[int] = None,
        create_review_items: bool = False,
    ) -> list[DriftFinding]:
        """Run full reconciliation for a project. Returns all drift findings."""
        findings: list[DriftFinding] = []

        findings.extend(self._reconcile_characters(project_id, up_to_scene_seq))
        findings.extend(self._reconcile_locations(project_id, up_to_scene_seq))
        findings.extend(self._reconcile_items(project_id, up_to_scene_seq))

        # Persist findings
        for f in findings:
            self._record_fault(f, project_id)
            if create_review_items and f.severity == "block":
                self._push_review_item(f, project_id)

        if findings:
            logger.warning(
                "Reconciliation found %d drift(s) for project %s",
                len(findings),
                project_id,
            )
        else:
            logger.info("No drift detected for project %s", project_id)

        return findings

    # ------------------------------------------------------------------
    # Per-entity-type reconciliation
    # ------------------------------------------------------------------

    def _reconcile_characters(
        self, project_id: str, up_to_scene_seq: Optional[int]
    ) -> list[DriftFinding]:
        """Compare event log character state vs StoryCharacter table."""
        findings: list[DriftFinding] = []

        characters = (
            self.session.query(StoryCharacter)
            .filter_by(project_id=project_id)
            .all()
        )

        if up_to_scene_seq is None:
            up_to_scene_seq = self._latest_scene_seq(project_id)
        if up_to_scene_seq is None:
            return findings

        for char in characters:
            # Delegate replay to NarrativeEventLog
            state = self._event_log.project_character_state(
                char.character_id, project_id, up_to_scene_seq=up_to_scene_seq
            )
            projected = state.as_dict()
            if not projected:
                continue

            # Compare against character table's JSON blobs
            char_data = self._extract_character_facts(char)

            for fact_key, event_value in projected.items():
                if fact_key in BLOCKING_FACT_KEYS:
                    severity = "block"
                elif fact_key in ADVISORY_FACT_KEYS:
                    severity = "warn"
                else:
                    continue

                table_value = char_data.get(fact_key)
                if table_value is not None and self._values_conflict(
                    fact_key, event_value, table_value
                ):
                    findings.append(
                        DriftFinding(
                            entity_type="character",
                            entity_id=char.character_id,
                            fact_key=fact_key,
                            event_log_value=event_value,
                            entity_table_value=table_value,
                            scene_seq=up_to_scene_seq,
                            severity=severity,
                        )
                    )

        return findings

    def _reconcile_locations(
        self, project_id: str, up_to_scene_seq: Optional[int]
    ) -> list[DriftFinding]:
        """Compare event log location state vs LibraryEntity table."""
        findings: list[DriftFinding] = []

        locations = (
            self.session.query(LibraryEntity)
            .filter_by(project_id=project_id, kind="location")
            .all()
        )

        if up_to_scene_seq is None:
            up_to_scene_seq = self._latest_scene_seq(project_id)
        if up_to_scene_seq is None:
            return findings

        for loc in locations:
            # Delegate replay to NarrativeEventLog
            state = self._event_log.project_location_state(
                loc.entity_id, project_id, up_to_scene_seq=up_to_scene_seq
            )
            projected = state.as_dict()
            if not projected:
                continue

            loc_data = self._extract_entity_facts(loc)

            for fact_key, event_value in projected.items():
                severity = "block" if fact_key in BLOCKING_FACT_KEYS else "warn"
                table_value = loc_data.get(fact_key)
                if table_value is not None and self._values_conflict(
                    fact_key, event_value, table_value
                ):
                    findings.append(
                        DriftFinding(
                            entity_type="location",
                            entity_id=loc.entity_id,
                            fact_key=fact_key,
                            event_log_value=event_value,
                            entity_table_value=table_value,
                            scene_seq=up_to_scene_seq,
                            severity=severity,
                        )
                    )

        return findings

    def _reconcile_items(
        self, project_id: str, up_to_scene_seq: Optional[int]
    ) -> list[DriftFinding]:
        """Compare event log item state vs LibraryEntity table."""
        findings: list[DriftFinding] = []

        items = (
            self.session.query(LibraryEntity)
            .filter_by(project_id=project_id, kind="item")
            .all()
        )

        if up_to_scene_seq is None:
            up_to_scene_seq = self._latest_scene_seq(project_id)
        if up_to_scene_seq is None:
            return findings

        for item in items:
            # Delegate replay to NarrativeEventLog
            state = self._event_log.project_item_state(
                item.entity_id, project_id, up_to_scene_seq=up_to_scene_seq
            )
            projected = state.as_dict()
            if not projected:
                continue

            item_data = self._extract_entity_facts(item)

            for fact_key, event_value in projected.items():
                severity = "warn"  # items are generally advisory
                table_value = item_data.get(fact_key)
                if table_value is not None and self._values_conflict(
                    fact_key, event_value, table_value
                ):
                    findings.append(
                        DriftFinding(
                            entity_type="item",
                            entity_id=item.entity_id,
                            fact_key=fact_key,
                            event_log_value=event_value,
                            entity_table_value=table_value,
                            scene_seq=up_to_scene_seq,
                            severity=severity,
                        )
                    )

        return findings

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _latest_scene_seq(self, project_id: str) -> Optional[int]:
        """Get the latest scene_seq from the event log for a project."""
        row = (
            self.session.execute(
                select(NarrativeEvent.scene_seq)
                .where(NarrativeEvent.project_id == project_id)
                .order_by(NarrativeEvent.scene_seq.desc())
                .limit(1)
            )
            .first()
        )
        return row[0] if row else None

    def _extract_character_facts(self, char: StoryCharacter) -> dict[str, str]:
        """Extract checkable facts from StoryCharacter's JSON blobs.

        StoryCharacter stores structured data in summary_json, synopsis_json,
        and bible_json (all JSON-typed columns, not plain text).
        """
        facts: dict[str, str] = {}
        for field_name in ("bible_json", "synopsis_json", "summary_json"):
            blob = getattr(char, field_name, None)
            if not blob:
                continue
            if isinstance(blob, str):
                blob = self._safe_json(blob)
            if not isinstance(blob, dict):
                continue
            for key in list(BLOCKING_FACT_KEYS) + list(ADVISORY_FACT_KEYS):
                if key in blob and key not in facts:
                    facts[key] = str(blob[key])
        return facts

    def _extract_entity_facts(self, entity: LibraryEntity) -> dict[str, str]:
        """Extract checkable facts from LibraryEntity's JSON.

        LibraryEntity stores structured data in details_json (JSON-typed)
        and summary (plain Text).
        """
        facts: dict[str, str] = {}
        # Check details_json (dict)
        blob = entity.details_json
        if blob:
            if isinstance(blob, str):
                blob = self._safe_json(blob)
            if isinstance(blob, dict):
                for key in list(BLOCKING_FACT_KEYS) + list(ADVISORY_FACT_KEYS):
                    if key in blob and key not in facts:
                        facts[key] = str(blob[key])
        # Check summary (plain text) — try to parse as JSON in case it holds structured data
        if entity.summary:
            parsed = self._safe_json(entity.summary)
            if isinstance(parsed, dict):
                for key in list(BLOCKING_FACT_KEYS) + list(ADVISORY_FACT_KEYS):
                    if key in parsed and key not in facts:
                        facts[key] = str(parsed[key])
        return facts

    @staticmethod
    def _safe_json(raw) -> Optional[dict]:
        if isinstance(raw, dict):
            return raw
        if isinstance(raw, str):
            try:
                return json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                return None
        return None

    @staticmethod
    def _values_conflict(fact_key: str, event_value: str, table_value: str) -> bool:
        """Check if two fact values are in conflict."""
        if event_value is None or table_value is None:
            return False
        # Normalize for comparison
        ev = str(event_value).strip().lower()
        tv = str(table_value).strip().lower()
        if ev == tv:
            return False
        # For boolean-like facts (alive), check semantic equivalence
        if fact_key == "alive":
            true_vals = {"true", "1", "yes", "alive"}
            false_vals = {"false", "0", "no", "dead", "deceased"}
            ev_bool = ev in true_vals
            tv_bool = tv in true_vals
            if (ev in true_vals or ev in false_vals) and (
                tv in true_vals or tv in false_vals
            ):
                return ev_bool != tv_bool
        return ev != tv

    def _record_fault(self, finding: DriftFinding, project_id: str) -> None:
        """Record a ReconcileFault in the database."""
        fault = ReconcileFault(
            fault_scope="event_sourcing",
            severity=finding.severity,
            object_ref=f"{finding.entity_type}:{finding.entity_id}:{finding.fact_key}",
            details_json=finding.to_dict(),
        )
        self.session.add(fault)

    def _push_review_item(self, finding: DriftFinding, project_id: str) -> None:
        """Push a blocking drift finding to the review inbox.

        Uses the ReviewItem schema: review_id (PK), item_type, status,
        candidate_text (required), candidate_payload_json, project_id.
        """
        message = (
            f"Event log says {finding.fact_key}={finding.event_log_value!r} "
            f"but entity table says {finding.entity_table_value!r} "
            f"at scene_seq={finding.scene_seq}"
        )
        review = ReviewItem(
            review_id=str(uuid.uuid4()),
            item_type="reconciliation_fault",
            status="pending",
            project_id=project_id,
            candidate_text=(
                f"State drift: {finding.entity_type}/{finding.entity_id}"
                f".{finding.fact_key} — {message}"
            ),
            candidate_payload_json={
                "drift": finding.to_dict(),
                "message": message,
            },
        )
        self.session.add(review)
