from __future__ import annotations

import json
import hashlib
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from novel_system.db.models import (
    ChapterGoal,
    ChapterMemory,
    ChapterState,
    FinalScene,
    RevisionCandidate,
    SceneBlueprint,
    SceneBundle,
    SceneCard,
    SceneDraft,
    SceneRunState,
    WriterEvaluation,
)
from novel_system.services.errors import DomainError
from novel_system.services.hash_engine import canonical_json
from novel_system.services.llm_accounting import LLMCallContext
from novel_system.services.llm_task_runner import (
    LLMNodeExecutionError,
    LLMNodeRunner,
    current_llm_execution_id,
)
from novel_system.services.prompt_builder import PromptBuilder
from novel_system.services.writer_briefs import normalize_chapter_writer_brief, normalize_scene_writer_brief

WRITER_RUBRIC_ID = "drama_effectiveness_v1"

WRITER_RUBRIC_DIMENSIONS: tuple[str, ...] = (
    "desire",
    "obstacle",
    "stakes",
    "turn",
    "subtext",
    "irreversible_change",
    "scene_necessity",
    "reader_hook",
    "continuity",
)

PROFESSIONAL_WRITER_DIMENSIONS: tuple[str, ...] = (
    "character_agency",
    "dialogue_edge",
    "information_rhythm",
    "imagery_freshness",
    "expression_repetition",
    "power_shift",
    "ending_drive",
)

ALL_WRITER_REVIEW_DIMENSIONS: tuple[str, ...] = WRITER_RUBRIC_DIMENSIONS + PROFESSIONAL_WRITER_DIMENSIONS


@dataclass(frozen=True, slots=True)
class WriterReviewLens:
    lens: str
    label: str
    scene_node_id: str
    chapter_node_id: str
    focus_dimensions: tuple[str, ...]


WRITER_REVIEW_LENSES: tuple[WriterReviewLens, ...] = (
    WriterReviewLens(
        lens="story",
        label="Story Editor",
        scene_node_id="writer_scene_story_diagnosis",
        chapter_node_id="writer_chapter_story_diagnosis",
        focus_dimensions=("scene_necessity", "information_rhythm", "turn", "continuity", "ending_drive"),
    ),
    WriterReviewLens(
        lens="character",
        label="Character Editor",
        scene_node_id="writer_scene_character_diagnosis",
        chapter_node_id="writer_chapter_character_diagnosis",
        focus_dimensions=("character_agency", "desire", "obstacle", "power_shift", "subtext"),
    ),
    WriterReviewLens(
        lens="prose",
        label="Prose Editor",
        scene_node_id="writer_scene_prose_diagnosis",
        chapter_node_id="writer_chapter_prose_diagnosis",
        focus_dimensions=("dialogue_edge", "imagery_freshness", "expression_repetition", "subtext"),
    ),
    WriterReviewLens(
        lens="reader",
        label="Reader Editor",
        scene_node_id="writer_scene_reader_diagnosis",
        chapter_node_id="writer_chapter_reader_diagnosis",
        focus_dimensions=("reader_hook", "stakes", "ending_drive", "information_rhythm"),
    ),
)


