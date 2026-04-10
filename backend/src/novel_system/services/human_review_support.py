from __future__ import annotations

from typing import Any


RETRYABLE_RECOVERY_PATHS = {
    "/api/v1/review-items/{review_id}/approve",
    "/api/v1/review-items/{review_id}/release",
    "/api/v1/index/verify/{job_id}/retry",
}


def recovery_action_contract(path_template: str | None) -> tuple[list[str], dict[str, str], str]:
    if path_template in RETRYABLE_RECOVERY_PATHS:
        return ["inspect", "retry_request"], {"inspect": "open", "retry_request": "pending"}, "inspect"
    return ["inspect"], {"inspect": "open"}, "inspect"


def recovery_linked_target(path_template: str | None, payload: dict[str, Any] | None) -> dict[str, str | None]:
    payload = payload or {}
    if path_template in {
        "/api/v1/review-items/{review_id}/approve",
        "/api/v1/review-items/{review_id}/release",
    }:
        review_id = payload.get("review_id")
        return {
            "linked_target_type": "review_item" if review_id else None,
            "linked_target_id": review_id,
            "linked_target_ref": f"review_item:{review_id}" if review_id else None,
        }
    if path_template == "/api/v1/index/verify/{job_id}/retry":
        job_id = payload.get("job_id")
        return {
            "linked_target_type": "verify_job" if job_id else None,
            "linked_target_id": job_id,
            "linked_target_ref": f"verify_job:{job_id}" if job_id else None,
        }
    return {
        "linked_target_type": None,
        "linked_target_id": None,
        "linked_target_ref": None,
    }


def structured_target(
    target_type: str | None,
    target_id: str | None,
    target_ref: str | None = None,
) -> dict[str, str] | None:
    if not target_type or not target_id:
        return None
    resolved_target_ref = target_ref or f"{target_type}:{target_id}"
    return {
        "target_type": target_type,
        "target_id": target_id,
        "target_ref": resolved_target_ref,
    }


def structured_target_from_ref(target_ref: str | None) -> dict[str, str] | None:
    if not target_ref or ":" not in target_ref:
        return None
    target_type, target_id = target_ref.split(":", 1)
    return structured_target(target_type, target_id, target_ref)


def structured_target_from_details(details: dict[str, Any] | None, prefix: str) -> dict[str, str] | None:
    details = details or {}
    target = structured_target(
        details.get(f"{prefix}_target_type"),
        details.get(f"{prefix}_target_id"),
        details.get(f"{prefix}_target_ref"),
    )
    if target is not None:
        return target
    return structured_target_from_ref(details.get(f"{prefix}_target_ref"))


def structured_target_from_replay_result(replay_result: dict[str, Any] | None) -> dict[str, str] | None:
    replay_result = replay_result or {}
    review_id = replay_result.get("review_id")
    if isinstance(review_id, str) and review_id:
        return structured_target("review_item", review_id)

    job_id = replay_result.get("job_id")
    if isinstance(job_id, str) and job_id:
        job_type = "reindex_job" if replay_result.get("job_type") == "reindex" or job_id.startswith("reindex_") else "verify_job"
        return structured_target(job_type, job_id)
    return None


def human_review_linked_target(details: dict[str, Any] | None, scene_id: str | None = None) -> dict[str, str] | None:
    target = structured_target_from_details(details, "linked")
    if target is not None:
        return target
    if scene_id:
        return structured_target("scene_card", scene_id)
    return None


def human_review_followup_target(details: dict[str, Any] | None) -> dict[str, str] | None:
    return structured_target_from_details(details, "followup")
