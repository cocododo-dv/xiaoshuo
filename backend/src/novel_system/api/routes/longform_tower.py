"""控制塔路由 — 锚点与交接契约(设计稿 lf6/lf7 塔台化语义)。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from novel_system.api.deps import get_session
from novel_system.api.longform_tower_requests import (
    LongformAnchorCreateRequest,
    LongformAnchorUpdateRequest,
    LongformAuditFindingAdjudicateRequest,
    LongformAuditFindingCreateRequest,
    LongformContractTransitionRequest,
    LongformContractUpdateRequest,
)
from novel_system.api.mutations import optional_idempotent_response
from novel_system.api.request_types import EmptyRequest
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
    payload: LongformAnchorCreateRequest,
    request: Request,
    session: Session = Depends(get_session),
):
    body = payload.model_dump(mode="json", exclude_unset=True)
    result, status = execute_with_idempotency(
        session,
        idempotency_key=request.headers.get("X-Idempotency-Key"),
        method="POST",
        path_template="/api/v2/projects/{project_id}/longform/anchors",
        payload={"project_id": project_id, "body": body},
        action=lambda: LongformTowerService(session).create_anchor(project_id, body),
        actor_ref=_operator(request),
    )
    headers = {"X-Idempotency-Status": status} if status else {}
    return ok(result, req_id=getattr(request.state, "request_id", None), headers=headers)


@router.patch("/api/v2/projects/{project_id}/longform/anchors/{anchor_id}")
def update_tower_anchor(
    project_id: str,
    anchor_id: str,
    payload: LongformAnchorUpdateRequest,
    request: Request,
    session: Session = Depends(get_session),
):
    body = payload.model_dump(mode="json", exclude_unset=True)
    return optional_idempotent_response(
        request,
        session,
        method="PATCH",
        path_template="/api/v2/projects/{project_id}/longform/anchors/{anchor_id}",
        payload={"project_id": project_id, "anchor_id": anchor_id, "body": body},
        action=lambda: LongformTowerService(session).update_anchor(project_id, anchor_id, body),
    )


@router.get("/api/v2/projects/{project_id}/longform/chapters/{chapter_id}/contract")
def get_chapter_contract(
    project_id: str,
    chapter_id: str,
    request: Request,
    session: Session = Depends(get_session),
):
    result = LongformTowerService(session).get_contract(project_id, chapter_id)
    return ok(result, req_id=getattr(request.state, "request_id", None))


@router.put("/api/v2/projects/{project_id}/longform/chapters/{chapter_id}/contract")
def update_chapter_contract(
    project_id: str,
    chapter_id: str,
    payload: LongformContractUpdateRequest,
    request: Request,
    session: Session = Depends(get_session),
):
    body = payload.model_dump(mode="json", exclude_unset=True)
    return optional_idempotent_response(
        request,
        session,
        method="PUT",
        path_template="/api/v2/projects/{project_id}/longform/chapters/{chapter_id}/contract",
        payload={"project_id": project_id, "chapter_id": chapter_id, "body": body},
        action=lambda: LongformTowerService(session).update_constraints(
            project_id,
            chapter_id,
            body,
            actor_ref=_operator(request),
        ),
    )


@router.post("/api/v2/projects/{project_id}/longform/chapters/{chapter_id}/contract/transition")
def transition_chapter_contract(
    project_id: str,
    chapter_id: str,
    payload: LongformContractTransitionRequest,
    request: Request,
    session: Session = Depends(get_session),
):
    body = payload.model_dump(mode="json", exclude_unset=True)
    return optional_idempotent_response(
        request,
        session,
        method="POST",
        path_template="/api/v2/projects/{project_id}/longform/chapters/{chapter_id}/contract/transition",
        payload={"project_id": project_id, "chapter_id": chapter_id, "body": body},
        action=lambda: LongformTowerService(session).transition_contract(project_id, chapter_id, body),
    )


@router.get("/api/v2/projects/{project_id}/longform/chapters/{chapter_id}/audit-receipt")
def get_chapter_audit_receipt(project_id: str, chapter_id: str, request: Request, session: Session = Depends(get_session)):
    """FE-ALIGN H2：章级审计回执（契约+产出+锚点在场确定性扫描，无 LLM）。"""
    result = LongformTowerService(session).audit_receipt(project_id, chapter_id)
    return ok(result, req_id=getattr(request.state, "request_id", None))


@router.post("/api/v2/projects/{project_id}/longform/derive-structure")
def derive_tower_structure(
    project_id: str,
    request: Request,
    payload: EmptyRequest | None = None,
    session: Session = Depends(get_session),
):
    """FE-ALIGN P3：从雪花场景规划确定性派生故事线/悬念债锚点（0 LLM、幂等），
    让非演示作品的控制塔也能显示真实结构。"""
    result, status = execute_with_idempotency(
        session,
        idempotency_key=request.headers.get("X-Idempotency-Key"),
        method="POST",
        path_template="/api/v2/projects/{project_id}/longform/derive-structure",
        payload={
            "project_id": project_id,
            "body": payload.model_dump(mode="json") if payload else {},
        },
        action=lambda: LongformTowerService(session).derive_structure(project_id),
        actor_ref=_operator(request),
    )
    headers = {"X-Idempotency-Status": status} if status else {}
    return ok(result, req_id=getattr(request.state, "request_id", None), headers=headers)


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
    payload: LongformAuditFindingCreateRequest,
    request: Request,
    session: Session = Depends(get_session),
):
    body = payload.model_dump(mode="json", exclude_unset=True)
    result, status = execute_with_idempotency(
        session,
        idempotency_key=request.headers.get("X-Idempotency-Key"),
        method="POST",
        path_template="/api/v2/projects/{project_id}/longform/chapters/{chapter_id}/audit",
        payload={"project_id": project_id, "chapter_id": chapter_id, "body": body},
        action=lambda: LongformTowerService(session).create_finding(project_id, chapter_id, body),
        actor_ref=_operator(request),
    )
    headers = {"X-Idempotency-Status": status} if status else {}
    return ok(result, req_id=getattr(request.state, "request_id", None), headers=headers)


@router.post("/api/v2/projects/{project_id}/longform/audit/{finding_id}/adjudicate")
def adjudicate_chapter_audit_finding(
    project_id: str,
    finding_id: str,
    payload: LongformAuditFindingAdjudicateRequest,
    request: Request,
    session: Session = Depends(get_session),
):
    body = payload.model_dump(mode="json", exclude_unset=True)
    return optional_idempotent_response(
        request,
        session,
        method="POST",
        path_template="/api/v2/projects/{project_id}/longform/audit/{finding_id}/adjudicate",
        payload={"project_id": project_id, "finding_id": finding_id, "body": body},
        action=lambda: LongformTowerService(session).adjudicate_finding(project_id, finding_id, body),
    )


@router.post("/api/v2/projects/{project_id}/longform/chapters/{chapter_id}/audit/adjudicate-draft")
def adjudicate_chapter_draft(
    project_id: str,
    chapter_id: str,
    request: Request,
    payload: EmptyRequest | None = None,
    session: Session = Depends(get_session),
):
    """FE-ALIGN P2(D13)：章级「违约级判定」——草稿 vs 交接契约 LLM 比对，产 drift findings；
    LLM 关闭时诚实降级（只声明检出/未检出，不机器判违约）。"""
    result, status = execute_with_idempotency(
        session,
        idempotency_key=request.headers.get("X-Idempotency-Key"),
        method="POST",
        path_template="/api/v2/projects/{project_id}/longform/chapters/{chapter_id}/audit/adjudicate-draft",
        payload={
            "project_id": project_id,
            "chapter_id": chapter_id,
            "body": payload.model_dump(mode="json") if payload else {},
        },
        action=lambda: LongformTowerService(session).adjudicate_draft(project_id, chapter_id),
        actor_ref=_operator(request),
    )
    headers = {"X-Idempotency-Status": status} if status else {}
    return ok(result, req_id=getattr(request.state, "request_id", None), headers=headers)
