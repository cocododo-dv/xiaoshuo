"""控制塔服务 — 锚点(全书记忆)与交接契约(下发约束)。

设计语义(交接包 chat39 最终结论):塔只做四件事——规划契约、
下发起草台、章级审计、守门归档;正文只在起草台与写作台产出。
本服务承载前两件;章级审计在后续迭代。
"""
from __future__ import annotations

import json
import logging
import re
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from novel_system.db.models import (
    ChapterAuditFinding,
    ChapterContract,
    LongformAnchor,
    ReviewItem,
    utcnow,
)
from novel_system.services.errors import DomainError
from novel_system.services.llm_accounting import LLMCallContext
from novel_system.services.projects import ProjectService
from novel_system.settings import get_settings

logger = logging.getLogger(__name__)

# fact/trait/setting/timeline = 设定锚点；promise/thread/arc = FE 控制塔的
# 悬念债/故事线/人物弧线（FE-ALIGN F4：结构化形状以 JSON 存 note 列，text 存摘要）。
ANCHOR_KINDS = {"fact", "trait", "setting", "timeline", "promise", "thread", "arc"}
AUDIT_KINDS = {"drift", "overdue", "unplanted_reveal", "causal_break", "unfair_clue", "stall", "deflation", "arc"}
AUDIT_SEVERITIES = {"warn", "block"}
AUDIT_DECISIONS = {"accept_fix", "defer", "dismiss"}
ANCHOR_STATUSES = {"pinned", "faded"}
# FE-ALIGN P2(D13)：章级「违约级判定」LLM 节点。确定性回执只声明检出/未检出，
# 这个节点把「草稿违反交接契约第 N 条」这一步接真；LLM 关闭时诚实降级（不机器判违约）。
AUDIT_ADJUDICATE_NODE_ID = "chapter_audit_adjudicate"
CONTRACT_TRANSITIONS = {
    "drafting": {"ready"},
    "ready": {"drafting", "dispatched"},
    "dispatched": {"archived"},
    "archived": set(),
}


# ---------------- 审计回执的确定性扫描工具（FE-ALIGN H2） ----------------
def _anchor_fe(anchor: LongformAnchor) -> dict[str, Any]:
    try:
        parsed = json.loads(anchor.note or "{}")
        fe = parsed.get("fe") if isinstance(parsed, dict) else None
        return fe if isinstance(fe, dict) else {}
    except (ValueError, TypeError):
        return {}


