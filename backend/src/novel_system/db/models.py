from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, CheckConstraint, Computed, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from novel_system.db.base import Base


def utcnow() -> str:
    return datetime.now(UTC).isoformat()


class ChapterGoal(Base):
    __tablename__ = "chapter_goals"

    chapter_id: Mapped[str] = mapped_column(String, primary_key=True)
    planned_scene_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    mid_aggregate_enabled: Mapped[int] = mapped_column(Integer, default=0)
    chapter_goal: Mapped[str] = mapped_column(Text)
    main_plot_push: Mapped[str | None] = mapped_column(Text, nullable=True)
    emotional_target: Mapped[str | None] = mapped_column(Text, nullable=True)
    ending_effect: Mapped[str | None] = mapped_column(Text, nullable=True)
    must_not: Mapped[str | None] = mapped_column(Text, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    writer_brief_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True, default=dict)
    trashed_flag: Mapped[int] = mapped_column(Integer, default=0)
    trashed_at: Mapped[str | None] = mapped_column(String, nullable=True)
    trashed_by: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[str] = mapped_column(String, default=utcnow)
    updated_at: Mapped[str] = mapped_column(String, default=utcnow, onupdate=utcnow)


class SceneCard(Base):
    __tablename__ = "scene_cards"

    scene_id: Mapped[str] = mapped_column(String, primary_key=True)
    chapter_id: Mapped[str] = mapped_column(ForeignKey("chapter_goals.chapter_id"))
    scene_seq: Mapped[int] = mapped_column(Integer)
    pov_character_id: Mapped[str | None] = mapped_column(String, nullable=True)
    onstage_chars_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    resolved_relation_id: Mapped[str | None] = mapped_column(String, nullable=True)
    location: Mapped[str | None] = mapped_column(String, nullable=True)
    scene_goal: Mapped[str] = mapped_column(Text)
    beats_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    must_include_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    forbidden_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    exit_change: Mapped[str | None] = mapped_column(Text, nullable=True)
    hook: Mapped[str | None] = mapped_column(Text, nullable=True)
    writer_brief_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True, default=dict)
    target_length_band: Mapped[str | None] = mapped_column(String, nullable=True)
    scene_type: Mapped[str | None] = mapped_column(String, nullable=True)
    is_chapter_last: Mapped[int] = mapped_column(Integer, default=0)
    trashed_flag: Mapped[int] = mapped_column(Integer, default=0)
    trashed_at: Mapped[str | None] = mapped_column(String, nullable=True)
    trashed_by: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[str] = mapped_column(String, default=utcnow)
    updated_at: Mapped[str] = mapped_column(String, default=utcnow, onupdate=utcnow)


class VoiceProfile(Base):
    __tablename__ = "voice_profiles"

    row_id: Mapped[str] = mapped_column(String, primary_key=True)
    voice_profile_id: Mapped[str] = mapped_column(String)
    version: Mapped[int] = mapped_column(Integer, default=1)
    character_id: Mapped[str] = mapped_column(String)
    content: Mapped[str] = mapped_column(Text)
    active_flag: Mapped[int] = mapped_column(Integer, default=0)
    runtime_eligible: Mapped[int] = mapped_column(Integer, default=0)
    runtime_eligibility_basis: Mapped[str] = mapped_column(String, default="stage_blocked")
    effective_at: Mapped[str | None] = mapped_column(String, nullable=True)
    source_review_id: Mapped[str | None] = mapped_column(String, nullable=True)
    source_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[str] = mapped_column(String, default=utcnow)
    updated_at: Mapped[str] = mapped_column(String, default=utcnow, onupdate=utcnow)


class RelationProfile(Base):
    __tablename__ = "relation_profiles"

    row_id: Mapped[str] = mapped_column(String, primary_key=True)
    relation_profile_id: Mapped[str] = mapped_column(String)
    left_character_id: Mapped[str] = mapped_column(String)
    right_character_id: Mapped[str] = mapped_column(String)
    version: Mapped[int] = mapped_column(Integer, default=1)
    content: Mapped[str] = mapped_column(Text)
    active_flag: Mapped[int] = mapped_column(Integer, default=0)
    runtime_eligible: Mapped[int] = mapped_column(Integer, default=0)
    runtime_eligibility_basis: Mapped[str] = mapped_column(String, default="stage_blocked")
    effective_at: Mapped[str | None] = mapped_column(String, nullable=True)
    source_review_id: Mapped[str | None] = mapped_column(String, nullable=True)
    source_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[str] = mapped_column(String, default=utcnow)
    updated_at: Mapped[str] = mapped_column(String, default=utcnow, onupdate=utcnow)


class SceneRunState(Base):
    __tablename__ = "scene_run_states"

    scene_id: Mapped[str] = mapped_column(ForeignKey("scene_cards.scene_id"), primary_key=True)
    scene_status: Mapped[str] = mapped_column(String, default="ready")
    current_bundle_id: Mapped[str | None] = mapped_column(String, nullable=True)
    current_bundle_hash: Mapped[str | None] = mapped_column(String, nullable=True)
    current_neutral_draft_row_id: Mapped[str | None] = mapped_column(String, nullable=True)
    current_style_draft_row_id: Mapped[str | None] = mapped_column(String, nullable=True)
    current_final_scene_row_id: Mapped[str | None] = mapped_column(String, nullable=True)
    current_human_review_event_id: Mapped[str | None] = mapped_column(String, nullable=True)
    current_qc_report_id: Mapped[str | None] = mapped_column(String, nullable=True)
    bundle_build_count: Mapped[int] = mapped_column(Integer, default=0)
    hard_partial_rewrite_count: Mapped[int] = mapped_column(Integer, default=0)
    hard_full_rewrite_count: Mapped[int] = mapped_column(Integer, default=0)
    soft_patch_count: Mapped[int] = mapped_column(Integer, default=0)
    total_attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    attempt_budget: Mapped[int] = mapped_column(Integer, default=4)
    repeat_issue_key: Mapped[str | None] = mapped_column(String, nullable=True)
    repeat_issue_count: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[str] = mapped_column(String, default=utcnow, onupdate=utcnow)


class ChapterState(Base):
    __tablename__ = "chapter_states"

    chapter_id: Mapped[str] = mapped_column(ForeignKey("chapter_goals.chapter_id"), primary_key=True)
    current_phase: Mapped[str] = mapped_column(String, default="planning")
    chapter_passed_scene_count: Mapped[int] = mapped_column(Integer, default=0)
    chapter_backfill_pending_count: Mapped[int] = mapped_column(Integer, default=0)
    mid_aggregate_enabled_effective: Mapped[int] = mapped_column(Integer, default=0)
    aggregate_block_reason: Mapped[str] = mapped_column(String, default="none")
    manual_hold_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_interim_memory_row_id: Mapped[str | None] = mapped_column(String, nullable=True)
    last_final_memory_row_id: Mapped[str | None] = mapped_column(String, nullable=True)
    updated_at: Mapped[str] = mapped_column(String, default=utcnow, onupdate=utcnow)


