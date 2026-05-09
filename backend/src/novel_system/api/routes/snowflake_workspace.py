from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from novel_system.api.deps import get_session
from novel_system.api.response import ok
from novel_system.services.idempotency import execute_with_idempotency
from novel_system.services.snowflake_workspace import SnowflakeWorkspaceService

router = APIRouter(tags=["snowflake-workspace"])


@router.get("/api/v2/projects")
def list_snowflake_workspace_projects(request: Request, session: Session = Depends(get_session)):
    return ok(
        SnowflakeWorkspaceService(session).list_projects(),
        req_id=getattr(request.state, "request_id", None),
    )


@router.post("/api/v2/projects")
def create_snowflake_workspace_project(
    payload: dict[str, Any],
    request: Request,
    session: Session = Depends(get_session),
):
    actor_ref = getattr(request.state, "operator_ref", None) or "operator"
    result, status = execute_with_idempotency(
        session,
        idempotency_key=request.headers.get("X-Idempotency-Key"),
        method="POST",
        path_template="/api/v2/projects",
        payload=payload,
        action=lambda: SnowflakeWorkspaceService(session).create_project(payload),
        actor_ref=actor_ref,
    )
    headers = {"X-Idempotency-Status": status} if status else {}
    return ok(result, req_id=getattr(request.state, "request_id", None), headers=headers)


@router.get("/api/v2/projects/{project_id}/snowflake-workspace")
def get_snowflake_workspace(project_id: str, request: Request, session: Session = Depends(get_session)):
    return ok(
        SnowflakeWorkspaceService(session).workspace(project_id),
        req_id=getattr(request.state, "request_id", None),
    )


@router.post("/api/v2/projects/{project_id}/snowflake-workspace/steps/{step_key}/generate")
def generate_workspace_step(
    project_id: str,
    step_key: str,
    payload: dict[str, Any] | None,
    request: Request,
    session: Session = Depends(get_session),
):
    result = SnowflakeWorkspaceService(session).generate_step(project_id, step_key, payload or {})
    session.commit()
    return ok(result, req_id=getattr(request.state, "request_id", None))


@router.patch("/api/v2/projects/{project_id}/snowflake-workspace/steps/{step_key}")
def update_workspace_step(
    project_id: str,
    step_key: str,
    payload: dict[str, Any] | None,
    request: Request,
    session: Session = Depends(get_session),
):
    result = SnowflakeWorkspaceService(session).update_step(project_id, step_key, payload or {})
    session.commit()
    return ok(result, req_id=getattr(request.state, "request_id", None))


@router.post("/api/v2/projects/{project_id}/snowflake-workspace/steps/{step_key}/approve")
def approve_workspace_step(
    project_id: str,
    step_key: str,
    payload: dict[str, Any] | None,
    request: Request,
    session: Session = Depends(get_session),
):
    result = SnowflakeWorkspaceService(session).approve_step(project_id, step_key)
    session.commit()
    return ok(result, req_id=getattr(request.state, "request_id", None))


@router.post("/api/v2/projects/{project_id}/snowflake-workspace/assistant")
def request_workspace_assistant(
    project_id: str,
    payload: dict[str, Any] | None,
    request: Request,
    session: Session = Depends(get_session),
):
    result = SnowflakeWorkspaceService(session).request_assistant(project_id, payload or {})
    session.commit()
    return ok(result, req_id=getattr(request.state, "request_id", None))


@router.post("/api/v2/projects/{project_id}/snowflake-workspace/scene-triage/suggest")
def suggest_workspace_scene_triage(
    project_id: str,
    payload: dict[str, Any] | None,
    request: Request,
    session: Session = Depends(get_session),
):
    result = SnowflakeWorkspaceService(session).suggest_scene_triage(project_id, payload or {})
    session.commit()
    return ok(result, req_id=getattr(request.state, "request_id", None))


@router.post("/api/v2/projects/{project_id}/snowflake-workspace/scene-triage")
def save_workspace_scene_triage(
    project_id: str,
    payload: dict[str, Any] | None,
    request: Request,
    session: Session = Depends(get_session),
):
    result = SnowflakeWorkspaceService(session).save_scene_triage(project_id, payload or {})
    session.commit()
    return ok(result, req_id=getattr(request.state, "request_id", None))


@router.patch("/api/v2/projects/{project_id}/snowflake-workspace/scenes/{scene_plan_id}")
def update_workspace_scene_plan(
    project_id: str,
    scene_plan_id: str,
    payload: dict[str, Any] | None,
    request: Request,
    session: Session = Depends(get_session),
):
    result = SnowflakeWorkspaceService(session).update_scene_plan(project_id, scene_plan_id, payload or {})
    session.commit()
    return ok(result, req_id=getattr(request.state, "request_id", None))


@router.post("/api/v2/projects/{project_id}/snowflake-workspace/scene-triage/{triage_id}/apply")
def apply_workspace_scene_triage_repair(
    project_id: str,
    triage_id: str,
    payload: dict[str, Any] | None,
    request: Request,
    session: Session = Depends(get_session),
):
    del payload
    result = SnowflakeWorkspaceService(session).apply_scene_triage_repair(project_id, triage_id)
    session.commit()
    return ok(result, req_id=getattr(request.state, "request_id", None))


@router.post("/api/v2/projects/{project_id}/snowflake-workspace/materialize")
def materialize_workspace_outline(
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
        path_template="/api/v2/projects/{project_id}/snowflake-workspace/materialize",
        payload={"project_id": project_id, **body},
        action=lambda: SnowflakeWorkspaceService(session).materialize(project_id),
        actor_ref=actor_ref,
    )
    headers = {"X-Idempotency-Status": status} if status else {}
    return ok(result, req_id=getattr(request.state, "request_id", None), headers=headers)


@router.post("/api/v2/projects/{project_id}/snowflake-workspace/outline/approve")
def approve_workspace_outline(
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
        path_template="/api/v2/projects/{project_id}/snowflake-workspace/outline/approve",
        payload={"project_id": project_id, **body},
        action=lambda: SnowflakeWorkspaceService(session).approve_outline(project_id),
        actor_ref=actor_ref,
    )
    headers = {"X-Idempotency-Status": status} if status else {}
    return ok(result, req_id=getattr(request.state, "request_id", None), headers=headers)
