from __future__ import annotations

import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from novel_system.db.models import (
    ChapterGoal,
    ChapterState,
    FinalScene,
    QcReport,
    ReferenceBook,
    SceneBundle,
    SceneCard,
    SceneRunState,
)
from novel_system.services.chapter_runner import ChapterRunnerService
from novel_system.services.errors import DomainError
from novel_system.services.reference_learning import ReferenceLearningService
from novel_system.services.settings_helpers import llm_generation_mode
from novel_system.services.versioning import PromotionService, ReviewMaterializationService

DRAGON_REFERENCE_BOOK_ID = "refbook_d4ae8e00eea8"
DRAGON_DEMO_PROFILE_NOT_READY = "DRAGON_PROFILE_NOT_READY"
DRAGON_DEMO_BOOK_NOT_FOUND = "DRAGON_REFERENCE_BOOK_NOT_FOUND"

FORBIDDEN_SOURCE_MARKERS = (
    "txt8080",
    "声明：本书",
    "路明非",
    "楚子航",
    "卡塞尔",
    "江南",
    "龙族",
    "Lu Mingfei",
    "Cassell",
    "Jiang Nan",
    "Dragon Raja",
)

DEMO_CHAPTERS: tuple[dict[str, Any], ...] = (
    {
        "chapter_id": "XXDEMO_CH01",
        "scene_id": "XXDEMO_CH01_SC01",
        "chapter_goal": "Open an original cultivation fantasy demo with a mortal oath and a hidden sect trial.",
        "main_plot_push": "The protagonist finds a spirit seal that points toward the mountain gate.",
        "emotional_target": "Wonder under pressure.",
        "ending_effect": "The seal answers with a dangerous invitation.",
        "location": "Misty ferry below Azure Peak",
        "scene_goal": "Show the first brush with cultivation power without copying source characters or settings.",
        "beats": ["mortal errand", "spirit seal wakes", "sect messenger tests resolve"],
        "must_include": "the spirit seal glows like cold jade",
        "hook": "continue",
    },
    {
        "chapter_id": "XXDEMO_CH02",
        "scene_id": "XXDEMO_CH02_SC01",
        "chapter_goal": "Escalate the trial into a sect conflict around a forbidden medicine furnace.",
        "main_plot_push": "The protagonist protects a weaker initiate during the entrance test.",
        "emotional_target": "Fear turning into disciplined courage.",
        "ending_effect": "A senior elder notices the protagonist's unusual meridian pattern.",
        "location": "Outer sect furnace hall",
        "scene_goal": "Turn the training challenge into a moral decision with clear consequences.",
        "beats": ["furnace sabotage", "initiate in danger", "elder intervenes"],
        "must_include": "the furnace flame bends away from the innocent initiate",
        "hook": "continue",
    },
    {
        "chapter_id": "XXDEMO_CH03",
        "scene_id": "XXDEMO_CH03_SC01",
        "chapter_goal": "Close the demo with an original oath, a new enemy, and a clean next-chapter hook.",
        "main_plot_push": "The protagonist earns a sect place while refusing an unsafe shortcut.",
        "emotional_target": "Relief mixed with sharper responsibility.",
        "ending_effect": "A rival clan marks the protagonist for future pursuit.",
        "location": "Moonlit oath platform",
        "scene_goal": "Land a satisfying demo endpoint while leaving a fresh cultivation hook.",
        "beats": ["oath platform", "shortcut refused", "rival clan threat"],
        "must_include": "the oath platform rings once under the moon",
        "hook": "demo endpoint with sequel hook",
    },
)