class StagedBackfill(Base):
    __tablename__ = "staged_backfill"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending','completed','deferred','abandoned')",
            name="ck_staged_backfill_status",
        ),
    )

    stage_id: Mapped[str] = mapped_column(String, primary_key=True)
    chapter_id: Mapped[str] = mapped_column(ForeignKey("chapter_goals.chapter_id"))
    scene_id: Mapped[str] = mapped_column(ForeignKey("scene_cards.scene_id"))
    marker_id: Mapped[str] = mapped_column(String)
    marker_text: Mapped[str] = mapped_column(Text)
    marker_token: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String, default="pending")
    linked_tracker_row_id: Mapped[str | None] = mapped_column(String, nullable=True)
    last_strategy: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[str] = mapped_column(String, default=utcnow)
    updated_at: Mapped[str] = mapped_column(String, default=utcnow, onupdate=utcnow)


class SceneBundle(Base):
    __tablename__ = "scene_bundles"

    bundle_id: Mapped[str] = mapped_column(String, primary_key=True)
    scene_id: Mapped[str] = mapped_column(ForeignKey("scene_cards.scene_id"))
    chapter_id: Mapped[str] = mapped_column(String)
    execution_mode: Mapped[str] = mapped_column(String, default="P2")
    bundle_snapshot_hash: Mapped[str] = mapped_column(String)
    frozen_snapshot_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[str] = mapped_column(String, default=utcnow)


class SceneBlueprint(Base):
    __tablename__ = "scene_blueprints"
    __table_args__ = (
        CheckConstraint(
            "status IN ('draft','accepted','superseded')",
            name="ck_scene_blueprints_status",
        ),
    )

    row_id: Mapped[str] = mapped_column(String, primary_key=True)
    scene_id: Mapped[str] = mapped_column(String)
    chapter_id: Mapped[str] = mapped_column(String)
    source_bundle_id: Mapped[str | None] = mapped_column(String, nullable=True)
    source_bundle_hash: Mapped[str | None] = mapped_column(String, nullable=True)
    blueprint_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    llm_call_id: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String, default="draft")
    created_at: Mapped[str] = mapped_column(String, default=utcnow)


class GenerationPlanningArtifact(Base):
    __tablename__ = "generation_planning_artifacts"
    __table_args__ = (
        CheckConstraint(
            "artifact_type IN ('character_pressure_blueprint','chapter_story_architecture')",
            name="ck_generation_planning_artifacts_type",
        ),
        CheckConstraint("object_type IN ('scene','chapter')", name="ck_generation_planning_artifacts_object_type"),
        CheckConstraint("status IN ('active','superseded')", name="ck_generation_planning_artifacts_status"),
    )

    row_id: Mapped[str] = mapped_column(String, primary_key=True)
    artifact_type: Mapped[str] = mapped_column(String)
    object_type: Mapped[str] = mapped_column(String)
    object_id: Mapped[str] = mapped_column(String)
    chapter_id: Mapped[str | None] = mapped_column(String, nullable=True)
    scene_id: Mapped[str | None] = mapped_column(String, nullable=True)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    llm_call_id: Mapped[str | None] = mapped_column(String, nullable=True)
    source_bundle_id: Mapped[str | None] = mapped_column(String, nullable=True)
    source_bundle_hash: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String, default="active")
    created_by: Mapped[str] = mapped_column(String, default="near_final_planning")
    created_at: Mapped[str] = mapped_column(String, default=utcnow)
    updated_at: Mapped[str] = mapped_column(String, default=utcnow, onupdate=utcnow)


class LlmCall(Base):
    __tablename__ = "llm_calls"

    llm_call_id: Mapped[str] = mapped_column(String, primary_key=True)
    provider: Mapped[str | None] = mapped_column(String, nullable=True)
    provider_id: Mapped[str | None] = mapped_column(String, nullable=True)
    account_id: Mapped[str | None] = mapped_column(String, nullable=True)
    model: Mapped[str | None] = mapped_column(String, nullable=True)
    node_id: Mapped[str | None] = mapped_column(String, nullable=True)
    reasoning_level: Mapped[str | None] = mapped_column(String, nullable=True)
    native_reasoning_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    credential_mode: Mapped[str | None] = mapped_column(String, nullable=True)
    prompt_hash: Mapped[str | None] = mapped_column(String, nullable=True)
    step: Mapped[str | None] = mapped_column(String, nullable=True)
    scene_id: Mapped[str | None] = mapped_column(String, nullable=True)
    chapter_id: Mapped[str | None] = mapped_column(String, nullable=True)
    request_payload_summary: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    response_payload_summary: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    prompt_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    completion_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    finish_reason: Mapped[str | None] = mapped_column(String, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[str] = mapped_column(String, default=utcnow)


class SceneDraft(Base):
    __tablename__ = "scene_drafts"

    row_id: Mapped[str] = mapped_column(String, primary_key=True)
    scene_id: Mapped[str] = mapped_column(String)
    chapter_id: Mapped[str] = mapped_column(String)
    stage: Mapped[str] = mapped_column(String)
    content: Mapped[str] = mapped_column(Text)
    source_bundle_id: Mapped[str] = mapped_column(String)
    source_bundle_hash: Mapped[str] = mapped_column(String)
    generation_llm_call_id: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[str] = mapped_column(String, default=utcnow)


class QcReport(Base):
    __tablename__ = "qc_reports"

    qc_report_id: Mapped[str] = mapped_column(String, primary_key=True)
    scene_id: Mapped[str | None] = mapped_column(String, nullable=True)
    chapter_id: Mapped[str | None] = mapped_column(String, nullable=True)
    qc_type: Mapped[str | None] = mapped_column(String, nullable=True)
    source_draft_row_id: Mapped[str | None] = mapped_column(String, nullable=True)
    source_bundle_id: Mapped[str | None] = mapped_column(String, nullable=True)
    resolution_code: Mapped[str | None] = mapped_column(String, nullable=True)
    pass_flag: Mapped[int | None] = mapped_column(Integer, nullable=True)
    next_action: Mapped[str | None] = mapped_column(String, nullable=True)
    issues_json: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON, nullable=True)
    rewrite_brief_json: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[str] = mapped_column(String, default=utcnow)


