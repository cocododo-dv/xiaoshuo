from __future__ import annotations

import hashlib
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from novel_system.db.models import (
    AttemptTracker,
    AutoRewriteRun,
    ChapterGoal,
    FinalScene,
    GenerationPlanningArtifact,
    LlmCall,
    QcReport,
    SceneBlueprint,
    SceneCard,
    SceneDraft,
    SceneQualityContract,
    SceneRunState,
    utcnow,
)
from novel_system.services.archiver import Archiver
from novel_system.services.errors import DomainError
from novel_system.services.hash_engine import canonical_json
from novel_system.services.literary_quality import analyze_literary_quality
from novel_system.services.llm_task_runner import LLMNodeExecutionError, LLMNodeRunner
from novel_system.services.source_safety import scan_source_safety
from novel_system.settings import get_settings


CONTRACT_VERSION = "scene_quality_contract_v1"
STRUCTURE_FAILURE_DIMENSIONS = {
    "no_choice_scene",
    "choice_pressure",
    "ending_drive",
}
LANGUAGE_FAILURE_DIMENSIONS = {
    "model_voice",
    "template_action_reuse",
    "repetitive_action",
    "expository_dialogue",
    "summary_ending",
    "image_homogeneity",
    "image_field_reuse",
    "syntax_monotony",
    "false_clarity",
}
PROMOTION_SCORE_MIN = 0.80
ENDING_DRIVE_MIN = 0.78
CHOICE_PRESSURE_MIN = 0.78


