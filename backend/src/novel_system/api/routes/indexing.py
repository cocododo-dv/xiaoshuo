from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from novel_system.api.deps import get_session
from novel_system.api.request_types import EmptyRequest
from novel_system.api.response import ok
from novel_system.api.mutations import idempotent_response
from novel_system.services.knowledge_catalog import (
    latest_recovery_action_receipt,
    list_activity_events,
    list_jobs as list_domain_jobs,
    list_target_activity_groups,
    list_vector_alias_scopes,
)
from novel_system.services.versioning import PromotionService, RuntimeRecoveryService, VectorLifecycleService

router = APIRouter(tags=["indexing"])


# 同一 handler 注册两条路径：/api/v1/vector-alias-scopes 是 domain 面的等价 URL，
# legacy Vue 两套 URL 都在用，响应形状必须逐字一致。
@router.get("/api/v1/index/alias-scopes")
@router.get("/api/v1/vector-alias-scopes")
def list_alias_scopes(
    request: Request,
    session: Session = Depends(get_session),
    object_type: str | None = None,
    scope: str | None = None,
    scope_ref_id: str | None = None,
    verify_status: str | None = None,
):
    return ok(
        {
            "items": list_vector_alias_scopes(
                session,
                object_type=object_type,
                scope=scope,
                scope_ref_id=scope_ref_id,
                verify_status=verify_status,
            )
        },
        req_id=getattr(request.state, "request_id", None),
    )


# 同一 handler 注册两条路径：/api/v1/jobs 是 domain 面的等价 URL，两条都保留。
@router.get("/api/v1/index/jobs")
@router.get("/api/v1/jobs")
def list_jobs(
    request: Request,
    session: Session = Depends(get_session),
    job_type: Literal["reindex", "verify"] | None = None,
    status: str | None = None,
    object_type: str | None = None,
    review_id: str | None = None,
    alias_scope: str | None = None,
    worker_id: str | None = None,
    stuck_only: bool | None = None,
    page: int | None = None,
    page_size: int | None = None,
    cursor: str | None = None,
    limit: int | None = None,
):
    return ok(
        list_domain_jobs(
            session,
            job_type=job_type,
            status=status,
            object_type=object_type,
            review_id=review_id,
            alias_scope=alias_scope,
            worker_id=worker_id,
            stuck_only=stuck_only,
            page=page,
            page_size=page_size,
            cursor=cursor,
            limit=limit,
        ),
        req_id=getattr(request.state, "request_id", None),
    )


@router.get("/api/v1/index/runtime-ledger")
def runtime_ledger(
    request: Request,
    session: Session = Depends(get_session),
    target_ref: str | None = None,
    source: Literal["recovery_timeline", "system_runtime", "operator_action"] | None = None,
    actor_ref: str | None = None,
):
    recovery_timeline = [] if source in {"system_runtime", "operator_action"} else list_activity_events(
        session,
        stream="recovery_timeline",
        target_ref=target_ref,
        actor_ref=actor_ref,
    )
    system_runtime_timeline = [] if source in {"recovery_timeline", "operator_action"} else list_activity_events(
        session,
        stream="system_runtime",
        target_ref=target_ref,
        actor_ref=actor_ref,
    )
    operator_action_timeline = [] if source in {"recovery_timeline", "system_runtime"} else list_activity_events(
        session,
        stream="operator_action",
        target_ref=target_ref,
        actor_ref=actor_ref,
    )
    return ok(
        {
            "latest_recovery_action_receipt": None
            if source in {"system_runtime", "operator_action"}
            else latest_recovery_action_receipt(session, target_ref=target_ref, actor_ref=actor_ref),
            "recovery_timeline_items": recovery_timeline,
            "system_runtime_timeline_items": system_runtime_timeline,
            "operator_action_timeline_items": operator_action_timeline,
            "target_activity_groups": list_target_activity_groups(
                session,
                target_ref=target_ref,
                source=source,
                actor_ref=actor_ref,
            ),
        },
        req_id=getattr(request.state, "request_id", None),
    )


@router.post("/api/v1/index/verify/{job_id}/retry")
def retry_verify(
    job_id: str,
    request: Request,
    payload: EmptyRequest | None = None,
    session: Session = Depends(get_session),
):
    return idempotent_response(
        request,
        session,
        method="POST",
        path_template="/api/v1/index/verify/{job_id}/retry",
        payload={"job_id": job_id},
        action=lambda: VectorLifecycleService(session).run_verify(job_id),
        owned_failure_callback=lambda error: VectorLifecycleService.publish_owned_verify_failure(
            session,
            error,
        ),
    )


@router.post("/api/v1/runtime/recovery/sweep")
def recovery_sweep(
    request: Request,
    payload: EmptyRequest | None = None,
    session: Session = Depends(get_session),
):
    from novel_system.services.scene_run_jobs import recover_expired_cancel_requested_jobs

    return idempotent_response(
        request,
        session,
        method="POST",
        path_template="/api/v1/runtime/recovery/sweep",
        payload={},
        action=lambda: RuntimeRecoveryService(session).recover_stuck_jobs(
            scene_cancellation_recoverer=recover_expired_cancel_requested_jobs,
        ),
    )


@router.post("/api/v1/runtime/promotions/run-due")
def run_due_promotions(
    request: Request,
    payload: EmptyRequest | None = None,
    session: Session = Depends(get_session),
):
    return idempotent_response(
        request,
        session,
        method="POST",
        path_template="/api/v1/runtime/promotions/run-due",
        payload={},
        action=lambda: PromotionService(session).run_due_promotions(),
    )
