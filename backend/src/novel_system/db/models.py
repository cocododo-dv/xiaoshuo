from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, CheckConstraint, Computed, ForeignKey, Integer, String, Text
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
    target_length_band: Mapped[str | None] = mapped_column(String, nullable=True)
    scene_type: Mapped[str | None] = mapped_column(String, nullable=True)
    is_chapter_last: Mapped[int] = mapped_column(Integer, default=0)
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
    last_interim_memory_row_id: Mapped[str | None] = mapped_column(String, nullable=True)
    last_final_memory_row_id: Mapped[str | None] = mapped_column(String, nullable=True)
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


class SceneDraft(Base):
    __tablename__ = "scene_drafts"

    row_id: Mapped[str] = mapped_column(String, primary_key=True)
    scene_id: Mapped[str] = mapped_column(String)
    chapter_id: Mapped[str] = mapped_column(String)
    stage: Mapped[str] = mapped_column(String)
    content: Mapped[str] = mapped_column(Text)
    source_bundle_id: Mapped[str] = mapped_column(String)
    source_bundle_hash: Mapped[str] = mapped_column(String)
    created_at: Mapped[str] = mapped_column(String, default=utcnow)


class FinalScene(Base):
    __tablename__ = "final_scenes"

    row_id: Mapped[str] = mapped_column(String, primary_key=True)
    scene_id: Mapped[str] = mapped_column(String)
    chapter_id: Mapped[str] = mapped_column(String)
    content: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String, default="approved")
    source_bundle_id: Mapped[str] = mapped_column(String)
    source_bundle_hash: Mapped[str] = mapped_column(String)
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
    active_flag: Mapped[int] = mapped_column(Integer, default=1)
    runtime_eligible: Mapped[int] = mapped_column(Integer, default=1)
    runtime_eligibility_basis: Mapped[str] = mapped_column(String, default="direct_read")
    created_at: Mapped[str] = mapped_column(String, default=utcnow)


class ChapterMemory(Base):
    __tablename__ = "chapter_memories"

    row_id: Mapped[str] = mapped_column(String, primary_key=True)
    chapter_id: Mapped[str] = mapped_column(String)
    aggregate_stage: Mapped[str] = mapped_column(String)
    content: Mapped[str] = mapped_column(Text)
    active_flag: Mapped[int] = mapped_column(Integer, default=0)
    runtime_eligible: Mapped[int] = mapped_column(Integer, default=0)
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
            "WHEN item_type = 'calibration_line' THEN 'calibration_lines' "
            "WHEN item_type = 'scene_memory' THEN 'scene_memories' "
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
