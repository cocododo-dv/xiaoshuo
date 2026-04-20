from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import Any, Callable

from sqlalchemy.orm import Session

from novel_system.db.models import IdempotencyKey, OperationLog, ReviewItem, SceneRunState, VerifyJob
from novel_system.services.errors import DomainError
from novel_system.services.human_review_support import structured_target
from novel_system.settings import get_settings


def utcnow() -> datetime:
    return datetime.now(UTC)


def canonical_request_hash(method: str, path_template: str, payload: Any) -> str:
    body = json.dumps(payload or {}, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    raw = f"{method.upper()}::{path_template}::{body}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def execute_with_idempotency(
    session: Session,
    *,
    idempotency_key: str | None,
    method: str,
    path_template: str,
    payload: Any,
    action: Callable[[], dict],
    actor_ref: str = "operator",
) -> tuple[dict, str | None]:
    if not idempotency_key:
        raise DomainError("IDEMPOTENCY_KEY_REQUIRED", "missing X-Idempotency-Key", status_code=400)

    request_hash = canonical_request_hash(method, path_template, payload)
    record = session.get(IdempotencyKey, idempotency_key)
    now = utcnow()
    lease_expires_at = (now + timedelta(seconds=get_settings().idempotency_ttl_seconds)).isoformat()
    operator_action_context = _prepare_operator_action_context(session, path_template=path_template, payload=payload)

    if record is None:
        record = IdempotencyKey(
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            status="started",
            worker_id="http",
            attempt_no=1,
            heartbeat_at=now.isoformat(),
            lease_expires_at=lease_expires_at,
        )
        session.add(record)
        session.add(
            OperationLog(
                event_type="idempotency_started",
                object_type="idempotency_key",
                object_ref=idempotency_key,
                payload_json={
                    "request_hash": request_hash,
                    "request_method": method.upper(),
                    "request_path_template": path_template,
                    "request_payload": payload or {},
                    "attempt_no": record.attempt_no,
                    "actor_ref": actor_ref,
                },
            )
        )
        session.flush()
    else:
        if record.request_hash != request_hash:
            raise DomainError(
                "IDEMPOTENCY_KEY_REUSED_WITH_DIFFERENT_PAYLOAD",
                "idempotency key reused with different payload",
                status_code=409,
            )
        if record.status == "succeeded":
            return record.response_json or {}, "replayed"
        if record.status == "started" and record.lease_expires_at and record.lease_expires_at > now.isoformat():
            raise DomainError(
                "IDEMPOTENCY_REQUEST_IN_PROGRESS",
                "request with the same idempotency key is still running",
                status_code=409,
            )
        record.status = "started"
        record.attempt_no += 1
        record.worker_id = "http"
        record.heartbeat_at = now.isoformat()
        record.lease_expires_at = lease_expires_at
        session.add(
            OperationLog(
                event_type="idempotency_started",
                object_type="idempotency_key",
                object_ref=idempotency_key,
                payload_json={
                    "request_hash": request_hash,
                    "request_method": method.upper(),
                    "request_path_template": path_template,
                    "request_payload": payload or {},
                    "attempt_no": record.attempt_no,
                    "actor_ref": actor_ref,
                },
            )
        )
        session.add(
            OperationLog(
                event_type="lease_reclaim",
                object_type="idempotency_key",
                object_ref=idempotency_key,
                payload_json={"attempt_no": record.attempt_no, "actor_ref": actor_ref},
            )
        )

    try:
        result = action()
        if "actor_ref" not in result:
            result = {**result, "actor_ref": actor_ref}
        operator_action_record = _build_operator_action_record(
            session,
            context=operator_action_context,
            method=method,
            path_template=path_template,
            payload=payload,
            result=result,
            actor_ref=actor_ref,
        )
        if operator_action_record is not None:
            session.add(operator_action_record)
        record.status = "succeeded"
        record.response_json = result
        record.heartbeat_at = now.isoformat()
        record.lease_expires_at = lease_expires_at
        session.add(
            OperationLog(
                event_type="idempotency_succeeded",
                object_type="idempotency_key",
                object_ref=idempotency_key,
                payload_json={"request_hash": request_hash, "actor_ref": actor_ref},
            )
        )
        session.commit()
        return result, None
    except DomainError:
        record.status = "failed"
        session.commit()
        raise
    except Exception as exc:
        record.status = "failed"
        session.commit()
        raise DomainError("INTERNAL_ERROR", str(exc), status_code=500) from exc