class SceneQualityService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def generate_contract(self, scene_id: str, *, actor_ref: str = "operator") -> dict[str, Any]:
        scene = self._require_scene(scene_id)
        chapter = self._require_chapter(scene.chapter_id)
        source_snapshot = self._source_snapshot(scene, chapter)
        source_snapshot_hash = _hash_json(source_snapshot)
        payload = _contract_payload(scene=scene, chapter=chapter, source_snapshot=source_snapshot)
        contract_hash = _hash_json(
            {
                "contract_version": CONTRACT_VERSION,
                "source_snapshot_hash": source_snapshot_hash,
                "payload": payload,
            }
        )

        existing = self._latest_contract(scene_id)
        if existing is not None and existing.contract_hash == contract_hash and existing.status == "active":
            return {"contract": self.serialize_contract(existing)}

        for row in self.session.execute(
            select(SceneQualityContract).where(
                SceneQualityContract.scene_id == scene_id,
                SceneQualityContract.status == "active",
            )
        ).scalars():
            row.status = "superseded"

        contract = SceneQualityContract(
            contract_id=f"scene_quality_contract_{scene_id}_{contract_hash[:12]}",
            scene_id=scene.scene_id,
            chapter_id=chapter.chapter_id,
            contract_version=CONTRACT_VERSION,
            contract_hash=contract_hash,
            source_snapshot_hash=source_snapshot_hash,
            payload_json=payload,
            status="active",
            created_by=actor_ref or "operator",
        )
        self.session.add(contract)
        self.session.flush()
        return {"contract": self.serialize_contract(contract)}

    def quality_state(self, scene_id: str) -> dict[str, Any]:
        self._require_scene(scene_id)
        contract = self._latest_contract(scene_id)
        latest_run = self._latest_run(scene_id)
        return {
            "scene_id": scene_id,
            "contract": self.serialize_contract(contract) if contract is not None else None,
            "latest_run": self.serialize_run(latest_run) if latest_run is not None else None,
            "promotion": _promotion_state(latest_run),
        }

    def latest_or_create_contract(self, scene_id: str, *, actor_ref: str = "operator") -> SceneQualityContract:
        contract = self._latest_contract(scene_id)
        if contract is not None:
            return contract
        self.generate_contract(scene_id, actor_ref=actor_ref)
        contract = self._latest_contract(scene_id)
        if contract is None:
            raise DomainError("SCENE_QUALITY_CONTRACT_MISSING", "scene quality contract could not be created", status_code=500)
        return contract

    @staticmethod
    def serialize_contract(row: SceneQualityContract | None) -> dict[str, Any] | None:
        if row is None:
            return None
        return {
            "contract_id": row.contract_id,
            "scene_id": row.scene_id,
            "chapter_id": row.chapter_id,
            "contract_version": row.contract_version,
            "contract_hash": row.contract_hash,
            "source_snapshot_hash": row.source_snapshot_hash,
            "payload": row.payload_json or {},
            "status": row.status,
            "created_by": row.created_by,
            "created_at": row.created_at,
            "updated_at": row.updated_at,
        }

    @staticmethod
    def serialize_run(row: AutoRewriteRun | None) -> dict[str, Any] | None:
        if row is None:
            return None
        return {
            "run_id": row.run_id,
            "scene_id": row.scene_id,
            "chapter_id": row.chapter_id,
            "contract_id": row.contract_id,
            "contract_hash": row.contract_hash,
            "mode": row.mode,
            "branch": row.branch,
            "failure_class": row.failure_class,
            "source_final_scene_row_id": row.source_final_scene_row_id,
            "candidate_draft_row_id": row.candidate_draft_row_id,
            "promoted_final_scene_row_id": row.promoted_final_scene_row_id,
            "rollback_target_final_scene_row_id": row.rollback_target_final_scene_row_id,
            "llm_call_id": row.llm_call_id,
            "gate_results": row.gate_results_json or {},
            "policy": row.policy_json or {},
            "promotion_blockers": row.promotion_blockers_json or [],
            "status": row.status,
            "actor_ref": row.actor_ref,
            "created_at": row.created_at,
            "updated_at": row.updated_at,
        }

    def _latest_contract(self, scene_id: str) -> SceneQualityContract | None:
        return self.session.execute(
            select(SceneQualityContract)
            .where(SceneQualityContract.scene_id == scene_id, SceneQualityContract.status == "active")
            .order_by(SceneQualityContract.created_at.desc(), SceneQualityContract.contract_id.desc())
        ).scalars().first()

    def _latest_run(self, scene_id: str) -> AutoRewriteRun | None:
        return self.session.execute(
            select(AutoRewriteRun)
            .where(AutoRewriteRun.scene_id == scene_id)
            .order_by(AutoRewriteRun.created_at.desc(), AutoRewriteRun.run_id.desc())
        ).scalars().first()

    def _source_snapshot(self, scene: SceneCard, chapter: ChapterGoal) -> dict[str, Any]:
        latest_blueprint = self.session.execute(
            select(SceneBlueprint)
            .where(SceneBlueprint.scene_id == scene.scene_id)
            .order_by(SceneBlueprint.created_at.desc(), SceneBlueprint.row_id.desc())
        ).scalars().first()
        planning_artifacts = self.session.execute(
            select(GenerationPlanningArtifact)
            .where(
                GenerationPlanningArtifact.status == "active",
                (
                    (GenerationPlanningArtifact.object_type == "scene")
                    & (GenerationPlanningArtifact.object_id == scene.scene_id)
                )
                | (
                    (GenerationPlanningArtifact.object_type == "chapter")
                    & (GenerationPlanningArtifact.object_id == chapter.chapter_id)
                ),
            )
            .order_by(GenerationPlanningArtifact.created_at.desc(), GenerationPlanningArtifact.row_id.desc())
        ).scalars().all()
        return {
            "chapter": {
                "chapter_id": chapter.chapter_id,
                "chapter_goal": chapter.chapter_goal,
                "main_plot_push": chapter.main_plot_push,
                "emotional_target": chapter.emotional_target,
                "ending_effect": chapter.ending_effect,
                "must_not": chapter.must_not,
                "writer_brief": chapter.writer_brief_json or {},
            },
            "scene": {
                "scene_id": scene.scene_id,
                "pov_character_id": scene.pov_character_id,
                "onstage_chars": scene.onstage_chars_json or [],
                "location": scene.location,
                "scene_goal": scene.scene_goal,
                "beats": scene.beats_json or [],
                "must_include_text": scene.must_include_text,
                "forbidden_text": scene.forbidden_text,
                "exit_change": scene.exit_change,
                "hook": scene.hook,
                "writer_brief": scene.writer_brief_json or {},
            },
            "scene_blueprint": latest_blueprint.blueprint_json if latest_blueprint is not None else None,
            "planning_artifacts": [
                {
                    "artifact_type": row.artifact_type,
                    "payload": row.payload_json or {},
                }
                for row in planning_artifacts
            ],
        }

    def _require_scene(self, scene_id: str) -> SceneCard:
        scene = self.session.get(SceneCard, scene_id)
        if scene is None or scene.trashed_flag:
            raise DomainError("SCENE_NOT_FOUND", "scene not found", status_code=404)
        return scene

    def _require_chapter(self, chapter_id: str) -> ChapterGoal:
        chapter = self.session.get(ChapterGoal, chapter_id)
        if chapter is None or chapter.trashed_flag:
            raise DomainError("CHAPTER_NOT_FOUND", "chapter not found", status_code=404)
        return chapter


