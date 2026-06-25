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
from novel_system.services.scene_run_preflight import SceneRunPreflightService

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

    def create_job(self, scene_id: str, *, actor_ref: str = "operator", author_note: str | None = None) -> ChapterRunJob:
        scene = AuthorLifecycleService(self.session).require_active_scene(scene_id)
        run_preflight = SceneRunPreflightService(self.session).build(scene, {})
        can_run = bool(run_preflight.get("can_run"))
        current_step = "queued" if can_run else "preflight_blocked"
        status = "queued" if can_run else "blocked"
        first_blocker = _first_preflight_blocker(run_preflight)
        now = utcnow()
        # FE-ALIGN G3：作者改写指令随任务下发（风格生成阶段注入提示词）
        note = str(author_note or "").strip()[:500]
        job = ChapterRunJob(
            job_id=f"scene_run_{scene_id}_{uuid4().hex[:10]}",
            chapter_id=scene.chapter_id,
            status=status,
            job_type=JOB_TYPE_SCENE_FULL,
            payload_json={
                "scene_id": scene_id,
                "actor_ref": actor_ref,
                "current_step": current_step,
                "stage_order": SCENE_RUN_STAGE_ORDER,
                "lock_wait_ms": 0,
                "run_preflight_status": run_preflight.get("overall_status"),
                **({"author_note": note} if note else {}),
            },
            result_summary_json={
                "scene_id": scene_id,
                "current_step": current_step,
                "latest_qc": None,
                "needs_human_review": False,
                "run_preflight": run_preflight,
                "next_action": _preflight_next_action(run_preflight) if not can_run else None,
                # 预检即拦截路径也透出结构化缺失字段（与 worker 路径同形），前端引导同源
                "error_details": {"missing_fields": list((first_blocker or {}).get("missing_fields") or [])} if first_blocker else {},
            },
            worker_id=None,
            attempt_no=0,
            heartbeat_at=now,
            finished_at=now if not can_run else None,
            error_code=first_blocker.get("code") if first_blocker else None,
            error_text=first_blocker.get("detail") or first_blocker.get("technical_hint") if first_blocker else None,
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
        error_details = dict(summary.get("error_details") or {})
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
            # 异步路径透出结构化缺失字段（与同步 run/full 的 error.details.missing_fields 同源），
            # 前端据此给「去补全场景卡(缺 xxx)」精确引导，不再只能拿到 error_code。
            "error_details": error_details,
            "missing_fields": list(error_details.get("missing_fields") or []),
            "author_note": payload.get("author_note") or "",
            "run_preflight": summary.get("run_preflight"),
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

    def mark_failed(self, job: ChapterRunJob, *, error_code: str, error_text: str, details: dict[str, Any] | None = None) -> None:
        job.status = "failed"
        job.finished_at = utcnow()
        job.error_code = error_code
        job.error_text = error_text
        error_details = dict(details or {})
        self._update_payload(job, current_step="failed")
        self._update_summary(
            job,
            current_step="failed",
            latest_error={"code": error_code, "message": error_text, "details": error_details},
            error_details=error_details,
        )
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
        issues = report.issues_json or []
        issue_keys: list[str] = []
        for issue in issues:
            if not isinstance(issue, dict):
                continue
            key = str(issue.get("issue_key") or issue.get("dimension") or issue.get("code") or "").strip()
            if key and key not in issue_keys:
                issue_keys.append(key)
        return {
            "qc_report_id": report.qc_report_id,
            "qc_type": report.qc_type,
            "pass_flag": None if report.pass_flag is None else bool(report.pass_flag),
            "resolution_code": report.resolution_code,
            "next_action": report.next_action,
            "issues": issues,
            "issue_keys": issue_keys,
            "primary_issue_key": issue_keys[0] if issue_keys else None,
        }

    @staticmethod
    def _update_payload(job: ChapterRunJob, **updates: Any) -> None:
        job.payload_json = {**dict(job.payload_json or {}), **updates}

    @staticmethod
    def _update_summary(job: ChapterRunJob, **updates: Any) -> None:
        job.result_summary_json = {**dict(job.result_summary_json or {}), **updates}


def _first_preflight_blocker(run_preflight: dict[str, Any]) -> dict[str, Any]:
    blockers = run_preflight.get("blocking_items") or []
    if blockers:
        return dict(blockers[0] or {})
    conflicts = run_preflight.get("constraint_conflicts") or []
    if conflicts:
        conflict = dict(conflicts[0] or {})
        return {
            "code": "SCENE_CONSTRAINT_CONFLICT",
            "detail": conflict.get("human_readable_reason") or "scene constraint conflict",
            "technical_hint": f"{conflict.get('required_source')} conflicts with {conflict.get('forbidden_source')}",
        }
    dependencies = run_preflight.get("missing_dependencies") or []
    if dependencies:
        dependency = dict(dependencies[0] or {})
        return {
            "code": dependency.get("blocking_code") or "SCENE_DEPENDENCY_MISSING",
            "detail": f"missing dependency: {dependency.get('lineage_key') or dependency.get('dependency_type')}",
            "technical_hint": dependency.get("lineage_key"),
        }
    return {}


def _preflight_next_action(run_preflight: dict[str, Any]) -> str:
    actions = run_preflight.get("create_actions") or []
    if actions:
        labels = [str(action.get("label") or action.get("action") or "").strip() for action in actions[:2]]
        labels = [item for item in labels if item]
        if labels:
            return "Create or release missing knowledge cards: " + "; ".join(labels)
    blocker = _first_preflight_blocker(run_preflight)
    return str(blocker.get("detail") or blocker.get("technical_hint") or "Resolve preflight blockers before running.")


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
        result = Orchestrator(session).run_scene(scene_id, author_note=str((job.payload_json or {}).get("author_note") or "") or None)
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
        _mark_worker_failure(job_id, exc.code, exc.message, details=exc.details)
    except Exception as exc:  # pragma: no cover - defensive worker boundary
        session.rollback()
        _mark_worker_failure(job_id, "RUN_JOB_FAILED", str(exc) or "run job failed")
    finally:
        session.close()


def _mark_worker_failure(job_id: str, error_code: str, error_text: str, details: dict[str, Any] | None = None) -> None:
    session = SessionLocal()
    try:
        service = SceneRunJobService(session)
        job = service.get_job(job_id)
        service.mark_failed(job, error_code=error_code, error_text=error_text, details=details)
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
