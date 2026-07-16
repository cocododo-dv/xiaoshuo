from __future__ import annotations

import argparse
import json
from typing import Any

from sqlalchemy import delete, func, or_, select
from sqlalchemy.orm import Session

from novel_system.db.models import (
    AttemptTracker,
    BannedRuleCluster,
    CalibrationLine,
    ChapterGoal,
    ChapterMemory,
    ChapterRollingNote,
    ChapterState,
    FinalScene,
    ForeshadowTracker,
    HumanReviewEvent,
    IdempotencyKey,
    OperationLog,
    ReindexJob,
    RelationProfile,
    ReviewItem,
    SceneBundle,
    SceneCard,
    SceneDraft,
    SceneMemory,
    SceneRunState,
    StagedBackfill,
    StoryProject,
    StyleObservation,
    StyleRule,
    VectorAliasRegistry,
    VerifyJob,
    VersionRegistry,
    VoiceProfile,
    WorldRule,
)
from novel_system.db.session import SessionLocal
from novel_system.services.idempotency import canonical_request_hash

DEMO_PROJECT = {
    "project_id": "PRJ_DEMO_CH001",
    "title": "Demo CH001",
    "outline_text": "Traceable demo project for the CH001 runtime fixtures.",
}

DEMO_CHAPTER = {
    "chapter_id": "CH001",
    "project_id": DEMO_PROJECT["project_id"],
    "planned_scene_count": 3,
    "chapter_goal": "重逢与试探成立",
    "main_plot_push": "旧信线索被正式打开",
    "emotional_target": "由迟疑转入警觉",
    "ending_effect": "留下余波",
}

DEMO_SCENES = [
    {
        "scene_id": "CH001_SC01",
        "project_id": DEMO_PROJECT["project_id"],
        "chapter_id": "CH001",
        "scene_seq": 1,
        "pov_character_id": "CHAR_A",
        "onstage_chars_json": ["CHAR_A", "CHAR_B"],
        "location": "旧城门廊",
        "scene_goal": "让两人重新见面并建立张力",
        "beats_json": ["重逢", "试探", "留钩子"],
        # The deterministic offline client intentionally never echoes required
        # facts. Keep the runnable demo advisory instead of falsely claiming an
        # offline placeholder satisfied a hard continuity requirement.
        "must_include_text": None,
        "target_length_band": "short",
        "scene_type": "reunion",
        "is_chapter_last": 0,
    },
    {
        "scene_id": "CH001_SC02",
        "project_id": DEMO_PROJECT["project_id"],
        "chapter_id": "CH001",
        "scene_seq": 2,
        "pov_character_id": "CHAR_B",
        "onstage_chars_json": ["CHAR_A", "CHAR_B", "CHAR_C"],
        "location": "档案库侧室",
        "scene_goal": "把旧信中的矛盾线索抬到台面上",
        "beats_json": ["核对笔迹", "暴露缺口", "压下结论"],
        "must_include_text": None,
        "target_length_band": "medium",
        "scene_type": "investigation",
        "is_chapter_last": 0,
    },
    {
        "scene_id": "CH001_SC03",
        "project_id": DEMO_PROJECT["project_id"],
        "chapter_id": "CH001",
        "scene_seq": 3,
        "pov_character_id": "CHAR_A",
        "onstage_chars_json": ["CHAR_A", "CHAR_C"],
        "location": "雨夜码头",
        "scene_goal": "让角色带着未解问题进入下一章",
        "beats_json": ["追到码头", "交换条件", "余波收束"],
        "must_include_text": None,
        # 章末场景(is_chapter_last=1)必须声明非空 hook,否则触发蓝图 §10 章末 hook
        # 硬门(missing_hook_type)→ partial_rewrite、不产出 final_scene。该门当前仅校验
        # hook 非空(classify_hook_type 对任意非空文本都会兜底归类),此处给一条语义贴合
        # 的悬念 hook,既满足硬门又是合理的 demo 数据。
        "hook": "汽笛压过最后一句话，他没说出口的秘密，到底会把两人引向怎样的命运。",
        "target_length_band": "medium",
        "scene_type": "cliffhanger",
        "is_chapter_last": 1,
    },
]

