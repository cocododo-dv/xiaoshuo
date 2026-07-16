from __future__ import annotations

import hashlib
import logging
import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from novel_system.db.models import (
    ChapterGoal,
    FinalScene,
    QcReport,
    SceneBlueprint,
    SceneCard,
    SceneExecutionContract,
    SceneRunState,
    SnowflakeArtifact,
    StoryProject,
    StyleReferenceInjectionBinding,
    StyleReferenceProfile,
)
from novel_system.services.errors import DomainError
from novel_system.services.hash_engine import canonical_json
from novel_system.services.narrative_position import NarrativePositionService
from novel_system.services.project_backtracks import ProjectBacktrackService

EXECUTION_CONTRACT_VERSION = "scene_execution_contract_v1"
logger = logging.getLogger(__name__)


@dataclass(slots=True)
class SceneCausalReadinessAssessment:
    warning: str | None = None
    diagnostics: list[dict[str, Any]] = field(default_factory=list)


class SceneExecutionContractService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def latest(self, scene_id: str) -> SceneExecutionContract | None:
        return self.session.execute(
            select(SceneExecutionContract)
            .where(
                SceneExecutionContract.scene_id == scene_id,
                SceneExecutionContract.status != "superseded",
            )
            .order_by(SceneExecutionContract.updated_at.desc(), SceneExecutionContract.contract_id.desc())
        ).scalars().first()

    def get_or_create(self, scene_id: str, *, actor_ref: str = "operator") -> SceneExecutionContract:
        scene = self._require_scene(scene_id)
        chapter = self._require_chapter(scene.chapter_id)
        project = self.session.get(StoryProject, scene.project_id) if scene.project_id else None
        blueprint = self._latest_blueprint(scene_id)
        reference_rules = self._reference_rules(project)
        snapshot = self._source_snapshot(scene, chapter, project, blueprint, reference_rules)
        snapshot_hash = hashlib.sha256(canonical_json(snapshot).encode("utf-8")).hexdigest()
        latest = self.latest(scene_id)
        if latest is not None and latest.source_snapshot_hash == snapshot_hash and latest.status != "stale":
            return latest
        return self.generate(scene_id, actor_ref=actor_ref)

    def generate(self, scene_id: str, *, actor_ref: str = "operator") -> SceneExecutionContract:
        scene = self._require_scene(scene_id)
        chapter = self._require_chapter(scene.chapter_id)
        project = self.session.get(StoryProject, scene.project_id) if scene.project_id else None
        blueprint = self._latest_blueprint(scene_id)
        reference_rules = self._reference_rules(project)
        snapshot = self._source_snapshot(scene, chapter, project, blueprint, reference_rules)
        snapshot_hash = hashlib.sha256(canonical_json(snapshot).encode("utf-8")).hexdigest()
        latest = self.latest(scene_id)
        if latest is not None and latest.source_snapshot_hash == snapshot_hash and latest.status != "stale":
            return latest

        payload, missing_fields = self._payload(scene, chapter, blueprint, reference_rules)

        # §4 Causal readiness — check reverse causal skeleton prerequisites.
        causal_assessment = self._check_causal_readiness(scene, project)
        if causal_assessment is not None and causal_assessment.warning:
            payload["causal_readiness_warning"] = causal_assessment.warning
            missing_fields.append("causal_prerequisite(advisory)")
        if causal_assessment is not None and causal_assessment.diagnostics:
            payload["causal_readiness_diagnostics"] = causal_assessment.diagnostics
            missing_fields.append("causal_readiness_diagnostic(advisory)")

        blocking_fields = [f for f in missing_fields if not f.endswith("(advisory)")]
        status = "active" if not blocking_fields else "blocked"

        rows = self.session.execute(
            select(SceneExecutionContract).where(
                SceneExecutionContract.scene_id == scene_id,
                SceneExecutionContract.status.in_(("active", "blocked")),
            )
        ).scalars().all()
        for row in rows:
            row.status = "superseded"

        contract = SceneExecutionContract(
            contract_id=f"scene_execution_contract_{scene_id}_{uuid.uuid4().hex[:10]}",
            scene_id=scene.scene_id,
            chapter_id=scene.chapter_id,
            project_id=scene.project_id,
            contract_version=EXECUTION_CONTRACT_VERSION,
            source_snapshot_hash=snapshot_hash,
            payload_json=payload,
            missing_fields_json=missing_fields,
            status=status,
            created_by=actor_ref or "operator",
        )
        self.session.add(contract)
        self.session.flush()
        return contract

    @staticmethod
    def serialize(row: SceneExecutionContract | None) -> dict[str, Any] | None:
        if row is None:
            return None
        return {
            "contract_id": row.contract_id,
            "scene_id": row.scene_id,
            "chapter_id": row.chapter_id,
            "project_id": row.project_id,
            "contract_version": row.contract_version,
            "source_snapshot_hash": row.source_snapshot_hash,
            "payload": row.payload_json or {},
            "missing_fields": list(row.missing_fields_json or []),
            "status": row.status,
            "ready_to_draft": row.status == "active",
            "created_by": row.created_by,
            "created_at": row.created_at,
            "updated_at": row.updated_at,
        }

    def _payload(
        self,
        scene: SceneCard,
        chapter: ChapterGoal,
        blueprint: SceneBlueprint | None,
        reference_rules: dict[str, list[str]],
    ) -> tuple[dict[str, Any], list[str]]:
        brief = dict(scene.writer_brief_json or {})
        blueprint_json = dict(blueprint.blueprint_json or {}) if blueprint is not None else {}
        scene_mode = _infer_scene_mode(scene, brief)
        explicit_scene_contract = _is_explicit_structured_scene(scene, brief)
        common_payload = {
            "scene_mode": scene_mode,
            "pov_character_id": _first_text(scene.pov_character_id),
            "scene_crucible": _first_text(
                brief.get("scene_crucible"),
                blueprint_json.get("scene_crucible") if explicit_scene_contract else None,
                brief.get("conflict") if scene_mode == "proactive" else brief.get("dilemma"),
                brief.get("choice_under_pressure") if not explicit_scene_contract else None,
                blueprint_json.get("choice_under_pressure") if not explicit_scene_contract else None,
                blueprint_json.get("concrete_obstacle"),
                brief.get("obstacle"),
                scene.scene_goal if not explicit_scene_contract else None,
                chapter.main_plot_push if not explicit_scene_contract else None,
            ),
            "timebox": _first_text(brief.get("timebox"), scene.target_length_band, "single_scene"),
            "expected_reader_emotion": _first_text(
                brief.get("expected_reader_emotion"),
                brief.get("reader_aftertaste"),
                brief.get("emotional_turn"),
                chapter.emotional_target,
            ),
            "must_reveal": _first_text(brief.get("must_reveal"), brief.get("new_information"), scene.must_include_text),
            "must_withhold": _first_text(
                brief.get("must_withhold"),
                brief.get("secret_or_misunderstanding"),
                scene.forbidden_text,
            ),
            "exit_change": _first_text(scene.exit_change, brief.get("irreversible_change")),
            "next_scene_pull": _first_text(scene.hook, brief.get("reader_question"), brief.get("next_scene_pull")),
            "anti_summary_rule": _first_text(
                blueprint_json.get("anti_summary_rule"),
                "End on a visible action and do not explain the scene's meaning after the final beat.",
            ),
            "image_anchor": _first_text(
                brief.get("image_anchor"),
                blueprint_json.get("image_anchor"),
                blueprint_json.get("image_promise"),
            ),
            "relationship_turn": _first_text(
                brief.get("relationship_turn"),
                brief.get("power_shift"),
                blueprint_json.get("relationship_turn"),
                blueprint_json.get("power_shift"),
            ),
            "price_paid": _first_text(
                brief.get("price_paid"),
                brief.get("stakes"),
                blueprint_json.get("price_paid"),
                scene.exit_change,
            ),
            "cost_requirement": _first_text(
                brief.get("cost_requirement"),
                blueprint_json.get("cost_requirement"),
                brief.get("price_paid"),
                brief.get("stakes"),
                blueprint_json.get("price_paid"),
                scene.exit_change,
            ),
            "function_tag": _first_text(
                brief.get("function_tag"),
                blueprint_json.get("function_tag"),
            ),
            "tension_target": brief.get("tension_target") or blueprint_json.get("tension_target"),
            "causal_prerequisite_scene_id": _first_text(
                brief.get("causal_prerequisite_scene_id"),
                blueprint_json.get("causal_prerequisite_scene_id"),
            ),
            "downstream_obligations": brief.get("downstream_obligations") or blueprint_json.get("downstream_obligations") or [],
            "reference_rules": reference_rules,
            # Internal marker: True if scene_crucible comes from explicit spec, not fallback
            "_has_explicit_crucible": bool(
                _first_text(brief.get("scene_crucible"), blueprint_json.get("scene_crucible"))
            ),
        }
        mode_payload: dict[str, Any]
        if scene_mode == "reactive":
            mode_payload = {
                "reaction": _first_text(
                    brief.get("reaction"),
                    brief.get("emotional_turn"),
                    blueprint_json.get("emotional_turn"),
                    _beat_text(scene, 0) if not explicit_scene_contract else None,
                    scene.scene_goal if not explicit_scene_contract else None,
                ),
                "dilemma": _first_text(
                    brief.get("dilemma"),
                    brief.get("choice_under_pressure"),
                    blueprint_json.get("choice_under_pressure"),
                    blueprint_json.get("concrete_obstacle"),
                    brief.get("obstacle"),
                    _beat_text(scene, 1) if not explicit_scene_contract else None,
                ),
                "decision": _first_text(
                    brief.get("decision"),
                    brief.get("irreversible_change") if not explicit_scene_contract else None,
                    blueprint_json.get("irreversible_consequence"),
                    scene.exit_change if not explicit_scene_contract else None,
                    _last_beat(scene) if not explicit_scene_contract else None,
                    brief.get("reader_question"),
                ),
            }
        else:
            mode_payload = {
                "goal": _first_text(
                    brief.get("goal"),
                    blueprint_json.get("character_current_desire"),
                    scene.scene_goal,
                ),
                "conflict": _first_text(
                    brief.get("conflict"),
                    blueprint_json.get("concrete_obstacle"),
                    brief.get("obstacle"),
                    _beat_text(scene, 1) if not explicit_scene_contract else None,
                    scene.hook if not explicit_scene_contract else None,
                ),
                "setback_or_victory": _first_text(
                    brief.get("setback_or_victory"),
                    brief.get("setback"),
                    brief.get("victory"),
                    brief.get("irreversible_change") if not explicit_scene_contract else None,
                    blueprint_json.get("information_release"),
                    blueprint_json.get("irreversible_consequence"),
                    scene.exit_change if not explicit_scene_contract else None,
                    _last_beat(scene) if not explicit_scene_contract else None,
                    scene.hook if not explicit_scene_contract else None,
                ),
            }
        payload = {**common_payload, **mode_payload}
        missing_fields = self._missing_fields(payload)
        return payload, missing_fields

    def _missing_fields(self, payload: dict[str, Any]) -> list[str]:
        missing = []
        for f in ("scene_mode", "pov_character_id", "scene_crucible"):
            if not _has_text(payload.get(f)):
                missing.append(f)
        scene_mode = str(payload.get("scene_mode") or "proactive")
        if scene_mode == "reactive":
            for f in ("reaction", "dilemma", "decision"):
                if not _has_text(payload.get(f)):
                    missing.append(f)
        else:
            for f in ("goal", "conflict", "setback_or_victory"):
                if not _has_text(payload.get(f)):
                    missing.append(f)
        # §4 cost_requirement — blocking for scenes with explicit structured specs
        # (scene_crucible in writer_brief or blueprint), advisory for simple/legacy scenes.
        # Blueprint §4: "「代价」字段是关键 — AI 最常见的毛病是免费选择"
        if not _has_text(payload.get("cost_requirement")):
            is_explicit = payload.get("_has_explicit_crucible", False)
            missing.append("cost_requirement" if is_explicit else "cost_requirement(advisory)")
        # §10 function_tag — advisory but tracked for rhythm enforcement
        if not _has_text(payload.get("function_tag")):
            missing.append("function_tag(advisory)")
        # §10 tension_target — advisory
        if payload.get("tension_target") is None:
            missing.append("tension_target(advisory)")
        return missing

    def _latest_blueprint(self, scene_id: str) -> SceneBlueprint | None:
        return self.session.execute(
            select(SceneBlueprint)
            .where(SceneBlueprint.scene_id == scene_id, SceneBlueprint.status.in_(("accepted", "draft")))
            .order_by(SceneBlueprint.created_at.desc(), SceneBlueprint.row_id.desc())
        ).scalars().first()

    def _source_snapshot(
        self,
        scene: SceneCard,
        chapter: ChapterGoal,
        project: StoryProject | None,
        blueprint: SceneBlueprint | None,
        reference_rules: dict[str, list[str]],
    ) -> dict[str, Any]:
        return {
            "scene": {
                "scene_id": scene.scene_id,
                "scene_type": scene.scene_type,
                "scene_goal": scene.scene_goal,
                "location": scene.location,
                "exit_change": scene.exit_change,
                "hook": scene.hook,
                "writer_brief_json": dict(scene.writer_brief_json or {}),
            },
            "chapter": {
                "chapter_id": chapter.chapter_id,
                "chapter_goal": chapter.chapter_goal,
                "main_plot_push": chapter.main_plot_push,
                "emotional_target": chapter.emotional_target,
                "writer_brief_json": dict(chapter.writer_brief_json or {}),
            },
            "project": {
                "project_id": project.project_id if project is not None else None,
                "reference_profile_ids": self._reference_profile_ids(project) if project is not None else [],
                "causal_readiness_basis_hash": self._causal_readiness_basis_hash(project),
            },
            "blueprint_json": dict(blueprint.blueprint_json or {}) if blueprint is not None else {},
            "reference_rules": reference_rules,
            "contract_version": EXECUTION_CONTRACT_VERSION,
        }

    def _causal_readiness_basis_hash(
        self,
        project: StoryProject | None,
    ) -> str | None:
        if project is None:
            return None
        skeleton_basis: dict[str, Any] | None = None
        for step_key in ("scene_details", "long_synopsis"):
            artifact = self.session.execute(
                select(SnowflakeArtifact)
                .where(
                    SnowflakeArtifact.project_id == project.project_id,
                    SnowflakeArtifact.step_key == step_key,
                )
                .order_by(SnowflakeArtifact.version.desc())
            ).scalars().first()
            if (
                artifact is not None
                and artifact.artifact_json
                and artifact.artifact_json.get("causal_skeleton")
            ):
                skeleton_basis = {
                    "artifact_id": artifact.artifact_id,
                    "version": artifact.version,
                    "causal_skeleton": artifact.artifact_json["causal_skeleton"],
                }
                break
        if skeleton_basis is None:
            return None
        position_service = NarrativePositionService(self.session)
        ordered_scenes = position_service.ordered_scenes(project.project_id)
        ordered_scene_ids = [scene.scene_id for scene in ordered_scenes]
        completed_scene_ids = self._canonical_completed_scene_ids(
            project.project_id,
            position_service=position_service,
        )
        return hashlib.sha256(
            canonical_json(
                {
                    "ordered_scene_ids": ordered_scene_ids,
                    "completed_scene_ids": [
                        scene_id
                        for scene_id in ordered_scene_ids
                        if scene_id in completed_scene_ids
                    ],
                    "skeleton": skeleton_basis,
                }
            ).encode("utf-8")
        ).hexdigest()

    def _reference_rules(self, project: StoryProject | None) -> dict[str, list[str]]:
        if project is None:
            return {"style_rules": [], "structure_rules": [], "safety_rules": []}
        style_profile = self._active_style_reference_profile(project.project_id)
        if style_profile is not None and style_profile.status == "active":
            return _normalize_reference_rules(style_profile.profile_json or {})
        return {"style_rules": [], "structure_rules": [], "safety_rules": []}

    def _active_style_reference_profile(self, project_id: str) -> StyleReferenceProfile | None:
        binding = self.session.execute(
            select(StyleReferenceInjectionBinding)
            .where(
                StyleReferenceInjectionBinding.scope == "project",
                StyleReferenceInjectionBinding.scope_ref_id == project_id,
                StyleReferenceInjectionBinding.task_type == "scene_generation",
                StyleReferenceInjectionBinding.status == "active",
            )
            .order_by(
                StyleReferenceInjectionBinding.created_at.desc(),
                StyleReferenceInjectionBinding.binding_id.desc(),
            )
        ).scalars().first()
        if binding is None:
            return None
        return self.session.get(StyleReferenceProfile, binding.profile_id)

    def _reference_profile_ids(self, project: StoryProject) -> list[str]:
        style_profile = self._active_style_reference_profile(project.project_id)
        if style_profile is not None:
            return [style_profile.profile_id]
        return []

    def _check_causal_readiness(
        self, scene: SceneCard, project: StoryProject | None,
    ) -> SceneCausalReadinessAssessment | None:
        """Evaluate advisory causal readiness and retain machine diagnostics."""
        if project is None:
            return None
        try:
            from novel_system.services.reverse_causal_skeleton import (
                ReverseCausalSkeleton,
                CausalLink,
                validate_scene_causal_readiness,
            )
            # Load causal skeleton from the scene_details or long_synopsis artifact
            for step_key in ("scene_details", "long_synopsis"):
                art = self.session.execute(
                    select(SnowflakeArtifact).where(
                        SnowflakeArtifact.project_id == project.project_id,
                        SnowflakeArtifact.step_key == step_key,
                    ).order_by(SnowflakeArtifact.version.desc())
                ).scalars().first()
                if art and art.artifact_json and art.artifact_json.get("causal_skeleton"):
                    skeleton_data = art.artifact_json["causal_skeleton"]
                    break
            else:
                return None  # no skeleton found

            # Reconstruct skeleton from JSON
            chain_data = skeleton_data.get("chain", [])
            if not chain_data:
                return None
            chain = [
                CausalLink(
                    step_index=link.get("step_index", i),
                    description=link.get("description", ""),
                    why_necessary=link.get("why_necessary", ""),
                    character_state_before=link.get("state_before") or link.get("character_state_before"),
                    character_state_after=link.get("state_after") or link.get("character_state_after"),
                    depends_on_index=link.get("depends_on_index"),
                    scene_id=link.get("scene_id"),
                )
                for i, link in enumerate(chain_data)
            ]
            skeleton = ReverseCausalSkeleton(
                controlling_idea=skeleton_data.get("controlling_idea", ""),
                ending_state=skeleton_data.get("ending_state", ""),
                chain=chain,
            )

            # Skeleton step indices are project-wide narrative positions. A
            # chapter-local scene_seq cannot distinguish CH01/SC01 from
            # CH02/SC01 and becomes stale after a catalog reorder.
            position_service = NarrativePositionService(self.session)
            ordered_scenes = position_service.ordered_scenes(project.project_id)
            scene_ordinal_by_id = {
                positioned_scene.scene_id: ordinal
                for ordinal, positioned_scene in enumerate(ordered_scenes, start=1)
            }
            scene_ordinal = scene_ordinal_by_id.get(scene.scene_id)
            # ReverseCausalSkeleton.step_index is zero-based while catalog
            # scene ordinals are one-based.
            scene_step_index = scene_ordinal - 1 if scene_ordinal is not None else None
            completed_scene_ids = {
                *self._canonical_completed_scene_ids(
                    project.project_id,
                    position_service=position_service,
                )
            }
            completed_scene_step_indices = sorted(
                scene_ordinal_by_id[completed_scene_id] - 1
                for completed_scene_id in completed_scene_ids
                if completed_scene_id in scene_ordinal_by_id
            )

            readiness = validate_scene_causal_readiness(
                skeleton,
                scene_step_index,
                completed_scenes=completed_scene_step_indices,
                scene_id=scene.scene_id,
                completed_scene_ids=sorted(completed_scene_ids),
                strict=False,  # advisory by default — author can enable strict per-project
            )
            return SceneCausalReadinessAssessment(
                warning=readiness.format_for_prompt() if readiness.unresolved else None,
                diagnostics=[diagnostic.as_dict() for diagnostic in readiness.diagnostics],
            )

        except Exception as exc:
            # Causal readiness stays advisory, but evaluation failure must not
            # masquerade as a clean result.
            logger.exception(
                "causal_readiness_evaluation_failed",
                extra={
                    "event_code": "CAUSAL_READINESS_INTERNAL_ERROR",
                    "project_id": project.project_id,
                    "scene_id": scene.scene_id,
                    "error_type": type(exc).__name__,
                },
            )
            return SceneCausalReadinessAssessment(
                diagnostics=[
                    {
                        "code": "CAUSAL_READINESS_INTERNAL_ERROR",
                        "message": "causal readiness evaluation failed; generation remains advisory",
                        "context": {
                            "project_id": project.project_id,
                            "scene_id": scene.scene_id,
                            "error_type": type(exc).__name__,
                        },
                    }
                ]
            )

    def _canonical_completed_scene_ids(
        self,
        project_id: str,
        *,
        position_service: NarrativePositionService | None = None,
    ) -> set[str]:
        """Return only scenes whose runtime pointer names the authority row.

        ``final_scenes`` is append-only history after author-draft promotion.  A
        historical/superseded row must never satisfy a causal prerequisite merely
        because it still exists.  The scene is complete only when the current
        ``SceneRunState`` pointer resolves to a ``FinalScene`` for that same scene.
        """

        positions = position_service or NarrativePositionService(self.session)
        statement = (
            positions.scene_statement(project_id)
            .join(SceneRunState, SceneRunState.scene_id == SceneCard.scene_id)
            .join(
                FinalScene,
                and_(
                    FinalScene.row_id == SceneRunState.current_final_scene_row_id,
                    FinalScene.scene_id == SceneCard.scene_id,
                ),
            )
        )
        return {
            completed_scene.scene_id
            for completed_scene in self.session.execute(statement).scalars().all()
        }

    def _require_scene(self, scene_id: str) -> SceneCard:
        scene = self.session.get(SceneCard, scene_id)
        if scene is None or scene.trashed_flag == 1:
            raise DomainError("SCENE_NOT_FOUND", "scene not found", status_code=404)
        return scene

    def _require_chapter(self, chapter_id: str) -> ChapterGoal:
        chapter = self.session.get(ChapterGoal, chapter_id)
        if chapter is None or chapter.trashed_flag == 1:
            raise DomainError("CHAPTER_NOT_FOUND", "chapter not found", status_code=404)
        return chapter