def _draft_paragraphs(content: str | None) -> list[str]:
    """正文（HTML 或纯文本）→ 段落列表（剥标签；占位文档不算正文）。"""
    raw = str(content or "")
    if not raw.strip():
        return []
    text = re.sub(r"</p\s*>|<br\s*/?>", "\n", raw, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    paras = [p.strip() for p in text.split("\n") if p.strip()]
    if len(paras) == 1 and paras[0].startswith("在这里开始写"):
        return []
    return paras


def _scan_value(paragraphs: list[dict[str, Any]], value: str) -> dict[str, Any] | None:
    """value 子串在章正文中的首个命中：返回包含它的真实句子与位置。"""
    needle = value.strip()
    if not needle:
        return None
    for para in paragraphs:
        text = str(para.get("text") or "")
        if needle not in text:
            continue
        for sentence in re.split(r"(?<=[。！？；…!?])", text):
            if needle in sentence and sentence.strip():
                return {"sentence": sentence.strip(), "scene_title": para["scene_title"], "idx": para["idx"]}
        return {"sentence": text[:80], "scene_title": para["scene_title"], "idx": para["idx"]}
    return None


def _anchor_payload(anchor: LongformAnchor) -> dict[str, Any]:
    return {
        "anchor_id": anchor.anchor_id,
        "project_id": anchor.project_id,
        "kind": anchor.kind,
        "text": anchor.text,
        "source_ref": anchor.source_ref or "",
        "note": anchor.note or "",
        "status": anchor.status,
        "updated_at": anchor.updated_at,
    }


def _finding_payload(finding: ChapterAuditFinding) -> dict[str, Any]:
    return {
        "finding_id": finding.finding_id,
        "project_id": finding.project_id,
        "chapter_id": finding.chapter_id,
        "kind": finding.kind,
        "severity": finding.severity,
        "text": finding.text,
        "evidence": finding.evidence or "",
        "status": finding.status,
        "decision": finding.decision or "",
        "decision_note": finding.decision_note or "",
        "updated_at": finding.updated_at,
    }


def _contract_payload(contract: ChapterContract) -> dict[str, Any]:
    return {
        "contract_id": contract.contract_id,
        "project_id": contract.project_id,
        "chapter_id": contract.chapter_id,
        "status": contract.status,
        "constraints": contract.constraints_json or [],
        "dispatched_at": contract.dispatched_at,
        "archived_at": contract.archived_at,
        "updated_at": contract.updated_at,
    }


class LongformTowerService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def _require_project(self, project_id: str):
        return ProjectService(self.session).require_project(project_id)

    # ---------------- 锚点 ----------------
    def list_anchors(self, project_id: str) -> dict[str, Any]:
        project = self._require_project(project_id)
        anchors = self.session.scalars(
            select(LongformAnchor)
            .where(LongformAnchor.project_id == project.project_id)
            .order_by(LongformAnchor.created_at)
        ).all()
        return {
            "project_id": project.project_id,
            "anchors": [_anchor_payload(item) for item in anchors],
        }

    def create_anchor(self, project_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        project = self._require_project(project_id)
        text = str(payload.get("text") or "").strip()
        if not text:
            raise DomainError("TOWER_ANCHOR_TEXT_REQUIRED", "anchor text is required", status_code=400)
        kind = str(payload.get("kind") or "fact").strip()
        if kind not in ANCHOR_KINDS:
            raise DomainError("TOWER_ANCHOR_KIND_INVALID", f"kind must be one of {sorted(ANCHOR_KINDS)}", status_code=400)
        anchor = LongformAnchor(
            anchor_id=f"ANC_{uuid.uuid4().hex[:10].upper()}",
            project_id=project.project_id,
            kind=kind,
            text=text,
            source_ref=str(payload.get("source_ref") or "").strip() or None,
            note=str(payload.get("note") or "").strip() or None,
            status="pinned",
        )
        self.session.add(anchor)
        self.session.flush()
        return _anchor_payload(anchor)

    def _require_anchor(self, project_id: str, anchor_id: str) -> LongformAnchor:
        anchor = self.session.get(LongformAnchor, anchor_id)
        if anchor is None or anchor.project_id != project_id:
            raise DomainError("TOWER_ANCHOR_NOT_FOUND", "anchor not found", status_code=404)
        return anchor

    def update_anchor(self, project_id: str, anchor_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        project = self._require_project(project_id)
        anchor = self._require_anchor(project.project_id, anchor_id)
        if "text" in payload:
            text = str(payload.get("text") or "").strip()
            if not text:
                raise DomainError("TOWER_ANCHOR_TEXT_REQUIRED", "anchor text is required", status_code=400)
            anchor.text = text
        if "kind" in payload:
            kind = str(payload.get("kind") or "").strip()
            if kind not in ANCHOR_KINDS:
                raise DomainError("TOWER_ANCHOR_KIND_INVALID", f"kind must be one of {sorted(ANCHOR_KINDS)}", status_code=400)
            anchor.kind = kind
        if "status" in payload:
            status = str(payload.get("status") or "").strip()
            if status not in ANCHOR_STATUSES:
                raise DomainError("TOWER_ANCHOR_STATUS_INVALID", f"status must be one of {sorted(ANCHOR_STATUSES)}", status_code=400)
            anchor.status = status
        if "note" in payload:
            anchor.note = str(payload.get("note") or "").strip() or None
        if "source_ref" in payload:
            anchor.source_ref = str(payload.get("source_ref") or "").strip() or None
        self.session.flush()
        return _anchor_payload(anchor)

    # ---------------- 交接契约 ----------------
    def get_or_create_contract(self, project_id: str, chapter_id: str) -> dict[str, Any]:
        project = self._require_project(project_id)
        contract = self.session.scalars(
            select(ChapterContract).where(
                ChapterContract.project_id == project.project_id,
                ChapterContract.chapter_id == chapter_id,
            )
        ).first()
        if contract is None:
            contract = ChapterContract(
                contract_id=f"CTR_{uuid.uuid4().hex[:10].upper()}",
                project_id=project.project_id,
                chapter_id=chapter_id,
                status="drafting",
                constraints_json=[],
            )
            self.session.add(contract)
            self.session.flush()
        return _contract_payload(contract)

    def _require_contract(self, project_id: str, chapter_id: str) -> ChapterContract:
        contract = self.session.scalars(
            select(ChapterContract).where(
                ChapterContract.project_id == project_id,
                ChapterContract.chapter_id == chapter_id,
            )
        ).first()
        if contract is None:
            raise DomainError("TOWER_CONTRACT_NOT_FOUND", "chapter contract not found", status_code=404)
        return contract

    def update_constraints(
        self,
        project_id: str,
        chapter_id: str,
        payload: dict[str, Any],
        *,
        actor_ref: str | None = None,
    ) -> dict[str, Any]:
        project = self._require_project(project_id)
        self.get_or_create_contract(project.project_id, chapter_id)
        contract = self._require_contract(project.project_id, chapter_id)
        if contract.status in {"dispatched", "archived"}:
            raise DomainError(
                "TOWER_CONTRACT_LOCKED",
                "dispatched/archived contracts are immutable; archive and start the next chapter instead",
                status_code=409,
            )
        constraints = payload.get("constraints")
        if not isinstance(constraints, list):
            raise DomainError("TOWER_CONTRACT_CONSTRAINTS_INVALID", "constraints must be a list", status_code=400)
        previous_by_id = {
            str(item.get("constraint_id")): item
            for item in (contract.constraints_json or [])
            if isinstance(item, dict) and item.get("constraint_id")
        }
        normalized = []
        seen_constraint_ids: set[str] = set()
        for index, item in enumerate(constraints, start=1):
            if not isinstance(item, dict):
                raise DomainError("TOWER_CONTRACT_CONSTRAINTS_INVALID", "each constraint must be an object", status_code=400)
            text = str(item.get("text") or "").strip()
            if not text:
                raise DomainError("TOWER_CONTRACT_CONSTRAINT_TEXT_REQUIRED", "constraint text is required", status_code=400)
            anchor_id = str(item.get("anchor_id") or "").strip()
            if anchor_id:
                self._require_anchor(project.project_id, anchor_id)
            enforcement = str(item.get("enforcement") or "advisory").strip().lower()
            if enforcement not in {"advisory", "blocking"}:
                raise DomainError(
                    "TOWER_CONTRACT_ENFORCEMENT_INVALID",
                    "enforcement must be advisory or blocking",
                    status_code=400,
                )
            match_mode = str(item.get("match_mode") or "any").strip().lower()
            if match_mode not in {"any", "all"}:
                raise DomainError(
                    "TOWER_CONTRACT_MATCH_MODE_INVALID",
                    "match_mode must be any or all",
                    status_code=400,
                )
            raw_terms = item.get("check_terms")
            if raw_terms is None:
                check_terms: list[str] = []
            elif isinstance(raw_terms, list):
                if any(not isinstance(value, str) for value in raw_terms):
                    raise DomainError(
                        "TOWER_CONTRACT_CHECK_TERMS_INVALID",
                        "check_terms must contain strings only",
                        status_code=400,
                    )
                check_terms = list(
                    dict.fromkeys(
                        value.strip()
                        for value in raw_terms
                        if value.strip()
                    )
                )
            else:
                raise DomainError(
                    "TOWER_CONTRACT_CHECK_TERMS_INVALID",
                    "check_terms must be a list of non-empty strings",
                    status_code=400,
                )
            raw_waived = item.get("waived", False)
            if not isinstance(raw_waived, bool):
                raise DomainError(
                    "TOWER_CONTRACT_WAIVED_INVALID",
                    "waived must be a boolean",
                    status_code=400,
                )
            waived = raw_waived
            waiver_reason = str(item.get("waiver_reason") or "").strip() or None
            if waived and not waiver_reason:
                raise DomainError(
                    "TOWER_CONTRACT_WAIVER_REASON_REQUIRED",
                    "a waived constraint needs a waiver_reason",
                    status_code=400,
                )
            constraint_id = (
                str(item.get("constraint_id") or "").strip()
                or f"{contract.contract_id}:{index}"
            )
            if constraint_id in seen_constraint_ids:
                raise DomainError(
                    "TOWER_CONTRACT_CONSTRAINT_ID_DUPLICATE",
                    "constraint_id must be unique within a chapter contract",
                    status_code=400,
                    details={"constraint_id": constraint_id},
                )
            seen_constraint_ids.add(constraint_id)
            constraint = {
                "constraint_id": constraint_id,
                "text": text,
                "anchor_id": anchor_id or None,
                "scene_id": str(item.get("scene_id") or "").strip() or None,
                "kind": str(item.get("kind") or "constraint").strip() or "constraint",
                "enforcement": enforcement,
                "check_terms": check_terms,
                "match_mode": match_mode,
                "waived": waived,
                "waiver_reason": waiver_reason,
            }
            previous = previous_by_id.get(constraint_id)
            unchanged_waiver = bool(
                waived
                and previous
                and previous.get("waived") is True
                and all(previous.get(key) == value for key, value in constraint.items())
            )
            constraint["waiver_actor_ref"] = (
                (previous.get("waiver_actor_ref") or actor_ref or "operator")
                if unchanged_waiver
                else (actor_ref or "operator") if waived else None
            )
            constraint["waived_at"] = (
                (previous.get("waived_at") or utcnow())
                if unchanged_waiver
                else utcnow() if waived else None
            )
            normalized.append(constraint)
        contract.constraints_json = normalized
        self.session.flush()
        return _contract_payload(contract)

    # ---------------- 章级审计 ----------------
    def list_findings(self, project_id: str, chapter_id: str) -> dict[str, Any]:
        project = self._require_project(project_id)
        findings = self.session.scalars(
            select(ChapterAuditFinding)
            .where(
                ChapterAuditFinding.project_id == project.project_id,
                ChapterAuditFinding.chapter_id == chapter_id,
            )
            .order_by(ChapterAuditFinding.created_at)
        ).all()
        return {
            "project_id": project.project_id,
            "chapter_id": chapter_id,
            "findings": [_finding_payload(item) for item in findings],
            "open_count": sum(1 for item in findings if item.status == "open"),
        }

    def list_all_findings(self, project_id: str) -> dict[str, Any]:
        """FE-ALIGN P7：项目级审计清单（lf7 桥的 ruled/pending 缓存数据源）。"""
        project = self._require_project(project_id)
        findings = self.session.scalars(
            select(ChapterAuditFinding)
            .where(ChapterAuditFinding.project_id == project.project_id)
            .order_by(ChapterAuditFinding.created_at)
        ).all()
        return {
            "project_id": project.project_id,
            "findings": [_finding_payload(item) for item in findings],
            "open_count": sum(1 for item in findings if item.status == "open"),
        }

    def create_finding(self, project_id: str, chapter_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        project = self._require_project(project_id)
        text = str(payload.get("text") or "").strip()
        if not text:
            raise DomainError("TOWER_AUDIT_TEXT_REQUIRED", "finding text is required", status_code=400)
        kind = str(payload.get("kind") or "drift").strip()
        if kind not in AUDIT_KINDS:
            raise DomainError("TOWER_AUDIT_KIND_INVALID", f"kind must be one of {sorted(AUDIT_KINDS)}", status_code=400)
        severity = str(payload.get("severity") or "warn").strip()
        if severity not in AUDIT_SEVERITIES:
            raise DomainError("TOWER_AUDIT_SEVERITY_INVALID", f"severity must be one of {sorted(AUDIT_SEVERITIES)}", status_code=400)
        # FE-ALIGN P7：允许调用方指定 finding_id（demo seed / 桥迁移的幂等键）；
        # FE 展示元数据（subject/value/source/drift）以 JSON 存 evidence（meta 优先）。
        finding_id = str(payload.get("finding_id") or "").strip() or f"AUD_{uuid.uuid4().hex[:10].upper()}"
        existing = self.session.get(ChapterAuditFinding, finding_id)
        if existing is not None:
            return _finding_payload(existing)
        meta = payload.get("meta") if isinstance(payload.get("meta"), dict) else None
        evidence = str(payload.get("evidence") or "").strip() or None
        if meta is not None and not evidence:
            evidence = json.dumps(meta, ensure_ascii=False)
        finding = ChapterAuditFinding(
            finding_id=finding_id,
            project_id=project.project_id,
            chapter_id=chapter_id,
            kind=kind,
            severity=severity,
            text=text,
            evidence=evidence,
            status="open",
        )
        self.session.add(finding)
        self.session.flush()
        # 链路①：finding 创建 ↔ 待办 decision 卡同事务同源（dedupe=canon:{finding_id}）
        self._create_canon_card(finding, meta or {})
        return _finding_payload(finding)

    def _create_canon_card(self, finding: ChapterAuditFinding, meta: dict[str, Any]) -> None:
        from novel_system.services.review_cards import ReviewCardService

        subject = str(meta.get("subject") or "").strip()
        value = str(meta.get("value") or "").strip()
        source = str(meta.get("source") or "").strip()
        can_rule = bool(value and value != "（待统一）")
        actions: list[dict[str, Any]] = []
        if can_rule:
            actions.append(
                {
                    "label": f"统一为「{value}」并锁定",
                    "intent": "primary",
                    "op": "resolve",
                    "effect": {"type": "rule_canon", "finding_id": finding.finding_id, "value": value},
                }
            )
        actions.append(
            {
                "label": "去控制塔细看" if can_rule else "去控制塔裁决",
                "intent": "ghost" if can_rule else "primary",
                "op": "nav",
                "nav_to": "longform",
            }
        )
        actions.append({"label": "稍后再说", "intent": "quiet", "op": "snooze"})
        detail = finding.text + (
            f"。控制塔建议以第 {source} 章为准（{subject} = {value}）；裁决后锁定为设定锚点，塔里的同一条会同步消失。"
            if can_rule
            else "。这条还没有可直接采纳的统一值，去控制塔裁决。"
        )
        ReviewCardService(self.session).create_card(
            {
                "project_id": finding.project_id,
                "chapter_id": finding.chapter_id,
                "kind": "risk" if bool(meta.get("drift")) or finding.severity == "block" else "decision",
                "priority": 1 if bool(meta.get("drift")) or finding.severity == "block" else 2,
                "title": f"设定冲突待裁决：{subject or finding.text[:24]}",
                "source": "长篇控制塔",
                "where": f"长篇控制塔 · 第 {finding.chapter_id} 章" if not source else f"长篇控制塔 · 第 {source} 章",
                "detail": detail,
                "options": [value] if can_rule else None,
                "dedupe_key": f"canon:{finding.finding_id}",
                "actions": actions,
            },
            actor_ref="longform_tower",
        )

    def adjudicate_finding(self, project_id: str, finding_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        project = self._require_project(project_id)
        finding = self.session.get(ChapterAuditFinding, finding_id)
        if finding is None or finding.project_id != project.project_id:
            raise DomainError("TOWER_AUDIT_NOT_FOUND", "audit finding not found", status_code=404)
        decision = str(payload.get("decision") or "").strip()
        if decision not in AUDIT_DECISIONS:
            raise DomainError("TOWER_AUDIT_DECISION_INVALID", f"decision must be one of {sorted(AUDIT_DECISIONS)}", status_code=400)
        finding.decision = decision
        finding.decision_note = str(payload.get("note") or "").strip() or None
        finding.status = "adjudicated"
        # 链路①反向：直接走塔的 adjudicate 时，同事务把对应待办卡置 resolved
        # （effect rule_canon 路径里该卡正被 resolve 流程处理，这里幂等置位即可）
        card = self.session.scalars(
            select(ReviewItem).where(
                ReviewItem.project_id == project.project_id,
                ReviewItem.dedupe_key == f"canon:{finding.finding_id}",
            )
        ).first()
        if card is not None and (card.state or "open") == "open":
            card.state = "resolved"
        self.session.flush()
        return _finding_payload(finding)

    # ---------------- 章级审计回执（FE-ALIGN H2，纯确定性） ----------------
    # 诚实口径：扫描只声明「检出（带真实引用句）/未检出（待人工核对）」，
    # 不机器判定「违约」——违约判定属 LLM 审计节点（D13）。
    def audit_receipt(self, project_id: str, chapter_id: str) -> dict[str, Any]:
        from novel_system.db.models import AuthorDraft, ChapterGoal, SceneCard

        project = self._require_project(project_id)
        chapter = self.session.get(ChapterGoal, chapter_id)
        if chapter is None or (chapter.project_id and chapter.project_id != project.project_id):
            raise DomainError("CHAPTER_NOT_FOUND", "chapter not found", status_code=404)
        contract = self.get_or_create_contract(project_id, chapter_id)

        scenes = self.session.scalars(
            select(SceneCard)
            .where(SceneCard.chapter_id == chapter_id, SceneCard.trashed_flag == 0)
            .order_by(SceneCard.scene_seq.asc())
        ).all()
        scene_rows: list[dict[str, Any]] = []
        paragraphs: list[dict[str, Any]] = []  # {scene_title, idx, text}
        words_total = 0
        for scene in scenes:
            draft = self.session.scalars(
                select(AuthorDraft).where(
                    AuthorDraft.object_type == "scene",
                    AuthorDraft.object_id == scene.scene_id,
                    AuthorDraft.status == "current",
                )
            ).first()
            paras = _draft_paragraphs(draft.content if draft else "")
            title = str((scene.writer_brief_json or {}).get("title") or scene.scene_goal or scene.scene_id)
            for idx, text in enumerate(paras, start=1):
                paragraphs.append({"scene_title": title, "idx": idx, "text": text})
            words = sum(len(p.replace(" ", "")) for p in paras)
            words_total += words
            scene_rows.append(
                {
                    "scene_id": scene.scene_id,
                    "title": title,
                    "state": scene.state,
                    "words": words,
                    "has_draft": bool(paras),
                }
            )

        chapter_no = self._chapter_ordinal(project.project_id, chapter_id)
        anchors = self.session.scalars(
            select(LongformAnchor).where(
                LongformAnchor.project_id == project.project_id,
                LongformAnchor.status == "pinned",
            ).order_by(LongformAnchor.created_at)
        ).all()
        hits: list[dict[str, Any]] = []
        misses: list[dict[str, Any]] = []
        pending: list[dict[str, Any]] = []
        for anchor in anchors:
            fe = _anchor_fe(anchor)
            if anchor.kind == "promise":
                if fe.get("payoff") == chapter_no and str(fe.get("state") or "open") != "closed":
                    pending.append({"kind": "promise", "id": fe.get("id") or anchor.anchor_id, "title": str(fe.get("title") or anchor.text), "note": "本章为计划回收章——是否落地待人工核对"})
                continue
            if anchor.kind not in {"fact", "trait", "setting", "timeline"}:
                continue
            subject = str(fe.get("subject") or "").strip()
            value = str(fe.get("value") or "").strip()
            if not value:
                continue
            hit = _scan_value(paragraphs, value)
            entry = {"id": fe.get("id") or anchor.anchor_id, "subject": subject or anchor.text, "value": value}
            if hit is not None:
                hits.append({**entry, "evidence": hit["sentence"], "at": f"{hit['scene_title']} · 段 {hit['idx']}"})
            else:
                misses.append(entry)

        return {
            "chapter_id": chapter_id,
            "chapter_no": chapter_no,
            "contract": contract,
            "scenes": scene_rows,
            "words_total": words_total,
            "has_text": bool(paragraphs),
            "anchor_hits": hits,
            "anchor_misses": misses,
            "pending": pending,
        }

    def _chapter_ordinal(self, project_id: str, chapter_id: str) -> int:
        from novel_system.db.models import ChapterGoal

        rows = self.session.scalars(
            select(ChapterGoal.chapter_id)
            .where(ChapterGoal.project_id == project_id, ChapterGoal.trashed_flag == 0)
            .order_by(ChapterGoal.display_order.asc(), ChapterGoal.created_at.asc())
        ).all()
        for index, cid in enumerate(rows, start=1):
            if cid == chapter_id:
                return index
        return 0

    def transition_contract(self, project_id: str, chapter_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        project = self._require_project(project_id)
        self.get_or_create_contract(project.project_id, chapter_id)
        contract = self._require_contract(project.project_id, chapter_id)
        target = str(payload.get("status") or "").strip()
        allowed = CONTRACT_TRANSITIONS.get(contract.status, set())
        if target not in allowed:
            raise DomainError(
                "TOWER_CONTRACT_TRANSITION_INVALID",
                f"cannot move contract from {contract.status} to {target or '(empty)'}",
                status_code=409,
            )
        if target == "archived" and not bool(payload.get("force")):
            open_findings = self.session.scalars(
                select(ChapterAuditFinding).where(
                    ChapterAuditFinding.project_id == project.project_id,
                    ChapterAuditFinding.chapter_id == chapter_id,
                    ChapterAuditFinding.status == "open",
                )
            ).all()
            if open_findings:
                raise DomainError(
                    "TOWER_AUDIT_OPEN",
                    f"{len(open_findings)} audit findings are still open; adjudicate them or archive with force=true",
                    status_code=409,
                )
        if target == "ready" and not (contract.constraints_json or []):
            raise DomainError(
                "TOWER_CONTRACT_EMPTY",
                "a contract needs at least one constraint before it is ready",
                status_code=409,
            )
        contract.status = target
        if target == "dispatched":
            contract.dispatched_at = utcnow()
        if target == "archived":
            contract.archived_at = utcnow()
        self.session.flush()
        result = _contract_payload(contract)
        # FE-ALIGN P7 链路③：归档写回 —— 推进目录章状态 + 触发资料派生（LLM 关则静默跳过）。
        if target == "archived":
            result["write_back"] = self._archive_write_back(project.project_id, chapter_id)
        return result

    def _archive_write_back(self, project_id: str, chapter_id: str) -> dict[str, Any]:
        from novel_system.db.models import ChapterGoal
        from novel_system.services.library_derive import LibraryDeriveService

        write_back: dict[str, Any] = {"chapter_state": None, "derive": None}
        chapter = self.session.get(ChapterGoal, chapter_id)
        if chapter is not None and chapter.project_id == project_id:
            if str(chapter.state or "planned") in {"planned", "todo", "writing"}:
                chapter.state = "draft"
            write_back["chapter_state"] = chapter.state
            self.session.flush()
        try:
            write_back["derive"] = LibraryDeriveService(self.session).derive_from_chapter(project_id, chapter_id)
        except Exception:  # 派生失败不阻塞归档
            logger.exception("archive derive failed for %s", chapter_id)
            write_back["derive"] = {"skipped": True, "reason": "error"}
        return write_back

    # ---------------- 章级「违约级判定」（FE-ALIGN P2 / D13，LLM + 诚实降级） ----------------
    # 设计：在 audit_receipt 的确定性扫描之上，用 LLM 把「草稿是否违反交接契约第 N 条」
    # 这一步接真——每条违约证据化（须引正文原句）、禁臆造；落 ChapterAuditFinding(kind=drift)
    # 并同事务产待办裁决卡（复用 create_finding 全链路）。LLM 关闭时诚实降级：只声明
    # 检出/未检出，drifted 留空，给 author_action 引导，不机器判违约（这是正确行为而非占位）。
    def adjudicate_draft(
        self, project_id: str, chapter_id: str, *, llm_client: Any | None = None
    ) -> dict[str, Any]:
        receipt = self.audit_receipt(project_id, chapter_id)
        settings = get_settings()
        if not settings.llm_enabled:
            return {
                "skipped": True,
                "reason": "llm_disabled",
                "violations": [],
                "findings_created": 0,
                "author_action": {
                    "title": "未配置 LLM",
                    "message": "违约级裁定需要启用 LLM。确定性审计回执不受影响（仍如实声明检出/未检出）；"
                    "配置后可在控制塔重跑「逐条裁定」。",
                    "target_view": "system-config",
                },
                "receipt": receipt,
            }
        if not receipt.get("has_text"):
            return {"skipped": True, "reason": "no_content", "violations": [], "findings_created": 0, "receipt": receipt}
        constraints = (receipt.get("contract") or {}).get("constraints") or []
        if not constraints:
            return {
                "skipped": True,
                "reason": "no_contract_constraints",
                "violations": [],
                "findings_created": 0,
                "receipt": receipt,
            }
        violations = self._adjudicate_violations(project_id, chapter_id, receipt, llm_client)
        created = self._record_violations(project_id, chapter_id, violations)
        return {
            "skipped": False,
            "violations": violations,
            "findings_created": created,
            "receipt": receipt,
        }

    def _build_llm_client(self) -> Any:
        from novel_system.services.llm_client import LLMClient
        from novel_system.services.system_config import load_llm_provider_runtime_configs

        settings = get_settings()
        return LLMClient(
            provider=settings.llm_provider,
            base_url=settings.llm_base_url,
            api_key=settings.llm_api_key,
            timeout_seconds=settings.llm_timeout_seconds,
            provider_configs=load_llm_provider_runtime_configs(),
        )

    def _chapter_prose_for_audit(self, chapter_id: str) -> str:
        """章正文（按场景拼接，剥标签，占位文档不计）——喂给违约裁定 LLM 的上下文。"""
        from novel_system.db.models import AuthorDraft, SceneCard

        scenes = self.session.scalars(
            select(SceneCard)
            .where(SceneCard.chapter_id == chapter_id, SceneCard.trashed_flag == 0)
            .order_by(SceneCard.scene_seq.asc())
        ).all()
        blocks: list[str] = []
        for scene in scenes:
            draft = self.session.scalars(
                select(AuthorDraft).where(
                    AuthorDraft.object_type == "scene",
                    AuthorDraft.object_id == scene.scene_id,
                    AuthorDraft.status == "current",
                )
            ).first()
            paras = _draft_paragraphs(draft.content if draft else "")
            if not paras:
                continue
            title = str((scene.writer_brief_json or {}).get("title") or scene.scene_goal or scene.scene_id)
            blocks.append(f"【{title}】\n" + "\n".join(paras))
        return "\n\n".join(blocks)

    def _adjudicate_violations(
        self, project_id: str, chapter_id: str, receipt: dict[str, Any], llm_client: Any | None
    ) -> list[dict[str, Any]]:
        from novel_system.services.style_reference._llm_helper import LLMNodeError, call_llm_node
        from novel_system.services.style_reference.untrusted_data import UntrustedPayload

        client = llm_client or self._build_llm_client()
        constraints = (receipt.get("contract") or {}).get("constraints") or []
        payload = {
            "chapter_no": receipt.get("chapter_no"),
            "constraints": [
                {
                    "index": idx + 1,
                    "text": c.get("text"),
                    "kind": c.get("kind"),
                    "anchor_id": c.get("anchor_id"),
                }
                for idx, c in enumerate(constraints)
            ],
            "anchor_hits": [
                {"subject": h.get("subject"), "value": h.get("value"), "evidence": h.get("evidence"), "at": h.get("at")}
                for h in (receipt.get("anchor_hits") or [])
            ],
            "anchor_misses": [
                {"subject": m.get("subject"), "value": m.get("value")} for m in (receipt.get("anchor_misses") or [])
            ],
            "chapter_prose": self._chapter_prose_for_audit(chapter_id)[:12000],
        }
        try:
            structured = call_llm_node(
                AUDIT_ADJUDICATE_NODE_ID,
                UntrustedPayload(payload),
                client,
                session=self.session,
                context=LLMCallContext(
                    scope_type="chapter",
                    scope_id=chapter_id,
                    project_id=project_id,
                    chapter_id=chapter_id,
                    node_id=AUDIT_ADJUDICATE_NODE_ID,
                    step="chapter_audit_adjudicate",
                ),
            )
        except LLMNodeError as exc:
            logger.warning("chapter audit adjudicate llm call failed: %s", exc)
            return []
        out: list[dict[str, Any]] = []
        for item in structured.get("violations") or []:
            if not isinstance(item, dict):
                continue
            text = str(item.get("text") or "").strip()
            if not text:
                continue
            kind = str(item.get("kind") or "drift").strip()
            if kind not in AUDIT_KINDS:
                kind = "drift"
            severity = str(item.get("severity") or "warn").strip()
            if severity not in AUDIT_SEVERITIES:
                severity = "warn"
            out.append(
                {
                    "clause_ref": str(item.get("clause_ref") or "").strip(),
                    "kind": kind,
                    "severity": severity,
                    "text": text,
                    "evidence_sentence": str(item.get("evidence_sentence") or "").strip(),
                    "at": str(item.get("at") or "").strip(),
                    "suggested_fix": str(item.get("suggested_fix") or "").strip(),
                }
            )
        return out

    def _record_violations(
        self, project_id: str, chapter_id: str, violations: list[dict[str, Any]]
    ) -> int:
        """每条违约 → 确定性 finding_id（同章+条款+文案幂等）→ create_finding 落库 + 产裁决卡。"""
        import hashlib

        created = 0
        for v in violations:
            seed = f"{chapter_id}:{v.get('clause_ref') or ''}:{v['text']}"
            finding_id = "AUD_" + hashlib.sha1(seed.encode("utf-8")).hexdigest()[:10].upper()
            v["finding_id"] = finding_id  # 回挂真实 finding_id，供前端裁决/去重消费
            already = self.session.get(ChapterAuditFinding, finding_id) is not None
            self.create_finding(
                project_id,
                chapter_id,
                {
                    "finding_id": finding_id,
                    "kind": v["kind"],
                    "severity": v["severity"],
                    "text": v["text"],
                    "evidence": v.get("evidence_sentence") or None,
                    "meta": {
                        "drift": True,
                        "clause_ref": v.get("clause_ref") or "",
                        "at": v.get("at") or "",
                        "suggested_fix": v.get("suggested_fix") or "",
                    },
                },
            )
            if not already:
                created += 1
        return created

    # ---------------- 结构层确定性派生（FE-ALIGN P3，0 LLM、幂等） ----------------
    # 从雪花场景规划投影故事线/悬念债锚点，让非演示作品的控制塔也有真实结构。
    # 只投影高置信、无歧义的映射：onstage 角色区段 → thread；显式伏笔/下游义务 → promise。
    # 断链/空降等推断性判定不在此投影（需真实数据校准，避免在没数据时产假阳性）。
    _THREAD_COLORS = ("crimson", "slate", "ink", "gold", "sage", "teal")

    def derive_structure(self, project_id: str) -> dict[str, Any]:
        from novel_system.db.models import SnowflakeScenePlan, StoryCharacter

        project = self._require_project(project_id)
        plans = self.session.scalars(
            select(SnowflakeScenePlan)
            .where(SnowflakeScenePlan.project_id == project.project_id)
            .order_by(SnowflakeScenePlan.scene_seq.asc())
        ).all()
        if not plans:
            return {"skipped": True, "reason": "no_scene_plans", "threads_created": 0, "promises_created": 0}

        # 章号映射：按 scene_seq 首现顺序给每个 chapter_id 编号（确定性）
        chapter_no: dict[str, int] = {}
        for plan in plans:
            if plan.chapter_id and plan.chapter_id not in chapter_no:
                chapter_no[plan.chapter_id] = len(chapter_no) + 1

        char_names = {
            row.character_id: row.display_name
            for row in self.session.scalars(
                select(StoryCharacter).where(StoryCharacter.project_id == project.project_id)
            ).all()
        }

        # —— thread：每个出场角色的章节区段（连续章号合并成 segs） ——
        char_chapters: dict[str, set[int]] = {}
        for plan in plans:
            no = chapter_no.get(plan.chapter_id)
            if not no:
                continue
            for raw in plan.onstage_chars_json or []:
                cid = str(raw or "").strip()
                if cid:
                    char_chapters.setdefault(cid, set()).add(no)

        threads_created = 0
        for index, (cid, nos) in enumerate(char_chapters.items()):
            name = char_names.get(cid) or cid
            anchor_id = self._derive_anchor_id(project.project_id, "thread", cid)
            fe = {
                "id": anchor_id,
                "name": name,
                "short": name[:6],
                "color": self._THREAD_COLORS[index % len(self._THREAD_COLORS)],
                "segs": self._merge_segments(nos),
                "derived": True,
            }
            if self._upsert_derived_anchor(project.project_id, anchor_id, "thread", f"{name} 的故事线", fe):
                threads_created += 1

        # —— promise：显式伏笔 / 下游义务（首现章为 setup，payoff 待人工排期） ——
        promise_setup: dict[str, int] = {}
        for plan in plans:
            no = chapter_no.get(plan.chapter_id) or 0
            for raw in list(plan.involved_foreshadowing_json or []) + list(plan.downstream_obligations_json or []):
                text = str(raw or "").strip()
                if text and text not in promise_setup:
                    promise_setup[text] = no

        promises_created = 0
        for text, setup_no in promise_setup.items():
            anchor_id = self._derive_anchor_id(project.project_id, "promise", text)
            fe = {
                "id": anchor_id,
                "title": text[:60],
                "setup": setup_no,
                "payoff": None,
                "state": "open",
                "pri": "medium",
                "pinned": False,
                "derived": True,
                "note": text,
            }
            if self._upsert_derived_anchor(project.project_id, anchor_id, "promise", text, fe):
                promises_created += 1

        return {"skipped": False, "threads_created": threads_created, "promises_created": promises_created}

    @staticmethod
    def _merge_segments(nos: set[int]) -> list[list[int]]:
        segs: list[list[int]] = []
        for n in sorted(nos):
            if segs and n == segs[-1][1] + 1:
                segs[-1][1] = n
            else:
                segs.append([n, n])
        return segs

    def _derive_anchor_id(self, project_id: str, kind: str, key: str) -> str:
        import hashlib

        seed = f"{project_id}:{kind}:{key}"
        return "ANC_" + hashlib.sha1(seed.encode("utf-8")).hexdigest()[:10].upper()

    def _upsert_derived_anchor(
        self, project_id: str, anchor_id: str, kind: str, text: str, fe: dict[str, Any]
    ) -> bool:
        """存在则刷新派生 note/text（幂等，保留人工 status），不存在则新建。返回是否新建。"""
        note = json.dumps({"fe": fe}, ensure_ascii=False)
        existing = self.session.get(LongformAnchor, anchor_id)
        if existing is not None:
            existing.text = text
            existing.note = note
            self.session.flush()
            return False
        self.session.add(
            LongformAnchor(
                anchor_id=anchor_id,
                project_id=project_id,
                kind=kind,
                text=text,
                source_ref="snowflake_scene_plan",
                note=note,
                status="pinned",
            )
        )
        self.session.flush()
        return True