DEMO_STYLE_OBSERVATION_REVIEW = {
    "review_id": "review_demo_style_observation",
    "scene_id": "CH001_SC01",
    "chapter_id": "CH001",
    "item_type": "style_observation",
    "status": "pending",
    "candidate_text": "收尾保留半句停顿，让情绪压在门后。",
    "candidate_payload_json": {
        "scope": "global",
        "scope_ref_id": "global",
        "lineage_key": "STY_DEMO_001",
        "text": "收尾保留半句停顿，让情绪压在门后。",
    },
    "active_on_approve": 0,
    "materialize_status": "pending",
    "retry_count": 0,
    "max_retry": 3,
    "approved_item_row_id": None,
    "approved_item_id": None,
}
DEMO_ALIAS_SCOPE = "style_observation:global:global"
DEMO_VOICE_PROFILES = [
    {
        "row_id": "voice_profile_VOICE_CHAR_A_v1",
        "voice_profile_id": "VOICE_CHAR_A",
        "version": 1,
        "character_id": "CHAR_A",
        "content": "short clipped lines; pressure makes the tone harder",
        "active_flag": 1,
        "source_note": "demo baseline",
    },
    {
        "row_id": "voice_profile_VOICE_CHAR_B_v1",
        "voice_profile_id": "VOICE_CHAR_B",
        "version": 1,
        "character_id": "CHAR_B",
        "content": "measured, observant phrasing; rarely answers directly",
        "active_flag": 1,
        "source_note": "demo baseline",
    },
]
DEMO_RELATION_PROFILES = [
    {
        "row_id": "relation_profile_REL_CHAR_A_CHAR_B_v1",
        "relation_profile_id": "REL_CHAR_A_CHAR_B",
        "left_character_id": "CHAR_A",
        "right_character_id": "CHAR_B",
        "version": 1,
        "content": "reunion tension; B knows slightly more than A",
        "active_flag": 1,
        "source_note": "demo baseline",
    },
    {
        "row_id": "relation_profile_REL_CHAR_A_CHAR_C_v1",
        "relation_profile_id": "REL_CHAR_A_CHAR_C",
        "left_character_id": "CHAR_A",
        "right_character_id": "CHAR_C",
        "version": 1,
        "content": "uneasy cooperation; both sides hold back a condition",
        "active_flag": 1,
        "source_note": "demo baseline",
    },
]
DEMO_STYLE_RULES = [
    {
        "row_id": "style_rule_STYLE_DEMO_MAIN_v1",
        "style_rule_set_id": "STYLE_DEMO_MAIN",
        "version": 1,
        "scope": "global",
        "scope_ref_id": "global",
        "content": "keep emotion in gesture and pause",
        "source_review_id": None,
        "active_flag": 1,
        "runtime_eligible": 1,
        "runtime_eligibility_basis": "direct_read",
    }
]
DEMO_BANNED_RULE_CLUSTERS = [
    {
        "row_id": "banned_rule_cluster_BAN_DEMO_REUNION_v1",
        "banned_cluster_id": "BAN_DEMO_REUNION",
        "version": 1,
        "scope": "global",
        "scope_ref_id": "global",
        "content": "do not explain the whole backstory at reunion time",
        "source_review_id": None,
        "active_flag": 1,
        "runtime_eligible": 1,
        "runtime_eligibility_basis": "direct_read",
    }
]
DEMO_WORLD_RULES = [
    {
        "row_id": "world_rule_WR_DEMO_CITY_v1",
        "world_rule_id": "WR_DEMO_CITY",
        "version": 1,
        "scope": "global",
        "scope_ref_id": "global",
        "rule_tier": "hard",
        "content": "public spellcasting inside the city is forbidden",
        "source_review_id": None,
        "active_flag": 1,
        "runtime_eligible": 1,
        "runtime_eligibility_basis": "direct_read",
        "expires_at": None,
    }
]
DEMO_CALIBRATION_LINES = [
    {
        "row_id": "calibration_line_CAL_DEMO_001_v1",
        "calibration_line_id": "CAL_DEMO_001",
        "version": 1,
        "scope": "global",
        "scope_ref_id": "global",
        "text": "the door closed like a sentence left unfinished",
        "source_review_id": None,
        "active_flag": 1,
        "runtime_eligible": 1,
        "runtime_eligibility_basis": "vector_ready",
    }
]
DEMO_FORESHADOW_TRACKERS = [
    {
        "row_id": "foreshadow_FORESHADOW_DEMO_001_v1",
        "foreshadow_id": "FORESHADOW_DEMO_001",
        "version": 1,
        "chapter_id": "CH001",
        "scene_id": "CH001_SC01",
        "text": "the old letter sender clue is now in play",
        "tracker_status": "open",
        "source_review_id": None,
        "active_flag": 1,
        "runtime_eligible": 1,
        "runtime_eligibility_basis": "foreshadow_open",
    }
]
DEMO_SCENE_SUMMARIES = [
    {
        "row_id": "scene_memory_CH001_SC01_summary_v1",
        "scene_id": "CH001_SC01",
        "chapter_id": "CH001",
        "content": "scene summary for the first reunion beat",
        "carry_notes_json": [],
        "source_bundle_id": "seed_demo",
        "final_scene_row_id": "seed_demo",
        "source_review_id": None,
        "active_flag": 1,
        "runtime_eligible": 1,
        "runtime_eligibility_basis": "direct_read",
    }
]
DEMO_CHAPTER_SUMMARIES = [
    {
        "row_id": "chapter_memory_CH001_summary_v1",
        "chapter_id": "CH001",
        "aggregate_stage": "summary",
        "content": "chapter summary for the first reunion chapter",
        "source_review_id": None,
        "active_flag": 1,
        "runtime_eligible": 1,
        "runtime_eligibility_basis": "direct_read",
    }
]
DEMO_KNOWLEDGE_VERSION_REGISTRIES = [
    {
        "object_type": "style_rule",
        "lineage_key": "STYLE_DEMO_MAIN",
        "version": 1,
        "physical_row_id": "style_rule_STYLE_DEMO_MAIN_v1",
        "alias_scope": None,
        "materialize_status": "succeeded",
        "reindex_status": "not_required",
        "verify_status": "not_required",
        "activated_at": "2026-04-10T00:00:00+00:00",
    },
    {
        "object_type": "banned_rule_cluster",
        "lineage_key": "BAN_DEMO_REUNION",
        "version": 1,
        "physical_row_id": "banned_rule_cluster_BAN_DEMO_REUNION_v1",
        "alias_scope": None,
        "materialize_status": "succeeded",
        "reindex_status": "not_required",
        "verify_status": "not_required",
        "activated_at": "2026-04-10T00:00:00+00:00",
    },
    {
        "object_type": "world_rule",
        "lineage_key": "WR_DEMO_CITY",
        "version": 1,
        "physical_row_id": "world_rule_WR_DEMO_CITY_v1",
        "alias_scope": None,
        "materialize_status": "succeeded",
        "reindex_status": "not_required",
        "verify_status": "not_required",
        "activated_at": "2026-04-10T00:00:00+00:00",
    },
    {
        "object_type": "calibration_line",
        "lineage_key": "CAL_DEMO_001",
        "version": 1,
        "physical_row_id": "calibration_line_CAL_DEMO_001_v1",
        "alias_scope": "calibration_line:global:global",
        "materialize_status": "succeeded",
        "reindex_status": "succeeded",
        "verify_status": "succeeded",
        "activated_at": "2026-04-10T00:00:00+00:00",
    },
    {
        "object_type": "foreshadow",
        "lineage_key": "FORESHADOW_DEMO_001",
        "version": 1,
        "physical_row_id": "foreshadow_FORESHADOW_DEMO_001_v1",
        "alias_scope": None,
        "materialize_status": "succeeded",
        "reindex_status": "not_required",
        "verify_status": "not_required",
        "activated_at": "2026-04-10T00:00:00+00:00",
    },
    {
        "object_type": "scene_summary",
        "lineage_key": "CH001_SC01",
        "version": 1,
        "physical_row_id": "scene_memory_CH001_SC01_summary_v1",
        "alias_scope": None,
        "materialize_status": "succeeded",
        "reindex_status": "not_required",
        "verify_status": "not_required",
        "activated_at": "2026-04-10T00:00:00+00:00",
    },
    {
        "object_type": "chapter_summary",
        "lineage_key": "CH001",
        "version": 1,
        "physical_row_id": "chapter_memory_CH001_summary_v1",
        "alias_scope": None,
        "materialize_status": "succeeded",
        "reindex_status": "not_required",
        "verify_status": "not_required",
        "activated_at": "2026-04-10T00:00:00+00:00",
    },
]
DEMO_CALIBRATION_ALIAS = {
    "alias_scope": "calibration_line:global:global",
    "object_type": "calibration_line",
    "scope": "global",
    "scope_ref_id": "global",
    "collection_family": "calibration_line_global_global",
    "active_alias": "calibration_line_global_global__candidate__calibration_line_CAL_DEMO_001_v1",
    "candidate_alias": None,
    "active_snapshot_version": "snapshot__calibration_line_CAL_DEMO_001_v1",
    "candidate_snapshot_version": None,
    "active_embedding_version": "embed__calibration_line_CAL_DEMO_001_v1",
    "candidate_embedding_version": None,
    "verify_status": "succeeded",
    "sample_query_success": 1,
}

