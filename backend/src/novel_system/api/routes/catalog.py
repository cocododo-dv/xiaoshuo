"""FE-ALIGN Phase 3: 目录 API（v2）—— 章节/场景树的唯一真相源。

对应原型 WsCatalog（design/ws-catalog.jsx）；创建类端点（建章/建场景）经
execute_with_idempotency 兑现幂等键（必填 + 同键重放同响应）；PATCH/move/软删/恢复
按天然幂等语义不强制。import 端点仅供 localStorage 一次性迁移使用，admin token 保护
（loopback 免 token）。
"""
from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from novel_system.api.deps import get_session
from novel_system.api.response import ok
from novel_system.services.catalog import CatalogService
from novel_system.services.idempotency import execute_with_idempotency
from novel_system.services.system_config import require_admin_token

router = APIRouter(tags=["catalog"])


class ChapterOrderRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    chapter_ids: list[
        Annotated[str, Field(min_length=1, max_length=255)]
    ] = Field(min_length=1, max_length=10_000)


def _req_id(request: Request):
    return getattr(request.state, "request_id", None)


def _operator(request: Request) -> str:
    return getattr(request.state, "operator_ref", None) or "operator"


@router.get("/api/v2/projects/{project_id}/catalog")
def get_catalog(project_id: str, request: Request, session: Session = Depends(get_session)):
    return ok(CatalogService(session).catalog(project_id), req_id=_req_id(request))


@router.post("/api/v2/projects/{project_id}/catalog/chapters")
def create_catalog_chapter(
    project_id: str,
    payload: dict[str, Any],
    request: Request,
    session: Session = Depends(get_session),
):
    result, status = execute_with_idempotency(
        session,
        idempotency_key=request.headers.get("X-Idempotency-Key"),
        method="POST",
        path_template=f"/api/v2/projects/{project_id}/catalog/chapters",
        payload=payload,
        action=lambda: CatalogService(session).create_chapter(project_id, payload or {}),
        actor_ref=_operator(request),
    )
    headers = {"X-Idempotency-Status": status} if status else {}
    return ok(result, req_id=_req_id(request), headers=headers)


@router.patch("/api/v2/projects/{project_id}/catalog/chapters/{chapter_id}")
def update_catalog_chapter(
    project_id: str,
    chapter_id: str,
    payload: dict[str, Any],
    request: Request,
    session: Session = Depends(get_session),
):
    result = CatalogService(session).update_chapter(project_id, chapter_id, payload or {})
    session.commit()
    return ok(result, req_id=_req_id(request))


@router.post("/api/v2/projects/{project_id}/catalog/chapter-order")
def reorder_catalog_chapters(
    project_id: str,
    payload: ChapterOrderRequest,
    request: Request,
    session: Session = Depends(get_session),
):
    body = payload.model_dump(mode="json")
    result, status = execute_with_idempotency(
        session,
        idempotency_key=request.headers.get("X-Idempotency-Key"),
        method="POST",
        path_template=f"/api/v2/projects/{project_id}/catalog/chapter-order",
        payload={"project_id": project_id, **body},
        action=lambda: CatalogService(session).reorder_chapters(
            project_id,
            body["chapter_ids"],
        ),
        actor_ref=_operator(request),
    )
    headers = {"X-Idempotency-Status": status} if status else {}
    return ok(result, req_id=_req_id(request), headers=headers)


@router.post("/api/v2/projects/{project_id}/catalog/chapters/{chapter_id}/scenes")
def create_catalog_scene(
    project_id: str,
    chapter_id: str,
    payload: dict[str, Any],
    request: Request,
    session: Session = Depends(get_session),
):
    result, status = execute_with_idempotency(
        session,
        idempotency_key=request.headers.get("X-Idempotency-Key"),
        method="POST",
        path_template=f"/api/v2/projects/{project_id}/catalog/chapters/{chapter_id}/scenes",
        payload=payload,
        action=lambda: CatalogService(session).create_scene(project_id, chapter_id, payload or {}),
        actor_ref=_operator(request),
    )
    headers = {"X-Idempotency-Status": status} if status else {}
    return ok(result, req_id=_req_id(request), headers=headers)


@router.patch("/api/v2/projects/{project_id}/catalog/scenes/{scene_id}")
def update_catalog_scene(
    project_id: str,
    scene_id: str,
    payload: dict[str, Any],
    request: Request,
    session: Session = Depends(get_session),
):
    result = CatalogService(session).update_scene(project_id, scene_id, payload or {})
    session.commit()
    return ok(result, req_id=_req_id(request))


@router.post("/api/v2/projects/{project_id}/catalog/scenes/{scene_id}/move")
def move_catalog_scene(
    project_id: str,
    scene_id: str,
    payload: dict[str, Any],
    request: Request,
    session: Session = Depends(get_session),
):
    result = CatalogService(session).move_scene(project_id, scene_id, payload or {})
    session.commit()
    return ok(result, req_id=_req_id(request))


@router.delete("/api/v2/projects/{project_id}/catalog/chapters/{chapter_id}")
def trash_catalog_chapter(
    project_id: str,
    chapter_id: str,
    request: Request,
    session: Session = Depends(get_session),
):
    """章级软删（桥接既有 AuthorLifecycleService trash 机制）。"""
    from novel_system.services.trash import TrashService

    result = TrashService(session).trash_chapter_in_project(project_id, chapter_id, actor_ref=_operator(request))
    session.commit()
    return ok(result, req_id=_req_id(request))


@router.post("/api/v2/projects/{project_id}/catalog/chapters/{chapter_id}/restore")
def restore_catalog_chapter(
    project_id: str,
    chapter_id: str,
    request: Request,
    session: Session = Depends(get_session),
):
    from novel_system.services.trash import TrashService

    result = TrashService(session).restore_entry(f"chapter:{chapter_id}")
    session.commit()
    return ok(result, req_id=_req_id(request))


@router.delete("/api/v2/projects/{project_id}/catalog/scenes/{scene_id}")
def trash_catalog_scene(
    project_id: str,
    scene_id: str,
    request: Request,
    session: Session = Depends(get_session),
):
    """场景级软删（桥接既有 AuthorLifecycleService trash 机制）。"""
    from novel_system.services.trash import TrashService

    result = TrashService(session).trash_scene_in_project(project_id, scene_id, actor_ref=_operator(request))
    session.commit()
    return ok(result, req_id=_req_id(request))


@router.post("/api/v2/projects/{project_id}/catalog/scenes/{scene_id}/restore")
def restore_catalog_scene(
    project_id: str,
    scene_id: str,
    request: Request,
    session: Session = Depends(get_session),
):
    from novel_system.services.trash import TrashService

    result = TrashService(session).restore_entry(f"scene:{scene_id}")
    session.commit()
    return ok(result, req_id=_req_id(request))


@router.post("/api/v2/projects/{project_id}/catalog/import")
def import_catalog(
    project_id: str,
    payload: dict[str, Any],
    request: Request,
    session: Session = Depends(get_session),
    x_admin_token: str | None = Header(default=None, alias="X-Admin-Token"),
):
    client_host = request.client.host if request.client else None
    require_admin_token(x_admin_token, client_host=client_host)
    result = CatalogService(session).import_catalog(project_id, payload or {})
    session.commit()
    return ok(result, req_id=_req_id(request))