class WriterEvaluation(Base):
    __tablename__ = "writer_evaluations"

    evaluation_id: Mapped[str] = mapped_column(String, primary_key=True)
    object_type: Mapped[str] = mapped_column(String)
    object_id: Mapped[str] = mapped_column(String)
    chapter_id: Mapped[str | None] = mapped_column(String, nullable=True)
    scene_id: Mapped[str | None] = mapped_column(String, nullable=True)
    rubric_id: Mapped[str] = mapped_column(String)
    source_text_ref: Mapped[str | None] = mapped_column(String, nullable=True)
    source_bundle_id: Mapped[str | None] = mapped_column(String, nullable=True)
    evaluator_llm_call_id: Mapped[str | None] = mapped_column(String, nullable=True)
    lens: Mapped[str | None] = mapped_column(String, nullable=True)
    parent_evaluation_id: Mapped[str | None] = mapped_column(String, nullable=True)
    evidence_spans_json: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON, nullable=True)
    source_blueprint_row_id: Mapped[str | None] = mapped_column(String, nullable=True)
    overall_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    scores_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    findings_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    revision_brief_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    requires_human_review: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String, default="completed")
    created_at: Mapped[str] = mapped_column(String, default=utcnow)


class RevisionCandidate(Base):
    __tablename__ = "revision_candidates"
    __table_args__ = (
        CheckConstraint(
            "status IN ('candidate','accepted','rejected','superseded')",
            name="ck_revision_candidates_status",
        ),
    )

    revision_id: Mapped[str] = mapped_column(String, primary_key=True)
    evaluation_id: Mapped[str | None] = mapped_column(String, nullable=True)
    object_type: Mapped[str] = mapped_column(String)
    object_id: Mapped[str] = mapped_column(String)
    chapter_id: Mapped[str | None] = mapped_column(String, nullable=True)
    scene_id: Mapped[str | None] = mapped_column(String, nullable=True)
    revision_type: Mapped[str] = mapped_column(String)
    source_text_ref: Mapped[str | None] = mapped_column(String, nullable=True)
    proposed_text: Mapped[str] = mapped_column(Text)
    instruction_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    diff_summary_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    patches_json: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON, nullable=True, default=list)
    apply_mode: Mapped[str] = mapped_column(String, default="manual_only")
    target_text_ref: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String, default="candidate")
    author_decision_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[str] = mapped_column(String, default="writer_engine")
    created_at: Mapped[str] = mapped_column(String, default=utcnow)
    updated_at: Mapped[str] = mapped_column(String, default=utcnow, onupdate=utcnow)


class PassagePatchCandidate(Base):
    __tablename__ = "passage_patch_candidates"
    __table_args__ = (
        CheckConstraint(
            "status IN ('candidate','accepted','rejected','superseded')",
            name="ck_passage_patch_candidates_status",
        ),
        CheckConstraint(
            "author_decision IN ('pending','accepted','rejected','regenerate')",
            name="ck_passage_patch_candidates_author_decision",
        ),
    )

    patch_id: Mapped[str] = mapped_column(String, primary_key=True)
    object_type: Mapped[str] = mapped_column(String)
    object_id: Mapped[str] = mapped_column(String)
    chapter_id: Mapped[str | None] = mapped_column(String, nullable=True)
    scene_id: Mapped[str | None] = mapped_column(String, nullable=True)
    source_text_ref: Mapped[str | None] = mapped_column(String, nullable=True)
    target_text_ref: Mapped[str | None] = mapped_column(String, nullable=True)
    source_draft_id: Mapped[str | None] = mapped_column(String, nullable=True)
    generation_llm_call_id: Mapped[str | None] = mapped_column(String, nullable=True)
    quality_signal_id: Mapped[str | None] = mapped_column(String, nullable=True)
    source_excerpt: Mapped[str] = mapped_column(Text)
    issue_dimension: Mapped[str] = mapped_column(String)
    candidate_category: Mapped[str] = mapped_column(String, default="local_patch")
    target_range_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    revision_strategy: Mapped[str | None] = mapped_column(Text, nullable=True)
    preference_tags_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    inserted_into_author_draft: Mapped[int] = mapped_column(Integer, default=0)
    replacement_options_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    manual_only: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String, default="candidate")
    author_decision: Mapped[str] = mapped_column(String, default="pending")
    selected_option_id: Mapped[str | None] = mapped_column(String, nullable=True)
    author_decision_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[str] = mapped_column(String, default="writer_deep_review")
    created_at: Mapped[str] = mapped_column(String, default=utcnow)
    updated_at: Mapped[str] = mapped_column(String, default=utcnow, onupdate=utcnow)


class AuthorPreferenceProfile(Base):
    __tablename__ = "author_preference_profiles"
    __table_args__ = (
        CheckConstraint(
            "status IN ('draft','approved','rejected','superseded')",
            name="ck_author_preference_profiles_status",
        ),
    )

    profile_id: Mapped[str] = mapped_column(String, primary_key=True)
    scope_type: Mapped[str] = mapped_column(String, default="global")
    scope_ref_id: Mapped[str] = mapped_column(String, default="global")
    status: Mapped[str] = mapped_column(String, default="draft")
    runtime_eligible: Mapped[int] = mapped_column(Integer, default=0)
    summary_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    source_patch_ids_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    created_by: Mapped[str] = mapped_column(String, default="writer_deep_review")
    created_at: Mapped[str] = mapped_column(String, default=utcnow)
    updated_at: Mapped[str] = mapped_column(String, default=utcnow, onupdate=utcnow)


class AuthorDraft(Base):
    __tablename__ = "author_drafts"
    __table_args__ = (
        CheckConstraint("object_type IN ('scene','chapter')", name="ck_author_drafts_object_type"),
        CheckConstraint("status IN ('current','superseded','archived')", name="ck_author_drafts_status"),
    )

    draft_id: Mapped[str] = mapped_column(String, primary_key=True)
    object_type: Mapped[str] = mapped_column(String)
    object_id: Mapped[str] = mapped_column(String)
    source_text_ref: Mapped[str] = mapped_column(String)
    content: Mapped[str] = mapped_column(Text)
    revision_no: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String, default="current")
    created_by: Mapped[str] = mapped_column(String, default="author_draft")
    updated_by: Mapped[str] = mapped_column(String, default="author_draft")
    created_at: Mapped[str] = mapped_column(String, default=utcnow)
    updated_at: Mapped[str] = mapped_column(String, default=utcnow, onupdate=utcnow)


