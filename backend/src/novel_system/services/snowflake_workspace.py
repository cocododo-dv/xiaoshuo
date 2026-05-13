from __future__ import annotations

import uuid
from copy import deepcopy
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from novel_system.db.models import (
    OutlinePlan,
    SnowflakeAssistantTurn,
    SnowflakeCharacterPlan,
    SnowflakeRevisionLink,
    SnowflakeScenePlan,
    SnowflakeSceneTriageItem,
    SnowflakeStepRun,
    StoryCharacter,
    StoryProject,
    utcnow,
)
from novel_system.services.errors import DomainError
from novel_system.services.projects import PLAN_STATUS_PENDING_REVIEW, ProjectService, outline_plan_payload, project_payload
from novel_system.services.snowflake_planner import GATE_STATUSES, SnowflakePlannerService
from novel_system.services.snowflake_steps import (
    MATERIALIZATION_REQUIREMENTS,
    MATERIALIZATION_REQUIRED_STEPS,
    MATERIALIZATION_WARNING_STEPS,
    QUALITY_POLICY,
    SNOWFLAKE_METHOD_VERSION,
    STEP_ORDER,
    default_step_draft,
    diagnose_step_pressure,
    diagnose_scene_detail,
    editor_payload,
    get_step_definition,
    list_step_definitions,
    merge_step_draft,
    step_completeness,
    step_guidance,
)
from novel_system.services.snowflake_workspace_assistant import SnowflakeWorkspaceAssistantService
from novel_system.services.snowflake_workspace_llm import SnowflakeWorkspaceLLMService

STRUCTURED_GATE_STATUSES = set(GATE_STATUSES)
SCENE_PATCH_FIELDS = {
    "chapter_id",
    "chapter_title",
    "chapter_goal",
    "chapter_role",
    "scene_seq",
    "pov_character_id",
    "onstage_chars_json",
    "title",
    "summary",
    "primary_form",
    "scene_type",
    "location",
    "scene_crucible",
    "crucible",
    "goal",
    "conflict",
    "setback",
    "reaction",
    "dilemma",
    "decision",
    "beats_json",
    "must_include_text",
    "exit_change",
    "hook",
    "target_length_band",
}


