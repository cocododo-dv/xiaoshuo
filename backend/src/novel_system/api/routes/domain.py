from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from novel_system.api.deps import get_session
from novel_system.api.response import ok
from novel_system.services.knowledge_catalog import (
    get_knowledge_entry,
    get_knowledge_workflow,
    list_paginated_activity_events,
    list_paginated_target_activity_groups,
    list_target_activity_group_items,
)

router = APIRouter(tags=["domain"])


# /api/v1/knowledge-entries 列表与 /api/v1/jobs、/api/v1/vector-alias-scopes 的
# handler 已收敛：分别注册在 routes/knowledge.py 与 routes/indexing.py 的同一函数上，
# URL 面不变。本文件保留 knowledge-entries 详情/工作流与活动流端点。
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


@router.get("/api/v1/activity-events")
def activity_events(
    request: Request,
    stream: Literal["recovery_timeline", "system_runtime", "operator_action"],
    session: Session = Depends(get_session),
    target_ref: str | None = None,
    actor_ref: str | None = None,
    page: int | None = None,
    page_size: int | None = None,
    cursor: str | None = None,
    limit: int | None = None,
):
    return ok(
        list_paginated_activity_events(
            session,
            stream=stream,
            target_ref=target_ref,
            actor_ref=actor_ref,
            page=page,
            page_size=page_size,
            cursor=cursor,
            limit=limit,
        ),
        req_id=getattr(request.state, "request_id", None),
    )


@router.get("/api/v1/target-activity-groups")
def target_activity_groups(
    request: Request,
    session: Session = Depends(get_session),
    target_ref: str | None = None,
    source: Literal["recovery_timeline", "system_runtime", "operator_action"] | None = None,
    actor_ref: str | None = None,
    page: int | None = None,
    page_size: int | None = None,
    cursor: str | None = None,
    limit: int | None = None,
):
    return ok(
        list_paginated_target_activity_groups(
            session,
            target_ref=target_ref,
            source=source,
            actor_ref=actor_ref,
            page=page,
            page_size=page_size,
            cursor=cursor,
            limit=limit,
        ),
        req_id=getattr(request.state, "request_id", None),
    )


@router.get("/api/v1/target-activity-groups/{target_ref:path}/items")
def target_activity_group_items(
    target_ref: str,
    request: Request,
    session: Session = Depends(get_session),
    source: Literal["recovery_timeline", "system_runtime", "operator_action"] | None = None,
    actor_ref: str | None = None,
    page: int | None = None,
    page_size: int | None = None,
    cursor: str | None = None,
    limit: int | None = None,
):
    return ok(
        list_target_activity_group_items(
            session,
            target_ref=target_ref,
            source=source,
            actor_ref=actor_ref,
            page=page,
            page_size=page_size,
            cursor=cursor,
            limit=limit,
        ),
        req_id=getattr(request.state, "request_id", None),
    )
