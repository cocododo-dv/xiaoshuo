"""成本看板端点（结果闭环治理设计 §5.8/§6.3/§10，Wave 6）。

GET /api/v2/projects/{project_id}/cost-summary —— 场景/章节/全书级 token 与费用聚合。
默认返回项目级；``?scene_id=`` / ``?chapter_id=`` 下钻。只读，不改任何状态。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from novel_system.api.deps import get_session
from novel_system.api.response import ok
from novel_system.services import cost_aggregation

router = APIRouter(tags=["cost"])


@router.get("/api/v2/projects/{project_id}/cost-summary")
def project_cost_summary(
    project_id: str,
    request: Request,
    scene_id: str | None = None,
    chapter_id: str | None = None,
    session: Session = Depends(get_session),
):
    if scene_id:
        payload = {"level": "scene", "summary": cost_aggregation.scene_cost(session, scene_id)}
    elif chapter_id:
        payload = {"level": "chapter", "summary": cost_aggregation.chapter_cost(session, chapter_id)}
    else:
        payload = {"level": "project", "summary": cost_aggregation.project_cost(session, project_id)}
    return ok(payload, req_id=getattr(request.state, "request_id", None))