DEMO_RUNTIME_OPS_E2E_FIXTURE = "runtime_ops_e2e"
DEMO_RUNTIME_OPS_E2E_DUE_PROMOTION_REVIEW = {
    "review_id": "review_demo_due_promotion",
    "scene_id": "CH001_SC02",
    "chapter_id": "CH001",
    "item_type": "style_observation",
    "status": "approved",
    "candidate_text": "promote the verified scene-scope note during runtime ops",
    "candidate_payload_json": {
        "scope": "scene",
        "scope_ref_id": "CH001_SC02",
        "lineage_key": "STY_DEMO_DUE_PROMOTION",
        "text": "promote the verified scene-scope note during runtime ops",
        "effective_at": "2000-01-01T00:00:00+00:00",
    },
    "active_on_approve": 1,
    "materialize_status": "succeeded",
    "retry_count": 0,
    "max_retry": 3,
    "approved_item_row_id": "style_observation_STY_DEMO_DUE_PROMOTION_v1",
    "approved_item_id": "STY_DEMO_DUE_PROMOTION",
}
DEMO_RUNTIME_OPS_E2E_RECOVERY_REVIEW = {
    "review_id": "review_demo_recovery_followup",
    "scene_id": "CH001_SC03",
    "chapter_id": "CH001",
    "item_type": "style_observation",
    "status": "pending",
    "candidate_text": "replay the stranded approve request and finish the follow-up chain",
    "candidate_payload_json": {
        "scope": "scene",
        "scope_ref_id": "CH001_SC03",
        "lineage_key": "STY_DEMO_RECOVERY_FOLLOWUP",
        "text": "replay the stranded approve request and finish the follow-up chain",
    },
    "active_on_approve": 0,
    "materialize_status": "pending",
    "retry_count": 0,
    "max_retry": 3,
    "approved_item_row_id": None,
    "approved_item_id": None,
}
DEMO_RUNTIME_OPS_E2E_DUE_PROMOTION_ACTIVE_ROW = {
    "row_id": "style_observation_STY_ACTIVE_SC02_v1",
    "style_observation_id": "STY_ACTIVE_SC02",
    "version": 1,
    "scope": "scene",
    "scope_ref_id": "CH001_SC02",
    "text": "the current scene note stays active until due promotion runs",
    "source_review_id": "review_demo_active_scene_seed",
    "active_flag": 1,
    "runtime_eligible": 1,
    "runtime_eligibility_basis": "vector_ready",
}
DEMO_RUNTIME_OPS_E2E_DUE_PROMOTION_ROW = {
    "row_id": "style_observation_STY_DEMO_DUE_PROMOTION_v1",
    "style_observation_id": "STY_DEMO_DUE_PROMOTION",
    "version": 1,
    "scope": "scene",
    "scope_ref_id": "CH001_SC02",
    "text": "promote the verified scene-scope note during runtime ops",
    "source_review_id": "review_demo_due_promotion",
    "active_flag": 0,
    "runtime_eligible": 0,
    "runtime_eligibility_basis": "future_effective",
    "effective_at": "2000-01-01T00:00:00+00:00",
}
DEMO_RUNTIME_OPS_E2E_DUE_PROMOTION_REGISTRY = {
    "object_type": "style_observation",
    "lineage_key": "STY_DEMO_DUE_PROMOTION",
    "version": 1,
    "physical_row_id": "style_observation_STY_DEMO_DUE_PROMOTION_v1",
    "alias_scope": "style_observation:scene:CH001_SC02",
    "materialize_status": "succeeded",
    "reindex_status": "succeeded",
    "verify_status": "succeeded",
}
DEMO_RUNTIME_OPS_E2E_DUE_PROMOTION_ALIAS = {
    "alias_scope": "style_observation:scene:CH001_SC02",
    "object_type": "style_observation",
    "scope": "scene",
    "scope_ref_id": "CH001_SC02",
    "collection_family": "style_observation_scene_CH001_SC02",
    "active_alias": "style_observation_scene_CH001_SC02__candidate__style_observation_STY_ACTIVE_SC02_v1",
    "candidate_alias": "style_observation_scene_CH001_SC02__candidate__style_observation_STY_DEMO_DUE_PROMOTION_v1",
    "active_snapshot_version": "snapshot__style_observation_STY_ACTIVE_SC02_v1",
    "candidate_snapshot_version": "snapshot__style_observation_STY_DEMO_DUE_PROMOTION_v1",
    "active_embedding_version": "embed__style_observation_STY_ACTIVE_SC02_v1",
    "candidate_embedding_version": "embed__style_observation_STY_DEMO_DUE_PROMOTION_v1",
    "verify_status": "succeeded",
    "sample_query_success": 1,
}
DEMO_RUNTIME_OPS_E2E_RECLAIMABLE_VERIFY_JOB = {
    "job_id": "verify_job_demo_reclaimable",
    "review_id": None,
    "status": "running",
    "object_type": "style_observation",
    "alias_scope": "style_observation:scene:CH001_SC01",
    "target_snapshot_version": "snapshot__style_observation_STY_RECLAIMABLE_v1",
    "target_embedding_version": "embed__style_observation_STY_RECLAIMABLE_v1",
    "worker_id": "verify-worker-stale",
    "attempt_no": 2,
    "heartbeat_at": "2026-04-09T16:00:00+00:00",
    "lease_expires_at": "2000-01-01T00:00:00+00:00",
    "started_at": "2026-04-09T15:59:00+00:00",
    "finished_at": None,
    "error_text": None,
}
DEMO_RUNTIME_OPS_E2E_FAILED_VERIFY_JOB = {
    "job_id": "verify_job_demo_failed_recent",
    "review_id": None,
    "status": "failed",
    "object_type": "style_observation",
    "alias_scope": "style_observation:scene:CH001_SC01",
    "target_snapshot_version": "snapshot__style_observation_STY_FAILED_v1",
    "target_embedding_version": "embed__style_observation_STY_FAILED_v1",
    "worker_id": "verify-worker-failed",
    "attempt_no": 3,
    "heartbeat_at": "2026-04-09T16:04:00+00:00",
    "lease_expires_at": "2026-04-09T16:07:00+00:00",
    "started_at": "2026-04-09T16:02:00+00:00",
    "finished_at": "2026-04-09T16:05:00+00:00",
    "error_text": "candidate alias verify failed",
}
DEMO_RUNTIME_OPS_E2E_RECOVERY_IDEMPOTENCY_KEY = "approve-review-demo-recovery-followup"
DEMO_RUNTIME_OPS_E2E_RECOVERY_REQUEST_PAYLOAD = {"review_id": "review_demo_recovery_followup"}
DEMO_RUNTIME_OPS_E2E_RECOVERY_REQUEST_HASH = canonical_request_hash(
    "POST",
    "/api/v1/review-items/{review_id}/approve",
    DEMO_RUNTIME_OPS_E2E_RECOVERY_REQUEST_PAYLOAD,
)
DEMO_RUNTIME_OPS_E2E_REVIEW_IDS = [
    DEMO_RUNTIME_OPS_E2E_DUE_PROMOTION_REVIEW["review_id"],
    DEMO_RUNTIME_OPS_E2E_RECOVERY_REVIEW["review_id"],
]
DEMO_RUNTIME_OPS_E2E_STYLE_IDS = [
    DEMO_RUNTIME_OPS_E2E_DUE_PROMOTION_ACTIVE_ROW["style_observation_id"],
    DEMO_RUNTIME_OPS_E2E_DUE_PROMOTION_ROW["style_observation_id"],
    DEMO_RUNTIME_OPS_E2E_RECOVERY_REVIEW["candidate_payload_json"]["lineage_key"],
]
DEMO_RUNTIME_OPS_E2E_STYLE_ROW_IDS = [
    DEMO_RUNTIME_OPS_E2E_DUE_PROMOTION_ACTIVE_ROW["row_id"],
    DEMO_RUNTIME_OPS_E2E_DUE_PROMOTION_ROW["row_id"],
]
DEMO_RUNTIME_OPS_E2E_JOB_IDS = [
    DEMO_RUNTIME_OPS_E2E_RECLAIMABLE_VERIFY_JOB["job_id"],
    DEMO_RUNTIME_OPS_E2E_FAILED_VERIFY_JOB["job_id"],
    "reindex_review_demo_recovery_followup",
    "verify_review_demo_recovery_followup",
]
DEMO_RUNTIME_OPS_E2E_EVENT_IDS = [
    "human_review_idempotency_recovery_approve-review-demo-recovery-followup",
]
DEMO_RUNTIME_OPS_E2E_ALIAS_SCOPES = [
    ("global", "global"),
    ("scene", "CH001_SC02"),
    ("scene", "CH001_SC03"),
]
DEMO_CHAPTER_OPS_E2E_FIXTURE = "chapter_ops_e2e"
DEMO_ALL_E2E_FIXTURE = "all_e2e"
DEMO_PREFLIGHT_BLOCKED_CHAPTER = {
    "chapter_id": "CH210",
    "planned_scene_count": 1,
    "chapter_goal": "Block scene run when POV voice is missing",
    "main_plot_push": "Make the blocker obvious before operators click run",
    "emotional_target": "Reduce avoidable runtime failures",
    "ending_effect": "Stay blocked until source dependencies are restored",
}
DEMO_PREFLIGHT_BLOCKED_SCENE = {
    "scene_id": "CH210_SC01",
    "chapter_id": "CH210",
    "scene_seq": 1,
    "pov_character_id": "CHAR_MISSING",
    "onstage_chars_json": ["CHAR_B"],
    "location": "North archive gate",
    "scene_goal": "Try to run a scene whose POV voice profile is missing",
    "beats_json": ["approach", "inspect", "hesitate"],
    "must_include_text": "missing voice profile should stop the run",
    "target_length_band": "short",
    "scene_type": "investigation",
    "is_chapter_last": 1,
}
DEMO_PREFLIGHT_WARNING_CHAPTER = {
    "chapter_id": "CH211",
    "planned_scene_count": 1,
    "chapter_goal": "Show warnings without blocking scene run",
    "main_plot_push": "Let operators see incomplete author fields early",
    "emotional_target": "Keep the panel informative without hard-stop gating",
    "ending_effect": "Warnings remain visible while run stays available",
}
DEMO_PREFLIGHT_WARNING_SCENE = {
    "scene_id": "CH211_SC01",
    "chapter_id": "CH211",
    "scene_seq": 1,
    "pov_character_id": "",
    "onstage_chars_json": [],
    "location": "",
    "scene_goal": "",
    "beats_json": [],
    "must_include_text": "",
    "target_length_band": "short",
    "scene_type": "bridge",
    "is_chapter_last": 1,
}
CHAPTER_OPS_MARKER_TOKEN = '{{backfill id=F200 text="旧信寄件人线索"}}'
CHAPTER_OPS_CHAPTER = {
    "chapter_id": "CH200",
    "planned_scene_count": 1,
    "chapter_goal": "补齐章节运行治理闭环",
    "main_plot_push": "把 backfill 和 final aggregate 走通",
    "emotional_target": "让卡住的线索重新可操作",
    "ending_effect": "形成新的 final aggregate 摘要",
}
CHAPTER_OPS_SCENES = [
    {
        "scene_id": "CH200_SC01",
        "chapter_id": "CH200",
        "scene_seq": 1,
        "pov_character_id": "CHAR_A",
        "onstage_chars_json": ["CHAR_A", "CHAR_B"],
        "location": "旧城门洞",
        "scene_goal": "把模板 marker 治理成 staged backfill",
        "beats_json": ["重逢", "试探", "收束"],
        "must_include_text": CHAPTER_OPS_MARKER_TOKEN,
        "target_length_band": "short",
        "scene_type": "reunion",
        "is_chapter_last": 1,
    }
]
CHAPTER_OPS_FINAL_SCENE = {
    "row_id": "final_scene_CH200_SC01_seed",
    "scene_id": "CH200_SC01",
    "chapter_id": "CH200",
    "content": f"归档里仍然保留 {CHAPTER_OPS_MARKER_TOKEN}",
    "status": "approved",
    "source_bundle_id": "bundle_chapter_ops_seed",
    "source_bundle_hash": "hash_chapter_ops_seed",
}
CHAPTER_OPS_SCENE_MEMORY = {
    "row_id": "scene_memory_CH200_SC01_seed",
    "scene_id": "CH200_SC01",
    "chapter_id": "CH200",
    "content": f"场景记忆仍然写着 {CHAPTER_OPS_MARKER_TOKEN}",
    "carry_notes_json": [],
    "source_bundle_id": "bundle_chapter_ops_seed",
    "final_scene_row_id": "final_scene_CH200_SC01_seed",
    "source_review_id": None,
    "active_flag": 1,
    "runtime_eligible": 1,
    "runtime_eligibility_basis": "direct_read",
}
CHAPTER_OPS_PENDING_REVIEW = {
    "review_id": "review_chapter_ops_pending",
    "scene_id": "CH200_SC01",
    "chapter_id": "CH200",
    "item_type": "scene_summary",
    "status": "pending",
    "candidate_text": f"待审摘要仍然引用 {CHAPTER_OPS_MARKER_TOKEN}",
    "candidate_payload_json": {
        "lineage_key": "CH200_SC01",
        "scene_id": "CH200_SC01",
        "text": f"待审摘要仍然引用 {CHAPTER_OPS_MARKER_TOKEN}",
    },
    "active_on_approve": 1,
}


