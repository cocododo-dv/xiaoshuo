from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy import or_
from sqlalchemy import select
from sqlalchemy.orm import Session

from novel_system.api.deps import get_session
from novel_system.api.response import ok
from novel_system.db.models import HumanReviewEvent, OperationLog, ReconcileFault, ReindexJob, VectorAliasRegistry, VerifyJob
from novel_system.services.human_review_support import (
    human_review_followup_target,
    human_review_linked_target,
    structured_target,
    structured_target_from_ref,
    structured_target_from_replay_result,
)
from novel_system.services.idempotency import execute_with_idempotency
from novel_system.services.version_manager import VersionManager

router = APIRouter(tags=["indexing"])


@router.get("/api/v1/index/alias-scopes")
def list_alias_scopes(request: Request, session: Session = Depends(get_session)):
    items = session.execute(select(VectorAliasRegistry).order_by(VectorAliasRegistry.alias_scope.asc())).scalars().all()
    return ok({"items": [_serialize_alias(item, session=session) for item in items]}, req_id=getattr(request.state, "request_id", None))


@router.get("/api/v1/index/alias-scopes/{alias_scope:path}")
def alias_scope_detail(alias_scope: str, request: Request, session: Session = Depends(get_session)):
    item = session.get(VectorAliasRegistry, alias_scope)
    return ok(_serialize_alias(item, session=session), req_id=getattr(request.state, "request_id", None))


@router.get("/api/v1/index/jobs")
def list_jobs(request: Request, session: Session = Depends(get_session)):
    reindex_jobs = session.execute(select(ReindexJob)).scalars().all()
    verify_jobs = session.execute(select(VerifyJob)).scalars().all()
    items = [_serialize_reindex(job) for job in reindex_jobs] + [_serialize_verify(job) for job in verify_jobs]
    items.sort(key=lambda item: item["job_id"])
    return ok({"items": items}, req_id=getattr(request.state, "request_id", None))


@router.get("/api/v1/index/runtime-ledger")
def runtime_ledger(request: Request, session: Session = Depends(get_session)):
    timeline = _serialize_recovery_timeline(session)
    latest_receipt = next((item for item in timeline if item["last_action_at"]), None)
    system_runtime_timeline = _serialize_system_runtime_timeline(session)
    operator_action_timeline = _serialize_operator_action_timeline(session)
    payload = {
        "latest_recovery_action_receipt": _serialize_recovery_receipt(latest_receipt),
        "recovery_timeline_items": timeline,
        "system_runtime_timeline_items": system_runtime_timeline,
        "operator_action_timeline_items": operator_action_timeline,
        "target_activity_groups": _serialize_target_activity_groups(
            timeline,
            system_runtime_timeline,
            operator_action_timeline,
        ),
    }
    return ok(payload, req_id=getattr(request.state, "request_id", None))


@router.get("/api/v1/index/jobs/{job_id}")
def job_detail(job_id: str, request: Request, session: Session = Depends(get_session)):
    job = session.get(ReindexJob, job_id)
    if job:
        payload = _serialize_reindex(job)
    else:
        payload = _serialize_verify(session.get(VerifyJob, job_id))
    return ok(payload, req_id=getattr(request.state, "request_id", None))


@router.post("/api/v1/index/verify/{job_id}/retry")
def retry_verify(job_id: str, request: Request, session: Session = Depends(get_session)):
    actor_ref = getattr(request.state, "operator_ref", None) or "operator"
    result, status = execute_with_idempotency(
        session,
        idempotency_key=request.headers.get("X-Idempotency-Key"),
        method="POST",
        path_template="/api/v1/index/verify/{job_id}/retry",
        payload={"job_id": job_id},
        action=lambda: VersionManager(session).run_verify(job_id),
        actor_ref=actor_ref,
    )
    headers = {"X-Idempotency-Status": status} if status else {}
    return ok(result, req_id=getattr(request.state, "request_id", None), headers=headers)


@router.post("/api/v1/runtime/recovery/sweep")
def recovery_sweep(request: Request, session: Session = Depends(get_session)):
    actor_ref = getattr(request.state, "operator_ref", None) or "operator"
    result, status = execute_with_idempotency(
        session,
        idempotency_key=request.headers.get("X-Idempotency-Key"),
        method="POST",
        path_template="/api/v1/runtime/recovery/sweep",
        payload={},
        action=lambda: VersionManager(session).recover_stuck_jobs(),
        actor_ref=actor_ref,
    )
    headers = {"X-Idempotency-Status": status} if status else {}
    return ok(result, req_id=getattr(request.state, "request_id", None), headers=headers)


