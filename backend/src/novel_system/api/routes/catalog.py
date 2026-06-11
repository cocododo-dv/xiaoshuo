"""FE-ALIGN Phase 3: 目录 API（v2）—— 章节/场景树的唯一真相源。

对应原型 WsCatalog（design/ws-catalog.jsx）；写端点全部要求幂等键（中间件统一拦截）。
import 端点仅供 localStorage 一次性迁移使用，admin token 保护（loopback 免 token）。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Header, Request
from sqlalchemy.orm import Session

from novel_system.api.deps import get_session
from novel_system.api.response import ok
from novel_system.services.catalog import CatalogService
from novel_system.services.system_config import require_admin_token

router = APIRouter(tags=["catalog"])


def _req_id(request: Request):
    return getattr(request.state, "request_id", None)


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
    result = CatalogService(session).create_chapter(project_id, payload or {})
    session.commit()
    return ok(result, req_id=_req_id(request))


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


@router.post("/api/v2/projects/{project_id}/catalog/chapters/{chapter_id}/scenes")
def create_catalog_scene(
    project_id: str,
    chapter_id: str,
    payload: dict[str, Any],
    request: Request,
    session: Session = Depends(get_session),
):
    result = CatalogService(session).create_scene(project_id, chapter_id, payload or {})
    session.commit()
    return ok(result, req_id=_req_id(request))


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