def _upsert(session: Any, model: type[Any], identity: str, payload: dict[str, Any]) -> Any:
    row = session.get(model, payload[identity])
    if row is None:
        row = model(**payload)
        session.add(row)
    else:
        for key, value in payload.items():
            setattr(row, key, value)
    return row


def _upsert_chapter(session: Any, payload: dict[str, Any]) -> None:
    _upsert(session, ChapterGoal, "chapter_id", payload)
    # These catalog models intentionally do not expose ORM relationships, so
    # SQLAlchemy cannot infer FK insertion order.  Materialize the parent before
    # the runtime state child while keeping the whole seed operation atomic.
    session.flush()
    _upsert(
        session,
        ChapterState,
        "chapter_id",
        {
            "chapter_id": payload["chapter_id"],
            "current_phase": "drafting",
            "chapter_passed_scene_count": 0,
            "chapter_backfill_pending_count": 0,
            "mid_aggregate_enabled_effective": 0,
            "aggregate_block_reason": "none",
            "manual_hold_reason": None,
            "last_interim_memory_row_id": None,
            "last_final_memory_row_id": None,
        },
    )


def _upsert_scene(session: Any, payload: dict[str, Any]) -> None:
    _upsert(session, SceneCard, "scene_id", payload)
    session.flush()
    _upsert(
        session,
        SceneRunState,
        "scene_id",
        {
            "scene_id": payload["scene_id"],
            "scene_status": "ready",
            "current_bundle_id": None,
            "current_bundle_hash": None,
            "current_neutral_draft_row_id": None,
            "current_style_draft_row_id": None,
            "current_final_scene_row_id": None,
            "current_human_review_event_id": None,
            "current_qc_report_id": None,
            "bundle_build_count": 0,
            "hard_partial_rewrite_count": 0,
            "hard_full_rewrite_count": 0,
            "soft_patch_count": 0,
            "total_attempt_count": 0,
            "attempt_budget": 4,
            "repeat_issue_key": None,
            "repeat_issue_count": 0,
        },
    )


