"""Tests for character decision weights & arc tracking — blueprint §11."""
from __future__ import annotations

from novel_system.db.models import SnowflakeCharacterPlan, StoryProject
from novel_system.services.character_arc import CharacterArcService, DecisionWeight


def _seed_character(session) -> None:
    session.add(StoryProject(project_id="ARC01", title="Test", outline_text="test"))
    session.add(SnowflakeCharacterPlan(
        character_plan_id="plan_lin",
        project_id="ARC01",
        character_id="CHAR_LIN",
        display_name="Lin Yuan",
        role="protagonist",
        bible_json={
            "decision_weights": [
                {
                    "situation": "facing_threat",
                    "options": {"fight": 0.7, "endure_alone": 0.2, "ask_for_help": 0.1},
                    "story_phase": "opening",
                },
                {
                    "situation": "facing_threat",
                    "options": {"fight": 0.4, "endure_alone": 0.3, "ask_for_help": 0.3},
                    "story_phase": "climax",
                },
                {
                    "situation": "facing_loss",
                    "options": {"suppress": 0.8, "express": 0.2},
                    "story_phase": "opening",
                },
            ],
        },
    ))
    session.commit()


def test_get_decision_weights(session) -> None:
    _seed_character(session)
    service = CharacterArcService(session)

    weights = service.get_decision_weights("ARC01", "CHAR_LIN")
    assert len(weights) == 3
    assert weights[0].situation == "facing_threat"
    assert weights[0].dominant_option() == "fight"


def test_get_weight_at_phase(session) -> None:
    _seed_character(session)
    service = CharacterArcService(session)

    w = service.get_weight_at_phase("ARC01", "CHAR_LIN", "facing_threat", "climax")
    assert w is not None
    assert w.dominant_option() == "fight"
    assert w.options["ask_for_help"] == 0.3


def test_detect_arc_shifts(session) -> None:
    """Seed a character with fight-dominant opening and help-dominant climax from the start."""
    session.add(StoryProject(project_id="ARC_SHIFT", title="Test", outline_text="test"))
    session.add(SnowflakeCharacterPlan(
        character_plan_id="plan_shift",
        project_id="ARC_SHIFT",
        character_id="CHAR_SHIFT",
        display_name="Shift Test",
        role="protagonist",
        bible_json={
            "decision_weights": [
                {
                    "situation": "facing_threat",
                    "options": {"fight": 0.7, "endure_alone": 0.2, "ask_for_help": 0.1},
                    "story_phase": "1_opening",
                },
                {
                    "situation": "facing_threat",
                    "options": {"fight": 0.2, "endure_alone": 0.2, "ask_for_help": 0.6},
                    "story_phase": "2_climax",
                },
            ],
        },
    ))
    session.commit()

    service = CharacterArcService(session)
    shifts = service.detect_arc_shifts("ARC_SHIFT", "CHAR_SHIFT")
    assert len(shifts) == 1
    assert shifts[0].situation == "facing_threat"
    assert shifts[0].from_dominant == "fight"
    assert shifts[0].to_dominant == "ask_for_help"


def test_set_decision_weights(session) -> None:
    session.add(StoryProject(project_id="ARC02", title="Test", outline_text="test"))
    session.add(SnowflakeCharacterPlan(
        character_plan_id="plan_su",
        project_id="ARC02",
        character_id="CHAR_SU",
        display_name="Su Wan",
        role="deuteragonist",
        bible_json={},
    ))
    session.commit()

    service = CharacterArcService(session)
    service.set_decision_weights("ARC02", "CHAR_SU", [
        {"situation": "trust_test", "options": {"trust": 0.3, "verify": 0.7}, "story_phase": "opening"},
    ])
    session.commit()

    weights = service.get_decision_weights("ARC02", "CHAR_SU")
    assert len(weights) == 1
    assert weights[0].dominant_option() == "verify"


def test_format_weights_for_prompt(session) -> None:
    _seed_character(session)
    service = CharacterArcService(session)

    prompt = service.format_weights_for_prompt("ARC01", "CHAR_LIN", "opening")
    assert prompt is not None
    assert "CHAR_LIN" in prompt
    assert "facing_threat" in prompt
    assert "fight" in prompt


def test_format_weights_none_when_empty(session) -> None:
    session.add(StoryProject(project_id="ARC03", title="Test", outline_text="test"))
    session.add(SnowflakeCharacterPlan(
        character_plan_id="plan_empty",
        project_id="ARC03",
        character_id="CHAR_EMPTY",
        display_name="Empty",
        role="extra",
        bible_json={},
    ))
    session.commit()

    service = CharacterArcService(session)
    assert service.format_weights_for_prompt("ARC03", "CHAR_EMPTY") is None


def test_decision_weight_has_shifted() -> None:
    w1 = DecisionWeight(situation="test", options={"a": 0.7, "b": 0.3}, story_phase="1")
    w2 = DecisionWeight(situation="test", options={"a": 0.3, "b": 0.7}, story_phase="2")
    assert w1.has_shifted(w2) is True

    w3 = DecisionWeight(situation="test", options={"a": 0.6, "b": 0.4}, story_phase="3")
    assert w1.has_shifted(w3) is False  # dominant still "a"
