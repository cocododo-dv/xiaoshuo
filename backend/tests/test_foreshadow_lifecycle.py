"""Tests for foreshadow lifecycle management — blueprint §5."""
from __future__ import annotations

from novel_system.db.models import (
    ChapterGoal,
    ChapterState,
    ForeshadowTracker,
    SceneCard,
    StoryProject,
)
from novel_system.services.catalog import CatalogService
from novel_system.services.foreshadow_lifecycle import (
    ForeshadowLifecycleService,
    MAX_PLANTS_PER_SCENE,
    MAX_SCENES_WITHOUT_PAYOFF,
    REINFORCE_INTERVAL_SCENES,
)


def _seed_chapter_with_scenes(session, *, n_scenes: int = 20) -> str:
    chapter_id = "FS100"
    session.add(ChapterGoal(chapter_id=chapter_id, planned_scene_count=n_scenes, chapter_goal="test"))
    session.add(ChapterState(chapter_id=chapter_id, current_phase="drafting"))
    for seq in range(1, n_scenes + 1):
        session.add(SceneCard(
            scene_id=f"{chapter_id}_SC{seq:02d}",
            chapter_id=chapter_id,
            scene_seq=seq,
            scene_goal=f"Scene {seq}",
        ))
    session.commit()
    return chapter_id


def _seed_project_with_repeating_scene_sequences(
    session,
    *,
    project_id: str = "FS_PROJECT",
) -> tuple[ChapterGoal, ChapterGoal]:
    chapters = (
        ChapterGoal(
            chapter_id="FS_PROJECT_CH_A",
            project_id=project_id,
            display_order=1,
            planned_scene_count=8,
            chapter_goal="first chapter",
        ),
        ChapterGoal(
            chapter_id="FS_PROJECT_CH_B",
            project_id=project_id,
            display_order=2,
            planned_scene_count=8,
            chapter_goal="second chapter",
        ),
    )
    session.add(
        StoryProject(
            project_id=project_id,
            title="Foreshadow project",
            outline_text="Two chapters used to verify project-wide foreshadow order.",
        )
    )
    session.flush()
    session.add_all(chapters)
    session.flush()
    for chapter in chapters:
        for scene_seq in range(1, 9):
            session.add(
                SceneCard(
                    scene_id=f"{chapter.chapter_id}_SC{scene_seq:02d}",
                    chapter_id=chapter.chapter_id,
                    project_id=project_id,
                    scene_seq=scene_seq,
                    scene_goal=f"Scene {scene_seq}",
                )
            )
    session.flush()
    return chapters


def _add_foreshadow(
    session,
    *,
    foreshadow_id: str,
    chapter_id: str,
    scene_id: str,
    status: str = "open",
    project_id: str | None = None,
) -> ForeshadowTracker:
    tracker = ForeshadowTracker(
        row_id=f"fs_row_{foreshadow_id}",
        foreshadow_id=foreshadow_id,
        project_id=project_id,
        chapter_id=chapter_id,
        scene_id=scene_id,
        text=f"Foreshadow: {foreshadow_id}",
        tracker_status=status,
        active_flag=1,
        runtime_eligible=1,
        runtime_eligibility_basis="direct_read",
    )
    session.add(tracker)
    session.flush()
    return tracker


def test_overdue_foreshadow_triggers_payoff_action(session) -> None:
    _seed_chapter_with_scenes(session)
    _add_foreshadow(session, foreshadow_id="FS001", chapter_id="FS100", scene_id="FS100_SC01")
    session.commit()

    service = ForeshadowLifecycleService(session)
    report = service.scene_actions(f"FS100_SC{MAX_SCENES_WITHOUT_PAYOFF + 1:02d}")

    payoff_actions = [a for a in report.actions if a.action == "payoff"]
    assert len(payoff_actions) == 1
    assert payoff_actions[0].foreshadow_id == "FS001"
    assert payoff_actions[0].urgency == "high"
    assert report.overdue_count == 1


