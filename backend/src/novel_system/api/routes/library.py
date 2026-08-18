"""资料库路由 — 实体/关系 CRUD 与项目级聚合(设计稿 ws-library)。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from novel_system.api.deps import get_session
from novel_system.api.library_requests import (
    LibraryCharacterRequest,
    LibraryDeriveRequest,
    LibraryEntityCreateRequest,
    LibraryEntityUpdateRequest,
    LibraryRelationCreateRequest,
    LibraryTimelineEventRequest,
)
from novel_system.api.mutations import optional_idempotent_response
from novel_system.api.request_types import EmptyRequest
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
    payload: LibraryEntityCreateRequest,
    request: Request,
    session: Session = Depends(get_session),
):
    body = payload.model_dump(mode="json", exclude_unset=True)
    result, status = execute_with_idempotency(
        session,
        idempotency_key=request.headers.get("X-Idempotency-Key"),
        method="POST",
        path_template="/api/v2/projects/{project_id}/library/entities",
        payload={"project_id": project_id, "body": body},
        action=lambda: LibraryService(session).create_entity(project_id, body),
        actor_ref=_operator(request),
    )
    headers = {"X-Idempotency-Status": status} if status else {}
    return ok(result, req_id=getattr(request.state, "request_id", None), headers=headers)


@router.patch("/api/v2/projects/{project_id}/library/entities/{entity_id}")
def update_library_entity(
    project_id: str,
    entity_id: str,
    payload: LibraryEntityUpdateRequest,
    request: Request,
    session: Session = Depends(get_session),
):
    body = payload.model_dump(mode="json", exclude_unset=True)
    return optional_idempotent_response(
        request,
        session,
        method="PATCH",
        path_template="/api/v2/projects/{project_id}/library/entities/{entity_id}",
        payload={"project_id": project_id, "entity_id": entity_id, "body": body},
        action=lambda: LibraryService(session).update_entity(project_id, entity_id, body),
    )


@router.post("/api/v2/projects/{project_id}/library/relations")
def create_library_relation(
    project_id: str,
    payload: LibraryRelationCreateRequest,
    request: Request,
    session: Session = Depends(get_session),
):
    body = payload.model_dump(mode="json", exclude_unset=True)
    result, status = execute_with_idempotency(
        session,
        idempotency_key=request.headers.get("X-Idempotency-Key"),
        method="POST",
        path_template="/api/v2/projects/{project_id}/library/relations",
        payload={"project_id": project_id, "body": body},
        action=lambda: LibraryService(session).create_relation(project_id, body),
        actor_ref=_operator(request),
    )
    headers = {"X-Idempotency-Status": status} if status else {}
    return ok(result, req_id=getattr(request.state, "request_id", None), headers=headers)


@router.delete("/api/v2/projects/{project_id}/library/relations/{relation_id}")
def delete_library_relation(
    project_id: str,
    relation_id: str,
    request: Request,
    payload: EmptyRequest | None = None,
    session: Session = Depends(get_session),
):
    return optional_idempotent_response(
        request,
        session,
        method="DELETE",
        path_template="/api/v2/projects/{project_id}/library/relations/{relation_id}",
        payload={
            "project_id": project_id,
            "relation_id": relation_id,
            "body": payload.model_dump(mode="json") if payload else {},
        },
        action=lambda: LibraryService(session).delete_relation(project_id, relation_id),
    )


# ---------------------------------------------------------------------------
# FE-ALIGN Phase 6：时间线 / 图投影 / 人物资料卡 / 半自动派生
# ---------------------------------------------------------------------------


@router.get("/api/v2/projects/{project_id}/library/timeline")
def list_library_timeline(project_id: str, request: Request, session: Session = Depends(get_session)):
    return ok(LibraryService(session).list_timeline(project_id), req_id=getattr(request.state, "request_id", None))


@router.post("/api/v2/projects/{project_id}/library/timeline")
def create_library_timeline_event(
    project_id: str,
    payload: LibraryTimelineEventRequest,
    request: Request,
    session: Session = Depends(get_session),
):
    body = payload.model_dump(mode="json", exclude_unset=True)
    result, status = execute_with_idempotency(
        session,
        idempotency_key=request.headers.get("X-Idempotency-Key"),
        method="POST",
        path_template="/api/v2/projects/{project_id}/library/timeline",
        payload={"project_id": project_id, "body": body},
        action=lambda: LibraryService(session).create_timeline_event(project_id, body),
        actor_ref=_operator(request),
    )
    headers = {"X-Idempotency-Status": status} if status else {}
    return ok(result, req_id=getattr(request.state, "request_id", None), headers=headers)


@router.patch("/api/v2/projects/{project_id}/library/timeline/{event_id}")
def update_library_timeline_event(
    project_id: str,
    event_id: str,
    payload: LibraryTimelineEventRequest,
    request: Request,
    session: Session = Depends(get_session),
):
    body = payload.model_dump(mode="json", exclude_unset=True)
    return optional_idempotent_response(
        request,
        session,
        method="PATCH",
        path_template="/api/v2/projects/{project_id}/library/timeline/{event_id}",
        payload={"project_id": project_id, "event_id": event_id, "body": body},
        action=lambda: LibraryService(session).update_timeline_event(project_id, event_id, body),
    )


@router.delete("/api/v2/projects/{project_id}/library/timeline/{event_id}")
def delete_library_timeline_event(
    project_id: str,
    event_id: str,
    request: Request,
    payload: EmptyRequest | None = None,
    session: Session = Depends(get_session),
):
    return optional_idempotent_response(
        request,
        session,
        method="DELETE",
        path_template="/api/v2/projects/{project_id}/library/timeline/{event_id}",
        payload={
            "project_id": project_id,
            "event_id": event_id,
            "body": payload.model_dump(mode="json") if payload else {},
        },
        action=lambda: LibraryService(session).delete_timeline_event(project_id, event_id),
    )


@router.get("/api/v2/projects/{project_id}/library/graph")
def library_graph(project_id: str, request: Request, session: Session = Depends(get_session)):
    return ok(LibraryService(session).graph(project_id), req_id=getattr(request.state, "request_id", None))


@router.post("/api/v2/projects/{project_id}/library/characters")
def create_library_character(
    project_id: str,
    payload: LibraryCharacterRequest,
    request: Request,
    session: Session = Depends(get_session),
):
    body = payload.model_dump(mode="json", exclude_unset=True)
    result, status = execute_with_idempotency(
        session,
        idempotency_key=request.headers.get("X-Idempotency-Key"),
        method="POST",
        path_template="/api/v2/projects/{project_id}/library/characters",
        payload={"project_id": project_id, "body": body},
        action=lambda: LibraryService(session).create_character(project_id, body),
        actor_ref=_operator(request),
    )
    headers = {"X-Idempotency-Status": status} if status else {}
    return ok(result, req_id=getattr(request.state, "request_id", None), headers=headers)


@router.patch("/api/v2/projects/{project_id}/library/characters/{character_id}")
def update_library_character(
    project_id: str,
    character_id: str,
    payload: LibraryCharacterRequest,
    request: Request,
    session: Session = Depends(get_session),
):
    body = payload.model_dump(mode="json", exclude_unset=True)
    return optional_idempotent_response(
        request,
        session,
        method="PATCH",
        path_template="/api/v2/projects/{project_id}/library/characters/{character_id}",
        payload={"project_id": project_id, "character_id": character_id, "body": body},
        action=lambda: LibraryService(session).update_character(project_id, character_id, body),
    )


@router.delete("/api/v2/projects/{project_id}/library/characters/{character_id}")
def delete_library_character(
    project_id: str,
    character_id: str,
    request: Request,
    payload: EmptyRequest | None = None,
    session: Session = Depends(get_session),
):
    return optional_idempotent_response(
        request,
        session,
        method="DELETE",
        path_template="/api/v2/projects/{project_id}/library/characters/{character_id}",
        payload={
            "project_id": project_id,
            "character_id": character_id,
            "body": payload.model_dump(mode="json") if payload else {},
        },
        action=lambda: LibraryService(session).delete_character(project_id, character_id),
    )


@router.delete("/api/v2/projects/{project_id}/library/entities/{entity_id}")
def delete_library_entity(
    project_id: str,
    entity_id: str,
    request: Request,
    payload: EmptyRequest | None = None,
    session: Session = Depends(get_session),
):
    return optional_idempotent_response(
        request,
        session,
        method="DELETE",
        path_template="/api/v2/projects/{project_id}/library/entities/{entity_id}",
        payload={
            "project_id": project_id,
            "entity_id": entity_id,
            "body": payload.model_dump(mode="json") if payload else {},
        },
        action=lambda: LibraryService(session).delete_entity(project_id, entity_id),
    )


@router.post("/api/v2/projects/{project_id}/library/derive")
def derive_library_candidates(
    project_id: str,
    payload: LibraryDeriveRequest,
    request: Request,
    session: Session = Depends(get_session),
):
    """半自动派生（D5）：LLM 提取候选 → idea 卡进待办；不直接入库。LLM 未配置时静默跳过。"""
    from novel_system.services.library_derive import LibraryDeriveService

    body = payload.model_dump(mode="json", exclude_unset=True)
    chapter_id = str(body.get("chapter_id") or "")
    return optional_idempotent_response(
        request,
        session,
        method="POST",
        path_template="/api/v2/projects/{project_id}/library/derive",
        payload={"project_id": project_id, "body": body},
        action=lambda: LibraryDeriveService(session).derive_from_chapter(project_id, chapter_id),
    )