class AuthorDraftEvent(Base):
    __tablename__ = "author_draft_events"
    __table_args__ = (
        CheckConstraint(
            "event_type IN ('created','edited','candidate_inserted','candidate_saved','candidate_rejected')",
            name="ck_author_draft_events_type",
        ),
    )

    event_id: Mapped[str] = mapped_column(String, primary_key=True)
    draft_id: Mapped[str] = mapped_column(String)
    object_type: Mapped[str] = mapped_column(String)
    object_id: Mapped[str] = mapped_column(String)
    event_type: Mapped[str] = mapped_column(String)
    patch_id: Mapped[str | None] = mapped_column(String, nullable=True)
    revision_id: Mapped[str | None] = mapped_column(String, nullable=True)
    option_id: Mapped[str | None] = mapped_column(String, nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_by: Mapped[str] = mapped_column(String, default="author_draft")
    created_at: Mapped[str] = mapped_column(String, default=utcnow)


class AuthorStructureCandidate(Base):
    __tablename__ = "author_structure_candidates"
    __table_args__ = (
        CheckConstraint("object_type IN ('scene','chapter')", name="ck_author_structure_candidates_object_type"),
        CheckConstraint(
            "status IN ('candidate','accepted','rejected','superseded')",
            name="ck_author_structure_candidates_status",
        ),
        CheckConstraint(
            "author_decision IN ('pending','accepted','rejected')",
            name="ck_author_structure_candidates_author_decision",
        ),
    )

    candidate_id: Mapped[str] = mapped_column(String, primary_key=True)
    object_type: Mapped[str] = mapped_column(String)
    object_id: Mapped[str] = mapped_column(String)
    chapter_id: Mapped[str | None] = mapped_column(String, nullable=True)
    scene_id: Mapped[str | None] = mapped_column(String, nullable=True)
    source_draft_id: Mapped[str] = mapped_column(String)
    source_text_ref: Mapped[str | None] = mapped_column(String, nullable=True)
    extraction_llm_call_id: Mapped[str | None] = mapped_column(String, nullable=True)
    candidate_brief_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    uncertainty_notes_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String, default="candidate")
    author_decision: Mapped[str] = mapped_column(String, default="pending")
    author_decision_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[str] = mapped_column(String, default="author_structure_extract")
    created_at: Mapped[str] = mapped_column(String, default=utcnow)
    updated_at: Mapped[str] = mapped_column(String, default=utcnow, onupdate=utcnow)


class LongformDiagnosticCard(Base):
    __tablename__ = "longform_diagnostic_cards"
    __table_args__ = (
        CheckConstraint(
            "card_type IN ("
            "'character_arc_gap',"
            "'foreshadow_debt',"
            "'promise_without_payoff',"
            "'information_congestion',"
            "'theme_pressure_light',"
            "'relationship_turn_stall',"
            "'ending_drive_drop',"
            "'reference_leakage_risk'"
            ")",
            name="ck_longform_diagnostic_cards_type",
        ),
        CheckConstraint(
            "severity IN ('info','minor','major','critical')",
            name="ck_longform_diagnostic_cards_severity",
        ),
        CheckConstraint(
            "status IN ('open','resolved','dismissed','published_guidance')",
            name="ck_longform_diagnostic_cards_status",
        ),
        CheckConstraint(
            "object_type IN ('book','chapter','scene','character','relation','foreshadow','reference')",
            name="ck_longform_diagnostic_cards_object_type",
        ),
    )

    card_id: Mapped[str] = mapped_column(String, primary_key=True)
    card_type: Mapped[str] = mapped_column(String)
    severity: Mapped[str] = mapped_column(String, default="major")
    status: Mapped[str] = mapped_column(String, default="open")
    object_type: Mapped[str] = mapped_column(String)
    object_id: Mapped[str] = mapped_column(String)
    chapter_id: Mapped[str | None] = mapped_column(String, nullable=True)
    scene_id: Mapped[str | None] = mapped_column(String, nullable=True)
    character_id: Mapped[str | None] = mapped_column(String, nullable=True)
    source_refs_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    evidence_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    recommendation_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    source_snapshot_hash: Mapped[str] = mapped_column(String)
    review_id: Mapped[str | None] = mapped_column(String, nullable=True)
    guidance_id: Mapped[str | None] = mapped_column(String, nullable=True)
    created_by: Mapped[str] = mapped_column(String, default="longform_editor")
    updated_by: Mapped[str] = mapped_column(String, default="longform_editor")
    created_at: Mapped[str] = mapped_column(String, default=utcnow)
    updated_at: Mapped[str] = mapped_column(String, default=utcnow, onupdate=utcnow)


class LongformStructureGuidance(Base):
    __tablename__ = "longform_structure_guidance"
    __table_args__ = (
        CheckConstraint(
            "scope_type IN ('global','chapter','scene','character')",
            name="ck_longform_structure_guidance_scope_type",
        ),
        CheckConstraint(
            "status IN ('draft','approved','rejected','superseded')",
            name="ck_longform_structure_guidance_status",
        ),
    )

    guidance_id: Mapped[str] = mapped_column(String, primary_key=True)
    card_id: Mapped[str | None] = mapped_column(String, nullable=True)
    scope_type: Mapped[str] = mapped_column(String, default="global")
    scope_ref_id: Mapped[str] = mapped_column(String, default="global")
    content: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String, default="draft")
    runtime_eligible: Mapped[int] = mapped_column(Integer, default=0)
    source_review_id: Mapped[str | None] = mapped_column(String, nullable=True)
    evidence_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    recommendation_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_by: Mapped[str] = mapped_column(String, default="longform_editor")
    created_at: Mapped[str] = mapped_column(String, default=utcnow)
    updated_at: Mapped[str] = mapped_column(String, default=utcnow, onupdate=utcnow)


class FinalScene(Base):
    __tablename__ = "final_scenes"

    row_id: Mapped[str] = mapped_column(String, primary_key=True)
    scene_id: Mapped[str] = mapped_column(String)
    chapter_id: Mapped[str] = mapped_column(String)
    content: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String, default="approved")
    source_bundle_id: Mapped[str] = mapped_column(String)
    source_bundle_hash: Mapped[str] = mapped_column(String)
    generation_llm_call_id: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[str] = mapped_column(String, default=utcnow)


class SceneMemory(Base):
    __tablename__ = "scene_memories"

    row_id: Mapped[str] = mapped_column(String, primary_key=True)
    scene_id: Mapped[str] = mapped_column(String)
    chapter_id: Mapped[str] = mapped_column(String)
    content: Mapped[str] = mapped_column(Text)
    carry_notes_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    source_bundle_id: Mapped[str] = mapped_column(String)
    final_scene_row_id: Mapped[str] = mapped_column(String)
    source_review_id: Mapped[str | None] = mapped_column(String, nullable=True)
    active_flag: Mapped[int] = mapped_column(Integer, default=1)
    runtime_eligible: Mapped[int] = mapped_column(Integer, default=1)
    runtime_eligibility_basis: Mapped[str] = mapped_column(String, default="direct_read")
    effective_at: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[str] = mapped_column(String, default=utcnow)