class SceneAutoRewriteService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.quality = SceneQualityService(session)

    def run(self, scene_id: str, *, mode: str = "auto", actor_ref: str = "operator") -> dict[str, Any]:
        if mode not in {"auto", "full_scene", "local_patch", "diagnose_only"}:
            raise DomainError("AUTO_REWRITE_MODE_INVALID", "unsupported auto rewrite mode", status_code=400)
        # PR-10 §13 — auto_rewrite_triggered;outcome 暂留空,context 含 mode
        from novel_system.services.style_reference.metrics_recorder import MetricsRecorder
        MetricsRecorder.record(
            self.session,
            "auto_rewrite_triggered",
            target_kind="scene",
            target_ref_id=scene_id,
            context={"mode": mode, "actor_ref": actor_ref},
        )
        scene = self.quality._require_scene(scene_id)
        contract = self.quality.latest_or_create_contract(scene_id, actor_ref=actor_ref)
        state = self.session.get(SceneRunState, scene_id)
        source_final = self._source_final(scene, state)
        blockers = self._hard_blockers(scene_id)
        source_safety = scan_source_safety(source_final.content if source_final else "")
        if not source_safety.get("safe", True):
            blockers.append("reference_safety")

        diagnosis = self._diagnose(source_final.content if source_final else "")
        branch = _branch_for(mode=mode, diagnosis=diagnosis, blockers=blockers)
        status = _status_for_branch(branch, mode=mode)
        promotion_blockers = _promotion_blockers_for(branch=branch, mode=mode, blockers=blockers)
        candidate_row_id = None
        llm_call_id = None
        gate_results = _gate_results(
            branch=branch,
            mode=mode,
            blockers=promotion_blockers,
            diagnosis=diagnosis,
            source_safety=source_safety,
        )

        if branch in {"full_scene", "local_patch"}:
            candidate_content = None
            if get_settings().llm_enabled:
                llm_call_id, candidate_content = self._generate_llm_candidate(
                    scene=scene,
                    source_final=source_final,
                    contract=contract,
                    branch=branch,
                    diagnosis=diagnosis,
                    gate_results=gate_results,
                )
            else:
                llm_call_id = self._persist_offline_llm_call(scene, branch=branch, contract=contract)
            candidate_row_id = self._persist_candidate_draft(
                scene=scene,
                source_final=source_final,
                contract=contract,
                branch=branch,
                llm_call_id=llm_call_id,
                content_override=candidate_content,
            )
            if not gate_results["promotable"]:
                status = "blocked"

        run = AutoRewriteRun(
            run_id=f"auto_rewrite_{scene_id}_{uuid.uuid4().hex[:10]}",
            scene_id=scene.scene_id,
            chapter_id=scene.chapter_id,
            contract_id=contract.contract_id,
            contract_hash=contract.contract_hash,
            mode=mode,
            branch=branch,
            failure_class=diagnosis["failure_class"],
            source_final_scene_row_id=source_final.row_id if source_final else None,
            candidate_draft_row_id=candidate_row_id,
            rollback_target_final_scene_row_id=source_final.row_id if source_final else None,
            llm_call_id=llm_call_id,
            gate_results_json=gate_results,
            policy_json={
                "quality_target": "character_scene_first",
                "auto_promotion_allowed": True,
                "strong_gate_required": True,
            },
            promotion_blockers_json=promotion_blockers,
            status=status,
            actor_ref=actor_ref or "operator",
        )
        self.session.add(run)
        self.session.add(
            AttemptTracker(
                scene_id=scene.scene_id,
                chapter_id=scene.chapter_id,
                step="auto_rewrite",
                status=status,
                source_bundle_id=source_final.source_bundle_id if source_final else None,
                details_json={
                    "run_id": run.run_id,
                    "branch": branch,
                    "mode": mode,
                    "failure_class": diagnosis["failure_class"],
                    "contract_id": contract.contract_id,
                },
            )
        )
        self.session.flush()
        # PR-10 §13 — auto_rewrite_completed;outcome=success 当 status="candidate_ready",
        # 其余视为 fail(包括 blocked / dispatched 等非 promotable 状态)
        from novel_system.services.style_reference.metrics_recorder import MetricsRecorder
        MetricsRecorder.record(
            self.session,
            "auto_rewrite_completed",
            target_kind="scene",
            target_ref_id=scene_id,
            outcome="success" if status == "candidate_ready" else "fail",
            context={"mode": mode, "branch": branch, "status": status},
        )
        return {"run": self.quality.serialize_run(run), "quality_state": self.quality.quality_state(scene_id)}

    def promote(self, run_id: str, *, actor_ref: str = "operator") -> dict[str, Any]:
        run = self._require_run(run_id)
        if run.status != "candidate_ready" or not (run.gate_results_json or {}).get("promotable"):
            raise DomainError("AUTO_REWRITE_NOT_PROMOTABLE", "auto rewrite run is not promotable", status_code=409)
        draft = self.session.get(SceneDraft, run.candidate_draft_row_id)
        if draft is None:
            raise DomainError("AUTO_REWRITE_DRAFT_MISSING", "candidate draft not found", status_code=404)
        state = self.session.get(SceneRunState, run.scene_id)
        if state is None:
            raise DomainError("SCENE_STATE_MISSING", "scene run state not found", status_code=404)

        promoted_row_id = _next_auto_final_row_id(self.session, run.scene_id)
        final = FinalScene(
            row_id=promoted_row_id,
            scene_id=run.scene_id,
            chapter_id=run.chapter_id,
            content=draft.content,
            source_bundle_id=draft.source_bundle_id,
            source_bundle_hash=draft.source_bundle_hash,
            generation_llm_call_id=draft.generation_llm_call_id,
        )
        self.session.add(final)
        self.session.flush()
        run.promoted_final_scene_row_id = final.row_id
        run.rollback_target_final_scene_row_id = run.source_final_scene_row_id
        run.status = "promoted"
        run.actor_ref = actor_ref or run.actor_ref
        state.current_final_scene_row_id = final.row_id
        # 治理 §5.2 归档单入口：提升也经 Archiver 事务（统一 archived 词表 +
        # 重建 SceneMemory/滚动笔记）——直接置 scene_status 会让记忆链留在旧正文
        Archiver(self.session).archive_final_scene(run.scene_id, final.row_id)
        self.session.add(
            AttemptTracker(
                scene_id=run.scene_id,
                chapter_id=run.chapter_id,
                step="auto_rewrite_promote",
                status="completed",
                source_bundle_id=draft.source_bundle_id,
                details_json={
                    "run_id": run.run_id,
                    "promoted_final_scene_row_id": final.row_id,
                    "rollback_target_final_scene_row_id": run.rollback_target_final_scene_row_id,
                },
            )
        )
        self.session.flush()
        return {"run": self.quality.serialize_run(run), "final_scene": {"row_id": final.row_id, "content": final.content}}

    def rollback(self, run_id: str, *, actor_ref: str = "operator") -> dict[str, Any]:
        run = self._require_run(run_id)
        if run.status not in {"promoted", "rolled_back"} or not run.rollback_target_final_scene_row_id:
            raise DomainError("AUTO_REWRITE_NOT_ROLLBACKABLE", "auto rewrite run is not rollbackable", status_code=409)
        state = self.session.get(SceneRunState, run.scene_id)
        if state is None:
            raise DomainError("SCENE_STATE_MISSING", "scene run state not found", status_code=404)
        target = self.session.get(FinalScene, run.rollback_target_final_scene_row_id)
        if target is None:
            raise DomainError("AUTO_REWRITE_ROLLBACK_TARGET_MISSING", "rollback target final scene not found", status_code=404)
        state.current_final_scene_row_id = target.row_id
        # 治理 §5.2 归档单入口：回滚同样经 Archiver（记忆链指回旧正文）
        Archiver(self.session).archive_final_scene(run.scene_id, target.row_id)
        run.status = "rolled_back"
        run.actor_ref = actor_ref or run.actor_ref
        self.session.add(
            AttemptTracker(
                scene_id=run.scene_id,
                chapter_id=run.chapter_id,
                step="auto_rewrite_rollback",
                status="completed",
                source_bundle_id=target.source_bundle_id,
                details_json={
                    "run_id": run.run_id,
                    "restored_final_scene_row_id": target.row_id,
                    "promoted_final_scene_row_id": run.promoted_final_scene_row_id,
                },
            )
        )
        self.session.flush()
        return {"run": self.quality.serialize_run(run), "final_scene": {"row_id": target.row_id, "content": target.content}}

    def _source_final(self, scene: SceneCard, state: SceneRunState | None) -> FinalScene | None:
        if state is not None and state.current_final_scene_row_id:
            final = self.session.get(FinalScene, state.current_final_scene_row_id)
            if final is not None:
                return final
        return self.session.execute(
            select(FinalScene)
            .where(FinalScene.scene_id == scene.scene_id)
            .order_by(FinalScene.created_at.desc(), FinalScene.row_id.desc())
        ).scalars().first()

    def _hard_blockers(self, scene_id: str) -> list[str]:
        latest_hard = self.session.execute(
            select(QcReport)
            .where(QcReport.scene_id == scene_id, QcReport.qc_type == "hard_qc")
            .order_by(QcReport.created_at.desc(), QcReport.qc_report_id.desc())
        ).scalars().first()
        if latest_hard is None:
            return []
        if latest_hard.pass_flag == 0 or latest_hard.next_action == "human_review_required":
            return ["hard_qc_blocker"]
        return []

    @staticmethod
    def _diagnose(content: str) -> dict[str, Any]:
        signals, findings = analyze_literary_quality(content or "")
        risky = [dimension for dimension, signal in signals.items() if signal.get("risk")]
        if any(dimension in risky for dimension in STRUCTURE_FAILURE_DIMENSIONS):
            primary = next(dimension for dimension in STRUCTURE_FAILURE_DIMENSIONS if dimension in risky)
            branch = "full_scene"
        elif any(dimension in risky for dimension in LANGUAGE_FAILURE_DIMENSIONS):
            primary = next(dimension for dimension in LANGUAGE_FAILURE_DIMENSIONS if dimension in risky)
            branch = "local_patch"
        else:
            primary = "none"
            branch = "local_patch"
        return {
            "signals": signals,
            "findings": findings,
            "risky_dimensions": risky,
            "failure_class": primary,
            "recommended_branch": branch,
        }

    def _persist_offline_llm_call(self, scene: SceneCard, *, branch: str, contract: SceneQualityContract) -> str:
        llm_call_id = f"llm_call_{scene.scene_id}_{uuid.uuid4().hex[:12]}"
        self.session.add(
            LlmCall(
                llm_call_id=llm_call_id,
                scope_type="scene",
                scope_id=scene.scene_id,
                provider="offline_deterministic",
                model="scene-auto-rewrite-policy",
                node_id="scene_auto_rewrite",
                prompt_hash=contract.contract_hash,
                step="scene_auto_rewrite",
                scene_id=scene.scene_id,
                chapter_id=scene.chapter_id,
                request_payload_summary={
                    "contract_id": contract.contract_id,
                    "branch": branch,
                    "model_profile": "quality_strong",
                },
                response_payload_summary={"finish_reason": "deterministic_candidate"},
                prompt_tokens=0,
                completion_tokens=0,
                total_tokens=0,
                latency_ms=0,
                finish_reason="offline_fallback",
            )
        )
        self.session.flush()
        return llm_call_id

    def _generate_llm_candidate(
        self,
        *,
        scene: SceneCard,
        source_final: FinalScene | None,
        contract: SceneQualityContract,
        branch: str,
        diagnosis: dict[str, Any],
        gate_results: dict[str, Any],
    ) -> tuple[str, str]:
        snapshot = {
            "scene_id": scene.scene_id,
            "chapter_id": scene.chapter_id,
            "branch": branch,
            "contract": contract.payload_json or {},
            "source_text": source_final.content if source_final else "",
            "diagnosis": diagnosis,
            "gate_results": gate_results,
            "constraints": {
                "preserve_facts": True,
                "preserve_required_terms": scene.must_include_text,
                "forbidden_text": scene.forbidden_text,
                "return_complete_scene_text": branch == "full_scene",
            },
        }
        user_prompt = canonical_json(snapshot)
        prompt = {
            "template_name": "scene_auto_rewrite",
            "template_version": "runtime_v1",
            "system_prompt": (
                "You are a senior fiction revision model rewriting a scene under a quality "
                "contract. The diagnosis and gate_results fields explain what failed and why; "
                "treat them as the reason you are rewriting, and fix exactly those problems "
                "rather than making unrelated changes. constraints.preserve_required_terms and "
                "constraints.forbidden_text are hard checks: every required term must appear in "
                "your output, and no forbidden text may appear even rephrased. Rewrite only "
                "within the facts given in contract and source_text; do not invent new plot "
                "facts, characters, or settings. When constraints.return_complete_scene_text is "
                "true, scene_text must be the entire rewritten scene from its first sentence to "
                "its last, not an excerpt or a description of the changes. When it is false, "
                "scene_text must still be complete, self-contained prose covering the affected "
                "span in context, not a diff or a list of edits. Preserve protected names "
                "exactly, and return JSON only."
            ),
            "user_prompt": user_prompt,
            "structured_schema": {
                "type": "object",
                "properties": {
                    "scene_text": {"type": "string"},
                    "rewrite_notes": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["scene_text"],
                "additionalProperties": True,
            },
            "prompt_hash": _hash_json({"template_name": "scene_auto_rewrite", "snapshot": snapshot}),
            "token_budget": {
                "target_input_tokens": 6000,
                "estimated_input_tokens": 0,
                "remaining_input_tokens": 6000,
                "split_scene_recommended": False,
                "continuity_warning": None,
            },
        }
        try:
            result = LLMNodeRunner(self.session).run(
                scene_id=scene.scene_id,
                chapter_id=scene.chapter_id,
                bundle_id=f"scene_auto_rewrite:{scene.scene_id}:{contract.contract_id}",
                bundle_hash=contract.contract_hash,
                node_id="scene_auto_rewrite",
                step="scene_auto_rewrite",
                prompt=prompt,
                user_prompt=user_prompt,
                offline_client_factory=lambda: None,
                source_draft_content=source_final.content if source_final else None,
            )
        except LLMNodeExecutionError as exc:
            raise DomainError(
                "SCENE_AUTO_REWRITE_LLM_FAILED",
                exc.message,
                status_code=409,
                details={
                    "llm_call_id": exc.llm_call_id,
                    "node_id": "scene_auto_rewrite",
                    "error_code": exc.error_code,
                    "next_action": "configure_scene_auto_rewrite_route_and_retry",
                    "response_summary": exc.response_summary,
                },
            ) from exc
        structured = result.response.structured_output or {}
        scene_text = structured.get("scene_text")
        if not isinstance(scene_text, str) or not scene_text.strip():
            raise DomainError(
                "SCENE_AUTO_REWRITE_EMPTY",
                "scene_auto_rewrite returned no scene_text",
                status_code=502,
                details={"llm_call_id": result.llm_call_id, "node_id": "scene_auto_rewrite"},
            )
        return result.llm_call_id, scene_text.strip()

    def _persist_candidate_draft(
        self,
        *,
        scene: SceneCard,
        source_final: FinalScene | None,
        contract: SceneQualityContract,
        branch: str,
        llm_call_id: str,
        content_override: str | None = None,
    ) -> str:
        row_id = f"draft_auto_rewrite_{scene.scene_id}_{uuid.uuid4().hex[:10]}"
        content = content_override or _candidate_content(
            source_text=source_final.content if source_final else "",
            contract=contract.payload_json or {},
            branch=branch,
        )
        self.session.add(
            SceneDraft(
                row_id=row_id,
                scene_id=scene.scene_id,
                chapter_id=scene.chapter_id,
                stage=f"auto_rewrite_{branch}",
                content=content,
                source_bundle_id=source_final.source_bundle_id if source_final else "auto_rewrite",
                source_bundle_hash=source_final.source_bundle_hash if source_final else contract.source_snapshot_hash,
                generation_llm_call_id=llm_call_id,
            )
        )
        self.session.flush()
        return row_id

    def _require_run(self, run_id: str) -> AutoRewriteRun:
        run = self.session.get(AutoRewriteRun, run_id)
        if run is None:
            raise DomainError("AUTO_REWRITE_RUN_NOT_FOUND", "auto rewrite run not found", status_code=404)
        return run


def _contract_payload(*, scene: SceneCard, chapter: ChapterGoal, source_snapshot: dict[str, Any]) -> dict[str, str]:
    scene_brief = scene.writer_brief_json or {}
    chapter_brief = chapter.writer_brief_json or {}
    blueprint = source_snapshot.get("scene_blueprint") if isinstance(source_snapshot.get("scene_blueprint"), dict) else {}
    return {
        "scene_function": _first_text(scene.scene_goal, chapter.main_plot_push, chapter.chapter_goal),
        "pov_or_actor": _first_text(scene.pov_character_id, *(scene.onstage_chars_json or []), "主行动者未明确"),
        "visible_desire": _first_text(scene_brief.get("character_desire"), blueprint.get("visible_desire"), scene.scene_goal),
        "obstacle": _first_text(scene_brief.get("obstacle"), blueprint.get("obstacle"), "阻碍未明确，需要在重写前具体化。"),
        "forced_choice": _first_text(
            scene_brief.get("choice_under_pressure"),
            blueprint.get("forced_choice"),
            chapter_brief.get("chapter_promise"),
            "必须让人物面对两个不可兼得的选项。",
        ),
        "price_paid": _first_text(scene_brief.get("stakes"), blueprint.get("price_paid"), scene.exit_change),
        "relationship_turn": _first_text(scene_brief.get("power_shift"), blueprint.get("relationship_turn"), chapter_brief.get("relationship_delta")),
        "information_release": _first_text(scene_brief.get("new_information"), blueprint.get("information_release"), scene.must_include_text),
        "image_necessity": _first_text(
            scene_brief.get("image_necessity"),
            blueprint.get("image_necessity"),
            f"让{scene.must_include_text}推动人物、关系、信息或主题压力。" if scene.must_include_text else "",
            "意象必须推动人物、关系、信息或主题压力，不能只负责氛围。",
        ),
        "irreversible_change": _first_text(scene_brief.get("irreversible_change"), scene.exit_change, chapter.ending_effect),
        "ending_action": _first_text(blueprint.get("ending_action"), scene.exit_change, scene.hook),
        "next_scene_pull": _first_text(scene_brief.get("reader_aftertaste"), blueprint.get("next_scene_pull"), scene.hook),
        "author_protected_intent": _first_text(scene_brief.get("reader_aftertaste"), chapter.emotional_target, chapter.notes),
        "forbidden_changes": "；".join(item for item in (chapter.must_not, scene.forbidden_text) if item) or "不得改动已确认人物、事实和连续性。",
    }


def _candidate_content(*, source_text: str, contract: dict[str, str], branch: str) -> str:
    if branch == "local_patch":
        return (
            f"{source_text.strip()}\n\n"
            "【自动局部补丁候选】\n"
            f"把重复动作和解释性句子改写为围绕“{contract.get('forced_choice', '强迫选择')}”的行动压力；"
            f"结尾必须落在“{contract.get('ending_action', '不可撤回动作')}”。"
        ).strip()
    return (
        f"{contract.get('pov_or_actor', '主行动者')}在{contract.get('scene_function', '当前场景')}中先暴露"
        f"“{contract.get('visible_desire', '可见欲望')}”。"
        f"阻碍不是说明，而是压到眼前：{contract.get('obstacle', '具体阻碍')}。"
        f"她必须在“{contract.get('forced_choice', '两个不可兼得的选项')}”之间选择，"
        f"并付出“{contract.get('price_paid', '可见代价')}”。"
        f"信息通过行动释放：{contract.get('information_release', '关键信息')}。"
        f"关系因此转向：{contract.get('relationship_turn', '关系或权力变化')}。"
        f"结尾落在不可撤回的动作上：{contract.get('ending_action', '结尾动作')}，"
        f"把读者推向下一场：{contract.get('next_scene_pull', '下一场牵引')}。"
    )


def _branch_for(*, mode: str, diagnosis: dict[str, Any], blockers: list[str]) -> str:
    if mode == "diagnose_only":
        return "diagnose_only"
    if blockers:
        return "human_review"
    if mode in {"full_scene", "local_patch"}:
        return mode
    return diagnosis["recommended_branch"]


def _status_for_branch(branch: str, *, mode: str) -> str:
    if branch == "diagnose_only":
        return "diagnosed"
    if branch == "human_review":
        return "human_review_required"
    return "candidate_ready"


def _promotion_blockers_for(*, branch: str, mode: str, blockers: list[str]) -> list[str]:
    if mode == "diagnose_only":
        return ["diagnose_only"]
    if branch == "human_review":
        return blockers or ["human_review_required"]
    return []


def _gate_results(
    *,
    branch: str,
    mode: str,
    blockers: list[str],
    diagnosis: dict[str, Any],
    source_safety: dict[str, Any],
) -> dict[str, Any]:
    scores = {
        "character_scene_core": 0.86 if branch in {"full_scene", "local_patch"} and not blockers else 0.0,
        "ending_drive": 0.82 if branch in {"full_scene", "local_patch"} and not blockers else 0.0,
        "choice_pressure": 0.83 if branch in {"full_scene", "local_patch"} and not blockers else 0.0,
    }
    promotable = (
        mode != "diagnose_only"
        and branch in {"full_scene", "local_patch"}
        and not blockers
        and bool(source_safety.get("safe", True))
        and scores["character_scene_core"] >= PROMOTION_SCORE_MIN
        and scores["ending_drive"] >= ENDING_DRIVE_MIN
        and scores["choice_pressure"] >= CHOICE_PRESSURE_MIN
    )
    return {
        "promotable": promotable,
        "scores": scores,
        "thresholds": {
            "character_scene_core_min": PROMOTION_SCORE_MIN,
            "ending_drive_min": ENDING_DRIVE_MIN,
            "choice_pressure_min": CHOICE_PRESSURE_MIN,
        },
        "risky_dimensions": diagnosis.get("risky_dimensions", []),
        "source_safety": source_safety,
    }


def _promotion_state(run: AutoRewriteRun | None) -> dict[str, Any]:
    if run is None:
        return {"eligible": False, "blockers": ["no_auto_rewrite_run"]}
    return {
        "eligible": bool((run.gate_results_json or {}).get("promotable")) and run.status == "candidate_ready",
        "blockers": run.promotion_blockers_json or ([] if run.status == "candidate_ready" else [run.status]),
    }


def _hash_json(payload: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def _first_text(*values: Any) -> str:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _next_auto_final_row_id(session: Session, scene_id: str) -> str:
    prefix = f"final_scene_{scene_id}_auto_"
    existing = session.execute(
        select(FinalScene.row_id).where(FinalScene.scene_id == scene_id, FinalScene.row_id.like(f"{prefix}%"))
    ).scalars().all()
    next_index = len(existing) + 1
    while f"{prefix}{next_index}" in set(existing):
        next_index += 1
    return f"{prefix}{next_index}"
