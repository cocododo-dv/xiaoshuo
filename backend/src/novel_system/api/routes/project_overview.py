"""FE-ALIGN Phase 2: v2 作品域端点 — profile / writing-stats / dashboard / flow-status。

原型对应：profile = WsWorks 作品档案；dashboard = 主页（续写卡/GOS/雪花进度/近章）；
flow-status = 流程视图聚合；writing-stats = 今日字数/streak（D2 服务端计算）。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from novel_system.api.deps import get_session
from novel_system.api.response import ok
from novel_system.services.project_overview import ProjectOverviewService
from novel_system.services.projects import ProjectService

router = APIRouter(tags=["project-overview"])


@router.patch("/api/v2/projects/{project_id}/profile")
def update_project_profile(
    project_id: str,
    payload: dict[str, Any],
    request: Request,
    session: Session = Depends(get_session),
):
    result = ProjectService(session).update_profile(project_id, payload or {})
    session.commit()
    return ok(result, req_id=getattr(request.state, "request_id", None))


@router.get("/api/v2/projects/{project_id}/writing-stats")
def project_writing_stats(project_id: str, request: Request, session: Session = Depends(get_session)):
    result = ProjectOverviewService(session).writing_stats(project_id)
    return ok(result, req_id=getattr(request.state, "request_id", None))


@router.get("/api/v2/projects/{project_id}/dashboard")
def project_dashboard_v2(project_id: str, request: Request, session: Session = Depends(get_session)):
    result = ProjectOverviewService(session).dashboard(project_id)
    return ok(result, req_id=getattr(request.state, "request_id", None))


@router.get("/api/v2/projects/{project_id}/flow-status")
def project_flow_status(project_id: str, request: Request, session: Session = Depends(get_session)):
    result = ProjectOverviewService(session).flow_status(project_id)
    return ok(result, req_id=getattr(request.state, "request_id", None))
