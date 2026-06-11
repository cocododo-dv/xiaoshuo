"""控制塔路由 — 锚点与交接契约(设计稿 lf6/lf7 塔台化语义)。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from novel_system.api.deps import get_session
from novel_system.api.response import ok
from novel_system.services.longform_tower import LongformTowerService

router = APIRouter(tags=["longform-tower"])


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
    result = LongformTowerService(session).create_anchor(project_id, payload or {})
    session.commit()
    return ok(result, req_id=getattr(request.state, "request_id", None))


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
    result = LongformTowerService(session).create_finding(project_id, chapter_id, payload or {})
    session.commit()
    return ok(result, req_id=getattr(request.state, "request_id", None))


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
