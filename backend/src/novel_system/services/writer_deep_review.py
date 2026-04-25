from __future__ import annotations

import uuid
from statistics import mean
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from novel_system.db.models import (
    AuthorPreferenceProfile,
    ChapterGoal,
    ChapterMemory,
    FinalScene,
    PassagePatchCandidate,
    SceneCard,
    SceneRunState,
    WriterEvaluation,
)
from novel_system.services.errors import DomainError


LITERARY_REVISION_RUBRIC_ID = "literary_revision_v1"
LITERARY_REVISION_DIMENSIONS: tuple[str, ...] = (
    "character_contradiction",
    "choice_pressure",
    "relationship_tension",
    "dialogue_subtext",
    "information_rhythm",
    "voice_distinction",
    "image_necessity",
    "repetitive_expression",
    "ending_drive",
    "theme_pressure",
)
DEEP_REVIEW_LENSES: tuple[str, ...] = ("story", "character", "prose", "reader", "theme")


class WriterDeepReviewService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def scene_summary(self, scene_id: str) -> dict[str, Any]:
        self._require_scene(scene_id)
        return self._review_payload("scene", scene_id)

    def chapter_summary(self, chapter_id: str) -> dict[str, Any]:
        self._require_chapter(chapter_id)
        return self._review_payload("chapter", chapter_id)

    def run_scene_review(self, scene_id: str, actor_ref: str = "operator") -> dict[str, Any]:
        scene = self._require_scene(scene_id)
        source = self._scene_source(scene)
        return self._create_deep_review(
            object_type="scene",
            object_id=scene.scene_id,
            chapter_id=scene.chapter_id,
            scene_id=scene.scene_id,
            source=source,
            actor_ref=actor_ref,
        )

    def run_chapter_review(self, chapter_id: str, actor_ref: str = "operator") -> dict[str, Any]:
        chapter = self._require_chapter(chapter_id)
        source = self._chapter_source(chapter)
        return self._create_deep_review(
            object_type="chapter",
            object_id=chapter.chapter_id,
            chapter_id=chapter.chapter_id,
            scene_id=None,
            source=source,
            actor_ref=actor_ref,
        )

    def create_patch_candidate(self, payload: dict[str, Any], actor_ref: str = "operator") -> dict[str, Any]:
        source_excerpt = _required_text(payload, "source_excerpt")
        issue_dimension = _required_text(payload, "issue_dimension")
        object_type = _required_text(payload, "object_type")
        object_id = _required_text(payload, "object_id")
        if object_type not in {"scene", "chapter"}:
            raise DomainError("PASSAGE_PATCH_INVALID", "object_type must be scene or chapter", status_code=400)
        replacement_options = _replacement_options(source_excerpt, issue_dimension)
        row = PassagePatchCandidate(
            patch_id=f"passage_patch_{object_type}_{object_id}_{uuid.uuid4().hex[:10]}",
            object_type=object_type,
            object_id=object_id,
            chapter_id=_optional_text(payload, "chapter_id"),
            scene_id=_optional_text(payload, "scene_id"),
            source_text_ref=_optional_text(payload, "source_text_ref") or _optional_text(payload, "target_text_ref"),
            target_text_ref=_optional_text(payload, "target_text_ref"),
            source_excerpt=source_excerpt,
            issue_dimension=issue_dimension,
            replacement_options_json=replacement_options,
            manual_only=1,
            status="candidate",
            author_decision="pending",
            created_by=actor_ref or "writer_deep_review",
        )
        self.session.add(row)
        self.session.flush()
        return {"candidate": self.serialize_patch_candidate(row)}

    def accept_patch_candidate(self, patch_id: str, payload: dict[str, Any], actor_ref: str = "operator") -> dict[str, Any]:
        row = self._require_patch_candidate(patch_id)
        selected_option_id = _optional_text(payload, "selected_option_id")
        option_ids = {str(option.get("option_id")) for option in row.replacement_options_json or []}
        if selected_option_id and selected_option_id not in option_ids:
            raise DomainError("PASSAGE_PATCH_OPTION_NOT_FOUND", "selected replacement option not found", status_code=404)
        row.status = "accepted"
        row.author_decision = "accepted"
        row.selected_option_id = selected_option_id
        row.author_decision_note = _optional_text(payload, "note") or row.author_decision_note
        self.session.flush()
        self._refresh_author_preference_profile(actor_ref=actor_ref)
        self.session.flush()
        return {"candidate": self.serialize_patch_candidate(row)}

    def reject_patch_candidate(self, patch_id: str, payload: dict[str, Any], actor_ref: str = "operator") -> dict[str, Any]:
        row = self._require_patch_candidate(patch_id)
        row.status = "rejected"
        row.author_decision = "rejected"
        row.author_decision_note = _optional_text(payload, "note") or row.author_decision_note
        self.session.flush()
        self._refresh_author_preference_profile(actor_ref=actor_ref)
        self.session.flush()
        return {"candidate": self.serialize_patch_candidate(row)}

    def author_preference_profile(self) -> dict[str, Any]:
        profile = self._latest_preference_profile()
        if profile is None:
            return {
                "profile": {
                    "profile_id": "author_pref_global_global",
                    "scope_type": "global",
                    "scope_ref_id": "global",
                    "status": "draft",
                    "runtime_eligible": False,
                    "summary": _empty_preference_summary(),
                    "source_patch_ids": [],
                    "created_at": None,
                    "updated_at": None,
                }
            }
        return {"profile": self.serialize_preference_profile(profile)}

    @staticmethod
    def serialize_evaluation(row: WriterEvaluation | None) -> dict[str, Any] | None:
        if row is None:
            return None
        return {
            "evaluation_id": row.evaluation_id,
            "object_type": row.object_type,
            "object_id": row.object_id,
            "chapter_id": row.chapter_id,
            "scene_id": row.scene_id,
            "rubric_id": row.rubric_id,
            "source_text_ref": row.source_text_ref,
            "source_bundle_id": row.source_bundle_id,
            "lens": row.lens or "aggregate",
            "parent_evaluation_id": row.parent_evaluation_id,
            "evidence_spans": row.evidence_spans_json or [],
            "overall_score": row.overall_score,
            "scores": row.scores_json or {},
            "findings": row.findings_json or [],
            "revision_brief": row.revision_brief_json or [],
            "requires_human_review": bool(row.requires_human_review),
            "status": row.status,
            "created_at": row.created_at,
        }

    @staticmethod
    def serialize_patch_candidate(row: PassagePatchCandidate) -> dict[str, Any]:
        return {
            "patch_id": row.patch_id,
            "object_type": row.object_type,
            "object_id": row.object_id,
            "chapter_id": row.chapter_id,
            "scene_id": row.scene_id,
            "source_text_ref": row.source_text_ref,
            "target_text_ref": row.target_text_ref,
            "source_excerpt": row.source_excerpt,
            "issue_dimension": row.issue_dimension,
            "replacement_options": row.replacement_options_json or [],
            "manual_only": bool(row.manual_only),
            "status": row.status,
            "author_decision": row.author_decision,
            "selected_option_id": row.selected_option_id,
            "author_decision_note": row.author_decision_note,
            "created_by": row.created_by,
            "created_at": row.created_at,
            "updated_at": row.updated_at,
        }

    @staticmethod
    def serialize_preference_profile(row: AuthorPreferenceProfile) -> dict[str, Any]:
        return {
            "profile_id": row.profile_id,
            "scope_type": row.scope_type,
            "scope_ref_id": row.scope_ref_id,
            "status": row.status,
            "runtime_eligible": bool(row.runtime_eligible),
            "summary": row.summary_json or _empty_preference_summary(),
            "source_patch_ids": row.source_patch_ids_json or [],
            "created_by": row.created_by,
            "created_at": row.created_at,
            "updated_at": row.updated_at,
        }

    def _create_deep_review(
        self,
        *,
        object_type: str,
        object_id: str,
        chapter_id: str | None,
        scene_id: str | None,
        source: dict[str, Any],
        actor_ref: str,
    ) -> dict[str, Any]:
        for row in self.session.execute(
            select(WriterEvaluation).where(
                WriterEvaluation.object_type == object_type,
                WriterEvaluation.object_id == object_id,
                WriterEvaluation.rubric_id == LITERARY_REVISION_RUBRIC_ID,
                WriterEvaluation.parent_evaluation_id.is_(None),
            )
        ).scalars().all():
            row.status = "superseded"

        lens_rows: list[WriterEvaluation] = []
        lens_payloads = _diagnose_by_lens(source["content"])
        aggregate_findings: list[dict[str, Any]] = []
        aggregate_scores = {dimension: 0.78 for dimension in LITERARY_REVISION_DIMENSIONS}
        for lens, payload in lens_payloads.items():
            aggregate_findings.extend({**finding, "lens": lens} for finding in payload["findings"])
            for dimension, score in payload["scores"].items():
                aggregate_scores[dimension] = min(aggregate_scores.get(dimension, score), score)

        if not source["content"].strip():
            aggregate_findings.append(
                _finding(
                    lens="story",
                    dimension="source_text",
                    classification="blocking",
                    issue="没有可诊断的正文。",
                    recommendation="先生成或导入正文，再运行深改诊断。",
                    evidence="",
                    why="深改必须基于作者实际文本，不能凭空判断。",
                )
            )
        aggregate_scores = _cap_scores_for_findings(aggregate_scores, aggregate_findings)
        revision_brief = _revision_brief_from_findings(aggregate_findings)
        aggregate_score = round(mean(aggregate_scores.values()), 2) if aggregate_scores else None
        parent = WriterEvaluation(
            evaluation_id=f"writer_deep_eval_{object_type}_{object_id}_{uuid.uuid4().hex[:10]}",
            object_type=object_type,
            object_id=object_id,
            chapter_id=chapter_id,
            scene_id=scene_id,
            rubric_id=LITERARY_REVISION_RUBRIC_ID,
            source_text_ref=source.get("source_text_ref"),
            source_bundle_id=source.get("source_bundle_id"),
            evaluator_llm_call_id=None,
            lens="aggregate",
            parent_evaluation_id=None,
            evidence_spans_json=_evidence_spans(source["content"], aggregate_findings),
            overall_score=aggregate_score,
            scores_json=aggregate_scores,
            findings_json=aggregate_findings,
            revision_brief_json=revision_brief,
            requires_human_review=1 if any(item["severity"] == "blocking" for item in aggregate_findings) else 0,
            status="completed",
        )
        self.session.add(parent)
        self.session.flush()

        for lens, payload in lens_payloads.items():
            scores = _cap_scores_for_findings(payload["scores"], payload["findings"])
            row = WriterEvaluation(
                evaluation_id=f"writer_deep_eval_{object_type}_{object_id}_{lens}_{uuid.uuid4().hex[:8]}",
                object_type=object_type,
                object_id=object_id,
                chapter_id=chapter_id,
                scene_id=scene_id,
                rubric_id=LITERARY_REVISION_RUBRIC_ID,
                source_text_ref=source.get("source_text_ref"),
                source_bundle_id=source.get("source_bundle_id"),
                evaluator_llm_call_id=None,
                lens=lens,
                parent_evaluation_id=parent.evaluation_id,
                evidence_spans_json=_evidence_spans(source["content"], payload["findings"]),
                overall_score=round(mean(scores.values()), 2) if scores else None,
                scores_json=scores,
                findings_json=payload["findings"],
                revision_brief_json=_revision_brief_from_findings(payload["findings"]),
                requires_human_review=1 if any(item["severity"] == "blocking" for item in payload["findings"]) else 0,
                status="completed",
            )
            self.session.add(row)
            lens_rows.append(row)
        self.session.flush()
        return self._review_payload(object_type, object_id)

    def _review_payload(self, object_type: str, object_id: str) -> dict[str, Any]:
        latest = self.session.execute(
            select(WriterEvaluation)
            .where(
                WriterEvaluation.object_type == object_type,
                WriterEvaluation.object_id == object_id,
                WriterEvaluation.rubric_id == LITERARY_REVISION_RUBRIC_ID,
                WriterEvaluation.parent_evaluation_id.is_(None),
            )
            .order_by(WriterEvaluation.created_at.desc(), WriterEvaluation.evaluation_id.desc())
        ).scalars().first()
        lenses: list[dict[str, Any]] = []
        if latest is not None:
            lens_rows = self.session.execute(
                select(WriterEvaluation)
                .where(WriterEvaluation.parent_evaluation_id == latest.evaluation_id)
                .order_by(WriterEvaluation.lens.asc(), WriterEvaluation.evaluation_id.asc())
            ).scalars().all()
            lenses = [item for item in (self.serialize_evaluation(row) for row in lens_rows) if item]
        patch_rows = self.session.execute(
            select(PassagePatchCandidate)
            .where(PassagePatchCandidate.object_type == object_type, PassagePatchCandidate.object_id == object_id)
            .order_by(PassagePatchCandidate.created_at.desc(), PassagePatchCandidate.patch_id.desc())
        ).scalars().all()
        latest_payload = self.serialize_evaluation(latest)
        return {
            "status": "reviewed" if latest else "not_run",
            "object_type": object_type,
            "object_id": object_id,
            "rubric_id": LITERARY_REVISION_RUBRIC_ID,
            "latest_evaluation": latest_payload,
            "latest_score": latest_payload["overall_score"] if latest_payload else None,
            "requires_human_review": bool(latest_payload["requires_human_review"]) if latest_payload else False,
            "lens_evaluations": lenses,
            "patch_candidates": [self.serialize_patch_candidate(row) for row in patch_rows],
        }

    def _scene_source(self, scene: SceneCard) -> dict[str, Any]:
        state = self.session.get(SceneRunState, scene.scene_id)
        final_row = self.session.get(FinalScene, state.current_final_scene_row_id) if state and state.current_final_scene_row_id else None
        if final_row is None:
            final_row = self.session.execute(
                select(FinalScene)
                .where(FinalScene.scene_id == scene.scene_id)
                .order_by(FinalScene.created_at.desc(), FinalScene.row_id.desc())
            ).scalars().first()
        return {
            "content": final_row.content if final_row else "",
            "source_text_ref": f"final_scene:{final_row.row_id}" if final_row else f"scene:{scene.scene_id}",
            "source_bundle_id": final_row.source_bundle_id if final_row else (state.current_bundle_id if state else None),
        }

    def _chapter_source(self, chapter: ChapterGoal) -> dict[str, Any]:
        final_memory = self.session.execute(
            select(ChapterMemory)
            .where(ChapterMemory.chapter_id == chapter.chapter_id, ChapterMemory.aggregate_stage == "final")
            .order_by(ChapterMemory.created_at.desc(), ChapterMemory.row_id.desc())
        ).scalars().first()
        if final_memory:
            return {
                "content": final_memory.content,
                "source_text_ref": f"chapter_memory:{final_memory.row_id}",
                "source_bundle_id": None,
            }
        scenes = self.session.execute(
            select(SceneCard).where(SceneCard.chapter_id == chapter.chapter_id, SceneCard.trashed_flag == 0).order_by(SceneCard.scene_seq.asc())
        ).scalars().all()
        parts: list[str] = []
        for scene in scenes:
            source = self._scene_source(scene)
            if source["content"]:
                parts.append(source["content"])
        return {
            "content": "\n\n".join(parts),
            "source_text_ref": f"chapter_assembled:{chapter.chapter_id}",
            "source_bundle_id": None,
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

    def _require_patch_candidate(self, patch_id: str) -> PassagePatchCandidate:
        row = self.session.get(PassagePatchCandidate, patch_id)
        if row is None:
            raise DomainError("PASSAGE_PATCH_NOT_FOUND", "passage patch candidate not found", status_code=404)
        return row

    def _latest_preference_profile(self) -> AuthorPreferenceProfile | None:
        return self.session.execute(
            select(AuthorPreferenceProfile)
            .where(AuthorPreferenceProfile.scope_type == "global", AuthorPreferenceProfile.scope_ref_id == "global")
            .order_by(AuthorPreferenceProfile.created_at.desc(), AuthorPreferenceProfile.profile_id.desc())
        ).scalars().first()

    def _refresh_author_preference_profile(self, *, actor_ref: str) -> AuthorPreferenceProfile:
        decided = self.session.execute(
            select(PassagePatchCandidate)
            .where(PassagePatchCandidate.author_decision.in_(("accepted", "rejected")))
            .order_by(PassagePatchCandidate.created_at.asc(), PassagePatchCandidate.patch_id.asc())
        ).scalars().all()
        summary = _preference_summary(decided)
        profile = self._latest_preference_profile()
        if profile is None:
            profile = AuthorPreferenceProfile(
                profile_id="author_pref_global_global",
                scope_type="global",
                scope_ref_id="global",
                status="draft",
                runtime_eligible=0,
                summary_json=summary,
                source_patch_ids_json=[row.patch_id for row in decided],
                created_by=actor_ref or "writer_deep_review",
            )
            self.session.add(profile)
        else:
            profile.status = "draft"
            profile.runtime_eligible = 0
            profile.summary_json = summary
            profile.source_patch_ids_json = [row.patch_id for row in decided]
            profile.created_by = actor_ref or profile.created_by
        return profile


def _diagnose_by_lens(content: str) -> dict[str, dict[str, Any]]:
    findings: dict[str, list[dict[str, Any]]] = {lens: [] for lens in DEEP_REVIEW_LENSES}
    text = content or ""
    if len(text.strip()) < 80:
        findings["story"].append(
            _finding(
                lens="story",
                dimension="choice_pressure",
                classification="blocking",
                issue="正文太短，尚不足以承载深改判断。",
                recommendation="补足人物选择、阻碍和结尾变化后再诊断。",
                evidence=text[:40],
                why="短文本容易让系统误把设定摘要当成完整场景。",
            )
        )
    if not any(token in text for token in ("选择", "决定", "必须", "不能", "公开", "隐藏", "保护")):
        findings["character"].append(
            _finding(
                lens="character",
                dimension="choice_pressure",
                classification="blocking",
                issue="人物没有被逼到必须选择的位置。",
                recommendation="让人物在两个代价之间做出可见动作。",
                evidence=text[:36],
                why="读者需要看到人物承担后果，而不是只接收线索。",
            )
        )
    elif "解释" in text and not any(token in text for token in ("藏", "交给", "删掉", "撕掉", "承认")):
        findings["character"].append(
            _finding(
                lens="character",
                dimension="character_contradiction",
                classification="blocking",
                issue="人物说出了正确理由，但选择还没有落成不可逆动作。",
                recommendation="让人物为保护或公开付出一个立刻可见的代价。",
                evidence=_first_match(text, ("解释", "保护")),
                why="深改阶段不能只让人物站在正确立场上，必须让她失去或冒犯什么。",
            )
        )
    if not any(mark in text for mark in ("“", "\"", "说", "问", "答")) or "解释" in text:
        findings["prose"].append(
            _finding(
                lens="prose",
                dimension="dialogue_subtext",
                classification="revision",
                issue="对白承担了解释功能，潜台词压力不足。",
                recommendation="把解释改成回避、截断、反问或动作。",
                evidence=_first_match(text, ("解释", "说")),
                why="深改台需要让对白产生关系摩擦，而不是复述动机。",
            )
        )
    repeated_terms = _repeated_ai_trace_terms(text)
    if repeated_terms:
        findings["prose"].append(
            _finding(
                lens="prose",
                dimension="repetitive_expression",
                classification="revision",
                issue=f"出现重复手势或同质 AI 氛围词：{'、'.join(repeated_terms)}。",
                recommendation="保留一个核心动作，其余改成关系反应或物理后果。",
                evidence=repeated_terms[0],
                why="重复的漂亮动作会让作者声线变薄，削弱人物独特性。",
            )
        )
    if not text.rstrip().endswith(("？", "?", "。")) or not any(token in text[-80:] for token in ("心跳", "证据", "谁", "不能", "独自", "公开", "隐藏")):
        findings["reader"].append(
            _finding(
                lens="reader",
                dimension="ending_drive",
                classification="taste",
                issue="结尾可以更硬地把读者推向下一场。",
                recommendation="用一个未回答的动作或视觉钩子收束，而不是总结。",
                evidence=text[-40:],
                why="结尾不是装饰，它决定读者是否愿意继续翻页。",
            )
        )
    if not any(token in text for token in ("保护", "真相", "代价", "背叛", "公开", "隐藏")):
        findings["theme"].append(
            _finding(
                lens="theme",
                dimension="theme_pressure",
                classification="revision",
                issue="场景的主题压力还没有落到人物选择上。",
                recommendation="把主题问题压进人物的具体取舍。",
                evidence=text[:40],
                why="深改阶段需要知道这场戏触碰了作品真正关心的问题。",
            )
        )
    else:
        findings["theme"].append(
            _finding(
                lens="theme",
                dimension="theme_pressure",
                classification="taste",
                issue="主题压力已经出现，但还可以更不体面。",
                recommendation="让人物承认自己也从隐瞒中获益，而不只是正确地保护他人。",
                evidence=_first_match(text, ("保护", "真相", "公开", "隐藏")),
                why="人物有不体面的一瞬间，主题才会有重量。",
            )
        )
    payloads: dict[str, dict[str, Any]] = {}
    for lens in DEEP_REVIEW_LENSES:
        lens_findings = findings[lens]
        payloads[lens] = {
            "findings": lens_findings,
            "scores": _scores_for_findings(lens_findings),
        }
    return payloads


def _finding(*, lens: str, dimension: str, classification: str, issue: str, recommendation: str, evidence: str, why: str) -> dict[str, Any]:
    return {
        "lens": lens,
        "dimension": dimension,
        "severity": classification,
        "classification": classification,
        "issue": issue,
        "recommendation": recommendation,
        "evidence_excerpt": evidence,
        "evidence_location": "source text",
        "why_it_matters": why,
    }


def _scores_for_findings(findings: list[dict[str, Any]]) -> dict[str, float]:
    scores = {dimension: 0.78 for dimension in LITERARY_REVISION_DIMENSIONS}
    for finding in findings:
        dimension = finding.get("dimension")
        if dimension not in scores:
            continue
        if finding.get("severity") == "blocking":
            scores[dimension] = min(scores[dimension], 0.42)
        elif finding.get("severity") == "revision":
            scores[dimension] = min(scores[dimension], 0.58)
        elif finding.get("severity") == "taste":
            scores[dimension] = min(scores[dimension], 0.72)
    return scores


def _cap_scores_for_findings(scores: dict[str, float], findings: list[dict[str, Any]]) -> dict[str, float]:
    capped = dict(scores)
    if findings:
        for dimension in capped:
            capped[dimension] = min(capped[dimension], 0.85)
    for finding in findings:
        dimension = finding.get("dimension")
        if dimension in capped and finding.get("severity") == "blocking":
            capped[dimension] = min(capped[dimension], 0.42)
        elif dimension in capped and finding.get("severity") == "revision":
            capped[dimension] = min(capped[dimension], 0.58)
    return capped


def _revision_brief_from_findings(findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    brief: list[dict[str, Any]] = []
    for finding in findings:
        if finding.get("severity") == "taste":
            priority = "low"
        elif finding.get("severity") == "blocking":
            priority = "high"
        else:
            priority = "medium"
        brief.append(
            {
                "dimension": finding.get("dimension"),
                "classification": finding.get("severity"),
                "action": finding.get("recommendation"),
                "priority": priority,
                "evidence_excerpt": finding.get("evidence_excerpt", ""),
            }
        )
    return brief


def _evidence_spans(content: str, findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    spans: list[dict[str, Any]] = []
    for finding in findings:
        excerpt = str(finding.get("evidence_excerpt") or "")
        if not excerpt:
            continue
        start = content.find(excerpt)
        if start < 0:
            continue
        spans.append({"text": excerpt, "start": start, "end": start + len(excerpt)})
        if len(spans) >= 8:
            break
    return spans


def _replacement_options(source_excerpt: str, issue_dimension: str) -> list[dict[str, Any]]:
    compressed = source_excerpt.strip().rstrip("。！？")
    return [
        {
            "option_id": "option_shorter",
            "tone": "shorter",
            "label": "更短",
            "replacement_text": f"{compressed}。",
            "changed_dimensions": [issue_dimension, "information_rhythm"],
            "why_it_helps": "压掉解释余量，让动作和停顿自己承担压力。",
        },
        {
            "option_id": "option_sharper",
            "tone": "sharper",
            "label": "更狠",
            "replacement_text": f"{compressed}。她没有补充理由，只把证据袋按进掌心。",
            "changed_dimensions": [issue_dimension, "relationship_tension"],
            "why_it_helps": "让角色拒绝解释，把锋利感放进动作后果。",
        },
        {
            "option_id": "option_subtler",
            "tone": "subtler",
            "label": "更含蓄",
            "replacement_text": f"{compressed}。话音落下后，她先看了一眼门缝。",
            "changed_dimensions": [issue_dimension, "dialogue_subtext"],
            "why_it_helps": "把明说转为观察和回避，保留读者自行判断的空间。",
        },
    ]


def _preference_summary(rows: list[PassagePatchCandidate]) -> dict[str, list[str]]:
    preferred: list[str] = []
    rejected: list[str] = []
    ai_traces: list[str] = []
    for row in rows:
        if row.author_decision == "accepted":
            selected = _selected_option(row)
            tone = selected.get("tone") if selected else ""
            if tone == "sharper":
                preferred.append("偏好更锋利的局部改写，让动作代替解释。")
            elif tone == "subtler":
                preferred.append("偏好更含蓄的局部改写，保留读者判断空间。")
            elif tone == "shorter":
                preferred.append("偏好更短的句段，压缩解释余量。")
            else:
                preferred.append(f"偏好围绕 {row.issue_dimension} 的人工局部改写。")
        elif row.author_decision == "rejected":
            note = row.author_decision_note or "保留作者原句，不把所有重复都视为错误。"
            rejected.append(note if "保留" in note else f"保留原意：{note}")
        ai_traces.extend(term for term in _repeated_ai_trace_terms(row.source_excerpt) if term not in ai_traces)
    return {
        "preferred_revision_moves": _dedupe(preferred),
        "rejected_revision_moves": _dedupe(rejected),
        "ai_trace_terms_to_watch": _dedupe(ai_traces),
        "runtime_policy": ["偏好摘要保持 draft；审核批准前不得进入运行 bundle。"],
    }


def _selected_option(row: PassagePatchCandidate) -> dict[str, Any] | None:
    for option in row.replacement_options_json or []:
        if option.get("option_id") == row.selected_option_id:
            return option
    return None


def _empty_preference_summary() -> dict[str, list[str]]:
    return {
        "preferred_revision_moves": [],
        "rejected_revision_moves": [],
        "ai_trace_terms_to_watch": [],
        "runtime_policy": ["偏好摘要保持 draft；审核批准前不得进入运行 bundle。"],
    }


def _repeated_ai_trace_terms(text: str) -> list[str]:
    watched = ("手指", "停顿", "幽蓝", "冷光", "低声", "盐霜", "泛着")
    return [term for term in watched if text.count(term) >= 2 or (term in {"幽蓝", "冷光", "盐霜"} and term in text)]


def _first_match(text: str, terms: tuple[str, ...]) -> str:
    for term in terms:
        index = text.find(term)
        if index >= 0:
            return text[max(0, index - 10) : index + len(term) + 16]
    return text[:40]


def _required_text(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise DomainError("PASSAGE_PATCH_INVALID", f"{key} is required", status_code=400)
    return value.strip()


def _optional_text(payload: dict[str, Any], key: str) -> str | None:
    value = payload.get(key)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    unique: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        unique.append(value)
    return unique
