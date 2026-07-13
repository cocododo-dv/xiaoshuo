from __future__ import annotations

import inspect
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from novel_system.db.models import ChapterRunJob, HumanReviewEvent, SceneCard, SceneRunState, utcnow
from novel_system.services.author_lifecycle import AuthorLifecycleService
from novel_system.services.author_actions import author_action
from novel_system.services.project_backtracks import ProjectBacktrackService
from novel_system.services.chapter_runtime import ChapterRuntimeService
from novel_system.services.orchestrator import Orchestrator
from novel_system.services.errors import DomainError
from novel_system.services.idempotency import owner_lease_ttl_seconds
from novel_system.services.scene_run_checkpoint import chapter_scene_execution_id

JOB_TYPE_CHAPTER_FULL = "chapter_run_full"
JOB_STATUS_PENDING = "pending"
JOB_STATUS_RUNNING = "running"
JOB_STATUS_BLOCKED = "blocked"
JOB_STATUS_COMPLETED = "completed"
JOB_STATUS_FAILED = "failed"


@dataclass
class ChapterRunLease:
    job_id: str
    worker_id: str
    attempt_no: int
    lease_expires_at: str
    _service: "ChapterRunnerService" = field(repr=False, compare=False)

    def renew(self, *, lease_seconds: int) -> str:
        self.lease_expires_at = self._service._renew_lease(self, lease_seconds=lease_seconds)
        return self.lease_expires_at


