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
    ChapterGoal,
    LongformAnchor,
    SceneCard,
    utcnow,
)
from novel_system.services.errors import DomainError
from novel_system.services.longform_adjudication import (
    adjudicate_finding as adjudicate_audit_finding,
    finding_payload as _finding_payload,
)
from novel_system.services.projects import ProjectService

logger = logging.getLogger(__name__)

# fact/trait/setting/timeline = 设定锚点；promise/thread/arc = FE 控制塔的
# 悬念债/故事线/人物弧线（FE-ALIGN F4：结构化形状以 JSON 存 note 列，text 存摘要）。
ANCHOR_KINDS = {"fact", "trait", "setting", "timeline", "promise", "thread", "arc"}
AUDIT_KINDS = {"drift", "overdue", "unplanted_reveal", "causal_break", "unfair_clue", "stall", "deflation", "arc"}
AUDIT_SEVERITIES = {"warn", "block"}
ANCHOR_STATUSES = {"pinned", "faded"}
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

    def _require_chapter(self, project_id: str, chapter_id: str) -> ChapterGoal:
        chapter = self.session.get(ChapterGoal, chapter_id)
        if (
            chapter is None
            or chapter.trashed_flag == 1
            or chapter.project_id != project_id
        ):
            raise DomainError(
                "CHAPTER_NOT_FOUND",
                "chapter not found in project",
                status_code=404,
            )
        return chapter

    def _require_contract_scene(
        self,
        project_id: str,
        chapter_id: str,
        scene_id: str,
    ) -> SceneCard:
        scene = self.session.get(SceneCard, scene_id)
        if (
            scene is None
            or scene.trashed_flag == 1
            or scene.chapter_id != chapter_id
            or (scene.project_id and scene.project_id != project_id)
        ):
            raise DomainError(
                "TOWER_CONTRACT_SCENE_NOT_FOUND",
                "contract scene not found in chapter",
                status_code=404,
            )
        return scene

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
    def get_contract(self, project_id: str, chapter_id: str) -> dict[str, Any]:
        """Read a contract without making GET/audit calls mutate the database."""

        project = self._require_project(project_id)
        self._require_chapter(project.project_id, chapter_id)
        contract = self.session.scalars(
            select(ChapterContract).where(
                ChapterContract.project_id == project.project_id,
                ChapterContract.chapter_id == chapter_id,
            )
        ).first()
        if contract is None:
            return {
                "contract_id": None,
                "project_id": project.project_id,
                "chapter_id": chapter_id,
                "status": "drafting",
                "constraints": [],
                "dispatched_at": None,
                "archived_at": None,
                "updated_at": None,
            }
        return _contract_payload(contract)

    def get_or_create_contract(self, project_id: str, chapter_id: str) -> dict[str, Any]:
        project = self._require_project(project_id)
        self._require_chapter(project.project_id, chapter_id)
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
            scene_id = str(item.get("scene_id") or "").strip()
            if scene_id:
                self._require_contract_scene(
                    project.project_id,
                    chapter_id,
                    scene_id,
                )
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
                "scene_id": scene_id or None,
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
        self._require_chapter(project.project_id, chapter_id)
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
        self._require_chapter(project.project_id, chapter_id)
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
            if (
                existing.project_id == project.project_id
                and existing.chapter_id == chapter_id
            ):
                return _finding_payload(existing)
            raise DomainError(
                "TOWER_AUDIT_FINDING_ID_CONFLICT",
                "audit finding id is already in use",
                status_code=409,
            )
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
        return adjudicate_audit_finding(self.session, project_id, finding_id, payload)
        # 链路①反向：直接走塔的 adjudicate 时，同事务把对应待办卡置 resolved
        # （effect rule_canon 路径里该卡正被 resolve 流程处理，这里幂等置位即可）

    # ---------------- 章级审计回执（FE-ALIGN H2，纯确定性） ----------------
    # 诚实口径：扫描只声明「检出（带真实引用句）/未检出（待人工核对）」，
    # 不机器判定「违约」——违约判定属 LLM 审计节点（D13）。
    def audit_receipt(self, project_id: str, chapter_id: str) -> dict[str, Any]:
        from novel_system.db.models import AuthorDraft

        project = self._require_project(project_id)
        chapter = self._require_chapter(project.project_id, chapter_id)
        contract = self.get_contract(project_id, chapter_id)

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
