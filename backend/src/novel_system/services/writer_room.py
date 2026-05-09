from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from novel_system.db.models import AuthorDraft, AuthorDraftProposal, ChapterGoal, SceneCard, SceneRunState, WriterEvaluation
from novel_system.services.author_drafts import AuthorDraftService
from novel_system.services.author_lifecycle import AuthorLifecycleService
from novel_system.services.author_desk import AuthorDeskService
from novel_system.services.errors import DomainError

SEVERITY_DISPLAY_PRIORITY = {
    "blocking": "先改这个",
    "blocker": "先改这个",
    "critical": "先改这个",
    "major": "先改这个",
    "revision": "先改这个",
    "profile_mismatch": "需人工判断",
    "taste": "审美取舍",
    "ignore_ok": "可保留",
    "info": "可保留",
}

PROPOSAL_KIND_LABELS = {
    "structure_note": "结构提示",
    "whole_draft": "整段候选",
    "local_patch": "局部改法",
    "dialogue_pass": "对白深改",
    "language_pass": "语言压缩",
    "continuation": "续写",
    "near_final_rewrite": "近终稿重写",
}


class WriterRoomService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.lifecycle = AuthorLifecycleService(session)
        self.drafts = AuthorDraftService(session)

    def room(self, object_type: str, object_id: str) -> dict[str, Any]:
        target = self._target(object_type, object_id)
        desk = AuthorDeskService(self.session).snapshot(object_type, object_id)
        draft = self._current_draft(object_type, object_id)
        primary_text = self._primary_text(draft, desk)
        diagnosis = self._diagnosis(object_type, object_id)
        proposals = self._open_proposals(draft)
        longform_cards = self._longform_cards(desk.get("longform_pressure") or [])
        proposal_cards = [_proposal_card(row) for row in proposals]
        top_issue = diagnosis.get("top_issue")
        keep_advice = diagnosis.get("keep") or "保留已经能推动人物行动的句段，只改最影响读者追问的位置。"
        return {
            "target": target,
            "navigation": self._navigation(target),
            "chapter": self._chapter_payload(target["chapter_id"]),
            "scene_card": self._scene_payload(target["scene_id"]) if target["scene_id"] else None,
            "draft": AuthorDraftService.serialize_draft(draft),
            "primary_text": primary_text,
            "diagnosis": diagnosis,
            "top_issue": top_issue,
            "keep_advice": keep_advice,
            "proposals": proposals,
            "proposal_cards": proposal_cards,
            "context_pressure": desk.get("longform_pressure") or [],
            "longform_cards": longform_cards,
            "scene_form": self._scene_form(target["scene_id"], diagnosis),
            "daily_focus": desk.get("daily_focus") or [],
            "author_preference_summary": desk.get("author_preference_summary") or {},
            "next_actions": self._next_actions(draft, proposal_cards, diagnosis, longform_cards),
        }

    def _target(self, object_type: str, object_id: str) -> dict[str, str | None]:
        if object_type == "scene":
            scene = self.lifecycle.require_active_scene(object_id)
            return {
                "object_type": "scene",
                "object_id": scene.scene_id,
                "chapter_id": scene.chapter_id,
                "scene_id": scene.scene_id,
            }
        if object_type == "chapter":
            chapter = self.lifecycle.require_active_chapter(object_id)
            return {
                "object_type": "chapter",
                "object_id": chapter.chapter_id,
                "chapter_id": chapter.chapter_id,
                "scene_id": None,
            }
        raise DomainError("WRITER_ROOM_TARGET_INVALID", "object_type must be scene or chapter", status_code=400)

    def _navigation(self, target: dict[str, str | None]) -> dict[str, Any]:
        chapter_id = str(target["chapter_id"])
        workspace = self.lifecycle.author_workspace_payload(chapter_id)
        return {
            "selected_chapter_id": chapter_id,
            "selected_scene_id": target["scene_id"],
            "chapters": self.lifecycle.list_active_chapters(),
            "scenes": workspace.get("scenes") or [],
        }

    def _chapter_payload(self, chapter_id: str | None) -> dict[str, Any] | None:
        if not chapter_id:
            return None
        chapter = self.session.get(ChapterGoal, chapter_id)
        if chapter is None:
            return None
        return self.lifecycle.serialize_chapter(chapter)

    def _scene_payload(self, scene_id: str | None) -> dict[str, Any] | None:
        if not scene_id:
            return None
        scene = self.session.get(SceneCard, scene_id)
        if scene is None:
            return None
        return self.lifecycle.serialize_author_scene(scene, self.session.get(SceneRunState, scene_id))

    def _current_draft(self, object_type: str, object_id: str) -> AuthorDraft | None:
        return self.session.execute(
            select(AuthorDraft)
            .where(
                AuthorDraft.object_type == object_type,
                AuthorDraft.object_id == object_id,
                AuthorDraft.status == "current",
            )
            .order_by(AuthorDraft.updated_at.desc(), AuthorDraft.draft_id.desc())
        ).scalars().first()

    def _primary_text(self, draft: AuthorDraft | None, desk: dict[str, Any]) -> dict[str, Any]:
        if draft is not None:
            return {
                "source": "author_draft",
                "source_ref": f"author_draft:{draft.draft_id}",
                "content": draft.content or "",
                "revision_no": draft.revision_no,
            }
        runtime_text = desk.get("runtime_text") or desk.get("aggregate_text") or {}
        if runtime_text:
            return {
                "source": runtime_text.get("text_layer") or "runtime",
                "source_ref": runtime_text.get("source_ref"),
                "content": runtime_text.get("content") or "",
                "revision_no": None,
            }
        return {"source": "empty", "source_ref": None, "content": "", "revision_no": None}

    def _diagnosis(self, object_type: str, object_id: str) -> dict[str, Any]:
        row = self.session.execute(
            select(WriterEvaluation)
            .where(
                WriterEvaluation.object_type == object_type,
                WriterEvaluation.object_id == object_id,
                WriterEvaluation.parent_evaluation_id.is_(None),
            )
            .order_by(WriterEvaluation.created_at.desc(), WriterEvaluation.evaluation_id.desc())
        ).scalars().first()
        if row is None:
            return {
                "status": "not_run",
                "score_visible": False,
                "top_issue": None,
                "keep": "先保留作者最有辨识度的动作、句法和悬念余味。",
                "options": [],
                "author_visible_summary": {
                    "label": "先写一版",
                    "summary": "暂无诊断。先写正文，再让系统只指出最影响阅读的一处。",
                },
                "advanced_evidence": {},
            }
        findings = [item for item in (row.findings_json or []) if isinstance(item, dict)]
        top_issue = findings[0] if findings else None
        visible_top_issue = _author_visible_finding(top_issue)
        return {
            "status": row.status,
            "score_visible": False,
            "evaluation_id": row.evaluation_id,
            "rubric_id": row.rubric_id,
            "top_issue": visible_top_issue,
            "keep": _keep_suggestion(findings),
            "options": _revision_options(row.revision_brief_json or [], top_issue),
            "requires_human_review": bool(row.requires_human_review),
            "author_visible_summary": _author_visible_summary(row, visible_top_issue),
            "advanced_evidence": {
                "overall_score": row.overall_score,
                "scores": row.scores_json or {},
                "findings": findings,
                "revision_brief": row.revision_brief_json or [],
                "evidence_spans": row.evidence_spans_json or [],
                "source_text_ref": row.source_text_ref,
                "source_bundle_id": row.source_bundle_id,
                "rubric_id": row.rubric_id,
            },
        }

    def _open_proposals(self, draft: AuthorDraft | None) -> list[dict[str, Any]]:
        if draft is None:
            return []
        rows = self.session.execute(
            select(AuthorDraftProposal)
            .where(AuthorDraftProposal.draft_id == draft.draft_id, AuthorDraftProposal.status == "candidate")
            .order_by(AuthorDraftProposal.created_at.desc(), AuthorDraftProposal.proposal_id.desc())
        ).scalars().all()
        return [AuthorDraftService.serialize_proposal(row) for row in rows]

    @staticmethod
    def _longform_cards(cards: list[dict[str, Any]]) -> list[dict[str, Any]]:
        severity_rank = {"critical": 0, "major": 1, "minor": 2, "info": 3}
        type_rank = {
            "promise_without_payoff": 0,
            "chapter_promise_unpaid": 0,
            "foreshadow_debt": 1,
            "foreshadowing_debt": 1,
            "character_arc_gap": 2,
            "information_congestion": 3,
            "relationship_turn_stall": 4,
            "ending_drive_drop": 5,
            "reference_leakage_risk": 6,
        }
        sanitized = [_author_longform_card(card) for card in cards if isinstance(card, dict)]
        sanitized = sorted(
            sanitized,
            key=lambda card: (
                severity_rank.get(str(card.get("severity") or ""), 9),
                type_rank.get(str(card.get("card_type") or ""), 9),
                str(card.get("card_id") or ""),
            ),
        )
        return sanitized[:3]

    def _scene_form(self, scene_id: str | None, diagnosis: dict[str, Any]) -> str | None:
        if scene_id:
            scene = self.session.get(SceneCard, scene_id)
            if scene is not None and scene.scene_type:
                return scene.scene_type
        top_issue = diagnosis.get("top_issue") or {}
        if isinstance(top_issue, dict) and top_issue.get("scene_form"):
            return str(top_issue["scene_form"])
        evidence = diagnosis.get("advanced_evidence") or {}
        for finding in evidence.get("findings") or []:
            if isinstance(finding, dict) and finding.get("scene_form"):
                return str(finding["scene_form"])
        return None

    def _next_actions(
        self,
        draft: AuthorDraft | None,
        proposals: list[dict[str, Any]],
        diagnosis: dict[str, Any],
        pressure: list[dict[str, Any]],
    ) -> list[dict[str, str]]:
        actions = [{"action": "write", "label": "继续写正文", "reason": "正文是当前工作中心。"}]
        if draft is None:
            actions.append({"action": "create_draft", "label": "建立作者稿", "reason": "把运行稿转成可编辑版本。"})
        if proposals:
            actions.append({"action": "review_proposal", "label": "比较可采纳改法", "reason": "先看差异，再决定是否合并。"})
        if diagnosis.get("top_issue"):
            actions.append({"action": "revise_focus", "label": "处理最关键问题", "reason": str(diagnosis["top_issue"].get("issue") or "")})
        if pressure:
            actions.append({"action": "check_longform", "label": "查看长篇压力", "reason": "避免局部改动破坏后续承诺。"})
        return actions[:4]


