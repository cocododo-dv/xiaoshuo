"""Tests for event-sourcing reconciliation service.

Verifies drift detection between NarrativeEvent log projections and
entity tables (StoryCharacter, LibraryEntity).
"""
from __future__ import annotations

from novel_system.db.models import (
    ChapterGoal,
    ChapterState,
    LibraryEntity,
    NarrativeEvent,
    ReconcileFault,
    ReviewItem,
    SceneCard,
    StoryCharacter,
    StoryProject,
)
from novel_system.services.event_reconciliation import (
    EventReconciliationService,
)
from novel_system.services.narrative_event_log import NarrativeEventLog


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _seed_project(session) -> None:
    """Create a minimal project with one chapter and two scenes."""
    session.add(StoryProject(
        project_id="PROJ_REC",
        title="Reconciliation Test",
        outline_text="test outline",
    ))
    session.add(ChapterGoal(
        chapter_id="CH_REC01",
        project_id="PROJ_REC",
        planned_scene_count=2,
        chapter_goal="test chapter",
    ))
    session.add(ChapterState(chapter_id="CH_REC01", current_phase="drafting"))
    for seq in (1, 2):
        session.add(SceneCard(
            scene_id=f"CH_REC01_SC0{seq}",
            chapter_id="CH_REC01",
            project_id="PROJ_REC",
            scene_seq=seq,
            scene_goal=f"Scene {seq}",
        ))
    session.commit()


def _add_character(session, character_id: str, *, bible: dict | None = None) -> None:
    """Add a StoryCharacter with optional bible_json."""
    session.add(StoryCharacter(
        character_id=character_id,
        project_id="PROJ_REC",
        display_name=character_id,
        bible_json=bible,
    ))
    session.commit()


def _add_location(session, entity_id: str, *, details: dict | None = None) -> None:
    """Add a LibraryEntity of kind 'location'."""
    session.add(LibraryEntity(
        entity_id=entity_id,
        project_id="PROJ_REC",
        kind="location",
        name=entity_id,
        details_json=details,
    ))
    session.commit()


def _add_item(session, entity_id: str, *, details: dict | None = None) -> None:
    """Add a LibraryEntity of kind 'item'."""
    session.add(LibraryEntity(
        entity_id=entity_id,
        project_id="PROJ_REC",
        kind="item",
        name=entity_id,
        details_json=details,
    ))
    session.commit()


def _log_event(session, **kwargs) -> NarrativeEvent:
    """Shorthand: log a narrative event via NarrativeEventLog."""
    log = NarrativeEventLog(session)
    defaults = dict(
        project_id="PROJ_REC",
        scene_id="CH_REC01_SC01",
        chapter_id="CH_REC01",
        authority_status="accepted",
        source_kind="test_fixture",
    )
    defaults.update(kwargs)
    evt = log.log_event(**defaults)
    session.commit()
    return evt


# ------------------------------------------------------------------
# Tests: no drift
# ------------------------------------------------------------------

def test_no_findings_when_state_matches(session) -> None:
    """Entity table matches event log exactly -> zero findings."""
    _seed_project(session)
    _add_character(session, "CHAR_A", bible={"alive": "true", "location": "city_x"})

    _log_event(
        session,
        event_type="character_state", entity_type="character",
        entity_id="CHAR_A", fact_key="alive", fact_value="true",
    )
    _log_event(
        session,
        event_type="character_state", entity_type="character",
        entity_id="CHAR_A", fact_key="location", fact_value="city_x",
    )

    svc = EventReconciliationService(session)
    findings = svc.reconcile_project("PROJ_REC")
    assert findings == []


def test_no_findings_when_no_events(session) -> None:
    """No events logged at all -> zero findings."""
    _seed_project(session)
    _add_character(session, "CHAR_A", bible={"alive": "true"})

    svc = EventReconciliationService(session)
    findings = svc.reconcile_project("PROJ_REC")
    assert findings == []


def test_no_findings_when_entity_has_no_matching_facts(session) -> None:
    """Event log has facts but entity table JSON has no overlapping keys."""
    _seed_project(session)
    _add_character(session, "CHAR_A", bible={"background": "noble family"})

    _log_event(
        session,
        event_type="character_state", entity_type="character",
        entity_id="CHAR_A", fact_key="location", fact_value="city_x",
    )

    svc = EventReconciliationService(session)
    findings = svc.reconcile_project("PROJ_REC")
    assert findings == []