class WriterReviewService:
    def __init__(self, session: Session, *, llm_client: Any | None = None, llm_runner: LLMNodeRunner | None = None) -> None:
        self.session = session
        self.prompt_builder = PromptBuilder()
        self._llm_runner = llm_runner or LLMNodeRunner(session, llm_client=llm_client)

    def scene_review(self, scene_id: str) -> dict[str, Any]:
        scene = self._require_scene(scene_id)
        return self._review_payload("scene", scene.scene_id)

    def chapter_review(self, chapter_id: str) -> dict[str, Any]:
        chapter = self._require_chapter(chapter_id)
        return self._review_payload("chapter", chapter.chapter_id)

    def run_scene_review(self, scene_id: str, actor_ref: str = "operator") -> dict[str, Any]:
        scene = self._require_scene(scene_id)
        chapter = self._require_chapter(scene.chapter_id)
        source = self._scene_source(scene)
        brief = normalize_scene_writer_brief(scene.writer_brief_json)
        chapter_brief = normalize_chapter_writer_brief(chapter.writer_brief_json)
        blueprint = self._latest_scene_blueprint(scene.scene_id)
        if blueprint is not None:
            source["source_blueprint_row_id"] = blueprint.row_id
        bundle = self._scene_review_bundle(scene)
        diagnosis = self._run_multi_lens_diagnosis(
            object_type="scene",
            object_id=scene.scene_id,
            chapter_id=scene.chapter_id,
            scene_id=scene.scene_id,
            bundle=bundle,
            source=source,
            writer_context={
                "scene_writer_brief": brief,
                "chapter_writer_brief": chapter_brief,
                "scene_blueprint": blueprint.blueprint_json if blueprint is not None else None,
                "scene_goal": scene.scene_goal,
                "chapter_goal": chapter.chapter_goal,
            },
            template_name="writer_scene_diagnosis",
        )
        if diagnosis["blocked"]:
            evaluation = self._create_evaluation_from_payload(
                object_type="scene",
                object_id=scene.scene_id,
                chapter_id=scene.chapter_id,
                scene_id=scene.scene_id,
                source=source,
                payload=diagnosis["payload"],
                llm_call_id=diagnosis["llm_call_id"],
                source_blueprint_row_id=source.get("source_blueprint_row_id"),
            )
            self._supersede_open_candidates("scene", scene.scene_id)
            self.session.flush()
            return {
                **self._review_payload("scene", scene.scene_id),
                "evaluation": self.serialize_evaluation(evaluation),
                "candidates": [],
            }
        payload = diagnosis["payload"]
        evaluation = self._create_lens_evaluations(
            object_type="scene",
            object_id=scene.scene_id,
            chapter_id=scene.chapter_id,
            scene_id=scene.scene_id,
            source=source,
            aggregate_payload=payload,
            lens_results=diagnosis["lens_results"],
        )
        self._supersede_open_candidates("scene", scene.scene_id)
        revision_payload = self._run_scene_revision(
            scene=scene,
            bundle=bundle,
            source=source,
            diagnosis_payload=payload,
            evaluation=evaluation,
        )
        candidate = self._create_candidate(
            evaluation=evaluation,
            revision_type="scene_revision",
            source=source,
            proposed_text=revision_payload["proposed_text"],
            actor_ref=actor_ref,
            diff_summary=revision_payload["diff_summary"],
            patches=revision_payload.get("patches"),
        )
        self.session.flush()
        return {
            **self._review_payload("scene", scene.scene_id),
            "evaluation": self.serialize_evaluation(evaluation),
            "candidates": [self.serialize_revision(candidate)],
        }

    def run_chapter_review(self, chapter_id: str, actor_ref: str = "operator") -> dict[str, Any]:
        chapter = self._require_chapter(chapter_id)
        source = self._chapter_source(chapter)
        brief = normalize_chapter_writer_brief(chapter.writer_brief_json)
        bundle = self._chapter_review_bundle(chapter, source, brief)
        diagnosis = self._run_multi_lens_diagnosis(
            object_type="chapter",
            object_id=chapter.chapter_id,
            chapter_id=chapter.chapter_id,
            scene_id=None,
            bundle=bundle,
            source=source,
            writer_context={
                "chapter_writer_brief": brief,
                "chapter_goal": chapter.chapter_goal,
                "main_plot_push": chapter.main_plot_push,
                "emotional_target": chapter.emotional_target,
                "ending_effect": chapter.ending_effect,
            },
            template_name="writer_chapter_diagnosis",
        )
        if diagnosis["blocked"]:
            evaluation = self._create_evaluation_from_payload(
                object_type="chapter",
                object_id=chapter.chapter_id,
                chapter_id=chapter.chapter_id,
                scene_id=None,
                source=source,
                payload=diagnosis["payload"],
                llm_call_id=diagnosis["llm_call_id"],
            )
            self._supersede_open_candidates("chapter", chapter.chapter_id)
            self.session.flush()
            return {
                **self._review_payload("chapter", chapter.chapter_id),
                "evaluation": self.serialize_evaluation(evaluation),
                "candidates": [],
            }
        payload = diagnosis["payload"]
        evaluation = self._create_lens_evaluations(
            object_type="chapter",
            object_id=chapter.chapter_id,
            chapter_id=chapter.chapter_id,
            scene_id=None,
            source=source,
            aggregate_payload=payload,
            lens_results=diagnosis["lens_results"],
        )
        self._supersede_open_candidates("chapter", chapter.chapter_id)
        revision_payload = self._run_chapter_revision(
            chapter=chapter,
            bundle=bundle,
            source=source,
            diagnosis_payload=payload,
            evaluation=evaluation,
        )
        candidate = self._create_candidate(
            evaluation=evaluation,
            revision_type="chapter_revision",
            source=source,
            proposed_text=revision_payload["proposed_text"],
            actor_ref=actor_ref,
            diff_summary=revision_payload["diff_summary"],
            patches=revision_payload.get("patches"),
        )
        self.session.flush()
        return {
            **self._review_payload("chapter", chapter.chapter_id),
            "evaluation": self.serialize_evaluation(evaluation),
            "candidates": [self.serialize_revision(candidate)],
        }

    def accept_revision(self, revision_id: str, note: str | None = None) -> dict[str, Any]:
        revision = self._require_revision(revision_id)
        revision.status = "accepted"
        revision.author_decision_note = note or revision.author_decision_note
        self.session.flush()
        return {"revision": self.serialize_revision(revision)}

    def reject_revision(self, revision_id: str, note: str | None = None) -> dict[str, Any]:
        revision = self._require_revision(revision_id)
        revision.status = "rejected"
        revision.author_decision_note = note or revision.author_decision_note
        self.session.flush()
        return {"revision": self.serialize_revision(revision)}

    def scene_summary(self, scene_id: str) -> dict[str, Any]:
        return self._review_payload("scene", scene_id)

    def chapter_summary(self, chapter_id: str) -> dict[str, Any]:
        return self._review_payload("chapter", chapter_id)

    def summaries(self, object_type: str, object_ids: list[str]) -> dict[str, dict[str, Any]]:
        """Load review summaries for one object type in a bounded query set."""

        ordered_ids = list(dict.fromkeys(object_id for object_id in object_ids if object_id))
        if not ordered_ids:
            return {}

        latest_rows = self.session.execute(
            select(WriterEvaluation)
            .where(
                WriterEvaluation.object_type == object_type,
                WriterEvaluation.object_id.in_(ordered_ids),
                WriterEvaluation.parent_evaluation_id.is_(None),
            )
            .order_by(
                WriterEvaluation.object_id.asc(),
                WriterEvaluation.created_at.desc(),
                WriterEvaluation.evaluation_id.desc(),
            )
        ).scalars().all()
        latest_by_object: dict[str, WriterEvaluation] = {}
        for row in latest_rows:
            latest_by_object.setdefault(row.object_id, row)

        candidate_rows = self.session.execute(
            select(RevisionCandidate)
            .where(
                RevisionCandidate.object_type == object_type,
                RevisionCandidate.object_id.in_(ordered_ids),
            )
            .order_by(
                RevisionCandidate.object_id.asc(),
                RevisionCandidate.created_at.desc(),
                RevisionCandidate.revision_id.desc(),
            )
        ).scalars().all()
        candidates_by_object: dict[str, list[RevisionCandidate]] = {
            object_id: [] for object_id in ordered_ids
        }
        for row in candidate_rows:
            candidates_by_object.setdefault(row.object_id, []).append(row)

        lens_by_parent: dict[str, list[WriterEvaluation]] = {}
        parent_ids = [row.evaluation_id for row in latest_by_object.values()]
        if parent_ids:
            lens_rows = self.session.execute(
                select(WriterEvaluation)
                .where(WriterEvaluation.parent_evaluation_id.in_(parent_ids))
                .order_by(
                    WriterEvaluation.parent_evaluation_id.asc(),
                    WriterEvaluation.lens.asc(),
                    WriterEvaluation.evaluation_id.asc(),
                )
            ).scalars().all()
            for row in lens_rows:
                if row.parent_evaluation_id:
                    lens_by_parent.setdefault(row.parent_evaluation_id, []).append(row)

        return {
            object_id: self._review_payload_from_rows(
                object_type=object_type,
                object_id=object_id,
                latest=latest_by_object.get(object_id),
                candidates=candidates_by_object.get(object_id, []),
                lens_rows=lens_by_parent.get(
                    latest_by_object[object_id].evaluation_id,
                    [],
                )
                if object_id in latest_by_object
                else [],
            )
            for object_id in ordered_ids
        }

    @staticmethod
    def serialize_evaluation(evaluation: WriterEvaluation | None) -> dict[str, Any] | None:
        if evaluation is None:
            return None
        return {
            "evaluation_id": evaluation.evaluation_id,
            "object_type": evaluation.object_type,
            "object_id": evaluation.object_id,
            "chapter_id": evaluation.chapter_id,
            "scene_id": evaluation.scene_id,
            "rubric_id": evaluation.rubric_id,
            "source_text_ref": evaluation.source_text_ref,
            "source_bundle_id": evaluation.source_bundle_id,
            "evaluator_llm_call_id": evaluation.evaluator_llm_call_id,
            "lens": evaluation.lens or "aggregate",
            "parent_evaluation_id": evaluation.parent_evaluation_id,
            "evidence_spans": evaluation.evidence_spans_json or [],
            "source_blueprint_row_id": evaluation.source_blueprint_row_id,
            "overall_score": evaluation.overall_score,
            "scores": evaluation.scores_json or {},
            "findings": evaluation.findings_json or [],
            "failure_class": evaluation.failure_class,
            "auto_rewrite_eligible": bool(evaluation.auto_rewrite_eligible) if evaluation.auto_rewrite_eligible is not None else None,
            "contract_field_refs": evaluation.contract_field_refs_json or {},
            "promotion_blockers": evaluation.promotion_blockers_json or [],
            "revision_brief": evaluation.revision_brief_json or [],
            "requires_human_review": bool(evaluation.requires_human_review),
            "status": evaluation.status,
            "created_at": evaluation.created_at,
        }

    @staticmethod
    def serialize_revision(revision: RevisionCandidate) -> dict[str, Any]:
        return {
            "revision_id": revision.revision_id,
            "evaluation_id": revision.evaluation_id,
            "object_type": revision.object_type,
            "object_id": revision.object_id,
            "chapter_id": revision.chapter_id,
            "scene_id": revision.scene_id,
            "revision_type": revision.revision_type,
            "source_text_ref": revision.source_text_ref,
            "proposed_text": revision.proposed_text,
            "instruction": revision.instruction_json or [],
            "diff_summary": revision.diff_summary_json or {},
            "patches": revision.patches_json or [],
            "apply_mode": revision.apply_mode or "manual_only",
            "target_text_ref": revision.target_text_ref or revision.source_text_ref,
            "status": revision.status,
            "author_decision_note": revision.author_decision_note,
            "created_by": revision.created_by,
            "created_at": revision.created_at,
            "updated_at": revision.updated_at,
        }

    def _review_payload(self, object_type: str, object_id: str) -> dict[str, Any]:
        return self.summaries(object_type, [object_id])[object_id]

    def _review_payload_from_rows(
        self,
        *,
        object_type: str,
        object_id: str,
        latest: WriterEvaluation | None,
        candidates: list[RevisionCandidate],
        lens_rows: list[WriterEvaluation],
    ) -> dict[str, Any]:
        serialized_latest = self.serialize_evaluation(latest)
        lens_evaluations = [item for item in (self.serialize_evaluation(row) for row in lens_rows) if item]
        return {
            "status": "reviewed" if latest else "not_run",
            "object_type": object_type,
            "object_id": object_id,
            "rubric_id": WRITER_RUBRIC_ID,
            "latest_evaluation": serialized_latest,
            "latest_score": serialized_latest["overall_score"] if serialized_latest else None,
            "requires_human_review": bool(serialized_latest["requires_human_review"]) if serialized_latest else False,
            "lens_evaluations": lens_evaluations,
            "candidate_count": len(candidates),
            "candidates": [self.serialize_revision(candidate) for candidate in candidates],
        }

    def _create_evaluation(
        self,
        *,
        object_type: str,
        object_id: str,
        chapter_id: str | None,
        scene_id: str | None,
        source: dict[str, Any],
        scores: dict[str, float],
        findings: list[dict[str, Any]],
        revision_brief: list[dict[str, Any]],
        overall_score: float | None = None,
        requires_human_review: bool | None = None,
        evaluator_llm_call_id: str | None = None,
        lens: str | None = None,
        parent_evaluation_id: str | None = None,
        evidence_spans: list[dict[str, Any]] | None = None,
        source_blueprint_row_id: str | None = None,
        evaluation_id: str | None = None,
    ) -> WriterEvaluation:
        low_score = any(score < 0.55 for score in scores.values())
        resolved_score = overall_score
        if resolved_score is None:
            resolved_score = round(sum(scores.values()) / len(scores), 2) if scores else None
        resolved_human_review = low_score or not source.get("content")
        if requires_human_review is not None:
            resolved_human_review = bool(requires_human_review)
        evaluation = WriterEvaluation(
            evaluation_id=evaluation_id or f"writer_eval_{object_type}_{object_id}_{uuid.uuid4().hex[:10]}",
            object_type=object_type,
            object_id=object_id,
            chapter_id=chapter_id,
            scene_id=scene_id,
            rubric_id=WRITER_RUBRIC_ID,
            source_text_ref=source.get("source_text_ref"),
            source_bundle_id=source.get("source_bundle_id"),
            evaluator_llm_call_id=evaluator_llm_call_id,
            lens=lens or "aggregate",
            parent_evaluation_id=parent_evaluation_id,
            evidence_spans_json=evidence_spans if evidence_spans is not None else _evidence_spans_from_findings(findings),
            source_blueprint_row_id=source_blueprint_row_id,
            overall_score=resolved_score,
            scores_json=scores,
            findings_json=findings,
            revision_brief_json=revision_brief,
            requires_human_review=1 if resolved_human_review else 0,
            status="completed",
        )
        self.session.add(evaluation)
        return evaluation

    def _create_candidate(
        self,
        *,
        evaluation: WriterEvaluation,
        revision_type: str,
        source: dict[str, Any],
        proposed_text: str,
        actor_ref: str,
        diff_summary: dict[str, Any] | None = None,
        patches: list[dict[str, Any]] | None = None,
    ) -> RevisionCandidate:
        summary = diff_summary or {
            "summary": "保留原文作为候选，不覆盖终稿；作者采纳后仍需人工合并。",
            "source_text_ref": source.get("source_text_ref"),
        }
        summary.setdefault("source_text_ref", source.get("source_text_ref"))
        candidate = RevisionCandidate(
            revision_id=f"revision_{evaluation.object_type}_{evaluation.object_id}_{uuid.uuid4().hex[:10]}",
            evaluation_id=evaluation.evaluation_id,
            object_type=evaluation.object_type,
            object_id=evaluation.object_id,
            chapter_id=evaluation.chapter_id,
            scene_id=evaluation.scene_id,
            revision_type=revision_type,
            source_text_ref=source.get("source_text_ref"),
            proposed_text=proposed_text,
            instruction_json=evaluation.revision_brief_json or [],
            diff_summary_json=summary,
            patches_json=patches if patches is not None else _default_candidate_patches(
                revision_type=revision_type,
                source=source,
                proposed_text=proposed_text,
                diff_summary=summary,
            ),
            apply_mode="manual_only",
            target_text_ref=source.get("source_text_ref"),
            status="candidate",
            created_by=actor_ref or "writer_engine",
        )
        self.session.add(candidate)
        return candidate

    def _supersede_open_candidates(self, object_type: str, object_id: str) -> None:
        rows = self.session.execute(
            select(RevisionCandidate).where(
                RevisionCandidate.object_type == object_type,
                RevisionCandidate.object_id == object_id,
                RevisionCandidate.status == "candidate",
            )
        ).scalars().all()
        for row in rows:
            row.status = "superseded"

    def _scene_review_bundle(self, scene: SceneCard) -> dict[str, Any]:
        state = self.session.get(SceneRunState, scene.scene_id)
        bundle_id = state.current_bundle_id if state is not None else None
        if bundle_id:
            existing = self.session.get(SceneBundle, bundle_id)
            if existing is not None:
                return {
                    "bundle_id": existing.bundle_id,
                    "bundle_snapshot_hash": existing.bundle_snapshot_hash,
                    "snapshot": existing.frozen_snapshot_json or {},
                }

        from novel_system.services.bundle_builder import BundleBuilder

        return BundleBuilder(self.session).build(scene.scene_id)

    def _chapter_review_bundle(
        self,
        chapter: ChapterGoal,
        source: dict[str, Any],
        chapter_brief: dict[str, str],
    ) -> dict[str, Any]:
        snapshot = {
            "contract_version": "WRITER_CHAPTER_REVIEW_v1",
            "stage_allowlist_name": "writer_chapter_review",
            "scene_id": "",
            "chapter_id": chapter.chapter_id,
            "source_version_refs": {
                "chapter_goal": chapter.chapter_id,
                "chapter_writer_brief": chapter.chapter_id,
                "source_text_ref": source.get("source_text_ref"),
            },
            "resolved_ref_ids": {},
            "ordered_injections": [
                {"slot": "chapter_goal", "ref_id": chapter.chapter_id, "digest_key": "chapter_goal"},
                {"slot": "chapter_writer_brief", "ref_id": chapter.chapter_id, "digest_key": "chapter_writer_brief"},
                {"slot": "chapter_summary", "ref_id": source.get("source_text_ref"), "digest_key": "chapter_summary"},
            ],
            "inline_digests": {
                "chapter_goal": chapter.chapter_goal or "",
                "chapter_writer_brief": json.dumps(chapter_brief, ensure_ascii=False, sort_keys=True),
                "chapter_summary": _compact_source_for_prompt(source.get("content") or ""),
            },
        }
        snapshot_hash = hashlib.sha256(canonical_json(snapshot).encode("utf-8")).hexdigest()
        return {
            "bundle_id": f"writer_chapter_review_{chapter.chapter_id}_{uuid.uuid4().hex[:10]}",
            "bundle_snapshot_hash": snapshot_hash,
            "snapshot": snapshot,
        }

    def _run_multi_lens_diagnosis(
        self,
        *,
        object_type: str,
        object_id: str,
        chapter_id: str,
        scene_id: str | None,
        bundle: dict[str, Any],
        source: dict[str, Any],
        writer_context: dict[str, Any],
        template_name: str,
    ) -> dict[str, Any]:
        lens_results: list[dict[str, Any]] = []
        for lens in WRITER_REVIEW_LENSES:
            node_id = lens.scene_node_id if object_type == "scene" else lens.chapter_node_id
            result = self._run_writer_diagnosis(
                object_type=object_type,
                object_id=object_id,
                chapter_id=chapter_id,
                scene_id=scene_id,
                bundle=bundle,
                source=source,
                writer_context={
                    **writer_context,
                    "active_lens": {
                        "lens": lens.lens,
                        "label": lens.label,
                        "focus_dimensions": list(lens.focus_dimensions),
                    },
                },
                node_id=node_id,
                template_name=template_name,
            )
            if result["blocked"]:
                payload = result["payload"]
                for finding in payload.get("findings") or []:
                    finding["lens"] = lens.lens
                return {
                    "blocked": True,
                    "payload": {
                        **payload,
                        "overall_score": None,
                        "scores": {},
                        "requires_human_review": True,
                    },
                    "llm_call_id": result["llm_call_id"],
                    "lens_results": [],
                }
            payload = dict(result["payload"])
            payload["findings"] = [_finding_with_lens(finding, lens.lens) for finding in payload.get("findings") or []]
            payload["revision_brief"] = [
                {**brief, "lens": lens.lens} for brief in payload.get("revision_brief") or []
            ]
            lens_results.append(
                {
                    "lens": lens,
                    "payload": payload,
                    "llm_call_id": result["llm_call_id"],
                }
            )
        return {
            "blocked": False,
            "payload": _aggregate_lens_payloads(lens_results),
            "llm_call_id": None,
            "lens_results": lens_results,
        }

    def _create_lens_evaluations(
        self,
        *,
        object_type: str,
        object_id: str,
        chapter_id: str,
        scene_id: str | None,
        source: dict[str, Any],
        aggregate_payload: dict[str, Any],
        lens_results: list[dict[str, Any]],
    ) -> WriterEvaluation:
        aggregate_id = f"writer_eval_{object_type}_{object_id}_{uuid.uuid4().hex[:10]}"
        for result in lens_results:
            lens: WriterReviewLens = result["lens"]
            payload = result["payload"]
            self._create_evaluation(
                object_type=object_type,
                object_id=object_id,
                chapter_id=chapter_id,
                scene_id=scene_id,
                source=source,
                scores=payload["scores"],
                findings=payload["findings"],
                revision_brief=payload["revision_brief"],
                overall_score=payload["overall_score"],
                requires_human_review=payload["requires_human_review"],
                evaluator_llm_call_id=result["llm_call_id"],
                lens=lens.lens,
                parent_evaluation_id=aggregate_id,
                source_blueprint_row_id=source.get("source_blueprint_row_id"),
            )
        return self._create_evaluation(
            object_type=object_type,
            object_id=object_id,
            chapter_id=chapter_id,
            scene_id=scene_id,
            source=source,
            scores=aggregate_payload["scores"],
            findings=aggregate_payload["findings"],
            revision_brief=aggregate_payload["revision_brief"],
            overall_score=aggregate_payload["overall_score"],
            requires_human_review=aggregate_payload["requires_human_review"],
            evaluator_llm_call_id=aggregate_payload.get("evaluator_llm_call_id"),
            lens="aggregate",
            source_blueprint_row_id=source.get("source_blueprint_row_id"),
            evaluation_id=aggregate_id,
        )

    def _run_writer_diagnosis(
        self,
        *,
        object_type: str,
        object_id: str,
        chapter_id: str,
        scene_id: str | None,
        bundle: dict[str, Any],
        source: dict[str, Any],
        writer_context: dict[str, Any],
        node_id: str,
        template_name: str,
    ) -> dict[str, Any]:
        node_result = None
        try:
            prompt = self.prompt_builder.build(bundle["snapshot"], template_name)
            user_prompt = _writer_review_user_prompt(
                prompt["user_prompt"],
                object_type=object_type,
                object_id=object_id,
                source=source,
                writer_context=writer_context,
            )
            chapter = self._require_chapter(chapter_id)
            execution_id = current_llm_execution_id()
            if object_type == "chapter":
                context = LLMCallContext(
                    scope_type="chapter",
                    scope_id=chapter.chapter_id,
                    project_id=chapter.project_id,
                    chapter_id=chapter.chapter_id,
                    node_id=node_id,
                    step=node_id,
                    execution_id=execution_id,
                    execution_step_key=node_id if execution_id is not None else None,
                    provider_execution_mode=self._llm_runner.provider_execution_mode,
                )
            else:
                context = LLMCallContext(
                    scope_type="scene",
                    scope_id=object_id,
                    project_id=chapter.project_id,
                    chapter_id=chapter.chapter_id,
                    scene_id=scene_id,
                    node_id=node_id,
                    step=node_id,
                    execution_id=execution_id,
                    execution_step_key=node_id if execution_id is not None else None,
                    provider_execution_mode=self._llm_runner.provider_execution_mode,
                )
            node_result = self._llm_runner.run(
                scene_id=scene_id or f"chapter_{chapter_id}",
                chapter_id=chapter_id,
                bundle_id=bundle["bundle_id"],
                bundle_hash=bundle["bundle_snapshot_hash"],
                node_id=node_id,
                step=node_id,
                prompt=prompt,
                user_prompt=user_prompt,
                source_draft_row_id=source.get("source_text_ref"),
                source_draft_content=source.get("content"),
                execution_step_key=node_id,
                context=context,
            )
            payload = _validate_writer_diagnosis_payload(node_result.response.structured_output)
            return {"blocked": False, "payload": payload, "llm_call_id": node_result.llm_call_id}
        except LLMNodeExecutionError as exc:
            return {
                "blocked": True,
                "payload": _blocked_writer_diagnosis_payload(f"作家诊断执行失败：{exc.message}"),
                "llm_call_id": exc.llm_call_id,
            }
        except WriterReviewPayloadError as exc:
            return {
                "blocked": True,
                "payload": _blocked_writer_diagnosis_payload(str(exc)),
                "llm_call_id": node_result.llm_call_id if node_result is not None else None,
            }

    def _run_scene_revision(
        self,
        *,
        scene: SceneCard,
        bundle: dict[str, Any],
        source: dict[str, Any],
        diagnosis_payload: dict[str, Any],
        evaluation: WriterEvaluation,
    ) -> dict[str, Any]:
        prompt = self.prompt_builder.build(bundle["snapshot"], "writer_scene_revision")
        user_prompt = _writer_revision_user_prompt(
            prompt["user_prompt"],
            object_type="scene",
            source=source,
            diagnosis_payload=diagnosis_payload,
        )
        node_result = self._llm_runner.run(
            scene_id=scene.scene_id,
            chapter_id=scene.chapter_id,
            bundle_id=bundle["bundle_id"],
            bundle_hash=bundle["bundle_snapshot_hash"],
            node_id="writer_scene_revision",
            step="writer_scene_revision",
            prompt=prompt,
            user_prompt=user_prompt,
            source_draft_row_id=source.get("source_text_ref"),
            source_draft_content=source.get("content"),
        )
        return _validate_scene_revision_payload(
            node_result.response.structured_output,
            source=source,
            evaluation=evaluation,
        )

    def _run_chapter_revision(
        self,
        *,
        chapter: ChapterGoal,
        bundle: dict[str, Any],
        source: dict[str, Any],
        diagnosis_payload: dict[str, Any],
        evaluation: WriterEvaluation,
    ) -> dict[str, Any]:
        prompt = self.prompt_builder.build(bundle["snapshot"], "writer_chapter_revision")
        user_prompt = _writer_revision_user_prompt(
            prompt["user_prompt"],
            object_type="chapter",
            source=source,
            diagnosis_payload=diagnosis_payload,
        )
        execution_step_key = "writer_chapter_revision"
        execution_id = current_llm_execution_id()
        context = LLMCallContext(
            scope_type="chapter",
            scope_id=chapter.chapter_id,
            project_id=chapter.project_id,
            chapter_id=chapter.chapter_id,
            node_id="writer_chapter_revision",
            step="writer_chapter_revision",
            execution_id=execution_id,
            execution_step_key=execution_step_key if execution_id is not None else None,
            provider_execution_mode=self._llm_runner.provider_execution_mode,
        )
        node_result = self._llm_runner.run(
            scene_id=f"chapter_{chapter.chapter_id}",
            chapter_id=chapter.chapter_id,
            bundle_id=bundle["bundle_id"],
            bundle_hash=bundle["bundle_snapshot_hash"],
            node_id="writer_chapter_revision",
            step="writer_chapter_revision",
            prompt=prompt,
            user_prompt=user_prompt,
            source_draft_row_id=source.get("source_text_ref"),
            source_draft_content=source.get("content"),
            execution_step_key=execution_step_key,
            context=context,
        )
        return _validate_chapter_revision_payload(
            node_result.response.structured_output,
            source=source,
            evaluation=evaluation,
        )

    def _create_evaluation_from_payload(
        self,
        *,
        object_type: str,
        object_id: str,
        chapter_id: str | None,
        scene_id: str | None,
        source: dict[str, Any],
        payload: dict[str, Any],
        llm_call_id: str | None,
        source_blueprint_row_id: str | None = None,
    ) -> WriterEvaluation:
        return self._create_evaluation(
            object_type=object_type,
            object_id=object_id,
            chapter_id=chapter_id,
            scene_id=scene_id,
            source=source,
            scores=payload.get("scores") or {},
            findings=payload.get("findings") or [],
            revision_brief=payload.get("revision_brief") or [],
            overall_score=payload.get("overall_score"),
            requires_human_review=bool(payload.get("requires_human_review", True)),
            evaluator_llm_call_id=llm_call_id,
            lens="aggregate",
            source_blueprint_row_id=source_blueprint_row_id,
        )

    def _scene_source(self, scene: SceneCard) -> dict[str, Any]:
        state = self.session.get(SceneRunState, scene.scene_id)
        if state is not None and state.current_final_scene_row_id:
            final = self.session.get(FinalScene, state.current_final_scene_row_id)
            if final is not None and final.scene_id == scene.scene_id:
                return {
                    "content": final.content or "",
                    "source_text_ref": f"final_scene:{final.row_id}",
                    "source_bundle_id": final.source_bundle_id,
                }
        if state is not None and state.current_style_draft_row_id:
            draft = self.session.get(SceneDraft, state.current_style_draft_row_id)
            if draft is not None and draft.scene_id == scene.scene_id:
                return {
                    "content": draft.content or "",
                    "source_text_ref": f"style_draft:{draft.row_id}",
                    "source_bundle_id": draft.source_bundle_id,
                }
        if state is not None and state.current_neutral_draft_row_id:
            draft = self.session.get(SceneDraft, state.current_neutral_draft_row_id)
            if draft is not None and draft.scene_id == scene.scene_id:
                return {
                    "content": draft.content or "",
                    "source_text_ref": f"neutral_draft:{draft.row_id}",
                    "source_bundle_id": draft.source_bundle_id,
                }
        raise DomainError(
            "WRITER_REVIEW_SOURCE_MISSING",
            "writer review needs a final scene or draft as source text",
            status_code=409,
        )

    def _chapter_source(self, chapter: ChapterGoal) -> dict[str, Any]:
        state = self.session.get(ChapterState, chapter.chapter_id)
        memory = None
        if state is not None and state.last_final_memory_row_id:
            pointed = self.session.get(ChapterMemory, state.last_final_memory_row_id)
            if pointed is not None and pointed.chapter_id == chapter.chapter_id and pointed.aggregate_stage == "final":
                memory = pointed
        if memory is None:
            memory = self.session.execute(
                select(ChapterMemory)
                .where(
                    ChapterMemory.chapter_id == chapter.chapter_id,
                    ChapterMemory.aggregate_stage == "final",
                    ChapterMemory.active_flag == 1,
                )
                .order_by(ChapterMemory.created_at.desc(), ChapterMemory.row_id.desc())
            ).scalars().first()
        if memory is not None and (memory.content or "").strip():
            return {
                "content": memory.content or "",
                "source_text_ref": f"chapter_memory:{memory.row_id}",
                "source_bundle_id": None,
            }

        scenes = self.session.execute(
            select(SceneCard)
            .where(SceneCard.chapter_id == chapter.chapter_id, SceneCard.trashed_flag == 0)
            .order_by(SceneCard.scene_seq.asc(), SceneCard.scene_id.asc())
        ).scalars().all()
        contents: list[str] = []
        for scene in scenes:
            scene_state = self.session.get(SceneRunState, scene.scene_id)
            if scene_state is None or not scene_state.current_final_scene_row_id:
                continue
            final = self.session.get(FinalScene, scene_state.current_final_scene_row_id)
            if final is not None and final.scene_id == scene.scene_id:
                contents.append(final.content or "")
        content = "\n".join(part for part in contents if part)
        if not content.strip():
            raise DomainError(
                "WRITER_REVIEW_SOURCE_MISSING",
                "chapter writer review needs assembled final scene text or an aggregate",
                status_code=409,
            )
        return {
            "content": content,
            "source_text_ref": f"chapter_assembled:{chapter.chapter_id}",
            "source_bundle_id": None,
        }

    def _latest_scene_blueprint(self, scene_id: str) -> SceneBlueprint | None:
        return self.session.execute(
            select(SceneBlueprint)
            .where(SceneBlueprint.scene_id == scene_id, SceneBlueprint.status.in_(("accepted", "draft")))
            .order_by(SceneBlueprint.created_at.desc(), SceneBlueprint.row_id.desc())
        ).scalars().first()

    @staticmethod
    def _score_scene(
        source_text: str,
        scene: SceneCard,
        chapter: ChapterGoal,
        brief: dict[str, str],
        chapter_brief: dict[str, str],
    ) -> dict[str, float]:
        values = {
            "desire": [brief.get("character_desire")],
            "obstacle": [brief.get("obstacle")],
            "stakes": [brief.get("stakes")],
            "turn": [brief.get("irreversible_change"), scene.exit_change],
            "subtext": [brief.get("subtext"), brief.get("secret_or_misunderstanding")],
            "irreversible_change": [brief.get("irreversible_change"), scene.exit_change],
            "scene_necessity": [scene.scene_goal, chapter.chapter_goal, chapter_brief.get("plot_movement")],
            "reader_hook": [brief.get("reader_question"), scene.hook],
            "continuity": [chapter.chapter_goal, scene.scene_goal, chapter_brief.get("core_promise")],
        }
        return {dimension: _dimension_score(values.get(dimension, []), source_text) for dimension in WRITER_RUBRIC_DIMENSIONS}

    @staticmethod
    def _score_chapter(source_text: str, chapter: ChapterGoal, brief: dict[str, str]) -> dict[str, float]:
        values = {
            "desire": [brief.get("core_promise"), brief.get("character_shift")],
            "obstacle": [brief.get("chapter_question")],
            "stakes": [brief.get("core_promise"), chapter.emotional_target],
            "turn": [brief.get("character_shift"), chapter.ending_effect],
            "subtext": [brief.get("ending_aftertaste")],
            "irreversible_change": [brief.get("character_shift"), chapter.main_plot_push],
            "scene_necessity": [brief.get("plot_movement"), chapter.main_plot_push, chapter.chapter_goal],
            "reader_hook": [brief.get("chapter_question"), brief.get("ending_aftertaste"), chapter.ending_effect],
            "continuity": [chapter.chapter_goal, chapter.main_plot_push],
        }
        return {dimension: _dimension_score(values.get(dimension, []), source_text) for dimension in WRITER_RUBRIC_DIMENSIONS}

    @staticmethod
    def _findings_for_scene(scores: dict[str, float], brief: dict[str, str], scene: SceneCard) -> list[dict[str, Any]]:
        field_by_dimension = {
            "desire": ("character_desire", "人物欲望"),
            "obstacle": ("obstacle", "阻碍"),
            "stakes": ("stakes", "风险/代价"),
            "subtext": ("subtext", "潜台词"),
            "irreversible_change": ("irreversible_change", "不可逆变化"),
            "reader_hook": ("reader_question", "读者问题"),
        }
        findings = _missing_field_findings(scores, brief, field_by_dimension)
        if scores.get("scene_necessity", 0) < 0.55 and not (scene.scene_goal or "").strip():
            findings.append(
                {
                    "dimension": "scene_necessity",
                    "severity": "blocker",
                    "issue": "场景目标不清，读者难以判断这一场为什么必须存在。",
                    "recommendation": "补一句这场推动主线或人物关系的唯一作用。",
                }
            )
        return findings or [
            {
                "dimension": "turn",
                "severity": "suggestion",
                "issue": "戏剧卡已基本成立，修订时可继续加重转折前后的行为差异。",
                "recommendation": "让人物在结尾做出一个无法完全撤回的小动作。",
            }
        ]

    @staticmethod
    def _findings_for_chapter(scores: dict[str, float], brief: dict[str, str], chapter: ChapterGoal) -> list[dict[str, Any]]:
        field_by_dimension = {
            "desire": ("core_promise", "核心承诺"),
            "scene_necessity": ("plot_movement", "主线推进"),
            "turn": ("character_shift", "人物变化"),
            "reader_hook": ("chapter_question", "章节问题"),
            "subtext": ("ending_aftertaste", "结尾余味"),
        }
        findings = _missing_field_findings(scores, brief, field_by_dimension)
        if scores.get("continuity", 0) < 0.55 and not (chapter.chapter_goal or "").strip():
            findings.append(
                {
                    "dimension": "continuity",
                    "severity": "blocker",
                    "issue": "章节目标缺失，章级诊断无法判断场景是否同向推进。",
                    "recommendation": "先补章节目标，再运行作家诊断。",
                }
            )
        return findings or [
            {
                "dimension": "reader_hook",
                "severity": "suggestion",
                "issue": "章节承诺清晰，修订时可让结尾问题更尖锐。",
                "recommendation": "把最后一场的余味落到一个具体疑问或选择上。",
            }
        ]

    @staticmethod
    def _revision_brief(scores: dict[str, float], findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
        briefs = [
            {
                "dimension": item.get("dimension"),
                "action": item.get("recommendation"),
                "priority": "high" if item.get("severity") == "blocker" else "medium",
            }
            for item in findings[:6]
        ]
        weakest = sorted(scores.items(), key=lambda pair: pair[1])[:2]
        for dimension, score in weakest:
            if any(item.get("dimension") == dimension for item in briefs):
                continue
            briefs.append(
                {
                    "dimension": dimension,
                    "action": f"把 {dimension} 的戏剧功能从暗示推进到可见行动。",
                    "priority": "medium" if score >= 0.55 else "high",
                }
            )
        return briefs

    @staticmethod
    def _candidate_text(source_text: str, revision_brief: list[dict[str, Any]], *, title: str) -> str:
        actions = "\n".join(
            f"- {item.get('dimension')}: {item.get('action')}" for item in revision_brief if item.get("action")
        )
        return f"{source_text.rstrip()}\n\n【{title}】\n{actions}\n\n（候选稿仅供采纳，不会自动覆盖终稿。）"

    def _require_chapter(self, chapter_id: str) -> ChapterGoal:
        chapter = self.session.get(ChapterGoal, chapter_id)
        if chapter is None or chapter.trashed_flag == 1:
            raise DomainError("CHAPTER_NOT_FOUND", "chapter not found", status_code=404)
        return chapter

    def _require_scene(self, scene_id: str) -> SceneCard:
        scene = self.session.get(SceneCard, scene_id)
        if scene is None or scene.trashed_flag == 1:
            raise DomainError("SCENE_NOT_FOUND", "scene not found", status_code=404)
        return scene

    def _require_revision(self, revision_id: str) -> RevisionCandidate:
        revision = self.session.get(RevisionCandidate, revision_id)
        if revision is None:
            raise DomainError("REVISION_CANDIDATE_NOT_FOUND", "revision candidate not found", status_code=404)
        return revision


class WriterReviewPayloadError(ValueError):
    pass


def _finding_with_lens(finding: dict[str, Any], lens: str) -> dict[str, Any]:
    return {**finding, "lens": finding.get("lens") or lens}


def _aggregate_lens_payloads(lens_results: list[dict[str, Any]]) -> dict[str, Any]:
    if not lens_results:
        return _blocked_writer_diagnosis_payload("no writer review lenses returned a diagnosis")
    score_values: dict[str, list[float]] = {dimension: [] for dimension in ALL_WRITER_REVIEW_DIMENSIONS}
    findings: list[dict[str, Any]] = []
    revision_brief: list[dict[str, Any]] = []
    requires_human_review = False
    for result in lens_results:
        payload = result["payload"]
        requires_human_review = requires_human_review or bool(payload.get("requires_human_review"))
        for dimension, score in (payload.get("scores") or {}).items():
            if dimension in score_values:
                score_values[dimension].append(float(score))
        findings.extend(payload.get("findings") or [])
        revision_brief.extend(payload.get("revision_brief") or [])

    scores: dict[str, float] = {}
    for dimension, values in score_values.items():
        if values:
            scores[dimension] = round(sum(values) / len(values), 2)

    conflict_findings = _lens_conflict_findings(score_values)
    if conflict_findings:
        requires_human_review = True
        findings = conflict_findings + findings
    if any(score < 0.55 for score in scores.values()):
        requires_human_review = True

    overall_score = round(sum(scores.values()) / len(scores), 2) if scores else None
    severity_order = {"blocker": 0, "major": 1, "minor": 2, "suggestion": 3, "info": 4}
    findings = sorted(
        findings,
        key=lambda item: (
            severity_order.get(str(item.get("severity") or "").lower(), 5),
            str(item.get("dimension") or ""),
        ),
    )
    return {
        "overall_score": overall_score,
        "scores": scores,
        "findings": findings[:12],
        "revision_brief": revision_brief[:10],
        "requires_human_review": requires_human_review,
    }


def _lens_conflict_findings(score_values: dict[str, list[float]]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for dimension, values in score_values.items():
        if len(values) < 2:
            continue
        spread = max(values) - min(values)
        if spread < 0.35:
            continue
        findings.append(
            {
                "dimension": dimension,
                "severity": "major",
                "issue": f"Writer review lenses disagree on {dimension}.",
                "recommendation": "Flag for human review before treating this as a final literary judgment.",
                "evidence_excerpt": "",
                "evidence_location": "multi-lens score spread",
                "why_it_matters": "Conflicting editorial lenses can mislead revision priorities if collapsed into one confident verdict.",
                "lens": "aggregate",
            }
        )
    return findings


def _evidence_spans_from_findings(findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    spans: list[dict[str, Any]] = []
    for finding in findings:
        evidence_spans = finding.get("evidence_spans")
        if isinstance(evidence_spans, list):
            for span in evidence_spans:
                if isinstance(span, dict):
                    spans.append({**span, "dimension": finding.get("dimension"), "lens": finding.get("lens")})
    return spans


def _default_candidate_patches(
    *,
    revision_type: str,
    source: dict[str, Any],
    proposed_text: str,
    diff_summary: dict[str, Any],
) -> list[dict[str, Any]]:
    patch_type = "full_scene_rewrite" if revision_type == "scene_revision" else "revision_plan"
    return [
        {
            "patch_type": patch_type,
            "target_text_ref": source.get("source_text_ref"),
            "replacement_text": proposed_text,
            "changed_dimensions": diff_summary.get("changed_dimensions") or [],
            "manual_only": True,
        }
    ]


def _blocked_writer_diagnosis_payload(message: str) -> dict[str, Any]:
    return {
        "overall_score": None,
        "scores": {},
        "findings": [
            {
                "dimension": "writer_diagnosis_payload",
                "severity": "blocker",
                "issue": message,
                "recommendation": "请检查模型输出或 prompt schema 后重新运行；本次不伪造作家评分。",
                "evidence_excerpt": "",
                "evidence_location": "",
                "why_it_matters": "无效诊断会误导作者修改方向，必须交给人工确认。",
            }
        ],
        "revision_brief": [],
        "requires_human_review": True,
    }


def _validate_writer_diagnosis_payload(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise WriterReviewPayloadError("writer diagnosis payload must be an object")

    overall_score = _optional_score(payload.get("overall_score"), "overall_score")
    scores_payload = payload.get("scores")
    if not isinstance(scores_payload, dict):
        raise WriterReviewPayloadError("writer diagnosis scores must be an object")
    scores: dict[str, float] = {}
    for dimension in ALL_WRITER_REVIEW_DIMENSIONS:
        if dimension not in scores_payload:
            raise WriterReviewPayloadError(f"writer diagnosis score missing {dimension}")
        scores[dimension] = _required_score(scores_payload.get(dimension), f"scores.{dimension}")

    findings_payload = payload.get("findings")
    if not isinstance(findings_payload, list):
        raise WriterReviewPayloadError("writer diagnosis findings must be an array")
    findings = [_validate_finding(item, index) for index, item in enumerate(findings_payload)]

    revision_payload = payload.get("revision_brief")
    if not isinstance(revision_payload, list):
        raise WriterReviewPayloadError("writer diagnosis revision_brief must be an array")
    revision_brief = [_validate_revision_brief(item, index) for index, item in enumerate(revision_payload)]

    requires_human_review = payload.get("requires_human_review")
    if not isinstance(requires_human_review, bool):
        raise WriterReviewPayloadError("writer diagnosis requires_human_review must be a boolean")

    return {
        "overall_score": overall_score,
        "scores": scores,
        "findings": findings,
        "revision_brief": revision_brief,
        "requires_human_review": requires_human_review,
    }


def _validate_finding(item: Any, index: int) -> dict[str, Any]:
    if not isinstance(item, dict):
        raise WriterReviewPayloadError(f"writer diagnosis finding {index} must be an object")
    required = (
        "dimension",
        "severity",
        "issue",
        "recommendation",
        "evidence_excerpt",
        "evidence_location",
        "why_it_matters",
    )
    finding = {key: _required_string(item.get(key), f"findings[{index}].{key}") for key in required}
    if isinstance(item.get("lens"), str) and item["lens"].strip():
        finding["lens"] = item["lens"].strip()
    if isinstance(item.get("confidence"), (int, float)) and not isinstance(item.get("confidence"), bool):
        finding["confidence"] = float(item["confidence"])
    evidence_spans = item.get("evidence_spans")
    if isinstance(evidence_spans, list):
        finding["evidence_spans"] = [span for span in evidence_spans if isinstance(span, dict)]
    return finding


def _validate_revision_brief(item: Any, index: int) -> dict[str, Any]:
    if not isinstance(item, dict):
        raise WriterReviewPayloadError(f"writer diagnosis revision_brief {index} must be an object")
    return {
        "dimension": _required_string(item.get("dimension"), f"revision_brief[{index}].dimension"),
        "action": _required_string(item.get("action"), f"revision_brief[{index}].action"),
        "priority": _required_string(item.get("priority"), f"revision_brief[{index}].priority"),
    }


def _validate_scene_revision_payload(payload: Any, *, source: dict[str, Any], evaluation: WriterEvaluation) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise WriterReviewPayloadError("writer scene revision payload must be an object")
    revised_text = _required_string(payload.get("revised_text"), "revised_text")
    diff_summary = _required_string(payload.get("diff_summary"), "diff_summary")
    changed_dimensions = _string_list(payload.get("changed_dimensions"))
    rewrite_strategy = _required_string(payload.get("rewrite_strategy"), "rewrite_strategy")
    return {
        "proposed_text": revised_text,
        "diff_summary": {
            "summary": diff_summary,
            "changed_dimensions": changed_dimensions,
            "rewrite_strategy": rewrite_strategy,
            "source_text_ref": source.get("source_text_ref"),
            "candidate_kind": "full_scene_rewrite",
            "evaluation_id": evaluation.evaluation_id,
        },
        "patches": [
            {
                "patch_type": "full_scene_rewrite",
                "target_text_ref": source.get("source_text_ref"),
                "replacement_text": revised_text,
                "changed_dimensions": changed_dimensions,
                "manual_only": True,
            }
        ],
    }


def _validate_chapter_revision_payload(payload: Any, *, source: dict[str, Any], evaluation: WriterEvaluation) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise WriterReviewPayloadError("writer chapter revision payload must be an object")
    revision_plan = _required_string_list(payload.get("revision_plan"), "revision_plan")
    passages = _validate_selected_rewrite_passages(payload.get("selected_rewrite_passages"))
    diff_summary = _required_string(payload.get("diff_summary"), "diff_summary")
    changed_dimensions = _string_list(payload.get("changed_dimensions"))
    rewrite_strategy = _required_string(payload.get("rewrite_strategy") or "revision_plan", "rewrite_strategy")
    return {
        "proposed_text": _chapter_revision_text(revision_plan, passages),
        "diff_summary": {
            "summary": diff_summary,
            "changed_dimensions": changed_dimensions,
            "rewrite_strategy": rewrite_strategy,
            "source_text_ref": source.get("source_text_ref"),
            "candidate_kind": "revision_plan",
            "evaluation_id": evaluation.evaluation_id,
        },
        "patches": [
            {
                "patch_type": "passage_rewrite",
                "target_text_ref": source.get("source_text_ref"),
                "source_excerpt": item["source_excerpt"],
                "replacement_text": item["revised_text"],
                "reason": item["reason"],
                "manual_only": True,
            }
            for item in passages
        ],
    }


def _validate_selected_rewrite_passages(payload: Any) -> list[dict[str, str]]:
    if not isinstance(payload, list):
        raise WriterReviewPayloadError("selected_rewrite_passages must be an array")
    passages: list[dict[str, str]] = []
    for index, item in enumerate(payload):
        if not isinstance(item, dict):
            raise WriterReviewPayloadError(f"selected_rewrite_passages[{index}] must be an object")
        passages.append(
            {
                "source_excerpt": _required_string(item.get("source_excerpt"), f"selected_rewrite_passages[{index}].source_excerpt"),
                "revised_text": _required_string(item.get("revised_text"), f"selected_rewrite_passages[{index}].revised_text"),
                "reason": _required_string(item.get("reason"), f"selected_rewrite_passages[{index}].reason"),
            }
        )
    return passages


def _chapter_revision_text(revision_plan: list[str], passages: list[dict[str, str]]) -> str:
    plan_lines = "\n".join(f"{index}. {item}" for index, item in enumerate(revision_plan, start=1))
    passage_lines = "\n\n".join(
        (
            f"原文：{item['source_excerpt']}\n"
            f"改写：{item['revised_text']}\n"
            f"理由：{item['reason']}"
        )
        for item in passages
    )
    if not passage_lines:
        passage_lines = "暂无局部改写；先按修订计划人工调整。"
    return f"【章节修订计划】\n{plan_lines}\n\n【局部改写】\n{passage_lines}"


def _writer_review_user_prompt(
    base_prompt: str,
    *,
    object_type: str,
    object_id: str,
    source: dict[str, Any],
    writer_context: dict[str, Any],
) -> str:
    return "\n".join(
        [
            base_prompt,
            "",
            "## Writer Review Target",
            f"Object Type: {object_type}",
            f"Object ID: {object_id}",
            f"Source Text Ref: {source.get('source_text_ref') or ''}",
            "",
            "## Author Intent Context",
            json.dumps(writer_context, ensure_ascii=False, indent=2, sort_keys=True),
            "",
            "## Source Text To Diagnose",
            source.get("content") or "",
        ]
    )


def _writer_revision_user_prompt(
    base_prompt: str,
    *,
    object_type: str,
    source: dict[str, Any],
    diagnosis_payload: dict[str, Any],
) -> str:
    return "\n".join(
        [
            base_prompt,
            "",
            "## Revision Target",
            f"Object Type: {object_type}",
            f"Source Text Ref: {source.get('source_text_ref') or ''}",
            "",
            "## Writer Diagnosis",
            json.dumps(diagnosis_payload, ensure_ascii=False, indent=2, sort_keys=True),
            "",
            "## Source Text To Revise",
            source.get("content") or "",
        ]
    )


def _compact_source_for_prompt(text: str, limit: int = 1600) -> str:
    stripped = (text or "").strip()
    if len(stripped) <= limit:
        return stripped
    return f"{stripped[:limit].rstrip()}\n...[truncated for writer review prompt]..."


def _required_score(value: Any, field_name: str) -> float:
    score = _optional_score(value, field_name)
    if score is None:
        raise WriterReviewPayloadError(f"{field_name} must be a number")
    return score


def _optional_score(value: Any, field_name: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise WriterReviewPayloadError(f"{field_name} must be a number")
    score = float(value)
    if score < 0 or score > 1:
        raise WriterReviewPayloadError(f"{field_name} must be between 0 and 1")
    return score


def _required_string(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise WriterReviewPayloadError(f"{field_name} must be a non-empty string")
    return value.strip()


def _required_string_list(value: Any, field_name: str) -> list[str]:
    items = _string_list(value)
    if not items:
        raise WriterReviewPayloadError(f"{field_name} must contain at least one string")
    return items


def _string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise WriterReviewPayloadError("expected an array of strings")
    items: list[str] = []
    for item in value:
        if isinstance(item, str) and item.strip():
            items.append(item.strip())
    return items


def _dimension_score(values: list[Any], source_text: str) -> float:
    has_brief = any(str(value or "").strip() for value in values)
    if not (source_text or "").strip():
        return 0.2
    base = 0.82 if has_brief else 0.48
    if len(source_text.strip()) > 80:
        base += 0.04
    return round(min(base, 0.95), 2)


def _missing_field_findings(
    scores: dict[str, float],
    brief: dict[str, str],
    field_by_dimension: dict[str, tuple[str, str]],
) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for dimension, (field_key, label) in field_by_dimension.items():
        if scores.get(dimension, 0) >= 0.55:
            continue
        if brief.get(field_key):
            continue
        findings.append(
            {
                "dimension": dimension,
                "severity": "blocker",
                "issue": f"戏剧卡缺少“{label}”，这一维很难被稳定生成或评估。",
                "recommendation": f"补写“{label}”：用一句话说明人物要什么、怕失去什么或读者要追问什么。",
            }
        )
    return findings
