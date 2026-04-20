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
DRAGON_DEMO_BOOK_NOT_FOUND = "DRAGON_REFERENCE_BOOK_NOT_FOUND"
DRAGON_DEMO_PROFILE_MISSING = "DRAGON_PROFILE_MISSING"
DRAGON_DEMO_PROFILE_STALE = "DRAGON_PROFILE_STALE"
DRAGON_DEMO_PROFILE_UNSAFE = "DRAGON_PROFILE_UNSAFE"
DRAGON_DEMO_REVIEW_PENDING = "DRAGON_REVIEW_PENDING"
DRAGON_DEMO_SOURCE_LEAKAGE = "DRAGON_SOURCE_LEAKAGE"
DRAGON_DEMO_CHAPTER_BLOCKED = "DRAGON_CHAPTER_RUN_BLOCKED"

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

    def status(self, *, book_id: str | None = None, profile_id: str | None = None) -> dict[str, Any]:
        return self._status_payload(book_id=book_id, profile_id=profile_id)

    def run(
        self,
        *,
        book_id: str | None = None,
        profile_id: str | None = None,
        force_rerun: bool = False,
    ) -> dict[str, Any]:
        status_payload = self._status_payload(book_id=book_id, profile_id=profile_id)
        if status_payload["blockers"]:
            raise self._blocked(status_payload["blockers"])

        book = self.session.get(ReferenceBook, status_payload["book_id"])
        profile = status_payload["selected_profile"]
        if book is None:
            raise self._blocked([self._blocker(DRAGON_DEMO_BOOK_NOT_FOUND)])
        if profile is None:
            raise self._blocked([self._blocker(DRAGON_DEMO_PROFILE_MISSING)])

        for chapter in DEMO_CHAPTERS:
            self._upsert_chapter(chapter)
            self._upsert_scene(chapter)
            if force_rerun:
                self._clear_scene_final(chapter["scene_id"])
            self._apply_profile_to_chapter(book.book_id, profile["profile_id"], chapter["chapter_id"])
            run_result = ChapterRunnerService(self.session).run_full(chapter["chapter_id"])
            if run_result.get("status") != "completed":
                raise self._blocked(
                    [
                        self._blocker(
                            DRAGON_DEMO_CHAPTER_BLOCKED,
                            chapter_id=chapter["chapter_id"],
                        )
                    ]
                )

        chapters = [self._chapter_payload(chapter) for chapter in DEMO_CHAPTERS]
        leakage_check = self._leakage_check(chapters)
        blockers = [] if leakage_check["passed"] else [self._blocker(DRAGON_DEMO_SOURCE_LEAKAGE)]
        detail = ReferenceLearningService(self.session).detail(book.book_id)
        payload = self._payload(
            book=book,
            detail=detail,
            selected_profile=self._select_profile(detail.get("profiles") or [], profile["profile_id"]),
            blockers=blockers,
            chapters=chapters,
            leakage_check=leakage_check,
            has_results=any(chapter.get("final_scene") for chapter in chapters),
        )
        self.session.flush()
        return payload

    def _status_payload(self, *, book_id: str | None, profile_id: str | None) -> dict[str, Any]:
        book = self._book(book_id)
        if book is None:
            return self._payload(
                book=None,
                detail=None,
                selected_profile=None,
                blockers=[self._blocker(DRAGON_DEMO_BOOK_NOT_FOUND)],
            )

        detail = ReferenceLearningService(self.session).detail(book.book_id)
        profiles = detail.get("profiles") or []
        selected_profile = self._select_profile(profiles, profile_id)
        ready_profiles = self._ready_profiles(profiles)
        blockers = self._profile_blockers(detail, profiles, selected_profile, ready_profiles, profile_id)
        return self._payload(
            book=book,
            detail=detail,
            selected_profile=selected_profile if self._profile_ready(selected_profile) else None,
            blockers=blockers,
        )

    def _payload(
        self,
        *,
        book: ReferenceBook | None,
        detail: dict[str, Any] | None,
        selected_profile: dict[str, Any] | None,
        blockers: list[dict[str, Any]],
        chapters: list[dict[str, Any]] | None = None,
        leakage_check: dict[str, Any] | None = None,
        has_results: bool | None = None,
    ) -> dict[str, Any]:
        profiles = detail.get("profiles") if detail else []
        ready_profiles = self._ready_profiles(profiles or [])
        chapter_payloads = chapters or [self._chapter_payload(chapter) for chapter in DEMO_CHAPTERS]
        result_available = any(chapter.get("final_scene") for chapter in chapter_payloads) if has_results is None else has_results
        return {
            "mode": llm_generation_mode(),
            "book_id": book.book_id if book else None,
            "book": ReferenceLearningService.serialize_book(book) if book else None,
            "selected_book": ReferenceLearningService.serialize_book(book) if book else None,
            "candidate_books": self._candidate_books(),
            "profile_id": selected_profile["profile_id"] if selected_profile else None,
            "profile": selected_profile,
            "selected_profile": selected_profile,
            "ready_profiles": ready_profiles,
            "ready": not blockers,
            "blockers": blockers,
            "primary_action": self._primary_action(blockers, has_results=result_available),
            "chapters": chapter_payloads,
            "leakage_check": leakage_check or self._leakage_check(chapter_payloads),
        }

    def _book(self, book_id: str | None = None) -> ReferenceBook | None:
        if book_id:
            return self.session.get(ReferenceBook, book_id.strip())
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

    def _candidate_books(self) -> list[dict[str, Any]]:
        service = ReferenceLearningService(self.session)
        books = self.session.execute(select(ReferenceBook).order_by(ReferenceBook.created_at.desc())).scalars().all()
        return [service.serialize_book_with_summary(book) for book in books]

    def _ready_profiles(self, profiles: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [profile for profile in profiles if self._profile_ready(profile)]

    def _select_profile(self, profiles: list[dict[str, Any]], profile_id: str | None = None) -> dict[str, Any] | None:
        if profile_id:
            return next((profile for profile in profiles if profile.get("profile_id") == profile_id), None)
        ready_profiles = self._ready_profiles(profiles)
        return ready_profiles[0] if ready_profiles else (profiles[0] if profiles else None)

    @staticmethod
    def _profile_ready(profile: dict[str, Any] | None) -> bool:
        if not profile:
            return False
        safety = profile.get("safety_summary") or {}
        coverage = profile.get("coverage") or {}
        return profile.get("status") == "ready" and safety.get("safe") is True and coverage.get("profile_stale") is not True

    def _profile_blockers(
        self,
        detail: dict[str, Any],
        profiles: list[dict[str, Any]],
        selected_profile: dict[str, Any] | None,
        ready_profiles: list[dict[str, Any]],
        requested_profile_id: str | None,
    ) -> list[dict[str, Any]]:
        if selected_profile and self._profile_ready(selected_profile):
            return []

        coverage = detail.get("coverage") or {}
        if int(coverage.get("pending_findings") or 0) > 0:
            return [self._blocker(DRAGON_DEMO_REVIEW_PENDING)]
        if requested_profile_id and selected_profile is None:
            return [self._blocker(DRAGON_DEMO_PROFILE_MISSING, profile_id=requested_profile_id)]
        if any((profile.get("safety_summary") or {}).get("safe") is False for profile in profiles):
            return [self._blocker(DRAGON_DEMO_PROFILE_UNSAFE)]
        if profiles and any(
            profile.get("status") == "stale" or (profile.get("coverage") or {}).get("profile_stale") is True
            for profile in profiles
        ):
            return [self._blocker(DRAGON_DEMO_PROFILE_STALE)]
        if ready_profiles:
            return []
        return [self._blocker(DRAGON_DEMO_PROFILE_MISSING)]

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

    def _clear_scene_final(self, scene_id: str) -> None:
        state = self.session.get(SceneRunState, scene_id)
        if state is None:
            return
        state.current_final_scene_row_id = None
        state.scene_status = "ready"
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

    def _primary_action(self, blockers: list[dict[str, Any]], *, has_results: bool) -> dict[str, Any]:
        if not blockers:
            return {
                "code": "view_results" if has_results else "run_demo",
                "label": "查看三章结果" if has_results else "运行三章修仙 Demo",
                "enabled": True,
                "target_view": "reference",
            }
        code = blockers[0].get("code")
        actions = {
            DRAGON_DEMO_BOOK_NOT_FOUND: ("import_reference_book", "导入或恢复参考样本", "reference"),
            DRAGON_DEMO_PROFILE_MISSING: ("continue_reference_learning", "继续分析参考样本", "reference"),
            DRAGON_DEMO_PROFILE_STALE: ("regenerate_profile", "重新生成安全画像", "reference"),
            DRAGON_DEMO_PROFILE_UNSAFE: ("regenerate_profile", "重新生成安全画像", "reference"),
            DRAGON_DEMO_REVIEW_PENDING: ("review_findings", "审核参考候选卡", "reference"),
            DRAGON_DEMO_SOURCE_LEAKAGE: ("inspect_leakage", "检查泄漏命中", "reference"),
            DRAGON_DEMO_CHAPTER_BLOCKED: ("inspect_chapter_run", "检查章节运行", "workbench"),
        }
        action_code, label, target_view = actions.get(code, ("resolve_blocker", "处理阻塞项", "reference"))
        return {
            "code": action_code,
            "label": label,
            "enabled": False,
            "target_view": target_view,
        }

    @staticmethod
    def _blocker(code: str, **extra: Any) -> dict[str, Any]:
        messages = {
            DRAGON_DEMO_BOOK_NOT_FOUND: "the local Dragon reference sample is not available",
            DRAGON_DEMO_PROFILE_MISSING: "the Dragon reference profile is missing",
            DRAGON_DEMO_PROFILE_STALE: "the Dragon reference profile is stale",
            DRAGON_DEMO_PROFILE_UNSAFE: "the Dragon reference profile is unsafe",
            DRAGON_DEMO_REVIEW_PENDING: "reference learning findings still need review",
            DRAGON_DEMO_SOURCE_LEAKAGE: "source markers detected",
            DRAGON_DEMO_CHAPTER_BLOCKED: "chapter run did not complete",
        }
        user_messages = {
            DRAGON_DEMO_BOOK_NOT_FOUND: "没有找到本机《龙族》参考样本。请先导入 TXT/MD，或选择已有参考书作为 demo 来源。",
            DRAGON_DEMO_PROFILE_MISSING: "参考书还没有安全画像。继续分析并审核候选卡后，才能用于原创生成。",
            DRAGON_DEMO_PROFILE_STALE: "当前画像已过期。请重新生成 ready 且 safe 的安全画像。",
            DRAGON_DEMO_PROFILE_UNSAFE: "画像中仍命中来源标记，系统已阻止进入生成。请重新分析或拒绝相关候选。",
            DRAGON_DEMO_REVIEW_PENDING: "参考书还有候选卡待审核。请先批准抽象技法并拒绝来源复刻风险。",
            DRAGON_DEMO_SOURCE_LEAKAGE: "终稿命中来源风险标记，已阻止完成。请查看命中词并重新生成。",
            DRAGON_DEMO_CHAPTER_BLOCKED: "章节运行没有完成。请打开章节工作台查看阻塞原因。",
        }
        return {
            "code": code,
            "message": messages[code],
            "user_message": user_messages[code],
            **extra,
        }

    @staticmethod
    def _blocked(blockers: list[dict[str, Any]]) -> DomainError:
        return DomainError(
            "DRAGON_DEMO_BLOCKED",
            "Dragon xianxia demo cannot run until blockers are resolved",
            status_code=409,
            details={"blockers": blockers},
        )
