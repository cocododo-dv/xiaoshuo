from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from novel_system.db.models import HumanReviewEvent, OperationLog, ReviewItem, VerifyJob
from novel_system.services.errors import DomainError
from novel_system.services.human_review_support import (
    recovery_linked_target,
    structured_target,
    structured_target_from_replay_result,
)
from novel_system.services.version_manager import VersionManager


class HumanReviewManager:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.version_manager = VersionManager(session)

    def run_action(self, event_id: str, action: str, *, actor_ref: str = "operator") -> dict:
        event = self.session.get(HumanReviewEvent, event_id)
        if event is None:
            raise DomainError("HUMAN_REVIEW_EVENT_NOT_FOUND", f"event {event_id} not found", status_code=404)
        if action not in (event.allowed_actions_json or []):
            raise DomainError(
                "HUMAN_REVIEW_ACTION_NOT_ALLOWED",
                f"action {action} is not allowed for event {event_id}",
                status_code=409,
            )

        action_at = datetime.now(UTC).isoformat()
        status_before = event.status
        details_json = dict(event.details_json or {})
        linked_target = recovery_linked_target(
            details_json.get("request_path_template"),
            details_json.get("request_payload") or {},
        )
        replay_result = None
        resolution_reason = None
        followup = self._empty_followup()

        if action == "retry_request":
            replay_result = self._retry_recovery_request(event)
            event.status, resolution_reason, followup = self._workflow_after_retry_request(event)
        elif action == "retry_verify":
            replay_result = self._retry_verify_followup(event)
            event.status, resolution_reason, followup = self._workflow_after_verify_followup(event)
        elif action == "release_review":
            replay_result = self._release_review_followup(event)
            event.status, resolution_reason, followup = self._workflow_after_release_followup(replay_result)
        else:
            event.status = (event.result_status_map_json or {}).get(action, event.status)

        action_entry = {
            "action": action,
            "actor_ref": actor_ref,
            "action_at": action_at,
            "status_before": status_before,
            "status_after": event.status,
        }
        for key, value in linked_target.items():
            if value is not None:
                action_entry[key] = value
        if replay_result is not None:
            action_entry["replay_result"] = replay_result
        if resolution_reason is not None:
            action_entry["resolution_reason"] = resolution_reason
        if followup["followup_action"] is not None:
            action_entry["followup_action"] = followup["followup_action"]
            action_entry["followup_target_ref"] = followup["followup_target_ref"]

        linked_target_object = structured_target(
            linked_target.get("linked_target_type"),
            linked_target.get("linked_target_id"),
            linked_target.get("linked_target_ref"),
        )
        followup_target_object = structured_target(
            followup["followup_target_type"],
            followup["followup_target_id"],
            followup["followup_target_ref"],
        )
        replay_target_object = structured_target_from_replay_result(replay_result)
        if linked_target_object is not None:
            action_entry["linked_target"] = linked_target_object
        if followup_target_object is not None:
            action_entry["followup_target"] = followup_target_object
        if replay_target_object is not None:
            action_entry["replay_target"] = replay_target_object

        history = list(details_json.get("action_history") or [])
        history.append(action_entry)
        details_json["last_action"] = action
        details_json["last_action_at"] = action_at
        details_json["last_action_status"] = event.status
        details_json["last_actor_ref"] = actor_ref
        details_json["action_history"] = history
        for key, value in linked_target.items():
            if value is not None:
                details_json[key] = value
        if replay_result is not None:
            details_json["last_replay_result"] = replay_result
        if resolution_reason is not None:
            details_json["resolution_reason"] = resolution_reason
        self._apply_followup_details(details_json, followup)
        self._apply_event_contract(event, followup)
        event.details_json = details_json

        self.session.add(
            OperationLog(
                event_type="human_review_action",
                object_type="human_review_event",
                object_ref=event.event_id,
                payload_json=action_entry,
            )
        )
        return {
            "event_id": event.event_id,
            "action": action,
            "status": event.status,
            "action_at": action_at,
            "actor_ref": actor_ref,
            "audit_entry": action_entry,
            "replay_result": replay_result,
            "replay_target": replay_target_object,
            "linked_target": linked_target_object,
            "linked_target_ref": linked_target.get("linked_target_ref"),
            "resolution_reason": resolution_reason,
            "followup_action": followup["followup_action"],
            "followup_target": followup_target_object,
            "followup_target_ref": followup["followup_target_ref"],
        }

    def _retry_recovery_request(self, event: HumanReviewEvent) -> dict:
        details = dict(event.details_json or {})
        path_template = details.get("request_path_template")
        payload = details.get("request_payload") or {}

        if path_template == "/api/v1/review-items/{review_id}/approve":
            review_id = payload.get("review_id")
            if not review_id:
                raise DomainError("HUMAN_REVIEW_RETRY_INVALID", "missing review_id for approve retry", status_code=409)
            return self.version_manager.materialize_review(review_id)

        if path_template == "/api/v1/review-items/{review_id}/release":
            review_id = payload.get("review_id")
            if not review_id:
                raise DomainError("HUMAN_REVIEW_RETRY_INVALID", "missing review_id for release retry", status_code=409)
            return self.version_manager.release_review(review_id)

        if path_template == "/api/v1/index/verify/{job_id}/retry":
            job_id = payload.get("job_id")
            if not job_id:
                raise DomainError("HUMAN_REVIEW_RETRY_INVALID", "missing job_id for verify retry", status_code=409)
            return self.version_manager.run_verify(job_id)

        raise DomainError(
            "HUMAN_REVIEW_RETRY_UNSUPPORTED",
            f"retry_request is not supported for {path_template}",
            status_code=409,
        )

    def _retry_verify_followup(self, event: HumanReviewEvent) -> dict:
        details = dict(event.details_json or {})
        job_id = details.get("followup_target_id")
        if not job_id:
            raise DomainError("HUMAN_REVIEW_FOLLOWUP_INVALID", "missing verify job follow-up target", status_code=409)
        return self.version_manager.run_verify(job_id)

    def _release_review_followup(self, event: HumanReviewEvent) -> dict:
        details = dict(event.details_json or {})
        review_id = details.get("followup_target_id")
        if not review_id:
            raise DomainError("HUMAN_REVIEW_FOLLOWUP_INVALID", "missing review follow-up target", status_code=409)
        return self.version_manager.release_review(review_id)

    def _workflow_after_retry_request(self, event: HumanReviewEvent) -> tuple[str, str, dict[str, str | None]]:
        details = dict(event.details_json or {})
        path_template = details.get("request_path_template")

        if path_template == "/api/v1/review-items/{review_id}/approve":
            review_id = details.get("request_payload", {}).get("review_id")
            return self._workflow_after_approve(review_id)

        if path_template == "/api/v1/review-items/{review_id}/release":
            return self._workflow_after_release_followup({"released": True})

        if path_template == "/api/v1/index/verify/{job_id}/retry":
            return self._workflow_after_verify_job(details.get("request_payload", {}).get("job_id"))

        return "needs_followup", "retry_request replay finished", self._empty_followup()

    def _workflow_after_verify_followup(self, event: HumanReviewEvent) -> tuple[str, str, dict[str, str | None]]:
        details = dict(event.details_json or {})
        return self._workflow_after_verify_job(details.get("followup_target_id"))

    def _workflow_after_approve(self, review_id: str | None) -> tuple[str, str, dict[str, str | None]]:
        review = self.session.get(ReviewItem, review_id) if review_id else None
        if review is None:
            return "needs_followup", "linked review item is missing", self._empty_followup()
        if review.status != "approved" or review.materialize_status != "succeeded":
            return "needs_followup", "review did not reach approved/materialized state", self._empty_followup()

        verify_job = self.session.execute(
            select(VerifyJob)
            .where(VerifyJob.review_id == review.review_id)
            .order_by(VerifyJob.job_id.asc())
        ).scalars().first()
        if verify_job is None:
            return "needs_followup", "review approved but verify job is missing", self._empty_followup()
        if verify_job.status != "succeeded":
            return (
                "needs_followup",
                "review approved; verify job is ready to run",
                self._followup("retry_verify", "verify_job", verify_job.job_id),
            )
        return self._workflow_after_verify_job(verify_job.job_id)

    def _workflow_after_verify_job(self, job_id: str | None) -> tuple[str, str, dict[str, str | None]]:
        job = self.session.get(VerifyJob, job_id) if job_id else None
        if job is None:
            return "needs_followup", "linked verify job is missing", self._empty_followup()
        if job.status != "succeeded":
            return "needs_followup", f"verify job remains {job.status}", self._followup("retry_verify", "verify_job", job.job_id)

        review = self.session.get(ReviewItem, job.review_id) if job.review_id else None
        if review is not None and review.active_on_approve == 0:
            return (
                "needs_followup",
                "verify succeeded but review still awaits manual release",
                self._followup("release_review", "review_item", review.review_id),
            )
        return "resolved", "verify job succeeded", self._empty_followup()

    @staticmethod
    def _workflow_after_release_followup(replay_result: dict) -> tuple[str, str, dict[str, str | None]]:
        if replay_result.get("released"):
            return "resolved", "review released and active alias promoted", HumanReviewManager._empty_followup()
        return "needs_followup", "review release did not reach a final promoted state", HumanReviewManager._empty_followup()

    @staticmethod
    def _empty_followup() -> dict[str, str | None]:
        return {
            "followup_action": None,
            "followup_target_type": None,
            "followup_target_id": None,
            "followup_target_ref": None,
        }

    @staticmethod
    def _followup(action: str, target_type: str, target_id: str) -> dict[str, str]:
        return {
            "followup_action": action,
            "followup_target_type": target_type,
            "followup_target_id": target_id,
            "followup_target_ref": f"{target_type}:{target_id}",
        }

    @staticmethod
    def _apply_followup_details(details_json: dict, followup: dict[str, str | None]) -> None:
        for key in ("followup_action", "followup_target_type", "followup_target_id", "followup_target_ref"):
            if followup[key] is None:
                details_json.pop(key, None)
            else:
                details_json[key] = followup[key]

    @staticmethod
    def _apply_event_contract(event: HumanReviewEvent, followup: dict[str, str | None]) -> None:
        followup_action = followup["followup_action"]
        if followup_action is None:
            event.allowed_actions_json = ["inspect"]
            event.result_status_map_json = {"inspect": event.status}
            event.default_action = "inspect"
            return

        event.allowed_actions_json = ["inspect", followup_action]
        terminal_status = "resolved" if followup_action == "release_review" else "needs_followup"
        event.result_status_map_json = {
            "inspect": event.status,
            followup_action: terminal_status,
        }
        event.default_action = followup_action
