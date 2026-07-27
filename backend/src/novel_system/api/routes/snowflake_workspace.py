from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from novel_system.api.deps import get_session
from novel_system.api.response import ok
from novel_system.services.idempotency import execute_with_idempotency
from novel_system.services.snowflake_chaptering import SnowflakeChapteringService
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


@router.post("/api/v2/projects/{project_id}/snowflake-workspace/steps/{step_key}/fe-candidates")
def generate_workspace_step_fe_candidates(
    project_id: str,
    step_key: str,
    payload: dict[str, Any] | None,
    request: Request,
    session: Session = Depends(get_session),
):
    result = SnowflakeWorkspaceService(session).fe_step_candidates(project_id, step_key, payload or {})
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


@router.get("/api/v2/projects/{project_id}/snowflake-workspace/steps/{step_key}/history")
def get_workspace_step_history(
    project_id: str,
    step_key: str,
    request: Request,
    include_draft: bool = False,
    session: Session = Depends(get_session),
):
    return ok(
        SnowflakeWorkspaceService(session).step_history(project_id, step_key, include_draft=include_draft),
        req_id=getattr(request.state, "request_id", None),
    )


@router.post("/api/v2/projects/{project_id}/snowflake-workspace/steps/{step_key}/restore")
def restore_workspace_step(
    project_id: str,
    step_key: str,
    payload: dict[str, Any] | None,
    request: Request,
    session: Session = Depends(get_session),
):
    result = SnowflakeWorkspaceService(session).restore_step(project_id, step_key, payload or {})
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


@router.post("/api/v2/projects/{project_id}/snowflake-workspace/steps/{step_key}/accept-stale")
def accept_workspace_stale_step(
    project_id: str,
    step_key: str,
    payload: dict[str, Any] | None,
    request: Request,
    session: Session = Depends(get_session),
):
    actor_ref = getattr(request.state, "operator_ref", None) or "operator"
    result = SnowflakeWorkspaceService(session).accept_stale_step(project_id, step_key, payload or {}, actor_ref=actor_ref)
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


@router.post("/api/v2/projects/{project_id}/snowflake-workspace/scenes/accept-stale")
def accept_workspace_stale_scenes(
    project_id: str,
    payload: dict[str, Any] | None,
    request: Request,
    session: Session = Depends(get_session),
):
    actor_ref = getattr(request.state, "operator_ref", None) or "operator"
    result = SnowflakeWorkspaceService(session).accept_stale_scenes(project_id, payload or {}, actor_ref=actor_ref)
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
        action=lambda: SnowflakeWorkspaceService(session).materialize(project_id, body, actor_ref=actor_ref),
        actor_ref=actor_ref,
    )
    headers = {"X-Idempotency-Status": status} if status else {}
    return ok(result, req_id=getattr(request.state, "request_id", None), headers=headers)


@router.post("/api/v2/projects/{project_id}/snowflake-workspace/chapter-plan/preview")
def preview_chapter_plan(
    project_id: str,
    payload: dict[str, Any] | None,
    request: Request,
    session: Session = Depends(get_session),
):
    """分章预览：**分章方案**只读推演，不落库。策略 spine_anchor / even / keep_current。

    「不落库」指的是这次推演算出来的归属——作者没在面板上确认之前，一场都不会按它改。

    但这个端点不是零副作用的：``ensure_chapter_plans`` 会为还没有章表行的项目补建
    ``SnowflakeChapterPlan``，并把**已经是既成事实**的归属绑上去（目录里的 ChapterGoal
    或场景行自带的 chapter_id —— 那是系统已经知道的事，不是待决策项），所以要 commit。
    历史项目第一次打开面板时，因此会看到归属从「未分章」变成实际章数，这是补录不是决策。
    """
    result = SnowflakeChapteringService(session).preview(project_id, payload or {})
    session.commit()
    return ok(result, req_id=getattr(request.state, "request_id", None))


@router.post("/api/v2/projects/{project_id}/snowflake-workspace/chapter-plan/suggest")
def suggest_chapter_plan(
    project_id: str,
    payload: dict[str, Any] | None,
    request: Request,
    session: Session = Depends(get_session),
):
    """让 LLM 给一份分章建议（只读，不落库）。

    fail-closed：LLM 没配好就 409 + author_action。作者点的是「让 AI 建议」，拿一份
    规则算出来的东西冒充建议是撒谎 —— 规则分章本来就以 spine_anchor 策略摆在面板上。
    """
    result = SnowflakeChapteringService(session).suggest(project_id, payload or {})
    session.commit()
    return ok(result, req_id=getattr(request.state, "request_id", None))


@router.patch("/api/v2/projects/{project_id}/snowflake-workspace/chapter-plan")
def save_chapter_plan(
    project_id: str,
    payload: dict[str, Any] | None,
    request: Request,
    session: Session = Depends(get_session),
):
    actor_ref = getattr(request.state, "operator_ref", None) or "operator"
    service = SnowflakeWorkspaceService(session)
    saved = SnowflakeChapteringService(session).save(project_id, payload or {}, actor_ref=actor_ref)
    result = {**saved, "workspace": service.workspace(project_id)}
    session.commit()
    return ok(result, req_id=getattr(request.state, "request_id", None))


@router.post(
    "/api/v2/projects/{project_id}/snowflake-workspace/orphaned-scenes/{scene_plan_id}/resolve"
)
def resolve_orphaned_scene(
    project_id: str,
    scene_plan_id: str,
    payload: dict[str, Any] | None,
    request: Request,
    session: Session = Depends(get_session),
):
    """处置一个孤儿场：``action`` = discard（正文也进回收站）/ keep（正文留在目录里）。

    没有这个端点时分章面板的 blocker 是死结——它让作者「先决定是一并删除还是保留」，
    但界面上不存在这两个决定，「确认分章」按钮从此再也点不动。
    """
    actor_ref = getattr(request.state, "operator_ref", None) or "operator"
    action = str((payload or {}).get("action") or "").strip()
    resolved = SnowflakeChapteringService(session).resolve_orphan(
        project_id, scene_plan_id, action=action, actor_ref=actor_ref
    )
    result = {**resolved, "workspace": SnowflakeWorkspaceService(session).workspace(project_id)}
    session.commit()
    return ok(result, req_id=getattr(request.state, "request_id", None))


@router.post("/api/v2/projects/{project_id}/snowflake-workspace/resync")
def resync_workspace_scenes(
    project_id: str,
    payload: dict[str, Any] | None,
    request: Request,
    session: Session = Depends(get_session),
):
    actor_ref = getattr(request.state, "operator_ref", None) or "operator"
    result = SnowflakeWorkspaceService(session).resync_materialized_scenes(
        project_id,
        payload or {},
        actor_ref=actor_ref,
    )
    session.commit()
    return ok(result, req_id=getattr(request.state, "request_id", None))


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