class SnowflakeWorkspaceService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self._projects = ProjectService(session)
        self._planner = SnowflakePlannerService(session)
        self._assistant = SnowflakeWorkspaceAssistantService()
        self._llm = SnowflakeWorkspaceLLMService(session)

    def list_projects(self) -> dict[str, Any]:
        rows = self._projects.list()
        return {
            "items": [
                item
                for item in rows.get("items") or []
                if str(item.get("planning_mode") or "") == "snowflake"
            ]
        }

    def create_project(self, payload: dict[str, Any]) -> dict[str, Any]:
        result = self._projects.create({**(payload or {}), "planning_mode": "snowflake"})
        project = result["project"]
        return {
            "project": project,
            "workspace": self.workspace(project["project_id"]),
        }

    def workspace(self, project_id: str) -> dict[str, Any]:
        project = self._require_snowflake_project(project_id)
        latest_by_step = self._latest_by_step(project_id)
        current_step_key = self._current_step_key(latest_by_step)
        scene_board = self._scene_board(project_id)
        triage_items = self._triage_items(project_id)
        latest_plan = self._latest_plan(project_id)
        steps = [self._workspace_step(step, latest_by_step, project_id=project_id) for step in list_step_definitions()]
        gate = self._materialization_gate(latest_by_step, triage_items)
        return {
            "project": project_payload(project),
            "method_version": SNOWFLAKE_METHOD_VERSION,
            "quality_policy": deepcopy(QUALITY_POLICY),
            "materialization_requirements": deepcopy(MATERIALIZATION_REQUIREMENTS),
            "current_step_key": current_step_key,
            "ready_to_materialize": gate["status"] != "blocked",
            "latest_plan": outline_plan_payload(latest_plan) if latest_plan is not None else None,
            "scene_board": scene_board,
            "triage_items": triage_items,
            "assistant_history": self._assistant_history(project_id),
            "materialization_gate": gate,
            "steps": steps,
        }

    def generate_step(self, project_id: str, step_key: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        project = self._require_snowflake_project(project_id)
        body = payload or {}
        self._require_step(step_key)
        latest_by_step = self._latest_by_step(project.project_id)
        self._require_previous_gates(step_key, latest_by_step)

        if body.get("skip"):
            draft = self._skip_draft(step_key, body)
            source = "skip"
            llm_call_id = None
            status = "skipped"
            approved_at = utcnow()
        else:
            llm_result = self._llm.generate_step(
                project=project,
                step_key=step_key,
                latest_by_step=latest_by_step,
                fallback_factory=lambda: self._planner._build_artifact_json(project, step_key, latest_by_step),
            )
            draft = llm_result.payload
            source = llm_result.source
            llm_call_id = llm_result.llm_call_id
            status = "pending_review"
            approved_at = None

        run = SnowflakeStepRun(
            step_run_id=f"snowflake_step_run_{project.project_id}_{step_key}_{uuid.uuid4().hex[:10]}",
            project_id=project.project_id,
            step_key=step_key,
            version=self._next_step_version(project.project_id, step_key),
            status=status,
            draft_json=draft,
            health_json=self._step_health(step_key, draft, status, generation_source=source),
            input_refs_json=self._input_refs(step_key, latest_by_step),
            llm_call_id=llm_call_id,
            approved_at=approved_at,
        )
        self.session.add(run)
        self.session.flush()
        self._sync_structured_step_data(project, step_key, draft, run)
        if status == "skipped":
            self._supersede_same_step(run)
            self._mark_downstream_stale(run)
        self.session.flush()
        workspace = self.workspace(project.project_id)
        return {"step": self._step_from_workspace(workspace, step_key), "workspace": workspace}

    def update_step(self, project_id: str, step_key: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        project = self._require_snowflake_project(project_id)
        body = payload or {}
        self._require_step(step_key)
        latest_by_step = self._latest_by_step(project.project_id)
        self._require_previous_gates(step_key, latest_by_step)
        draft = merge_step_draft(step_key, body.get("draft") or {}, latest_by_step=latest_by_step)
        latest = latest_by_step.get(step_key)

        if latest is not None and latest.status == "pending_review":
            run = latest
            run.draft_json = draft
            run.input_refs_json = self._input_refs(step_key, latest_by_step)
            run.health_json = self._step_health(step_key, draft, "pending_review", generation_source="author")
            run.stale_reason = None
        else:
            run = SnowflakeStepRun(
                step_run_id=f"snowflake_step_run_{project.project_id}_{step_key}_{uuid.uuid4().hex[:10]}",
                project_id=project.project_id,
                step_key=step_key,
                version=self._next_step_version(project.project_id, step_key),
                status="pending_review",
                draft_json=draft,
                health_json=self._step_health(step_key, draft, "pending_review", generation_source="author"),
                input_refs_json=self._input_refs(step_key, latest_by_step),
            )
            self.session.add(run)

        self.session.flush()
        self._sync_structured_step_data(project, step_key, draft, run)
        self.session.flush()
        workspace = self.workspace(project.project_id)
        return {"step": self._step_from_workspace(workspace, step_key), "workspace": workspace, "step_run": self._step_run_payload(run)}

    def approve_step(self, project_id: str, step_key: str) -> dict[str, Any]:
        project = self._require_snowflake_project(project_id)
        latest_by_step = self._latest_by_step(project.project_id)
        run = latest_by_step.get(step_key)
        if run is None:
            raise DomainError("SNOWFLAKE_STEP_RUN_NOT_FOUND", "no draft exists for this snowflake step", status_code=404)
        if run.status in {"approved", "skipped"}:
            workspace = self.workspace(project.project_id)
            return {"step": self._step_from_workspace(workspace, step_key), "workspace": workspace}
        if run.status != "pending_review":
            raise DomainError("SNOWFLAKE_STEP_RUN_NOT_APPROVABLE", "step run cannot be approved in its current status", status_code=409)

        self._require_previous_gates(step_key, latest_by_step, allow_self=run.step_run_id)
        self._supersede_same_step(run)
        run.status = "approved"
        run.approved_at = utcnow()
        run.health_json = self._step_health(step_key, run.draft_json or {}, "approved", generation_source=(run.health_json or {}).get("generation_source"))
        self._sync_structured_step_data(project, step_key, run.draft_json or {}, run, approved=True)
        self._mark_downstream_stale(run)
        self.session.flush()
        workspace = self.workspace(project.project_id)
        return {"step": self._step_from_workspace(workspace, step_key), "workspace": workspace}

    def request_assistant(self, project_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        project = self._require_snowflake_project(project_id)
        body = payload or {}
        latest_by_step = self._latest_by_step(project.project_id)
        workspace = self.workspace(project.project_id)
        step_key = str(body.get("step_key") or workspace.get("current_step_key") or "book_brief").strip() or "book_brief"
        step = self._step_from_workspace(workspace, step_key)
        step = self._step_with_override(step, body.get("draft_override"), latest_by_step=latest_by_step)
        approved_context = self._approved_context(workspace)
        focus_scene_id = str(body.get("focus_scene_id") or "").strip() or None
        llm_result = self._llm.assistant_reply(
            project=workspace["project"],
            step=step,
            message=str(body.get("message") or ""),
            approved_context=approved_context,
            latest_by_step=latest_by_step,
            focus_scene_id=focus_scene_id,
            fallback_factory=lambda: self._assistant.reply(
                project=workspace["project"],
                step=step,
                message=str(body.get("message") or ""),
                approved_context=approved_context,
                focus_scene_id=focus_scene_id,
            ),
        )
        result = {
            **llm_result.payload,
            "step_key": step_key,
            "source": llm_result.source,
            "llm_call_id": llm_result.llm_call_id,
        }
        turn = self._record_assistant_turn(
            project.project_id,
            step_key=step_key,
            message=str(body.get("message") or ""),
            focus_scene_id=focus_scene_id,
            result=result,
        )
        history = self._assistant_history(project.project_id)
        return {
            **result,
            "turn_id": turn.turn_id,
            "created_at": turn.created_at,
            "assistant_history": history,
        }

    def suggest_scene_triage(self, project_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        project = self._require_snowflake_project(project_id)
        body = payload or {}
        workspace = self.workspace(project.project_id)
        step = self._step_from_workspace(workspace, "scene_details")
        if not step.get("draft", {}).get("scenes"):
            raise DomainError("SNOWFLAKE_SCENE_DETAILS_REQUIRED", "scene details must be prepared first", status_code=409)
        step = self._step_with_override(step, body.get("draft_override"), latest_by_step=self._latest_by_step(project.project_id))
        llm_result = self._llm.scene_triage_suggestions(
            project=workspace["project"],
            step=step,
            approved_context=self._approved_context(workspace),
        )
        return {
            "items": self._attach_triage_identity(project.project_id, llm_result.payload.get("items") or []),
            "source": llm_result.source,
            "llm_call_id": llm_result.llm_call_id,
        }

    def save_scene_triage(self, project_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        project = self._require_snowflake_project(project_id)
        items = list((payload or {}).get("items") or [])
        for item in items:
            if not isinstance(item, dict):
                continue
            scene = self._scene_plan_for_triage_item(project.project_id, item)
            diagnosis = diagnose_scene_detail(_scene_plan_payload(scene))
            manual_status = _coerce_triage_status(item.get("status") or item.get("manual_status"))
            recommended_status = _coerce_triage_status(item.get("recommended_status")) or diagnosis["recommended_status"]
            effective_status = manual_status or recommended_status
            triage_id = str(item.get("triage_id") or "").strip()
            row = self.session.get(SnowflakeSceneTriageItem, triage_id) if triage_id else None
            if row is None:
                row = SnowflakeSceneTriageItem(
                    triage_id=f"snowflake_triage_{project.project_id}_{scene.scene_id}_{uuid.uuid4().hex[:8]}",
                    project_id=project.project_id,
                    scene_plan_id=scene.scene_plan_id,
                    scene_id=scene.scene_id,
                )
                self.session.add(row)
            row.scene_plan_id = scene.scene_plan_id
            row.scene_id = scene.scene_id
            row.recommended_status = recommended_status
            row.manual_status = manual_status
            row.effective_status = effective_status
            row.score = _coerce_int(item.get("score"), diagnosis["score"])
            row.missing_fields_json = _coerce_string_list(item.get("missing_fields")) or diagnosis["missing_fields"]
            row.fix_steps_json = _coerce_string_list(item.get("fix_steps")) or diagnosis["fix_steps"]
            row.repair_patch_json = _sanitize_scene_patch(item.get("repair_patch") or {})
            row.pressure_flags_json = _coerce_string_list(item.get("pressure_flags")) or diagnosis["pressure_flags"]
            row.notes = str(item.get("notes") or "").strip()
            row.blocking = 1 if effective_status == "rewrite" else 0
            row.manual_override = 1 if manual_status and manual_status != recommended_status else 0
            row.llm_call_id = str(item.get("llm_call_id") or "").strip() or row.llm_call_id
        self.session.flush()
        workspace = self.workspace(project.project_id)
        return {"items": workspace["triage_items"], "workspace": workspace}

    def apply_scene_triage_repair(self, project_id: str, triage_id: str) -> dict[str, Any]:
        project = self._require_snowflake_project(project_id)
        row = self.session.get(SnowflakeSceneTriageItem, triage_id)
        if row is None or row.project_id != project.project_id:
            raise DomainError("SNOWFLAKE_TRIAGE_NOT_FOUND", "scene triage item not found", status_code=404)
        scene = self.session.get(SnowflakeScenePlan, row.scene_plan_id)
        if scene is None or scene.project_id != project.project_id:
            raise DomainError("SNOWFLAKE_SCENE_PLAN_NOT_FOUND", "scene plan not found", status_code=404)
        patch = _sanitize_scene_patch(row.repair_patch_json or {})
        if not patch:
            raise DomainError("SNOWFLAKE_TRIAGE_REPAIR_EMPTY", "triage item has no repair patch to apply", status_code=409)
        self._apply_scene_patch(scene, patch)
        scene.diagnosis_json = diagnose_scene_detail(_scene_plan_payload(scene))
        row.recommended_status = scene.diagnosis_json["recommended_status"]
        row.score = scene.diagnosis_json["score"]
        row.missing_fields_json = scene.diagnosis_json["missing_fields"]
        row.fix_steps_json = scene.diagnosis_json["fix_steps"]
        row.pressure_flags_json = scene.diagnosis_json["pressure_flags"]
        row.effective_status = row.manual_status or row.recommended_status
        row.blocking = 1 if row.effective_status == "rewrite" else 0
        row.manual_override = 1 if row.manual_status and row.manual_status != row.recommended_status else 0
        self.session.flush()
        return {"triage": self._triage_payload(row), "scene": _scene_plan_payload(scene), "workspace": self.workspace(project.project_id)}

    def update_scene_plan(self, project_id: str, scene_plan_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        project = self._require_snowflake_project(project_id)
        scene = self.session.get(SnowflakeScenePlan, scene_plan_id)
        if scene is None or scene.project_id != project.project_id:
            raise DomainError("SNOWFLAKE_SCENE_PLAN_NOT_FOUND", "scene plan not found", status_code=404)
        self._apply_scene_patch(scene, _sanitize_scene_patch(payload or {}))
        scene.status = "draft" if scene.status == "approved" else scene.status
        scene.diagnosis_json = diagnose_scene_detail(_scene_plan_payload(scene))
        self.session.flush()
        return {"scene": _scene_plan_payload(scene), "workspace": self.workspace(project.project_id)}

    def materialize(self, project_id: str) -> dict[str, Any]:
        project = self._require_snowflake_project(project_id)
        workspace = self.workspace(project.project_id)
        gate = workspace.get("materialization_gate") or {}
        if gate.get("status") == "blocked":
            if any(
                str(item.get("effective_status") or item.get("status") or "").strip().lower() == "rewrite"
                for item in workspace.get("triage_items") or []
            ):
                raise DomainError(
                    "SNOWFLAKE_TRIAGE_BLOCKED",
                    "rewrite-marked scenes must be repaired before materializing the outline",
                    status_code=409,
                    details={"materialization_gate": gate},
                )
            raise DomainError(
                "SNOWFLAKE_NOT_READY",
                "snowflake workspace must pass materialization gate before materializing",
                status_code=409,
                details={"materialization_gate": gate},
            )
        scene_plans = self._scene_plans(project.project_id)
        if not scene_plans:
            raise DomainError("SNOWFLAKE_SCENES_REQUIRED", "scene plans are required", status_code=409)
        plan = OutlinePlan(
            plan_id=f"outline_plan_{project.project_id}_{self._next_plan_version(project.project_id):02d}_{uuid.uuid4().hex[:8]}",
            project_id=project.project_id,
            version=self._next_plan_version(project.project_id),
            status=PLAN_STATUS_PENDING_REVIEW,
            plan_json=self._planner._build_outline_plan(
                project,
                {"scenes": [_scene_list_payload(scene) for scene in scene_plans]},
                {"scenes": [_scene_plan_payload(scene) for scene in scene_plans]},
            ),
        )
        project.status = "outline_review"
        self.session.add(plan)
        self.session.flush()
        return {"plan": outline_plan_payload(plan), "workspace": self.workspace(project.project_id)}

    def approve_outline(self, project_id: str) -> dict[str, Any]:
        project = self._require_snowflake_project(project_id)
        latest_plan = self._latest_plan(project.project_id)
        if latest_plan is None:
            raise DomainError("OUTLINE_PLAN_NOT_FOUND", "outline plan not found", status_code=404)
        result = self._projects.approve_outline_plan(project.project_id, latest_plan.plan_id)
        workspace = self.workspace(project.project_id)
        return {
            "plan": result["plan"],
            "workspace": workspace,
            "created_chapter_count": result.get("created_chapter_count", 0),
            "created_scene_count": result.get("created_scene_count", 0),
        }

    def _require_snowflake_project(self, project_id: str) -> StoryProject:
        project = self._projects.require_project(project_id)
        if str(getattr(project, "planning_mode", "") or "") != "snowflake":
            raise DomainError(
                "PROJECT_NOT_SNOWFLAKE",
                "this workspace only supports snowflake projects",
                status_code=409,
            )
        return project

    def _workspace_step(self, step: dict[str, Any], latest_by_step: dict[str, SnowflakeStepRun], *, project_id: str) -> dict[str, Any]:
        run = latest_by_step.get(step["step_key"])
        draft = self._draft_for_step(step["step_key"], run, latest_by_step, project_id=project_id)
        status = run.status if run is not None else "draft"
        return {
            "step_key": step["step_key"],
            "label": step["label"],
            "english_label": step.get("english_label", ""),
            "phase": step["phase"],
            "description": step["description"],
            "status": status,
            "version": run.version if run is not None else 0,
            "health": deepcopy(run.health_json or {}) if run is not None else {},
            "stale_reason": run.stale_reason if run is not None else "",
            "can_skip": bool(step.get("skippable")),
            "can_backtrack": run is not None and run.status in {"approved", "skipped", "stale"},
            "guidance": step_guidance(step["step_key"]),
            "gate_satisfied": self._gate_satisfied(step["step_key"], latest_by_step),
            "artifact": self._step_run_payload(run),
            "draft": draft,
            "completeness": step_completeness(step["step_key"], draft),
            "editor": editor_payload(step["step_key"]),
            "last_generation_source": (run.health_json or {}).get("generation_source") if run is not None else None,
            "last_llm_call_id": run.llm_call_id if run is not None else None,
        }

    def _draft_for_step(
        self,
        step_key: str,
        run: SnowflakeStepRun | None,
        latest_by_step: dict[str, SnowflakeStepRun],
        *,
        project_id: str,
    ) -> dict[str, Any]:
        if step_key == "scene_list":
            scenes = [_scene_list_payload(scene) for scene in self._scene_plans(project_id)]
            return {"scenes": scenes} if scenes else merge_step_draft(step_key, run.draft_json if run else None, latest_by_step=latest_by_step)
        if step_key == "scene_details":
            scenes = [_scene_plan_payload(scene) for scene in self._scene_plans(project_id)]
            return {"scenes": scenes} if scenes else merge_step_draft(step_key, run.draft_json if run else None, latest_by_step=latest_by_step)
        return merge_step_draft(step_key, run.draft_json if run else None, latest_by_step=latest_by_step)

    @staticmethod
    def _gate_satisfied(step_key: str, latest_by_step: dict[str, SnowflakeStepRun]) -> bool:
        run = latest_by_step.get(step_key)
        return run is not None and run.status in STRUCTURED_GATE_STATUSES

    def _current_step_key(self, latest_by_step: dict[str, SnowflakeStepRun]) -> str | None:
        for step in list_step_definitions():
            if not self._gate_satisfied(step["step_key"], latest_by_step):
                return step["step_key"]
        return None

    def _require_step(self, step_key: str) -> None:
        if step_key not in STEP_ORDER:
            raise DomainError("SNOWFLAKE_STEP_NOT_FOUND", "unknown snowflake step", status_code=404)

    def _require_previous_gates(
        self,
        step_key: str,
        latest_by_step: dict[str, SnowflakeStepRun],
        *,
        allow_self: str | None = None,
    ) -> None:
        step_index = STEP_ORDER[step_key]
        for step in list_step_definitions()[:step_index]:
            run = latest_by_step.get(step["step_key"])
            if allow_self and run is not None and run.step_run_id == allow_self:
                continue
            if run is None or run.status not in STRUCTURED_GATE_STATUSES:
                raise DomainError(
                    "SNOWFLAKE_PREVIOUS_STEP_REQUIRED",
                    "previous snowflake steps must be approved first",
                    status_code=409,
                )

    def _latest_by_step(self, project_id: str) -> dict[str, SnowflakeStepRun]:
        rows = self.session.execute(
            select(SnowflakeStepRun)
            .where(SnowflakeStepRun.project_id == project_id)
            .order_by(SnowflakeStepRun.version.asc(), SnowflakeStepRun.created_at.asc())
        ).scalars().all()
        latest: dict[str, SnowflakeStepRun] = {}
        for row in rows:
            if row.status == "superseded":
                continue
            latest[row.step_key] = row
        return latest

    def _input_refs(self, step_key: str, latest_by_step: dict[str, SnowflakeStepRun]) -> dict[str, Any]:
        step_index = STEP_ORDER[step_key]
        refs: dict[str, Any] = {}
        for step in list_step_definitions()[:step_index]:
            run = latest_by_step.get(step["step_key"])
            if run is not None and run.status in STRUCTURED_GATE_STATUSES:
                refs[step["step_key"]] = run.step_run_id
        return refs

    def _next_step_version(self, project_id: str, step_key: str) -> int:
        latest = self.session.execute(
            select(SnowflakeStepRun.version)
            .where(SnowflakeStepRun.project_id == project_id, SnowflakeStepRun.step_key == step_key)
            .order_by(SnowflakeStepRun.version.desc())
        ).scalar()
        return int(latest or 0) + 1

    def _next_plan_version(self, project_id: str) -> int:
        latest = self.session.execute(
            select(OutlinePlan.version)
            .where(OutlinePlan.project_id == project_id)
            .order_by(OutlinePlan.version.desc())
        ).scalar()
        return int(latest or 0) + 1

    def _latest_plan(self, project_id: str) -> OutlinePlan | None:
        return self.session.execute(
            select(OutlinePlan)
            .where(OutlinePlan.project_id == project_id)
            .order_by(OutlinePlan.version.desc(), OutlinePlan.created_at.desc())
        ).scalars().first()

    def _scene_plans(self, project_id: str) -> list[SnowflakeScenePlan]:
        return self.session.execute(
            select(SnowflakeScenePlan)
            .where(SnowflakeScenePlan.project_id == project_id)
            .order_by(SnowflakeScenePlan.chapter_id.asc(), SnowflakeScenePlan.scene_seq.asc(), SnowflakeScenePlan.scene_id.asc())
        ).scalars().all()

    def _scene_board(self, project_id: str) -> dict[str, Any]:
        scenes = [_scene_plan_payload(scene) for scene in self._scene_plans(project_id)]
        chapters_by_id: dict[str, dict[str, Any]] = {}
        for scene in scenes:
            chapter_id = scene["chapter_id"]
            chapter = chapters_by_id.setdefault(
                chapter_id,
                {
                    "chapter_id": chapter_id,
                    "title": scene.get("chapter_title") or chapter_id,
                    "chapter_goal": scene.get("chapter_goal") or "",
                    "scene_count": 0,
                },
            )
            chapter["scene_count"] += 1
        return {"chapters": list(chapters_by_id.values()), "scenes": scenes}

    def _triage_items(self, project_id: str) -> list[dict[str, Any]]:
        stored = {
            row.scene_plan_id: row
            for row in self.session.execute(
                select(SnowflakeSceneTriageItem).where(SnowflakeSceneTriageItem.project_id == project_id)
            ).scalars().all()
        }
        items: list[dict[str, Any]] = []
        for scene in self._scene_plans(project_id):
            row = stored.get(scene.scene_plan_id)
            if row is not None:
                items.append(self._triage_payload(row))
                continue
            diagnosis = diagnose_scene_detail(_scene_plan_payload(scene))
            items.append(
                {
                    "triage_id": "",
                    "scene_plan_id": scene.scene_plan_id,
                    "scene_id": scene.scene_id,
                    "title": scene.title or scene.summary or scene.scene_id,
                    "primary_form": scene.scene_type,
                    "scene_type": scene.scene_type,
                    "status": "",
                    "manual_status": "",
                    "notes": "",
                    "recommended_status": diagnosis["recommended_status"],
                    "effective_status": "unreviewed",
                    "triage_source": "auto_diagnosis",
                    "score": diagnosis["score"],
                    "pressure_flags": diagnosis["pressure_flags"],
                    "missing_fields": diagnosis["missing_fields"],
                    "fix_steps": diagnosis["fix_steps"],
                    "repair_patch": {},
                    "blocking": False,
                    "manual_override": False,
                }
            )
        return items

    def _assistant_history(self, project_id: str, *, limit: int = 50) -> list[dict[str, Any]]:
        rows = self.session.execute(
            select(SnowflakeAssistantTurn)
            .where(SnowflakeAssistantTurn.project_id == project_id)
            .order_by(SnowflakeAssistantTurn.created_at.desc(), SnowflakeAssistantTurn.turn_id.desc())
            .limit(max(1, min(int(limit or 50), 200)))
        ).scalars().all()
        return [self._assistant_turn_payload(row) for row in reversed(rows)]

    def _record_assistant_turn(
        self,
        project_id: str,
        *,
        step_key: str,
        message: str,
        focus_scene_id: str | None,
        result: dict[str, Any],
    ) -> SnowflakeAssistantTurn:
        turn = SnowflakeAssistantTurn(
            turn_id=f"snowflake_assistant_turn_{project_id}_{uuid.uuid4().hex[:10]}",
            project_id=project_id,
            step_key=step_key,
            focus_scene_id=focus_scene_id,
            user_message=str(message or "").strip(),
            reply=str(result.get("reply") or "").strip(),
            suggestions_json=_coerce_string_list(result.get("suggestions")),
            candidate_label=str(result.get("candidate_label") or "").strip() or None,
            candidate_patch_json=deepcopy(result.get("candidate_patch") or {}) or None,
            source=str(result.get("source") or "fallback").strip() or "fallback",
            llm_call_id=str(result.get("llm_call_id") or "").strip() or None,
        )
        self.session.add(turn)
        self.session.flush()
        return turn

    @staticmethod
    def _assistant_turn_payload(row: SnowflakeAssistantTurn) -> dict[str, Any]:
        return {
            "turn_id": row.turn_id,
            "project_id": row.project_id,
            "step_key": row.step_key,
            "focus_scene_id": row.focus_scene_id or None,
            "message": row.user_message or "",
            "reply": row.reply or "",
            "suggestions": list(row.suggestions_json or []),
            "candidate_label": row.candidate_label or None,
            "candidate_patch": deepcopy(row.candidate_patch_json or {}) or None,
            "source": row.source or "fallback",
            "llm_call_id": row.llm_call_id,
            "created_at": row.created_at,
        }

    def _triage_payload(self, row: SnowflakeSceneTriageItem) -> dict[str, Any]:
        scene = self.session.get(SnowflakeScenePlan, row.scene_plan_id)
        return {
            "triage_id": row.triage_id,
            "scene_plan_id": row.scene_plan_id,
            "scene_id": row.scene_id,
            "title": scene.title or scene.summary or row.scene_id if scene is not None else row.scene_id,
            "primary_form": scene.scene_type if scene is not None else "",
            "scene_type": scene.scene_type if scene is not None else "",
            "status": row.manual_status or "",
            "manual_status": row.manual_status or "",
            "notes": row.notes or "",
            "recommended_status": row.recommended_status or "",
            "effective_status": row.effective_status or row.manual_status or row.recommended_status or "",
            "triage_source": "author_saved",
            "score": row.score,
            "pressure_flags": list(row.pressure_flags_json or []),
            "missing_fields": list(row.missing_fields_json or []),
            "fix_steps": list(row.fix_steps_json or []),
            "repair_patch": deepcopy(row.repair_patch_json or {}),
            "blocking": bool(row.blocking),
            "manual_override": bool(row.manual_override),
        }

    @staticmethod
    def _materialization_gate(latest_by_step: dict[str, SnowflakeStepRun], triage_items: list[dict[str, Any]]) -> dict[str, Any]:
        blockers: list[str] = []
        warnings: list[str] = []
        items: list[dict[str, Any]] = []

        def add_step_item(*, severity: str, kind: str, message: str, step_key: str) -> None:
            if severity == "blocker":
                blockers.append(message)
            else:
                warnings.append(message)
            items.append(
                {
                    "id": f"{severity}:{kind}:{step_key}",
                    "severity": severity,
                    "kind": kind,
                    "message": message,
                    "step_key": step_key,
                    "scene_id": None,
                    "scene_plan_id": None,
                    "target_view": "snowflake-workbench",
                    "primary_action": {
                        "type": "jump_to_step",
                        "label": "去补这一步" if severity == "blocker" else "查看这一步",
                        "step_key": step_key,
                    },
                    "assistant_action": {
                        "type": "draft_with_assistant",
                        "label": "让助手起草",
                        "step_key": step_key,
                    },
                }
            )

        def add_scene_item(*, severity: str, kind: str, message: str, item: dict[str, Any]) -> None:
            if severity == "blocker":
                blockers.append(message)
            else:
                warnings.append(message)
            scene_id = str(item.get("scene_id") or "").strip()
            scene_plan_id = str(item.get("scene_plan_id") or "").strip()
            items.append(
                {
                    "id": f"{severity}:{kind}:{scene_plan_id or scene_id or len(items)}",
                    "severity": severity,
                    "kind": kind,
                    "message": message,
                    "step_key": "scene_details",
                    "scene_id": scene_id or None,
                    "scene_plan_id": scene_plan_id or None,
                    "target_view": "snowflake-workbench",
                    "primary_action": {
                        "type": "open_triage",
                        "label": "去修这个场景" if severity == "blocker" else "查看这个提醒",
                        "panel": "triage",
                        "scene_id": scene_id or None,
                        "scene_plan_id": scene_plan_id or None,
                    },
                    "assistant_action": {
                        "type": "draft_with_assistant",
                        "label": "让助手起草修法",
                        "scene_id": scene_id or None,
                        "scene_plan_id": scene_plan_id or None,
                    },
                }
            )

        for step_key in MATERIALIZATION_REQUIRED_STEPS:
            run = latest_by_step.get(step_key)
            step_label = _step_display_label(step_key)
            if run is None:
                add_step_item(
                    severity="blocker",
                    kind="missing_required_step",
                    message=f"{step_label} 是整理章节结构前必需步骤。",
                    step_key=step_key,
                )
                continue
            if run.status == "skipped":
                add_step_item(
                    severity="blocker",
                    kind="skipped_required_step",
                    message=f"{step_label} 是整理章节结构前必需步骤，不能跳过。",
                    step_key=step_key,
                )
                continue
            if run.status not in STRUCTURED_GATE_STATUSES:
                add_step_item(
                    severity="blocker",
                    kind="unapproved_required_step",
                    message=f"{step_label} 需要先确认，才能整理章节结构。",
                    step_key=step_key,
                )
                continue
            health = run.health_json or {}
            if step_key != "scene_details" and str(health.get("status") or health.get("pressure_status") or "").strip().lower() == "rewrite":
                add_step_item(
                    severity="blocker",
                    kind="rewrite_step_health",
                    message=f"{step_label} 存在废除重写级质量阻断。",
                    step_key=step_key,
                )

        for step_key in MATERIALIZATION_WARNING_STEPS:
            run = latest_by_step.get(step_key)
            step_label = _step_display_label(step_key)
            if run is None:
                add_step_item(
                    severity="warning",
                    kind="missing_optional_step",
                    message=f"{step_label} 尚未完成；可以继续整理，但角色或长篇细化风险会保留。",
                    step_key=step_key,
                )
                continue
            if run.status == "skipped":
                reason = str((run.draft_json or {}).get("skip_reason") or "").strip()
                suffix = f"：{reason}" if reason else "。"
                add_step_item(
                    severity="warning",
                    kind="skipped_optional_step",
                    message=f"{step_label} 已跳过{suffix}",
                    step_key=step_key,
                )
                continue
            if run.status not in STRUCTURED_GATE_STATUSES:
                add_step_item(
                    severity="warning",
                    kind="unapproved_optional_step",
                    message=f"{step_label} 尚未确认；可以继续整理，但后续可能需要回修。",
                    step_key=step_key,
                )
        for item in triage_items:
            scene_label = str(item.get("title") or item.get("scene_id") or "scene").strip()
            scene_id = str(item.get("scene_id") or "").strip()
            status = str(item.get("effective_status") or item.get("status") or "").strip().lower()
            recommended_status = str(item.get("recommended_status") or "").strip().lower()
            triage_source = str(item.get("triage_source") or "").strip().lower()
            scene_display = f"「{scene_label}」"
            if scene_id and scene_id != scene_label:
                scene_display = f"「{scene_label}」（{scene_id}）"
            if triage_source == "auto_diagnosis" and status == "unreviewed":
                if recommended_status == "rewrite":
                    add_scene_item(
                        severity="blocker",
                        kind="triage_confirmation_required",
                        message=f"{scene_display} 系统建议重写，请先确认急救判断。",
                        item=item,
                    )
                elif recommended_status == "maybe":
                    add_scene_item(
                        severity="warning",
                        kind="triage_unreviewed_maybe",
                        message=f"{scene_display} 系统建议复核修改，整理前请先确认急救判断。",
                        item=item,
                    )
                continue
            if status == "rewrite":
                add_scene_item(
                    severity="blocker",
                    kind="triage_rewrite",
                    message=f"{scene_display} 被标为废除重写，需先重建。",
                    item=item,
                )
            elif status == "maybe":
                add_scene_item(
                    severity="warning",
                    kind="triage_maybe",
                    message=f"{scene_display} 仍需修改；允许整理，但章节生成风险较高。",
                    item=item,
                )
            if item.get("manual_override") and recommended_status == "rewrite" and status != "rewrite":
                add_scene_item(
                    severity="warning",
                    kind="triage_manual_override",
                    message=f"{scene_display} 人工覆盖了自动废除重写诊断；整理前请复核急救备注。",
                    item=item,
                )
        return {
            "status": "blocked" if blockers else "warning" if warnings else "ready",
            "blockers": blockers,
            "warnings": warnings,
            "items": items,
        }

    def _sync_structured_step_data(
        self,
        project: StoryProject,
        step_key: str,
        draft: dict[str, Any],
        run: SnowflakeStepRun,
        *,
        approved: bool = False,
    ) -> None:
        if step_key in {"character_sheets", "character_synopses", "character_bibles"}:
            self._sync_character_plans(project.project_id, step_key, draft.get("characters") or [], approved=approved)
        if step_key in {"scene_list", "scene_details"}:
            self._sync_scene_plans(project.project_id, step_key, draft.get("scenes") or [], run, approved=approved)

    def _sync_character_plans(self, project_id: str, step_key: str, characters: list[Any], *, approved: bool) -> None:
        for index, item in enumerate(characters, start=1):
            if not isinstance(item, dict):
                continue
            character_id = str(item.get("character_id") or f"{project_id}_CHAR{index:02d}").strip()
            display_name = str(item.get("display_name") or item.get("name") or character_id).strip()
            plan_id = f"snowflake_character_plan_{project_id}_{character_id}"
            plan = self.session.get(SnowflakeCharacterPlan, plan_id)
            if plan is None:
                plan = SnowflakeCharacterPlan(
                    character_plan_id=plan_id,
                    project_id=project_id,
                    character_id=character_id,
                    display_name=display_name,
                )
                self.session.add(plan)
            plan.display_name = display_name
            plan.role = item.get("role") or plan.role
            plan.source_step_key = step_key
            plan.status = "approved" if approved else "draft"
            plan.stale_reason = None
            if step_key == "character_sheets":
                plan.summary_json = item
            elif step_key == "character_synopses":
                plan.synopsis_json = item
            elif step_key == "character_bibles":
                plan.bible_json = item

            if approved and step_key in {"character_sheets", "character_bibles"}:
                self._sync_story_character(project_id, character_id, display_name, item, step_key)

    def _sync_story_character(self, project_id: str, character_id: str, display_name: str, item: dict[str, Any], step_key: str) -> None:
        row = self.session.get(StoryCharacter, character_id)
        if row is None:
            row = StoryCharacter(
                character_id=character_id,
                project_id=project_id,
                display_name=display_name,
                role=item.get("role"),
                summary_json={},
                bible_json={},
                status="approved",
            )
            self.session.add(row)
        row.display_name = display_name
        row.role = item.get("role") or row.role
        row.status = "approved"
        if step_key == "character_sheets":
            row.summary_json = item
        elif step_key == "character_bibles":
            row.bible_json = item

    def _sync_scene_plans(
        self,
        project_id: str,
        step_key: str,
        scenes: list[Any],
        run: SnowflakeStepRun,
        *,
        approved: bool,
    ) -> None:
        current_chapter_id = f"{project_id}_CH01"
        seq_by_chapter: dict[str, int] = {}
        for index, item in enumerate(scenes, start=1):
            if not isinstance(item, dict):
                continue
            chapter_id = str(item.get("chapter_id") or current_chapter_id or f"{project_id}_CH01").strip()
            current_chapter_id = chapter_id
            next_seq = seq_by_chapter.get(chapter_id, 0) + 1
            scene_seq = _coerce_int(item.get("scene_seq"), next_seq)
            seq_by_chapter[chapter_id] = scene_seq
            scene_id = str(item.get("scene_id") or f"{chapter_id}_SC{scene_seq:02d}").strip()
            plan = self._scene_plan_by_scene_id(project_id, scene_id)
            created = plan is None
            if plan is None:
                plan = SnowflakeScenePlan(
                    scene_plan_id=f"snowflake_scene_plan_{project_id}_{scene_id}",
                    project_id=project_id,
                    scene_id=scene_id,
                    chapter_id=chapter_id,
                    scene_seq=scene_seq,
                )
                self.session.add(plan)
            plan.chapter_id = chapter_id
            plan.scene_seq = scene_seq
            plan.source_step_run_id = run.step_run_id
            plan.status = "approved" if approved else "draft"
            plan.stale_reason = None
            self._apply_scene_patch(plan, _sanitize_scene_patch(item))
            if created and not plan.title:
                plan.title = str(item.get("title") or item.get("summary") or f"场景 {index:02d}").strip()
            if created and not plan.chapter_title:
                plan.chapter_title = str(item.get("chapter_title") or chapter_id).strip()
            plan.diagnosis_json = diagnose_scene_detail(_scene_plan_payload(plan))

    def _scene_plan_by_scene_id(self, project_id: str, scene_id: str) -> SnowflakeScenePlan | None:
        return self.session.execute(
            select(SnowflakeScenePlan).where(SnowflakeScenePlan.project_id == project_id, SnowflakeScenePlan.scene_id == scene_id)
        ).scalars().first()

    def _scene_plan_for_triage_item(self, project_id: str, item: dict[str, Any]) -> SnowflakeScenePlan:
        scene_plan_id = str(item.get("scene_plan_id") or "").strip()
        scene = self.session.get(SnowflakeScenePlan, scene_plan_id) if scene_plan_id else None
        if scene is None:
            scene_id = str(item.get("scene_id") or "").strip()
            scene = self._scene_plan_by_scene_id(project_id, scene_id) if scene_id else None
        if scene is None or scene.project_id != project_id:
            raise DomainError("SNOWFLAKE_SCENE_PLAN_NOT_FOUND", "scene plan not found", status_code=404)
        return scene

    def _attach_triage_identity(self, project_id: str, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            try:
                scene = self._scene_plan_for_triage_item(project_id, item)
            except DomainError:
                continue
            result.append(
                {
                    **item,
                    "triage_id": item.get("triage_id") or "",
                    "scene_plan_id": scene.scene_plan_id,
                    "scene_id": scene.scene_id,
                    "title": scene.title or scene.summary or scene.scene_id,
                    "primary_form": scene.scene_type,
                    "scene_type": scene.scene_type,
                    "repair_patch": _sanitize_scene_patch(item.get("repair_patch") or {}),
                }
            )
        return result

    def _apply_scene_patch(self, scene: SnowflakeScenePlan, patch: dict[str, Any]) -> None:
        if "crucible" in patch and "scene_crucible" not in patch:
            patch["scene_crucible"] = patch["crucible"]
        for key, value in patch.items():
            if key == "crucible":
                continue
            if key == "primary_form":
                scene_type = str(value or "").strip().lower()
                scene.scene_type = scene_type if scene_type in {"proactive", "reactive"} else "proactive"
                continue
            if not hasattr(scene, key):
                continue
            if key in {"onstage_chars_json", "beats_json"}:
                setattr(scene, key, _coerce_string_list(value))
            elif key == "scene_seq":
                setattr(scene, key, _coerce_int(value, scene.scene_seq or 1))
            elif key == "scene_type":
                scene_type = str(value or "").strip().lower()
                setattr(scene, key, scene_type if scene_type in {"proactive", "reactive"} else "proactive")
            else:
                setattr(scene, key, str(value or "").strip())

    def _supersede_same_step(self, run: SnowflakeStepRun) -> None:
        rows = self.session.execute(
            select(SnowflakeStepRun).where(
                SnowflakeStepRun.project_id == run.project_id,
                SnowflakeStepRun.step_key == run.step_key,
                SnowflakeStepRun.step_run_id != run.step_run_id,
                SnowflakeStepRun.status.in_(["approved", "skipped"]),
            )
        ).scalars().all()
        for row in rows:
            row.status = "superseded"

    def _mark_downstream_stale(self, run: SnowflakeStepRun) -> None:
        step_index = STEP_ORDER[run.step_key]
        downstream_keys = [step["step_key"] for step in list_step_definitions()[step_index + 1 :]]
        if not downstream_keys:
            return
        reason = f"{run.step_key} was revised in version {run.version}; review dependent snowflake work."
        rows = self.session.execute(
            select(SnowflakeStepRun).where(
                SnowflakeStepRun.project_id == run.project_id,
                SnowflakeStepRun.step_key.in_(downstream_keys),
                SnowflakeStepRun.status.in_(["pending_review", "approved", "skipped"]),
            )
        ).scalars().all()
        for row in rows:
            row.status = "stale"
            row.stale_reason = reason
            self._record_revision_link(run, affected_kind="step_run", affected_id=row.step_run_id, reason=reason)

        if any(STEP_ORDER[key] >= STEP_ORDER["scene_list"] for key in downstream_keys):
            for scene in self._scene_plans(run.project_id):
                scene.status = "stale"
                scene.stale_reason = reason
                self._record_revision_link(run, affected_kind="scene_plan", affected_id=scene.scene_plan_id, reason=reason)

    def _record_revision_link(self, run: SnowflakeStepRun, *, affected_kind: str, affected_id: str, reason: str) -> None:
        existing = self.session.execute(
            select(SnowflakeRevisionLink).where(
                SnowflakeRevisionLink.project_id == run.project_id,
                SnowflakeRevisionLink.source_step_run_id == run.step_run_id,
                SnowflakeRevisionLink.affected_kind == affected_kind,
                SnowflakeRevisionLink.affected_id == affected_id,
                SnowflakeRevisionLink.status == "open",
            )
        ).scalars().first()
        if existing is not None:
            return
        self.session.add(
            SnowflakeRevisionLink(
                revision_link_id=f"snowflake_revision_{run.project_id}_{uuid.uuid4().hex[:10]}",
                project_id=run.project_id,
                source_step_key=run.step_key,
                source_step_run_id=run.step_run_id,
                affected_kind=affected_kind,
                affected_id=affected_id,
                reason=reason,
                status="open",
            )
        )

    def _skip_draft(self, step_key: str, payload: dict[str, Any]) -> dict[str, Any]:
        step = get_step_definition(step_key)
        if not step.get("skippable"):
            raise DomainError("SNOWFLAKE_STEP_NOT_SKIPPABLE", "this snowflake step cannot be skipped", status_code=400)
        reason = str(payload.get("skip_reason") or "").strip()
        if not reason:
            raise DomainError("SNOWFLAKE_SKIP_REASON_REQUIRED", "skip_reason is required", status_code=400)
        return {"skipped": True, "skip_reason": reason}

    def _step_health(self, step_key: str, draft: dict[str, Any], status: str, *, generation_source: str | None = None) -> dict[str, Any]:
        if status == "skipped":
            return {
                "severity": "info",
                "message": "step skipped with an explicit author reason",
                "generation_source": generation_source or "skip",
                "step_key": step_key,
                "pressure_score": 100,
                "pressure_status": "pass",
                "pressure_flags": [],
                "fix_steps": [],
                "strengths": ["step skipped with an explicit author reason"],
                "score": 100,
                "status": "pass",
                "gaps": [],
                "next_actions": [],
                "hard_blockers": [],
            }
        completeness = step_completeness(step_key, draft)
        missing = completeness.get("missing_fields") or []
        return {
            "severity": "warning" if missing else "info",
            "message": "step has missing fields" if missing else "step draft is structurally complete",
            "generation_source": generation_source or "fallback",
            "missing_fields": missing,
            **diagnose_step_pressure(step_key, draft),
        }

    @staticmethod
    def _step_run_payload(run: SnowflakeStepRun | None) -> dict[str, Any] | None:
        if run is None:
            return None
        return {
            "step_run_id": run.step_run_id,
            "artifact_id": run.step_run_id,
            "step_key": run.step_key,
            "version": run.version,
            "status": run.status,
            "diagnosis_json": deepcopy(run.health_json or {}),
            "llm_call_id": run.llm_call_id,
            "approved_at": run.approved_at,
            "created_at": run.created_at,
            "updated_at": run.updated_at,
        }

    @staticmethod
    def _step_from_workspace(workspace: dict[str, Any], step_key: str) -> dict[str, Any]:
        for step in workspace.get("steps") or []:
            if step.get("step_key") == step_key:
                return step
        raise DomainError("SNOWFLAKE_STEP_NOT_FOUND", "unknown snowflake step", status_code=404)

    @staticmethod
    def _approved_context(workspace: dict[str, Any]) -> list[dict[str, Any]]:
        return [
            {
                "step_key": item["step_key"],
                "label": item["label"],
                "draft": deepcopy(item.get("draft") or {}),
            }
            for item in workspace.get("steps") or []
            if item.get("gate_satisfied")
        ]

    @staticmethod
    def _step_with_override(
        step: dict[str, Any],
        draft_override: Any,
        *,
        latest_by_step: dict[str, SnowflakeStepRun],
    ) -> dict[str, Any]:
        if not isinstance(draft_override, dict):
            return step
        merged_step = deepcopy(step)
        merged_step["draft"] = _merge_dicts(merged_step.get("draft") or {}, draft_override)
        merged_step["draft"] = merge_step_draft(
            str(merged_step.get("step_key") or ""),
            merged_step.get("draft") or {},
            latest_by_step=latest_by_step,
        )
        return merged_step


def _merge_dicts(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merge_dicts(merged[key], value)
        else:
            merged[key] = deepcopy(value)
    return merged


def _scene_plan_payload(scene: SnowflakeScenePlan) -> dict[str, Any]:
    return {
        "scene_plan_id": scene.scene_plan_id,
        "scene_id": scene.scene_id,
        "chapter_id": scene.chapter_id,
        "chapter_title": scene.chapter_title or "",
        "chapter_goal": scene.chapter_goal or "",
        "chapter_role": scene.chapter_role or "",
        "scene_seq": scene.scene_seq,
        "pov_character_id": scene.pov_character_id or "",
        "onstage_chars_json": list(scene.onstage_chars_json or []),
        "title": scene.title or "",
        "summary": scene.summary or "",
        "primary_form": scene.scene_type or "proactive",
        "scene_type": scene.scene_type or "proactive",
        "location": scene.location or "",
        "scene_crucible": scene.scene_crucible or "",
        "crucible": scene.scene_crucible or "",
        "goal": scene.goal or "",
        "conflict": scene.conflict or "",
        "setback": scene.setback or "",
        "reaction": scene.reaction or "",
        "dilemma": scene.dilemma or "",
        "decision": scene.decision or "",
        "beats_json": list(scene.beats_json or []),
        "must_include_text": scene.must_include_text or "",
        "exit_change": scene.exit_change or "",
        "hook": scene.hook or "",
        "target_length_band": scene.target_length_band or "",
        "status": scene.status,
        "stale_reason": scene.stale_reason or "",
        "diagnosis": deepcopy(scene.diagnosis_json or {}),
    }


def _scene_list_payload(scene: SnowflakeScenePlan) -> dict[str, Any]:
    return {
        "scene_plan_id": scene.scene_plan_id,
        "scene_id": scene.scene_id,
        "chapter_id": scene.chapter_id,
        "chapter_title": scene.chapter_title or scene.chapter_id,
        "chapter_goal": scene.chapter_goal or "",
        "scene_seq": scene.scene_seq,
        "pov_character_id": scene.pov_character_id or "",
        "summary": scene.summary or scene.title or "",
        "primary_form": scene.scene_type or "proactive",
        "scene_type": scene.scene_type or "proactive",
        "chapter_role": scene.chapter_role or "",
        "location": scene.location or "",
        "crucible": scene.scene_crucible or "",
    }


def _sanitize_scene_patch(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    patch: dict[str, Any] = {}
    for key in SCENE_PATCH_FIELDS:
        if key in payload:
            patch[key] = deepcopy(payload[key])
    if "primary_form" in patch:
        patch["scene_type"] = patch["primary_form"]
    return patch


def _coerce_string_list(value: Any) -> list[str]:
    if isinstance(value, str):
        return [item.strip() for item in value.splitlines() if item.strip()]
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _coerce_triage_status(value: Any) -> str:
    status = str(value or "").strip().lower()
    return status if status in {"pass", "maybe", "rewrite"} else ""


def _step_display_label(step_key: str) -> str:
    try:
        return str(get_step_definition(step_key).get("label") or step_key)
    except KeyError:
        return step_key


def _coerce_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default
