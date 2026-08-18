"""Acyclic transaction boundary for long-form audit adjudication."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from novel_system.db.models import ChapterAuditFinding, ReviewItem
from novel_system.services.errors import DomainError
from novel_system.services.projects import ProjectService


AUDIT_DECISIONS = frozenset({"accept_fix", "defer", "dismiss"})


def finding_payload(finding: ChapterAuditFinding) -> dict[str, Any]:
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


def adjudicate_finding(
    session: Session,
    project_id: str,
    finding_id: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    project = ProjectService(session).require_project(project_id)
    finding = session.get(ChapterAuditFinding, finding_id)
    if finding is None or finding.project_id != project.project_id:
        raise DomainError("TOWER_AUDIT_NOT_FOUND", "audit finding not found", status_code=404)
    decision = str(payload.get("decision") or "").strip()
    if decision not in AUDIT_DECISIONS:
        raise DomainError(
            "TOWER_AUDIT_DECISION_INVALID",
            f"decision must be one of {sorted(AUDIT_DECISIONS)}",
            status_code=400,
        )
    finding.decision = decision
    finding.decision_note = str(payload.get("note") or "").strip() or None
    finding.status = "adjudicated"
    card = session.scalars(
        select(ReviewItem).where(
            ReviewItem.project_id == project.project_id,
            ReviewItem.dedupe_key == f"canon:{finding.finding_id}",
        )
    ).first()
    if card is not None and (card.state or "open") == "open":
        card.state = "resolved"
    session.flush()
    return finding_payload(finding)
