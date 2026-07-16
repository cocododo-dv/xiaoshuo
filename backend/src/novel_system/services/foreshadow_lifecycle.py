"""Foreshadow lifecycle management — blueprint §5.

Upgrades foreshadow tracking from passive 3-state (open/resolved/closed) to
active lifecycle: Plant → Reinforce → Payoff, with density checks, overdue
detection, pre-planned reinforcement schedules, theme association, and
scene-level action directives.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from novel_system.db.models import ChapterGoal, ForeshadowTracker, SceneCard
from novel_system.services.narrative_position import NarrativePositionService


MAX_PLANTS_PER_SCENE = 3
MAX_SCENES_WITHOUT_PAYOFF = 15
REINFORCE_INTERVAL_SCENES = 5
PLANNED_REINFORCE_TOLERANCE = 1


@dataclass(slots=True)
class ForeshadowAction:
    foreshadow_id: str
    action: str
    text: str
    urgency: str
    reason: str
    method: str | None = None
    theme_tag: str | None = None


@dataclass(slots=True)
class ForeshadowHealthReport:
    scene_id: str
    scene_seq: int
    actions: list[ForeshadowAction] = field(default_factory=list)
    density_warning: str | None = None
    open_count: int = 0
    overdue_count: int = 0
    unresolved_plants: list[dict[str, str | None]] = field(default_factory=list)


@dataclass(slots=True)
class ForeshadowAggregateHealth:
    total_open: int = 0
    with_planned_reinforcement: int = 0
    without_planned_reinforcement: int = 0
    with_theme_tag: int = 0
    without_theme_tag: int = 0
    overdue: list[str] = field(default_factory=list)
    unresolved_plants: list[dict[str, str | None]] = field(default_factory=list)


class ForeshadowLifecycleService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def scene_actions(self, scene_id: str) -> ForeshadowHealthReport:
        """What foreshadow actions should this scene perform?

        Returns reinforcement/payoff directives and density warnings.
        Pre-planned reinforcement points take priority over reactive interval logic.
        """
        scene = self.session.get(SceneCard, scene_id)
        if scene is None:
            return ForeshadowHealthReport(scene_id=scene_id, scene_seq=0)

        scene_seq = scene.scene_seq or 0
        chapter_id = scene.chapter_id
        project_id = self._project_id_for_scene(scene)
        ordered_scene_ordinal_by_id: dict[str, int] | None = None
        current_scene_ordinal: int | None = None
        if project_id is not None:
            ordered_scenes = NarrativePositionService(self.session).ordered_scenes(project_id)
            ordered_scene_ordinal_by_id = {
                positioned_scene.scene_id: ordinal
                for ordinal, positioned_scene in enumerate(ordered_scenes, start=1)
            }
            current_scene_ordinal = ordered_scene_ordinal_by_id.get(scene.scene_id)
            open_foreshadows = self.project_open_foreshadows(project_id)
        else:
            open_foreshadows = self._open_foreshadows(chapter_id)
        report = ForeshadowHealthReport(
            scene_id=scene_id,
            scene_seq=scene_seq,
            open_count=len(open_foreshadows),
        )

        planted_this_scene = self._count_planted_in_scene(scene_id)
        if planted_this_scene >= MAX_PLANTS_PER_SCENE:
            report.density_warning = (
                f"Scene already has {planted_this_scene} foreshadow plants — "
                f"reader absorption limit ({MAX_PLANTS_PER_SCENE}). Do not add more."
            )

        for fs in open_foreshadows:
            if ordered_scene_ordinal_by_id is not None:
                plant_ordinal = ordered_scene_ordinal_by_id.get(fs.scene_id or "")
                if plant_ordinal is None or current_scene_ordinal is None:
                    report.unresolved_plants.append(
                        self._unresolved_plant_diagnostic(fs)
                    )
                    continue
                scenes_since_plant = current_scene_ordinal - plant_ordinal
            else:
                plant_seq = self._plant_scene_seq(fs)
                if plant_seq is None:
                    report.unresolved_plants.append(
                        self._unresolved_plant_diagnostic(fs)
                    )
                    continue
                scenes_since_plant = scene_seq - plant_seq

            # A future plant may already exist in the outline catalog. It is not
            # active narrative history yet and cannot request reinforcement.
            if scenes_since_plant < 0:
                continue

            if scenes_since_plant >= MAX_SCENES_WITHOUT_PAYOFF:
                report.actions.append(ForeshadowAction(
                    foreshadow_id=fs.foreshadow_id,
                    action="payoff",
                    text=fs.text,
                    urgency="high",
                    reason=f"Open for {scenes_since_plant} scenes — reader will forget. Resolve now.",
                    method=fs.payoff_method,
                    theme_tag=fs.theme_tag,
                ))
                report.overdue_count += 1
                continue

            planned_action = self._check_planned_reinforcement(
                fs,
                scene_seq,
                current_chapter_id=chapter_id,
                current_scene_id=scene.scene_id,
                current_scene_ordinal=current_scene_ordinal,
            )
            if planned_action is not None:
                report.actions.append(planned_action)
            elif scenes_since_plant >= REINFORCE_INTERVAL_SCENES and scenes_since_plant % REINFORCE_INTERVAL_SCENES < 2:
                report.actions.append(ForeshadowAction(
                    foreshadow_id=fs.foreshadow_id,
                    action="reinforce",
                    text=fs.text,
                    urgency="medium",
                    reason=f"Open for {scenes_since_plant} scenes — reinforce without revealing.",
                    theme_tag=fs.theme_tag,
                ))

        consecutive_without_payoff = self._consecutive_scenes_without_payoff(chapter_id, scene_seq)
        if consecutive_without_payoff >= 10:
            report.density_warning = (report.density_warning or "") + (
                f" {consecutive_without_payoff} consecutive scenes without any foreshadow payoff — "
                "reader perceives accumulated details as wasted."
            )

        return report

    def format_foreshadow_directives(self, scene_id: str) -> str | None:
        """Format foreshadow lifecycle actions as a prompt section."""
        report = self.scene_actions(scene_id)
        if not report.actions and not report.density_warning and not report.unresolved_plants:
            return None

        lines = ["## Foreshadow Lifecycle Directives"]
        if report.density_warning:
            lines.append(f"WARNING: {report.density_warning}")

        for diagnostic in report.unresolved_plants:
            lines.append(
                "WARNING: unresolved foreshadow plant "
                f"[{diagnostic['foreshadow_id']}] scene={diagnostic['scene_id'] or 'missing'}; "
                "age-based reinforcement was not evaluated."
            )

        for action in report.actions:
            theme_suffix = f" [theme: {action.theme_tag}]" if action.theme_tag else ""
            if action.action == "payoff":
                method_hint = f" — method: {action.method}" if action.method else ""
                lines.append(
                    f"- RESOLVE foreshadow [{action.foreshadow_id}]: \"{action.text}\""
                    f"{method_hint} ({action.urgency} urgency — {action.reason}){theme_suffix}"
                )
            elif action.action == "reinforce":
                method_hint = f" — method: {action.method}" if action.method else ""
                lines.append(
                    f"- REINFORCE foreshadow [{action.foreshadow_id}]: \"{action.text}\""
                    f"{method_hint} (hint without revealing — {action.reason}){theme_suffix}"
                )

        lines.append(f"\nOpen foreshadows: {report.open_count}, Overdue: {report.overdue_count}")
        return "\n".join(lines)

    def health_report(self, chapter_id: str) -> ForeshadowAggregateHealth:
        """Aggregate health stats for all open foreshadows in a chapter."""
        open_foreshadows = self._open_foreshadows(chapter_id)
        report = ForeshadowAggregateHealth(total_open=len(open_foreshadows))

        latest_scene_seq = self._latest_scene_seq(chapter_id)

        for fs in open_foreshadows:
            if fs.reinforce_plan_json:
                report.with_planned_reinforcement += 1
            else:
                report.without_planned_reinforcement += 1

            if fs.theme_tag:
                report.with_theme_tag += 1
            else:
                report.without_theme_tag += 1

            plant_seq = self._plant_scene_seq(fs)
            if plant_seq is not None and latest_scene_seq - plant_seq >= MAX_SCENES_WITHOUT_PAYOFF:
                report.overdue.append(fs.foreshadow_id)

        return report

    def _check_planned_reinforcement(
        self,
        fs: ForeshadowTracker,
        current_scene_seq: int,
        *,
        current_chapter_id: str | None = None,
        current_scene_id: str | None = None,
        current_scene_ordinal: int | None = None,
    ) -> ForeshadowAction | None:
        """Check if any pre-planned reinforcement point matches the current scene."""
        plan = fs.reinforce_plan_json
        if not plan:
            return None
        for entry in plan:
            target_scene_id = str(entry.get("target_scene_id") or "").strip()
            target_scene_ordinal = entry.get("target_scene_ordinal")
            target_chapter_id = str(entry.get("target_chapter_id") or "").strip()
            target_seq = entry.get("target_scene_seq")
            matches = False
            target_label: str | int | None = None
            if target_scene_id:
                matches = target_scene_id == current_scene_id
                target_label = target_scene_id
            elif target_scene_ordinal is not None and current_scene_ordinal is not None:
                if isinstance(target_scene_ordinal, int) and not isinstance(target_scene_ordinal, bool):
                    matches = (
                        abs(current_scene_ordinal - target_scene_ordinal)
                        <= PLANNED_REINFORCE_TOLERANCE
                    )
                    target_label = target_scene_ordinal
            elif target_seq is not None:
                # Legacy scene_seq is chapter-local. Never reinterpret it across
                # chapters unless an explicit target_chapter_id is supplied.
                same_chapter = (
                    target_chapter_id == current_chapter_id
                    if target_chapter_id
                    else fs.chapter_id == current_chapter_id
                )
                if same_chapter and isinstance(target_seq, int) and not isinstance(target_seq, bool):
                    matches = (
                        abs(current_scene_seq - target_seq)
                        <= PLANNED_REINFORCE_TOLERANCE
                    )
                    target_label = target_seq
            if matches:
                return ForeshadowAction(
                    foreshadow_id=fs.foreshadow_id,
                    action="reinforce",
                    text=fs.text,
                    urgency="medium",
                    reason=f"Pre-planned reinforcement at scene {target_label}.",
                    method=entry.get("method"),
                    theme_tag=fs.theme_tag,
                )
        return None

    def _open_foreshadows(self, chapter_id: str) -> list[ForeshadowTracker]:
        return list(self.session.execute(
            select(ForeshadowTracker)
            .where(
                ForeshadowTracker.chapter_id == chapter_id,
                ForeshadowTracker.tracker_status == "open",
                ForeshadowTracker.active_flag == 1,
            )
            .order_by(ForeshadowTracker.created_at.asc())
        ).scalars().all())

    def _project_id_for_scene(self, scene: SceneCard) -> str | None:
        if scene.project_id:
            return scene.project_id
        chapter = self.session.get(ChapterGoal, scene.chapter_id)
        return chapter.project_id if chapter is not None else None

    @staticmethod
    def _unresolved_plant_diagnostic(
        fs: ForeshadowTracker,
    ) -> dict[str, str | None]:
        return {
            "code": "FORESHADOW_PLANT_SCENE_UNRESOLVED",
            "foreshadow_id": fs.foreshadow_id,
            "scene_id": fs.scene_id,
            "reason": "plant scene is missing from the active project narrative catalog",
        }

    def _plant_scene_seq(self, fs: ForeshadowTracker) -> int | None:
        if fs.scene_id is None:
            return None
        scene = self.session.get(SceneCard, fs.scene_id)
        return scene.scene_seq if scene else None

    def _count_planted_in_scene(self, scene_id: str) -> int:
        return self.session.execute(
            select(func.count())
            .select_from(ForeshadowTracker)
            .where(
                ForeshadowTracker.scene_id == scene_id,
                ForeshadowTracker.active_flag == 1,
            )
        ).scalar() or 0

    def _consecutive_scenes_without_payoff(self, chapter_id: str, current_seq: int) -> int:
        resolved_scene_ids = set(self.session.execute(
            select(ForeshadowTracker.scene_id)
            .where(
                ForeshadowTracker.chapter_id == chapter_id,
                ForeshadowTracker.tracker_status == "resolved",
                ForeshadowTracker.scene_id.isnot(None),
            )
        ).scalars().all())

        scenes = self.session.execute(
            select(SceneCard)
            .where(
                SceneCard.chapter_id == chapter_id,
                SceneCard.trashed_flag == 0,
                SceneCard.scene_seq <= current_seq,
            )
            .order_by(SceneCard.scene_seq.desc())
        ).scalars().all()

        count = 0
        for scene in scenes:
            if scene.scene_id in resolved_scene_ids:
                break
            count += 1
        return count

    def _latest_scene_seq(self, chapter_id: str) -> int:
        result = self.session.execute(
            select(func.max(SceneCard.scene_seq))
            .where(SceneCard.chapter_id == chapter_id, SceneCard.trashed_flag == 0)
        ).scalar()
        return result or 0

    # ------------------------------------------------------------------
    # Blueprint §5: Reverse Foreshadow Generation
    # ------------------------------------------------------------------
    def create_retroactive_foreshadow(
        self,
        chapter_id: str,
        *,
        text: str,
        payoff_scene_id: str,
        target_plant_range: tuple[int, int],
        plant_method: str | None = None,
        payoff_method: str | None = None,
        reinforce_plan: list[dict[str, Any]] | None = None,
        theme_tag: str | None = None,
    ) -> ForeshadowTracker:
        """Blueprint §5 reverse foreshadow: post-hoc 'go back and plant a hint'.

        When later planning discovers 'this payoff needs earlier support',
        mark where in the scene range (target_plant_range) a hint should be
        inserted, along with optional reinforcement points.

        In a write-then-publish workflow this enables going back to add
        foreshadowing after the overall structure is clear.

        Args:
            chapter_id: the chapter context
            text: what the foreshadow is about (the thing to hint at)
            payoff_scene_id: the scene where this foreshadow pays off
            target_plant_range: (min_scene_seq, max_scene_seq) where the plant should go
            plant_method: how to plant the hint
            payoff_method: how the payoff should manifest
            reinforce_plan: optional pre-planned reinforcement points
            theme_tag: theme association
        """
        import uuid

        foreshadow_id = f"fs_retro_{uuid.uuid4().hex[:12]}"

        # Find the best scene in the target range that exists
        plant_scene = self.session.execute(
            select(SceneCard)
            .where(
                SceneCard.chapter_id == chapter_id,
                SceneCard.trashed_flag == 0,
                SceneCard.scene_seq >= target_plant_range[0],
                SceneCard.scene_seq <= target_plant_range[1],
            )
            .order_by(SceneCard.scene_seq.asc())
        ).scalars().first()

        tracker = ForeshadowTracker(
            row_id=f"foreshadow_tracker_{foreshadow_id}_v1",
            foreshadow_id=foreshadow_id,
            chapter_id=chapter_id,
            scene_id=plant_scene.scene_id if plant_scene else None,
            text=text,
            tracker_status="retroactive_pending",
            plant_method=plant_method or "Retroactive: needs insertion during revision pass",
            payoff_method=payoff_method,
            reinforce_plan_json=reinforce_plan or [],
            theme_tag=theme_tag,
            active_flag=1,
        )
        self.session.add(tracker)
        self.session.flush()
        return tracker

    def pending_retroactive_foreshadows(self, chapter_id: str) -> list[ForeshadowTracker]:
        """List all retroactive foreshadows awaiting insertion."""
        return list(self.session.execute(
            select(ForeshadowTracker)
            .where(
                ForeshadowTracker.chapter_id == chapter_id,
                ForeshadowTracker.tracker_status == "retroactive_pending",
                ForeshadowTracker.active_flag == 1,
            )
            .order_by(ForeshadowTracker.created_at.asc())
        ).scalars().all())

    def mark_retroactive_planted(self, foreshadow_id: str, planted_scene_id: str) -> None:
        """Mark a retroactive foreshadow as successfully planted during revision."""
        tracker = self.session.execute(
            select(ForeshadowTracker)
            .where(
                ForeshadowTracker.foreshadow_id == foreshadow_id,
                ForeshadowTracker.active_flag == 1,
            )
        ).scalars().first()
        if tracker is None:
            return
        tracker.tracker_status = "open"
        tracker.scene_id = planted_scene_id
        self.session.flush()

    # ------------------------------------------------------------------
    # Blueprint §5: Cross-chapter (project-level) foreshadow management
    # ------------------------------------------------------------------

    def project_open_foreshadows(self, project_id: str) -> list[ForeshadowTracker]:
        """All open foreshadows across the entire project — cross-chapter lifecycle.

        Blueprint §5 implies book-wide foreshadow management: plant in ch3,
        reinforce in ch8, payoff in ch15. This method enables that query.
        """
        return list(self.session.execute(
            select(ForeshadowTracker)
            .outerjoin(ChapterGoal, ChapterGoal.chapter_id == ForeshadowTracker.chapter_id)
            .where(
                or_(
                    ForeshadowTracker.project_id == project_id,
                    and_(
                        ForeshadowTracker.project_id.is_(None),
                        ChapterGoal.project_id == project_id,
                    ),
                ),
                ForeshadowTracker.tracker_status == "open",
                ForeshadowTracker.active_flag == 1,
            )
            .order_by(ForeshadowTracker.created_at.asc())
        ).scalars().all())

    def project_health_report(self, project_id: str) -> ForeshadowAggregateHealth:
        """Aggregate health across all chapters in a project.

        Reports on total open foreshadows, reinforcement coverage, theme
        tag coverage, and overdue items across the entire book.
        """
        open_foreshadows = self.project_open_foreshadows(project_id)
        report = ForeshadowAggregateHealth(total_open=len(open_foreshadows))
        ordered_scenes = NarrativePositionService(self.session).ordered_scenes(project_id)
        scene_ordinal_by_id = {
            scene.scene_id: ordinal
            for ordinal, scene in enumerate(ordered_scenes, start=1)
        }
        latest_scene_ordinal = len(ordered_scenes)

        for fs in open_foreshadows:
            if fs.reinforce_plan_json:
                report.with_planned_reinforcement += 1
            else:
                report.without_planned_reinforcement += 1

            if fs.theme_tag:
                report.with_theme_tag += 1
            else:
                report.without_theme_tag += 1

            plant_ordinal = scene_ordinal_by_id.get(fs.scene_id or "")
            if plant_ordinal is None:
                # Broken/trashed legacy references remain visible in aggregate
                # coverage but cannot be assigned a trustworthy age. Surface
                # that uncertainty instead of presenting the item as healthy.
                report.unresolved_plants.append(
                    self._unresolved_plant_diagnostic(fs)
                )
                continue
            if latest_scene_ordinal - plant_ordinal >= MAX_SCENES_WITHOUT_PAYOFF:
                report.overdue.append(fs.foreshadow_id)

        return report