def _prepare_operator_action_context(session: Session, *, path_template: str, payload: Any) -> dict[str, Any] | None:
    payload = payload or {}

    if path_template == "/api/v1/human-review-events/{event_id}/actions":
        return None

    if path_template == "/api/v1/review-items/{review_id}/approve":
        review_id = payload.get("review_id")
        if not isinstance(review_id, str) or not review_id:
            return None
        review = session.get(ReviewItem, review_id)
        return {
            "object_type": "review_item",
            "object_ref": review_id,
            "action": "approve_review",
            "status_before": review.status if review else None,
            "target_refs": [_target("review_item", review_id)],
        }

    if path_template == "/api/v1/review-items/{review_id}/release":
        review_id = payload.get("review_id")
        if not isinstance(review_id, str) or not review_id:
            return None
        review = session.get(ReviewItem, review_id)
        return {
            "object_type": "review_item",
            "object_ref": review_id,
            "action": "release_review",
            "status_before": review.status if review else None,
            "target_refs": [_target("review_item", review_id)],
        }

    if path_template == "/api/v1/review-items/{review_id}/reject":
        review_id = payload.get("review_id")
        if not isinstance(review_id, str) or not review_id:
            return None
        review = session.get(ReviewItem, review_id)
        return {
            "object_type": "review_item",
            "object_ref": review_id,
            "action": "reject_review",
            "status_before": review.status if review else None,
            "target_refs": [_target("review_item", review_id)],
        }

    if path_template == "/api/v1/index/verify/{job_id}/retry":
        job_id = payload.get("job_id")
        if not isinstance(job_id, str) or not job_id:
            return None
        job = session.get(VerifyJob, job_id)
        targets = [_target("verify_job", job_id)]
        if job and job.review_id:
            targets.append(_target("review_item", job.review_id))
        return {
            "object_type": "verify_job",
            "object_ref": job_id,
            "action": "retry_verify",
            "status_before": job.status if job else None,
            "target_refs": targets,
        }

    if path_template == "/api/v1/scenes/{scene_id}/run/full":
        scene_id = payload.get("scene_id")
        if not isinstance(scene_id, str) or not scene_id:
            return None
        state = session.get(SceneRunState, scene_id)
        return {
            "object_type": "scene_card",
            "object_ref": scene_id,
            "action": "run_scene",
            "status_before": state.scene_status if state else None,
            "target_refs": [_target("scene_card", scene_id)],
        }

    if path_template == "/api/v1/runtime/recovery/sweep":
        return {
            "object_type": "runtime_operation",
            "object_ref": "recovery_sweep",
            "action": "run_recovery_sweep",
            "status_before": None,
            "target_refs": [],
        }

    if path_template == "/api/v1/runtime/promotions/run-due":
        return {
            "object_type": "runtime_operation",
            "object_ref": "run_due_promotions",
            "action": "run_due_promotions",
            "status_before": None,
            "target_refs": [],
        }

    return None


def _build_operator_action_record(
    session: Session,
    *,
    context: dict[str, Any] | None,
    method: str,
    path_template: str,
    payload: Any,
    result: dict[str, Any],
    actor_ref: str,
) -> OperationLog | None:
    if context is None:
        return None

    object_type = context["object_type"]
    object_ref = context["object_ref"]
    action = context["action"]
    status_after, resolution_reason, extra_payload = _resolve_operator_action_outcome(
        session,
        action=action,
        object_ref=object_ref,
        result=result,
    )
    target_refs = _dedupe_targets([*context.get("target_refs", []), *extra_payload.pop("target_refs", [])])
    summary = resolution_reason

    return OperationLog(
        event_type="operator_action",
        object_type=object_type,
        object_ref=object_ref,
        payload_json={
            "actor_ref": actor_ref,
            "action": action,
            "status_before": context.get("status_before"),
            "status_after": status_after,
            "resolution_reason": resolution_reason,
            "summary": summary,
            "request_method": method.upper(),
            "request_path_template": path_template,
            "request_payload": payload or {},
            "target_refs": target_refs,
            **extra_payload,
        },
    )


