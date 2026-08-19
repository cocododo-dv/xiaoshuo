from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from novel_system.db.models import (
    ChapterGoal,
    ChapterState,
    FinalScene,
    ForeshadowTracker,
    OperationLog,
    ReviewItem,
    SceneCard,
    SceneMemory,
    SceneRunState,
    StagedBackfill,
)
from novel_system.services.aggregator import Aggregator
from novel_system.services.errors import DomainError

BACKFILL_MARKER_RE = re.compile(r'{{backfill\s+id=(?P<marker_id>[^\s}]+)\s+text="(?P<marker_text>[^"]+)"\s*}}')
BACKFILL_PENDING = "pending"
BACKFILL_COMPLETED = "completed"
BACKFILL_DEFERRED = "deferred"
BACKFILL_ABANDONED = "abandoned"
BACKFILL_STRATEGIES = {
    "create_tracker_now": BACKFILL_COMPLETED,
    "run_backfill_again": BACKFILL_COMPLETED,
    "explicit_defer_with_tracker": BACKFILL_DEFERRED,
    "mark_staged_abandoned": BACKFILL_ABANDONED,
}


@dataclass(frozen=True)
class ParsedBackfillMarker:
    stage_id: str
    chapter_id: str
    scene_id: str
    marker_id: str
    marker_text: str
    marker_token: str


def clean_backfill_markers(text: str | None) -> str | None:
    if text is None:
        return None
    return BACKFILL_MARKER_RE.sub(lambda match: match.group("marker_text"), text)