# ------------------------------------------------------------------
# Tests: character drift
# ------------------------------------------------------------------

def test_character_alive_drift_detected(session) -> None:
    """Event log says dead, entity table says alive -> blocking drift."""
    _seed_project(session)
    _add_character(session, "CHAR_B", bible={"alive": "true"})

    _log_event(
        session,
        event_type="character_state", entity_type="character",
        entity_id="CHAR_B", fact_key="alive", fact_value="dead",
    )

    svc = EventReconciliationService(session)
    findings = svc.reconcile_project("PROJ_REC")
    assert len(findings) == 1
    f = findings[0]
    assert f.entity_type == "character"
    assert f.entity_id == "CHAR_B"
    assert f.fact_key == "alive"
    assert f.severity == "block"
    assert f.event_log_value == "dead"
    assert f.entity_table_value == "true"


def test_character_location_drift_detected(session) -> None:
    """Event log says location changed, entity table is stale -> blocking drift."""
    _seed_project(session)
    _add_character(session, "CHAR_C", bible={"location": "city_old"})

    _log_event(
        session,
        event_type="character_state", entity_type="character",
        entity_id="CHAR_C", fact_key="location", fact_value="city_new",
    )

    svc = EventReconciliationService(session)
    findings = svc.reconcile_project("PROJ_REC")
    assert len(findings) == 1
    assert findings[0].fact_key == "location"
    assert findings[0].severity == "block"


def test_character_advisory_drift(session) -> None:
    """Soft-fact drift (physical_state) gets 'warn' severity."""
    _seed_project(session)
    _add_character(session, "CHAR_D", bible={"physical_state": "healthy"})

    _log_event(
        session,
        event_type="character_state", entity_type="character",
        entity_id="CHAR_D", fact_key="physical_state", fact_value="injured",
    )

    svc = EventReconciliationService(session)
    findings = svc.reconcile_project("PROJ_REC")
    assert len(findings) == 1
    assert findings[0].severity == "warn"
    assert findings[0].fact_key == "physical_state"


# ------------------------------------------------------------------
# Tests: location and item drift
# ------------------------------------------------------------------

def test_location_drift_detected(session) -> None:
    """Location entity table contradicts event log -> finding."""
    _seed_project(session)
    _add_location(session, "LOC_CASTLE", details={"physical_state": "intact"})

    _log_event(
        session,
        event_type="character_state", entity_type="location",
        entity_id="LOC_CASTLE", fact_key="physical_state", fact_value="destroyed",
    )

    svc = EventReconciliationService(session)
    findings = svc.reconcile_project("PROJ_REC")
    assert len(findings) == 1
    assert findings[0].entity_type == "location"
    assert findings[0].entity_id == "LOC_CASTLE"


def test_item_drift_detected(session) -> None:
    """Item entity table contradicts event log -> finding."""
    _seed_project(session)
    _add_item(session, "ITEM_SWORD", details={"has_item": "lost:sword"})

    _log_event(
        session,
        event_type="item_change", entity_type="item",
        entity_id="ITEM_SWORD", fact_key="has_item", fact_value="equipped",
    )

    svc = EventReconciliationService(session)
    findings = svc.reconcile_project("PROJ_REC")
    assert len(findings) == 1
    assert findings[0].entity_type == "item"


# ------------------------------------------------------------------
# Tests: severity classification
# ------------------------------------------------------------------

def test_severity_blocking_vs_advisory(session) -> None:
    """Multiple drifts: blocking and advisory classified correctly."""
    _seed_project(session)
    _add_character(session, "CHAR_E", bible={
        "alive": "true",
        "physical_state": "healthy",
    })

    # Blocking: alive drift
    _log_event(
        session,
        event_type="character_state", entity_type="character",
        entity_id="CHAR_E", fact_key="alive", fact_value="dead",
    )
    # Advisory: physical_state drift
    _log_event(
        session,
        event_type="character_state", entity_type="character",
        entity_id="CHAR_E", fact_key="physical_state", fact_value="wounded",
    )

    svc = EventReconciliationService(session)
    findings = svc.reconcile_project("PROJ_REC")
    assert len(findings) == 2
    severities = {f.fact_key: f.severity for f in findings}
    assert severities["alive"] == "block"
    assert severities["physical_state"] == "warn"


# ------------------------------------------------------------------
# Tests: fault recording and review items
# ------------------------------------------------------------------

