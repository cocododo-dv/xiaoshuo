"""FE-ALIGN Phase 4: 回收站端点（v2）。

- DELETE /api/v2/projects/{id}            整部软删（进回收站）
- POST   /api/v2/projects/{id}/restore    整部恢复
- GET    /api/v2/trash?project_id=…       三级统一列表（全局作品桶 + 作品内章/场景桶）
- POST   /api/v2/trash/{entry_id}/restore 按条目恢复
- DELETE /api/v2/trash/{entry_id}         永久清除（D3：仅手动）
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from novel_system.api.deps import get_session
from novel_system.api.request_types import EmptyRequest
from novel_system.api.response import ok
from novel_system.services.idempotency import execute_with_optional_idempotency
from novel_system.services.trash import TrashService

router = APIRouter(tags=["trash"])


def _req_id(request: Request):
    return getattr(request.state, "request_id", None)


def _actor(request: Request) -> str:
    return getattr(request.state, "operator_ref", None) or "operator"


def _mutation_response(
    request: Request,
    session: Session,
    *,
    method: str,
    path_template: str,
    payload: dict,
    action,
):
    result, status = execute_with_optional_idempotency(
        session,
        idempotency_key=request.headers.get("X-Idempotency-Key"),
        method=method,
        path_template=path_template,
        payload=payload,
        action=action,
        actor_ref=_actor(request),
    )
    headers = {"X-Idempotency-Status": status} if status else {}
    return ok(result, req_id=_req_id(request), headers=headers)


@router.delete("/api/v2/projects/{project_id}")
def trash_project(
    project_id: str,
    request: Request,
    payload: EmptyRequest | None = None,
    session: Session = Depends(get_session),
):
    return _mutation_response(
        request,
        session,
        method="DELETE",
        path_template="/api/v2/projects/{project_id}",
        payload={"project_id": project_id},
        action=lambda: TrashService(session).trash_project(project_id, actor_ref=_actor(request)),
    )


@router.post("/api/v2/projects/{project_id}/restore")
def restore_project(
    project_id: str,
    request: Request,
    payload: EmptyRequest | None = None,
    session: Session = Depends(get_session),
):
    return _mutation_response(
        request,
        session,
        method="POST",
        path_template="/api/v2/projects/{project_id}/restore",
        payload={"project_id": project_id},
        action=lambda: TrashService(session).restore_project(project_id),
    )


@router.get("/api/v2/trash")
def list_trash(request: Request, project_id: str | None = None, session: Session = Depends(get_session)):
    return ok(TrashService(session).list_trash(project_id), req_id=_req_id(request))


@router.post("/api/v2/trash/{entry_id}/restore")
def restore_trash_entry(
    entry_id: str,
    request: Request,
    payload: EmptyRequest | None = None,
    session: Session = Depends(get_session),
):
    return _mutation_response(
        request,
        session,
        method="POST",
        path_template="/api/v2/trash/{entry_id}/restore",
        payload={"entry_id": entry_id},
        action=lambda: TrashService(session).restore_entry(entry_id, actor_ref=_actor(request)),
    )


@router.delete("/api/v2/trash/{entry_id}")
def purge_trash_entry(
    entry_id: str,
    request: Request,
    payload: EmptyRequest | None = None,
    session: Session = Depends(get_session),
):
    return _mutation_response(
        request,
        session,
        method="DELETE",
        path_template="/api/v2/trash/{entry_id}",
        payload={"entry_id": entry_id},
        action=lambda: TrashService(session).purge_entry(entry_id),
    )