@router.post("/api/v1/runtime/promotions/run-due")
def run_due_promotions(request: Request, session: Session = Depends(get_session)):
    actor_ref = getattr(request.state, "operator_ref", None) or "operator"
    result, status = execute_with_idempotency(
        session,
        idempotency_key=request.headers.get("X-Idempotency-Key"),
        method="POST",
        path_template="/api/v1/runtime/promotions/run-due",
        payload={},
        action=lambda: VersionManager(session).run_due_promotions(),
        actor_ref=actor_ref,
    )
    headers = {"X-Idempotency-Status": status} if status else {}
    return ok(result, req_id=getattr(request.state, "request_id", None), headers=headers)


def _latest_alias_fault_summary(session: Session, alias_scope: str) -> dict | None:
    fault = session.execute(
        select(ReconcileFault)
        .where(
            ReconcileFault.fault_scope == "alias_mismatch",
            ReconcileFault.object_ref == alias_scope,
        )
        .order_by(ReconcileFault.created_at.desc(), ReconcileFault.fault_id.desc())
    ).scalars().first()
    if fault is None:
        return None
    return {
        "fault_scope": fault.fault_scope,
        "severity": fault.severity,
        "object_ref": fault.object_ref,
        "details_json": fault.details_json,
        "created_at": fault.created_at,
    }


def _serialize_alias(item: VectorAliasRegistry, *, session: Session) -> dict:
    return {
        "alias_scope": item.alias_scope,
        "object_type": item.object_type,
        "scope": item.scope,
        "scope_ref_id": item.scope_ref_id,
        "collection_family": item.collection_family,
        "active_alias": item.active_alias,
        "candidate_alias": item.candidate_alias,
        "active_snapshot_version": item.active_snapshot_version,
        "candidate_snapshot_version": item.candidate_snapshot_version,
        "active_embedding_version": item.active_embedding_version,
        "candidate_embedding_version": item.candidate_embedding_version,
        "verify_status": item.verify_status,
        "sample_query_success": bool(item.sample_query_success),
        "updated_at": item.updated_at,
        "recent_fault_summary": _latest_alias_fault_summary(session, item.alias_scope),
    }


def _serialize_reindex(job: ReindexJob) -> dict:
    return {
        "job_id": job.job_id,
        "review_id": job.review_id,
        "status": job.status,
        "job_type": "reindex",
        "object_type": job.object_type,
        "alias_scope": job.alias_scope,
        "target_snapshot_version": job.target_snapshot_version,
        "target_embedding_version": job.target_embedding_version,
        "worker_id": job.worker_id,
        "attempt_no": job.attempt_no,
        "heartbeat_at": job.heartbeat_at,
        "lease_expires_at": job.lease_expires_at,
        "started_at": job.started_at,
        "finished_at": job.finished_at,
        "error_text": job.error_text,
    }


def _serialize_verify(job: VerifyJob) -> dict:
    return {
        "job_id": job.job_id,
        "review_id": job.review_id,
        "status": job.status,
        "job_type": "verify",
        "object_type": job.object_type,
        "alias_scope": job.alias_scope,
        "target_snapshot_version": job.target_snapshot_version,
        "target_embedding_version": job.target_embedding_version,
        "worker_id": job.worker_id,
        "attempt_no": job.attempt_no,
        "heartbeat_at": job.heartbeat_at,
        "lease_expires_at": job.lease_expires_at,
        "started_at": job.started_at,
        "finished_at": job.finished_at,
        "error_text": job.error_text,
    }


def _serialize_recovery_timeline(session: Session) -> list[dict]:
    items = session.execute(
        select(HumanReviewEvent)
        .where(HumanReviewEvent.event_source == "idempotency_recovery")
    ).scalars().all()
    serialized = [_serialize_recovery_event(item) for item in items]
    serialized.sort(
        key=lambda item: (
            item["last_action_at"] or "",
            item["created_at"] or "",
            item["event_id"] or "",
        ),
        reverse=True,
    )
    return serialized


def _serialize_recovery_event(item: HumanReviewEvent) -> dict:
    details = dict(item.details_json or {})
    linked_target = human_review_linked_target(details, item.scene_id)
    followup_target = human_review_followup_target(details)
    replay_target = structured_target_from_replay_result(details.get("last_replay_result"))
    return {
        "event_id": item.event_id,
        "event_source": item.event_source,
        "priority": item.priority,
        "status": item.status,
        "object_ref": item.object_ref,
        "default_action": item.default_action,
        "linked_target": linked_target,
        "allowed_actions_json": item.allowed_actions_json,
        "result_status_map_json": item.result_status_map_json,
        "linked_target_ref": linked_target["target_ref"] if linked_target else details.get("linked_target_ref"),
        "resolution_reason": details.get("resolution_reason"),
        "followup_action": details.get("followup_action"),
        "followup_target": followup_target,
        "followup_target_ref": followup_target["target_ref"] if followup_target else details.get("followup_target_ref"),
        "last_action": details.get("last_action"),
        "last_action_at": details.get("last_action_at"),
        "last_action_status": details.get("last_action_status"),
        "last_actor_ref": details.get("last_actor_ref"),
        "last_replay_result": details.get("last_replay_result"),
        "replay_target": replay_target,
        "details_json": details,
        "created_at": item.created_at,
        "updated_at": item.updated_at,
    }


