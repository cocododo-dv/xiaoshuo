from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator
from sqlalchemy.orm import Session

from novel_system.api.deps import get_session
from novel_system.api.mutations import optional_idempotent_response
from novel_system.api.project_requests import ProjectCreateRequest
from novel_system.api.request_types import EmptyRequest
from novel_system.api.response import ok
from novel_system.services.idempotency import execute_with_idempotency, execute_with_optional_idempotency
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


class ProjectBacktrackResolveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    resolution_note: str | None = Field(default=None, max_length=4000)


class ProjectOutlinePlanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    target_chapter_count: int | None = Field(default=None, ge=1, le=80)


class ProjectChapterSceneDecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    scene_id: str | None = Field(default=None, max_length=255)
    # The service owns the decision vocabulary and its stable domain error.
    decision: str | None = Field(default=None, max_length=64)
    note: str | None = Field(default=None, max_length=2000)


class ProjectChapterFinalReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    # Keep optional so an omitted body retains the existing default-approve
    # behavior and invalid values retain CHAPTER_FINAL_REVIEW_DECISION_INVALID.
    decision: str | None = Field(default=None, max_length=64)
    revision_notes: str | None = Field(default=None, max_length=2000)
    scene_decisions: list[ProjectChapterSceneDecisionRequest] = Field(
        default_factory=list,
        max_length=200,
    )


class ProjectReferenceProfileAttachRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    profile_id: str = Field(min_length=1, max_length=255)


@router.post("/api/v1/projects")
def create_project(payload: ProjectCreateRequest, request: Request, session: Session = Depends(get_session)):
    body = payload.model_dump(mode="json", exclude_unset=True)
    actor_ref = getattr(request.state, "operator_ref", None) or "operator"
    result, status = execute_with_idempotency(
        session,
        idempotency_key=request.headers.get("X-Idempotency-Key"),
        method="POST",
        path_template="/api/v1/projects",
        payload=body,
        action=lambda: ProjectService(session).create(body),
        actor_ref=actor_ref,
    )
    headers = {"X-Idempotency-Status": status} if status else {}
    return ok(result, req_id=getattr(request.state, "request_id", None), headers=headers)


@router.get("/api/v1/projects")
def list_projects(request: Request, session: Session = Depends(get_session)):
    return ok(
        ProjectService(session).list(),
        req_id=getattr(request.state, "request_id", None),
    )


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
    request: Request,
    payload: ProjectBacktrackResolveRequest | None = None,
    session: Session = Depends(get_session),
):
    body = payload.model_dump(mode="json", exclude_unset=True) if payload is not None else {}
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
    request: Request,
    payload: ProjectOutlinePlanRequest | None = None,
    session: Session = Depends(get_session),
):
    body = payload.model_dump(mode="json", exclude_unset=True) if payload is not None else {}
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
    request: Request,
    payload: EmptyRequest | None = None,
    session: Session = Depends(get_session),
):
    body = payload.model_dump(mode="json") if payload is not None else {}
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
    request: Request,
    payload: EmptyRequest | None = None,
    session: Session = Depends(get_session),
):
    body = payload.model_dump(mode="json") if payload is not None else {}
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
    body = payload.model_dump(mode="json") if payload is not None else {"offline_demo": False}
    job_to_start: str | None = None

    def prepare() -> dict[str, Any]:
        nonlocal job_to_start
        result = ProjectChapterFlowService(session).prepare_chapter_run_job(
            project_id,
            chapter_id,
            offline_demo=bool(body["offline_demo"]),
        )
        if bool(result.pop("_start_worker", False)):
            job_to_start = result["run"]["job_id"]
        return result

    result, status = execute_with_optional_idempotency(
        session,
        idempotency_key=request.headers.get("X-Idempotency-Key"),
        method="POST",
        path_template="/api/v1/projects/{project_id}/chapters/{chapter_id}/run-job",
        payload={"project_id": project_id, "chapter_id": chapter_id, "body": body},
        action=prepare,
        actor_ref=getattr(request.state, "operator_ref", None) or "operator",
    )
    # The closure is populated only when this request executed the action. A
    # durable replay returns the cached response without launching another worker.
    if job_to_start is not None:
        start_project_chapter_run_job_worker(project_id, chapter_id, job_to_start)
    headers = {"X-Idempotency-Status": status} if status else {}
    return ok(result, req_id=getattr(request.state, "request_id", None), headers=headers)


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
    return optional_idempotent_response(
        request,
        session,
        method="POST",
        path_template="/api/v1/projects/{project_id}/chapters/{chapter_id}/read-confirm",
        payload={"project_id": project_id, "chapter_id": chapter_id, "body": body},
        action=lambda: ProjectChapterFlowService(session).confirm_read(
            project_id, chapter_id, body, actor_ref=actor_ref
        ),
    )


@router.post("/api/v1/projects/{project_id}/chapters/{chapter_id}/final-review")
def review_project_chapter_final(
    project_id: str,
    chapter_id: str,
    request: Request,
    payload: ProjectChapterFinalReviewRequest | None = None,
    session: Session = Depends(get_session),
):
    body = payload.model_dump(mode="json", exclude_unset=True) if payload is not None else {}
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
    payload: ProjectReferenceProfileAttachRequest,
    request: Request,
    session: Session = Depends(get_session),
):
    body = payload.model_dump(mode="json")
    actor_ref = getattr(request.state, "operator_ref", None) or "operator"
    result, status = execute_with_idempotency(
        session,
        idempotency_key=request.headers.get("X-Idempotency-Key"),
        method="POST",
        path_template="/api/v1/projects/{project_id}/reference-profiles",
        payload={"project_id": project_id, **body},
        action=lambda: ProjectService(session).attach_reference_profile(project_id, body["profile_id"]),
        actor_ref=actor_ref,
    )
    headers = {"X-Idempotency-Status": status} if status else {}
    return ok(result, req_id=getattr(request.state, "request_id", None), headers=headers)