class ChapterRunnerService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self._active_owner: ChapterRunLease | None = None

    def run_full(self, chapter_id: str, *, restart: bool = False, request_lease=None) -> dict[str, Any]:
        AuthorLifecycleService(self.session).require_active_chapter(chapter_id)
        scene_ids = self._scene_ids(chapter_id)
        job = None if restart else self._resumeable_job(chapter_id)
        if job is None:
            job = self._create_job(chapter_id, scene_ids)
        else:
            self._reconcile_job(job, scene_ids)
            self._transition_explicit_failed_retry(job)
            if job.status in {JOB_STATUS_BLOCKED, JOB_STATUS_COMPLETED}:
                self.session.flush()
                return self._serialize_job(job)
            self.session.flush()

        owner = self._claim_running(
            job,
            worker_id=f"chapter-run:{uuid4().hex}",
            lease_seconds=owner_lease_ttl_seconds(),
        )
        self._active_owner = owner
        self.session.commit()

        def _renew_all(*, lease_seconds: int) -> None:
            owner.renew(lease_seconds=lease_seconds)
            if request_lease is not None:
                request_lease.renew(lease_seconds=lease_seconds)

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
                call_parameters = inspect.signature(orchestrator.run_scene).parameters
                if "execution_id" in call_parameters:
                    call_kwargs = {
                        "execution_id": chapter_scene_execution_id(job.job_id, next_scene_id),
                        "lease_renewer": _renew_all,
                    }
                    if "run_job_id" in call_parameters or any(
                        parameter.kind == inspect.Parameter.VAR_KEYWORD
                        for parameter in call_parameters.values()
                    ):
                        call_kwargs["run_job_id"] = job.job_id
                    result = orchestrator.run_scene(next_scene_id, **call_kwargs)
                else:  # compatibility for focused test doubles
                    result = orchestrator.run_scene(next_scene_id)
            except Exception as exc:  # pragma: no cover - safety net for runtime failures
                self._release_scene_job_ownership(next_scene_id, job.job_id)
                self._mark_failed(
                    job,
                    current_scene_id=next_scene_id,
                    error_code="CHAPTER_RUN_FAILED",
                    error_text=str(exc) or "chapter run failed",
                )
                self.session.flush()
                return self._serialize_job(job)
            self._release_scene_job_ownership(next_scene_id, job.job_id)

            if self._scene_requires_human_review(result):
                self._mark_blocked(
                    job,
                    blocked_scene_id=next_scene_id,
                    latest_error=self._human_review_error(next_scene_id, result),
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
            scene_ids = self._scene_ids(chapter_id)
            return {
                "job_id": None,
                "chapter_id": chapter_id,
                "job_type": JOB_TYPE_CHAPTER_FULL,
                "status": "idle",
                "scene_ids": scene_ids,
                "current_scene_id": None,
                "completed_scene_ids": [],
                "blocked_scene_id": None,
                "latest_error": None,
                "scene_count": len(scene_ids),
                "completed_count": 0,
                "progress_pct": 0,
                "started_at": None,
                "finished_at": None,
            }
        self._reconcile_job(job, self._scene_ids(chapter_id))
        self.session.flush()
        return self._serialize_job(job)

    def prepare_full_run(self, chapter_id: str, *, offline_demo: bool = False) -> tuple[dict[str, Any], bool]:
        AuthorLifecycleService(self.session).require_active_chapter(chapter_id)
        scene_ids = self._scene_ids(chapter_id)
        job = self._resumeable_job(chapter_id)
        should_start_worker = False
        if job is None:
            job = self._create_job(chapter_id, scene_ids)
            should_start_worker = True
        else:
            previous_status = job.status
            self._reconcile_job(job, scene_ids)
            self._transition_explicit_failed_retry(job)
            should_start_worker = job.status == JOB_STATUS_PENDING and previous_status != JOB_STATUS_RUNNING
            if job.status == JOB_STATUS_BLOCKED:
                blocked_scene_id = self._blocked_scene_id(job, scene_ids)
                if self._chapter_gate_error(chapter_id, scene_id=blocked_scene_id) is None:
                    payload = self._payload(job)
                    payload["blocked_scene_id"] = None
                    job.payload_json = payload
                    job.status = JOB_STATUS_PENDING
                    job.error_code = None
                    job.error_text = None
                    job.finished_at = None
                    self._update_summary(job, blocked_scene_id=None, latest_error=None)
                    should_start_worker = True
        if offline_demo:
            payload = self._payload(job)
            payload["offline_demo"] = True
            payload["source"] = "fallback"
            job.payload_json = payload
            self._update_summary(job, offline_demo=True, source="fallback")
        self.session.flush()
        return self._serialize_job(job), should_start_worker

    def _transition_explicit_failed_retry(self, job: ChapterRunJob) -> None:
        if job.status != JOB_STATUS_FAILED:
            return
        job.status = JOB_STATUS_PENDING
        job.finished_at = None
        job.error_code = None
        job.error_text = None
        self._update_summary(job, latest_error=None)
        self.session.flush()

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
        if (
            blocked_scene_id is not None
            and self._chapter_gate_error(job.chapter_id, scene_id=blocked_scene_id) is None
        ):
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

    def _claim_running(
        self,
        job: ChapterRunJob,
        *,
        worker_id: str,
        lease_seconds: int,
    ) -> ChapterRunLease:
        self.session.refresh(job)
        now = datetime.now(UTC)
        now_iso = now.isoformat()
        expires = (now + timedelta(seconds=max(1, lease_seconds))).isoformat()
        running_with_expired_lease = (
            job.status == JOB_STATUS_RUNNING
            and job.lease_expires_at is not None
            and job.lease_expires_at <= now_iso
        )
        if job.status == JOB_STATUS_RUNNING and not running_with_expired_lease:
            raise DomainError(
                "RUN_JOB_IN_PROGRESS",
                "chapter run is already owned by an active worker",
                status_code=409,
                details={"job_id": job.job_id, "worker_id": job.worker_id},
            )
        if job.status != JOB_STATUS_PENDING and not running_with_expired_lease:
            raise DomainError(
                "RUN_JOB_NOT_CLAIMABLE",
                "chapter run status cannot be claimed by a worker",
                status_code=409,
                details={"job_id": job.job_id, "status": job.status},
            )
        old_status = job.status
        old_worker = job.worker_id
        old_attempt = int(job.attempt_no or 0)
        old_expiry = job.lease_expires_at
        conditions = [
            ChapterRunJob.job_id == job.job_id,
            ChapterRunJob.job_type == JOB_TYPE_CHAPTER_FULL,
            ChapterRunJob.status == old_status,
            ChapterRunJob.attempt_no == old_attempt,
            ChapterRunJob.worker_id.is_(None) if old_worker is None else ChapterRunJob.worker_id == old_worker,
            ChapterRunJob.lease_expires_at.is_(None) if old_expiry is None else ChapterRunJob.lease_expires_at == old_expiry,
        ]
        claimed = self.session.execute(
            update(ChapterRunJob)
            .where(*conditions)
            .values(
                status=JOB_STATUS_RUNNING,
                worker_id=worker_id,
                attempt_no=old_attempt + 1,
                started_at=job.started_at or now_iso,
                heartbeat_at=now_iso,
                lease_expires_at=expires,
            )
            .execution_options(synchronize_session=False)
        )
        if claimed.rowcount != 1:
            self.session.rollback()
            raise DomainError("RUN_JOB_IN_PROGRESS", "another worker won the chapter run claim", status_code=409)
        self.session.flush()
        self.session.refresh(job)
        self._update_summary(job, latest_error=None)
        self.session.flush()
        return ChapterRunLease(
            job_id=job.job_id,
            worker_id=worker_id,
            attempt_no=old_attempt + 1,
            lease_expires_at=expires,
            _service=self,
        )

    def _renew_lease(self, owner: ChapterRunLease, *, lease_seconds: int) -> str:
        now = datetime.now(UTC)
        expires = (now + timedelta(seconds=max(1, lease_seconds))).isoformat()
        renewed = self.session.execute(
            update(ChapterRunJob)
            .where(
                ChapterRunJob.job_id == owner.job_id,
                ChapterRunJob.job_type == JOB_TYPE_CHAPTER_FULL,
                ChapterRunJob.status == JOB_STATUS_RUNNING,
                ChapterRunJob.worker_id == owner.worker_id,
                ChapterRunJob.attempt_no == owner.attempt_no,
            )
            .values(heartbeat_at=now.isoformat(), lease_expires_at=expires)
            .execution_options(synchronize_session=False)
        )
        if renewed.rowcount != 1:
            self.session.rollback()
            raise DomainError("RUN_OWNER_LEASE_LOST", "chapter run owner lease was lost", status_code=409)
        self.session.flush()
        return expires

    def _fence_active_owner(self, job: ChapterRunJob) -> None:
        owner = self._active_owner
        if owner is None:
            return
        self.session.flush()
        fenced = self.session.execute(
            update(ChapterRunJob)
            .where(
                ChapterRunJob.job_id == owner.job_id,
                ChapterRunJob.status == JOB_STATUS_RUNNING,
                ChapterRunJob.worker_id == owner.worker_id,
                ChapterRunJob.attempt_no == owner.attempt_no,
            )
            .values(heartbeat_at=utcnow())
            .execution_options(synchronize_session=False)
        )
        if fenced.rowcount != 1:
            self.session.rollback()
            raise DomainError("RUN_OWNER_LEASE_LOST", "chapter run owner was replaced", status_code=409)
        self.session.flush()
        self.session.refresh(job)

    def _set_current_scene(self, job: ChapterRunJob, scene_id: str) -> None:
        self._fence_active_owner(job)
        payload = self._payload(job)
        payload["current_scene_id"] = scene_id
        payload["blocked_scene_id"] = None
        job.payload_json = payload
        self._update_summary(job, current_scene_id=scene_id, blocked_scene_id=None, latest_error=None)
        state = self.session.get(SceneRunState, scene_id)
        if state is None:
            raise DomainError("SCENE_NOT_FOUND", "scene run state not found", status_code=404)
        if state.active_run_job_id not in {None, job.job_id}:
            raise DomainError(
                "RUN_JOB_IN_PROGRESS",
                "scene is owned by another active run job",
                status_code=409,
            )
        state.active_run_job_id = job.job_id

    def _release_scene_job_ownership(self, scene_id: str, job_id: str) -> None:
        self.session.execute(
            update(SceneRunState)
            .where(
                SceneRunState.scene_id == scene_id,
                SceneRunState.active_run_job_id == job_id,
            )
            .values(active_run_job_id=None)
            .execution_options(synchronize_session=False)
        )
        self.session.flush()

    def _mark_scene_completed(self, job: ChapterRunJob, scene_id: str) -> None:
        self._fence_active_owner(job)
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

    def _mark_blocked(self, job: ChapterRunJob, *, blocked_scene_id: str | None, latest_error: dict[str, Any]) -> None:
        self._fence_active_owner(job)
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
        self._fence_active_owner(job)
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
        self._fence_active_owner(job)
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

    def _chapter_gate_error(self, chapter_id: str, *, scene_id: str | None = None) -> dict[str, Any] | None:
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
                "author_action": author_action(
                    "章节需要先处理返工",
                    "当前章节还有待处理返工项。处理完这些结构问题后，章节起草会继续。",
                    target_view="review",
                    target_ref=f"backtrack_item:{first_item.item_id}",
                    primary_button_label="去待处理建议",
                    evidence_summary=[f"章节：{chapter_id}", f"范围：{first_item.scope}"],
                ),
            }
        chapter_state = ChapterRuntimeService(self.session).chapter_state_payload(chapter_id)
        manual_hold_reason = chapter_state.get("manual_hold_reason")
        if isinstance(manual_hold_reason, str) and manual_hold_reason.strip():
            return {
                "code": "CHAPTER_RUN_MANUAL_HOLD",
                "message": "chapter run is blocked by manual hold",
                "author_action": author_action(
                    "章节被手动暂停",
                    "当前章节处于人工暂停状态，请先解除暂停或处理暂停原因。",
                    target_view="workbench",
                    target_ref=f"chapter:{chapter_id}",
                    primary_button_label="去场景工作台",
                    evidence_summary=[f"章节：{chapter_id}", f"原因：{manual_hold_reason.strip()}"],
                ),
            }
        if chapter_state.get("chapter_backfill_pending_count", 0):
            return {
                "code": "CHAPTER_RUN_BACKFILL_PENDING",
                "message": "chapter run is blocked by pending staged backfill",
                "author_action": author_action(
                    "章节有待回填内容",
                    "当前章节还有标记内容等待回填，先处理这些占位，再继续章节起草。",
                    target_view="workbench",
                    target_ref=f"chapter:{chapter_id}",
                    primary_button_label="去场景工作台",
                    evidence_summary=[f"章节：{chapter_id}", "状态：待回填"],
                ),
            }
        aggregate_block_reason = chapter_state.get("aggregate_block_reason")
        if aggregate_block_reason and aggregate_block_reason != "none":
            return {
                "code": "CHAPTER_RUN_AGGREGATE_BLOCKED",
                "message": f"chapter run is blocked by aggregate gate: {aggregate_block_reason}",
                "author_action": author_action(
                    "章节汇总暂时被阻塞",
                    "章节汇总门还没有放行，请先检查当前章节的场景完成度和回填状态。",
                    target_view="workbench",
                    target_ref=f"chapter:{chapter_id}",
                    primary_button_label="去场景工作台",
                    evidence_summary=[f"章节：{chapter_id}", f"阻塞：{aggregate_block_reason}"],
                ),
            }
        return None

    def _scene_human_review_error(self, scene_id: str | None) -> dict[str, Any] | None:
        if not scene_id:
            return None
        scene_state = self.session.get(SceneRunState, scene_id)
        if scene_state is None or not scene_state.current_human_review_event_id:
            return None
        event = self.session.get(HumanReviewEvent, scene_state.current_human_review_event_id)
        if event is None or event.status != "resolved":
            return self._human_review_error(scene_id, {"current_human_review_event_id": scene_state.current_human_review_event_id})
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

    def _human_review_error(self, scene_id: str, result: dict[str, Any] | None) -> dict[str, Any]:
        event_id = str((result or {}).get("current_human_review_event_id") or "").strip()
        if not event_id:
            state = self.session.get(SceneRunState, scene_id)
            event_id = str(state.current_human_review_event_id or "").strip() if state is not None else ""
        target_ref = f"human_review_event:{event_id}" if event_id else f"scene_card:{scene_id}"
        evidence = [f"场景：{scene_id}"]
        if event_id:
            evidence.append(f"审核：{event_id}")
        return {
            "code": "CHAPTER_RUN_HUMAN_REVIEW_REQUIRED",
            "message": "scene requires human review before chapter run can continue",
            "author_action": author_action(
                "场景需要人工审核",
                "当前场景有一条待处理审核，处理完后章节起草会从这里继续。",
                target_view="review",
                target_ref=target_ref,
                primary_button_label="去待处理建议",
                evidence_summary=evidence,
            ),
        }

    def _scene_incomplete_error(self, scene_id: str, result: dict[str, Any] | None) -> dict[str, Any] | None:
        if not isinstance(result, dict):
            return self._generic_scene_incomplete_error(scene_id)
        if result.get("current_final_scene_row_id"):
            return None
        state = self.session.get(SceneRunState, scene_id)
        if state is not None and state.current_final_scene_row_id:
            return None
        error_code = str(result.get("error_code") or result.get("code") or "").strip()
        scene_status = str(result.get("scene_status") or (state.scene_status if state is not None else "") or "").strip()
        if error_code == "LLM_ROUTE_NOT_CONFIGURED":
            return {
                "code": "LLM_ROUTE_NOT_CONFIGURED",
                "message": "model route is not configured for scene generation",
                "author_action": author_action(
                    "需要配置模型路由",
                    "当前场景起草找不到可用的模型路由。请先到系统配置完成 provider、模型和路由设置。",
                    target_view="config",
                    target_ref="system_config:llm",
                    primary_button_label="去系统配置",
                    evidence_summary=[f"场景：{scene_id}", "错误：LLM_ROUTE_NOT_CONFIGURED"],
                ),
            }
        if error_code == "CONTINUITY_BUDGET_EXCEEDED":
            return {
                "code": "CONTINUITY_BUDGET_EXCEEDED",
                "message": "continuity context budget was exceeded",
                "author_action": author_action(
                    "上下文太重，需要拆分",
                    "这一场承载的信息过多，建议拆分场景或降低连续性上下文后再跑。",
                    target_view="snowflake-workbench",
                    target_ref=f"scene_card:{scene_id}",
                    primary_button_label="拆分场景",
                    evidence_summary=[f"场景：{scene_id}", "错误：CONTINUITY_BUDGET_EXCEEDED"],
                ),
            }
        if scene_status in {"hard_qc_partial_rewrite_required", "hard_qc_full_rewrite_required", "near_final_revision_required"}:
            return {
                "code": "CHAPTER_RUN_SCENE_NEEDS_REWRITE",
                "message": "当前场景停在硬质检返修，还没有形成可审阅终稿。",
                "author_action": author_action(
                    "场景需要补修",
                    "这一场没有形成可审阅终稿，请先回到场景工作台处理返修，再继续章节起草。",
                    target_view="workbench",
                    target_ref=f"scene_card:{scene_id}",
                    primary_button_label="去场景工作台",
                    evidence_summary=[f"场景：{scene_id}", f"状态：{scene_status}"],
                ),
            }
        return self._generic_scene_incomplete_error(scene_id)

    @staticmethod
    def _generic_scene_incomplete_error(scene_id: str) -> dict[str, Any]:
        return {
            "code": "CHAPTER_RUN_SCENE_INCOMPLETE",
            "message": "scene run did not produce a final scene",
            "author_action": author_action(
                "场景还没有可审阅正文",
                "当前场景没有生成可审阅终稿。请先回到场景工作台检查缺字段、返修或运行失败原因。",
                target_view="workbench",
                target_ref=f"scene_card:{scene_id}",
                primary_button_label="去场景工作台",
                evidence_summary=[f"场景：{scene_id}"],
            ),
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
        scene_ids = summary.get("scene_ids") or self._payload(job).get("scene_ids", [])
        completed_scene_ids = summary.get("completed_scene_ids") or []
        scene_count = len(scene_ids)
        completed_count = len(completed_scene_ids)
        progress_pct = 100 if scene_count == 0 and job.status == JOB_STATUS_COMPLETED else 0
        if scene_count:
            progress_pct = min(100, round((completed_count / scene_count) * 100))
        return {
            "job_id": job.job_id,
            "chapter_id": job.chapter_id,
            "job_type": job.job_type,
            "status": job.status,
            "scene_ids": scene_ids,
            "current_scene_id": summary.get("current_scene_id"),
            "completed_scene_ids": completed_scene_ids,
            "blocked_scene_id": summary.get("blocked_scene_id"),
            "latest_error": summary.get("latest_error"),
            "scene_count": scene_count,
            "completed_count": completed_count,
            "progress_pct": progress_pct,
            "started_at": job.started_at,
            "finished_at": job.finished_at,
            "offline_demo": bool(summary.get("offline_demo") or self._payload(job).get("offline_demo")),
            "source": summary.get("source") or self._payload(job).get("source") or "llm",
        }