class SceneTriageService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.contracts = SceneExecutionContractService(session)
        self.backtracks = ProjectBacktrackService(session)

    def evaluate(self, scene_id: str, *, actor_ref: str = "operator", mutate: bool = True) -> dict[str, Any]:
        scene = self.contracts._require_scene(scene_id)
        state = self.session.get(SceneRunState, scene_id)
        if state is None:
            raise DomainError("SCENE_RUN_STATE_NOT_FOUND", "scene run state not found", status_code=404)
        contract = self.contracts.get_or_create(scene_id, actor_ref=actor_ref)
        latest_qc = self._latest_qc_report(scene_id, state)
        decision = "yes"
        next_action = "chapter_aggregate"
        reason_codes: list[str] = []
        backtrack_item = None

        if contract.status == "stale":
            decision = "no"
            next_action = "create_backtrack_item"
            reason_codes = ["execution_contract_stale"]
        elif contract.status == "blocked":
            decision = "no"
            next_action = "create_backtrack_item"
            reason_codes = ["execution_contract_blocked", *list(contract.missing_fields_json or [])]
        elif latest_qc is not None and (latest_qc.next_action == "patch" or latest_qc.resolution_code == "soft_patch_requested"):
            if state.soft_patch_count >= 1:
                decision = "no"
                next_action = "create_backtrack_item"
                reason_codes = ["soft_patch_limit_reached", latest_qc.resolution_code or "soft_patch_requested"]
            else:
                decision = "maybe"
                next_action = "auto_rewrite"
                reason_codes = [latest_qc.resolution_code or "soft_patch_requested"]
        elif latest_qc is not None and latest_qc.next_action == "rewrite_partial":
            if state.hard_partial_rewrite_count >= 2:
                decision = "no"
                next_action = "create_backtrack_item"
                reason_codes = ["hard_partial_limit_reached", latest_qc.resolution_code or "rewrite_partial"]
            else:
                decision = "maybe"
                next_action = "auto_rewrite"
                reason_codes = [latest_qc.resolution_code or "rewrite_partial"]
        elif state.current_human_review_event_id:
            decision = "no"
            next_action = "create_backtrack_item"
            reason_codes = ["human_review_required"]
        elif not state.current_final_scene_row_id:
            decision = "maybe"
            next_action = "auto_rewrite"
            reason_codes = ["final_scene_missing"]

        if decision == "no" and mutate:
            backtrack_item = self._ensure_backtrack_item(scene, contract, latest_qc, reason_codes, actor_ref=actor_ref)
            self._mark_scene_for_replan(state)
        payload = {
            "scene_id": scene.scene_id,
            "decision": decision,
            "reason_codes": reason_codes,
            "next_action": next_action,
            "source_qc_report_id": latest_qc.qc_report_id if latest_qc is not None else None,
            "execution_contract_id": contract.contract_id,
            "backtrack_item_id": backtrack_item.item_id if backtrack_item is not None else None,
        }
        self.session.flush()
        return payload

    def _ensure_backtrack_item(
        self,
        scene: SceneCard,
        contract: SceneExecutionContract,
        latest_qc: QcReport | None,
        reason_codes: list[str],
        *,
        actor_ref: str,
    ):
        scope = _scope_from_reasons(reason_codes)
        summary = _problem_summary(contract, latest_qc, reason_codes)
        recommended_fix = _recommended_fix(scope, contract, latest_qc)
        return self.backtracks.ensure_item(
            project_id=scene.project_id or "",
            chapter_id=scene.chapter_id,
            scene_id=scene.scene_id,
            scope=scope,
            target_ref=f"scene_card:{scene.scene_id}",
            problem_summary=summary,
            recommended_fix=recommended_fix,
            reason_codes=reason_codes,
            source_qc_report_id=latest_qc.qc_report_id if latest_qc is not None else None,
            source_contract_id=contract.contract_id,
            created_by=actor_ref or "operator",
        )

    @staticmethod
    def _mark_scene_for_replan(state: SceneRunState) -> None:
        state.scene_status = "needs_replan"
        state.current_bundle_id = None
        state.current_bundle_hash = None
        state.current_neutral_draft_row_id = None
        state.current_style_draft_row_id = None
        state.current_final_scene_row_id = None
        state.current_qc_report_id = None
        state.current_human_review_event_id = None

    def _latest_qc_report(self, scene_id: str, state: SceneRunState) -> QcReport | None:
        if state.current_qc_report_id:
            report = self.session.get(QcReport, state.current_qc_report_id)
            if report is not None and report.scene_id == scene_id:
                return report
        return self.session.execute(
            select(QcReport)
            .where(QcReport.scene_id == scene_id, QcReport.status != "stale")
            .order_by(QcReport.created_at.desc(), QcReport.qc_report_id.desc())
        ).scalars().first()