class ChapterMemory(Base):
    __tablename__ = "chapter_memories"

    row_id: Mapped[str] = mapped_column(String, primary_key=True)
    chapter_id: Mapped[str] = mapped_column(String)
    aggregate_stage: Mapped[str] = mapped_column(String)
    content: Mapped[str] = mapped_column(Text)
    source_review_id: Mapped[str | None] = mapped_column(String, nullable=True)
    active_flag: Mapped[int] = mapped_column(Integer, default=0)
    runtime_eligible: Mapped[int] = mapped_column(Integer, default=0)
    runtime_eligibility_basis: Mapped[str] = mapped_column(String, default="stage_blocked")
    effective_at: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[str] = mapped_column(String, default=utcnow)


class ChapterRollingNote(Base):
    __tablename__ = "chapter_rolling_notes"

    row_id: Mapped[str] = mapped_column(String, primary_key=True)
    scene_id: Mapped[str] = mapped_column(String, unique=True)
    chapter_id: Mapped[str] = mapped_column(String)
    source_scene_memory_row_id: Mapped[str] = mapped_column(String)
    note_text: Mapped[str] = mapped_column(Text)
    revision_no: Mapped[int] = mapped_column(Integer, default=1)
    updated_at: Mapped[str] = mapped_column(String, default=utcnow, onupdate=utcnow)


class AttemptTracker(Base):
    __tablename__ = "attempt_tracker"

    attempt_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    scene_id: Mapped[str | None] = mapped_column(String, nullable=True)
    chapter_id: Mapped[str | None] = mapped_column(String, nullable=True)
    step: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String)
    source_bundle_id: Mapped[str | None] = mapped_column(String, nullable=True)
    details_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[str] = mapped_column(String, default=utcnow)


class ChapterRunJob(Base):
    __tablename__ = "chapter_run_jobs"

    job_id: Mapped[str] = mapped_column(String, primary_key=True)
    chapter_id: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String)
    job_type: Mapped[str] = mapped_column(String)
    payload_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    result_summary_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    worker_id: Mapped[str | None] = mapped_column(String, nullable=True)
    attempt_no: Mapped[int | None] = mapped_column(Integer, nullable=True)
    heartbeat_at: Mapped[str | None] = mapped_column(String, nullable=True)
    lease_expires_at: Mapped[str | None] = mapped_column(String, nullable=True)
    started_at: Mapped[str | None] = mapped_column(String, nullable=True)
    finished_at: Mapped[str | None] = mapped_column(String, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String, nullable=True)
    error_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[str] = mapped_column(String, default=utcnow)
    updated_at: Mapped[str] = mapped_column(String, default=utcnow, onupdate=utcnow)


class ReviewItem(Base):
    __tablename__ = "review_items"
    __table_args__ = (
        CheckConstraint("status IN ('pending','approved','rejected')", name="ck_review_items_status"),
    )

    review_id: Mapped[str] = mapped_column(String, primary_key=True)
    scene_id: Mapped[str | None] = mapped_column(String, nullable=True)
    chapter_id: Mapped[str | None] = mapped_column(String, nullable=True)
    item_type: Mapped[str] = mapped_column(String)
    target_collection: Mapped[str] = mapped_column(
        String,
        Computed(
            "CASE "
            "WHEN item_type = 'style_observation' THEN 'style_observations' "
            "WHEN item_type = 'style_rule_set' THEN 'style_rules' "
            "WHEN item_type = 'banned_rule_cluster' THEN 'banned_rule_clusters' "
            "WHEN item_type = 'narrative_pattern' THEN 'narrative_patterns' "
            "WHEN item_type = 'voice_card_candidate' THEN 'voice_cards' "
            "WHEN item_type = 'relation_card_candidate' THEN 'relation_cards' "
            "WHEN item_type = 'world_rule' THEN 'world_rules' "
            "WHEN item_type = 'calibration_candidate' THEN 'calibration_lines' "
            "WHEN item_type = 'foreshadow_open' THEN 'foreshadow_tracker' "
            "WHEN item_type = 'foreshadow_touch' THEN 'foreshadow_tracker' "
            "WHEN item_type = 'foreshadow_resolve' THEN 'foreshadow_tracker' "
            "WHEN item_type = 'scene_memory' THEN 'scene_memories' "
            "WHEN item_type = 'scene_summary' THEN 'scene_memories' "
            "WHEN item_type = 'chapter_summary' THEN 'chapter_memories' "
            "WHEN item_type = 'author_preference_profile' THEN 'author_preference_profiles' "
            "WHEN item_type = 'longform_structure_guidance' THEN 'longform_structure_guidance' "
            "ELSE 'review_items' END",
            persisted=True,
        ),
    )
    status: Mapped[str] = mapped_column(String, default="pending")
    candidate_text: Mapped[str] = mapped_column(Text)
    candidate_payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    active_on_approve: Mapped[int] = mapped_column(Integer, default=1)
    materialize_status: Mapped[str] = mapped_column(String, default="pending")
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    max_retry: Mapped[int] = mapped_column(Integer, default=3)
    approved_item_row_id: Mapped[str | None] = mapped_column(String, nullable=True)
    approved_item_id: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[str] = mapped_column(String, default=utcnow)
    updated_at: Mapped[str] = mapped_column(String, default=utcnow, onupdate=utcnow)


class HumanReviewEvent(Base):
    __tablename__ = "human_review_events"

    event_id: Mapped[str] = mapped_column(String, primary_key=True)
    scene_id: Mapped[str | None] = mapped_column(String, nullable=True)
    chapter_id: Mapped[str | None] = mapped_column(String, nullable=True)
    object_ref: Mapped[str | None] = mapped_column(String, nullable=True)
    event_source: Mapped[str] = mapped_column(String, default="system")
    priority: Mapped[str] = mapped_column(String, default="normal")
    owner: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String, default="open")
    allowed_actions_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    result_status_map_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    details_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    default_action: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[str] = mapped_column(String, default=utcnow)
    updated_at: Mapped[str] = mapped_column(String, default=utcnow, onupdate=utcnow)


