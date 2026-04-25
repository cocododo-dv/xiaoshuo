from __future__ import annotations

import threading
from datetime import datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from novel_system.db.models import ChapterRunJob, QcReport, SceneRunState, utcnow
from novel_system.db.session import SessionLocal
from novel_system.services.author_lifecycle import AuthorLifecycleService
from novel_system.services.errors import DomainError
from novel_system.services.orchestrator import Orchestrator

JOB_TYPE_SCENE_FULL = "scene_run_full"
SCENE_RUN_STAGE_ORDER = [
    "planning_running",
    "bundle_built",
    "neutral_running",
    "hard_qc_running",
    "style_running",
    "soft_qc_running",
    "rewrite_running",
    "acceptance_review_running",
    "near_final",
    "archived",
]


class SceneRunJobService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create_job(self, scene_id: str, *, actor_ref: str = "operator") -> ChapterRunJob:
        scene = AuthorLifecycleService(self.session).require_active_scene(scene_id)
        now = utcnow()
        job = ChapterRunJob(
            job_id=f"scene_run_{scene_id}_{uuid4().hex[:10]}",
            chapter_id=scene.chapter_id,
            status="queued",
            job_type=JOB_TYPE_SCENE_FULL,
            payload_json={
                "scene_id": scene_id,
                "actor_ref": actor_ref,
                "current_step": "queued",
                "stage_order": SCENE_RUN_STAGE_ORDER,
                "lock_wait_ms": 0,
            },
            result_summary_json={
                "scene_id": scene_id,
                "current_step": "queued",
                "latest_qc": None,
                "needs_human_review": False,
            },
            worker_id=None,
            attempt_no=0,
            heartbeat_at=now,
        )
        self.session.add(job)
        self.session.flush()
        return job

    def get_job(self, job_id: str) -> ChapterRunJob:
        job = self.session.get(ChapterRunJob, job_id)
        if job is None or job.job_type != JOB_TYPE_SCENE_FULL:
            raise DomainError("RUN_JOB_NOT_FOUND", "run job not found", status_code=404)
        return job

    def serialize_job(self, job: ChapterRunJob) -> dict[str, Any]:
        payload = dict(job.payload_json or {})
        summary = dict(job.result_summary_json or {})
        scene_id = payload.get("scene_id") or summary.get("scene_id")
        latest_qc = summary.get("latest_qc") or self._latest_qc_summary(str(scene_id or ""))
        return {
            "job_id": job.job_id,
            "chapter_id": job.chapter_id,
            "scene_id": scene_id,
            "job_type": job.job_type,
            "status": job.status,
            "current_step": payload.get("current_step") or summary.get("current_step") or job.status,
            "stage_order": payload.get("stage_order") or SCENE_RUN_STAGE_ORDER,
            "started_at": job.started_at,
            "finished_at": job.finished_at,
            "elapsed_ms": _elapsed_ms(job.started_at or job.created_at, job.finished_at),
            "current_model_call": summary.get("current_model_call"),
            "lock_wait_ms": payload.get("lock_wait_ms", 0),
            "latest_qc": latest_qc,
            "needs_human_review": bool(summary.get("needs_human_review")),
            "error_code": job.error_code,
            "error_text": job.error_text,
            "result_summary": summary,
        }

    def mark_running(self, job: ChapterRunJob, *, current_step: str) -> None:
        now = utcnow()
        job.status = "running"
        job.started_at = job.started_at or now
        job.heartbeat_at = now
        job.worker_id = "scene-job-thread"
        job.attempt_no = (job.attempt_no or 0) + 1
        self._update_payload(job, current_step=current_step)
        self._update_summary(job, current_step=current_step)
        self.session.flush()

    def mark_finished(self, job: ChapterRunJob, *, status: str, current_step: str, result: dict[str, Any]) -> None:
        job.status = status
        job.finished_at = utcnow()
        job.error_code = None
        job.error_text = None
        self._update_payload(job, current_step=current_step)
        self._update_summary(
            job,
            current_step=current_step,
            scene_status=result.get("scene_status"),
            current_final_scene_row_id=result.get("current_final_scene_row_id"),
            current_human_review_event_id=result.get("current_human_review_event_id"),
            needs_human_review=bool(result.get("current_human_review_event_id") or result.get("scene_status") == "human_review_required"),
            latest_qc=self._latest_qc_summary(str((job.payload_json or {}).get("scene_id") or "")),
        )
        self.session.flush()

    def mark_failed(self, job: ChapterRunJob, *, error_code: str, error_text: str) -> None:
        job.status = "failed"
        job.finished_at = utcnow()
        job.error_code = error_code
        job.error_text = error_text
        self._update_payload(job, current_step="failed")
        self._update_summary(job, current_step="failed", latest_error={"code": error_code, "message": error_text})
        self.session.flush()

    def _latest_qc_summary(self, scene_id: str) -> dict[str, Any] | None:
        if not scene_id:
            return None
        report = self.session.execute(
            select(QcReport)
            .where(QcReport.scene_id == scene_id)
            .order_by(QcReport.created_at.desc(), QcReport.qc_report_id.desc())
        ).scalars().first()
        if report is None:
            return None
        return {
            "qc_report_id": report.qc_report_id,
            "qc_type": report.qc_type,
            "pass_flag": None if report.pass_flag is None else bool(report.pass_flag),
            "resolution_code": report.resolution_code,
            "next_action": report.next_action,
            "issues": report.issues_json or [],
        }

    @staticmethod
    def _update_payload(job: ChapterRunJob, **updates: Any) -> None:
        job.payload_json = {**dict(job.payload_json or {}), **updates}

    @staticmethod
    def _update_summary(job: ChapterRunJob, **updates: Any) -> None:
        job.result_summary_json = {**dict(job.result_summary_json or {}), **updates}