def test_reinforce_triggered_at_interval(session) -> None:
    _seed_chapter_with_scenes(session)
    _add_foreshadow(session, foreshadow_id="FS002", chapter_id="FS100", scene_id="FS100_SC01")
    session.commit()

    service = ForeshadowLifecycleService(session)
    target_seq = 1 + REINFORCE_INTERVAL_SCENES
    report = service.scene_actions(f"FS100_SC{target_seq:02d}")

    reinforce_actions = [a for a in report.actions if a.action == "reinforce"]
    assert len(reinforce_actions) >= 1
    assert reinforce_actions[0].foreshadow_id == "FS002"


def test_no_actions_for_fresh_foreshadow(session) -> None:
    _seed_chapter_with_scenes(session)
    _add_foreshadow(session, foreshadow_id="FS003", chapter_id="FS100", scene_id="FS100_SC01")
    session.commit()

    service = ForeshadowLifecycleService(session)
    report = service.scene_actions("FS100_SC02")

    assert report.actions == []
    assert report.open_count == 1


def test_density_warning_too_many_plants(session) -> None:
    _seed_chapter_with_scenes(session)
    for i in range(MAX_PLANTS_PER_SCENE + 1):
        _add_foreshadow(session, foreshadow_id=f"FS_DENSE_{i}", chapter_id="FS100", scene_id="FS100_SC05")
    session.commit()

    service = ForeshadowLifecycleService(session)
    report = service.scene_actions("FS100_SC05")

    assert report.density_warning is not None
    assert "absorption limit" in report.density_warning


def test_resolved_foreshadow_not_in_actions(session) -> None:
    _seed_chapter_with_scenes(session)
    _add_foreshadow(session, foreshadow_id="FS_RESOLVED", chapter_id="FS100", scene_id="FS100_SC01", status="resolved")
    session.commit()

    service = ForeshadowLifecycleService(session)
    report = service.scene_actions("FS100_SC18")

    assert report.open_count == 0
    assert report.actions == []


def test_format_foreshadow_directives(session) -> None:
    _seed_chapter_with_scenes(session)
    _add_foreshadow(session, foreshadow_id="FS_FMT", chapter_id="FS100", scene_id="FS100_SC01")
    session.commit()

    service = ForeshadowLifecycleService(session)
    directives = service.format_foreshadow_directives(f"FS100_SC{MAX_SCENES_WITHOUT_PAYOFF + 1:02d}")

    assert directives is not None
    assert "RESOLVE" in directives
    assert "FS_FMT" in directives


def test_consecutive_without_payoff_detection(session) -> None:
    _seed_chapter_with_scenes(session)
    _add_foreshadow(session, foreshadow_id="FS_OLD", chapter_id="FS100", scene_id="FS100_SC01")
    session.commit()

    service = ForeshadowLifecycleService(session)
    report = service.scene_actions("FS100_SC15")

    # §5 回收荒漠: 15 scenes deep with zero payoffs MUST raise the warning.
    # (Previously guarded by `if report.density_warning:` — a no-op assertion that
    # passed whether or not the check fired. Made it actually falsifiable.)
    assert report.density_warning is not None, "consecutive-no-payoff warning did not fire"
    assert "without any foreshadow payoff" in report.density_warning


def test_project_health_counts_scene_distance_across_chapters(session) -> None:
    project_id = "FS_PROJECT"
    first_chapter, _second_chapter = _seed_project_with_repeating_scene_sequences(
        session,
        project_id=project_id,
    )
    _add_foreshadow(
        session,
        foreshadow_id="FS_CROSS_CHAPTER",
        project_id=project_id,
        chapter_id=first_chapter.chapter_id,
        scene_id=f"{first_chapter.chapter_id}_SC01",
    )
    session.commit()

    report = ForeshadowLifecycleService(session).project_health_report(project_id)

    # Both chapters restart scene_seq at 1. The planted scene is nevertheless
    # fifteen canonical scene positions behind the project tail.
    assert report.overdue == ["FS_CROSS_CHAPTER"]


