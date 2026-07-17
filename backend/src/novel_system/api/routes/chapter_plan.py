"""章节编排 LLM 规划 API（v2，挂 catalog 路由族）。

设计文档：docs/chapter-arrangement-llm-design-2026-07-16.md §5。
- 蓝图三端点：GET/PUT architecture + POST architecture/generate（幂等）
- 三通道：POST plan/candidates | plan/fill | plan/review（单次结构化咨询调用，
  与雪花 generate/fe-candidates 同级别，不套幂等——重生成是合法诉求；
  计量/审计由 execute_accounted_call 承担）
- POST plan/apply（幂等）：补丁经服务端 sanitize 后单事务原子回写目录。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from novel_system.api.deps import get_session
from novel_system.api.response import ok
from novel_system.services.chapter_plan_llm import ChapterPlanService
from novel_system.services.idempotency import execute_with_idempotency

router = APIRouter(tags=["chapter-plan"])


def _req_id(request: Request):
    return getattr(request.state, "request_id", None)


def _operator(request: Request) -> str:
    return getattr(request.state, "operator_ref", None) or "operator"


@router.get("/api/v2/projects/{project_id}/catalog/chapters/{chapter_id}/architecture")
def get_chapter_architecture(
    project_id: str,
    chapter_id: str,
    request: Request,
    session: Session = Depends(get_session),
):
    result = ChapterPlanService(session).get_architecture(project_id, chapter_id)
    return ok(result, req_id=_req_id(request))


@router.put("/api/v2/projects/{project_id}/catalog/chapters/{chapter_id}/architecture")
def put_chapter_architecture(
    project_id: str,
    chapter_id: str,
    payload: dict[str, Any],
    request: Request,
    session: Session = Depends(get_session),
):
    result = ChapterPlanService(session).put_architecture(
        project_id,
        chapter_id,
        payload or {},
        actor_ref=_operator(request),
    )
    return ok(result, req_id=_req_id(request))


@router.post("/api/v2/projects/{project_id}/catalog/chapters/{chapter_id}/architecture/generate")
def generate_chapter_architecture(
    project_id: str,
    chapter_id: str,
    payload: dict[str, Any] | None,
    request: Request,
    session: Session = Depends(get_session),
):
    result, status = execute_with_idempotency(
        session,
        idempotency_key=request.headers.get("X-Idempotency-Key"),
        method="POST",
        path_template=f"/api/v2/projects/{project_id}/catalog/chapters/{chapter_id}/architecture/generate",
        payload=payload or {},
        action=lambda: ChapterPlanService(session).generate_architecture(
            project_id,
            chapter_id,
            actor_ref=_operator(request),
        ),
        actor_ref=_operator(request),
    )
    headers = {"X-Idempotency-Status": status} if status else {}
    return ok(result, req_id=_req_id(request), headers=headers)


@router.post("/api/v2/projects/{project_id}/catalog/chapters/{chapter_id}/plan/candidates")
def chapter_plan_candidates(
    project_id: str,
    chapter_id: str,
    payload: dict[str, Any] | None,
    request: Request,
    session: Session = Depends(get_session),
):
    result = ChapterPlanService(session).candidates(project_id, chapter_id, payload or {})
    return ok(result, req_id=_req_id(request))


@router.post("/api/v2/projects/{project_id}/catalog/chapters/{chapter_id}/plan/fill")
def chapter_plan_fill(
    project_id: str,
    chapter_id: str,
    payload: dict[str, Any] | None,
    request: Request,
    session: Session = Depends(get_session),
):
    result = ChapterPlanService(session).fill(project_id, chapter_id, payload or {})
    return ok(result, req_id=_req_id(request))


@router.post("/api/v2/projects/{project_id}/catalog/chapters/{chapter_id}/plan/review")
def chapter_plan_review(
    project_id: str,
    chapter_id: str,
    request: Request,
    session: Session = Depends(get_session),
):
    result = ChapterPlanService(session).review(project_id, chapter_id)
    return ok(result, req_id=_req_id(request))


@router.post("/api/v2/projects/{project_id}/catalog/chapters/{chapter_id}/plan/apply")
def chapter_plan_apply(
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
        path_template=f"/api/v2/projects/{project_id}/catalog/chapters/{chapter_id}/plan/apply",
        payload=payload or {},
        action=lambda: ChapterPlanService(session).apply(
            project_id,
            chapter_id,
            payload or {},
            actor_ref=_operator(request),
        ),
        actor_ref=_operator(request),
    )
    headers = {"X-Idempotency-Status": status} if status else {}
    return ok(result, req_id=_req_id(request), headers=headers)
