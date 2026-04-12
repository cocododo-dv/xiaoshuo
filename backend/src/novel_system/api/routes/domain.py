from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from novel_system.api.deps import get_session
from novel_system.api.response import ok
from novel_system.services.knowledge_catalog import (
    get_knowledge_entry,
    get_knowledge_workflow,
    list_activity_events,
    list_jobs,
    list_knowledge_entries,
    list_target_activity_groups,
    list_vector_alias_scopes,
    supported_object_types,
)

router = APIRouter(tags=["domain"])


@router.get("/api/v1/knowledge-entries")
def knowledge_entries(
    request: Request,
    session: Session = Depends(get_session),
    object_type: str | None = None,
    scope: str | None = None,
    scope_ref_id: str | None = None,
    status: str | None = None,
):
    return ok(
        {
            "items": list_knowledge_entries(
                session,
                object_type=object_type,
                scope=scope,
                scope_ref_id=scope_ref_id,
                status=status,
            ),
            "supported_object_types": supported_object_types(),
        },
        req_id=getattr(request.state, "request_id", None),
    )


@router.get("/api/v1/knowledge-entries/{object_type}/{lineage_key}")
def knowledge_entry_detail(
    object_type: str,
    lineage_key: str,
    request: Request,
    session: Session = Depends(get_session),
):
    return ok(
        get_knowledge_entry(session, object_type=object_type, lineage_key=lineage_key),
        req_id=getattr(request.state, "request_id", None),
    )


@router.get("/api/v1/knowledge-entries/{object_type}/{lineage_key}/workflow")
def knowledge_entry_workflow(
    object_type: str,
    lineage_key: str,
    request: Request,
    session: Session = Depends(get_session),
):
    return ok(
        get_knowledge_workflow(session, object_type=object_type, lineage_key=lineage_key),
        req_id=getattr(request.state, "request_id", None),
    )


@router.get("/api/v1/vector-alias-scopes")
def vector_alias_scopes(
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


@router.get("/api/v1/jobs")
def jobs(
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
        list_jobs(
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


@router.get("/api/v1/activity-events")
def activity_events(
    request: Request,
    stream: Literal["recovery_timeline", "system_runtime", "operator_action"],
    session: Session = Depends(get_session),
    target_ref: str | None = None,
    actor_ref: str | None = None,
):
    return ok(
        {"items": list_activity_events(session, stream=stream, target_ref=target_ref, actor_ref=actor_ref)},
        req_id=getattr(request.state, "request_id", None),
    )


@router.get("/api/v1/target-activity-groups")
def target_activity_groups(
    request: Request,
    session: Session = Depends(get_session),
    target_ref: str | None = None,
    source: Literal["recovery_timeline", "system_runtime", "operator_action"] | None = None,
    actor_ref: str | None = None,
):
    return ok(
        {
            "items": list_target_activity_groups(
                session,
                target_ref=target_ref,
                source=source,
                actor_ref=actor_ref,
            )
        },
        req_id=getattr(request.state, "request_id", None),
    )
