from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

_LOGGER = logging.getLogger(__name__)

from novel_system.db.models import AttemptTracker, ChapterGoal, FinalScene, QcReport, SceneCard, SceneDraft, SceneRunState
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
        self.llm_runner = llm_runner
        self.scene_generation_service = scene_generation_service or SceneGenerationService(session, llm_runner=llm_runner)
        self.hard_qc_engine = hard_qc_engine or HardQcEngine(session, llm_runner=llm_runner)
        self.soft_qc_engine = soft_qc_engine or SoftQcEngine(session, llm_runner=llm_runner)
        self.scene_blueprint_service = SceneBlueprintService(session, llm_runner=llm_runner)
        self.execution_contract_service = SceneExecutionContractService(session)
        self.planning_service = planning_service or NearFinalPlanningService(session, llm_runner=llm_runner)
        self.near_final_service = near_final_service or NearFinalAcceptanceService(session, llm_runner=llm_runner)

    def run_scene(self, scene_id: str, from_step: str = "bundle", resume: bool = False, author_note: str | None = None) -> dict:
        self.version_manager.recover_stuck_jobs()
        scene = self.session.get(SceneCard, scene_id)
        state = self.session.get(SceneRunState, scene_id)
        if state is None:
            # FE 目录直接建的场景没有运行时状态行（scenes POST 才会建）：按同一约定补建
            state = SceneRunState(scene_id=scene_id, scene_status="ready")
            self.session.add(state)
            self.session.flush()
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

        from novel_system.services.scene_criticality import classify_scene
        chapter = self.session.get(ChapterGoal, scene.chapter_id)
        chapter_seq = chapter.display_order if chapter and chapter.display_order is not None else None
        # §6.4 / §16: feed consecutive transition count and constraint_intensity
        _consecutive_trans = self._consecutive_transition_count(scene)
        criticality = classify_scene(
            scene,
            chapter_seq=chapter_seq,
            consecutive_transition_count=_consecutive_trans,
            constraint_intensity=getattr(scene, "constraint_intensity", None),
        )
        _LOGGER.info(
            "scene %s criticality=%s reasons=%s best_of_n=%d",
            scene_id, criticality.level, criticality.reasons, criticality.best_of_n,
        )
        # §6 Defect D: persist criticality classification for API exposure
        state.criticality_level = criticality.level
        state.criticality_reasons_json = criticality.reasons

        # §10 / §12: pre-generation tension + theme diagnostics
        self._run_pre_generation_diagnostics(scene, chapter)

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

        n_candidates = self._best_of_n_count(contract, criticality=criticality)
        candidate_summaries: list[dict[str, Any]] = []
        if n_candidates > 1:
            candidates = self.scene_generation_service.generate_style_draft_candidates(
                scene_id,
                bundle,
                neutral_draft_row_id=neutral_generation.row_id,
                neutral_content=neutral_content,
                author_note=author_note,
                n_candidates=n_candidates,
            )
            # §6.3 Blueprint: "终选决定质量上界，归人。"
            # Critical scenes: auto-select adversarial-ranked #1 but signal that
            # human terminal selection is recommended.  Pipeline continues (no block)
            # so downstream QC and archival still run; the frontend/review inbox gets
            # the candidate_selection_recommended flag to surface the choice.
            from novel_system.services.literary_quality import adversarial_rank_score
            for idx, cand in enumerate(candidates):
                cand_score = adversarial_rank_score(cand.content)
                candidate_summaries.append({
                    "row_id": cand.row_id,
                    "rank": idx,
                    "adversarial_score": round(cand_score, 3),
                    "content_preview": (cand.content or "")[:300],
                    "selected": idx == 0,
                })

            style_generation = candidates[0]
        else:
            style_generation = self.scene_generation_service.generate_style_draft(
                scene_id,
                bundle,
                neutral_draft_row_id=neutral_generation.row_id,
                neutral_content=neutral_content,
                author_note=author_note,
            )

        # §8 reflexion-style auto-critique pass (after best-of-N selection, before soft QC).
        # Default: rule-based pass only. Opt-in (NOVEL_SYSTEM_LLM_AUTO_CRITIQUE_ENABLED +
        # llm_enabled) layers the independent LLM editor critic on top — degrades to
        # rule-only on any runner error, never blocks (blueprint §8 + §15 honest-bounds).
        try:
            from novel_system.services.auto_critique import llm_auto_critique, format_critique_brief
            from novel_system.settings import get_settings as _get_settings
            _settings = _get_settings()
            _critique_runner = (
                self.llm_runner
                if (_settings.llm_enabled and _settings.llm_auto_critique_enabled)
                else None
            )
            critique = llm_auto_critique(
                style_generation.content,
                scene_context=self._scene_critique_context(scene, contract),
                session=self.session,
                llm_runner=_critique_runner,
                skip_critique=criticality.skip_critique,
            )
            if critique.should_rewrite:
                _LOGGER.info(
                    "auto-critique flagged %d dimensions for scene %s: %s",
                    len(critique.flagged_dimensions), scene_id, critique.flagged_dimensions,
                )
                critique_brief = format_critique_brief(critique)
                style_generation = self.scene_generation_service.generate_style_patch(
                    scene_id,
                    bundle,
                    source_style_draft_row_id=style_generation.row_id,
                    source_style_content=style_generation.content,
                    rewrite_brief=critique_brief,
                    source_qc_report_id=f"auto_critique_{scene_id}",
                )
        except Exception:
            _LOGGER.debug("auto-critique skipped", exc_info=True)

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

        if criticality.human_gate and near_final.get("pass_flag"):
            gate_event = self._create_criticality_human_gate(scene, criticality, bundle, final_generation)
            if gate_event:
                state.scene_status = "critical_scene_human_gate"
                state.current_human_review_event_id = gate_event.event_id
                self.session.flush()
                return {
                    "scene_status": state.scene_status,
                    "current_bundle_id": bundle["bundle_id"],
                    "current_bundle_hash": bundle["bundle_snapshot_hash"],
                    "current_final_scene_row_id": state.current_final_scene_row_id,
                    "current_qc_report_id": state.current_qc_report_id,
                    "current_human_review_event_id": gate_event.event_id,
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
                    "criticality": {
                        "level": criticality.level,
                        "reasons": criticality.reasons,
                        "human_gate": True,
                    },
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
        self._record_narrative_events(scene, contract, final_generation.content)
        self._index_scene_to_vector_store(scene, final_generation.content)

        chapter_near_final = None
        if scene.is_chapter_last == 1:
            self.aggregator.run_final_aggregate(scene.chapter_id)
            # §2 summary tower: roll up a volume-level atmosphere summary at span boundaries
            try:
                self.aggregator.maybe_aggregate_volume(scene.chapter_id)
            except Exception:
                _LOGGER.debug("volume aggregation skipped", exc_info=True)
            chapter_near_final = self.near_final_service.evaluate_chapter(scene.chapter_id)
            self._detect_and_store_style_drift(scene)

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
            "style_candidates": candidate_summaries if candidate_summaries else None,
            # §6.3 Blueprint: "终选决定质量上界，归人。" Signal for critical scenes
            # that human candidate selection is recommended (pipeline auto-selected
            # adversarial-ranked #1, but the human should review all candidates).
            "candidate_selection_recommended": (
                bool(criticality and criticality.human_gate and len(candidate_summaries) > 1)
            ),
        }

    def _consecutive_transition_count(self, scene: SceneCard) -> int:
        """Count how many consecutive transition-level scenes precede *scene* in this chapter.

        Used by §6.4 probabilistic promotion: after 3+ consecutive transitions,
        the next transition is elevated to standard to break the "温吞" rhythm.
        """
        from novel_system.services.scene_criticality import classify_scene
        preceding = list(self.session.execute(
            select(SceneCard).where(
                SceneCard.chapter_id == scene.chapter_id,
                SceneCard.scene_seq < scene.scene_seq,
                SceneCard.trashed_flag == 0,
            ).order_by(SceneCard.scene_seq.desc())
        ).scalars().all())
        count = 0
        for prev in preceding:
            crit = classify_scene(prev)  # quick: no DB queries, pure field inspection
            if crit.level == "transition":
                count += 1
            else:
                break
        return count

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

    def _record_narrative_events(self, scene: SceneCard, contract, content: str) -> None:
        """Extract all 7 event types from approved scene and log to event sourcing.

        Blueprint §2: event log is the single source of truth.
        """
        try:
            from novel_system.services.narrative_event_log import NarrativeEventLog
            log = NarrativeEventLog(self.session)
            payload = contract.payload_json or {}
            project_id = (
                scene.project_id
                or payload.get("project_id")
                or (scene.chapter_id.rsplit("_", 1)[0] if "_" in scene.chapter_id else scene.chapter_id)
            )
            pov = scene.pov_character_id or payload.get("pov_character_id")
            onstage = scene.onstage_chars_json or []
            all_chars = list(dict.fromkeys(([pov] if pov else []) + [c for c in onstage if c != pov]))
            base = dict(project_id=project_id, scene_id=scene.scene_id, chapter_id=scene.chapter_id)

            # --- 1. character_state: appeared_in_scene ---
            for char_id in all_chars:
                if not char_id:
                    continue
                log.log_event(
                    **base,
                    event_type="character_state",
                    entity_type="character",
                    entity_id=char_id,
                    fact_key="appeared_in_scene",
                    fact_value=scene.scene_id,
                    source_text_excerpt=content[:200] if content else None,
                )

            # --- 2. character_state: exit_change ---
            exit_change = scene.exit_change or payload.get("exit_change") or ""
            if exit_change and pov:
                log.log_event(
                    **base,
                    event_type="character_state",
                    entity_type="character",
                    entity_id=pov,
                    fact_key="exit_change",
                    fact_value=exit_change[:500],
                )

            # --- 3. location_change ---
            location = scene.location or payload.get("location")
            if location:
                for char_id in all_chars:
                    if not char_id:
                        continue
                    log.log_event(
                        **base,
                        event_type="location_change",
                        entity_type="character",
                        entity_id=char_id,
                        fact_key="location",
                        fact_value=location[:200],
                    )

            # --- 4. character_learns: from writer_brief must_reveal ---
            writer_brief = scene.writer_brief_json or {}
            must_reveal = writer_brief.get("must_reveal")
            if must_reveal and pov:
                reveal_text = must_reveal if isinstance(must_reveal, str) else str(must_reveal)
                log.log_event(
                    **base,
                    event_type="character_learns",
                    entity_type="character",
                    entity_id=pov,
                    fact_key="scene_revelation",
                    fact_value=reveal_text[:500],
                )

            # --- 5. relation_change: from scene blueprint relationship_turn ---
            self._record_relation_events(log, scene, base, pov, all_chars)

            # --- 6. foreshadow_plant / foreshadow_resolve ---
            self._record_foreshadow_events(log, scene, base)

            # --- 7. (opt-in) prose-grounded events: what the TEXT actually realized,
            # not just what the spec planned. Advisory (confidence="extracted"). ---
            self._record_prose_events(log, scene, base, content)

            self.session.flush()
        except Exception:
            _LOGGER.debug("narrative event recording skipped", exc_info=True)

    def _record_prose_events(self, log, scene: SceneCard, base: dict, content: str) -> None:
        """§2 (opt-in): extract events from the ACTUAL generated prose so model drift away
        from the spec is captured. Tagged confidence="extracted" + source="prose" → advisory
        only, never a hard consistency blocker (blueprint §15 honest-bounds). Degrades to a
        no-op when disabled, no runner, or on any error."""
        from novel_system.settings import get_settings
        settings = get_settings()
        if not (settings.llm_enabled and getattr(settings, "llm_event_extraction_enabled", False)):
            return
        if not (content and content.strip()):
            return
        try:
            from novel_system.services.prose_event_extractor import extract_events_from_prose
            for ev in extract_events_from_prose(content, llm_runner=self.llm_runner):
                log.log_event(
                    **base,
                    event_type=ev.event_type,
                    entity_type="relation" if ev.event_type == "relation_change" else "character",
                    entity_id=ev.entity_id,
                    fact_key=ev.fact_key,
                    fact_value=ev.fact_value,
                    confidence="extracted",
                    source_text_excerpt=ev.evidence or content[:200],
                    payload={"source": "prose"},
                )
        except Exception:
            _LOGGER.debug("prose event extraction skipped", exc_info=True)

    def _record_relation_events(
        self, log, scene: SceneCard, base: dict, pov: str | None, all_chars: list[str],
    ) -> None:
        """Extract relation_change events from scene blueprint and writer brief."""
        from novel_system.db.models import SceneBlueprint
        blueprint = self.session.execute(
            select(SceneBlueprint)
            .where(SceneBlueprint.scene_id == scene.scene_id, SceneBlueprint.status.in_(("accepted", "draft")))
            .order_by(SceneBlueprint.created_at.desc())
        ).scalars().first()
        relationship_turn = None
        if blueprint and blueprint.blueprint_json:
            relationship_turn = blueprint.blueprint_json.get("relationship_turn")
        if not relationship_turn:
            relationship_turn = (scene.writer_brief_json or {}).get("relationship_turn")
        if relationship_turn and pov and len(all_chars) >= 2:
            other = next((c for c in all_chars if c != pov), pov)
            log.log_event(
                **base,
                event_type="relation_change",
                entity_type="relation",
                entity_id=f"{pov}--{other}",
                fact_key="relationship_turn",
                fact_value=str(relationship_turn)[:500],
            )

    def _record_foreshadow_events(self, log, scene: SceneCard, base: dict) -> None:
        """Record foreshadow_plant / foreshadow_reinforce / foreshadow_resolve from ForeshadowTracker.

        Blueprint §5: reinforcement execution must be tracked as narrative events,
        not just as directives — otherwise the system 'thinks' it reinforced but
        the text may never have included the hint.
        """
        from novel_system.db.models import ForeshadowTracker
        from novel_system.services.foreshadow_lifecycle import ForeshadowLifecycleService

        trackers = self.session.execute(
            select(ForeshadowTracker).where(
                ForeshadowTracker.scene_id == scene.scene_id,
                ForeshadowTracker.active_flag == 1,
            )
        ).scalars().all()
        for tracker in trackers:
            if tracker.tracker_status == "open":
                log.log_event(
                    **base,
                    event_type="foreshadow_plant",
                    entity_type="foreshadow",
                    entity_id=tracker.foreshadow_id,
                    fact_key="planted",
                    fact_value=tracker.text[:500] if tracker.text else "foreshadow planted",
                )
            elif tracker.tracker_status == "resolved":
                log.log_event(
                    **base,
                    event_type="foreshadow_resolve",
                    entity_type="foreshadow",
                    entity_id=tracker.foreshadow_id,
                    fact_key="resolved",
                    fact_value=tracker.text[:500] if tracker.text else "foreshadow resolved",
                )

        # Blueprint §5 reinforcement tracking: check if this scene had reinforcement
        # directives and record them as narrative events for audit trail.
        try:
            lifecycle = ForeshadowLifecycleService(self.session)
            report = lifecycle.scene_actions(scene.scene_id)
            for action in report.actions:
                if action.action == "reinforce":
                    log.log_event(
                        **base,
                        event_type="foreshadow_reinforce",
                        entity_type="foreshadow",
                        entity_id=action.foreshadow_id,
                        fact_key="reinforced",
                        fact_value=f"Reinforcement directed: {action.reason}"[:500],
                    )
        except Exception:
            pass  # non-critical — don't block scene finalization

    @staticmethod
    def _index_scene_to_vector_store(scene: SceneCard, content: str) -> None:
        """Index approved scene content into the vector store for semantic retrieval (§3 Track 3)."""
        try:
            from novel_system.services.vector_store import InMemoryVectorStore
            project_id = scene.project_id or (scene.chapter_id.rsplit("_", 1)[0] if "_" in scene.chapter_id else scene.chapter_id)
            collection_name = f"scenes_{project_id}"
            store = InMemoryVectorStore()
            existing = store.load_collection(collection_name) if store.collection_exists(collection_name) else []
            existing_ids = {doc["id"] for doc in existing}
            if scene.scene_id not in existing_ids:
                existing.append({"id": scene.scene_id, "text": (content or "")[:600]})
                store.write_collection(collection_name, existing)
        except Exception:
            _LOGGER.debug("vector store indexing skipped", exc_info=True)

    def _detect_and_store_style_drift(self, scene: SceneCard) -> None:
        """Run style drift detection at chapter boundary and store correction prompt.

        Blueprint §9 drift correction loop: when drift is detected at chapter end,
        store the correction guidance scoped to the NEXT chapter so the bundle_builder
        picks it up for subsequent generation. This closes the detect→correct feedback loop.
        """
        try:
            from novel_system.services.style_drift_detector import (
                detect_chapter_drift,
                format_drift_correction_prompt,
                format_drift_dimensions_for_bundle,
                drift_corrective_ptype_priority,
            )
            from novel_system.db.models import LongformStructureGuidance
            import uuid

            baseline = self._load_style_baseline(scene)
            report = detect_chapter_drift(self.session, scene.chapter_id, baseline)
            if not report.has_drift:
                return

            correction = format_drift_correction_prompt(report)
            if not correction:
                return

            # Find the next chapter to scope the correction guidance correctly
            next_chapter = self._find_next_chapter(scene)
            if next_chapter:
                scope_type = "chapter"
                scope_ref_id = next_chapter.chapter_id
            else:
                # No next chapter found — store globally so it's picked up by any future chapter
                scope_type = "global"
                scope_ref_id = "global"

            # Supersede any prior drift guidance for the same scope
            from novel_system.db.models import LongformStructureGuidance as LSG
            prior_drift = self.session.execute(
                select(LSG).where(
                    LSG.scope_type == scope_type,
                    LSG.scope_ref_id == scope_ref_id,
                    LSG.guidance_id.like("drift_%"),
                    LSG.status == "approved",
                )
            ).scalars().all()
            for prior in prior_drift:
                prior.status = "superseded"

            # §9 Defect B: store both text guidance AND structured drift data
            # so the injection service can do "show" (few-shot) in addition to "tell" (text)
            ptype_priority = drift_corrective_ptype_priority(report)
            drift_bundle_data = format_drift_dimensions_for_bundle(report)
            recommendation = {}
            if ptype_priority:
                recommendation["drift_ptype_priority"] = ptype_priority
            if drift_bundle_data:
                recommendation["drift_dimensions"] = drift_bundle_data

            guidance = LongformStructureGuidance(
                guidance_id=f"drift_{uuid.uuid4().hex[:12]}",
                scope_type=scope_type,
                scope_ref_id=scope_ref_id,
                content=correction,
                recommendation_json=recommendation,
                status="approved",
                runtime_eligible=1,
                source_review_id=f"auto_drift_{scene.chapter_id}",
            )
            self.session.add(guidance)
            self.session.flush()
            _LOGGER.info(
                "§9 style drift correction stored: chapter %s → scope %s/%s, %d dimensions drifting",
                scene.chapter_id, scope_type, scope_ref_id, len(report.drifts),
            )
        except Exception:
            _LOGGER.debug("style drift detection skipped", exc_info=True)

    def _find_next_chapter(self, scene: SceneCard) -> ChapterGoal | None:
        """Find the next chapter after the scene's chapter, by display_order."""
        try:
            current = self.session.get(ChapterGoal, scene.chapter_id)
            if current is None or current.display_order is None:
                return None
            return self.session.execute(
                select(ChapterGoal)
                .where(
                    ChapterGoal.project_id == scene.project_id,
                    ChapterGoal.display_order > current.display_order,
                )
                .order_by(ChapterGoal.display_order.asc())
            ).scalars().first()
        except Exception:
            return None

    def _load_style_baseline(self, scene: SceneCard) -> dict[str, float] | None:
        """Load baseline metrics from style reference profile if available."""
        try:
            from novel_system.db.models import StyleReferenceInjectionBinding, StyleReferenceProfile
            binding = self.session.execute(
                select(StyleReferenceInjectionBinding).where(
                    StyleReferenceInjectionBinding.scope == "project",
                    StyleReferenceInjectionBinding.scope_ref_id == scene.project_id,
                    StyleReferenceInjectionBinding.active == 1,
                ).order_by(StyleReferenceInjectionBinding.created_at.desc())
            ).scalars().first()
            if not binding:
                return None
            profile = self.session.get(StyleReferenceProfile, binding.profile_id)
            if profile and profile.profile_json:
                metrics = profile.profile_json.get("metrics_baseline")
                if isinstance(metrics, dict):
                    return metrics
            return None
        except Exception:
            return None

    @staticmethod
    def _best_of_n_count(contract, *, criticality=None) -> int:
        from novel_system.settings import get_settings
        if not get_settings().llm_enabled:
            return 1
        if criticality is not None:
            return criticality.best_of_n
        payload = contract.payload_json or {}
        crucible = payload.get("scene_crucible") or ""
        if crucible and len(crucible) > 10:
            return 3
        return 1

    def _create_criticality_human_gate(self, scene, criticality, bundle, final_generation):
        """Blueprint §13 Step 7: proactive human gate for critical scenes."""
        import uuid
        from novel_system.db.models import HumanReviewEvent
        event = HumanReviewEvent(
            event_id=f"hre_gate_{uuid.uuid4().hex[:12]}",
            scene_id=scene.scene_id,
            chapter_id=scene.chapter_id,
            object_ref=f"criticality_gate:{scene.scene_id}",
            event_source="criticality_gate",
            priority="high",
            status="awaiting_review",
            allowed_actions_json=["approve", "request_revision", "redirect"],
            details_json={
                "gate_type": "critical_scene_proactive",
                "criticality_level": criticality.level,
                "criticality_reasons": criticality.reasons,
                "bundle_id": bundle["bundle_id"],
                "draft_row_id": final_generation.row_id,
                "content_preview": (final_generation.content or "")[:500],
            },
            default_action="approve",
        )
        self.session.add(event)
        self.session.flush()
        return event

    def _scene_critique_context(self, scene: SceneCard, contract):
        """Build the §8 SceneContext for the LLM editor critic (best-effort; the critic
        degrades gracefully when fields are absent)."""
        from novel_system.services.auto_critique import SceneContext
        payload = getattr(contract, "payload_json", None) or {}
        brief = getattr(scene, "writer_brief_json", None) or {}
        tension = brief.get("tension_target")
        return SceneContext(
            scene_goal=str(getattr(scene, "scene_goal", "") or payload.get("scene_goal") or ""),
            tension_target=tension if isinstance(tension, int) else None,
            cost_requirement=str(payload.get("cost_requirement") or brief.get("cost_requirement") or ""),
        )

    def _run_pre_generation_diagnostics(self, scene: SceneCard, chapter: ChapterGoal | None) -> None:
        """Blueprint §10/§12: pre-generation tension curve + theme relevance diagnostics.

        These checks are non-blocking (logged as warnings) — the execution contract
        handles hard blocking. This provides early feedback on rhythm and theme health.
        """
        # §10: tension curve adjacent-tag and monotony check
        if chapter is not None:
            try:
                from novel_system.services.tension_curve import TensionCurveService
                tension_svc = TensionCurveService(self.session)
                tension_report = tension_svc.validate_chapter(chapter.chapter_id)
                for v in tension_report.violations:
                    _LOGGER.warning(
                        "§10 tension violation in chapter %s scene %s: [%s] %s",
                        chapter.chapter_id, v.scene_id, v.violation_type, v.message,
                    )
                # §10: chapter-end hook type adjacency check
                hook_violations = tension_svc.validate_chapter_hooks(chapter.chapter_id)
                for hv in hook_violations:
                    _LOGGER.warning(
                        "§10 hook violation in chapter %s scene %s: [%s] %s",
                        chapter.chapter_id, hv.scene_id, hv.violation_type, hv.message,
                    )
            except Exception:
                _LOGGER.debug("tension curve diagnostics skipped", exc_info=True)

        # §12: theme relevance check
        project_id = scene.project_id
        if project_id:
            try:
                from novel_system.services.theme_anchor import ThemeAnchorService
                theme_svc = ThemeAnchorService(self.session)
                idea = theme_svc.get_controlling_idea(project_id)
                if idea:
                    check = theme_svc.check_scene_relevance(scene, idea)
                    if not check.relevant:
                        _LOGGER.warning(
                            "§12 theme relevance warning for scene %s: %s — %s",
                            scene.scene_id, check.connection, check.suggestion,
                        )
            except Exception:
                _LOGGER.debug("theme relevance diagnostics skipped", exc_info=True)

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
