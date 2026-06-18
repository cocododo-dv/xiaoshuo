"""Tests for foreshadow lifecycle management — blueprint §5."""
from __future__ import annotations

from novel_system.db.models import (
    ChapterGoal,
    ChapterState,
    ForeshadowTracker,
    SceneCard,
)
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


def _add_foreshadow(session, *, foreshadow_id: str, chapter_id: str, scene_id: str, status: str = "open") -> None:
    session.add(ForeshadowTracker(
        row_id=f"fs_row_{foreshadow_id}",
        foreshadow_id=foreshadow_id,
        chapter_id=chapter_id,
        scene_id=scene_id,
        text=f"Foreshadow: {foreshadow_id}",
        tracker_status=status,
        active_flag=1,
        runtime_eligible=1,
        runtime_eligibility_basis="direct_read",
    ))
    session.flush()


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