def start_scene_run_job_worker(job_id: str) -> None:
    thread = threading.Thread(target=_run_scene_job_worker, args=(job_id,), daemon=True)
    thread.start()


def _run_scene_job_worker(job_id: str) -> None:
    session = SessionLocal()
    try:
        service = SceneRunJobService(session)
        job = service.get_job(job_id)
        scene_id = str((job.payload_json or {}).get("scene_id") or "")
        service.mark_running(job, current_step="neutral_running")
        session.commit()
        result = Orchestrator(session).run_scene(scene_id)
        state = session.get(SceneRunState, scene_id)
        scene_status = result.get("scene_status") if isinstance(result, dict) else state.scene_status if state else ""
        if scene_status == "archived":
            service.mark_finished(job, status="completed", current_step="archived", result=result)
        elif scene_status == "human_review_required":
            service.mark_finished(job, status="blocked", current_step="blocked", result=result)
        elif scene_status == "near_final_revision_required":
            service.mark_finished(job, status="blocked", current_step="acceptance_review_running", result=result if isinstance(result, dict) else {})
        else:
            service.mark_finished(job, status="blocked", current_step="rewrite_running", result=result if isinstance(result, dict) else {})
        session.commit()
    except DomainError as exc:
        session.rollback()
        _mark_worker_failure(job_id, exc.code, exc.message)
    except Exception as exc:  # pragma: no cover - defensive worker boundary
        session.rollback()
        _mark_worker_failure(job_id, "RUN_JOB_FAILED", str(exc) or "run job failed")
    finally:
        session.close()


def _mark_worker_failure(job_id: str, error_code: str, error_text: str) -> None:
    session = SessionLocal()
    try:
        service = SceneRunJobService(session)
        job = service.get_job(job_id)
        service.mark_failed(job, error_code=error_code, error_text=error_text)
        session.commit()
    finally:
        session.close()


def _elapsed_ms(started_at: str | None, finished_at: str | None) -> int:
    if not started_at:
        return 0
    try:
        start = datetime.fromisoformat(started_at)
        end = datetime.fromisoformat(finished_at) if finished_at else datetime.now(start.tzinfo)
        return max(0, int((end - start).total_seconds() * 1000))
    except ValueError:
        return 0