def _infer_scene_mode(scene: SceneCard, brief: dict[str, Any]) -> str:
    for value in (brief.get("scene_mode"), brief.get("scene_form"), scene.scene_type):
        text = str(value or "").strip().lower()
        if text in {"reactive", "reaction"}:
            return "reactive"
        if text in {"proactive", "goal"}:
            return "proactive"
    return "reactive" if brief.get("reaction") or brief.get("decision") else "proactive"


def _is_explicit_structured_scene(scene: SceneCard, brief: dict[str, Any]) -> bool:
    for value in (brief.get("scene_mode"), brief.get("scene_form"), scene.scene_type):
        text = str(value or "").strip().lower()
        if text in {"proactive", "reactive", "reaction", "goal"}:
            return True
    return False


def _normalize_reference_rules(profile_json: dict[str, Any]) -> dict[str, list[str]]:
    style_rules = _listify(profile_json.get("style_rules"))
    structure_rules = _listify(profile_json.get("structure_rules"))
    safety_rules = _listify(profile_json.get("safety_rules"))
    if not style_rules:
        style_rules = (
            _listify(profile_json.get("style_features"))
            + _listify(profile_json.get("rhythm"))
            + _listify(profile_json.get("syntax"))
            + _listify(profile_json.get("narrative_methods"))
        )
    if not structure_rules:
        structure_rules = (
            _listify(profile_json.get("narrative_patterns"))
            + _listify(profile_json.get("calibration_guidance"))
            + _listify(profile_json.get("structure_patterns"))
            + _listify(profile_json.get("structure_techniques"))
        )
    if not safety_rules:
        safety_rules = (
            _listify(profile_json.get("banned_replication_rules"))
            + _listify(profile_json.get("forbidden_copy_rules"))
            + _listify(profile_json.get("safety_constraints"))
        )
    return {
        "style_rules": _dedupe(style_rules),
        "structure_rules": _dedupe(structure_rules),
        "safety_rules": _dedupe(safety_rules),
    }


