from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator
from sqlalchemy.orm import Session

from novel_system.api.deps import get_session
from novel_system.api.response import ok
from novel_system.services.idempotency import execute_with_idempotency
from novel_system.services.project_backtracks import ProjectBacktrackService
from novel_system.services.projects import (
    OutlinePlannerService,
    ProjectChapterFlowService,
    ProjectService,
    start_project_chapter_run_job_worker,
)

router = APIRouter(tags=["projects"])


class ProjectChapterRunJobRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    offline_demo: StrictBool = False


class ProjectChapterReadConfirmRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    note: str | None = Field(default=None, max_length=1000)


class ProjectChapterApproveFinalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    revision_notes: str | None = Field(default=None, max_length=2000)


class ProjectChapterReopenFinalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    reason: str = Field(min_length=1, max_length=1000)

    @field_validator("reason")
    @classmethod
    def validate_reason(cls, value: str) -> str:
        reason = value.strip()
        if not reason:
            raise ValueError("reason must not be blank")
        return reason


@router.post("/api/v1/projects")
def create_project(payload: dict[str, Any], request: Request, session: Session = Depends(get_session)):
    actor_ref = getattr(request.state, "operator_ref", None) or "operator"
    result, status = execute_with_idempotency(
        session,
        idempotency_key=request.headers.get("X-Idempotency-Key"),
        method="POST",
        path_template="/api/v1/projects",
        payload=payload,
        action=lambda: ProjectService(session).create(payload),
        actor_ref=actor_ref,
    )
    headers = {"X-Idempotency-Status": status} if status else {}
    return ok(result, req_id=getattr(request.state, "request_id", None), headers=headers)


@router.get("/api/v1/projects")
def list_projects(request: Request, session: Session = Depends(get_session)):
    return ok(ProjectService(session).list(), req_id=getattr(request.state, "request_id", None))


@router.get("/api/v1/projects/{project_id}/dashboard")
def project_dashboard(project_id: str, request: Request, session: Session = Depends(get_session)):
    return ok(ProjectService(session).dashboard(project_id), req_id=getattr(request.state, "request_id", None))


@router.get("/api/v1/projects/{project_id}/backtrack-items")
def list_project_backtrack_items(project_id: str, request: Request, session: Session = Depends(get_session)):
    return ok(
        ProjectBacktrackService(session).list(project_id),
        req_id=getattr(request.state, "request_id", None),
    )


@router.post("/api/v1/projects/{project_id}/backtrack-items/{item_id}/resolve")
def resolve_project_backtrack_item(
    project_id: str,
    item_id: str,
    payload: dict[str, Any] | None,
    request: Request,
    session: Session = Depends(get_session),
):
    body = payload or {}
    actor_ref = getattr(request.state, "operator_ref", None) or "operator"
    result, status = execute_with_idempotency(
        session,
        idempotency_key=request.headers.get("X-Idempotency-Key"),
        method="POST",
        path_template="/api/v1/projects/{project_id}/backtrack-items/{item_id}/resolve",
        payload={"project_id": project_id, "item_id": item_id, **body},
        action=lambda: ProjectBacktrackService(session).resolve(project_id, item_id, body),
        actor_ref=actor_ref,
    )
    headers = {"X-Idempotency-Status": status} if status else {}
    return ok(result, req_id=getattr(request.state, "request_id", None), headers=headers)


@router.post("/api/v1/projects/{project_id}/outline-plan")
def generate_outline_plan(
    project_id: str,
    payload: dict[str, Any] | None,
    request: Request,
    session: Session = Depends(get_session),
):
    body = payload or {}
    actor_ref = getattr(request.state, "operator_ref", None) or "operator"
    result, status = execute_with_idempotency(
        session,
        idempotency_key=request.headers.get("X-Idempotency-Key"),
        method="POST",
        path_template="/api/v1/projects/{project_id}/outline-plan",
        payload={"project_id": project_id, **body},
        action=lambda: OutlinePlannerService(session).generate(project_id, body),
        actor_ref=actor_ref,
    )
    headers = {"X-Idempotency-Status": status} if status else {}
    return ok(result, req_id=getattr(request.state, "request_id", None), headers=headers)


@router.post("/api/v1/projects/{project_id}/outline-plan/{plan_id}/approve")
def approve_outline_plan(
    project_id: str,
    plan_id: str,
    payload: dict[str, Any] | None,
    request: Request,
    session: Session = Depends(get_session),
):
    body = payload or {}
    actor_ref = getattr(request.state, "operator_ref", None) or "operator"
    result, status = execute_with_idempotency(
        session,
        idempotency_key=request.headers.get("X-Idempotency-Key"),
        method="POST",
        path_template="/api/v1/projects/{project_id}/outline-plan/{plan_id}/approve",
        payload={"project_id": project_id, "plan_id": plan_id, **body},
        action=lambda: ProjectService(session).approve_outline_plan(project_id, plan_id),
        actor_ref=actor_ref,
    )
    headers = {"X-Idempotency-Status": status} if status else {}
    return ok(result, req_id=getattr(request.state, "request_id", None), headers=headers)


@router.post("/api/v1/projects/{project_id}/chapters/{chapter_id}/run")
def run_project_chapter(
    project_id: str,
    chapter_id: str,
    payload: dict[str, Any] | None,
    request: Request,
    session: Session = Depends(get_session),
):
    body = payload or {}
    actor_ref = getattr(request.state, "operator_ref", None) or "operator"
    result, status = execute_with_idempotency(
        session,
        idempotency_key=request.headers.get("X-Idempotency-Key"),
        method="POST",
        path_template="/api/v1/projects/{project_id}/chapters/{chapter_id}/run",
        payload={"project_id": project_id, "chapter_id": chapter_id, **body},
        action=lambda: ProjectChapterFlowService(session).run_chapter(project_id, chapter_id),
        actor_ref=actor_ref,
    )
    headers = {"X-Idempotency-Status": status} if status else {}
    return ok(result, req_id=getattr(request.state, "request_id", None), headers=headers)


