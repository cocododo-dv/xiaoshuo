"""Causal chain integrity validation — blueprint §4.

Core principle: "没有上一层的绑定 spec，绝不生成散文。"

Validates that scene plans form a coherent causal chain:
- Every scene (after the first) links to a causal prerequisite
- Scenes with choices/decisions specify what the character sacrifices
- Downstream obligations are eventually consumed by a later scene
- Prerequisite links point to scenes that actually exist
"""
from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from novel_system.db.models import SnowflakeScenePlan


@dataclass(slots=True)
class CausalChainViolation:
    scene_plan_id: str
    violation_type: str
    message: str
    severity: str


@dataclass(slots=True)
class CausalChainReport:
    project_id: str
    total_scenes: int
    violations: list[CausalChainViolation] = field(default_factory=list)
    chain_coverage: float = 0.0
    cost_coverage: float = 0.0

    @property
    def error_count(self) -> int:
        return sum(1 for v in self.violations if v.severity == "error")

    @property
    def warning_count(self) -> int:
        return sum(1 for v in self.violations if v.severity == "warning")


class CausalChainValidator:
    def __init__(self, session: Session) -> None:
        self.session = session

    def validate_project(self, project_id: str) -> CausalChainReport:
        plans = list(self.session.execute(
            select(SnowflakeScenePlan)
            .where(
                SnowflakeScenePlan.project_id == project_id,
                SnowflakeScenePlan.status != "deleted",
            )
            .order_by(SnowflakeScenePlan.scene_seq.asc())
        ).scalars().all())

        report = CausalChainReport(project_id=project_id, total_scenes=len(plans))
        if not plans:
            return report

        scene_ids = {p.scene_id for p in plans}
        referenced_as_prereq: set[str] = set()

        linked_count = 0
        cost_eligible = 0
        cost_filled = 0

        for idx, plan in enumerate(plans):
            prereq = plan.causal_prerequisite_scene_id
            if prereq:
                linked_count += 1
                referenced_as_prereq.add(prereq)
                if prereq not in scene_ids:
                    report.violations.append(CausalChainViolation(
                        scene_plan_id=plan.scene_plan_id,
                        violation_type="broken_link",
                        message=(
                            f"Scene '{plan.scene_id}' (seq {plan.scene_seq}) references "
                            f"prerequisite '{prereq}' which does not exist in project."
                        ),
                        severity="error",
                    ))
            elif idx > 0:
                report.violations.append(CausalChainViolation(
                    scene_plan_id=plan.scene_plan_id,
                    violation_type="missing_prerequisite",
                    message=(
                        f"Scene '{plan.scene_id}' (seq {plan.scene_seq}) has no "
                        f"causal_prerequisite_scene_id — causal chain gap."
                    ),
                    severity="warning",
                ))

            has_choice = bool(plan.dilemma or plan.decision)
            if has_choice:
                cost_eligible += 1
                if plan.cost_requirement and plan.cost_requirement.strip():
                    cost_filled += 1
                else:
                    report.violations.append(CausalChainViolation(
                        scene_plan_id=plan.scene_plan_id,
                        violation_type="free_choice",
                        message=(
                            f"Scene '{plan.scene_id}' (seq {plan.scene_seq}) has a "
                            f"dilemma/decision but no cost_requirement — "
                            f"角色做了决定但什么都没牺牲 (free choice)."
                        ),
                        severity="warning",
                    ))

        for plan in plans:
            obligations = plan.downstream_obligations_json or []
            if not obligations:
                continue
            if plan.scene_id not in referenced_as_prereq:
                later = any(
                    p.causal_prerequisite_scene_id == plan.scene_id
                    for p in plans
                    if p.scene_seq > plan.scene_seq
                )
                if not later:
                    report.violations.append(CausalChainViolation(
                        scene_plan_id=plan.scene_plan_id,
                        violation_type="orphan_obligation",
                        message=(
                            f"Scene '{plan.scene_id}' (seq {plan.scene_seq}) declares "
                            f"{len(obligations)} downstream obligation(s) but no later "
                            f"scene references it as a causal prerequisite."
                        ),
                        severity="warning",
                    ))

        report.chain_coverage = (linked_count / max(report.total_scenes - 1, 1)) if report.total_scenes > 1 else 1.0
        report.cost_coverage = (cost_filled / cost_eligible) if cost_eligible > 0 else 1.0

        return report


def format_validation_report(report: CausalChainReport) -> str:
    lines = [
        f"# Causal Chain Integrity Report — project {report.project_id}",
        f"Scenes: {report.total_scenes} | "
        f"Chain coverage: {report.chain_coverage:.0%} | "
        f"Cost coverage: {report.cost_coverage:.0%}",
        f"Errors: {report.error_count} | Warnings: {report.warning_count}",
    ]

    if not report.violations:
        lines.append("\nNo violations — causal chain is intact.")
        return "\n".join(lines)

    errors = [v for v in report.violations if v.severity == "error"]
    warnings = [v for v in report.violations if v.severity == "warning"]

    if errors:
        lines.append("\n## Errors (must fix)")
        for v in errors:
            lines.append(f"- [{v.violation_type}] {v.message}")

    if warnings:
        lines.append("\n## Warnings (should fix)")
        for v in warnings:
            lines.append(f"- [{v.violation_type}] {v.message}")

    if report.chain_coverage < 0.5:
        lines.append(
            f"\n⚠ Chain coverage is {report.chain_coverage:.0%} — "
            "most scenes lack causal links. Fill causal_prerequisite_scene_id."
        )
    if report.cost_coverage < 0.5:
        lines.append(
            f"\n⚠ Cost coverage is {report.cost_coverage:.0%} — "
            "most choices lack a cost. Fill cost_requirement to avoid free-choice drift."
        )

    return "\n".join(lines)