class StyleObservation(Base):
    __tablename__ = "style_observations"
    __table_args__ = (
        CheckConstraint("NOT (active_flag = 0 AND runtime_eligible = 1)", name="ck_style_obs_runtime"),
    )

    row_id: Mapped[str] = mapped_column(String, primary_key=True)
    style_observation_id: Mapped[str] = mapped_column(String)
    version: Mapped[int] = mapped_column(Integer, default=1)
    scope: Mapped[str] = mapped_column(String, default="global")
    scope_ref_id: Mapped[str | None] = mapped_column(String, nullable=True)
    text: Mapped[str] = mapped_column(Text)
    source_review_id: Mapped[str | None] = mapped_column(String, nullable=True)
    active_flag: Mapped[int] = mapped_column(Integer, default=0)
    runtime_eligible: Mapped[int] = mapped_column(Integer, default=0)
    runtime_eligibility_basis: Mapped[str] = mapped_column(String, default="stage_blocked")
    effective_at: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[str] = mapped_column(String, default=utcnow)
    updated_at: Mapped[str] = mapped_column(String, default=utcnow, onupdate=utcnow)


class StyleRule(Base):
    __tablename__ = "style_rules"
    __table_args__ = (
        CheckConstraint("NOT (active_flag = 0 AND runtime_eligible = 1)", name="ck_style_rules_runtime"),
    )

    row_id: Mapped[str] = mapped_column(String, primary_key=True)
    style_rule_set_id: Mapped[str] = mapped_column(String)
    version: Mapped[int] = mapped_column(Integer, default=1)
    scope: Mapped[str] = mapped_column(String, default="global")
    scope_ref_id: Mapped[str | None] = mapped_column(String, nullable=True)
    content: Mapped[str] = mapped_column(Text)
    source_review_id: Mapped[str | None] = mapped_column(String, nullable=True)
    active_flag: Mapped[int] = mapped_column(Integer, default=0)
    runtime_eligible: Mapped[int] = mapped_column(Integer, default=0)
    runtime_eligibility_basis: Mapped[str] = mapped_column(String, default="stage_blocked")
    effective_at: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[str] = mapped_column(String, default=utcnow)
    updated_at: Mapped[str] = mapped_column(String, default=utcnow, onupdate=utcnow)


class NarrativePattern(Base):
    __tablename__ = "narrative_patterns"
    __table_args__ = (
        CheckConstraint("NOT (active_flag = 0 AND runtime_eligible = 1)", name="ck_narrative_patterns_runtime"),
    )

    row_id: Mapped[str] = mapped_column(String, primary_key=True)
    narrative_pattern_id: Mapped[str] = mapped_column(String)
    version: Mapped[int] = mapped_column(Integer, default=1)
    scope: Mapped[str] = mapped_column(String, default="global")
    scope_ref_id: Mapped[str | None] = mapped_column(String, nullable=True)
    content: Mapped[str] = mapped_column(Text)
    source_review_id: Mapped[str | None] = mapped_column(String, nullable=True)
    active_flag: Mapped[int] = mapped_column(Integer, default=0)
    runtime_eligible: Mapped[int] = mapped_column(Integer, default=0)
    runtime_eligibility_basis: Mapped[str] = mapped_column(String, default="stage_blocked")
    effective_at: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[str] = mapped_column(String, default=utcnow)
    updated_at: Mapped[str] = mapped_column(String, default=utcnow, onupdate=utcnow)


class BannedRuleCluster(Base):
    __tablename__ = "banned_rule_clusters"
    __table_args__ = (
        CheckConstraint("NOT (active_flag = 0 AND runtime_eligible = 1)", name="ck_banned_clusters_runtime"),
    )

    row_id: Mapped[str] = mapped_column(String, primary_key=True)
    banned_cluster_id: Mapped[str] = mapped_column(String)
    version: Mapped[int] = mapped_column(Integer, default=1)
    scope: Mapped[str] = mapped_column(String, default="global")
    scope_ref_id: Mapped[str | None] = mapped_column(String, nullable=True)
    content: Mapped[str] = mapped_column(Text)
    source_review_id: Mapped[str | None] = mapped_column(String, nullable=True)
    active_flag: Mapped[int] = mapped_column(Integer, default=0)
    runtime_eligible: Mapped[int] = mapped_column(Integer, default=0)
    runtime_eligibility_basis: Mapped[str] = mapped_column(String, default="stage_blocked")
    effective_at: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[str] = mapped_column(String, default=utcnow)
    updated_at: Mapped[str] = mapped_column(String, default=utcnow, onupdate=utcnow)


class WorldRule(Base):
    __tablename__ = "world_rules"
    __table_args__ = (
        CheckConstraint("NOT (active_flag = 0 AND runtime_eligible = 1)", name="ck_world_rules_runtime"),
    )

    row_id: Mapped[str] = mapped_column(String, primary_key=True)
    world_rule_id: Mapped[str] = mapped_column(String)
    version: Mapped[int] = mapped_column(Integer, default=1)
    scope: Mapped[str] = mapped_column(String, default="global")
    scope_ref_id: Mapped[str | None] = mapped_column(String, nullable=True)
    rule_tier: Mapped[str] = mapped_column(String, default="normal")
    content: Mapped[str] = mapped_column(Text)
    source_review_id: Mapped[str | None] = mapped_column(String, nullable=True)
    active_flag: Mapped[int] = mapped_column(Integer, default=0)
    runtime_eligible: Mapped[int] = mapped_column(Integer, default=0)
    runtime_eligibility_basis: Mapped[str] = mapped_column(String, default="stage_blocked")
    effective_at: Mapped[str | None] = mapped_column(String, nullable=True)
    expires_at: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[str] = mapped_column(String, default=utcnow)
    updated_at: Mapped[str] = mapped_column(String, default=utcnow, onupdate=utcnow)


class CalibrationLine(Base):
    __tablename__ = "calibration_lines"
    __table_args__ = (
        CheckConstraint("NOT (active_flag = 0 AND runtime_eligible = 1)", name="ck_calibration_lines_runtime"),
    )

    row_id: Mapped[str] = mapped_column(String, primary_key=True)
    calibration_line_id: Mapped[str] = mapped_column(String)
    version: Mapped[int] = mapped_column(Integer, default=1)
    scope: Mapped[str] = mapped_column(String, default="global")
    scope_ref_id: Mapped[str | None] = mapped_column(String, nullable=True)
    text: Mapped[str] = mapped_column(Text)
    source_review_id: Mapped[str | None] = mapped_column(String, nullable=True)
    active_flag: Mapped[int] = mapped_column(Integer, default=0)
    runtime_eligible: Mapped[int] = mapped_column(Integer, default=0)
    runtime_eligibility_basis: Mapped[str] = mapped_column(String, default="stage_blocked")
    effective_at: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[str] = mapped_column(String, default=utcnow)
    updated_at: Mapped[str] = mapped_column(String, default=utcnow, onupdate=utcnow)


