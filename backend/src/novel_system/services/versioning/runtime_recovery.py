from __future__ import annotations

from collections.abc import Callable
from typing import Any

from sqlalchemy import select

from novel_system.db.models import ReindexJob, VerifyJob
from novel_system.services.versioning.base import VersioningServiceBase


class RuntimeRecoveryService(VersioningServiceBase):
    def recover_stuck_jobs(
        self,
        *,
        scene_cancellation_recoverer: Callable[..., list[dict[str, Any]]] | None = None,
    ) -> dict[str, Any]:
        recovered_scene_cancellations = (
            scene_cancellation_recoverer(
                self.session,
                worker_id="system/recovery_sweep",
            )
            if scene_cancellation_recoverer is not None
            else []
        )
        running_jobs = [
            *self.session.execute(select(ReindexJob).where(ReindexJob.status == "running")).scalars().all(),
            *self.session.execute(select(VerifyJob).where(VerifyJob.status == "running")).scalars().all(),
        ]
        reclaimed_job_summaries = self._reclaim_expired_jobs(running_jobs)
        failed_job_summaries = self._collect_failed_job_summaries()
        (
            reclaimed_idempotency_key_summaries,
            created_human_review_event_ids,
            created_human_review_event_targets,
        ) = self._recover_stale_idempotency_keys()
        return {
            "reclaimed_jobs": len(reclaimed_job_summaries),
            "reclaimed_job_summaries": reclaimed_job_summaries,
            "failed_jobs": len(failed_job_summaries),
            "failed_job_summaries": failed_job_summaries,
            "reclaimed_idempotency_keys": len(reclaimed_idempotency_key_summaries),
            "failed_idempotency_keys": len(reclaimed_idempotency_key_summaries),
            "reclaimed_idempotency_key_summaries": reclaimed_idempotency_key_summaries,
            "created_human_review_events": len(created_human_review_event_ids),
            "created_human_review_event_ids": created_human_review_event_ids,
            "created_human_review_event_targets": created_human_review_event_targets,
            "recovered_scene_cancellations": len(recovered_scene_cancellations),
            "recovered_scene_cancellation_summaries": recovered_scene_cancellations,
        }