def _upsert_review_item(session: Any, payload: dict[str, Any]) -> None:
    _upsert(session, ReviewItem, "review_id", payload)


def _upsert_version_registry(session: Session, payload: dict[str, Any]) -> None:
    row = session.execute(
        select(VersionRegistry).where(VersionRegistry.physical_row_id == payload["physical_row_id"])
    ).scalar_one_or_none()
    if row is None:
        session.add(VersionRegistry(**payload))
        return
    for key, value in payload.items():
        setattr(row, key, value)


def _delete_alias_if_scope_empty(session: Session, scope: str, scope_ref_id: str) -> None:
    remaining_scope_count = session.scalar(
        select(func.count()).select_from(StyleObservation).where(
            StyleObservation.scope == scope,
            func.coalesce(StyleObservation.scope_ref_id, "global") == scope_ref_id,
        )
    )
    if remaining_scope_count == 0:
        alias = session.get(VectorAliasRegistry, f"style_observation:{scope}:{scope_ref_id}")
        if alias is not None:
            session.delete(alias)


def _cleanup_demo_runtime(session: Session) -> None:
    chapter_id = DEMO_CHAPTER["chapter_id"]
    all_demo_review_ids = [DEMO_STYLE_OBSERVATION_REVIEW["review_id"], *DEMO_RUNTIME_OPS_E2E_REVIEW_IDS]
    all_demo_lineage_keys = [DEMO_STYLE_OBSERVATION_REVIEW["candidate_payload_json"]["lineage_key"], *DEMO_RUNTIME_OPS_E2E_STYLE_IDS]
    demo_registry_lineage_keys = [
        *all_demo_lineage_keys,
        *[item["lineage_key"] for item in DEMO_KNOWLEDGE_VERSION_REGISTRIES],
    ]
    all_demo_style_row_ids = [
        "style_observation_STY_DEMO_001_v1",
        *DEMO_RUNTIME_OPS_E2E_STYLE_ROW_IDS,
    ]
    demo_knowledge_row_ids = [
        *all_demo_style_row_ids,
        *[item["row_id"] for item in DEMO_STYLE_RULES],
        *[item["row_id"] for item in DEMO_BANNED_RULE_CLUSTERS],
        *[item["row_id"] for item in DEMO_WORLD_RULES],
        *[item["row_id"] for item in DEMO_CALIBRATION_LINES],
        *[item["row_id"] for item in DEMO_FORESHADOW_TRACKERS],
        *[item["row_id"] for item in DEMO_SCENE_SUMMARIES],
        *[item["row_id"] for item in DEMO_CHAPTER_SUMMARIES],
    ]
    all_demo_job_ids = [
        "reindex_review_demo_style_observation",
        "verify_review_demo_style_observation",
        *DEMO_RUNTIME_OPS_E2E_JOB_IDS,
    ]
    all_demo_operation_refs = [
        *all_demo_review_ids,
        *all_demo_style_row_ids,
        *all_demo_job_ids,
        DEMO_RUNTIME_OPS_E2E_RECOVERY_IDEMPOTENCY_KEY,
        *DEMO_RUNTIME_OPS_E2E_EVENT_IDS,
    ]
    demo_voice_ids = [item["voice_profile_id"] for item in DEMO_VOICE_PROFILES]
    demo_relation_ids = [item["relation_profile_id"] for item in DEMO_RELATION_PROFILES]

    session.execute(delete(AttemptTracker).where(AttemptTracker.chapter_id == chapter_id))
    session.execute(delete(SceneBundle).where(SceneBundle.chapter_id == chapter_id))
    session.execute(delete(SceneDraft).where(SceneDraft.chapter_id == chapter_id))
    session.execute(delete(FinalScene).where(FinalScene.chapter_id == chapter_id))
    session.execute(delete(SceneMemory).where(SceneMemory.chapter_id == chapter_id))
    session.execute(delete(ChapterMemory).where(ChapterMemory.chapter_id == chapter_id))
    session.execute(delete(ChapterRollingNote).where(ChapterRollingNote.chapter_id == chapter_id))
    session.execute(delete(StagedBackfill).where(StagedBackfill.chapter_id == chapter_id))
    session.execute(delete(HumanReviewEvent).where(HumanReviewEvent.chapter_id == chapter_id))
    session.execute(delete(OperationLog).where(OperationLog.object_ref.in_(all_demo_operation_refs)))
    session.execute(delete(IdempotencyKey).where(IdempotencyKey.idempotency_key == DEMO_RUNTIME_OPS_E2E_RECOVERY_IDEMPOTENCY_KEY))
    session.execute(
        delete(ReindexJob).where(
            or_(
                ReindexJob.review_id.in_(all_demo_review_ids),
                ReindexJob.job_id.in_(all_demo_job_ids),
            )
        )
    )
    session.execute(
        delete(VerifyJob).where(
            or_(
                VerifyJob.review_id.in_(all_demo_review_ids),
                VerifyJob.job_id.in_(all_demo_job_ids),
            )
        )
    )
    session.execute(
        delete(VersionRegistry).where(
            or_(
                VersionRegistry.lineage_key.in_(demo_registry_lineage_keys),
                VersionRegistry.physical_row_id.in_(demo_knowledge_row_ids),
            )
        )
    )
    session.execute(
        delete(StyleObservation).where(
            or_(
                StyleObservation.style_observation_id.in_(all_demo_lineage_keys),
                StyleObservation.source_review_id.in_(all_demo_review_ids),
                StyleObservation.row_id.in_(all_demo_style_row_ids),
            )
        )
    )
    session.execute(delete(ReviewItem).where(ReviewItem.review_id.in_(DEMO_RUNTIME_OPS_E2E_REVIEW_IDS)))
    session.execute(delete(VoiceProfile).where(VoiceProfile.voice_profile_id.in_(demo_voice_ids)))
    session.execute(delete(RelationProfile).where(RelationProfile.relation_profile_id.in_(demo_relation_ids)))
    session.execute(delete(StyleRule).where(StyleRule.style_rule_set_id.in_([item["style_rule_set_id"] for item in DEMO_STYLE_RULES])))
    session.execute(
        delete(BannedRuleCluster).where(
            BannedRuleCluster.banned_cluster_id.in_([item["banned_cluster_id"] for item in DEMO_BANNED_RULE_CLUSTERS])
        )
    )
    session.execute(delete(WorldRule).where(WorldRule.world_rule_id.in_([item["world_rule_id"] for item in DEMO_WORLD_RULES])))
    session.execute(
        delete(CalibrationLine).where(
            CalibrationLine.calibration_line_id.in_([item["calibration_line_id"] for item in DEMO_CALIBRATION_LINES])
        )
    )
    session.execute(
        delete(ForeshadowTracker).where(
            ForeshadowTracker.foreshadow_id.in_([item["foreshadow_id"] for item in DEMO_FORESHADOW_TRACKERS])
        )
    )

    for scope, scope_ref_id in DEMO_RUNTIME_OPS_E2E_ALIAS_SCOPES:
        _delete_alias_if_scope_empty(session, scope, scope_ref_id)
    session.execute(
        delete(VectorAliasRegistry).where(VectorAliasRegistry.alias_scope == DEMO_CALIBRATION_ALIAS["alias_scope"])
    )


