"""控制塔路由 — 锚点与交接契约(设计稿 lf6/lf7 塔台化语义)。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from novel_system.api.deps import get_session
from novel_system.api.response import ok
from novel_system.services.idempotency import execute_with_idempotency
from novel_system.services.longform_tower import LongformTowerService

router = APIRouter(tags=["longform-tower"])


def _operator(request: Request) -> str:
    return getattr(request.state, "operator_ref", None) or "operator"


@router.get("/api/v2/projects/{project_id}/longform/anchors")
def list_tower_anchors(project_id: str, request: Request, session: Session = Depends(get_session)):
    result = LongformTowerService(session).list_anchors(project_id)
    return ok(result, req_id=getattr(request.state, "request_id", None))


@router.post("/api/v2/projects/{project_id}/longform/anchors")
def create_tower_anchor(
    project_id: str,
    payload: dict[str, Any],
    request: Request,
    session: Session = Depends(get_session),
):
    result, status = execute_with_idempotency(
        session,
        idempotency_key=request.headers.get("X-Idempotency-Key"),
        method="POST",
        path_template=f"/api/v2/projects/{project_id}/longform/anchors",
        payload=payload,
        action=lambda: LongformTowerService(session).create_anchor(project_id, payload or {}),
        actor_ref=_operator(request),
    )
    headers = {"X-Idempotency-Status": status} if status else {}
    return ok(result, req_id=getattr(request.state, "request_id", None), headers=headers)


@router.patch("/api/v2/projects/{project_id}/longform/anchors/{anchor_id}")
def update_tower_anchor(
    project_id: str,
    anchor_id: str,
    payload: dict[str, Any],
    request: Request,
    session: Session = Depends(get_session),
):
    result = LongformTowerService(session).update_anchor(project_id, anchor_id, payload or {})
    session.commit()
    return ok(result, req_id=getattr(request.state, "request_id", None))


@router.get("/api/v2/projects/{project_id}/longform/chapters/{chapter_id}/contract")
def get_chapter_contract(
    project_id: str,
    chapter_id: str,
    request: Request,
    session: Session = Depends(get_session),
):
    result = LongformTowerService(session).get_or_create_contract(project_id, chapter_id)
    session.commit()
    return ok(result, req_id=getattr(request.state, "request_id", None))


@router.put("/api/v2/projects/{project_id}/longform/chapters/{chapter_id}/contract")
def update_chapter_contract(
    project_id: str,
    chapter_id: str,
    payload: dict[str, Any],
    request: Request,
    session: Session = Depends(get_session),
):
    result = LongformTowerService(session).update_constraints(project_id, chapter_id, payload or {})
    session.commit()
    return ok(result, req_id=getattr(request.state, "request_id", None))


@router.post("/api/v2/projects/{project_id}/longform/chapters/{chapter_id}/contract/transition")
def transition_chapter_contract(
    project_id: str,
    chapter_id: str,
    payload: dict[str, Any],
    request: Request,
    session: Session = Depends(get_session),
):
    result = LongformTowerService(session).transition_contract(project_id, chapter_id, payload or {})
    session.commit()
    return ok(result, req_id=getattr(request.state, "request_id", None))


@router.get("/api/v2/projects/{project_id}/longform/chapters/{chapter_id}/audit-receipt")
def get_chapter_audit_receipt(project_id: str, chapter_id: str, request: Request, session: Session = Depends(get_session)):
    """FE-ALIGN H2：章级审计回执（契约+产出+锚点在场确定性扫描，无 LLM）。"""
    result = LongformTowerService(session).audit_receipt(project_id, chapter_id)
    session.commit()  # get_or_create_contract 可能补建契约行
    return ok(result, req_id=getattr(request.state, "request_id", None))


@router.get("/api/v2/projects/{project_id}/longform/audit")
def list_project_audit(
    project_id: str,
    request: Request,
    session: Session = Depends(get_session),
):
    """FE-ALIGN P7：项目级审计清单（lf7 桥 ruled/pending 缓存数据源）。"""
    result = LongformTowerService(session).list_all_findings(project_id)
    return ok(result, req_id=getattr(request.state, "request_id", None))


@router.get("/api/v2/projects/{project_id}/longform/chapters/{chapter_id}/audit")
def list_chapter_audit(
    project_id: str,
    chapter_id: str,
    request: Request,
    session: Session = Depends(get_session),
):
    result = LongformTowerService(session).list_findings(project_id, chapter_id)
    return ok(result, req_id=getattr(request.state, "request_id", None))


@router.post("/api/v2/projects/{project_id}/longform/chapters/{chapter_id}/audit")
def create_chapter_audit_finding(
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
        path_template=f"/api/v2/projects/{project_id}/longform/chapters/{chapter_id}/audit",
        payload=payload,
        action=lambda: LongformTowerService(session).create_finding(project_id, chapter_id, payload or {}),
        actor_ref=_operator(request),
    )
    headers = {"X-Idempotency-Status": status} if status else {}
    return ok(result, req_id=getattr(request.state, "request_id", None), headers=headers)


@router.post("/api/v2/projects/{project_id}/longform/audit/{finding_id}/adjudicate")
def adjudicate_chapter_audit_finding(
    project_id: str,
    finding_id: str,
    payload: dict[str, Any],
    request: Request,
    session: Session = Depends(get_session),
):
    result = LongformTowerService(session).adjudicate_finding(project_id, finding_id, payload or {})
    session.commit()
    return ok(result, req_id=getattr(request.state, "request_id", None))


@router.post("/api/v2/projects/{project_id}/longform/chapters/{chapter_id}/audit/adjudicate-draft")
def adjudicate_chapter_draft(
    project_id: str,
    chapter_id: str,
    request: Request,
    payload: dict[str, Any] | None = None,
    session: Session = Depends(get_session),
):
    """FE-ALIGN P2(D13)：章级「违约级判定」——草稿 vs 交接契约 LLM 比对，产 drift findings；
    LLM 关闭时诚实降级（只声明检出/未检出，不机器判违约）。"""
    result, status = execute_with_idempotency(
        session,
        idempotency_key=request.headers.get("X-Idempotency-Key"),
        method="POST",
        path_template=f"/api/v2/projects/{project_id}/longform/chapters/{chapter_id}/audit/adjudicate-draft",
        payload=payload or {},
        action=lambda: LongformTowerService(session).adjudicate_draft(project_id, chapter_id),
        actor_ref=_operator(request),
    )
    headers = {"X-Idempotency-Status": status} if status else {}
    return ok(result, req_id=getattr(request.state, "request_id", None), headers=headers)
