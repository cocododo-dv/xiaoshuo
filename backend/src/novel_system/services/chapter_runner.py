from __future__ import annotations

from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from novel_system.db.models import ChapterRunJob, HumanReviewEvent, SceneCard, SceneRunState, utcnow
from novel_system.services.author_lifecycle import AuthorLifecycleService
from novel_system.services.project_backtracks import ProjectBacktrackService
from novel_system.services.chapter_runtime import ChapterRuntimeService
from novel_system.services.orchestrator import Orchestrator

JOB_TYPE_CHAPTER_FULL = "chapter_run_full"
JOB_STATUS_PENDING = "pending"
JOB_STATUS_RUNNING = "running"
JOB_STATUS_BLOCKED = "blocked"
JOB_STATUS_COMPLETED = "completed"
JOB_STATUS_FAILED = "failed"


class ChapterRunnerService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def run_full(self, chapter_id: str, *, restart: bool = False) -> dict[str, Any]:
        AuthorLifecycleService(self.session).require_active_chapter(chapter_id)
        scene_ids = self._scene_ids(chapter_id)
        job = None if restart else self._resumeable_job(chapter_id)
        if job is None:
            job = self._create_job(chapter_id, scene_ids)
        else:
            self._reconcile_job(job, scene_ids)

        self._mark_running(job)
        orchestrator = Orchestrator(self.session)
        while True:
            next_scene_id = self._next_scene_id(job, scene_ids)
            if next_scene_id is None:
                self._mark_completed(job)
                self.session.flush()
                return self._serialize_job(job)

            gate_error = self._chapter_gate_error(chapter_id, scene_id=next_scene_id)
            if gate_error is not None:
                self._mark_blocked(job, blocked_scene_id=next_scene_id, latest_error=gate_error)
                self.session.flush()
                return self._serialize_job(job)

            self._set_current_scene(job, next_scene_id)

            try:
                result = orchestrator.run_scene(next_scene_id)
            except Exception as exc:  # pragma: no cover - safety net for runtime failures
                self._mark_failed(
                    job,
                    current_scene_id=next_scene_id,
                    error_code="CHAPTER_RUN_FAILED",
                    error_text=str(exc) or "chapter run failed",
                )
                self.session.flush()
                return self._serialize_job(job)

            if self._scene_requires_human_review(result):
                self._mark_blocked(
                    job,
                    blocked_scene_id=next_scene_id,
                    latest_error={
                        "code": "CHAPTER_RUN_HUMAN_REVIEW_REQUIRED",
                        "message": "scene requires human review before chapter run can continue",
                    },
                )
                self.session.flush()
                return self._serialize_job(job)

            scene_incomplete_error = self._scene_incomplete_error(next_scene_id, result)
            if scene_incomplete_error is not None:
                self._mark_blocked(job, blocked_scene_id=next_scene_id, latest_error=scene_incomplete_error)
                self.session.flush()
                return self._serialize_job(job)

            self._mark_scene_completed(job, next_scene_id)
            gate_error = self._chapter_gate_error(chapter_id, scene_id=next_scene_id)
            if gate_error is not None:
                self._mark_blocked(job, blocked_scene_id=next_scene_id, latest_error=gate_error)
                self.session.flush()
                return self._serialize_job(job)

    def run_status(self, chapter_id: str) -> dict[str, Any]:
        AuthorLifecycleService(self.session).require_active_chapter(chapter_id)
        job = self._latest_job(chapter_id)
        if job is None:
            return {
                "job_id": None,
                "chapter_id": chapter_id,
                "job_type": JOB_TYPE_CHAPTER_FULL,
                "status": "idle",
                "scene_ids": self._scene_ids(chapter_id),
                "current_scene_id": None,
                "completed_scene_ids": [],
                "blocked_scene_id": None,
                "latest_error": None,
            }
        self._reconcile_job(job, self._scene_ids(chapter_id))
        self.session.flush()
        return self._serialize_job(job)

    def _scene_ids(self, chapter_id: str) -> list[str]:
        scenes = self.session.execute(
            select(SceneCard)
            .where(SceneCard.chapter_id == chapter_id, SceneCard.trashed_flag == 0)
            .order_by(SceneCard.scene_seq.asc(), SceneCard.scene_id.asc())
        ).scalars().all()
        return [scene.scene_id for scene in scenes]

    def _latest_job(self, chapter_id: str) -> ChapterRunJob | None:
        return self.session.execute(
            select(ChapterRunJob)
            .where(ChapterRunJob.chapter_id == chapter_id, ChapterRunJob.job_type == JOB_TYPE_CHAPTER_FULL)
            .order_by(ChapterRunJob.created_at.desc(), ChapterRunJob.job_id.desc())
        ).scalars().first()

    def _resumeable_job(self, chapter_id: str) -> ChapterRunJob | None:
        return self._latest_job(chapter_id)

    def _create_job(self, chapter_id: str, scene_ids: list[str]) -> ChapterRunJob:
        now = utcnow()
        job = ChapterRunJob(
            job_id=f"chapter_run_{chapter_id}_{uuid4().hex[:10]}",
            chapter_id=chapter_id,
            status=JOB_STATUS_PENDING,
            job_type=JOB_TYPE_CHAPTER_FULL,
            payload_json={
                "scene_ids": scene_ids,
                "completed_scene_ids": [],
                "current_scene_id": None,
                "blocked_scene_id": None,
            },
            result_summary_json={
                "scene_ids": scene_ids,
                "completed_scene_ids": [],
                "current_scene_id": None,
                "blocked_scene_id": None,
                "latest_error": None,
            },
            worker_id="local-process",
            attempt_no=0,
            started_at=now,
        )
        self.session.add(job)
        self.session.flush()
        return job

    def _reconcile_job(self, job: ChapterRunJob, scene_ids: list[str]) -> None:
        payload = self._payload(job)
        finalized_scene_ids = self._finalized_scene_ids(scene_ids)
        completed_set = {
            scene_id
            for scene_id in payload.get("completed_scene_ids", [])
            if scene_id in scene_ids
        }
        completed = [scene_id for scene_id in scene_ids if scene_id in completed_set or scene_id in finalized_scene_ids]
        current_scene_id = payload.get("current_scene_id")
        if current_scene_id not in scene_ids:
            current_scene_id = completed[-1] if completed else None
        blocked_scene_id = payload.get("blocked_scene_id")
        if blocked_scene_id not in scene_ids:
            blocked_scene_id = None
        if blocked_scene_id in completed and self._chapter_gate_error(job.chapter_id, scene_id=blocked_scene_id) is None:
            blocked_scene_id = None
        if blocked_scene_id is not None:
            current_scene_id = blocked_scene_id
        next_scene_id = next((scene_id for scene_id in scene_ids if scene_id not in set(completed)), None)
        payload.update(
            {
                "scene_ids": scene_ids,
                "completed_scene_ids": completed,
                "blocked_scene_id": blocked_scene_id,
                "current_scene_id": current_scene_id,
            }
        )
        job.payload_json = payload
        summary = dict(job.result_summary_json or {})
        latest_error = summary.get("latest_error")
        if blocked_scene_id is None:
            if next_scene_id is None:
                latest_error = None
                job.error_code = None
                job.error_text = None
                job.status = JOB_STATUS_COMPLETED
                job.finished_at = job.finished_at or utcnow()
            elif job.status in {JOB_STATUS_BLOCKED, JOB_STATUS_COMPLETED}:
                latest_error = None
                job.error_code = None
                job.error_text = None
                job.status = JOB_STATUS_PENDING
                job.finished_at = None
        summary["scene_ids"] = scene_ids
        summary["completed_scene_ids"] = completed
        summary["blocked_scene_id"] = blocked_scene_id
        summary["current_scene_id"] = current_scene_id
        summary["latest_error"] = latest_error
        job.result_summary_json = summary

    def _finalized_scene_ids(self, scene_ids: list[str]) -> set[str]:
        if not scene_ids:
            return set()
        states = self.session.execute(
            select(SceneRunState).where(SceneRunState.scene_id.in_(scene_ids))
        ).scalars().all()
        return {
            state.scene_id
            for state in states
            if state.current_final_scene_row_id
        }

    def _mark_running(self, job: ChapterRunJob) -> None:
        now = utcnow()
        job.status = JOB_STATUS_RUNNING
        job.attempt_no = (job.attempt_no or 0) + 1
        job.worker_id = "local-process"
        job.started_at = job.started_at or now
        job.heartbeat_at = now
        job.lease_expires_at = now
        self._update_summary(job, latest_error=None)

    def _set_current_scene(self, job: ChapterRunJob, scene_id: str) -> None:
        payload = self._payload(job)
        payload["current_scene_id"] = scene_id
        payload["blocked_scene_id"] = None
        job.payload_json = payload
        self._update_summary(job, current_scene_id=scene_id, blocked_scene_id=None, latest_error=None)

    def _mark_scene_completed(self, job: ChapterRunJob, scene_id: str) -> None:
        payload = self._payload(job)
        completed_scene_ids = list(payload.get("completed_scene_ids", []))
        if scene_id not in completed_scene_ids:
            completed_scene_ids.append(scene_id)
        payload["completed_scene_ids"] = completed_scene_ids
        payload["current_scene_id"] = scene_id
        payload["blocked_scene_id"] = None
        job.payload_json = payload
        self._update_summary(
            job,
            current_scene_id=scene_id,
            completed_scene_ids=completed_scene_ids,
            blocked_scene_id=None,
            latest_error=None,
        )

    def _mark_blocked(self, job: ChapterRunJob, *, blocked_scene_id: str | None, latest_error: dict[str, str]) -> None:
        job.status = JOB_STATUS_BLOCKED
        job.error_code = latest_error["code"]
        job.error_text = latest_error["message"]
        job.finished_at = None
        payload = self._payload(job)
        payload["blocked_scene_id"] = blocked_scene_id
        if blocked_scene_id is not None:
            payload["current_scene_id"] = blocked_scene_id
        job.payload_json = payload
        self._update_summary(
            job,
            current_scene_id=payload.get("current_scene_id"),
            blocked_scene_id=blocked_scene_id,
            latest_error=latest_error,
        )

    def _mark_completed(self, job: ChapterRunJob) -> None:
        payload = self._payload(job)
        completed_scene_ids = list(payload.get("completed_scene_ids", []))
        job.status = JOB_STATUS_COMPLETED
        job.error_code = None
        job.error_text = None
        job.finished_at = utcnow()
        payload["blocked_scene_id"] = None
        payload["current_scene_id"] = completed_scene_ids[-1] if completed_scene_ids else None
        job.payload_json = payload
        self._update_summary(
            job,
            current_scene_id=payload.get("current_scene_id"),
            completed_scene_ids=completed_scene_ids,
            blocked_scene_id=None,
            latest_error=None,
        )

    def _mark_failed(self, job: ChapterRunJob, *, current_scene_id: str | None, error_code: str, error_text: str) -> None:
        job.status = JOB_STATUS_FAILED
        job.error_code = error_code
        job.error_text = error_text
        job.finished_at = utcnow()
        payload = self._payload(job)
        payload["current_scene_id"] = current_scene_id
        job.payload_json = payload
        self._update_summary(
            job,
            current_scene_id=current_scene_id,
            blocked_scene_id=None,
            latest_error={"code": error_code, "message": error_text},
        )

    def _chapter_gate_error(self, chapter_id: str, *, scene_id: str | None = None) -> dict[str, str] | None:
        human_review_error = self._scene_human_review_error(scene_id)
        if human_review_error is not None:
            return human_review_error
        pending_backtracks = [
            item
            for item in ProjectBacktrackService(self.session).pending_for_chapter(chapter_id)
            if item.scene_id in {None, scene_id}
        ]
        if pending_backtracks:
            first_item = pending_backtracks[0]
            return {
                "code": "CHAPTER_RUN_BACKTRACK_REQUIRED",
                "message": f"chapter run is blocked by pending replanning work: {first_item.scope}",
            }
        chapter_state = ChapterRuntimeService(self.session).chapter_state_payload(chapter_id)
        manual_hold_reason = chapter_state.get("manual_hold_reason")
        if isinstance(manual_hold_reason, str) and manual_hold_reason.strip():
            return {
                "code": "CHAPTER_RUN_MANUAL_HOLD",
                "message": "chapter run is blocked by manual hold",
            }
        if chapter_state.get("chapter_backfill_pending_count", 0):
            return {
                "code": "CHAPTER_RUN_BACKFILL_PENDING",
                "message": "chapter run is blocked by pending staged backfill",
            }
        aggregate_block_reason = chapter_state.get("aggregate_block_reason")
        if aggregate_block_reason and aggregate_block_reason != "none":
            return {
                "code": "CHAPTER_RUN_AGGREGATE_BLOCKED",
                "message": f"chapter run is blocked by aggregate gate: {aggregate_block_reason}",
            }
        return None

    def _scene_human_review_error(self, scene_id: str | None) -> dict[str, str] | None:
        if not scene_id:
            return None
        scene_state = self.session.get(SceneRunState, scene_id)
        if scene_state is None or not scene_state.current_human_review_event_id:
            return None
        event = self.session.get(HumanReviewEvent, scene_state.current_human_review_event_id)
        if event is None or event.status != "resolved":
            return {
                "code": "CHAPTER_RUN_HUMAN_REVIEW_REQUIRED",
                "message": "scene requires human review before chapter run can continue",
            }
        return None

    def _next_scene_id(self, job: ChapterRunJob, scene_ids: list[str]) -> str | None:
        completed = set(self._payload(job).get("completed_scene_ids", []))
        for scene_id in scene_ids:
            if scene_id not in completed:
                return scene_id
        return None

    def _blocked_scene_id(self, job: ChapterRunJob, scene_ids: list[str]) -> str | None:
        payload = self._payload(job)
        blocked_scene_id = payload.get("blocked_scene_id")
        if blocked_scene_id in scene_ids:
            return blocked_scene_id
        current_scene_id = payload.get("current_scene_id")
        if current_scene_id in scene_ids:
            return current_scene_id
        return self._next_scene_id(job, scene_ids)

    @staticmethod
    def _scene_requires_human_review(result: dict[str, Any] | None) -> bool:
        if not isinstance(result, dict):
            return False
        if result.get("scene_status") == "human_review_required":
            return True
        return bool(result.get("current_human_review_event_id"))

    def _scene_incomplete_error(self, scene_id: str, result: dict[str, Any] | None) -> dict[str, str] | None:
        if not isinstance(result, dict):
            return {
                "code": "CHAPTER_RUN_SCENE_INCOMPLETE",
                "message": "scene run did not produce a final scene",
            }
        if result.get("current_final_scene_row_id"):
            return None
        state = self.session.get(SceneRunState, scene_id)
        if state is not None and state.current_final_scene_row_id:
            return None
        return {
            "code": "CHAPTER_RUN_SCENE_INCOMPLETE",
            "message": "scene run did not produce a final scene",
        }

    @staticmethod
    def _payload(job: ChapterRunJob) -> dict[str, Any]:
        return dict(job.payload_json or {})

    def _update_summary(self, job: ChapterRunJob, **updates: Any) -> None:
        summary = {
            "scene_ids": self._payload(job).get("scene_ids", []),
            "completed_scene_ids": self._payload(job).get("completed_scene_ids", []),
            "current_scene_id": self._payload(job).get("current_scene_id"),
            "blocked_scene_id": self._payload(job).get("blocked_scene_id"),
            "latest_error": None,
            **dict(job.result_summary_json or {}),
        }
        summary.update({key: value for key, value in updates.items() if key is not None})
        job.result_summary_json = summary

    def _serialize_job(self, job: ChapterRunJob) -> dict[str, Any]:
        summary = dict(job.result_summary_json or {})
        return {
            "job_id": job.job_id,
            "chapter_id": job.chapter_id,
            "job_type": job.job_type,
            "status": job.status,
            "scene_ids": summary.get("scene_ids") or self._payload(job).get("scene_ids", []),
            "current_scene_id": summary.get("current_scene_id"),
            "completed_scene_ids": summary.get("completed_scene_ids") or [],
            "blocked_scene_id": summary.get("blocked_scene_id"),
            "latest_error": summary.get("latest_error"),
        }