def _seed_runtime_ops_e2e(session: Session) -> list[str]:
    _upsert_review_item(session, DEMO_RUNTIME_OPS_E2E_DUE_PROMOTION_REVIEW)
    _upsert_review_item(session, DEMO_RUNTIME_OPS_E2E_RECOVERY_REVIEW)
    _upsert(session, StyleObservation, "row_id", DEMO_RUNTIME_OPS_E2E_DUE_PROMOTION_ACTIVE_ROW)
    _upsert(session, StyleObservation, "row_id", DEMO_RUNTIME_OPS_E2E_DUE_PROMOTION_ROW)
    _upsert_version_registry(session, DEMO_RUNTIME_OPS_E2E_DUE_PROMOTION_REGISTRY)
    _upsert(session, VectorAliasRegistry, "alias_scope", DEMO_RUNTIME_OPS_E2E_DUE_PROMOTION_ALIAS)
    _upsert(session, VerifyJob, "job_id", DEMO_RUNTIME_OPS_E2E_RECLAIMABLE_VERIFY_JOB)
    _upsert(session, VerifyJob, "job_id", DEMO_RUNTIME_OPS_E2E_FAILED_VERIFY_JOB)
    _upsert(
        session,
        IdempotencyKey,
        "idempotency_key",
        {
            "idempotency_key": DEMO_RUNTIME_OPS_E2E_RECOVERY_IDEMPOTENCY_KEY,
            "request_hash": DEMO_RUNTIME_OPS_E2E_RECOVERY_REQUEST_HASH,
            "status": "started",
            "response_json": None,
            "worker_id": "http",
            "attempt_no": 2,
            "heartbeat_at": "2026-04-09T16:00:00+00:00",
            "lease_expires_at": "2000-01-01T00:00:00+00:00",
        },
    )
    session.add(
        OperationLog(
            event_type="idempotency_started",
            object_type="idempotency_key",
            object_ref=DEMO_RUNTIME_OPS_E2E_RECOVERY_IDEMPOTENCY_KEY,
            payload_json={
                "request_hash": DEMO_RUNTIME_OPS_E2E_RECOVERY_REQUEST_HASH,
                "request_method": "POST",
                "request_path_template": "/api/v1/review-items/{review_id}/approve",
                "request_payload": DEMO_RUNTIME_OPS_E2E_RECOVERY_REQUEST_PAYLOAD,
                "attempt_no": 2,
                "actor_ref": "system/e2e_fixture",
            },
        )
    )
    return [
        DEMO_RUNTIME_OPS_E2E_DUE_PROMOTION_REVIEW["review_id"],
        DEMO_RUNTIME_OPS_E2E_RECOVERY_REVIEW["review_id"],
    ]