def test_faults_persisted_to_db(session) -> None:
    """ReconcileFault rows are created for each drift."""
    _seed_project(session)
    _add_character(session, "CHAR_F", bible={"alive": "true"})

    _log_event(
        session,
        event_type="character_state", entity_type="character",
        entity_id="CHAR_F", fact_key="alive", fact_value="dead",
    )

    svc = EventReconciliationService(session)
    svc.reconcile_project("PROJ_REC")
    session.commit()

    faults = session.query(ReconcileFault).filter_by(fault_scope="event_sourcing").all()
    assert len(faults) == 1
    assert faults[0].severity == "block"
    assert "CHAR_F" in faults[0].object_ref


def test_review_items_created_for_blocking_drifts(session) -> None:
    """When create_review_items=True, blocking drifts push ReviewItem rows."""
    _seed_project(session)
    _add_character(session, "CHAR_G", bible={
        "alive": "true",
        "physical_state": "healthy",
    })

    _log_event(
        session,
        event_type="character_state", entity_type="character",
        entity_id="CHAR_G", fact_key="alive", fact_value="dead",
    )
    _log_event(
        session,
        event_type="character_state", entity_type="character",
        entity_id="CHAR_G", fact_key="physical_state", fact_value="wounded",
    )

    svc = EventReconciliationService(session)
    svc.reconcile_project("PROJ_REC", create_review_items=True)
    session.commit()

    reviews = (
        session.query(ReviewItem)
        .filter_by(item_type="reconciliation_fault")
        .all()
    )
    # Only the blocking drift (alive) should produce a ReviewItem
    assert len(reviews) == 1
    assert "alive" in reviews[0].candidate_text
    assert reviews[0].status == "pending"
    assert reviews[0].project_id == "PROJ_REC"


# ------------------------------------------------------------------
# Tests: alive semantic equivalence
# ------------------------------------------------------------------

def test_alive_semantic_equivalence_no_false_positive(session) -> None:
    """'true' vs 'alive' should NOT be flagged as a conflict."""
    _seed_project(session)
    _add_character(session, "CHAR_H", bible={"alive": "alive"})

    _log_event(
        session,
        event_type="character_state", entity_type="character",
        entity_id="CHAR_H", fact_key="alive", fact_value="true",
    )

    svc = EventReconciliationService(session)
    findings = svc.reconcile_project("PROJ_REC")
    assert findings == []


# ------------------------------------------------------------------
# Tests: up_to_scene_seq filtering
# ------------------------------------------------------------------

def test_up_to_scene_seq_limits_replay(session) -> None:
    """Only events up to the specified scene_seq are considered."""
    _seed_project(session)
    _add_character(session, "CHAR_I", bible={"location": "city_a"})

    # Scene 1: location = city_a (matches entity)
    _log_event(
        session,
        scene_id="CH_REC01_SC01",
        event_type="character_state", entity_type="character",
        entity_id="CHAR_I", fact_key="location", fact_value="city_a",
    )
    # Scene 2: location = city_b (diverges from entity)
    _log_event(
        session,
        scene_id="CH_REC01_SC02",
        event_type="character_state", entity_type="character",
        entity_id="CHAR_I", fact_key="location", fact_value="city_b",
    )

    svc = EventReconciliationService(session)

    # Up to scene 1: should match -> no findings
    findings_s1 = svc.reconcile_project("PROJ_REC", up_to_scene_seq=1)
    assert findings_s1 == []

    # Up to scene 2: should diverge -> one finding
    findings_s2 = svc.reconcile_project("PROJ_REC", up_to_scene_seq=2)
    assert len(findings_s2) == 1
    assert findings_s2[0].event_log_value == "city_b"


# ------------------------------------------------------------------
# Tests: to_dict serialization
# ------------------------------------------------------------------

def test_drift_finding_to_dict(session) -> None:
    """DriftFinding.to_dict produces the expected structure."""
    _seed_project(session)
    _add_character(session, "CHAR_J", bible={"alive": "true"})

    _log_event(
        session,
        event_type="character_state", entity_type="character",
        entity_id="CHAR_J", fact_key="alive", fact_value="dead",
    )

    svc = EventReconciliationService(session)
    findings = svc.reconcile_project("PROJ_REC")
    assert len(findings) == 1
    d = findings[0].to_dict()
    assert d["entity_type"] == "character"
    assert d["entity_id"] == "CHAR_J"
    assert d["fact_key"] == "alive"
    assert d["event_log_value"] == "dead"
    assert d["entity_table_value"] == "true"
    assert d["severity"] == "block"
    assert "scene_seq" in d
