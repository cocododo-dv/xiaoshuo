from __future__ import annotations

from copy import deepcopy

from novel_system.db.models import ChapterGoal, SceneCard, SceneRunState, StyleObservation
from novel_system.services.bundle_builder import BundleBuilder
from novel_system.services.prompt_builder import PromptBuilder, PromptConfigurationError, load_prompt_templates


def _bundle_snapshot() -> dict:
    return {
        "contract_version": "BSHASH_v1",
        "stage_allowlist_name": "bundle_build_allowlist_v1",
        "scene_id": "CH001_SC01",
        "chapter_id": "CH001",
        "source_version_refs": {
            "chapter_goal": "CH001",
            "scene_card": "CH001_SC01",
            "style_observation_ids": ["STY_SCENE_01", "STY_SCENE_02"],
        },
        "resolved_ref_ids": {
            "relation_ids": ["REL_A_B"],
            "world_rule_ids": ["WR_GLOBAL_014"],
            "open_foreshadow_ids": ["F014"],
        },
        "ordered_injections": [
            {"slot": "chapter_goal", "ref_id": "CH001", "digest_key": "chapter_goal"},
            {"slot": "scene_card", "ref_id": "CH001_SC01", "digest_key": "scene_card"},
            {"slot": "style_observations", "ref_id": "STY_SCENE_01", "digest_key": "style_observation"},
        ],
        "inline_digests": {
            "chapter_goal": "Close the reunion chapter with a traceable reveal.",
            "scene_card": "Reunite the leads and turn the old letter into immediate action.",
            "voice_card": "Short clipped lines; pressure makes the tone harder.",
            "style_rule": "Keep emotion in gesture and pause.",
            "banned_rule": "Do not explain the whole backstory at reunion time.",
            "style_observation": (
                "Gesture before explanation. Let silence carry accusation. "
                "End paragraphs on pressure, not exposition. Keep the emotional turn tactile."
            ),
            "calibration_line": "The door closed like a sentence left unfinished.",
            "relation_card": "Reunion tension; B knows slightly more than A.",
            "world_rule": "Public spellcasting inside the city is forbidden.",
            "foreshadow": "The old letter sender clue is now in play.",
            "scene_memory": "Previous scene memory digest about the hidden sender.",
            "scene_summary": "Current scene summary digest about the reunion beat.",
            "chapter_summary": "Chapter summary digest about guarded trust replacing suspicion.",
            "similar_scene": (
                "Similar-scene reference: another gate reunion leaned too heavily on explanation "
                "and lost pressure halfway through."
            ),
        },
    }


def test_prompt_builder_includes_required_sections_and_stable_hash() -> None:
    builder = PromptBuilder()
    snapshot = _bundle_snapshot()

    payload = builder.build(snapshot, "neutral_draft")
    repeated = builder.build(deepcopy(snapshot), "neutral_draft")

    assert payload["template_name"] == "neutral_draft"
    assert payload["system_prompt"]
    assert payload["structured_schema"]["type"] == "object"
    assert "Chapter Goal" in payload["user_prompt"]
    assert "Scene Card" in payload["user_prompt"]
    assert "POV Voice" in payload["user_prompt"]
    assert "Style Rules" in payload["user_prompt"]
    assert "Open Foreshadow" in payload["user_prompt"]
    assert "Close the reunion chapter with a traceable reveal." in payload["user_prompt"]
    assert "Reunite the leads and turn the old letter into immediate action." in payload["user_prompt"]
    assert payload["prompt_hash"] == repeated["prompt_hash"]
    assert payload["token_budget"]["compressed_sections"] == []
    assert payload["token_budget"]["omitted_sections"] == []
    assert "chapter_goal" in payload["token_budget"]["included_sections"]
    assert payload["token_budget"]["split_scene_recommended"] is False


def test_prompt_builder_hash_changes_only_for_relevant_inputs() -> None:
    builder = PromptBuilder()
    baseline_snapshot = _bundle_snapshot()
    irrelevant_change = deepcopy(baseline_snapshot)
    relevant_change = deepcopy(baseline_snapshot)

    irrelevant_change["source_version_refs"]["debug_timestamp"] = "2026-04-14T21:00:00Z"
    relevant_change["inline_digests"]["scene_card"] = "The leads reunite, but the letter clue stays buried."

    baseline = builder.build(baseline_snapshot, "neutral_draft")
    same_hash = builder.build(irrelevant_change, "neutral_draft")
    changed_hash = builder.build(relevant_change, "neutral_draft")

    assert baseline["prompt_hash"] == same_hash["prompt_hash"]
    assert baseline["prompt_hash"] != changed_hash["prompt_hash"]