def _cleanup_chapter_ops_runtime(session: Session) -> None:
    chapter_id = CHAPTER_OPS_CHAPTER["chapter_id"]
    scene_ids = [item["scene_id"] for item in CHAPTER_OPS_SCENES]

    session.execute(delete(AttemptTracker).where(AttemptTracker.chapter_id == chapter_id))
    session.execute(delete(SceneBundle).where(SceneBundle.chapter_id == chapter_id))
    session.execute(delete(SceneDraft).where(SceneDraft.chapter_id == chapter_id))
    session.execute(delete(FinalScene).where(FinalScene.chapter_id == chapter_id))
    session.execute(delete(SceneMemory).where(SceneMemory.chapter_id == chapter_id))
    session.execute(delete(ChapterMemory).where(ChapterMemory.chapter_id == chapter_id))
    session.execute(delete(ChapterRollingNote).where(ChapterRollingNote.chapter_id == chapter_id))
    session.execute(delete(StagedBackfill).where(StagedBackfill.chapter_id == chapter_id))
    session.execute(delete(HumanReviewEvent).where(HumanReviewEvent.chapter_id == chapter_id))
    session.execute(delete(ReviewItem).where(ReviewItem.chapter_id == chapter_id))
    session.execute(delete(ForeshadowTracker).where(ForeshadowTracker.chapter_id == chapter_id))
    session.execute(delete(SceneRunState).where(SceneRunState.scene_id.in_(scene_ids)))
    session.execute(delete(SceneCard).where(SceneCard.scene_id.in_(scene_ids)))
    session.execute(delete(ChapterState).where(ChapterState.chapter_id == chapter_id))
    session.execute(delete(ChapterGoal).where(ChapterGoal.chapter_id == chapter_id))


def _cleanup_preflight_e2e_runtime(session: Session) -> None:
    chapter_ids = [
        DEMO_PREFLIGHT_BLOCKED_CHAPTER["chapter_id"],
        DEMO_PREFLIGHT_WARNING_CHAPTER["chapter_id"],
    ]
    scene_ids = [
        DEMO_PREFLIGHT_BLOCKED_SCENE["scene_id"],
        DEMO_PREFLIGHT_WARNING_SCENE["scene_id"],
    ]

    session.execute(delete(AttemptTracker).where(AttemptTracker.chapter_id.in_(chapter_ids)))
    session.execute(delete(SceneBundle).where(SceneBundle.chapter_id.in_(chapter_ids)))
    session.execute(delete(SceneDraft).where(SceneDraft.chapter_id.in_(chapter_ids)))
    session.execute(delete(FinalScene).where(FinalScene.chapter_id.in_(chapter_ids)))
    session.execute(delete(SceneMemory).where(SceneMemory.chapter_id.in_(chapter_ids)))
    session.execute(delete(ChapterMemory).where(ChapterMemory.chapter_id.in_(chapter_ids)))
    session.execute(delete(ChapterRollingNote).where(ChapterRollingNote.chapter_id.in_(chapter_ids)))
    session.execute(delete(StagedBackfill).where(StagedBackfill.chapter_id.in_(chapter_ids)))
    session.execute(delete(HumanReviewEvent).where(HumanReviewEvent.chapter_id.in_(chapter_ids)))
    session.execute(delete(ReviewItem).where(ReviewItem.chapter_id.in_(chapter_ids)))
    session.execute(delete(ForeshadowTracker).where(ForeshadowTracker.chapter_id.in_(chapter_ids)))
    session.execute(delete(SceneRunState).where(SceneRunState.scene_id.in_(scene_ids)))
    session.execute(delete(SceneCard).where(SceneCard.scene_id.in_(scene_ids)))
    session.execute(delete(ChapterState).where(ChapterState.chapter_id.in_(chapter_ids)))
    session.execute(delete(ChapterGoal).where(ChapterGoal.chapter_id.in_(chapter_ids)))