class DragonXianxiaDemoService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def status(self) -> dict[str, Any]:
        book = self._book()
        if book is None:
            return self._payload(book=None, profile=None, blockers=[self._blocker(DRAGON_DEMO_BOOK_NOT_FOUND)])
        profile = self._ready_profile(book.book_id)
        blockers = [] if profile else [self._blocker(DRAGON_DEMO_PROFILE_NOT_READY)]
        return self._payload(book=book, profile=profile, blockers=blockers)

    def run(self) -> dict[str, Any]:
        book = self._book()
        blockers: list[dict[str, str]] = []
        if book is None:
            blockers.append(self._blocker(DRAGON_DEMO_BOOK_NOT_FOUND))
            raise self._blocked(blockers)

        profile = self._ready_profile(book.book_id)
        if profile is None:
            blockers.append(self._blocker(DRAGON_DEMO_PROFILE_NOT_READY))
            raise self._blocked(blockers)

        for chapter in DEMO_CHAPTERS:
            self._upsert_chapter(chapter)
            self._upsert_scene(chapter)
            self._apply_profile_to_chapter(book.book_id, profile["profile_id"], chapter["chapter_id"])
            run_result = ChapterRunnerService(self.session).run_full(chapter["chapter_id"])
            if run_result.get("status") != "completed":
                blockers.append(
                    {
                        "code": "DRAGON_CHAPTER_RUN_BLOCKED",
                        "message": "chapter run did not complete",
                        "chapter_id": chapter["chapter_id"],
                    }
                )
                raise self._blocked(blockers)

        chapters = [self._chapter_payload(chapter) for chapter in DEMO_CHAPTERS]
        leakage_check = self._leakage_check(chapters)
        payload = {
            "mode": llm_generation_mode(),
            "book_id": book.book_id,
            "profile_id": profile["profile_id"],
            "ready": leakage_check["passed"],
            "blockers": [] if leakage_check["passed"] else [{"code": "DRAGON_SOURCE_LEAKAGE", "message": "source markers detected"}],
            "chapters": chapters,
            "leakage_check": leakage_check,
        }
        self.session.flush()
        return payload

    def _payload(
        self,
        *,
        book: ReferenceBook | None,
        profile: dict[str, Any] | None,
        blockers: list[dict[str, str]],
    ) -> dict[str, Any]:
        return {
            "mode": llm_generation_mode(),
            "book_id": book.book_id if book else None,
            "book": ReferenceLearningService.serialize_book(book) if book else None,
            "profile_id": profile["profile_id"] if profile else None,
            "profile": profile,
            "ready": not blockers,
            "blockers": blockers,
            "chapters": [self._chapter_payload(chapter) for chapter in DEMO_CHAPTERS],
            "leakage_check": self._leakage_check([self._chapter_payload(chapter) for chapter in DEMO_CHAPTERS]),
        }

    def _book(self) -> ReferenceBook | None:
        book = self.session.get(ReferenceBook, DRAGON_REFERENCE_BOOK_ID)
        if book is not None:
            return book
        return self.session.execute(
            select(ReferenceBook)
            .where(
                (ReferenceBook.title.contains("龙族"))
                | (ReferenceBook.file_name.contains("龙族"))
                | (ReferenceBook.title.contains("Dragon"))
                | (ReferenceBook.file_name.contains("Dragon"))
            )
            .order_by(ReferenceBook.created_at.desc())
        ).scalars().first()

    def _ready_profile(self, book_id: str) -> dict[str, Any] | None:
        detail = ReferenceLearningService(self.session).detail(book_id)
        for profile in detail.get("profiles") or []:
            safety = profile.get("safety_summary") or {}
            coverage = profile.get("coverage") or {}
            if profile.get("status") == "ready" and safety.get("safe") is True and coverage.get("profile_stale") is not True:
                return profile
        return None

    def _apply_profile_to_chapter(self, book_id: str, profile_id: str, chapter_id: str) -> None:
        applied = ReferenceLearningService(self.session).apply_profile(
            book_id,
            profile_id,
            scope="chapter",
            scope_ref_id=chapter_id,
        )
        materializer = ReviewMaterializationService(self.session)
        promoter = PromotionService(self.session)
        for review in applied.get("reviews") or []:
            review_id = review["review_id"]
            materialized = materializer.materialize_review(review_id)
            if materialized.get("released"):
                continue
            try:
                promoter.release_review(review_id)
            except DomainError as exc:
                if exc.code != "RELEASE_PRECONDITION_FAILED":
                    raise

    def _upsert_chapter(self, spec: dict[str, Any]) -> None:
        payload = {
            "chapter_id": spec["chapter_id"],
            "planned_scene_count": 1,
            "chapter_goal": spec["chapter_goal"],
            "main_plot_push": spec["main_plot_push"],
            "emotional_target": spec["emotional_target"],
            "ending_effect": spec["ending_effect"],
            "must_not": "Do not reuse protected source names, settings, declarations, or recognizable plot bridges.",
            "notes": "Three-chapter cultivation demo generated from abstract reference-profile mechanics.",
        }
        chapter = self.session.get(ChapterGoal, spec["chapter_id"])
        if chapter is None:
            chapter = ChapterGoal(**payload)
            self.session.add(chapter)
        else:
            for key, value in payload.items():
                setattr(chapter, key, value)
            chapter.trashed_flag = 0

        state = self.session.get(ChapterState, spec["chapter_id"])
        if state is None:
            self.session.add(
                ChapterState(
                    chapter_id=spec["chapter_id"],
                    current_phase="drafting",
                    mid_aggregate_enabled_effective=0,
                    aggregate_block_reason="none",
                )
            )
        else:
            state.current_phase = "drafting"
            state.aggregate_block_reason = "none"
            state.manual_hold_reason = None
        self.session.flush()

    def _upsert_scene(self, spec: dict[str, Any]) -> None:
        payload = {
            "scene_id": spec["scene_id"],
            "chapter_id": spec["chapter_id"],
            "scene_seq": 1,
            "pov_character_id": None,
            "onstage_chars_json": [],
            "location": spec["location"],
            "scene_goal": spec["scene_goal"],
            "beats_json": spec["beats"],
            "must_include_text": spec["must_include"],
            "forbidden_text": "Do not copy protected source names, settings, declarations, or recognizable plot bridges.",
            "exit_change": spec["ending_effect"],
            "hook": spec["hook"],
            "target_length_band": "short",
            "scene_type": "cultivation_trial",
            "is_chapter_last": 1,
        }
        scene = self.session.get(SceneCard, spec["scene_id"])
        if scene is None:
            scene = SceneCard(**payload)
            self.session.add(scene)
        else:
            for key, value in payload.items():
                setattr(scene, key, value)
            scene.trashed_flag = 0

        state = self.session.get(SceneRunState, spec["scene_id"])
        if state is None:
            self.session.add(SceneRunState(scene_id=spec["scene_id"], scene_status="ready"))
        else:
            state.current_human_review_event_id = None
        self.session.flush()

    def _chapter_payload(self, spec: dict[str, Any]) -> dict[str, Any]:
        state = self.session.get(SceneRunState, spec["scene_id"])
        final_scene = self.session.get(FinalScene, state.current_final_scene_row_id) if state and state.current_final_scene_row_id else None
        bundle = self.session.get(SceneBundle, state.current_bundle_id) if state and state.current_bundle_id else None
        qc_report = self.session.get(QcReport, state.current_qc_report_id) if state and state.current_qc_report_id else None
        return {
            "chapter_id": spec["chapter_id"],
            "scene_id": spec["scene_id"],
            "status": "completed" if final_scene is not None else "pending",
            "final_scene": {
                "row_id": final_scene.row_id,
                "content": final_scene.content,
            }
            if final_scene
            else None,
            "qc_summary": {
                "qc_report_id": qc_report.qc_report_id,
                "qc_type": qc_report.qc_type,
                "pass_flag": bool(qc_report.pass_flag) if qc_report.pass_flag is not None else None,
                "resolution_code": qc_report.resolution_code,
                "next_action": qc_report.next_action,
            }
            if qc_report
            else None,
            "bundle": {
                "bundle_id": bundle.bundle_id,
                "bundle_snapshot_hash": bundle.bundle_snapshot_hash,
                "snapshot": bundle.frozen_snapshot_json,
            }
            if bundle
            else None,
        }

    def _leakage_check(self, chapters: list[dict[str, Any]]) -> dict[str, Any]:
        serialized = json.dumps(chapters, ensure_ascii=False, sort_keys=True)
        hits = [marker for marker in FORBIDDEN_SOURCE_MARKERS if marker in serialized]
        return {
            "passed": not hits,
            "hits": sorted(set(hits)),
        }

    @staticmethod
    def _blocker(code: str) -> dict[str, str]:
        messages = {
            DRAGON_DEMO_BOOK_NOT_FOUND: "the local Dragon reference sample is not available",
            DRAGON_DEMO_PROFILE_NOT_READY: "the Dragon reference profile is missing, stale, or unsafe",
        }
        return {"code": code, "message": messages[code]}

    @staticmethod
    def _blocked(blockers: list[dict[str, str]]) -> DomainError:
        return DomainError(
            "DRAGON_DEMO_BLOCKED",
            "Dragon xianxia demo cannot run until blockers are resolved",
            status_code=409,
            details={"blockers": blockers},
        )