def test_prompt_builder_enforces_budget_using_rendered_prompt_shape() -> None:
    builder = PromptBuilder()
    snapshot = _bundle_snapshot()

    baseline = builder.build(snapshot, "neutral_draft")
    threshold = baseline["token_budget"]["estimated_input_tokens"] - 1

    payload = builder.build(snapshot, "neutral_draft", max_input_tokens=threshold)

    assert payload["token_budget"]["estimated_input_tokens"] <= threshold
    assert payload["token_budget"]["section_status"]["similar_scene_context"]["status"] == "omitted"


def test_prompt_builder_applies_continuity_compaction_order_and_split_scene_recommendation() -> None:
    builder = PromptBuilder()
    snapshot = _bundle_snapshot()
    snapshot["inline_digests"]["chapter_goal"] = " ".join(["Goal pressure"] * 80)
    snapshot["inline_digests"]["scene_card"] = " ".join(["Scene pressure"] * 80)

    payload = builder.build(snapshot, "neutral_draft", max_input_tokens=120)
    budget = payload["token_budget"]

    assert budget["section_status"]["similar_scene_context"]["status"] == "omitted"
    assert budget["section_status"]["style_observations"]["status"] == "compressed"
    assert budget["section_status"]["calibration_lines"]["status"] == "included"
    assert budget["section_status"]["relation_digest"]["status"] == "included"
    assert budget["section_status"]["world_rules"]["status"] == "included"
    assert budget["section_status"]["scene_memory_digest"]["status"] == "included"
    assert budget["section_status"]["scene_summary"]["status"] == "included"
    assert budget["section_status"]["chapter_summary"]["status"] == "included"
    assert budget["split_scene_recommended"] is True
    assert budget["stop_reason"] == "split_scene_recommended"
    assert "Similar Scene Context" not in payload["user_prompt"]
    assert "The door closed like a sentence left unfinished." in payload["user_prompt"]
    assert "## Scene Summary" in payload["user_prompt"]
    assert "## Chapter Summary" in payload["user_prompt"]


def test_prompt_builder_returns_isolated_schema_copies() -> None:
    builder = PromptBuilder()
    snapshot = _bundle_snapshot()

    original = builder.build(snapshot, "neutral_draft")
    original_hash = original["prompt_hash"]
    original["structured_schema"]["required"].append("mutated_field")
    original["structured_schema"]["properties"]["scene_text"]["type"] = "array"

    repeated = builder.build(snapshot, "neutral_draft")

    assert repeated["prompt_hash"] == original_hash
    assert repeated["structured_schema"]["required"] == ["scene_text"]
    assert repeated["structured_schema"]["properties"]["scene_text"]["type"] == "string"


def test_chapter_summary_schema_requires_carry_forward() -> None:
    payload = PromptBuilder().build(_bundle_snapshot(), "chapter_summary")

    assert payload["structured_schema"]["required"] == ["summary", "carry_forward"]


def test_load_prompt_templates_rejects_invalid_config(tmp_path) -> None:
    missing_field_path = tmp_path / "prompts_missing.yaml"
    missing_field_path.write_text(
        """
templates:
  neutral_draft:
    version: "2026-04-14.v1"
    input_token_budget: 2600
    system_prompt: "system"
    structured_schema: {}
""".strip(),
        encoding="utf-8",
    )

    wrong_type_path = tmp_path / "prompts_wrong_type.yaml"
    wrong_type_path.write_text(
        """
templates:
  neutral_draft:
    version: 20260414
    input_token_budget: "2600"
    system_prompt: "system"
    task_prompt: "task"
    structured_schema: {}
""".strip(),
        encoding="utf-8",
    )

    try:
        load_prompt_templates(missing_field_path)
    except PromptConfigurationError as exc:
        assert str(exc) == "template neutral_draft is missing required fields: task_prompt"
    else:
        raise AssertionError("expected missing-field prompt config to be rejected")

    try:
        load_prompt_templates(wrong_type_path)
    except PromptConfigurationError as exc:
        assert str(exc) == "template neutral_draft.version must be a string"
    else:
        raise AssertionError("expected wrong-type prompt config to be rejected")


