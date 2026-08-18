from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from novel_system.api.deps import get_session
from novel_system.api.mutations import optional_idempotent_response
from novel_system.api.request_types import EmptyRequest
from novel_system.api.response import ok
from novel_system.api.snowflake_requests import (
    LegacySnowflakeArtifactUpdateRequest,
    LegacySnowflakeStepGenerateRequest,
)
from novel_system.services.idempotency import execute_with_idempotency
from novel_system.services.snowflake_planner import SnowflakePlannerService

router = APIRouter(tags=["snowflake"])


@router.get("/api/v1/projects/{project_id}/snowflake")
def snowflake_state(project_id: str, request: Request, session: Session = Depends(get_session)):
    return ok(SnowflakePlannerService(session).state(project_id), req_id=getattr(request.state, "request_id", None))


@router.post("/api/v1/projects/{project_id}/snowflake/steps/{step_key}/generate")
def generate_snowflake_step(
    project_id: str,
    step_key: str,
    request: Request,
    payload: LegacySnowflakeStepGenerateRequest | None = None,
    session: Session = Depends(get_session),
):
    body = payload.model_dump(mode="json", exclude_unset=True) if payload else {}
    actor_ref = getattr(request.state, "operator_ref", None) or "operator"
    result, status = execute_with_idempotency(
        session,
        idempotency_key=request.headers.get("X-Idempotency-Key"),
        method="POST",
        path_template="/api/v1/projects/{project_id}/snowflake/steps/{step_key}/generate",
        payload={"project_id": project_id, "step_key": step_key, **body},
        action=lambda: SnowflakePlannerService(session).generate(project_id, step_key, body),
        actor_ref=actor_ref,
    )
    headers = {"X-Idempotency-Status": status} if status else {}
    return ok(result, req_id=getattr(request.state, "request_id", None), headers=headers)


@router.patch("/api/v1/projects/{project_id}/snowflake/artifacts/{artifact_id}")
def update_snowflake_artifact(
    project_id: str,
    artifact_id: str,
    payload: LegacySnowflakeArtifactUpdateRequest,
    request: Request,
    session: Session = Depends(get_session),
):
    body = payload.model_dump(mode="json", exclude_unset=True)
    return optional_idempotent_response(
        request,
        session,
        method="PATCH",
        path_template="/api/v1/projects/{project_id}/snowflake/artifacts/{artifact_id}",
        payload={"project_id": project_id, "artifact_id": artifact_id, "body": body},
        action=lambda: SnowflakePlannerService(session).update_artifact(project_id, artifact_id, body),
    )


@router.post("/api/v1/projects/{project_id}/snowflake/artifacts/{artifact_id}/approve")
def approve_snowflake_artifact(
    project_id: str,
    artifact_id: str,
    request: Request,
    payload: EmptyRequest | None = None,
    session: Session = Depends(get_session),
):
    body = payload.model_dump(mode="json") if payload else {}
    actor_ref = getattr(request.state, "operator_ref", None) or "operator"
    result, status = execute_with_idempotency(
        session,
        idempotency_key=request.headers.get("X-Idempotency-Key"),
        method="POST",
        path_template="/api/v1/projects/{project_id}/snowflake/artifacts/{artifact_id}/approve",
        payload={"project_id": project_id, "artifact_id": artifact_id, **body},
        action=lambda: SnowflakePlannerService(session).approve(project_id, artifact_id),
        actor_ref=actor_ref,
    )
    headers = {"X-Idempotency-Status": status} if status else {}
    return ok(result, req_id=getattr(request.state, "request_id", None), headers=headers)


@router.post("/api/v1/projects/{project_id}/snowflake/materialize-outline-plan")
def materialize_snowflake_outline_plan(
    project_id: str,
    request: Request,
    payload: EmptyRequest | None = None,
    session: Session = Depends(get_session),
):
    body = payload.model_dump(mode="json") if payload else {}
    actor_ref = getattr(request.state, "operator_ref", None) or "operator"
    result, status = execute_with_idempotency(
        session,
        idempotency_key=request.headers.get("X-Idempotency-Key"),
        method="POST",
        path_template="/api/v1/projects/{project_id}/snowflake/materialize-outline-plan",
        payload={"project_id": project_id, **body},
        action=lambda: SnowflakePlannerService(session).materialize_outline_plan(project_id),
        actor_ref=actor_ref,
    )
    headers = {"X-Idempotency-Status": status} if status else {}
    return ok(result, req_id=getattr(request.state, "request_id", None), headers=headers)