def _serialize_recovery_receipt(item: dict | None) -> dict | None:
    if item is None:
        return None
    return {
        "event_id": item["event_id"],
        "event_source": item["event_source"],
        "status": item["status"],
        "action": item["last_action"],
        "action_at": item["last_action_at"],
        "actor_ref": item["last_actor_ref"],
        "object_ref": item["object_ref"],
        "linked_target": item["linked_target"],
        "linked_target_ref": item["linked_target_ref"],
        "resolution_reason": item["resolution_reason"],
        "followup_action": item["followup_action"],
        "followup_target": item["followup_target"],
        "followup_target_ref": item["followup_target_ref"],
        "replay_result": item["last_replay_result"],
        "replay_target": item["replay_target"],
    }


def _serialize_system_runtime_timeline(session: Session) -> list[dict]:
    items = session.execute(
        select(OperationLog)
        .where(OperationLog.object_type == "runtime_activity")
        .order_by(OperationLog.created_at.desc(), OperationLog.operation_id.desc())
    ).scalars().all()
    return [_serialize_system_runtime_activity(item) for item in items]


def _serialize_operator_action_timeline(session: Session) -> list[dict]:
    items = session.execute(
        select(OperationLog)
        .where(or_(OperationLog.event_type == "human_review_action", OperationLog.event_type == "operator_action"))
        .order_by(OperationLog.created_at.desc(), OperationLog.operation_id.desc())
    ).scalars().all()
    return [_serialize_operator_action(item) for item in items]


def _serialize_system_runtime_activity(item: OperationLog) -> dict:
    payload = dict(item.payload_json or {})
    return {
        "operation_id": item.operation_id,
        "event_type": item.event_type,
        "object_ref": item.object_ref,
        "actor_ref": payload.get("actor_ref"),
        "summary": payload.get("summary"),
        "created_at": item.created_at,
        "target_refs": _operation_log_target_refs(item.object_type, item.event_type, item.object_ref, payload),
        "payload_json": payload,
    }


def _serialize_operator_action(item: OperationLog) -> dict:
    payload = dict(item.payload_json or {})
    data = {
        "operation_id": item.operation_id,
        "event_type": item.event_type,
        "event_id": item.object_ref if item.object_type == "human_review_event" else None,
        "object_ref": item.object_ref,
        "actor_ref": payload.get("actor_ref"),
        "action": payload.get("action"),
        "status_before": payload.get("status_before"),
        "status_after": payload.get("status_after"),
        "resolution_reason": payload.get("resolution_reason") or payload.get("summary"),
        "created_at": item.created_at,
        "target_refs": _operation_log_target_refs(item.object_type, item.event_type, item.object_ref, payload),
        "payload_json": payload,
    }
    if item.event_type == "operator_action":
        data["summary"] = payload.get("summary")
    return data


def _operation_log_target_refs(object_type: str, event_type: str, object_ref: str, payload: dict) -> list[dict[str, str]]:
    targets: list[dict[str, str]] = []

    if object_type == "human_review_event" and object_ref:
        event_target = structured_target("human_review_event", object_ref)
        if event_target is not None:
            targets.append(event_target)

    for value in payload.get("target_refs") or []:
        target = _coerce_target(value)
        if target is not None:
            targets.append(target)

    if object_type in {"review_item", "scene_card", "verify_job", "reindex_job"} and object_ref:
        direct_target = structured_target(object_type, object_ref)
        if direct_target is not None:
            targets.append(direct_target)

    review_id = payload.get("review_id")
    if isinstance(review_id, str) and review_id:
        targets.append(
            {
                "target_type": "review_item",
                "target_id": review_id,
                "target_ref": f"review_item:{review_id}",
            }
        )

    event_id = payload.get("event_id")
    if isinstance(event_id, str) and event_id:
        targets.append(
            {
                "target_type": "human_review_event",
                "target_id": event_id,
                "target_ref": f"human_review_event:{event_id}",
            }
        )

    job_id = payload.get("job_id")
    job_type = payload.get("job_type")
    if isinstance(job_id, str) and job_id:
        if job_type == "reindex" or job_id.startswith("reindex_"):
            target_type = "reindex_job"
        else:
            target_type = "verify_job"
        targets.append(
            {
                "target_type": target_type,
                "target_id": job_id,
                "target_ref": f"{target_type}:{job_id}",
            }
        )
    elif event_type == "runtime_job_reclaimed":
        if object_ref.startswith("reindex_"):
            target_type = "reindex_job"
        else:
            target_type = "verify_job"
        targets.append(
            {
                "target_type": target_type,
                "target_id": object_ref,
                "target_ref": f"{target_type}:{object_ref}",
            }
        )

    for key in ("linked_target", "followup_target", "replay_target"):
        target = _coerce_target(payload.get(key))
        if target is not None:
            targets.append(target)

    for key in ("linked_target_ref", "followup_target_ref", "replay_target_ref"):
        target = structured_target_from_ref(payload.get(key))
        if target is not None:
            targets.append(target)

    deduped: list[dict[str, str]] = []
    seen_refs: set[str] = set()
    for target in targets:
        target_ref = target["target_ref"]
        if target_ref in seen_refs:
            continue
        seen_refs.add(target_ref)
        deduped.append(target)
    return deduped


