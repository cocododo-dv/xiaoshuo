from __future__ import annotations

import uuid
from copy import deepcopy
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from novel_system.db.models import (
    AuthorDraft,
    ChapterGoal,
    FinalScene,
    LlmCall,
    OperationLog,
    OutlinePlan,
    SceneCard,
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
from novel_system.services.author_actions import author_action
from novel_system.services.errors import DomainError
from novel_system.services.projects import PLAN_STATUS_PENDING_REVIEW, ProjectService, outline_plan_payload, project_payload
from novel_system.services.project_runtime_invalidation import ProjectRuntimeInvalidationService
from novel_system.services.snowflake_planner import GATE_STATUSES, SnowflakePlannerService
from novel_system.services.snowflake_staleness import (
    field_sigs,
    recompute_stale,
    snapshot_consumed_sigs,
)
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
    # P1-1: scene_id / chapter_id are system-minted identity, never author-editable.
    # chapter_title / chapter_goal / chapter_role stay editable (content, not identity).
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
        items = [
            item
            for item in rows.get("items") or []
            if str(item.get("planning_mode") or "") == "snowflake"
        ]
        # FE-ALIGN P2: 切换器/主页需要每部作品的统计摘要（只读派生，D2 服务端计算）。
        from novel_system.services.writing_stats import WritingStatsService

        stats = WritingStatsService(self.session)
        for item in items:
            project_id = item.get("project_id")
            item["stats"] = stats.stats_payload(project_id)
            item["chapters_written"] = self._chapters_written(project_id)
        return {"items": items}

    def _chapters_written(self, project_id: str) -> int:
        chapters = self.session.execute(
            select(ChapterGoal).where(
                ChapterGoal.project_id == project_id, ChapterGoal.trashed_flag == 0
            )
        ).scalars().all()
        written = 0
        for chapter in chapters:
            display = dict((chapter.writer_brief_json or {}).get("fe_display") or {})
            if int(display.get("pct") or 0) > 0:
                written += 1
        return written

    def create_project(self, payload: dict[str, Any]) -> dict[str, Any]:
        result = self._projects.create({**(payload or {}), "planning_mode": "snowflake", "snowflake_workflow_mode": (payload or {}).get("snowflake_workflow_mode") or "explore"})
        project = result["project"]
        return {
            "project": project,
            "workspace": self.workspace(project["project_id"]),
        }

    def workspace(self, project_id: str) -> dict[str, Any]:
        project = self._require_snowflake_project(project_id)
        latest_by_step = self._latest_by_step(project_id)
        current_step_key = self._current_step_key(latest_by_step)
        scene_plans = self._scene_plans(project_id)
        scene_board = self._scene_board(project_id, scene_plans=scene_plans)
        triage_items = self._triage_items(project_id)
        latest_plan = self._latest_plan(project_id)
        steps = [self._workspace_step(step, latest_by_step, project_id=project_id) for step in list_step_definitions()]
        gate = self._materialization_gate(latest_by_step, triage_items, scene_plans)
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
            "resync_status": self._resync_status(project.project_id, scene_plans),
            "steps": steps,
        }

    def generate_step(self, project_id: str, step_key: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        project = self._require_snowflake_project(project_id)
        body = payload or {}
        self._require_step(step_key)
        latest_by_step = self._latest_by_step(project.project_id)
        if self._draft_gate_mode(project) == "strict":
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
        if self._draft_gate_mode(project) == "strict":
            self._require_previous_gates(step_key, latest_by_step)
        draft = merge_step_draft(step_key, body.get("draft") or {}, latest_by_step=latest_by_step)
        latest = latest_by_step.get(step_key)

        if latest is not None and latest.status == "pending_review":
            run = latest
            run.draft_json = draft
            run.input_refs_json = self._input_refs(step_key, latest_by_step)
            run.health_json = self._step_health(step_key, draft, "pending_review", generation_source="author")
            run.stale_reason = None
            run.stale_accepted_at = None
            run.stale_accepted_by = None
            run.stale_accepted_note = None
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

    def step_history(self, project_id: str, step_key: str, *, include_draft: bool = False) -> dict[str, Any]:
        project = self._require_snowflake_project(project_id)
        self._require_step(step_key)
        rows = self.session.execute(
            select(SnowflakeStepRun)
            .where(SnowflakeStepRun.project_id == project.project_id, SnowflakeStepRun.step_key == step_key)
            .order_by(SnowflakeStepRun.version.desc(), SnowflakeStepRun.updated_at.desc(), SnowflakeStepRun.created_at.desc())
        ).scalars().all()
        return {
            "project_id": project.project_id,
            "step_key": step_key,
            "items": [self._step_run_history_payload(row, include_draft=include_draft) for row in rows],
        }

    def restore_step(self, project_id: str, step_key: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        project = self._require_snowflake_project(project_id)
        body = payload or {}
        self._require_step(step_key)
        source_run_id = str(body.get("step_run_id") or "").strip()
        if not source_run_id:
            raise DomainError("SNOWFLAKE_STEP_RUN_REQUIRED", "step_run_id is required", status_code=400)
        source_run = self.session.get(SnowflakeStepRun, source_run_id)
        if source_run is None or source_run.project_id != project.project_id or source_run.step_key != step_key:
            raise DomainError("SNOWFLAKE_STEP_RUN_NOT_FOUND", "snowflake step run does not belong to this project step", status_code=404)
        latest_by_step = self._latest_by_step(project.project_id)
        if self._draft_gate_mode(project) == "strict":
            self._require_previous_gates(step_key, latest_by_step)
        draft = deepcopy(source_run.draft_json or {})
        refs = self._input_refs(step_key, latest_by_step)
        refs["restored_from_step_run_id"] = source_run.step_run_id
        run = SnowflakeStepRun(
            step_run_id=f"snowflake_step_run_{project.project_id}_{step_key}_{uuid.uuid4().hex[:10]}",
            project_id=project.project_id,
            step_key=step_key,
            version=self._next_step_version(project.project_id, step_key),
            status="pending_review",
            draft_json=draft,
            health_json=self._step_health(step_key, draft, "pending_review", generation_source="history_restore"),
            input_refs_json=refs,
        )
        self.session.add(run)
        self.session.flush()
        self._sync_structured_step_data(project, step_key, draft, run)
        self.session.flush()
        workspace = self.workspace(project.project_id)
        step_run = self._step_run_payload(run) or {}
        step_run["restored_from_step_run_id"] = source_run.step_run_id
        return {
            "step": self._step_from_workspace(workspace, step_key),
            "workspace": workspace,
            "step_run": step_run,
            "restored_from": self._step_run_history_payload(source_run, include_draft=False),
        }

    def import_discovery_steps(
        self,
        project_id: str,
        step_drafts: dict[str, Any],
        *,
        actor_ref: str = "operator",
    ) -> dict[str, Any]:
        del actor_ref
        project = self._require_snowflake_project(project_id)
        allowed_order = [
            "book_brief",
            "one_sentence_summary",
            "one_paragraph_summary",
            "character_sheets",
            "character_synopses",
            "scene_list",
            "scene_details",
        ]
        latest_by_step = self._latest_by_step(project.project_id)
        imported_runs: list[SnowflakeStepRun] = []
        for step_key in allowed_order:
            raw_draft = step_drafts.get(step_key)
            if not isinstance(raw_draft, dict):
                continue
            self._require_step(step_key)
            latest = latest_by_step.get(step_key)
            if step_key in {"character_sheets", "character_synopses", "character_bibles"}:
                raw_draft = self._merge_character_import_draft(latest.draft_json if latest else {}, raw_draft)
            draft = merge_step_draft(step_key, raw_draft, latest_by_step=latest_by_step)
            if latest is not None and latest.status == "pending_review":
                run = latest
                run.draft_json = draft
                run.input_refs_json = self._input_refs(step_key, latest_by_step)
                run.health_json = self._step_health(step_key, draft, "pending_review", generation_source="author_discovery")
                run.stale_reason = None
                run.stale_accepted_at = None
                run.stale_accepted_by = None
                run.stale_accepted_note = None
            else:
                run = SnowflakeStepRun(
                    step_run_id=f"snowflake_step_run_{project.project_id}_{step_key}_{uuid.uuid4().hex[:10]}",
                    project_id=project.project_id,
                    step_key=step_key,
                    version=self._next_step_version(project.project_id, step_key),
                    status="pending_review",
                    draft_json=draft,
                    health_json=self._step_health(step_key, draft, "pending_review", generation_source="author_discovery"),
                    input_refs_json=self._input_refs(step_key, latest_by_step),
                )
                self.session.add(run)
            self.session.flush()
            self._sync_structured_step_data(project, step_key, draft, run)
            latest_by_step[step_key] = run
            imported_runs.append(run)
        self.session.flush()
        workspace = self.workspace(project.project_id)
        return {
            "imported_step_keys": [run.step_key for run in imported_runs],
            "step_runs": [self._step_run_payload(run) for run in imported_runs],
            "workspace": workspace,
        }

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
        previous_run = self._latest_approved_step_run(project.project_id, step_key, exclude_step_run_id=run.step_run_id)
        self._supersede_same_step(run)
        run.status = "approved"
        run.approved_at = utcnow()
        run.health_json = self._step_health(step_key, run.draft_json or {}, "approved", generation_source=(run.health_json or {}).get("generation_source"))
        # Snapshot "what I consumed, at what version" so a later upstream revision can
        # be diffed field-by-field instead of blindly staling everything downstream.
        run.consumed_input_sigs_json = snapshot_consumed_sigs(
            latest_by_step, list(self._input_refs(step_key, latest_by_step).keys())
        )
        self._sync_structured_step_data(project, step_key, run.draft_json or {}, run, approved=True)
        downstream_impact = self._mark_downstream_stale(run)
        runtime_impact = (
            ProjectRuntimeInvalidationService(self.session).invalidate_for_snowflake_step(
                project.project_id,
                step_key,
                previous_payload=previous_run.draft_json if previous_run is not None else None,
                current_payload=run.draft_json or {},
            )
            if previous_run is not None
            else {
                "step_key": step_key,
                "scope": "none",
                "broad": False,
                "affected_count": 0,
                "affected_scene_ids": [],
                "summary": "First approval has no stale runtime scope.",
            }
        )
        self.session.flush()
        workspace = self.workspace(project.project_id)
        return {
            "step": self._step_from_workspace(workspace, step_key),
            "workspace": workspace,
            "impact": self._combine_approval_impact(step_key, downstream_impact, runtime_impact),
        }

    def accept_stale_step(self, project_id: str, step_key: str, payload: dict[str, Any] | None = None, *, actor_ref: str = "operator") -> dict[str, Any]:
        project = self._require_snowflake_project(project_id)
        self._require_step(step_key)
        run = self._latest_by_step(project.project_id).get(step_key)
        if run is None:
            raise DomainError("SNOWFLAKE_STEP_RUN_NOT_FOUND", "no draft exists for this snowflake step", status_code=404)
        if run.status != "stale":
            raise DomainError("SNOWFLAKE_STEP_NOT_STALE", "only stale snowflake steps can be accepted as still valid", status_code=409)
        body = payload or {}
        note = str(body.get("note") or "").strip() or None
        accepted_at = utcnow()
        run.stale_accepted_at = accepted_at
        run.stale_accepted_by = actor_ref or "operator"
        run.stale_accepted_note = note
        self.session.add(
            OperationLog(
                event_type="snowflake_step_stale_accepted",
                object_type="snowflake_step_run",
                object_ref=run.step_run_id,
                payload_json={
                    "project_id": project.project_id,
                    "step_key": step_key,
                    "accepted_at": accepted_at,
                    "accepted_by": actor_ref or "operator",
                    "note": note or "",
                    "stale_reason": run.stale_reason or "",
                },
            )
        )
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

    def accept_stale_scenes(self, project_id: str, payload: dict[str, Any] | None = None, *, actor_ref: str = "operator") -> dict[str, Any]:
        project = self._require_snowflake_project(project_id)
        body = payload or {}
        requested_ids = [str(item or "").strip() for item in body.get("scene_plan_ids") or [] if str(item or "").strip()]
        scenes = self._scene_plans(project.project_id)
        if requested_ids:
            requested = set(requested_ids)
            scenes = [scene for scene in scenes if scene.scene_plan_id in requested]
        if not scenes:
            raise DomainError("SNOWFLAKE_STALE_SCENES_NOT_FOUND", "no matching scene plans found", status_code=404)
        note = str(body.get("note") or "").strip() or None
        accepted_at = utcnow()
        accepted: list[dict[str, Any]] = []
        for scene in scenes:
            if scene.status != "stale":
                continue
            scene.stale_accepted_at = accepted_at
            scene.stale_accepted_by = actor_ref or "operator"
            scene.stale_accepted_note = note
            accepted.append(_scene_plan_payload(scene))
            self.session.add(
                OperationLog(
                    event_type="snowflake_scene_stale_accepted",
                    object_type="snowflake_scene_plan",
                    object_ref=scene.scene_plan_id,
                    payload_json={
                        "project_id": project.project_id,
                        "scene_id": scene.scene_id,
                        "scene_plan_id": scene.scene_plan_id,
                        "accepted_at": accepted_at,
                        "accepted_by": actor_ref or "operator",
                        "note": note or "",
                        "stale_reason": scene.stale_reason or "",
                    },
                )
            )
        if not accepted:
            raise DomainError("SNOWFLAKE_SCENES_NOT_STALE", "no matching stale scene plans found", status_code=409)
        self.session.flush()
        return {"accepted_scenes": accepted, "workspace": self.workspace(project.project_id)}

    def update_scene_plan(self, project_id: str, scene_plan_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        project = self._require_snowflake_project(project_id)
        scene = self.session.get(SnowflakeScenePlan, scene_plan_id)
        if scene is None or scene.project_id != project.project_id:
            raise DomainError("SNOWFLAKE_SCENE_PLAN_NOT_FOUND", "scene plan not found", status_code=404)
        self._apply_scene_patch(scene, _sanitize_scene_patch(payload or {}))
        scene.status = "draft" if scene.status in {"approved", "stale"} else scene.status
        scene.stale_accepted_at = None
        scene.stale_accepted_by = None
        scene.stale_accepted_note = None
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

    def resync_materialized_scenes(
        self,
        project_id: str,
        payload: dict[str, Any] | None = None,
        *,
        actor_ref: str = "operator",
    ) -> dict[str, Any]:
        project = self._require_snowflake_project(project_id)
        body = payload or {}
        dry_run = bool(body.get("dry_run", False))
        requested_plan_ids = {
            str(item or "").strip()
            for item in body.get("scene_plan_ids") or []
            if str(item or "").strip()
        }
        requested_scene_ids = {
            str(item or "").strip()
            for item in body.get("scene_ids") or []
            if str(item or "").strip()
        }
        plans = self._scene_plans(project.project_id)
        if requested_plan_ids:
            plans = [plan for plan in plans if plan.scene_plan_id in requested_plan_ids]
        if requested_scene_ids:
            plans = [plan for plan in plans if plan.scene_id in requested_scene_ids]
        if not plans:
            raise DomainError("SNOWFLAKE_RESYNC_SCENES_NOT_FOUND", "no matching scene plans found", status_code=404)

        results: list[dict[str, Any]] = []
        affected_scene_ids: list[str] = []
        for plan in plans:
            scene = self.session.get(SceneCard, plan.scene_id)
            if scene is None or scene.project_id != project.project_id:
                results.append(
                    {
                        "scene_plan_id": plan.scene_plan_id,
                        "scene_id": plan.scene_id,
                        "synced": False,
                        "reason": "scene_not_materialized",
                        "diff": {},
                    }
                )
                continue
            chapter = self.session.get(ChapterGoal, scene.chapter_id)
            scene_patch = self._scene_card_resync_patch(plan, scene)
            diff = self._scene_card_diff(scene, scene_patch)
            if diff:
                affected_scene_ids.append(scene.scene_id)
            if not dry_run and diff:
                self._apply_scene_card_resync(scene, scene_patch)
                if chapter is not None:
                    chapter.writer_brief_json = {
                        **dict(chapter.writer_brief_json or {}),
                        "source": "snowflake_resync",
                        "project_id": project.project_id,
                        "chapter_id": plan.chapter_id,
                        "chapter_goal": plan.chapter_goal or chapter.chapter_goal,
                    }
                    if plan.chapter_goal:
                        chapter.chapter_goal = plan.chapter_goal
                self.session.add(
                    OperationLog(
                        event_type="snowflake_scene_resynced",
                        object_type="scene_card",
                        object_ref=scene.scene_id,
                        payload_json={
                            "project_id": project.project_id,
                            "scene_id": scene.scene_id,
                            "scene_plan_id": plan.scene_plan_id,
                            "dry_run": False,
                            "diff_fields": sorted(diff.keys()),
                            "actor_ref": actor_ref or "operator",
                        },
                    )
                )
            results.append(
                {
                    "scene_plan_id": plan.scene_plan_id,
                    "scene_id": scene.scene_id,
                    "synced": bool(diff) and not dry_run,
                    "reason": "changed" if diff else "already_current",
                    "diff": diff,
                }
            )

        if not dry_run:
            self.session.flush()
        affected_runtime = self._affected_runtime_summary(project.project_id, affected_scene_ids)
        return {
            "dry_run": dry_run,
            "results": results,
            "affected_runtime": affected_runtime,
            "workspace": self.workspace(project.project_id),
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
        approval_blockers = self._previous_gate_blockers(step["step_key"], latest_by_step)
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
            "stale_accepted_at": run.stale_accepted_at if run is not None else None,
            "stale_accepted_by": run.stale_accepted_by if run is not None else "",
            "stale_accepted_note": run.stale_accepted_note if run is not None else "",
            "can_skip": bool(step.get("skippable")),
            "can_confirm": bool(run is not None and run.status == "pending_review" and not approval_blockers),
            "approval_blockers": approval_blockers,
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
        if run is None:
            return False
        if run.status in STRUCTURED_GATE_STATUSES:
            return True
        return run.status == "stale" and bool(run.stale_accepted_at)

    def _current_step_key(self, latest_by_step: dict[str, SnowflakeStepRun]) -> str | None:
        for step in list_step_definitions():
            if not self._gate_satisfied(step["step_key"], latest_by_step):
                return step["step_key"]
        return None

    @staticmethod
    def _draft_gate_mode(project: StoryProject) -> str:
        mode = str(getattr(project, "snowflake_workflow_mode", "strict") or "strict").strip().lower()
        return "explore" if mode == "explore" else "strict"

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
        blockers = []
        for step in list_step_definitions()[:step_index]:
            run = latest_by_step.get(step["step_key"])
            if allow_self and run is not None and run.step_run_id == allow_self:
                continue
            if not self._gate_satisfied(step["step_key"], latest_by_step):
                blockers.append({"step_key": step["step_key"], "label": step["label"]})
        if blockers:
            first = blockers[0]
            raise DomainError(
                "SNOWFLAKE_PREVIOUS_STEP_REQUIRED",
                "previous snowflake steps must be approved first",
                status_code=409,
                details={
                    "missing_previous_steps": blockers,
                    "author_action": author_action(
                        f"还差{first['label']}",
                        f"先确认「{first['label']}」，再确认当前雪花步骤。你可以继续写草稿，但确认和物化仍会守住依赖。",
                        target_view="snowflake-workbench",
                        target_ref=f"snowflake_step:{first['step_key']}",
                        primary_button_label=f"去补{first['label']}",
                        evidence_summary=[f"缺少上游步骤：{first['label']}"],
                    ),
                },
            )

    def _previous_gate_blockers(
        self,
        step_key: str,
        latest_by_step: dict[str, SnowflakeStepRun],
    ) -> list[dict[str, str]]:
        blockers: list[dict[str, str]] = []
        for step in list_step_definitions()[: STEP_ORDER[step_key]]:
            if not self._gate_satisfied(step["step_key"], latest_by_step):
                blockers.append({"step_key": step["step_key"], "label": step["label"]})
        return blockers

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
            if run is not None and self._gate_satisfied(step["step_key"], latest_by_step):
                refs[step["step_key"]] = run.step_run_id
        return refs

    def _next_step_version(self, project_id: str, step_key: str) -> int:
        latest = self.session.execute(
            select(SnowflakeStepRun.version)
            .where(SnowflakeStepRun.project_id == project_id, SnowflakeStepRun.step_key == step_key)
            .order_by(SnowflakeStepRun.version.desc())
        ).scalar()
        return int(latest or 0) + 1

    def _latest_approved_step_run(
        self,
        project_id: str,
        step_key: str,
        *,
        exclude_step_run_id: str,
    ) -> SnowflakeStepRun | None:
        return self.session.execute(
            select(SnowflakeStepRun)
            .where(
                SnowflakeStepRun.project_id == project_id,
                SnowflakeStepRun.step_key == step_key,
                SnowflakeStepRun.step_run_id != exclude_step_run_id,
                SnowflakeStepRun.status.in_(["approved", "skipped"]),
            )
            .order_by(SnowflakeStepRun.version.desc(), SnowflakeStepRun.created_at.desc())
        ).scalars().first()

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

    def _scene_board(self, project_id: str, *, scene_plans: list[SnowflakeScenePlan] | None = None) -> dict[str, Any]:
        scenes = [_scene_plan_payload(scene) for scene in (scene_plans if scene_plans is not None else self._scene_plans(project_id))]
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

    def _resync_status(self, project_id: str, scene_plans: list[SnowflakeScenePlan]) -> dict[str, Any]:
        pending: list[dict[str, Any]] = []
        for plan in scene_plans:
            scene = self.session.get(SceneCard, plan.scene_id)
            if scene is None or scene.project_id != project_id:
                continue
            diff = self._scene_card_diff(scene, self._scene_card_resync_patch(plan, scene))
            if not diff:
                continue
            pending.append(
                {
                    "scene_plan_id": plan.scene_plan_id,
                    "scene_id": plan.scene_id,
                    "title": plan.title or plan.summary or plan.scene_id,
                    "changed_fields": sorted(diff.keys()),
                }
            )
        return {
            "pending_count": len(pending),
            "pending_scene_plan_ids": [item["scene_plan_id"] for item in pending],
            "pending_scenes": pending,
        }

    @staticmethod
    def _scene_card_resync_patch(plan: SnowflakeScenePlan, scene: SceneCard) -> dict[str, Any]:
        brief = {
            **dict(scene.writer_brief_json or {}),
            "source": "snowflake_resync",
            "scene_plan_id": plan.scene_plan_id,
            "project_id": plan.project_id,
            "chapter_id": plan.chapter_id,
            "scene_id": plan.scene_id,
            "chapter_goal": plan.chapter_goal,
            "scene_crucible": plan.scene_crucible,
            "goal": plan.goal,
            "conflict": plan.conflict,
            "setback": plan.setback,
            "reaction": plan.reaction,
            "dilemma": plan.dilemma,
            "decision": plan.decision,
            "primary_form": plan.scene_type,
        }
        beats = list(plan.beats_json or [])
        if not beats:
            beats = [
                item
                for item in [plan.goal, plan.conflict, plan.setback or plan.decision, plan.hook]
                if str(item or "").strip()
            ]
        return {
            "scene_goal": plan.summary or plan.goal or scene.scene_goal,
            "beats_json": beats or list(scene.beats_json or []),
            "must_include_text": plan.must_include_text or scene.must_include_text,
            "exit_change": plan.exit_change or plan.setback or plan.decision or scene.exit_change,
            "hook": plan.hook or scene.hook,
            "target_length_band": plan.target_length_band or scene.target_length_band,
            "scene_type": plan.scene_type or scene.scene_type,
            "pov_character_id": plan.pov_character_id or scene.pov_character_id,
            "onstage_chars_json": list(plan.onstage_chars_json or scene.onstage_chars_json or []),
            "location": plan.location or scene.location,
            "writer_brief_json": brief,
        }

    @staticmethod
    def _scene_card_diff(scene: SceneCard, patch: dict[str, Any]) -> dict[str, dict[str, Any]]:
        diff: dict[str, dict[str, Any]] = {}
        for field, after in patch.items():
            before = getattr(scene, field)
            if before != after:
                diff[field] = {"before": before, "after": after}
        return diff

    @staticmethod
    def _apply_scene_card_resync(scene: SceneCard, patch: dict[str, Any]) -> None:
        for field, value in patch.items():
            setattr(scene, field, value)

    def _affected_runtime_summary(self, project_id: str, scene_ids: list[str]) -> dict[str, int]:
        unique_scene_ids = list(dict.fromkeys(scene_ids))
        if not unique_scene_ids:
            return {"final_scene_count": 0, "author_draft_count": 0, "llm_call_count": 0}
        final_scene_count = self.session.query(FinalScene).filter(FinalScene.scene_id.in_(unique_scene_ids)).count()
        author_draft_count = self.session.query(AuthorDraft).filter(
            AuthorDraft.object_type == "scene",
            AuthorDraft.object_id.in_(unique_scene_ids),
        ).count()
        llm_call_count = self.session.query(LlmCall).filter(
            LlmCall.project_id == project_id,
            LlmCall.scene_id.in_(unique_scene_ids),
        ).count()
        return {
            "final_scene_count": final_scene_count,
            "author_draft_count": author_draft_count,
            "llm_call_count": llm_call_count,
        }

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
    def _materialization_gate(
        latest_by_step: dict[str, SnowflakeStepRun],
        triage_items: list[dict[str, Any]],
        scene_plans: list[SnowflakeScenePlan] | None = None,
    ) -> dict[str, Any]:
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
                    severity="warning",
                    kind="skipped_required_step",
                    message=f"{step_label} 已跳过；可以继续整理，但建议在生成章节前复核这一层是否仍需要补齐。",
                    step_key=step_key,
                )
                continue
            if run.status == "stale" and run.stale_accepted_at:
                add_step_item(
                    severity="warning",
                    kind="accepted_stale_required_step",
                    message=f"{step_label} was marked stale, but the current draft was reviewed and accepted.",
                    step_key=step_key,
                )
            if run.status not in STRUCTURED_GATE_STATUSES and not (run.status == "stale" and run.stale_accepted_at):
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
            if run.status == "stale" and run.stale_accepted_at:
                add_step_item(
                    severity="warning",
                    kind="accepted_stale_optional_step",
                    message=f"{step_label} was marked stale, but the current draft was reviewed and accepted.",
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
        for scene in scene_plans or []:
            if scene.status != "stale":
                continue
            scene_label = str(scene.title or scene.summary or scene.scene_id or "scene").strip()
            item = _scene_plan_payload(scene)
            if scene.stale_accepted_at:
                add_scene_item(
                    severity="warning",
                    kind="accepted_stale_scene_plan",
                    message=f"{scene_label} was marked stale, but the current scene plan was reviewed and accepted.",
                    item=item,
                )
                continue
            add_scene_item(
                severity="blocker",
                kind="stale_scene_plan",
                message=f"{scene_label} needs review before the chapter structure is materialized.",
                item=item,
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
        minted = False
        for index, item in enumerate(scenes, start=1):
            if not isinstance(item, dict):
                continue
            # Identity is anchored on the immutable row_uid (P1-1). Fall back to the
            # legacy scene_id lookup so step-9 drafts and pre-migration rows still
            # bind to the plan that step-8 seeded — but never trust an author's edit
            # of scene_id / chapter_id to *re-key* an existing row.
            row_uid = str(item.get("row_uid") or "").strip()
            plan = self._scene_plan_by_row_uid(project_id, row_uid) if row_uid else None
            if plan is None:
                incoming_scene_id = str(item.get("scene_id") or "").strip()
                plan = self._scene_plan_by_scene_id(project_id, incoming_scene_id) if incoming_scene_id else None
            created = plan is None

            input_chapter_id = str(item.get("chapter_id") or current_chapter_id or f"{project_id}_CH01").strip()
            if created:
                # First time we see this row — mint its identity exactly once.
                chapter_id = input_chapter_id
            else:
                # Already exists — system identity is locked, author input is ignored.
                chapter_id = plan.chapter_id or input_chapter_id
            current_chapter_id = chapter_id

            next_seq = seq_by_chapter.get(chapter_id, 0) + 1
            scene_seq = _coerce_int(item.get("scene_seq"), next_seq)
            seq_by_chapter[chapter_id] = scene_seq

            if created:
                row_uid = row_uid or _mint_row_uid()
                scene_id = f"{chapter_id}_SC{scene_seq:02d}"
                plan = SnowflakeScenePlan(
                    scene_plan_id=f"snowflake_scene_plan_{project_id}_{row_uid}",
                    project_id=project_id,
                    row_uid=row_uid,
                    scene_id=scene_id,
                    chapter_id=chapter_id,
                    scene_seq=scene_seq,
                )
                self.session.add(plan)
                minted = True
            else:
                scene_id = plan.scene_id
                if not plan.row_uid:
                    # Adopt a row_uid for a legacy row matched via scene_id.
                    plan.row_uid = row_uid or _mint_row_uid()
                    minted = True
                row_uid = plan.row_uid

            plan.scene_seq = scene_seq
            plan.source_step_run_id = run.step_run_id
            plan.status = "approved" if approved else "draft"
            plan.stale_reason = None
            plan.stale_accepted_at = None
            plan.stale_accepted_by = None
            plan.stale_accepted_note = None
            # Discard any author-supplied scene_id / chapter_id — those are system
            # identity, not editable narrative fields.
            patch = _sanitize_scene_patch(item)
            patch.pop("scene_id", None)
            patch.pop("chapter_id", None)
            self._apply_scene_patch(plan, patch)
            if created and not plan.title:
                plan.title = str(item.get("title") or item.get("summary") or f"场景 {index:02d}").strip()
            if created and not plan.chapter_title:
                plan.chapter_title = str(item.get("chapter_title") or chapter_id).strip()
            plan.diagnosis_json = diagnose_scene_detail(_scene_plan_payload(plan))

            # Stamp the minted identity back onto the draft row so the persisted
            # draft_json and every later re-seed carry the same stable anchor.
            if item.get("row_uid") != row_uid or item.get("scene_id") != scene_id or item.get("chapter_id") != chapter_id:
                item["row_uid"] = row_uid
                item["scene_id"] = scene_id
                item["chapter_id"] = chapter_id
                minted = True

        if minted and isinstance(run.draft_json, dict):
            run.draft_json = {**run.draft_json, "scenes": scenes}

    def _scene_plan_by_scene_id(self, project_id: str, scene_id: str) -> SnowflakeScenePlan | None:
        return self.session.execute(
            select(SnowflakeScenePlan).where(SnowflakeScenePlan.project_id == project_id, SnowflakeScenePlan.scene_id == scene_id)
        ).scalars().first()

    def _scene_plan_by_row_uid(self, project_id: str, row_uid: str) -> SnowflakeScenePlan | None:
        if not row_uid:
            return None
        return self.session.execute(
            select(SnowflakeScenePlan).where(SnowflakeScenePlan.project_id == project_id, SnowflakeScenePlan.row_uid == row_uid)
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

    def _mark_downstream_stale(self, run: SnowflakeStepRun) -> dict[str, Any]:
        # P0-3: a single dependency/diff-aware judgment replaces the old "stale every
        # later step" loop. Only steps whose approval snapshot of THIS step's consumed
        # fields actually changed are marked — revising a step no longer punishes
        # downstream work that did not depend on what changed.
        candidates = self.session.execute(
            select(SnowflakeStepRun).where(
                SnowflakeStepRun.project_id == run.project_id,
                SnowflakeStepRun.step_run_id != run.step_run_id,
                SnowflakeStepRun.status.in_(["pending_review", "approved", "skipped"]),
            )
        ).scalars().all()
        hits = recompute_stale(
            changed_step_key=run.step_key,
            current_field_sigs=field_sigs(run.draft_json or {}),
            candidate_rows=candidates,
            step_order=STEP_ORDER,
        )

        affected_step_run_ids: list[str] = []
        affected_scene_plan_ids: list[str] = []
        stale_step_keys: set[str] = set()
        for hit in hits:
            row = hit.row
            row.status = "stale"
            row.stale_reason = hit.reason
            row.stale_accepted_at = None
            row.stale_accepted_by = None
            row.stale_accepted_note = None
            affected_step_run_ids.append(row.step_run_id)
            stale_step_keys.add(row.step_key)
            self._record_revision_link(run, affected_kind="step_run", affected_id=row.step_run_id, reason=hit.reason)

        # Scene plans are the materialized output of scene_list / scene_details, so they
        # only go stale when one of those steps is itself affected — not on every change
        # that happens to sit upstream of scene_list.
        if stale_step_keys & {"scene_list", "scene_details"}:
            reason = f"{run.step_key} 改动影响了场景列表，复核场景计划。"
            for scene in self._scene_plans(run.project_id):
                scene.status = "stale"
                scene.stale_reason = reason
                scene.stale_accepted_at = None
                scene.stale_accepted_by = None
                scene.stale_accepted_note = None
                affected_scene_plan_ids.append(scene.scene_plan_id)
                self._record_revision_link(run, affected_kind="scene_plan", affected_id=scene.scene_plan_id, reason=reason)

        summary = (
            f"{run.step_key} 改动影响 {len(affected_step_run_ids)} 个下游步骤、"
            f"{len(affected_scene_plan_ids)} 个场景计划。"
            if affected_step_run_ids or affected_scene_plan_ids
            else "No downstream snowflake artifacts are affected."
        )
        return {
            "step_key": run.step_key,
            "affected_count": len(affected_step_run_ids) + len(affected_scene_plan_ids),
            "affected_step_run_ids": affected_step_run_ids,
            "affected_scene_plan_ids": affected_scene_plan_ids,
            "summary": summary,
        }

    @staticmethod
    def _combine_approval_impact(
        step_key: str,
        downstream_impact: dict[str, Any],
        runtime_impact: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "step_key": step_key,
            "affected_count": int(downstream_impact.get("affected_count") or 0)
            + int(runtime_impact.get("affected_count") or 0),
            "downstream": downstream_impact,
            "runtime": runtime_impact,
            "summary": "; ".join(
                part
                for part in [
                    str(downstream_impact.get("summary") or "").strip(),
                    str(runtime_impact.get("summary") or "").strip(),
                ]
                if part
            ),
        }

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
            "stale_reason": run.stale_reason,
            "stale_accepted_at": run.stale_accepted_at,
            "stale_accepted_by": run.stale_accepted_by,
            "stale_accepted_note": run.stale_accepted_note,
            "created_at": run.created_at,
            "updated_at": run.updated_at,
        }

    @staticmethod
    def _step_run_history_payload(run: SnowflakeStepRun, *, include_draft: bool = False) -> dict[str, Any]:
        payload = {
            "step_run_id": run.step_run_id,
            "version": run.version,
            "status": run.status,
            "created_at": run.created_at,
            "updated_at": run.updated_at,
            "approved_at": run.approved_at,
            "stale_reason": run.stale_reason,
            "stale_accepted_at": run.stale_accepted_at,
            "stale_accepted_by": run.stale_accepted_by,
            "stale_accepted_note": run.stale_accepted_note,
            "generation_source": str((run.health_json or {}).get("generation_source") or ""),
            "draft_summary": _draft_summary(run.draft_json or {}),
        }
        if include_draft:
            payload["draft"] = deepcopy(run.draft_json or {})
        return payload

    @staticmethod
    def _merge_character_import_draft(existing: dict[str, Any] | None, incoming: dict[str, Any]) -> dict[str, Any]:
        existing_characters = existing.get("characters") if isinstance(existing, dict) else None
        incoming_characters = incoming.get("characters") if isinstance(incoming, dict) else None
        if not isinstance(existing_characters, list) or not isinstance(incoming_characters, list):
            return deepcopy(incoming)
        existing_by_id: dict[str, dict[str, Any]] = {}
        merged_characters: list[dict[str, Any]] = []
        for item in existing_characters:
            if not isinstance(item, dict):
                continue
            cloned = deepcopy(item)
            identity = _character_identity(cloned)
            if identity:
                existing_by_id[identity] = cloned
            merged_characters.append(cloned)
        for item in incoming_characters:
            if not isinstance(item, dict):
                continue
            identity = _character_identity(item)
            if not identity or identity not in existing_by_id:
                cloned = deepcopy(item)
                merged_characters.append(cloned)
                if identity:
                    existing_by_id[identity] = cloned
                continue
            merged_item = _merge_preserving_existing(existing_by_id[identity], item)
            existing_by_id[identity].clear()
            existing_by_id[identity].update(merged_item)
        return {
            **deepcopy(incoming),
            "characters": merged_characters,
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


def _draft_summary(value: Any, *, limit: int = 180) -> str:
    pieces: list[str] = []

    def visit(item: Any) -> None:
        if len(" ".join(pieces)) >= limit:
            return
        if isinstance(item, str):
            text = " ".join(item.split())
            if text:
                pieces.append(text)
            return
        if isinstance(item, list):
            for child in item[:8]:
                visit(child)
            return
        if isinstance(item, dict):
            for child in item.values():
                visit(child)

    visit(value)
    summary = " ".join(pieces)
    return summary[:limit].rstrip()


def _character_identity(item: dict[str, Any]) -> str:
    return str(item.get("character_id") or item.get("display_name") or item.get("name") or "").strip()


def _has_meaningful_value(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, tuple, set, dict)):
        return bool(value)
    return True


def _merge_preserving_existing(existing: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    merged = deepcopy(existing)
    for key, value in incoming.items():
        if not _has_meaningful_value(value):
            continue
        current = merged.get(key)
        if not _has_meaningful_value(current):
            merged[key] = deepcopy(value)
            continue
        if isinstance(current, dict) and isinstance(value, dict):
            merged[key] = _merge_preserving_existing(current, value)
        elif isinstance(current, list) and isinstance(value, list):
            merged[key] = current or deepcopy(value)
    return merged


def _scene_plan_payload(scene: SnowflakeScenePlan) -> dict[str, Any]:
    return {
        "scene_plan_id": scene.scene_plan_id,
        "row_uid": scene.row_uid or "",
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
        "stale_accepted_at": scene.stale_accepted_at,
        "stale_accepted_by": scene.stale_accepted_by or "",
        "stale_accepted_note": scene.stale_accepted_note or "",
        "diagnosis": deepcopy(scene.diagnosis_json or {}),
    }


def _scene_list_payload(scene: SnowflakeScenePlan) -> dict[str, Any]:
    return {
        "scene_plan_id": scene.scene_plan_id,
        "row_uid": scene.row_uid or "",
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


def _mint_row_uid() -> str:
    """Mint an immutable, system-owned scene-row identity (P1-1).

    Scene identity no longer derives from the author-editable ``scene_id``; this
    uuid is minted once when a row is first seen and then never changes, so a
    reorder or an ID re-mint can never orphan a plan or break the diff chain.
    """
    return f"row_{uuid.uuid4().hex}"