class ForeshadowTracker(Base):
    __tablename__ = "foreshadow_tracker"
    __table_args__ = (
        CheckConstraint("NOT (active_flag = 0 AND runtime_eligible = 1)", name="ck_foreshadow_runtime"),
    )

    row_id: Mapped[str] = mapped_column(String, primary_key=True)
    foreshadow_id: Mapped[str] = mapped_column(String)
    version: Mapped[int] = mapped_column(Integer, default=1)
    chapter_id: Mapped[str] = mapped_column(String)
    scene_id: Mapped[str | None] = mapped_column(String, nullable=True)
    text: Mapped[str] = mapped_column(Text)
    tracker_status: Mapped[str] = mapped_column(String, default="open")
    source_review_id: Mapped[str | None] = mapped_column(String, nullable=True)
    active_flag: Mapped[int] = mapped_column(Integer, default=0)
    runtime_eligible: Mapped[int] = mapped_column(Integer, default=0)
    runtime_eligibility_basis: Mapped[str] = mapped_column(String, default="stage_blocked")
    effective_at: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[str] = mapped_column(String, default=utcnow)
    updated_at: Mapped[str] = mapped_column(String, default=utcnow, onupdate=utcnow)


class VersionRegistry(Base):
    __tablename__ = "version_registry"

    registry_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    object_type: Mapped[str] = mapped_column(String)
    lineage_key: Mapped[str] = mapped_column(String)
    version: Mapped[int] = mapped_column(Integer)
    physical_row_id: Mapped[str] = mapped_column(String)
    alias_scope: Mapped[str | None] = mapped_column(String, nullable=True)
    materialize_status: Mapped[str] = mapped_column(String, default="pending")
    reindex_status: Mapped[str] = mapped_column(String, default="queued")
    verify_status: Mapped[str] = mapped_column(String, default="pending")
    sample_query_success: Mapped[int] = mapped_column(Integer, default=0)
    approved_at: Mapped[str | None] = mapped_column(String, nullable=True)
    materialized_at: Mapped[str | None] = mapped_column(String, nullable=True)
    activated_at: Mapped[str | None] = mapped_column(String, nullable=True)
    reindexed_at: Mapped[str | None] = mapped_column(String, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)


class VectorAliasRegistry(Base):
    __tablename__ = "vector_alias_registry"
    __table_args__ = (
        CheckConstraint(
            "(active_alias IS NOT NULL) OR (candidate_alias IS NOT NULL)",
            name="ck_vector_alias_presence",
        ),
    )

    alias_scope: Mapped[str] = mapped_column(String, primary_key=True)
    object_type: Mapped[str] = mapped_column(String)
    scope: Mapped[str] = mapped_column(String)
    scope_ref_id: Mapped[str | None] = mapped_column(String, nullable=True)
    collection_family: Mapped[str] = mapped_column(String)
    active_alias: Mapped[str | None] = mapped_column(String, nullable=True)
    candidate_alias: Mapped[str | None] = mapped_column(String, nullable=True)
    active_snapshot_version: Mapped[str | None] = mapped_column(String, nullable=True)
    candidate_snapshot_version: Mapped[str | None] = mapped_column(String, nullable=True)
    active_embedding_version: Mapped[str | None] = mapped_column(String, nullable=True)
    candidate_embedding_version: Mapped[str | None] = mapped_column(String, nullable=True)
    verify_status: Mapped[str] = mapped_column(String, default="pending")
    sample_query_success: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[str] = mapped_column(String, default=utcnow, onupdate=utcnow)


class ReindexJob(Base):
    __tablename__ = "reindex_jobs"

    job_id: Mapped[str] = mapped_column(String, primary_key=True)
    review_id: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String, default="queued")
    object_type: Mapped[str] = mapped_column(String)
    alias_scope: Mapped[str] = mapped_column(String)
    target_snapshot_version: Mapped[str] = mapped_column(String)
    target_embedding_version: Mapped[str] = mapped_column(String)
    worker_id: Mapped[str | None] = mapped_column(String, nullable=True)
    attempt_no: Mapped[int] = mapped_column(Integer, default=0)
    heartbeat_at: Mapped[str | None] = mapped_column(String, nullable=True)
    lease_expires_at: Mapped[str | None] = mapped_column(String, nullable=True)
    started_at: Mapped[str | None] = mapped_column(String, nullable=True)
    finished_at: Mapped[str | None] = mapped_column(String, nullable=True)
    error_text: Mapped[str | None] = mapped_column(Text, nullable=True)


class VerifyJob(Base):
    __tablename__ = "verify_jobs"

    job_id: Mapped[str] = mapped_column(String, primary_key=True)
    review_id: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String, default="queued")
    object_type: Mapped[str] = mapped_column(String)
    alias_scope: Mapped[str] = mapped_column(String)
    target_snapshot_version: Mapped[str] = mapped_column(String)
    target_embedding_version: Mapped[str] = mapped_column(String)
    worker_id: Mapped[str | None] = mapped_column(String, nullable=True)
    attempt_no: Mapped[int] = mapped_column(Integer, default=0)
    heartbeat_at: Mapped[str | None] = mapped_column(String, nullable=True)
    lease_expires_at: Mapped[str | None] = mapped_column(String, nullable=True)
    started_at: Mapped[str | None] = mapped_column(String, nullable=True)
    finished_at: Mapped[str | None] = mapped_column(String, nullable=True)
    error_text: Mapped[str | None] = mapped_column(Text, nullable=True)


class InteropArtifact(Base):
    __tablename__ = "interop_artifacts"

    artifact_id: Mapped[str] = mapped_column(String, primary_key=True)
    artifact_kind: Mapped[str] = mapped_column(String)
    scene_id: Mapped[str | None] = mapped_column(String, nullable=True)
    chapter_id: Mapped[str | None] = mapped_column(String, nullable=True)
    source_bundle_id: Mapped[str | None] = mapped_column(String, nullable=True)
    file_path: Mapped[str] = mapped_column(String)
    file_format: Mapped[str] = mapped_column(String)
    file_checksum: Mapped[str | None] = mapped_column(String, nullable=True)
    direction: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String, default="completed")
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[str] = mapped_column(String, default=utcnow)


class IdempotencyKey(Base):
    __tablename__ = "idempotency_keys"

    idempotency_key: Mapped[str] = mapped_column(String, primary_key=True)
    request_hash: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String, default="started")
    response_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    worker_id: Mapped[str | None] = mapped_column(String, nullable=True)
    attempt_no: Mapped[int] = mapped_column(Integer, default=1)
    heartbeat_at: Mapped[str | None] = mapped_column(String, nullable=True)
    lease_expires_at: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[str] = mapped_column(String, default=utcnow)
    updated_at: Mapped[str] = mapped_column(String, default=utcnow, onupdate=utcnow)