def _coerce_target(value: object) -> dict[str, str] | None:
    if not isinstance(value, dict):
        return None
    return structured_target(value.get("target_type"), value.get("target_id"), value.get("target_ref"))


def _serialize_target_activity_groups(
    recovery_timeline: list[dict],
    system_runtime_timeline: list[dict],
    operator_action_timeline: list[dict],
) -> list[dict]:
    groups: dict[str, dict] = {}

    for item in recovery_timeline:
        targets = _dedupe_targets([item.get("linked_target"), item.get("followup_target"), item.get("replay_target")])
        entry = {
            "activity_key": f"recovery_timeline:{item['event_id']}",
            "source": "recovery_timeline",
            "timestamp": item.get("last_action_at") or item.get("created_at"),
            "actor_ref": item.get("last_actor_ref"),
            "label": item.get("last_action") or item.get("default_action"),
            "status": item.get("status"),
            "summary": item.get("resolution_reason"),
            "object_ref": item.get("object_ref"),
            "target_refs": targets,
        }
        _append_target_group_entries(groups, targets, entry)

    for item in system_runtime_timeline:
        targets = _dedupe_targets(item.get("target_refs") or [])
        entry = {
            "activity_key": f"system_runtime:{item['operation_id']}",
            "source": "system_runtime",
            "timestamp": item.get("created_at"),
            "actor_ref": item.get("actor_ref"),
            "label": item.get("event_type"),
            "status": None,
            "summary": item.get("summary"),
            "object_ref": item.get("object_ref"),
            "target_refs": targets,
        }
        _append_target_group_entries(groups, targets, entry)

    for item in operator_action_timeline:
        targets = _dedupe_targets(item.get("target_refs") or [])
        entry = {
            "activity_key": f"operator_action:{item['operation_id']}",
            "source": "operator_action",
            "timestamp": item.get("created_at"),
            "actor_ref": item.get("actor_ref"),
            "label": item.get("action") or item.get("event_type"),
            "status": item.get("status_after"),
            "summary": item.get("resolution_reason"),
            "object_ref": item.get("object_ref"),
            "target_refs": targets,
        }
        _append_target_group_entries(groups, targets, entry)

    serialized: list[dict] = []
    for group in groups.values():
        activity_items = sorted(
            group["activity_items"],
            key=lambda item: ((item.get("timestamp") or ""), item.get("activity_key") or ""),
            reverse=True,
        )
        sources: list[str] = []
        seen_sources: set[str] = set()
        for item in activity_items:
            source = item["source"]
            if source in seen_sources:
                continue
            seen_sources.add(source)
            sources.append(source)
        serialized.append(
            {
                "target": group["target"],
                "latest_at": activity_items[0].get("timestamp") if activity_items else None,
                "activity_count": len(activity_items),
                "sources": sources,
                "activity_items": activity_items,
            }
        )
    serialized.sort(key=lambda item: ((item.get("latest_at") or ""), item["target"]["target_ref"]), reverse=True)
    return serialized


def _append_target_group_entries(groups: dict[str, dict], targets: list[dict[str, str]], entry: dict) -> None:
    for target in targets:
        if target["target_type"] == "human_review_event":
            continue
        target_ref = target["target_ref"]
        group = groups.setdefault(
            target_ref,
            {
                "target": target,
                "activity_items": [],
                "_seen_keys": set(),
            },
        )
        activity_key = entry["activity_key"]
        if activity_key in group["_seen_keys"]:
            continue
        group["_seen_keys"].add(activity_key)
        group["activity_items"].append(entry)


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