def _scope_from_reasons(reason_codes: list[str]) -> str:
    joined = " ".join(reason_codes)
    if "character" in joined:
        return "character"
    if "synopsis" in joined or "moral_premise" in joined:
        return "synopsis"
    if "scene_list" in joined:
        return "scene_list"
    return "scene_detail"


FIELD_LABELS = {
    "scene_crucible": "坩埚/场景压力",
    "crucible": "坩埚/场景压力",
    "conflict": "冲突推进",
    "setback_or_victory": "挫折/胜负变化",
    "setback": "挫折",
    "goal": "场景目标",
    "reaction": "反应",
    "dilemma": "困境",
    "decision": "决定",
}


def _field_labels(fields: list[str]) -> list[str]:
    return [FIELD_LABELS.get(str(field), str(field)) for field in fields]


def _problem_summary(contract: SceneExecutionContract, latest_qc: QcReport | None, reason_codes: list[str]) -> str:
    if contract.status == "blocked":
        missing = "、".join(_field_labels(contract.missing_fields_json or []))
        return f"场景执行契约还缺少作者可判断的关键项：{missing}。"
    if contract.status == "stale":
        return "上游雪花规划已经变化，当前场景执行契约需要刷新。"
    if latest_qc is not None and latest_qc.issues_json:
        first_issue = latest_qc.issues_json[0]
        if isinstance(first_issue, dict) and first_issue.get("message"):
            return str(first_issue["message"])
    return f"场景急救判断为需要重做：{'、'.join(reason_codes)}。"