@router.post("/api/v1/projects/{project_id}/chapters/{chapter_id}/run-job")
def run_project_chapter_job(
    project_id: str,
    chapter_id: str,
    request: Request,
    payload: ProjectChapterRunJobRequest | None = None,
    session: Session = Depends(get_session),
):
    offline_demo = payload.offline_demo if payload is not None else False
    result = ProjectChapterFlowService(session).prepare_chapter_run_job(
        project_id,
        chapter_id,
        offline_demo=offline_demo,
    )
    should_start_worker = bool(result.pop("_start_worker", False))
    session.commit()
    if should_start_worker:
        start_project_chapter_run_job_worker(project_id, chapter_id, result["run"]["job_id"])
    return ok(result, req_id=getattr(request.state, "request_id", None))


@router.post("/api/v1/projects/{project_id}/chapters/{chapter_id}/approve-final")
def approve_project_chapter_final(
    project_id: str,
    chapter_id: str,
    request: Request,
    payload: ProjectChapterApproveFinalRequest | None = None,
    session: Session = Depends(get_session),
):
    body = payload.model_dump(mode="json", exclude_unset=True) if payload is not None else {}
    actor_ref = getattr(request.state, "operator_ref", None) or "operator"
    result, status = execute_with_idempotency(
        session,
        idempotency_key=request.headers.get("X-Idempotency-Key"),
        method="POST",
        path_template="/api/v1/projects/{project_id}/chapters/{chapter_id}/approve-final",
        payload={"project_id": project_id, "chapter_id": chapter_id, **body},
        action=lambda: ProjectChapterFlowService(session).approve_final(project_id, chapter_id, body, actor_ref=actor_ref),
        actor_ref=actor_ref,
    )
    headers = {"X-Idempotency-Status": status} if status else {}
    return ok(result, req_id=getattr(request.state, "request_id", None), headers=headers)


@router.post("/api/v1/projects/{project_id}/chapters/{chapter_id}/reopen-final")
def reopen_project_chapter_final(
    project_id: str,
    chapter_id: str,
    payload: ProjectChapterReopenFinalRequest,
    request: Request,
    session: Session = Depends(get_session),
):
    body = payload.model_dump(mode="json")
    actor_ref = getattr(request.state, "operator_ref", None) or "operator"
    result, status = execute_with_idempotency(
        session,
        idempotency_key=request.headers.get("X-Idempotency-Key"),
        method="POST",
        path_template="/api/v1/projects/{project_id}/chapters/{chapter_id}/reopen-final",
        payload={"project_id": project_id, "chapter_id": chapter_id, **body},
        action=lambda: ProjectChapterFlowService(session).reopen_final(
            project_id,
            chapter_id,
            reason=body["reason"],
            actor_ref=actor_ref,
        ),
        actor_ref=actor_ref,
    )
    headers = {"X-Idempotency-Status": status} if status else {}
    return ok(result, req_id=getattr(request.state, "request_id", None), headers=headers)


@router.post("/api/v1/projects/{project_id}/chapters/{chapter_id}/read-confirm")
def confirm_project_chapter_read(
    project_id: str,
    chapter_id: str,
    request: Request,
    payload: ProjectChapterReadConfirmRequest | None = None,
    session: Session = Depends(get_session),
):
    body = payload.model_dump(mode="json", exclude_unset=True) if payload is not None else {}
    actor_ref = getattr(request.state, "operator_ref", None) or "operator"
    result = ProjectChapterFlowService(session).confirm_read(project_id, chapter_id, body, actor_ref=actor_ref)
    session.commit()
    return ok(result, req_id=getattr(request.state, "request_id", None))


@router.post("/api/v1/projects/{project_id}/chapters/{chapter_id}/final-review")
def review_project_chapter_final(
    project_id: str,
    chapter_id: str,
    payload: dict[str, Any] | None,
    request: Request,
    session: Session = Depends(get_session),
):
    body = payload or {}
    actor_ref = getattr(request.state, "operator_ref", None) or "operator"
    result, status = execute_with_idempotency(
        session,
        idempotency_key=request.headers.get("X-Idempotency-Key"),
        method="POST",
        path_template="/api/v1/projects/{project_id}/chapters/{chapter_id}/final-review",
        payload={"project_id": project_id, "chapter_id": chapter_id, **body},
        action=lambda: ProjectChapterFlowService(session).final_review(project_id, chapter_id, body, actor_ref=actor_ref),
        actor_ref=actor_ref,
    )
    headers = {"X-Idempotency-Status": status} if status else {}
    return ok(result, req_id=getattr(request.state, "request_id", None), headers=headers)


@router.post("/api/v1/projects/{project_id}/reference-profiles")
def attach_reference_profile(
    project_id: str,
    payload: dict[str, Any],
    request: Request,
    session: Session = Depends(get_session),
):
    actor_ref = getattr(request.state, "operator_ref", None) or "operator"
    result, status = execute_with_idempotency(
        session,
        idempotency_key=request.headers.get("X-Idempotency-Key"),
        method="POST",
        path_template="/api/v1/projects/{project_id}/reference-profiles",
        payload={"project_id": project_id, **payload},
        action=lambda: ProjectService(session).attach_reference_profile(project_id, str(payload.get("profile_id") or "")),
        actor_ref=actor_ref,
    )
    headers = {"X-Idempotency-Status": status} if status else {}
    return ok(result, req_id=getattr(request.state, "request_id", None), headers=headers)
