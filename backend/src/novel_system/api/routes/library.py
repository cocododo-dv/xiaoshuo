"""资料库路由 — 实体/关系 CRUD 与项目级聚合(设计稿 ws-library)。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from novel_system.api.deps import get_session
from novel_system.api.response import ok
from novel_system.services.idempotency import execute_with_idempotency
from novel_system.services.library import LibraryService

router = APIRouter(tags=["library"])


def _operator(request: Request) -> str:
    return getattr(request.state, "operator_ref", None) or "operator"


@router.get("/api/v2/projects/{project_id}/library")
def library_overview(project_id: str, request: Request, session: Session = Depends(get_session)):
    result = LibraryService(session).overview(project_id)
    return ok(result, req_id=getattr(request.state, "request_id", None))


@router.post("/api/v2/projects/{project_id}/library/entities")
def create_library_entity(
    project_id: str,
    payload: dict[str, Any],
    request: Request,
    session: Session = Depends(get_session),
):
    result, status = execute_with_idempotency(
        session,
        idempotency_key=request.headers.get("X-Idempotency-Key"),
        method="POST",
        path_template=f"/api/v2/projects/{project_id}/library/entities",
        payload=payload,
        action=lambda: LibraryService(session).create_entity(project_id, payload or {}),
        actor_ref=_operator(request),
    )
    headers = {"X-Idempotency-Status": status} if status else {}
    return ok(result, req_id=getattr(request.state, "request_id", None), headers=headers)


@router.patch("/api/v2/projects/{project_id}/library/entities/{entity_id}")
def update_library_entity(
    project_id: str,
    entity_id: str,
    payload: dict[str, Any],
    request: Request,
    session: Session = Depends(get_session),
):
    result = LibraryService(session).update_entity(project_id, entity_id, payload or {})
    session.commit()
    return ok(result, req_id=getattr(request.state, "request_id", None))


@router.post("/api/v2/projects/{project_id}/library/relations")
def create_library_relation(
    project_id: str,
    payload: dict[str, Any],
    request: Request,
    session: Session = Depends(get_session),
):
    result, status = execute_with_idempotency(
        session,
        idempotency_key=request.headers.get("X-Idempotency-Key"),
        method="POST",
        path_template=f"/api/v2/projects/{project_id}/library/relations",
        payload=payload,
        action=lambda: LibraryService(session).create_relation(project_id, payload or {}),
        actor_ref=_operator(request),
    )
    headers = {"X-Idempotency-Status": status} if status else {}
    return ok(result, req_id=getattr(request.state, "request_id", None), headers=headers)


@router.delete("/api/v2/projects/{project_id}/library/relations/{relation_id}")
def delete_library_relation(
    project_id: str,
    relation_id: str,
    request: Request,
    session: Session = Depends(get_session),
):
    result = LibraryService(session).delete_relation(project_id, relation_id)
    session.commit()
    return ok(result, req_id=getattr(request.state, "request_id", None))


# ---------------------------------------------------------------------------
# FE-ALIGN Phase 6：时间线 / 图投影 / 人物资料卡 / 半自动派生
# ---------------------------------------------------------------------------


@router.get("/api/v2/projects/{project_id}/library/timeline")
def list_library_timeline(project_id: str, request: Request, session: Session = Depends(get_session)):
    return ok(LibraryService(session).list_timeline(project_id), req_id=getattr(request.state, "request_id", None))


@router.post("/api/v2/projects/{project_id}/library/timeline")
def create_library_timeline_event(
    project_id: str,
    payload: dict[str, Any],
    request: Request,
    session: Session = Depends(get_session),
):
    result, status = execute_with_idempotency(
        session,
        idempotency_key=request.headers.get("X-Idempotency-Key"),
        method="POST",
        path_template=f"/api/v2/projects/{project_id}/library/timeline",
        payload=payload,
        action=lambda: LibraryService(session).create_timeline_event(project_id, payload or {}),
        actor_ref=_operator(request),
    )
    headers = {"X-Idempotency-Status": status} if status else {}
    return ok(result, req_id=getattr(request.state, "request_id", None), headers=headers)


@router.patch("/api/v2/projects/{project_id}/library/timeline/{event_id}")
def update_library_timeline_event(
    project_id: str,
    event_id: str,
    payload: dict[str, Any],
    request: Request,
    session: Session = Depends(get_session),
):
    result = LibraryService(session).update_timeline_event(project_id, event_id, payload or {})
    session.commit()
    return ok(result, req_id=getattr(request.state, "request_id", None))


@router.delete("/api/v2/projects/{project_id}/library/timeline/{event_id}")
def delete_library_timeline_event(
    project_id: str,
    event_id: str,
    request: Request,
    session: Session = Depends(get_session),
):
    result = LibraryService(session).delete_timeline_event(project_id, event_id)
    session.commit()
    return ok(result, req_id=getattr(request.state, "request_id", None))


@router.get("/api/v2/projects/{project_id}/library/graph")
def library_graph(project_id: str, request: Request, session: Session = Depends(get_session)):
    return ok(LibraryService(session).graph(project_id), req_id=getattr(request.state, "request_id", None))


@router.post("/api/v2/projects/{project_id}/library/characters")
def create_library_character(
    project_id: str,
    payload: dict[str, Any],
    request: Request,
    session: Session = Depends(get_session),
):
    result, status = execute_with_idempotency(
        session,
        idempotency_key=request.headers.get("X-Idempotency-Key"),
        method="POST",
        path_template=f"/api/v2/projects/{project_id}/library/characters",
        payload=payload,
        action=lambda: LibraryService(session).create_character(project_id, payload or {}),
        actor_ref=_operator(request),
    )
    headers = {"X-Idempotency-Status": status} if status else {}
    return ok(result, req_id=getattr(request.state, "request_id", None), headers=headers)


@router.patch("/api/v2/projects/{project_id}/library/characters/{character_id}")
def update_library_character(
    project_id: str,
    character_id: str,
    payload: dict[str, Any],
    request: Request,
    session: Session = Depends(get_session),
):
    result = LibraryService(session).update_character(project_id, character_id, payload or {})
    session.commit()
    return ok(result, req_id=getattr(request.state, "request_id", None))


@router.post("/api/v2/projects/{project_id}/library/derive")
def derive_library_candidates(
    project_id: str,
    payload: dict[str, Any],
    request: Request,
    session: Session = Depends(get_session),
):
    """半自动派生（D5）：LLM 提取候选 → idea 卡进待办；不直接入库。LLM 未配置时静默跳过。"""
    from novel_system.services.library_derive import LibraryDeriveService

    result = LibraryDeriveService(session).derive_from_chapter(
        project_id, str((payload or {}).get("chapter_id") or "")
    )
    session.commit()
    return ok(result, req_id=getattr(request.state, "request_id", None))
