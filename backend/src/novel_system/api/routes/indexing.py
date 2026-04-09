from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from novel_system.api.deps import get_session
from novel_system.api.response import ok
from novel_system.db.models import ReindexJob, VectorAliasRegistry, VerifyJob
from novel_system.services.idempotency import execute_with_idempotency
from novel_system.services.version_manager import VersionManager

router = APIRouter(tags=["indexing"])


@router.get("/api/v1/index/alias-scopes")
def list_alias_scopes(request: Request, session: Session = Depends(get_session)):
    items = session.execute(select(VectorAliasRegistry).order_by(VectorAliasRegistry.alias_scope.asc())).scalars().all()
    return ok({"items": [_serialize_alias(item) for item in items]}, req_id=getattr(request.state, "request_id", None))


@router.get("/api/v1/index/alias-scopes/{alias_scope:path}")
def alias_scope_detail(alias_scope: str, request: Request, session: Session = Depends(get_session)):
    item = session.get(VectorAliasRegistry, alias_scope)
    return ok(_serialize_alias(item), req_id=getattr(request.state, "request_id", None))


@router.get("/api/v1/index/jobs")
def list_jobs(request: Request, session: Session = Depends(get_session)):
    reindex_jobs = session.execute(select(ReindexJob)).scalars().all()
    verify_jobs = session.execute(select(VerifyJob)).scalars().all()
    items = [_serialize_reindex(job) for job in reindex_jobs] + [_serialize_verify(job) for job in verify_jobs]
    items.sort(key=lambda item: item["job_id"])
    return ok({"items": items}, req_id=getattr(request.state, "request_id", None))


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
    result, status = execute_with_idempotency(
        session,
        idempotency_key=request.headers.get("X-Idempotency-Key"),
        method="POST",
        path_template="/api/v1/index/verify/{job_id}/retry",
        payload={"job_id": job_id},
        action=lambda: VersionManager(session).run_verify(job_id),
    )
    headers = {"X-Idempotency-Status": status} if status else {}
    return ok(result, req_id=getattr(request.state, "request_id", None), headers=headers)


@router.post("/api/v1/runtime/recovery/sweep")
def recovery_sweep(request: Request, session: Session = Depends(get_session)):
    result, status = execute_with_idempotency(
        session,
        idempotency_key=request.headers.get("X-Idempotency-Key"),
        method="POST",
        path_template="/api/v1/runtime/recovery/sweep",
        payload={},
        action=lambda: VersionManager(session).recover_stuck_jobs(),
    )
    headers = {"X-Idempotency-Status": status} if status else {}
    return ok(result, req_id=getattr(request.state, "request_id", None), headers=headers)


@router.post("/api/v1/runtime/promotions/run-due")
def run_due_promotions(request: Request):
    return ok({"promoted": 0}, req_id=getattr(request.state, "request_id", None))


def _serialize_alias(item: VectorAliasRegistry) -> dict:
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
    }
