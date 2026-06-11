"""资料库路由 — 实体/关系 CRUD 与项目级聚合(设计稿 ws-library)。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from novel_system.api.deps import get_session
from novel_system.api.response import ok
from novel_system.services.library import LibraryService

router = APIRouter(tags=["library"])


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
    result = LibraryService(session).create_entity(project_id, payload or {})
    session.commit()
    return ok(result, req_id=getattr(request.state, "request_id", None))


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
    result = LibraryService(session).create_relation(project_id, payload or {})
    session.commit()
    return ok(result, req_id=getattr(request.state, "request_id", None))


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
