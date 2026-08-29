from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from novel_system.api.deps import get_session
from novel_system.api.response import ok
from novel_system.services.knowledge_catalog import get_knowledge, list_knowledge_entries, supported_object_types

router = APIRouter(tags=["knowledge"])


# 同一 handler 注册两条路径：/api/v1/knowledge-entries 是 domain 面的等价 URL，
# legacy Vue 两套 URL 都在用，响应形状必须逐字一致。
@router.get("/api/v1/knowledge")
@router.get("/api/v1/knowledge-entries")
def knowledge_index(
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


@router.get("/api/v1/knowledge/{object_type}/{lineage_key}")
def knowledge_detail(object_type: str, lineage_key: str, request: Request, session: Session = Depends(get_session)):
    return ok(
        get_knowledge(session, object_type=object_type, lineage_key=lineage_key),
        req_id=getattr(request.state, "request_id", None),
    )
