"""0064 遗留关系孤儿诊断（只读）与迁移兼容测试。"""
from __future__ import annotations

import importlib.util
from pathlib import Path

from sqlalchemy import text

from novel_system.db.models import (
    ChapterGoal,
    SceneCard,
    SceneRunState,
    StyleReferenceEvidence,
)
from novel_system.tools import orphan_inventory as oi


def _load_migration():
    path = (
        Path(__file__).resolve().parents[1]
        / "alembic" / "versions" / "20260712_0064_purge_orphans.py"
    )
    spec = importlib.util.spec_from_file_location("mig_0064", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_clean_db_reports_no_orphans(session):
    report = oi.orphan_report(session)
    assert report["clean"] is True
    assert report["total_orphans"] == 0
    assert report["relations_checked"] == len(oi.ORPHAN_RELATIONS)


def test_scan_detects_scene_run_state_orphan(session):
    # SceneRunState.scene_id 指向不存在的 SceneCard（FK 关闭可插）
    session.add(SceneRunState(scene_id="ghost_scene"))
    session.flush()
    found = oi.scan_orphans(session)
    assert "scene_run_states" in found
    assert "ghost_scene" in found["scene_run_states"]


def test_scan_detects_style_reference_evidence_orphan(session):
    session.add(StyleReferenceEvidence(
        evidence_id="ev_orphan", finding_id="ghost_finding", quote_id="q",
        anchor_kind="direct", is_synthetic=0,
    ))
    session.flush()
    found = oi.scan_orphans(session)
    assert "ghost_finding" not in str(found.get("style_reference_evidences", []))  # sanity: id is evidence pk
    assert "ev_orphan" in found.get("style_reference_evidences", [])


def test_valid_rows_not_flagged(session):
    # 建立完整链：ChapterGoal → SceneCard → SceneRunState，皆不应是孤儿
    session.add(ChapterGoal(chapter_id="CH", chapter_goal="g"))
    session.add(SceneCard(scene_id="SC", chapter_id="CH", project_id="P", scene_seq=1, scene_goal="g"))
    session.add(SceneRunState(scene_id="SC"))
    session.flush()
    report = oi.orphan_report(session)
    assert report["clean"] is True


def test_report_counts_and_by_table(session):
    session.add(SceneRunState(scene_id="g1"))
    session.add(SceneRunState(scene_id="g2"))
    session.flush()
    report = oi.orphan_report(session)
    assert report["total_orphans"] == 2
    assert report["by_table"]["scene_run_states"] == 2
    assert report["clean"] is False


def test_scan_fails_closed_when_a_registered_relation_cannot_be_checked(
    session,
    monkeypatch,
):
    original = oi._orphan_ids

    def fail_one_relation(active_session, relation):
        if relation is oi.ORPHAN_RELATIONS[0]:
            raise RuntimeError("simulated missing table")
        return original(active_session, relation)

    monkeypatch.setattr(oi, "_orphan_ids", fail_one_relation)

    try:
        oi.orphan_report(session)
    except oi.OrphanInventoryIncomplete as exc:
        assert "legacy_orphan_scan_incomplete=" in str(exc)
    else:  # pragma: no cover - regression guard
        raise AssertionError("incomplete legacy scan must not report clean")


def test_migration_purges_orphans(session):
    session.add(SceneRunState(scene_id="ghost_scene"))
    session.add(StyleReferenceEvidence(
        evidence_id="ev_orphan", finding_id="ghost_finding", quote_id="q",
        anchor_kind="direct", is_synthetic=0,
    ))
    session.flush()
    assert oi.orphan_report(session)["total_orphans"] == 2

    mig = _load_migration()
    counts = mig.purge_orphans(session.connection())
    session.flush()
    assert sum(counts.values()) >= 2
    # 修复后盘点为空
    assert oi.orphan_report(session)["total_orphans"] == 0
    # 幂等：再删一次 0
    counts2 = mig.purge_orphans(session.connection())
    assert sum(counts2.values()) == 0


def test_migration_keeps_valid_rows(session):
    session.add(ChapterGoal(chapter_id="CH", chapter_goal="g"))
    session.add(SceneCard(scene_id="SC", chapter_id="CH", project_id="P", scene_seq=1, scene_goal="g"))
    session.add(SceneRunState(scene_id="SC"))
    session.flush()
    mig = _load_migration()
    mig.purge_orphans(session.connection())
    session.flush()
    # 有效行不被误删
    assert session.get(SceneRunState, "SC") is not None
    remaining = session.execute(text("SELECT COUNT(*) FROM scene_cards")).scalar()
    assert remaining == 1