def _seed_chapter_ops_e2e(session: Session) -> dict[str, list[str] | str]:
    _cleanup_chapter_ops_runtime(session)
    _upsert_chapter(session, CHAPTER_OPS_CHAPTER)
    for payload in CHAPTER_OPS_SCENES:
        _upsert_scene(session, payload)
    session.flush()
    _upsert(session, FinalScene, "row_id", CHAPTER_OPS_FINAL_SCENE)
    _upsert(session, SceneMemory, "row_id", CHAPTER_OPS_SCENE_MEMORY)
    _upsert_review_item(session, CHAPTER_OPS_PENDING_REVIEW)

    scene_state = session.get(SceneRunState, CHAPTER_OPS_SCENES[0]["scene_id"])
    if scene_state is not None:
        scene_state.scene_status = "archived"
        scene_state.current_final_scene_row_id = CHAPTER_OPS_FINAL_SCENE["row_id"]

    return {
        "chapter_id": CHAPTER_OPS_CHAPTER["chapter_id"],
        "scene_ids": [item["scene_id"] for item in CHAPTER_OPS_SCENES],
        "review_ids": [CHAPTER_OPS_PENDING_REVIEW["review_id"]],
    }


def _seed_preflight_e2e(session: Session) -> dict[str, list[str]]:
    _cleanup_preflight_e2e_runtime(session)
    _upsert_chapter(session, DEMO_PREFLIGHT_BLOCKED_CHAPTER)
    _upsert_scene(session, DEMO_PREFLIGHT_BLOCKED_SCENE)
    _upsert_chapter(session, DEMO_PREFLIGHT_WARNING_CHAPTER)
    _upsert_scene(session, DEMO_PREFLIGHT_WARNING_SCENE)
    return {
        "chapter_ids": [
            DEMO_PREFLIGHT_BLOCKED_CHAPTER["chapter_id"],
            DEMO_PREFLIGHT_WARNING_CHAPTER["chapter_id"],
        ],
        "scene_ids": [
            DEMO_PREFLIGHT_BLOCKED_SCENE["scene_id"],
            DEMO_PREFLIGHT_WARNING_SCENE["scene_id"],
        ],
    }


def _seed_demo(session: Session, *, fixture: str | None = None) -> dict[str, list[str] | str]:
    # FE-ALIGN P2: 两部种子作品（潮汐档案/盐镇来信）后端化（独立模块，自带幂等清理）。
    from novel_system.tools.seed_fe_demo_works import seed_fe_demo_works

    seed_fe_demo_works(session)
    _cleanup_demo_runtime(session)
    _upsert(session, StoryProject, "project_id", DEMO_PROJECT)
    session.flush()
    _upsert_chapter(session, DEMO_CHAPTER)
    for payload in DEMO_SCENES:
        _upsert_scene(session, payload)
    for payload in DEMO_VOICE_PROFILES:
        _upsert(session, VoiceProfile, "row_id", payload)
    for payload in DEMO_RELATION_PROFILES:
        _upsert(session, RelationProfile, "row_id", payload)
    for payload in DEMO_STYLE_RULES:
        _upsert(session, StyleRule, "row_id", payload)
    for payload in DEMO_BANNED_RULE_CLUSTERS:
        _upsert(session, BannedRuleCluster, "row_id", payload)
    for payload in DEMO_WORLD_RULES:
        _upsert(session, WorldRule, "row_id", payload)
    for payload in DEMO_CALIBRATION_LINES:
        _upsert(session, CalibrationLine, "row_id", payload)
    for payload in DEMO_FORESHADOW_TRACKERS:
        _upsert(session, ForeshadowTracker, "row_id", payload)
    for payload in DEMO_SCENE_SUMMARIES:
        _upsert(session, SceneMemory, "row_id", payload)
    for payload in DEMO_CHAPTER_SUMMARIES:
        _upsert(session, ChapterMemory, "row_id", payload)
    for payload in DEMO_KNOWLEDGE_VERSION_REGISTRIES:
        _upsert_version_registry(session, payload)
    _upsert(session, VectorAliasRegistry, "alias_scope", DEMO_CALIBRATION_ALIAS)
    _upsert_review_item(session, DEMO_STYLE_OBSERVATION_REVIEW)
    review_ids = [DEMO_STYLE_OBSERVATION_REVIEW["review_id"]]
    extra_chapter_ids: list[str] = []
    extra_scene_ids: list[str] = []
    extra_review_ids: list[str] = []
    if fixture is None:
        pass
    elif fixture == DEMO_RUNTIME_OPS_E2E_FIXTURE:
        review_ids.extend(_seed_runtime_ops_e2e(session))
    elif fixture == DEMO_CHAPTER_OPS_E2E_FIXTURE:
        chapter_ops_summary = _seed_chapter_ops_e2e(session)
        extra_chapter_ids.append(chapter_ops_summary["chapter_id"])
        extra_scene_ids.extend(chapter_ops_summary["scene_ids"])
        extra_review_ids.extend(chapter_ops_summary["review_ids"])
    elif fixture == DEMO_ALL_E2E_FIXTURE:
        review_ids.extend(_seed_runtime_ops_e2e(session))
        chapter_ops_summary = _seed_chapter_ops_e2e(session)
        preflight_summary = _seed_preflight_e2e(session)
        extra_chapter_ids.append(chapter_ops_summary["chapter_id"])
        extra_chapter_ids.extend(preflight_summary["chapter_ids"])
        extra_scene_ids.extend(chapter_ops_summary["scene_ids"])
        extra_scene_ids.extend(preflight_summary["scene_ids"])
        extra_review_ids.extend(chapter_ops_summary["review_ids"])
    else:
        raise ValueError(f"Unsupported demo fixture: {fixture}")
    summary = {
        "chapter_id": DEMO_CHAPTER["chapter_id"],
        "scene_ids": [item["scene_id"] for item in DEMO_SCENES],
        "review_ids": review_ids,
    }
    if extra_chapter_ids:
        summary["extra_chapter_ids"] = extra_chapter_ids
        summary["extra_scene_ids"] = extra_scene_ids
        summary["extra_review_ids"] = extra_review_ids
    return summary


def seed_demo(session: Session | None = None, *, fixture: str | None = None) -> dict[str, list[str] | str]:
    if session is not None:
        return _seed_demo(session, fixture=fixture)

    with SessionLocal() as managed_session:
        summary = _seed_demo(managed_session, fixture=fixture)
        managed_session.commit()
        return summary


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture", choices=[DEMO_RUNTIME_OPS_E2E_FIXTURE, DEMO_CHAPTER_OPS_E2E_FIXTURE, DEMO_ALL_E2E_FIXTURE])
    args = parser.parse_args(argv)
    print(json.dumps(seed_demo(fixture=args.fixture), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