class OperationLog(Base):
    __tablename__ = "operation_logs"

    operation_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_type: Mapped[str] = mapped_column(String)
    object_type: Mapped[str] = mapped_column(String)
    object_ref: Mapped[str] = mapped_column(String)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[str] = mapped_column(String, default=utcnow)


class ReconcileFault(Base):
    __tablename__ = "reconcile_faults"

    fault_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    fault_scope: Mapped[str] = mapped_column(String)
    severity: Mapped[str] = mapped_column(String)
    object_ref: Mapped[str] = mapped_column(String)
    details_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[str] = mapped_column(String, default=utcnow)


class ReferenceBook(Base):
    __tablename__ = "reference_books"

    book_id: Mapped[str] = mapped_column(String, primary_key=True)
    title: Mapped[str] = mapped_column(String)
    author_label: Mapped[str | None] = mapped_column(String, nullable=True)
    source_kind: Mapped[str] = mapped_column(String)
    source_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    file_name: Mapped[str | None] = mapped_column(String, nullable=True)
    cloud_policy: Mapped[str] = mapped_column(String)
    analysis_focus: Mapped[str] = mapped_column(String, default="style_structure")
    text_checksum: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String, default="imported")
    total_chars: Mapped[int] = mapped_column(Integer, default=0)
    total_segments: Mapped[int] = mapped_column(Integer, default=0)
    stats_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[str] = mapped_column(String, default=utcnow)
    updated_at: Mapped[str] = mapped_column(String, default=utcnow, onupdate=utcnow)


class ReferenceBookSegment(Base):
    __tablename__ = "reference_book_segments"

    segment_id: Mapped[str] = mapped_column(String, primary_key=True)
    book_id: Mapped[str] = mapped_column(ForeignKey("reference_books.book_id"))
    segment_index: Mapped[int] = mapped_column(Integer)
    chapter_hint: Mapped[str | None] = mapped_column(String, nullable=True)
    segment_kind: Mapped[str] = mapped_column(String)
    start_offset: Mapped[int] = mapped_column(Integer, default=0)
    end_offset: Mapped[int] = mapped_column(Integer, default=0)
    text: Mapped[str] = mapped_column(Text)
    selected_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[str] = mapped_column(String, default=utcnow)


class ReferenceLearningRun(Base):
    __tablename__ = "reference_learning_runs"

    run_id: Mapped[str] = mapped_column(String, primary_key=True)
    book_id: Mapped[str] = mapped_column(ForeignKey("reference_books.book_id"))
    status: Mapped[str] = mapped_column(String, default="running")
    batch_size: Mapped[int] = mapped_column(Integer, default=8)
    coverage_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    round_count: Mapped[int] = mapped_column(Integer, default=0)
    profile_id: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[str] = mapped_column(String, default=utcnow)
    updated_at: Mapped[str] = mapped_column(String, default=utcnow, onupdate=utcnow)


class ReferenceLearningRound(Base):
    __tablename__ = "reference_learning_rounds"

    round_id: Mapped[str] = mapped_column(String, primary_key=True)
    book_id: Mapped[str] = mapped_column(ForeignKey("reference_books.book_id"))
    run_id: Mapped[str] = mapped_column(ForeignKey("reference_learning_runs.run_id"))
    round_index: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String, default="waiting_review")
    segment_ids_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    finding_ids_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    created_at: Mapped[str] = mapped_column(String, default=utcnow)
    updated_at: Mapped[str] = mapped_column(String, default=utcnow, onupdate=utcnow)


class ReferenceFinding(Base):
    __tablename__ = "reference_findings"

    finding_id: Mapped[str] = mapped_column(String, primary_key=True)
    book_id: Mapped[str] = mapped_column(ForeignKey("reference_books.book_id"))
    run_id: Mapped[str] = mapped_column(ForeignKey("reference_learning_runs.run_id"))
    round_id: Mapped[str] = mapped_column(ForeignKey("reference_learning_rounds.round_id"))
    segment_id: Mapped[str] = mapped_column(ForeignKey("reference_book_segments.segment_id"))
    review_id: Mapped[str] = mapped_column(String)
    finding_type: Mapped[str] = mapped_column(String)
    dimension: Mapped[str] = mapped_column(String)
    summary: Mapped[str] = mapped_column(Text)
    evidence_preview: Mapped[str] = mapped_column(Text)
    candidate_payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String, default="pending")
    created_at: Mapped[str] = mapped_column(String, default=utcnow)
    updated_at: Mapped[str] = mapped_column(String, default=utcnow, onupdate=utcnow)


class ReferenceProfile(Base):
    __tablename__ = "reference_profiles"

    profile_id: Mapped[str] = mapped_column(String, primary_key=True)
    book_id: Mapped[str] = mapped_column(ForeignKey("reference_books.book_id"))
    run_id: Mapped[str] = mapped_column(ForeignKey("reference_learning_runs.run_id"))
    title: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String, default="ready")
    profile_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    coverage_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    source_finding_ids_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    created_at: Mapped[str] = mapped_column(String, default=utcnow)
    updated_at: Mapped[str] = mapped_column(String, default=utcnow, onupdate=utcnow)


class SystemConfigSnapshot(Base):
    __tablename__ = "system_config_snapshots"

    snapshot_id: Mapped[str] = mapped_column(String, primary_key=True)
    category: Mapped[str] = mapped_column(String)
    version: Mapped[int] = mapped_column(Integer)
    yaml_raw: Mapped[str] = mapped_column(Text)
    parsed_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    validation_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String, default="draft")
    active_flag: Mapped[int] = mapped_column(Integer, default=0)
    created_by: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[str] = mapped_column(String, default=utcnow)
    activated_at: Mapped[str | None] = mapped_column(String, nullable=True)


class SystemSecret(Base):
    __tablename__ = "system_secrets"

    secret_id: Mapped[str] = mapped_column(String, primary_key=True)
    encrypted_value: Mapped[str] = mapped_column(Text)
    value_hint: Mapped[str | None] = mapped_column(String, nullable=True)
    secret_type: Mapped[str] = mapped_column(String, default="generic")
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    expires_at: Mapped[str | None] = mapped_column(String, nullable=True)
    updated_by: Mapped[str | None] = mapped_column(String, nullable=True)
    updated_at: Mapped[str] = mapped_column(String, default=utcnow, onupdate=utcnow)