def test_load_prompt_templates_rejects_invalid_structured_schema_shape(tmp_path) -> None:
    invalid_schema_path = tmp_path / "prompts_invalid_schema.yaml"
    invalid_schema_path.write_text(
        """
templates:
  neutral_draft:
    version: "2026-04-14.v1"
    input_token_budget: 2600
    system_prompt: "system"
    task_prompt: "task"
    structured_schema:
      type: array
      properties: []
      required: scene_text
""".strip(),
        encoding="utf-8",
    )

    try:
        load_prompt_templates(invalid_schema_path)
    except PromptConfigurationError as exc:
        assert str(exc) == "template neutral_draft.structured_schema.type must be 'object'"
    else:
        raise AssertionError("expected invalid structured_schema shape to be rejected")


def test_load_prompt_templates_rejects_unsupported_structured_schema_type(tmp_path) -> None:
    invalid_schema_path = tmp_path / "prompts_invalid_schema_type.yaml"
    invalid_schema_path.write_text(
        """
templates:
  neutral_draft:
    version: "2026-04-14.v1"
    input_token_budget: 2600
    system_prompt: "system"
    task_prompt: "task"
    structured_schema:
      type: object
      additionalProperties: false
      required:
        - scene_text
      properties:
        scene_text:
          type: dictionary
""".strip(),
        encoding="utf-8",
    )

    try:
        load_prompt_templates(invalid_schema_path)
    except PromptConfigurationError as exc:
        assert str(exc) == (
            "template neutral_draft.structured_schema.properties.scene_text.type "
            "has unsupported value dictionary"
        )
    else:
        raise AssertionError("expected unsupported structured_schema type to be rejected")


def test_load_prompt_templates_rejects_required_fields_missing_from_properties_when_closed(tmp_path) -> None:
    invalid_schema_path = tmp_path / "prompts_invalid_required.yaml"
    invalid_schema_path.write_text(
        """
templates:
  neutral_draft:
    version: "2026-04-14.v1"
    input_token_budget: 2600
    system_prompt: "system"
    task_prompt: "task"
    structured_schema:
      type: object
      additionalProperties: false
      required:
        - scene_text
        - continuity_notes
      properties:
        scene_text:
          type: string
""".strip(),
        encoding="utf-8",
    )

    try:
        load_prompt_templates(invalid_schema_path)
    except PromptConfigurationError as exc:
        assert str(exc) == (
            "template neutral_draft.structured_schema.required contains entries not declared in properties: "
            "continuity_notes"
        )
    else:
        raise AssertionError("expected closed-schema required/property mismatch to be rejected")


def test_bundle_builder_adds_style_observation_digest_to_snapshot(session) -> None:
    session.add(
        ChapterGoal(
            chapter_id="CH900",
            planned_scene_count=1,
            chapter_goal="Hold the pressure at the city gate.",
        )
    )
    session.add(
        SceneCard(
            scene_id="CH900_SC01",
            chapter_id="CH900",
            scene_seq=1,
            onstage_chars_json=[],
            scene_goal="Reunite the leads at the gate.",
        )
    )
    session.add(SceneRunState(scene_id="CH900_SC01"))
    session.add(
        StyleObservation(
            row_id="style_observation_STY_GATE_v1",
            style_observation_id="STY_GATE",
            scope="global",
            scope_ref_id="global",
            text="Gesture before explanation at reunion moments.",
            active_flag=1,
            runtime_eligible=1,
            created_at="2026-04-14T00:00:00+00:00",
        )
    )
    session.add(
        StyleObservation(
            row_id="style_observation_STY_ALPHA_v1",
            style_observation_id="STY_ALPHA",
            scope="global",
            scope_ref_id="global",
            text="Let pauses land before exposition.",
            active_flag=1,
            runtime_eligible=1,
            created_at="2026-04-14T00:00:00+00:00",
        )
    )
    session.commit()

    payload = BundleBuilder(session).build("CH900_SC01")
    snapshot = payload["snapshot"]

    assert snapshot["source_version_refs"]["style_observation_ids"] == ["STY_ALPHA", "STY_GATE"]
    assert snapshot["inline_digests"]["style_observation"] == (
        "Let pauses land before exposition.\n\nGesture before explanation at reunion moments."
    )
    assert {
        item["digest_key"]
        for item in snapshot["ordered_injections"]
    } >= {"chapter_goal", "scene_card", "style_observation"}