class ChapterRuntimeService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.aggregator = Aggregator(session)

    def sync_chapter(self, chapter_id: str) -> tuple[ChapterState, list[StagedBackfill]]:
        self._ensure_chapter_exists(chapter_id)
        chapter_state = self._ensure_chapter_state(chapter_id)
        scenes = self.session.execute(
            select(SceneCard).where(SceneCard.chapter_id == chapter_id).order_by(SceneCard.scene_seq.asc(), SceneCard.scene_id.asc())
        ).scalars().all()
        markers = {marker.stage_id: marker for scene in scenes for marker in self._parse_scene_markers(scene)}
        staged_rows = {
            row.stage_id: row
            for row in self.session.execute(
                select(StagedBackfill).where(StagedBackfill.chapter_id == chapter_id)
            ).scalars().all()
        }

        for stage_id, marker in markers.items():
            row = staged_rows.get(stage_id)
            if row is None:
                row = StagedBackfill(
                    stage_id=marker.stage_id,
                    chapter_id=marker.chapter_id,
                    scene_id=marker.scene_id,
                    marker_id=marker.marker_id,
                    marker_text=marker.marker_text,
                    marker_token=marker.marker_token,
                    status=BACKFILL_PENDING,
                )
                self.session.add(row)
                staged_rows[stage_id] = row
            else:
                row.chapter_id = marker.chapter_id
                row.scene_id = marker.scene_id
                row.marker_id = marker.marker_id
                row.marker_text = marker.marker_text
                row.marker_token = marker.marker_token
            row.status = BACKFILL_PENDING
            row.last_strategy = None
            tracker = self._latest_tracker(marker.chapter_id, marker.marker_id)
            row.linked_tracker_row_id = tracker.row_id if tracker is not None else None

        for row in staged_rows.values():
            if row.stage_id in markers:
                continue
            if row.status == BACKFILL_PENDING:
                row.status = BACKFILL_COMPLETED

        self.session.flush()
        staged_items = self._list_staged_backfill(chapter_id)
        self._recalculate_gate(chapter_state, staged_items)
        self.session.flush()
        return chapter_state, staged_items

    def chapter_state_payload(self, chapter_id: str) -> dict[str, Any]:
        chapter_state, staged_items = self.sync_chapter(chapter_id)
        return self._serialize_chapter_state(chapter_state, staged_items)

    def chapter_state_snapshot(self, chapter_id: str) -> dict[str, Any]:
        """Project the same status without creating or updating runtime rows.

        Status/workbench GET endpoints used to call ``sync_chapter`` and commit,
        so merely refreshing a page created ``ChapterState``/``StagedBackfill``
        records and rewrote pending statuses. Mutations still call
        ``sync_chapter`` before acting; this method only computes their would-be
        view for read paths.
        """

        self._ensure_chapter_exists(chapter_id)
        chapter_state = self.session.get(ChapterState, chapter_id)
        scenes = self.session.execute(
            select(SceneCard)
            .where(SceneCard.chapter_id == chapter_id)
            .order_by(SceneCard.scene_seq.asc(), SceneCard.scene_id.asc())
        ).scalars().all()
        markers = {marker.stage_id: marker for scene in scenes for marker in self._parse_scene_markers(scene)}
        stored_rows = {
            row.stage_id: row
            for row in self.session.execute(
                select(StagedBackfill).where(StagedBackfill.chapter_id == chapter_id)
            ).scalars().all()
        }

        staged_items: list[dict[str, Any]] = []
        all_stage_ids = set(markers) | set(stored_rows)
        for stage_id in all_stage_ids:
            marker = markers.get(stage_id)
            stored = stored_rows.get(stage_id)
            if marker is not None:
                tracker = self._latest_tracker(marker.chapter_id, marker.marker_id)
                item = {
                    "stage_id": marker.stage_id,
                    "chapter_id": marker.chapter_id,
                    "scene_id": marker.scene_id,
                    "marker_id": marker.marker_id,
                    "marker_text": marker.marker_text,
                    "marker_token": marker.marker_token,
                    "status": BACKFILL_PENDING,
                    "linked_tracker_row_id": tracker.row_id if tracker is not None else None,
                    "last_strategy": None,
                }
            else:
                assert stored is not None
                item = self._serialize_staged_backfill(stored)
                if item["status"] == BACKFILL_PENDING:
                    item["status"] = BACKFILL_COMPLETED
            staged_items.append(item)

        staged_items.sort(key=lambda item: (str(item["scene_id"]), str(item["stage_id"])))
        pending_count = sum(1 for item in staged_items if item["status"] == BACKFILL_PENDING)
        manual_hold_reason = chapter_state.manual_hold_reason if chapter_state is not None else None
        aggregate_block_reason = (
            "manual_hold"
            if manual_hold_reason
            else "blocked_waiting_backfill"
            if pending_count > 0
            else "none"
        )
        return {
            "chapter_id": chapter_id,
            "chapter_passed_scene_count": chapter_state.chapter_passed_scene_count if chapter_state is not None else 0,
            "chapter_backfill_pending_count": pending_count,
            "mid_aggregate_enabled_effective": (
                chapter_state.mid_aggregate_enabled_effective if chapter_state is not None else 0
            ),
            "aggregate_block_reason": aggregate_block_reason,
            "manual_hold_reason": manual_hold_reason,
            "last_interim_memory_row_id": chapter_state.last_interim_memory_row_id if chapter_state is not None else None,
            "last_final_memory_row_id": chapter_state.last_final_memory_row_id if chapter_state is not None else None,
            "staged_backfill_items": staged_items,
        }

    def run_backfill(self, chapter_id: str, stage_id: str, strategy: str) -> dict[str, Any]:
        if strategy not in BACKFILL_STRATEGIES:
            raise DomainError("BACKFILL_STRATEGY_INVALID", "unsupported backfill strategy", status_code=400)

        chapter_state, _ = self.sync_chapter(chapter_id)
        staged = self.session.get(StagedBackfill, stage_id)
        if staged is None or staged.chapter_id != chapter_id or staged.status != BACKFILL_PENDING:
            raise DomainError("BACKFILL_STAGE_NOT_FOUND", "backfill stage missing or already finalized")

        tracker = self._resolve_tracker_for_strategy(staged, strategy)
        self._rewrite_marker_references(staged)
        staged.status = BACKFILL_STRATEGIES[strategy]
        staged.last_strategy = strategy
        staged.linked_tracker_row_id = tracker.row_id if tracker is not None else None
        self.session.add(
            OperationLog(
                event_type="chapter_backfill",
                object_type="chapter_runtime",
                object_ref=chapter_id,
                payload_json={
                    "chapter_id": chapter_id,
                    "scene_id": staged.scene_id,
                    "stage_id": staged.stage_id,
                    "marker_id": staged.marker_id,
                    "strategy": strategy,
                    "tracker_row_id": staged.linked_tracker_row_id,
                    "status": staged.status,
                },
            )
        )
        chapter_state, staged_items = self.sync_chapter(chapter_id)
        return {
            "chapter_state": self._serialize_chapter_state(chapter_state, staged_items),
            "receipt": {
                "action": "run_backfill",
                "chapter_id": chapter_id,
                "scene_id": staged.scene_id,
                "stage_id": staged.stage_id,
                "strategy": strategy,
                "tracker_row_id": staged.linked_tracker_row_id,
                "status": staged.status,
            },
        }

    def run_final_aggregate(self, chapter_id: str) -> dict[str, Any]:
        chapter_state, staged_items = self.sync_chapter(chapter_id)
        if chapter_state.manual_hold_reason:
            raise DomainError("CHAPTER_MANUAL_HOLD_ACTIVE", "chapter manual hold is active")
        if chapter_state.chapter_backfill_pending_count > 0:
            raise DomainError(
                "BACKFILL_PENDING_BLOCKS_FINAL_AGGREGATE",
                "pending staged backfill blocks final aggregate",
            )

        result = self.aggregator.run_final_aggregate(chapter_id)
        self.session.add(
            OperationLog(
                event_type="chapter_final_aggregate",
                object_type="chapter_runtime",
                object_ref=chapter_id,
                payload_json={"chapter_id": chapter_id, **(result or {})},
            )
        )
        chapter_state, staged_items = self.sync_chapter(chapter_id)
        return {
            "chapter_state": self._serialize_chapter_state(chapter_state, staged_items),
            "receipt": {
                "action": "run_final_aggregate",
                "chapter_id": chapter_id,
                **(result or {"chapter_memory_row_id": None}),
            },
        }

    def set_manual_hold(self, chapter_id: str, reason: str) -> dict[str, Any]:
        if not reason.strip():
            raise DomainError("MANUAL_HOLD_REASON_REQUIRED", "manual hold reason is required", status_code=400)

        chapter_state, _ = self.sync_chapter(chapter_id)
        chapter_state.manual_hold_reason = reason.strip()
        self.session.add(
            OperationLog(
                event_type="chapter_manual_hold_set",
                object_type="chapter_runtime",
                object_ref=chapter_id,
                payload_json={"chapter_id": chapter_id, "reason": chapter_state.manual_hold_reason},
            )
        )
        chapter_state, staged_items = self.sync_chapter(chapter_id)
        return {
            "chapter_state": self._serialize_chapter_state(chapter_state, staged_items),
            "receipt": {
                "action": "set_manual_hold",
                "chapter_id": chapter_id,
                "reason": chapter_state.manual_hold_reason,
            },
        }

    def clear_manual_hold(self, chapter_id: str) -> dict[str, Any]:
        chapter_state, _ = self.sync_chapter(chapter_id)
        chapter_state.manual_hold_reason = None
        self.session.add(
            OperationLog(
                event_type="chapter_manual_hold_cleared",
                object_type="chapter_runtime",
                object_ref=chapter_id,
                payload_json={"chapter_id": chapter_id},
            )
        )
        chapter_state, staged_items = self.sync_chapter(chapter_id)
        return {
            "chapter_state": self._serialize_chapter_state(chapter_state, staged_items),
            "receipt": {"action": "clear_manual_hold", "chapter_id": chapter_id},
        }

    def _ensure_chapter_exists(self, chapter_id: str) -> None:
        if self.session.get(ChapterGoal, chapter_id) is None:
            raise DomainError("CHAPTER_NOT_FOUND", "chapter not found", status_code=404)

    def _ensure_chapter_state(self, chapter_id: str) -> ChapterState:
        from novel_system.services.chapter_state import ensure_chapter_state

        return ensure_chapter_state(self.session, chapter_id)

    def _parse_scene_markers(self, scene: SceneCard) -> list[ParsedBackfillMarker]:
        text = scene.must_include_text or ""
        markers: list[ParsedBackfillMarker] = []
        for match in BACKFILL_MARKER_RE.finditer(text):
            token = match.group(0)
            marker_id = match.group("marker_id")
            markers.append(
                ParsedBackfillMarker(
                    stage_id=self._stage_id(scene.scene_id, marker_id, token),
                    chapter_id=scene.chapter_id,
                    scene_id=scene.scene_id,
                    marker_id=marker_id,
                    marker_text=match.group("marker_text"),
                    marker_token=token,
                )
            )
        return markers

    def _stage_id(self, scene_id: str, marker_id: str, marker_token: str) -> str:
        digest = hashlib.sha1(marker_token.encode("utf-8")).hexdigest()[:10]
        return f"staged_backfill_{scene_id}_{marker_id}_{digest}"

    def _latest_tracker(self, chapter_id: str, marker_id: str) -> ForeshadowTracker | None:
        return self.session.execute(
            select(ForeshadowTracker)
            .where(ForeshadowTracker.chapter_id == chapter_id, ForeshadowTracker.foreshadow_id == marker_id)
            .order_by(ForeshadowTracker.version.desc(), ForeshadowTracker.row_id.desc())
        ).scalars().first()

    def _resolve_tracker_for_strategy(self, staged: StagedBackfill, strategy: str) -> ForeshadowTracker | None:
        tracker = self._latest_tracker(staged.chapter_id, staged.marker_id)
        if strategy == "run_backfill_again" and tracker is None:
            raise DomainError("BACKFILL_TRACKER_MISSING", "backfill tracker is required before rerunning")

        if strategy == "create_tracker_now":
            return self._upsert_tracker(staged, tracker, tracker_status="open", runtime_eligible=1, basis="foreshadow_open")
        if strategy == "run_backfill_again":
            assert tracker is not None
            return self._upsert_tracker(staged, tracker, tracker_status="open", runtime_eligible=1, basis="foreshadow_open")
        if strategy == "explicit_defer_with_tracker":
            return self._upsert_tracker(staged, tracker, tracker_status="deferred", runtime_eligible=0, basis="backfill_deferred")
        if strategy == "mark_staged_abandoned":
            return self._upsert_tracker(staged, tracker, tracker_status="abandoned", runtime_eligible=0, basis="backfill_abandoned")
        raise DomainError("BACKFILL_STRATEGY_INVALID", "unsupported backfill strategy", status_code=400)

    def _upsert_tracker(
        self,
        staged: StagedBackfill,
        tracker: ForeshadowTracker | None,
        *,
        tracker_status: str,
        runtime_eligible: int,
        basis: str,
    ) -> ForeshadowTracker:
        if tracker is None:
            tracker = ForeshadowTracker(
                row_id=f"foreshadow_{staged.marker_id}_v1",
                foreshadow_id=staged.marker_id,
                version=1,
                chapter_id=staged.chapter_id,
                scene_id=staged.scene_id,
                text=staged.marker_text,
                source_review_id=None,
            )
            self.session.add(tracker)
        tracker.scene_id = staged.scene_id
        tracker.text = staged.marker_text
        tracker.tracker_status = tracker_status
        tracker.active_flag = 1
        tracker.runtime_eligible = runtime_eligible
        tracker.runtime_eligibility_basis = basis
        self.session.flush()
        return tracker

    def _rewrite_marker_references(self, staged: StagedBackfill) -> None:
        scene = self.session.get(SceneCard, staged.scene_id)
        if scene is not None:
            scene.must_include_text = self._replace_marker_token(scene.must_include_text, staged)

        final_scenes = self.session.execute(
            select(FinalScene).where(FinalScene.chapter_id == staged.chapter_id, FinalScene.scene_id == staged.scene_id)
        ).scalars().all()
        state = self.session.get(SceneRunState, staged.scene_id)
        changed_current_final: FinalScene | None = None
        for final_scene in final_scenes:
            rewritten = self._replace_marker_token(final_scene.content, staged)
            if rewritten == final_scene.content:
                continue
            final_scene.content = rewritten
            final_scene.content_hash = hashlib.sha256((rewritten or "").encode("utf-8")).hexdigest()
            if state is not None and state.current_final_scene_row_id == final_scene.row_id:
                changed_current_final = final_scene

        scene_memories = self.session.execute(
            select(SceneMemory).where(
                SceneMemory.chapter_id == staged.chapter_id,
                SceneMemory.scene_id == staged.scene_id,
                SceneMemory.active_flag == 1,
            )
        ).scalars().all()
        for memory in scene_memories:
            memory.content = self._replace_marker_token(memory.content, staged)

        reviews = self.session.execute(
            select(ReviewItem).where(
                ReviewItem.chapter_id == staged.chapter_id,
                ReviewItem.scene_id == staged.scene_id,
                ReviewItem.status == "pending",
            )
        ).scalars().all()
        for review in reviews:
            review.candidate_text = self._replace_marker_token(review.candidate_text, staged)
            payload = dict(review.candidate_payload_json or {})
            text = payload.get("text")
            if isinstance(text, str):
                payload["text"] = self._replace_marker_token(text, staged)
                review.candidate_payload_json = payload

        if changed_current_final is not None:
            # Backfill used to edit canonical prose in place without invalidating
            # its hash-bound continuity proof. Quarantine that proof immediately.
            from novel_system.services.canon_continuity import CanonContinuityService

            try:
                CanonContinuityService(self.session).mark_archive_pending(
                    changed_current_final.row_id
                )
            except DomainError as exc:
                if exc.code != "SCENE_PROJECT_REQUIRED":
                    raise

    def _replace_marker_token(self, text: str | None, staged: StagedBackfill) -> str | None:
        if text is None:
            return None
        return text.replace(staged.marker_token, staged.marker_text)

    def _list_staged_backfill(self, chapter_id: str) -> list[StagedBackfill]:
        return self.session.execute(
            select(StagedBackfill)
            .where(StagedBackfill.chapter_id == chapter_id)
            .order_by(StagedBackfill.scene_id.asc(), StagedBackfill.stage_id.asc())
        ).scalars().all()

    def _recalculate_gate(self, chapter_state: ChapterState, staged_items: list[StagedBackfill]) -> None:
        pending_count = sum(1 for item in staged_items if item.status == BACKFILL_PENDING)
        chapter_state.chapter_backfill_pending_count = pending_count
        if chapter_state.manual_hold_reason:
            chapter_state.aggregate_block_reason = "manual_hold"
        elif pending_count > 0:
            chapter_state.aggregate_block_reason = "blocked_waiting_backfill"
        else:
            chapter_state.aggregate_block_reason = "none"

    def _serialize_chapter_state(self, chapter_state: ChapterState, staged_items: list[StagedBackfill]) -> dict[str, Any]:
        return {
            "chapter_id": chapter_state.chapter_id,
            "chapter_passed_scene_count": chapter_state.chapter_passed_scene_count,
            "chapter_backfill_pending_count": chapter_state.chapter_backfill_pending_count,
            "mid_aggregate_enabled_effective": chapter_state.mid_aggregate_enabled_effective,
            "aggregate_block_reason": chapter_state.aggregate_block_reason,
            "manual_hold_reason": chapter_state.manual_hold_reason,
            "last_interim_memory_row_id": chapter_state.last_interim_memory_row_id,
            "last_final_memory_row_id": chapter_state.last_final_memory_row_id,
            "staged_backfill_items": [self._serialize_staged_backfill(item) for item in staged_items],
        }

    def _serialize_staged_backfill(self, item: StagedBackfill) -> dict[str, Any]:
        return {
            "stage_id": item.stage_id,
            "chapter_id": item.chapter_id,
            "scene_id": item.scene_id,
            "marker_id": item.marker_id,
            "marker_text": item.marker_text,
            "marker_token": item.marker_token,
            "status": item.status,
            "linked_tracker_row_id": item.linked_tracker_row_id,
            "last_strategy": item.last_strategy,
        }
