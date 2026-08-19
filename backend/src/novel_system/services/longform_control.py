from __future__ import annotations

from collections import defaultdict
from statistics import mean
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from novel_system.db.models import (
    ChapterGoal,
    ChapterMemory,
    ChapterState,
    FinalScene,
    ForeshadowTracker,
    LlmCall,
    QcReport,
    RelationProfile,
    RevisionCandidate,
    SceneCard,
    SceneRunState,
    VoiceProfile,
    WriterEvaluation,
)
from novel_system.services.canon_continuity import CanonContinuityService
from novel_system.services.errors import DomainError
from novel_system.services.writer_briefs import normalize_chapter_writer_brief, normalize_scene_writer_brief


class LongformControlService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def dashboard(self) -> dict[str, Any]:
        chapters = self.session.execute(
            select(ChapterGoal).where(ChapterGoal.trashed_flag == 0).order_by(ChapterGoal.chapter_id.asc())
        ).scalars().all()
        chapter_ids = [chapter.chapter_id for chapter in chapters]
        scenes = self._scenes_by_chapter(chapter_ids)
        scene_states = self._scene_states()
        chapter_states = self._chapter_states(chapter_ids)
        final_scenes = self._final_scenes(scene_states)
        aggregates = self._final_aggregates(chapter_ids, chapter_states)
        evaluations = self._evaluations_by_chapter(chapter_ids)
        candidates = self._candidates_by_chapter(chapter_ids)
        qc_reports = self._qc_reports_by_chapter(chapter_ids)
        llm_errors = self._llm_errors_by_chapter(chapter_ids)
        canon_statuses = self._canon_status_by_chapter(chapters)

        chapter_rows = [
            self._chapter_row(
                chapter,
                scenes=scenes.get(chapter.chapter_id, []),
                scene_states=scene_states,
                final_scenes=final_scenes,
                chapter_state=chapter_states.get(chapter.chapter_id),
                aggregate=aggregates.get(chapter.chapter_id),
                evaluations=evaluations.get(chapter.chapter_id, []),
                candidates=candidates.get(chapter.chapter_id, []),
                canon_status=canon_statuses.get(chapter.chapter_id),
            )
            for chapter in chapters
        ]
        rhythm_map = [
            self._rhythm_row(row, qc_reports.get(row["chapter_id"], []))
            for row in chapter_rows
        ]
        character_arcs = self._character_arcs(chapter_ids, scenes, evaluations)
        foreshadow_debts = self._foreshadow_debts(chapter_ids)
        promise_payoff = self._promise_payoff(chapters, foreshadow_debts)
        character_arc_timeline = self._character_arc_timeline(chapter_ids, scenes, evaluations)
        relation_tension_matrix = self._relation_tension_matrix(chapter_ids, scenes)
        motif_tracking = self._motif_tracking(chapter_ids, scenes)
        information_release_curve = self._information_release_curve(chapter_ids, scenes, evaluations)
        reader_hook_debts = self._reader_hook_debts(chapters, scenes, foreshadow_debts, evaluations)
        debt_radar = self._debt_radar(
            chapters=chapters,
            scenes=scenes,
            chapter_rows=chapter_rows,
            foreshadow_debts=foreshadow_debts,
            reader_hook_debts=reader_hook_debts,
        )
        revision_pressure = [
            self._revision_pressure_row(row, evaluations.get(row["chapter_id"], []), candidates.get(row["chapter_id"], []))
            for row in chapter_rows
        ]
        continuity_alerts = self._continuity_alerts(
            chapter_rows=chapter_rows,
            evaluations=evaluations,
            llm_errors=llm_errors,
        )
        return {
            "summary": self._summary(chapter_rows, revision_pressure, foreshadow_debts, continuity_alerts, debt_radar),
            "chapters": chapter_rows,
            "rhythm_map": rhythm_map,
            "character_arcs": character_arcs,
            "promise_payoff": promise_payoff,
            "character_arc_timeline": character_arc_timeline,
            "relation_tension_matrix": relation_tension_matrix,
            "motif_tracking": motif_tracking,
            "information_release_curve": information_release_curve,
            "reader_hook_debts": reader_hook_debts,
            "debt_radar": debt_radar,
            "foreshadow_debts": foreshadow_debts,
            "continuity_alerts": continuity_alerts,
            "revision_pressure": revision_pressure,
        }

    def _scenes_by_chapter(self, chapter_ids: list[str]) -> dict[str, list[SceneCard]]:
        if not chapter_ids:
            return {}
        rows = self.session.execute(
            select(SceneCard)
            .where(SceneCard.chapter_id.in_(chapter_ids), SceneCard.trashed_flag == 0)
            .order_by(SceneCard.chapter_id.asc(), SceneCard.scene_seq.asc(), SceneCard.scene_id.asc())
        ).scalars().all()
        grouped: dict[str, list[SceneCard]] = defaultdict(list)
        for row in rows:
            grouped[row.chapter_id].append(row)
        return grouped

    def _scene_states(self) -> dict[str, SceneRunState]:
        rows = self.session.execute(select(SceneRunState)).scalars().all()
        return {row.scene_id: row for row in rows}

    def _chapter_states(self, chapter_ids: list[str]) -> dict[str, ChapterState]:
        if not chapter_ids:
            return {}
        rows = self.session.execute(select(ChapterState).where(ChapterState.chapter_id.in_(chapter_ids))).scalars().all()
        return {row.chapter_id: row for row in rows}

    def _final_scenes(self, scene_states: dict[str, SceneRunState]) -> dict[str, FinalScene]:
        row_ids = [state.current_final_scene_row_id for state in scene_states.values() if state.current_final_scene_row_id]
        if not row_ids:
            return {}
        rows = self.session.execute(select(FinalScene).where(FinalScene.row_id.in_(row_ids))).scalars().all()
        return {row.row_id: row for row in rows}

    def _final_aggregates(self, chapter_ids: list[str], chapter_states: dict[str, ChapterState]) -> dict[str, ChapterMemory]:
        if not chapter_ids:
            return {}
        rows = self.session.execute(
            select(ChapterMemory)
            .where(ChapterMemory.chapter_id.in_(chapter_ids), ChapterMemory.aggregate_stage == "final", ChapterMemory.active_flag == 1)
            .order_by(ChapterMemory.created_at.desc(), ChapterMemory.row_id.desc())
        ).scalars().all()
        by_chapter: dict[str, ChapterMemory] = {}
        for row in rows:
            by_chapter.setdefault(row.chapter_id, row)
        for chapter_id, state in chapter_states.items():
            if not state.last_final_memory_row_id:
                continue
            pointed = self.session.get(ChapterMemory, state.last_final_memory_row_id)
            if pointed and pointed.chapter_id == chapter_id and pointed.aggregate_stage == "final":
                by_chapter[chapter_id] = pointed
        return by_chapter

    def _evaluations_by_chapter(self, chapter_ids: list[str]) -> dict[str, list[WriterEvaluation]]:
        if not chapter_ids:
            return {}
        rows = self.session.execute(
            select(WriterEvaluation)
            .where(WriterEvaluation.chapter_id.in_(chapter_ids))
            .order_by(WriterEvaluation.created_at.desc(), WriterEvaluation.evaluation_id.desc())
        ).scalars().all()
        grouped: dict[str, list[WriterEvaluation]] = defaultdict(list)
        for row in rows:
            if row.chapter_id:
                grouped[row.chapter_id].append(row)
        return grouped

    def _candidates_by_chapter(self, chapter_ids: list[str]) -> dict[str, list[RevisionCandidate]]:
        if not chapter_ids:
            return {}
        rows = self.session.execute(
            select(RevisionCandidate)
            .where(RevisionCandidate.chapter_id.in_(chapter_ids))
            .order_by(RevisionCandidate.created_at.desc(), RevisionCandidate.revision_id.desc())
        ).scalars().all()
        grouped: dict[str, list[RevisionCandidate]] = defaultdict(list)
        for row in rows:
            if row.chapter_id:
                grouped[row.chapter_id].append(row)
        return grouped

    def _qc_reports_by_chapter(self, chapter_ids: list[str]) -> dict[str, list[QcReport]]:
        if not chapter_ids:
            return {}
        rows = self.session.execute(select(QcReport).where(QcReport.chapter_id.in_(chapter_ids))).scalars().all()
        grouped: dict[str, list[QcReport]] = defaultdict(list)
        for row in rows:
            if row.chapter_id:
                grouped[row.chapter_id].append(row)
        return grouped

    def _llm_errors_by_chapter(self, chapter_ids: list[str]) -> dict[str, list[LlmCall]]:
        if not chapter_ids:
            return {}
        rows = self.session.execute(
            select(LlmCall).where(LlmCall.chapter_id.in_(chapter_ids), LlmCall.error_code.is_not(None))
        ).scalars().all()
        grouped: dict[str, list[LlmCall]] = defaultdict(list)
        for row in rows:
            if row.chapter_id:
                grouped[row.chapter_id].append(row)
        return grouped

    def _canon_status_by_chapter(
        self,
        chapters: list[ChapterGoal],
    ) -> dict[str, dict[str, Any]]:
        """Reuse the authoritative canon read model for dashboard status.

        A legacy ``SceneRunState.narrative_sync_status='synced'`` is only a
        hint.  It must not make the long-form dashboard green without a
        current-final, hash-matched active commit and complete snapshot.
        """

        service = CanonContinuityService(self.session)
        result: dict[str, dict[str, Any]] = {}
        for chapter in chapters:
            if not chapter.project_id:
                continue
            try:
                result[chapter.chapter_id] = service.chapter_status(
                    chapter.project_id,
                    chapter.chapter_id,
                )
            except DomainError:
                # Legacy/projectless rows remain visibly incomplete. The rest
                # of this read-only dashboard should still be inspectable.
                continue
        return result

    def _chapter_row(
        self,
        chapter: ChapterGoal,
        *,
        scenes: list[SceneCard],
        scene_states: dict[str, SceneRunState],
        final_scenes: dict[str, FinalScene],
        chapter_state: ChapterState | None,
        aggregate: ChapterMemory | None,
        evaluations: list[WriterEvaluation],
        candidates: list[RevisionCandidate],
        canon_status: dict[str, Any] | None,
    ) -> dict[str, Any]:
        generated_scene_ids: list[str] = []
        missing_scene_ids: list[str] = []
        assembled_parts: list[str] = []
        canon_synced_scene_count = 0
        canon_pending_scene_ids: list[str] = []
        for scene in scenes:
            state = scene_states.get(scene.scene_id)
            final_row = final_scenes.get(state.current_final_scene_row_id) if state and state.current_final_scene_row_id else None
            if final_row is None:
                missing_scene_ids.append(scene.scene_id)
                continue
            generated_scene_ids.append(scene.scene_id)
            assembled_parts.append(final_row.content or "")
            if canon_status is None:
                # No authoritative ownership/status can be established for a
                # legacy row. Fail closed instead of trusting the old flag.
                canon_pending_scene_ids.append(scene.scene_id)
        if canon_status is not None:
            canon_synced_scene_count = int(canon_status["synced_scene_count"])
            canon_pending_scene_ids = list(canon_status["pending_scene_ids"])
        assembled_content = "\n".join(assembled_parts)
        comparison_status = "aggregate_missing"
        if aggregate is not None:
            comparison_status = "aggregate_matches_current" if (aggregate.content or "") == assembled_content else "aggregate_differs_current"
        scores = [float(row.overall_score) for row in evaluations if row.overall_score is not None]
        return {
            "chapter_id": chapter.chapter_id,
            "chapter_goal": chapter.chapter_goal,
            "current_phase": chapter_state.current_phase if chapter_state else "planning",
            "planned_scene_count": chapter.planned_scene_count,
            "scene_count": len(scenes),
            "generated_scene_count": len(generated_scene_ids),
            "missing_scene_ids": missing_scene_ids,
            "completion_status": self._completion_status(len(scenes), len(generated_scene_ids)),
            "comparison_status": comparison_status,
            "assembled_char_count": len(assembled_content),
            "final_aggregate_row_id": aggregate.row_id if aggregate else None,
            "final_aggregate_char_count": len(aggregate.content or "") if aggregate else 0,
            "average_writer_score": round(mean(scores), 2) if scores else None,
            "open_revision_candidate_count": sum(1 for row in candidates if row.status == "candidate"),
            "requires_human_review_count": sum(1 for row in evaluations if row.requires_human_review),
            "canon_continuity": {
                "complete": bool(canon_status and canon_status["complete"]),
                "synced_scene_count": canon_synced_scene_count,
                "pending_scene_ids": canon_pending_scene_ids,
                "pending_candidate_count": int(
                    canon_status["pending_candidate_count"] if canon_status else 0
                ),
            },
        }

    @staticmethod
    def _rhythm_row(chapter_row: dict[str, Any], qc_reports: list[QcReport]) -> dict[str, Any]:
        scene_count = chapter_row["scene_count"] or 0
        return {
            "chapter_id": chapter_row["chapter_id"],
            "scene_count": scene_count,
            "generated_scene_count": chapter_row["generated_scene_count"],
            "assembled_char_count": chapter_row["assembled_char_count"],
            "final_aggregate_char_count": chapter_row["final_aggregate_char_count"],
            "average_scene_char_count": round(chapter_row["assembled_char_count"] / scene_count) if scene_count else 0,
            "average_writer_score": chapter_row["average_writer_score"],
            "completion_status": chapter_row["completion_status"],
            "comparison_status": chapter_row["comparison_status"],
            "qc_blocker_count": sum(1 for row in qc_reports if row.pass_flag == 0 or row.next_action == "human_review"),
        }

    def _character_arcs(
        self,
        chapter_ids: list[str],
        scenes: dict[str, list[SceneCard]],
        evaluations: dict[str, list[WriterEvaluation]],
    ) -> list[dict[str, Any]]:
        voice_profiles = self.session.execute(select(VoiceProfile).where(VoiceProfile.active_flag == 1)).scalars().all()
        relation_profiles = self.session.execute(select(RelationProfile).where(RelationProfile.active_flag == 1)).scalars().all()
        arc_map: dict[str, dict[str, Any]] = {}
        for chapter_id in chapter_ids:
            for scene in scenes.get(chapter_id, []):
                character_ids = [scene.pov_character_id, *(scene.onstage_chars_json or [])]
                for character_id in {item for item in character_ids if item}:
                    arc = arc_map.setdefault(
                        character_id,
                        {
                            "character_id": character_id,
                            "chapters": set(),
                            "pov_scene_count": 0,
                            "onstage_scene_count": 0,
                            "active_voice_profile_count": 0,
                            "relation_profile_count": 0,
                            "low_agency_finding_count": 0,
                            "power_shift_finding_count": 0,
                        },
                    )
                    arc["chapters"].add(chapter_id)
                    if scene.pov_character_id == character_id:
                        arc["pov_scene_count"] += 1
                    if character_id in (scene.onstage_chars_json or []) or scene.pov_character_id == character_id:
                        arc["onstage_scene_count"] += 1
        for profile in voice_profiles:
            arc_map.setdefault(
                profile.character_id,
                {
                    "character_id": profile.character_id,
                    "chapters": set(),
                    "pov_scene_count": 0,
                    "onstage_scene_count": 0,
                    "active_voice_profile_count": 0,
                    "relation_profile_count": 0,
                    "low_agency_finding_count": 0,
                    "power_shift_finding_count": 0,
                },
            )["active_voice_profile_count"] += 1
        for profile in relation_profiles:
            for character_id in (profile.left_character_id, profile.right_character_id):
                if character_id in arc_map:
                    arc_map[character_id]["relation_profile_count"] += 1
        for rows in evaluations.values():
            for evaluation in rows:
                scores = evaluation.scores_json or {}
                involved = self._characters_for_evaluation(evaluation, scenes)
                for character_id in involved:
                    arc = arc_map.get(character_id)
                    if not arc:
                        continue
                    if float(scores.get("character_agency") or 1) < 0.55:
                        arc["low_agency_finding_count"] += 1
                    if float(scores.get("power_shift") or 1) < 0.55:
                        arc["power_shift_finding_count"] += 1
        rows = []
        for arc in arc_map.values():
            rows.append({**arc, "chapters": sorted(arc["chapters"])})
        return sorted(rows, key=lambda row: (-row["pov_scene_count"], row["character_id"]))

    @staticmethod
    def _characters_for_evaluation(evaluation: WriterEvaluation, scenes: dict[str, list[SceneCard]]) -> set[str]:
        involved: set[str] = set()
        for scene_list in scenes.values():
            for scene in scene_list:
                if evaluation.scene_id and scene.scene_id != evaluation.scene_id:
                    continue
                if scene.pov_character_id:
                    involved.add(scene.pov_character_id)
                involved.update(scene.onstage_chars_json or [])
        return involved

    def _foreshadow_debts(self, chapter_ids: list[str]) -> list[dict[str, Any]]:
        if not chapter_ids:
            return []
        rows = self.session.execute(
            select(ForeshadowTracker)
            .where(ForeshadowTracker.chapter_id.in_(chapter_ids))
            .order_by(ForeshadowTracker.chapter_id.asc(), ForeshadowTracker.created_at.asc(), ForeshadowTracker.row_id.asc())
        ).scalars().all()
        resolved_statuses = {"resolved", "closed", "paid", "done"}
        return [
            {
                "row_id": row.row_id,
                "foreshadow_id": row.foreshadow_id,
                "chapter_id": row.chapter_id,
                "scene_id": row.scene_id,
                "text": row.text,
                "tracker_status": row.tracker_status,
                "debt_state": "resolved" if (row.tracker_status or "").lower() in resolved_statuses else "open",
                "active": bool(row.active_flag),
                "runtime_eligible": bool(row.runtime_eligible),
                "created_at": row.created_at,
                "updated_at": row.updated_at,
                "target_ref": f"scene_card:{row.scene_id}" if row.scene_id else f"chapter:{row.chapter_id}",
            }
            for row in rows
        ]

    def _promise_payoff(self, chapters: list[ChapterGoal], foreshadow_debts: list[dict[str, Any]]) -> list[dict[str, Any]]:
        debts_by_chapter: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for debt in foreshadow_debts:
            debts_by_chapter[debt["chapter_id"]].append(debt)
        rows: list[dict[str, Any]] = []
        for chapter in chapters:
            brief = normalize_chapter_writer_brief(chapter.writer_brief_json)
            chapter_promise = brief.get("chapter_promise") or brief.get("core_promise") or chapter.chapter_goal or ""
            ending_question = brief.get("ending_question") or brief.get("chapter_question") or chapter.ending_effect or ""
            open_debts = [item for item in debts_by_chapter.get(chapter.chapter_id, []) if item["debt_state"] == "open"]
            rows.append(
                {
                    "chapter_id": chapter.chapter_id,
                    "chapter_promise": chapter_promise,
                    "ending_question": ending_question,
                    "payoff_target": brief.get("payoff_target") or "",
                    "open_hook_count": len(open_debts),
                    "status": "debt_open" if open_debts or ending_question else "no_visible_debt",
                    "target_ref": f"chapter:{chapter.chapter_id}",
                }
            )
        return rows

    def _character_arc_timeline(
        self,
        chapter_ids: list[str],
        scenes: dict[str, list[SceneCard]],
        evaluations: dict[str, list[WriterEvaluation]],
    ) -> list[dict[str, Any]]:
        low_agency_by_scene: dict[str, bool] = {}
        for rows in evaluations.values():
            for evaluation in rows:
                if not evaluation.scene_id:
                    continue
                scores = evaluation.scores_json or {}
                low_agency_by_scene[evaluation.scene_id] = float(scores.get("character_agency") or 1) < 0.55
        timeline: list[dict[str, Any]] = []
        for chapter_id in chapter_ids:
            for scene in scenes.get(chapter_id, []):
                brief = normalize_scene_writer_brief(scene.writer_brief_json)
                character_ids = [scene.pov_character_id, *(scene.onstage_chars_json or [])]
                for character_id in sorted({item for item in character_ids if item}):
                    timeline.append(
                        {
                            "chapter_id": chapter_id,
                            "scene_id": scene.scene_id,
                            "scene_seq": scene.scene_seq,
                            "character_id": character_id,
                            "desire": brief.get("character_desire") or "",
                            "choice_under_pressure": brief.get("choice_under_pressure") or "",
                            "power_shift": brief.get("power_shift") or "",
                            "low_agency": bool(low_agency_by_scene.get(scene.scene_id)),
                            "target_ref": f"scene_card:{scene.scene_id}",
                        }
                    )
        return timeline

    def _relation_tension_matrix(
        self,
        chapter_ids: list[str],
        scenes: dict[str, list[SceneCard]],
    ) -> list[dict[str, Any]]:
        profiles = self.session.execute(select(RelationProfile).where(RelationProfile.active_flag == 1)).scalars().all()
        all_scenes = [scene for chapter_id in chapter_ids for scene in scenes.get(chapter_id, [])]
        rows: list[dict[str, Any]] = []
        for profile in profiles:
            pair = [profile.left_character_id, profile.right_character_id]
            scene_ids: list[str] = []
            pressure_notes: list[str] = []
            for scene in all_scenes:
                onstage = set(scene.onstage_chars_json or [])
                if scene.pov_character_id:
                    onstage.add(scene.pov_character_id)
                if not set(pair).issubset(onstage):
                    continue
                scene_ids.append(scene.scene_id)
                brief = normalize_scene_writer_brief(scene.writer_brief_json)
                for key in ("secret_or_misunderstanding", "power_shift", "reader_aftertaste"):
                    if brief.get(key):
                        pressure_notes.append(brief[key])
            rows.append(
                {
                    "pair": pair,
                    "relation_profile_id": profile.relation_profile_id,
                    "scene_ids": scene_ids,
                    "tension_note": profile.content,
                    "unexploded_points": pressure_notes[:5],
                    "target_ref": f"relation_profile:{profile.relation_profile_id}",
                }
            )
        return rows

    @staticmethod
    def _motif_tracking(chapter_ids: list[str], scenes: dict[str, list[SceneCard]]) -> list[dict[str, Any]]:
        anchors: list[tuple[str, SceneCard, str, str]] = []
        for chapter_id in chapter_ids:
            for scene in scenes.get(chapter_id, []):
                brief = normalize_scene_writer_brief(scene.writer_brief_json)
                image_anchor = brief.get("image_anchor") or ""
                if image_anchor:
                    transformation_note = " / ".join(
                        item
                        for item in (
                            brief.get("power_shift") or "",
                            brief.get("emotional_turn") or "",
                            brief.get("reader_aftertaste") or "",
                        )
                        if item
                    )
                    anchors.append((chapter_id, scene, image_anchor, transformation_note))
        counts: dict[str, int] = defaultdict(int)
        notes_by_anchor: dict[str, set[str]] = defaultdict(set)
        latest_note_by_anchor: dict[str, str] = {}
        chapters_by_anchor: dict[str, set[str]] = defaultdict(set)
        for chapter_id, _scene, image_anchor, transformation_note in anchors:
            counts[image_anchor] += 1
            chapters_by_anchor[image_anchor].add(chapter_id)
            if transformation_note:
                notes_by_anchor[image_anchor].add(transformation_note)
                latest_note_by_anchor[image_anchor] = transformation_note
        rows: list[dict[str, Any]] = []
        for chapter_id, scene, image_anchor, transformation_note in anchors:
            repeat_count = counts[image_anchor]
            transformed = repeat_count > 1 and len(notes_by_anchor[image_anchor]) > 1
            transformation_status = "transformed" if transformed else "static_repeat" if repeat_count > 1 else "fresh"
            rows.append(
                {
                    "chapter_id": chapter_id,
                    "scene_id": scene.scene_id,
                    "image_anchor": image_anchor,
                    "motif": image_anchor,
                    "chapters": sorted(chapters_by_anchor[image_anchor]),
                    "repeat_count": repeat_count,
                    "repeat_risk": repeat_count > 1 and not transformed,
                    "risk": "repeating" if repeat_count > 1 and not transformed else "fresh",
                    "transformation_status": transformation_status,
                    "transformation_note": latest_note_by_anchor.get(image_anchor) or transformation_note,
                    "target_ref": f"scene_card:{scene.scene_id}",
                }
            )
        return [
            row
            for row in sorted(rows, key=lambda item: (item["chapter_id"], item["scene_id"], item["image_anchor"]))
        ]

    def _information_release_curve(
        self,
        chapter_ids: list[str],
        scenes: dict[str, list[SceneCard]],
        evaluations: dict[str, list[WriterEvaluation]],
    ) -> list[dict[str, Any]]:
        low_info_by_scene: dict[str, bool] = {}
        for rows in evaluations.values():
            for evaluation in rows:
                if not evaluation.scene_id:
                    continue
                low_info_by_scene[evaluation.scene_id] = float((evaluation.scores_json or {}).get("information_rhythm") or 1) < 0.55
        curve: list[dict[str, Any]] = []
        for chapter_id in chapter_ids:
            for scene in scenes.get(chapter_id, []):
                brief = normalize_scene_writer_brief(scene.writer_brief_json)
                new_information = brief.get("new_information") or ""
                curve.append(
                    {
                        "chapter_id": chapter_id,
                        "scene_id": scene.scene_id,
                        "scene_seq": scene.scene_seq,
                        "release_type": "reveal" if new_information else "action",
                        "new_information": new_information,
                        "low_information_rhythm": bool(low_info_by_scene.get(scene.scene_id)),
                        "target_ref": f"scene_card:{scene.scene_id}",
                    }
                )
        return curve

    def _reader_hook_debts(
        self,
        chapters: list[ChapterGoal],
        scenes: dict[str, list[SceneCard]],
        foreshadow_debts: list[dict[str, Any]],
        evaluations: dict[str, list[WriterEvaluation]],
    ) -> list[dict[str, Any]]:
        debts = [
            {
                "chapter_id": debt["chapter_id"],
                "scene_id": debt["scene_id"],
                "hook_text": debt["text"],
                "debt_state": debt["debt_state"],
                "source": "foreshadow",
                "target_ref": f"scene_card:{debt['scene_id']}" if debt["scene_id"] else f"chapter:{debt['chapter_id']}",
            }
            for debt in foreshadow_debts
        ]
        low_hook_scenes = {
            evaluation.scene_id
            for rows in evaluations.values()
            for evaluation in rows
            if evaluation.scene_id and float((evaluation.scores_json or {}).get("reader_hook") or 1) < 0.55
        }
        for chapter in chapters:
            chapter_scenes = scenes.get(chapter.chapter_id, [])
            brief = normalize_chapter_writer_brief(chapter.writer_brief_json)
            ending_question = brief.get("ending_question") or brief.get("chapter_question") or ""
            if ending_question:
                debts.append(
                    {
                        "chapter_id": chapter.chapter_id,
                        "scene_id": chapter_scenes[-1].scene_id if chapter_scenes else None,
                        "hook_text": ending_question,
                        "debt_state": "open",
                        "source": "chapter_brief",
                        "target_ref": f"chapter:{chapter.chapter_id}",
                    }
                )
            for scene in chapter_scenes:
                if scene.scene_id not in low_hook_scenes:
                    continue
                debts.append(
                    {
                        "chapter_id": chapter.chapter_id,
                        "scene_id": scene.scene_id,
                        "hook_text": scene.hook or scene.scene_goal or "",
                        "debt_state": "weak",
                        "source": "writer_review",
                        "target_ref": f"scene_card:{scene.scene_id}",
                    }
                )
        return debts

    @staticmethod
    def _debt_radar(
        *,
        chapters: list[ChapterGoal],
        scenes: dict[str, list[SceneCard]],
        chapter_rows: list[dict[str, Any]],
        foreshadow_debts: list[dict[str, Any]],
        reader_hook_debts: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        chapter_status = {row["chapter_id"]: row for row in chapter_rows}
        rows: list[dict[str, Any]] = []
        for chapter in chapters:
            brief = normalize_chapter_writer_brief(chapter.writer_brief_json)
            promise = brief.get("chapter_promise") or brief.get("core_promise") or chapter.chapter_goal or ""
            payoff_target = brief.get("payoff_target") or chapter.ending_effect or ""
            ending_question = brief.get("ending_question") or brief.get("chapter_question") or ""
            if not any((promise, payoff_target, ending_question)):
                continue
            status = chapter_status.get(chapter.chapter_id, {})
            completion = status.get("completion_status")
            comparison = status.get("comparison_status")
            if completion == "complete" and comparison == "aggregate_matches_current" and payoff_target:
                payoff_status = "needs_review"
                risk_level = "minor"
                deferral_reason = "章节已有完整聚合稿，但仍需要作者确认承诺是否真正兑现。"
            else:
                payoff_status = "open"
                risk_level = "major" if completion != "complete" else "critical"
                deferral_reason = ending_question or "章节承诺尚未在当前成稿中明确偿还。"
            rows.append(
                {
                    "promise_ref": f"chapter_promise:{chapter.chapter_id}",
                    "debt_type": "chapter_promise",
                    "chapter_id": chapter.chapter_id,
                    "scene_id": None,
                    "text": promise,
                    "opened_at": f"chapter:{chapter.chapter_id}",
                    "expected_payoff_window": f"chapter:{chapter.chapter_id}:ending",
                    "payoff_status": payoff_status,
                    "deferral_reason": deferral_reason,
                    "risk_level": risk_level,
                    "target_ref": f"chapter:{chapter.chapter_id}",
                }
            )
        for debt in foreshadow_debts:
            status = chapter_status.get(debt["chapter_id"], {})
            open_debt = debt["debt_state"] == "open"
            complete = status.get("completion_status") == "complete"
            rows.append(
                {
                    "promise_ref": f"foreshadow:{debt['foreshadow_id']}",
                    "debt_type": "foreshadow",
                    "chapter_id": debt["chapter_id"],
                    "scene_id": debt["scene_id"],
                    "text": debt["text"],
                    "opened_at": f"scene:{debt['scene_id']}" if debt["scene_id"] else f"chapter:{debt['chapter_id']}",
                    "expected_payoff_window": f"chapter:{debt['chapter_id']}",
                    "payoff_status": debt["debt_state"],
                    "deferral_reason": "" if not open_debt else "伏笔仍未偿还或未标注延宕理由。",
                    "risk_level": "critical" if open_debt and complete else "major" if open_debt else "info",
                    "target_ref": debt["target_ref"],
                }
            )
        seen_refs = {row["promise_ref"] for row in rows}
        for hook in reader_hook_debts:
            if hook.get("source") == "foreshadow":
                continue
            promise_ref = f"reader_hook:{hook['chapter_id']}:{hook.get('scene_id') or 'chapter'}:{hook.get('source')}"
            if promise_ref in seen_refs:
                continue
            rows.append(
                {
                    "promise_ref": promise_ref,
                    "debt_type": "reader_hook",
                    "chapter_id": hook["chapter_id"],
                    "scene_id": hook.get("scene_id"),
                    "text": hook.get("hook_text") or "",
                    "opened_at": f"scene:{hook['scene_id']}" if hook.get("scene_id") else f"chapter:{hook['chapter_id']}",
                    "expected_payoff_window": f"chapter:{hook['chapter_id']}",
                    "payoff_status": hook.get("debt_state") or "open",
                    "deferral_reason": "读者问题需要后续场景偿还，或在章节目标中明确延宕。",
                    "risk_level": "major" if hook.get("debt_state") in {"open", "weak"} else "info",
                    "target_ref": hook["target_ref"],
                }
            )
        rank = {"critical": 0, "major": 1, "minor": 2, "info": 3}
        return sorted(rows, key=lambda row: (rank.get(row["risk_level"], 9), row["chapter_id"], row["promise_ref"]))

    @staticmethod
    def _revision_pressure_row(
        chapter_row: dict[str, Any],
        evaluations: list[WriterEvaluation],
        candidates: list[RevisionCandidate],
    ) -> dict[str, Any]:
        low_dimensions: dict[str, float] = {}
        for evaluation in evaluations:
            for dimension, score in (evaluation.scores_json or {}).items():
                try:
                    numeric = float(score)
                except (TypeError, ValueError):
                    continue
                if numeric < 0.55:
                    low_dimensions[dimension] = min(numeric, low_dimensions.get(dimension, 1.0))
        return {
            "chapter_id": chapter_row["chapter_id"],
            "latest_score": chapter_row["average_writer_score"],
            "open_candidate_count": sum(1 for row in candidates if row.status == "candidate"),
            "accepted_candidate_count": sum(1 for row in candidates if row.status == "accepted"),
            "rejected_candidate_count": sum(1 for row in candidates if row.status == "rejected"),
            "requires_human_review_count": chapter_row["requires_human_review_count"],
            "top_low_dimensions": [
                {"dimension": dimension, "score": score}
                for dimension, score in sorted(low_dimensions.items(), key=lambda item: (item[1], item[0]))[:5]
            ],
        }

    @staticmethod
    def _continuity_alerts(
        *,
        chapter_rows: list[dict[str, Any]],
        evaluations: dict[str, list[WriterEvaluation]],
        llm_errors: dict[str, list[LlmCall]],
    ) -> list[dict[str, Any]]:
        alerts: list[dict[str, Any]] = []
        for row in chapter_rows:
            chapter_id = row["chapter_id"]
            if row["comparison_status"] == "aggregate_missing":
                alerts.append(
                    {
                        "alert_type": "aggregate_missing",
                        "severity": "major",
                        "chapter_id": chapter_id,
                        "scene_id": None,
                        "message": "chapter has no final aggregate",
                    }
                )
            elif row["comparison_status"] == "aggregate_differs_current":
                alerts.append(
                    {
                        "alert_type": "aggregate_stale",
                        "severity": "major",
                        "chapter_id": chapter_id,
                        "scene_id": None,
                        "message": "final aggregate differs from assembled scenes",
                    }
                )
            for scene_id in row["missing_scene_ids"]:
                alerts.append(
                    {
                        "alert_type": "missing_final_scene",
                        "severity": "blocker",
                        "chapter_id": chapter_id,
                        "scene_id": scene_id,
                        "message": "scene is missing final text",
                    }
                )
            for scene_id in row.get("canon_continuity", {}).get("pending_scene_ids", []):
                alerts.append(
                    {
                        "alert_type": "canon_review_pending",
                        "severity": "blocker",
                        "chapter_id": chapter_id,
                        "scene_id": scene_id,
                        "message": "scene continuity facts are not committed to canon",
                    }
                )
            for evaluation in evaluations.get(chapter_id, []):
                if not evaluation.requires_human_review:
                    continue
                alerts.append(
                    {
                        "alert_type": "writer_human_review",
                        "severity": "major",
                        "chapter_id": chapter_id,
                        "scene_id": evaluation.scene_id,
                        "message": f"writer evaluation requires human review: {evaluation.evaluation_id}",
                    }
                )
            for llm_call in llm_errors.get(chapter_id, []):
                alerts.append(
                    {
                        "alert_type": "llm_error",
                        "severity": "major",
                        "chapter_id": chapter_id,
                        "scene_id": llm_call.scene_id,
                        "message": f"{llm_call.node_id or 'llm'} failed with {llm_call.error_code}",
                    }
                )
        return alerts

    @staticmethod
    def _summary(
        chapter_rows: list[dict[str, Any]],
        revision_pressure: list[dict[str, Any]],
        foreshadow_debts: list[dict[str, Any]],
        continuity_alerts: list[dict[str, Any]],
        debt_radar: list[dict[str, Any]],
    ) -> dict[str, Any]:
        open_statuses = {"open", "weak", "overdue", "needs_review"}
        return {
            "chapter_count": len(chapter_rows),
            "scene_count": sum(row["scene_count"] for row in chapter_rows),
            "complete_chapter_count": sum(1 for row in chapter_rows if row["completion_status"] == "complete"),
            "aggregate_missing_count": sum(1 for row in chapter_rows if row["comparison_status"] == "aggregate_missing"),
            "open_revision_candidate_count": sum(row["open_candidate_count"] for row in revision_pressure),
            "human_review_count": sum(row["requires_human_review_count"] for row in revision_pressure),
            "open_foreshadow_count": sum(1 for row in foreshadow_debts if row["debt_state"] == "open"),
            "continuity_alert_count": len(continuity_alerts),
            "open_debt_count": sum(1 for row in debt_radar if row["payoff_status"] in open_statuses),
            "critical_debt_count": sum(1 for row in debt_radar if row["risk_level"] == "critical"),
        }

    @staticmethod
    def _completion_status(scene_count: int, generated_scene_count: int) -> str:
        if generated_scene_count == 0:
            return "empty"
        if scene_count > 0 and generated_scene_count >= scene_count:
            return "complete"
        return "partial"
