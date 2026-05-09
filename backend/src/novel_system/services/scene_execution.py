from __future__ import annotations

import hashlib
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from novel_system.db.models import (
    ChapterGoal,
    QcReport,
    ReferenceProfile,
    SceneBlueprint,
    SceneCard,
    SceneExecutionContract,
    SceneRunState,
    StoryProject,
)
from novel_system.services.errors import DomainError
from novel_system.services.hash_engine import canonical_json
from novel_system.services.project_backtracks import ProjectBacktrackService

EXECUTION_CONTRACT_VERSION = "scene_execution_contract_v1"


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
        status = "active" if not missing_fields else "blocked"

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
            "reference_rules": reference_rules,
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

    @staticmethod
    def _missing_fields(payload: dict[str, Any]) -> list[str]:
        missing = []
        for field in ("scene_mode", "pov_character_id", "scene_crucible"):
            if not _has_text(payload.get(field)):
                missing.append(field)
        scene_mode = str(payload.get("scene_mode") or "proactive")
        if scene_mode == "reactive":
            for field in ("reaction", "dilemma", "decision"):
                if not _has_text(payload.get(field)):
                    missing.append(field)
        else:
            for field in ("goal", "conflict", "setback_or_victory"):
                if not _has_text(payload.get(field)):
                    missing.append(field)
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
                "reference_profile_ids": list(project.reference_profile_ids_json or []) if project is not None else [],
            },
            "blueprint_json": dict(blueprint.blueprint_json or {}) if blueprint is not None else {},
            "reference_rules": reference_rules,
            "contract_version": EXECUTION_CONTRACT_VERSION,
        }

    def _reference_rules(self, project: StoryProject | None) -> dict[str, list[str]]:
        if project is None:
            return {"style_rules": [], "structure_rules": [], "safety_rules": []}
        profile_ids = list(project.reference_profile_ids_json or [])
        if not profile_ids:
            return {"style_rules": [], "structure_rules": [], "safety_rules": []}
        profiles = self.session.execute(
            select(ReferenceProfile).where(ReferenceProfile.profile_id.in_(profile_ids))
        ).scalars().all()
        style_rules: list[str] = []
        structure_rules: list[str] = []
        safety_rules: list[str] = []
        for profile in profiles:
            rules = _normalize_reference_rules(profile.profile_json or {})
            style_rules.extend(rules["style_rules"])
            structure_rules.extend(rules["structure_rules"])
            safety_rules.extend(rules["safety_rules"])
        return {
            "style_rules": _dedupe(style_rules),
            "structure_rules": _dedupe(structure_rules),
            "safety_rules": _dedupe(safety_rules),
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
        style_rules = _listify(profile_json.get("rhythm")) + _listify(profile_json.get("syntax")) + _listify(profile_json.get("narrative_methods"))
    if not structure_rules:
        structure_rules = _listify(profile_json.get("structure_patterns")) + _listify(profile_json.get("structure_techniques"))
    if not safety_rules:
        safety_rules = _listify(profile_json.get("forbidden_copy_rules")) + _listify(profile_json.get("safety_constraints"))
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


def _problem_summary(contract: SceneExecutionContract, latest_qc: QcReport | None, reason_codes: list[str]) -> str:
    if contract.status == "blocked":
        missing = ", ".join(contract.missing_fields_json or [])
        return f"Scene execution contract is missing required fields: {missing}."
    if contract.status == "stale":
        return "Scene execution contract is stale because upstream snowflake planning changed."
    if latest_qc is not None and latest_qc.issues_json:
        first_issue = latest_qc.issues_json[0]
        if isinstance(first_issue, dict) and first_issue.get("message"):
            return str(first_issue["message"])
    return f"Scene needs replanning because triage returned no: {', '.join(reason_codes)}."


def _recommended_fix(scope: str, contract: SceneExecutionContract, latest_qc: QcReport | None) -> str:
    if contract.status == "blocked":
        missing = ", ".join(contract.missing_fields_json or [])
        return f"Return to scene_details and fill the missing contract fields: {missing}."
    if contract.status == "stale":
        return "Review the updated snowflake step, regenerate the execution contract, and rerun drafting from the refreshed plan."
    if scope == "character":
        return "Return to character_sheets or character_bibles and align the scene choice with the character's goal, values, and pressure."
    return "Return to scene_details, redesign the scene crucible and the action logic, then regenerate the execution contract before drafting again."


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
