from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from novel_system.db.models import AttemptTracker, FinalScene, QcReport, SceneCard, SceneDraft, SceneRunState
from novel_system.services.errors import DomainError
from novel_system.services.aggregator import Aggregator
from novel_system.services.archiver import Archiver
from novel_system.services.bundle_builder import BundleBuilder
from novel_system.services.llm_task_runner import LLMNodeRunner
from novel_system.services.near_final import NearFinalAcceptanceService, NearFinalPlanningService
from novel_system.services.qc_engine import HardQcEngine, SoftQcEngine
from novel_system.services.scene_blueprint import SceneBlueprintService
from novel_system.services.scene_execution import SceneExecutionContractService
from novel_system.services.scene_generation import SceneGenerationService, versioned_scene_artifact_id
from novel_system.services.version_manager import VersionManager


class Orchestrator:
    def __init__(
        self,
        session: Session,
        *,
        scene_generation_service: SceneGenerationService | None = None,
        hard_qc_engine: HardQcEngine | None = None,
        soft_qc_engine: SoftQcEngine | None = None,
        planning_service: NearFinalPlanningService | None = None,
        near_final_service: NearFinalAcceptanceService | None = None,
    ) -> None:
        self.session = session
        self.bundle_builder = BundleBuilder(session)
        self.archiver = Archiver(session)
        self.aggregator = Aggregator(session)
        self.version_manager = VersionManager(session)
        llm_runner = LLMNodeRunner(session)
        self.scene_generation_service = scene_generation_service or SceneGenerationService(session, llm_runner=llm_runner)
        self.hard_qc_engine = hard_qc_engine or HardQcEngine(session, llm_runner=llm_runner)
        self.soft_qc_engine = soft_qc_engine or SoftQcEngine(session, llm_runner=llm_runner)
        self.scene_blueprint_service = SceneBlueprintService(session, llm_runner=llm_runner)
        self.execution_contract_service = SceneExecutionContractService(session)
        self.planning_service = planning_service or NearFinalPlanningService(session, llm_runner=llm_runner)
        self.near_final_service = near_final_service or NearFinalAcceptanceService(session, llm_runner=llm_runner)

    def run_scene(self, scene_id: str, from_step: str = "bundle", resume: bool = False) -> dict:
        self.version_manager.recover_stuck_jobs()
        scene = self.session.get(SceneCard, scene_id)
        state = self.session.get(SceneRunState, scene_id)
        contract = self.execution_contract_service.get_or_create(scene_id, actor_ref="orchestrator")
        if contract.status != "active":
            detail_reason = "scene execution contract is not ready for drafting"
            if contract.status == "blocked":
                missing_fields = list(contract.missing_fields_json or [])
                detail_reason = "scene execution contract is missing required fields"
                raise DomainError(
                    "SCENE_EXECUTION_CONTRACT_BLOCKED",
                    detail_reason,
                    status_code=409,
                    details={
                        "scene_id": scene_id,
                        "execution_contract_id": contract.contract_id,
                        "status": contract.status,
                        "missing_fields": missing_fields,
                    },
                )
            raise DomainError(
                "SCENE_EXECUTION_CONTRACT_BLOCKED",
                detail_reason,
                status_code=409,
                details={
                    "scene_id": scene_id,
                    "execution_contract_id": contract.contract_id,
                    "status": contract.status,
                    "missing_fields": list(contract.missing_fields_json or []),
                },
            )
        self._prepare_state_for_run(state)
        self.scene_blueprint_service.ensure_for_scene(scene_id)
        planning = self.planning_service.ensure_scene_planning(scene_id)
        bundle = self.bundle_builder.build(scene_id, "P2")

        neutral_generation = self.scene_generation_service.generate_neutral_draft(scene_id, bundle)
        neutral_content = neutral_generation.content

        hard_qc = self.hard_qc_engine.evaluate(
            scene_id=scene_id,
            bundle=bundle,
            neutral_draft_row_id=neutral_generation.row_id,
            neutral_content=neutral_content,
        )
        if not hard_qc.should_continue:
            self.session.flush()
            return {
                "scene_status": state.scene_status,
                "current_bundle_id": bundle["bundle_id"],
                "current_bundle_hash": bundle["bundle_snapshot_hash"],
                "current_final_scene_row_id": state.current_final_scene_row_id,
                "current_qc_report_id": state.current_qc_report_id,
                "current_human_review_event_id": state.current_human_review_event_id,
                "hard_qc": {
                    "branch": hard_qc.branch,
                    "qc_report_id": hard_qc.qc_report_id,
                    "human_review_event_id": hard_qc.human_review_event_id,
                    "resolution_code": hard_qc.resolution_code,
                    "next_action": hard_qc.next_action,
                    "stop_reason": hard_qc.stop_reason,
                },
            }

        style_generation = self.scene_generation_service.generate_style_draft(
            scene_id,
            bundle,
            neutral_draft_row_id=neutral_generation.row_id,
            neutral_content=neutral_content,
        )
        soft_qc = self.soft_qc_engine.evaluate(
            scene_id=scene_id,
            bundle=bundle,
            source_draft_row_id=style_generation.row_id,
            source_draft_content=style_generation.content,
        )

        final_generation = style_generation
        if soft_qc.branch == "patch":
            rewrite_brief = self._rewrite_brief_from_report(soft_qc.qc_report_id)
            final_generation = self.scene_generation_service.generate_style_patch(
                scene_id,
                bundle,
                source_style_draft_row_id=style_generation.row_id,
                source_style_content=style_generation.content,
                rewrite_brief=rewrite_brief,
                source_qc_report_id=soft_qc.qc_report_id,
            )
            soft_qc = self.soft_qc_engine.evaluate(
                scene_id=scene_id,
                bundle=bundle,
                source_draft_row_id=final_generation.row_id,
                source_draft_content=final_generation.content,
            )

        if soft_qc.branch == "human_review_required":
            self.session.flush()
            return {
                "scene_status": state.scene_status,
                "current_bundle_id": bundle["bundle_id"],
                "current_bundle_hash": bundle["bundle_snapshot_hash"],
                "current_final_scene_row_id": state.current_final_scene_row_id,
                "current_qc_report_id": state.current_qc_report_id,
                "current_human_review_event_id": state.current_human_review_event_id,
                "hard_qc": {
                    "branch": hard_qc.branch,
                    "qc_report_id": hard_qc.qc_report_id,
                    "human_review_event_id": hard_qc.human_review_event_id,
                    "resolution_code": hard_qc.resolution_code,
                    "next_action": hard_qc.next_action,
                    "stop_reason": hard_qc.stop_reason,
                },
                "soft_qc": self._soft_qc_result_payload(soft_qc),
                "planning": planning,
            }

        rewrite_count = 0
        near_final = self.near_final_service.evaluate_scene(
            scene_id,
            bundle=bundle,
            source_draft_row_id=final_generation.row_id,
            source_content=final_generation.content,
        )
        if not near_final["pass_flag"] and near_final.get("should_rewrite"):
            rewrite_count = 1
            final_generation = self.scene_generation_service.generate_near_final_rewrite(
                scene_id,
                bundle,
                source_draft_row_id=final_generation.row_id,
                source_content=final_generation.content,
                revision_brief=self._near_final_rewrite_brief(near_final),
                source_evaluation_id=str(near_final.get("evaluation_id") or ""),
            )
            near_final = self.near_final_service.evaluate_scene(
                scene_id,
                bundle=bundle,
                source_draft_row_id=final_generation.row_id,
                source_content=final_generation.content,
            )
        near_final_payload = self._near_final_result_payload(near_final, rewrite_count=rewrite_count)
        if not near_final["pass_flag"]:
            state.scene_status = "human_review_required" if near_final.get("requires_human_review") else "near_final_revision_required"
            self.session.flush()
            return {
                "scene_status": state.scene_status,
                "current_bundle_id": bundle["bundle_id"],
                "current_bundle_hash": bundle["bundle_snapshot_hash"],
                "current_final_scene_row_id": state.current_final_scene_row_id,
                "current_qc_report_id": state.current_qc_report_id,
                "current_human_review_event_id": state.current_human_review_event_id,
                "hard_qc": {
                    "branch": hard_qc.branch,
                    "qc_report_id": hard_qc.qc_report_id,
                    "human_review_event_id": hard_qc.human_review_event_id,
                    "resolution_code": hard_qc.resolution_code,
                    "next_action": hard_qc.next_action,
                    "stop_reason": hard_qc.stop_reason,
                },
                "soft_qc": self._soft_qc_result_payload(soft_qc),
                "planning": planning,
                "near_final": near_final_payload,
            }

        final_row_id = versioned_scene_artifact_id("final_scene", scene_id, bundle)
        soft_risk_acceptance_event_id = self._soft_risk_acceptance_event_id(soft_qc)
        carry_notes_json = self._carry_notes_from_report(soft_qc.qc_report_id) if soft_qc.branch == "waive" else []
        if soft_risk_acceptance_event_id:
            carry_notes_json.append(
                {
                    "kind": "soft_risk_acceptance",
                    "human_review_event_id": soft_risk_acceptance_event_id,
                    "qc_report_id": soft_qc.qc_report_id,
                }
            )
        self.session.add(
            FinalScene(
                row_id=final_row_id,
                scene_id=scene_id,
                chapter_id=scene.chapter_id,
                content=final_generation.content,
                status="near_final_ready",
                source_bundle_id=bundle["bundle_id"],
                source_bundle_hash=bundle["bundle_snapshot_hash"],
                generation_llm_call_id=final_generation.llm_call_id,
            )
        )
        self.session.flush()
        state.current_final_scene_row_id = final_row_id
        finalize_details = {
            "source_style_draft_row_id": final_generation.row_id,
            "source_qc_report_id": soft_qc.qc_report_id,
            "final_generation_llm_call_id": final_generation.llm_call_id,
        }
        if soft_risk_acceptance_event_id:
            finalize_details["soft_risk_acceptance_event_id"] = soft_risk_acceptance_event_id
        self.session.add(
            AttemptTracker(
                scene_id=scene_id,
                chapter_id=scene.chapter_id,
                step="finalize",
                status="completed",
                source_bundle_id=bundle["bundle_id"],
                details_json=finalize_details,
            )
        )
        self.session.flush()

        archive_result = self.archiver.archive_final_scene(
            scene_id,
            final_row_id,
            qc_report_id=soft_qc.qc_report_id,
            carry_notes_json=carry_notes_json,
        )

        chapter_near_final = None
        if scene.is_chapter_last == 1:
            self.aggregator.run_final_aggregate(scene.chapter_id)
            chapter_near_final = self.near_final_service.evaluate_chapter(scene.chapter_id)

        return {
            "scene_status": archive_result["scene_status"],
            "current_bundle_id": bundle["bundle_id"],
            "current_bundle_hash": bundle["bundle_snapshot_hash"],
            "current_final_scene_row_id": final_row_id,
            "current_qc_report_id": state.current_qc_report_id,
            "current_human_review_event_id": state.current_human_review_event_id,
            "hard_qc": {
                "branch": hard_qc.branch,
                "qc_report_id": hard_qc.qc_report_id,
                "human_review_event_id": hard_qc.human_review_event_id,
                "resolution_code": hard_qc.resolution_code,
                "next_action": hard_qc.next_action,
                "stop_reason": hard_qc.stop_reason,
            },
            "soft_qc": self._soft_qc_result_payload(soft_qc),
            "planning": planning,
            "near_final": near_final_payload,
            "chapter_near_final": chapter_near_final,
        }

    @staticmethod
    def _prepare_state_for_run(state: SceneRunState) -> None:
        preserve_hard_retry_state = (
            state.current_final_scene_row_id is None
            and state.scene_status in {"hard_qc_partial_rewrite_required", "hard_qc_full_rewrite_required"}
        )
        state.current_bundle_id = None
        state.current_bundle_hash = None
        state.current_neutral_draft_row_id = None
        state.current_style_draft_row_id = None
        state.current_final_scene_row_id = None
        state.current_human_review_event_id = None
        state.current_qc_report_id = None
        state.total_attempt_count = 0
        state.soft_patch_count = 0
        if not preserve_hard_retry_state:
            state.hard_partial_rewrite_count = 0
            state.hard_full_rewrite_count = 0
            state.repeat_issue_key = None
            state.repeat_issue_count = 0

    def _rewrite_brief_from_report(self, qc_report_id: str) -> list[str]:
        report = self.session.get(QcReport, qc_report_id)
        if report is None:
            return []
        entries = report.rewrite_brief_json or []
        rewrite_brief: list[str] = []
        for entry in entries:
            if isinstance(entry, dict):
                instruction = entry.get("instruction")
                if isinstance(instruction, str) and instruction.strip():
                    rewrite_brief.append(instruction.strip())
        return rewrite_brief

    def _carry_notes_from_report(self, qc_report_id: str) -> list[dict[str, Any]]:
        report = self.session.get(QcReport, qc_report_id)
        if report is None:
            return []
        carry_notes: list[dict[str, Any]] = []
        for entry in report.rewrite_brief_json or []:
            if not isinstance(entry, dict):
                continue
            if entry.get("kind") != "carry_forward_note":
                continue
            note_scope = entry.get("note_scope")
            carry_note_text = entry.get("carry_note_text")
            if isinstance(note_scope, str) and note_scope.strip() and isinstance(carry_note_text, str) and carry_note_text.strip():
                carry_notes.append(
                    {
                        "kind": "carry_forward_note",
                        "note_scope": note_scope.strip(),
                        "carry_note_text": carry_note_text.strip(),
                    }
                )
        return carry_notes

    @staticmethod
    def _soft_risk_acceptance_event_id(soft_qc) -> str | None:
        stop_reason = str(getattr(soft_qc, "stop_reason", "") or "")
        prefix = "accepted_soft_risk:"
        if not stop_reason.startswith(prefix):
            return None
        event_id = stop_reason[len(prefix) :].strip()
        return event_id or None

    @staticmethod
    def _near_final_rewrite_brief(near_final: dict[str, Any]) -> list[str]:
        rewrite_brief: list[str] = []
        for entry in near_final.get("revision_brief") or []:
            if isinstance(entry, dict):
                action = entry.get("action") or entry.get("instruction") or entry.get("recommendation")
                if isinstance(action, str) and action.strip():
                    rewrite_brief.append(action.strip())
            elif isinstance(entry, str) and entry.strip():
                rewrite_brief.append(entry.strip())
        if not rewrite_brief:
            rewrite_brief.append(
                "Rewrite the full scene so forced choice, paid cost, relationship turn, and ending action are visible."
            )
        return rewrite_brief

    @staticmethod
    def _near_final_result_payload(near_final: dict[str, Any], *, rewrite_count: int) -> dict[str, Any]:
        return {
            "near_final_status": near_final.get("near_final_status"),
            "pass_flag": bool(near_final.get("pass_flag")),
            "overall_score": near_final.get("overall_score"),
            "failure_class": near_final.get("failure_class"),
            "requires_human_review": bool(near_final.get("requires_human_review")),
            "evaluation_id": near_final.get("evaluation_id"),
            "revision_candidate_id": near_final.get("revision_candidate_id"),
            "should_rewrite": bool(near_final.get("should_rewrite")),
            "rewrite_count": rewrite_count,
            "findings": near_final.get("findings") or [],
            "revision_brief": near_final.get("revision_brief") or [],
        }

    @staticmethod
    def _soft_qc_result_payload(soft_qc) -> dict[str, str | None]:
        return {
            "branch": soft_qc.branch,
            "qc_report_id": soft_qc.qc_report_id,
            "human_review_event_id": soft_qc.human_review_event_id,
            "resolution_code": soft_qc.resolution_code,
            "next_action": soft_qc.next_action,
            "stop_reason": soft_qc.stop_reason,
        }