def test_project_health_recomputes_overdue_after_chapter_reorder(session) -> None:
    project_id = "FS_PROJECT"
    first_chapter, second_chapter = _seed_project_with_repeating_scene_sequences(
        session,
        project_id=project_id,
    )
    tracker = _add_foreshadow(
        session,
        foreshadow_id="FS_REORDER",
        project_id=project_id,
        chapter_id=first_chapter.chapter_id,
        scene_id=f"{first_chapter.chapter_id}_SC01",
    )
    session.commit()
    tracker_identity = (
        tracker.row_id,
        tracker.chapter_id,
        tracker.scene_id,
        tracker.tracker_status,
    )
    service = ForeshadowLifecycleService(session)

    assert service.project_health_report(project_id).overdue == ["FS_REORDER"]

    CatalogService(session).reorder_chapters(
        project_id,
        [second_chapter.chapter_id, first_chapter.chapter_id],
    )
    session.commit()

    assert service.project_health_report(project_id).overdue == []
    session.refresh(tracker)
    assert (
        tracker.row_id,
        tracker.chapter_id,
        tracker.scene_id,
        tracker.tracker_status,
    ) == tracker_identity


def test_project_health_conservatively_ignores_unresolvable_plant_scene(session) -> None:
    project_id = "FS_PROJECT"
    first_chapter, _second_chapter = _seed_project_with_repeating_scene_sequences(
        session,
        project_id=project_id,
    )
    _add_foreshadow(
        session,
        foreshadow_id="FS_MISSING_PLANT",
        project_id=project_id,
        chapter_id=first_chapter.chapter_id,
        scene_id="FS_PROJECT_SCENE_DOES_NOT_EXIST",
    )
    session.commit()

    report = ForeshadowLifecycleService(session).project_health_report(project_id)

    assert report.total_open == 1
    assert report.without_planned_reinforcement == 1
    assert report.overdue == []
    assert report.unresolved_plants == [
        {
            "code": "FORESHADOW_PLANT_SCENE_UNRESOLVED",
            "foreshadow_id": "FS_MISSING_PLANT",
            "scene_id": "FS_PROJECT_SCENE_DOES_NOT_EXIST",
            "reason": "plant scene is missing from the active project narrative catalog",
        }
    ]


def test_scene_actions_carry_open_foreshadow_across_chapter_boundary(session) -> None:
    project_id = "FS_PROJECT"
    first_chapter, second_chapter = _seed_project_with_repeating_scene_sequences(
        session,
        project_id=project_id,
    )
    # Exercise the legacy rows created before project_id was consistently set:
    # membership must be derived from the authoritative chapter catalog.
    _add_foreshadow(
        session,
        foreshadow_id="FS_CROSS_CHAPTER_ACTION",
        project_id=None,
        chapter_id=first_chapter.chapter_id,
        scene_id=f"{first_chapter.chapter_id}_SC01",
    )
    session.commit()

    report = ForeshadowLifecycleService(session).scene_actions(
        f"{second_chapter.chapter_id}_SC08"
    )

    payoff_actions = [action for action in report.actions if action.action == "payoff"]
    assert [action.foreshadow_id for action in payoff_actions] == [
        "FS_CROSS_CHAPTER_ACTION"
    ]
    assert report.open_count == 1
    assert report.overdue_count == 1


def test_legacy_local_reinforcement_sequence_does_not_match_another_chapter(session) -> None:
    project_id = "FS_PROJECT"
    first_chapter, second_chapter = _seed_project_with_repeating_scene_sequences(
        session,
        project_id=project_id,
    )
    tracker = _add_foreshadow(
        session,
        foreshadow_id="FS_LOCAL_PLAN",
        project_id=project_id,
        chapter_id=first_chapter.chapter_id,
        scene_id=f"{first_chapter.chapter_id}_SC01",
    )
    tracker.reinforce_plan_json = [{"target_scene_seq": 2, "method": "legacy local"}]
    session.commit()

    report = ForeshadowLifecycleService(session).scene_actions(
        f"{second_chapter.chapter_id}_SC02"
    )

    assert not any(
        action.foreshadow_id == "FS_LOCAL_PLAN"
        and action.reason.startswith("Pre-planned")
        for action in report.actions
    )