def _recommended_fix(scope: str, contract: SceneExecutionContract, latest_qc: QcReport | None) -> str:
    if contract.status == "blocked":
        missing = "、".join(_field_labels(contract.missing_fields_json or []))
        return f"回到场景规划，把这些项补成可写判断：{missing}。"
    if contract.status == "stale":
        return "复核更新后的雪花步骤，重新生成场景执行契约，再从刷新后的规划起草。"
    if scope == "character":
        return "回到角色摘要或角色全档案，让场景选择重新贴合角色目标、价值观和压力。"
    return "回到场景规划，重设坩埚/场景压力和行动逻辑，再生成执行契约。"


def _first_text(*values: Any) -> str:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _has_text(value: Any) -> bool:
    return isinstance(value, str) and value.strip() != ""


def _listify(value: Any) -> list[str]:
    if isinstance(value, str):
        text = value.strip()
        return [text] if text else []
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _beat_text(scene: SceneCard, index: int) -> str:
    beats = [str(item).strip() for item in list(scene.beats_json or []) if str(item).strip()]
    if index < 0 or index >= len(beats):
        return ""
    return beats[index]


def _last_beat(scene: SceneCard) -> str:
    beats = [str(item).strip() for item in list(scene.beats_json or []) if str(item).strip()]
    return beats[-1] if beats else ""


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        ordered.append(value)
    return ordered