def _keep_suggestion(findings: list[dict[str, Any]]) -> str:
    for finding in findings:
        if str(finding.get("severity") or "") == "taste":
            return "这属于审美取舍，优先保留作者声线。"
    return "保留已经能推动人物行动的句段，只改最影响读者追问的位置。"


def _author_visible_finding(finding: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(finding, dict):
        return None
    severity = str(finding.get("severity") or finding.get("classification") or "").strip().lower()
    return {
        "dimension": finding.get("dimension") or "",
        "severity": severity or finding.get("severity") or "",
        "display_priority": SEVERITY_DISPLAY_PRIORITY.get(severity, "先改这个"),
        "issue": finding.get("issue") or finding.get("message") or "",
        "recommendation": finding.get("recommendation") or "",
        "why_it_matters": finding.get("why_it_matters") or "",
        "evidence_excerpt": finding.get("evidence_excerpt") or "",
        "lens": finding.get("lens") or "",
        "scene_form": finding.get("scene_form") or None,
    }


def _author_visible_summary(row: WriterEvaluation, top_issue: dict[str, Any] | None) -> dict[str, Any]:
    if row.requires_human_review:
        label = "需人工判断"
    elif top_issue is None:
        label = "可保留"
    else:
        label = top_issue.get("display_priority") or "先改这个"
    summary = "暂无必须处理的问题。"
    if top_issue is not None:
        summary = top_issue.get("issue") or top_issue.get("recommendation") or summary
    return {
        "label": label,
        "summary": summary,
        "score_visible": False,
        "requires_human_review": bool(row.requires_human_review),
        "evaluation_id": row.evaluation_id,
    }


def _proposal_card(row: dict[str, Any]) -> dict[str, Any]:
    proposal_kind = str(row.get("proposal_kind") or row.get("proposal_type") or "whole_draft")
    return {
        "proposal_id": row.get("proposal_id"),
        "draft_id": row.get("draft_id"),
        "proposal_kind": proposal_kind,
        "proposal_type": row.get("proposal_type"),
        "display_kind": PROPOSAL_KIND_LABELS.get(proposal_kind, "可采纳改法"),
        "status": row.get("status"),
        "merge_status": row.get("merge_status"),
        "rationale": row.get("rationale"),
        "excerpt": row.get("replacement_text") or row.get("content") or "",
        "target_range": row.get("target_range"),
        "source_evaluation_id": row.get("source_evaluation_id"),
    }


def _author_longform_card(card: dict[str, Any]) -> dict[str, Any]:
    recommendation = card.get("recommendation") if isinstance(card.get("recommendation"), dict) else {}
    evidence = card.get("evidence") if isinstance(card.get("evidence"), dict) else {}
    return {
        "card_id": card.get("card_id"),
        "card_type": card.get("card_type"),
        "severity": card.get("severity"),
        "object_type": card.get("object_type"),
        "object_id": card.get("object_id"),
        "chapter_id": card.get("chapter_id"),
        "scene_id": card.get("scene_id"),
        "title": evidence.get("issue") or card.get("card_type") or "长篇压力",
        "summary": recommendation.get("summary") or recommendation.get("action") or "",
        "recommendation": recommendation,
        "source_refs": card.get("source_refs") or [],
        "updated_at": card.get("updated_at"),
    }


def _revision_options(revision_brief: list[Any], top_issue: dict[str, Any] | None) -> list[dict[str, str]]:
    options: list[dict[str, str]] = []
    for item in revision_brief[:2]:
        if isinstance(item, dict):
            text = str(item.get("action") or item.get("summary") or item.get("recommendation") or "").strip()
        else:
            text = str(item or "").strip()
        if text:
            options.append({"kind": "brief", "text": text})
    if not options and top_issue:
        recommendation = str(top_issue.get("recommendation") or "").strip()
        if recommendation:
            options.append({"kind": "finding", "text": recommendation})
    return options[:2]
