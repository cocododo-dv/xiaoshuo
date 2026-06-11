"""控制塔服务 — 锚点(全书记忆)与交接契约(下发约束)。

设计语义(交接包 chat39 最终结论):塔只做四件事——规划契约、
下发起草台、章级审计、守门归档;正文只在起草台与写作台产出。
本服务承载前两件;章级审计在后续迭代。
"""
from __future__ import annotations

import json
import logging
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
from novel_system.services.projects import ProjectService

logger = logging.getLogger(__name__)

ANCHOR_KINDS = {"fact", "trait", "setting", "timeline"}
AUDIT_KINDS = {"drift", "overdue", "unplanted_reveal", "causal_break", "unfair_clue", "stall", "deflation", "arc"}
AUDIT_SEVERITIES = {"warn", "block"}
AUDIT_DECISIONS = {"accept_fix", "defer", "dismiss"}
ANCHOR_STATUSES = {"pinned", "faded"}
CONTRACT_TRANSITIONS = {
    "drafting": {"ready"},
    "ready": {"drafting", "dispatched"},
    "dispatched": {"archived"},
    "archived": set(),
}


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

    def update_constraints(self, project_id: str, chapter_id: str, payload: dict[str, Any]) -> dict[str, Any]:
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
        normalized = []
        for item in constraints:
            if not isinstance(item, dict):
                raise DomainError("TOWER_CONTRACT_CONSTRAINTS_INVALID", "each constraint must be an object", status_code=400)
            text = str(item.get("text") or "").strip()
            if not text:
                raise DomainError("TOWER_CONTRACT_CONSTRAINT_TEXT_REQUIRED", "constraint text is required", status_code=400)
            anchor_id = str(item.get("anchor_id") or "").strip()
            if anchor_id:
                self._require_anchor(project.project_id, anchor_id)
            normalized.append(
                {
                    "text": text,
                    "anchor_id": anchor_id or None,
                    "scene_id": str(item.get("scene_id") or "").strip() or None,
                    "kind": str(item.get("kind") or "constraint").strip() or "constraint",
                }
            )
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