def _resolve_operator_action_outcome(
    session: Session,
    *,
    action: str,
    object_ref: str,
    result: dict[str, Any],
) -> tuple[str | None, str, dict[str, Any]]:
    if action == "approve_review":
        job_ids = result.get("job_ids") or []
        targets = []
        for job_id in job_ids:
            if not isinstance(job_id, str):
                continue
            if job_id.startswith("reindex_"):
                targets.append(_target("reindex_job", job_id))
            elif job_id.startswith("verify_"):
                targets.append(_target("verify_job", job_id))
        return (
            result.get("materialize_status"),
            "review approved and candidate materialized",
            {
                "review_id": object_ref,
                "approved_item_row_id": result.get("approved_item_row_id"),
                "materialize_status": result.get("materialize_status"),
                "target_refs": targets,
            },
        )

    if action == "release_review":
        status_after = "released" if result.get("released") else None
        return (
            status_after,
            "review released and active alias promoted",
            {
                "review_id": object_ref,
                "released": result.get("released"),
            },
        )

    if action == "reject_review":
        return (
            result.get("status"),
            "review rejected by operator",
            {
                "review_id": object_ref,
                "reason": result.get("reason"),
            },
        )

    if action == "retry_verify":
        job = session.get(VerifyJob, object_ref)
        return (
            result.get("status") or (job.status if job else None),
            "verify succeeded for candidate alias",
            {
                "job_id": object_ref,
                "job_type": "verify",
                "review_id": job.review_id if job else None,
                "alias_scope": result.get("alias_scope"),
            },
        )

    if action == "run_scene":
        return (
            result.get("scene_status"),
            "scene run completed and final scene archived",
            {
                "scene_id": object_ref,
                "current_bundle_id": result.get("current_bundle_id"),
                "current_bundle_hash": result.get("current_bundle_hash"),
                "current_final_scene_row_id": result.get("current_final_scene_row_id"),
            },
        )

    if action == "run_recovery_sweep":
        return (
            "completed",
            "recovery sweep completed",
            {
                "reclaimed_jobs": result.get("reclaimed_jobs"),
                "reclaimed_job_summaries": result.get("reclaimed_job_summaries"),
                "failed_jobs": result.get("failed_jobs"),
                "failed_job_summaries": result.get("failed_job_summaries"),
                "reclaimed_idempotency_keys": result.get("reclaimed_idempotency_keys"),
                "failed_idempotency_keys": result.get("failed_idempotency_keys"),
                "reclaimed_idempotency_key_summaries": result.get("reclaimed_idempotency_key_summaries"),
                "created_human_review_events": result.get("created_human_review_events"),
                "created_human_review_event_ids": result.get("created_human_review_event_ids"),
                "created_human_review_event_targets": result.get("created_human_review_event_targets"),
                "target_refs": _dedupe_targets(
                    [
                        *_result_targets(result.get("reclaimed_job_summaries")),
                        *_result_targets(result.get("failed_job_summaries")),
                        *_result_targets(result.get("created_human_review_event_targets")),
                    ]
                ),
            },
        )

    if action == "run_due_promotions":
        return (
            "completed",
            "due promotions completed",
            {
                "promoted": result.get("promoted"),
                "promoted_review_ids": result.get("promoted_review_ids"),
                "promoted_review_targets": result.get("promoted_review_targets"),
                "promoted_row_ids": result.get("promoted_row_ids"),
                "promoted_alias_scopes": result.get("promoted_alias_scopes"),
                "target_refs": _dedupe_targets(_result_targets(result.get("promoted_review_targets"))),
            },
        )

    return (None, action, {})


def _target(target_type: str, target_id: str) -> dict[str, str]:
    target = structured_target(target_type, target_id)
    assert target is not None
    return target


def _dedupe_targets(targets: list[dict[str, str] | None]) -> list[dict[str, str]]:
    deduped: list[dict[str, str]] = []
    seen_refs: set[str] = set()
    for target in targets:
        if target is None:
            continue
        target_ref = target["target_ref"]
        if target_ref in seen_refs:
            continue
        seen_refs.add(target_ref)
        deduped.append(target)
    return deduped


def _result_targets(items: Any) -> list[dict[str, str]]:
    if not isinstance(items, list):
        return []
    targets: list[dict[str, str]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        target = item.get("target")
        if not isinstance(target, dict):
            continue
        target_type = target.get("target_type")
        target_id = target.get("target_id")
        target_ref = target.get("target_ref")
        structured = structured_target(target_type, target_id, target_ref)
        if structured is not None:
            targets.append(structured)
    return targets
