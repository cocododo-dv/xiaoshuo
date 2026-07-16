from __future__ import annotations

import threading
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import (
    Boolean,
    JSON,
    CheckConstraint,
    Computed,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from novel_system.accounting_contract import DEFAULT_PROVIDER_ATTEMPT_BUDGET
from novel_system.db.base import Base


_utcnow_lock = threading.Lock()
_utcnow_last = datetime.min.replace(tzinfo=UTC)


def utcnow() -> str:
    """进程内严格单调的 UTC ISO 时间戳。

    Windows 时钟粒度粗，连续插入常落入同一 tick，按 created_at 排序会
    退化为随机主键序；同 tick 时微秒 +1 兜底，保证排序确定。
    """
    global _utcnow_last
    with _utcnow_lock:
        now = datetime.now(UTC)
        if now <= _utcnow_last:
            now = _utcnow_last + timedelta(microseconds=1)
        _utcnow_last = now
        return now.isoformat()


class StoryProject(Base):
    __tablename__ = "story_projects"

    project_id: Mapped[str] = mapped_column(String, primary_key=True)
    title: Mapped[str] = mapped_column(String)
    genre: Mapped[str | None] = mapped_column(String, nullable=True)
    target_word_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    target_chapter_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # FE-ALIGN P2: 作品档案字段（原型 WsWorks 作品对象 mark/accent/sub/今日目标）。
    mark: Mapped[str | None] = mapped_column(String, nullable=True)
    accent: Mapped[str | None] = mapped_column(String, nullable=True)
    synopsis_line: Mapped[str | None] = mapped_column(Text, nullable=True)
    words_target_daily: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_demo: Mapped[int] = mapped_column(Integer, default=0)
    outline_text: Mapped[str] = mapped_column(Text)
    planning_mode: Mapped[str] = mapped_column(String, default="outline_driven")
    snowflake_schema_version: Mapped[str | None] = mapped_column(String, nullable=True)
    snowflake_workflow_mode: Mapped[str] = mapped_column(String, default="strict")
    status: Mapped[str] = mapped_column(String, default="outline_draft")
    active_outline_plan_id: Mapped[str | None] = mapped_column(String, nullable=True)
    current_chapter_id: Mapped[str | None] = mapped_column(String, nullable=True)
    approved_chapter_ids_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    # FE-ALIGN P4: 作品级软删（沿用章/场景 trash 的列名约定；级联只动可见性不动数据）
    trashed_flag: Mapped[int] = mapped_column(Integer, default=0)
    trashed_at: Mapped[str | None] = mapped_column(String, nullable=True)
    trashed_by: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[str] = mapped_column(String, default=utcnow)
    updated_at: Mapped[str] = mapped_column(String, default=utcnow, onupdate=utcnow)


class ProjectWritingStats(Base):
    """FE-ALIGN P2: 每个项目一行的写作统计（D2：服务端计算，Asia/Shanghai）。

    today/streak 规则照抄原型 ws-catalog.jsx 的 catAddToday/catBumpStreak/
    catEffectiveStreak：当天首次正向增量记账；昨天也写过 +1 否则重记 1；
    断更超一天展示为 0（展示态在服务层算，不落库）。
    """

    __tablename__ = "project_writing_stats"

    project_id: Mapped[str] = mapped_column(
        ForeignKey("story_projects.project_id"), primary_key=True
    )
    words_total: Mapped[int] = mapped_column(Integer, default=0)
    day: Mapped[str | None] = mapped_column(String, nullable=True)
    words_today: Mapped[int] = mapped_column(Integer, default=0)
    streak_last_day: Mapped[str | None] = mapped_column(String, nullable=True)
    streak_days: Mapped[int] = mapped_column(Integer, default=0)
    last_active_at: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[str] = mapped_column(String, default=utcnow)
    updated_at: Mapped[str] = mapped_column(String, default=utcnow, onupdate=utcnow)


class OutlinePlan(Base):
    __tablename__ = "outline_plans"

    plan_id: Mapped[str] = mapped_column(String, primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("story_projects.project_id"))
    version: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String, default="pending_review")
    plan_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[str] = mapped_column(String, default=utcnow)
    approved_at: Mapped[str | None] = mapped_column(String, nullable=True)
    updated_at: Mapped[str] = mapped_column(String, default=utcnow, onupdate=utcnow)


class SnowflakeArtifact(Base):
    __tablename__ = "snowflake_artifacts"

    artifact_id: Mapped[str] = mapped_column(String, primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("story_projects.project_id"))
    step_key: Mapped[str] = mapped_column(String)
    version: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String, default="pending_review")
    artifact_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    input_refs_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    # P0-3: per-upstream content signatures captured at approval ("what I consumed,
    # at what version"). Powers dependency/diff-aware staleness instead of marking
    # every downstream step stale on any upstream change.
    consumed_input_sigs_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    diagnosis_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    llm_call_id: Mapped[str | None] = mapped_column(String, nullable=True)
    approved_at: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[str] = mapped_column(String, default=utcnow)
    updated_at: Mapped[str] = mapped_column(String, default=utcnow, onupdate=utcnow)


class SnowflakeStepRun(Base):
    __tablename__ = "snowflake_step_runs"

    step_run_id: Mapped[str] = mapped_column(String, primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("story_projects.project_id"))
    step_key: Mapped[str] = mapped_column(String)
    version: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String, default="pending_review")
    draft_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    health_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True, default=dict)
    input_refs_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    # P0-3: per-upstream content signatures captured at approval — see SnowflakeArtifact.
    consumed_input_sigs_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    stale_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    stale_accepted_at: Mapped[str | None] = mapped_column(String, nullable=True)
    stale_accepted_by: Mapped[str | None] = mapped_column(String, nullable=True)
    stale_accepted_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    llm_call_id: Mapped[str | None] = mapped_column(String, nullable=True)
    approved_at: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[str] = mapped_column(String, default=utcnow)
    updated_at: Mapped[str] = mapped_column(String, default=utcnow, onupdate=utcnow)

    @property
    def artifact_json(self) -> dict[str, Any]:
        return self.draft_json or {}


class SnowflakeAssistantTurn(Base):
    __tablename__ = "snowflake_assistant_turns"

    turn_id: Mapped[str] = mapped_column(String, primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("story_projects.project_id"))
    step_key: Mapped[str] = mapped_column(String)
    focus_scene_id: Mapped[str | None] = mapped_column(String, nullable=True)
    user_message: Mapped[str] = mapped_column(Text)
    reply: Mapped[str] = mapped_column(Text)
    suggestions_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    candidate_label: Mapped[str | None] = mapped_column(String, nullable=True)
    candidate_patch_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True, default=dict)
    source: Mapped[str] = mapped_column(String, default="fallback")
    llm_call_id: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[str] = mapped_column(String, default=utcnow)


class SnowflakeCharacterPlan(Base):
    __tablename__ = "snowflake_character_plans"

    character_plan_id: Mapped[str] = mapped_column(String, primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("story_projects.project_id"))
    character_id: Mapped[str] = mapped_column(String)
    display_name: Mapped[str] = mapped_column(String)
    role: Mapped[str | None] = mapped_column(String, nullable=True)
    summary_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True, default=dict)
    synopsis_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True, default=dict)
    bible_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True, default=dict)
    source_step_key: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String, default="draft")
    stale_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[str] = mapped_column(String, default=utcnow)
    updated_at: Mapped[str] = mapped_column(String, default=utcnow, onupdate=utcnow)


class SnowflakeScenePlan(Base):
    __tablename__ = "snowflake_scene_plans"
    __table_args__ = (
        # P1-1: immutable, system-minted row identity. Scene identity is no longer
        # derived from the author-editable ``scene_id`` — ``row_uid`` is the stable
        # anchor the staleness diff (P0-3) relies on.
        Index("ix_snowflake_scene_plans_row_uid", "project_id", "row_uid", unique=True),
    )

    scene_plan_id: Mapped[str] = mapped_column(String, primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("story_projects.project_id"))
    row_uid: Mapped[str | None] = mapped_column(String, nullable=True)
    scene_id: Mapped[str] = mapped_column(String)
    chapter_id: Mapped[str] = mapped_column(String)
    chapter_title: Mapped[str | None] = mapped_column(String, nullable=True)
    chapter_goal: Mapped[str | None] = mapped_column(Text, nullable=True)
    chapter_role: Mapped[str | None] = mapped_column(Text, nullable=True)
    scene_seq: Mapped[int] = mapped_column(Integer, default=1)
    pov_character_id: Mapped[str | None] = mapped_column(String, nullable=True)
    onstage_chars_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    title: Mapped[str | None] = mapped_column(String, nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    scene_type: Mapped[str] = mapped_column(String, default="proactive")
    location: Mapped[str | None] = mapped_column(String, nullable=True)
    scene_crucible: Mapped[str | None] = mapped_column(Text, nullable=True)
    goal: Mapped[str | None] = mapped_column(Text, nullable=True)
    conflict: Mapped[str | None] = mapped_column(Text, nullable=True)
    setback: Mapped[str | None] = mapped_column(Text, nullable=True)
    reaction: Mapped[str | None] = mapped_column(Text, nullable=True)
    dilemma: Mapped[str | None] = mapped_column(Text, nullable=True)
    decision: Mapped[str | None] = mapped_column(Text, nullable=True)
    beats_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    must_include_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    exit_change: Mapped[str | None] = mapped_column(Text, nullable=True)
    hook: Mapped[str | None] = mapped_column(Text, nullable=True)
    tension_target: Mapped[int | None] = mapped_column(Integer, nullable=True)
    function_tag: Mapped[str | None] = mapped_column(String, nullable=True)
    involved_foreshadowing_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    causal_prerequisite_scene_id: Mapped[str | None] = mapped_column(String, nullable=True)
    cost_requirement: Mapped[str | None] = mapped_column(Text, nullable=True)
    downstream_obligations_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    target_length_band: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String, default="draft")
    source_step_run_id: Mapped[str | None] = mapped_column(String, nullable=True)
    stale_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    stale_accepted_at: Mapped[str | None] = mapped_column(String, nullable=True)
    stale_accepted_by: Mapped[str | None] = mapped_column(String, nullable=True)
    stale_accepted_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    diagnosis_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True, default=dict)
    created_at: Mapped[str] = mapped_column(String, default=utcnow)
    updated_at: Mapped[str] = mapped_column(String, default=utcnow, onupdate=utcnow)


class SnowflakeSceneTriageItem(Base):
    __tablename__ = "snowflake_scene_triage_items"

    triage_id: Mapped[str] = mapped_column(String, primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("story_projects.project_id"))
    scene_plan_id: Mapped[str] = mapped_column(ForeignKey("snowflake_scene_plans.scene_plan_id"))
    scene_id: Mapped[str] = mapped_column(String)
    recommended_status: Mapped[str] = mapped_column(String, default="")
    manual_status: Mapped[str] = mapped_column(String, default="")
    effective_status: Mapped[str] = mapped_column(String, default="")
    score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    missing_fields_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    fix_steps_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    repair_patch_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    pressure_flags_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    blocking: Mapped[int] = mapped_column(Integer, default=0)
    manual_override: Mapped[int] = mapped_column(Integer, default=0)
    llm_call_id: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[str] = mapped_column(String, default=utcnow)
    updated_at: Mapped[str] = mapped_column(String, default=utcnow, onupdate=utcnow)


class SnowflakeRevisionLink(Base):
    __tablename__ = "snowflake_revision_links"

    revision_link_id: Mapped[str] = mapped_column(String, primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("story_projects.project_id"))
    source_step_key: Mapped[str] = mapped_column(String)
    source_step_run_id: Mapped[str | None] = mapped_column(String, nullable=True)
    affected_kind: Mapped[str] = mapped_column(String)
    affected_id: Mapped[str] = mapped_column(String)
    reason: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String, default="open")
    created_at: Mapped[str] = mapped_column(String, default=utcnow)
    resolved_at: Mapped[str | None] = mapped_column(String, nullable=True)


class StoryCharacter(Base):
    __tablename__ = "story_characters"

    character_id: Mapped[str] = mapped_column(String, primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("story_projects.project_id"))
    display_name: Mapped[str] = mapped_column(String)
    role: Mapped[str | None] = mapped_column(String, nullable=True)
    summary_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    synopsis_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    bible_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String, default="draft")
    created_at: Mapped[str] = mapped_column(String, default=utcnow)
    updated_at: Mapped[str] = mapped_column(String, default=utcnow, onupdate=utcnow)


class LongformAnchor(Base):
    """控制塔锚点 — 全书必须保持为真的长程事实(强约束记忆)。

    kind 字符串常量:fact / trait / setting / timeline;
    status:pinned(在场)/ faded(淡出,可重新钉入)。
    """

    __tablename__ = "longform_anchors"
    __table_args__ = (Index("ix_longform_anchors_project", "project_id"),)

    anchor_id: Mapped[str] = mapped_column(String, primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("story_projects.project_id"))
    kind: Mapped[str] = mapped_column(String, default="fact")
    text: Mapped[str] = mapped_column(Text)
    source_ref: Mapped[str | None] = mapped_column(String, nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String, default="pinned")
    created_at: Mapped[str] = mapped_column(String, default=utcnow)
    updated_at: Mapped[str] = mapped_column(String, default=utcnow, onupdate=utcnow)


class ChapterContract(Base):
    """控制塔交接契约 — 塔在生成/写作一章前下发的长程约束包。

    status 闸门:drafting → ready → dispatched → archived;
    constraints_json:[{text, anchor_id?, scene_id?, kind?}, ...]。
    """

    __tablename__ = "chapter_contracts"
    __table_args__ = (Index("ix_chapter_contracts_project", "project_id", "chapter_id"),)

    contract_id: Mapped[str] = mapped_column(String, primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("story_projects.project_id"))
    chapter_id: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String, default="drafting")
    constraints_json: Mapped[list[Any] | None] = mapped_column(JSON, nullable=True, default=list)
    dispatched_at: Mapped[str | None] = mapped_column(String, nullable=True)
    archived_at: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[str] = mapped_column(String, default=utcnow)
    updated_at: Mapped[str] = mapped_column(String, default=utcnow, onupdate=utcnow)


class ChapterAuditFinding(Base):
    """控制塔章级审计发现 — 跨场连续性问题(逐场质检看不见的)。

    kind 八类失控分类学(字符串常量):drift(漂移)/ overdue(逾期)/
    unplanted_reveal(空降)/ causal_break(断链)/ unfair_clue(线索不公平)/
    stall(停滞)/ deflation(泄气)/ arc(弧线);severity:warn / block;
    status:open / adjudicated;decision:accept_fix / defer / dismiss。
    """

    __tablename__ = "chapter_audit_findings"
    __table_args__ = (Index("ix_chapter_audit_project_chapter", "project_id", "chapter_id"),)

    finding_id: Mapped[str] = mapped_column(String, primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("story_projects.project_id"))
    chapter_id: Mapped[str] = mapped_column(String)
    kind: Mapped[str] = mapped_column(String, default="drift")
    severity: Mapped[str] = mapped_column(String, default="warn")
    text: Mapped[str] = mapped_column(Text)
    evidence: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String, default="open")
    decision: Mapped[str | None] = mapped_column(String, nullable=True)
    decision_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[str] = mapped_column(String, default=utcnow)
    updated_at: Mapped[str] = mapped_column(String, default=utcnow, onupdate=utcnow)


class LibraryEntity(Base):
    """资料库实体(地点/物品/阵营/设定等非人物对象)。

    人物的权威实体是 StoryCharacter,不在此表重复;资料库聚合接口
    会把两者合并输出。kind 用字符串常量(不新增 Enum):
    location / item / faction / concept。
    """

    __tablename__ = "library_entities"
    __table_args__ = (Index("ix_library_entities_project", "project_id"),)

    entity_id: Mapped[str] = mapped_column(String, primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("story_projects.project_id"))
    kind: Mapped[str] = mapped_column(String, default="concept")
    name: Mapped[str] = mapped_column(String)
    aliases_json: Mapped[list[Any] | None] = mapped_column(JSON, nullable=True, default=list)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    details_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True, default=dict)
    tags_json: Mapped[list[Any] | None] = mapped_column(JSON, nullable=True, default=list)
    status: Mapped[str] = mapped_column(String, default="active")
    created_at: Mapped[str] = mapped_column(String, default=utcnow)
    updated_at: Mapped[str] = mapped_column(String, default=utcnow, onupdate=utcnow)


class LibraryRelation(Base):
    """资料库关系边。端点用带前缀的 ref:"character:<id>" 或 "entity:<id>"。"""

    __tablename__ = "library_relations"
    __table_args__ = (Index("ix_library_relations_project", "project_id"),)

    relation_id: Mapped[str] = mapped_column(String, primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("story_projects.project_id"))
    from_ref: Mapped[str] = mapped_column(String)
    to_ref: Mapped[str] = mapped_column(String)
    kind: Mapped[str] = mapped_column(String, default="related")
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[str] = mapped_column(String, default=utcnow)
    updated_at: Mapped[str] = mapped_column(String, default=utcnow, onupdate=utcnow)


class TimelineEvent(Base):
    """FE-ALIGN P6: 资料库时间线事件（原型 ws-library 大事记 cat=events）。

    entity_refs_json 元素用带前缀 ref（"character:<id>" / "entity:<id>"），
    chapter_ref 是展示用章标记（如 "CH02" / "贯穿"），不强约束外键。
    """

    __tablename__ = "timeline_events"
    __table_args__ = (Index("ix_timeline_events_project", "project_id"),)

    event_id: Mapped[str] = mapped_column(String, primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("story_projects.project_id"))
    label: Mapped[str] = mapped_column(String)
    time_label: Mapped[str | None] = mapped_column(String, nullable=True)
    chapter_ref: Mapped[str | None] = mapped_column(String, nullable=True)
    entity_refs_json: Mapped[list[Any] | None] = mapped_column(JSON, nullable=True, default=list)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    display_order: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[str] = mapped_column(String, default=utcnow)
    updated_at: Mapped[str] = mapped_column(String, default=utcnow, onupdate=utcnow)


class ChapterGoal(Base):
    __tablename__ = "chapter_goals"
    __table_args__ = (
        Index(
            "ix_chapter_goals_project_display_order",
            "project_id",
            "display_order",
            "chapter_id",
        ),
    )

    chapter_id: Mapped[str] = mapped_column(String, primary_key=True)
    project_id: Mapped[str | None] = mapped_column(ForeignKey("story_projects.project_id"), nullable=True)
    outline_plan_id: Mapped[str | None] = mapped_column(ForeignKey("outline_plans.plan_id"), nullable=True)
    planned_scene_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    mid_aggregate_enabled: Mapped[int] = mapped_column(Integer, default=0)
    chapter_goal: Mapped[str] = mapped_column(Text)
    # FE-ALIGN P3 目录统一：叙事卡（act/tension/pov/entry/exit/promise/drama/threads/title）、
    # 章状态、目标字数、显示顺序（混合 id 格式下不能依赖 chapter_id 字典序）。
    narrative_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    state: Mapped[str] = mapped_column(String, default="planned")
    words_target: Mapped[int | None] = mapped_column(Integer, nullable=True)
    display_order: Mapped[int | None] = mapped_column(Integer, nullable=True)
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
    __table_args__ = (
        Index(
            "ix_scene_cards_project_chapter_seq",
            "project_id",
            "chapter_id",
            "scene_seq",
            "scene_id",
        ),
    )

    scene_id: Mapped[str] = mapped_column(String, primary_key=True)
    chapter_id: Mapped[str] = mapped_column(ForeignKey("chapter_goals.chapter_id"))
    project_id: Mapped[str | None] = mapped_column(ForeignKey("story_projects.project_id"), nullable=True)
    outline_plan_id: Mapped[str | None] = mapped_column(ForeignKey("outline_plans.plan_id"), nullable=True)
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
    # FE-ALIGN P3：场景写作状态（todo/writing/done）与当前正文字数
    # （正文保存时更新；排序复用既有 scene_seq，不另建 display_order）。
    state: Mapped[str] = mapped_column(String, default="todo")
    words_current: Mapped[int] = mapped_column(Integer, default=0)
    # §16 "breathing gap" — author-facing slider; 0.0=free-flow, 1.0=full-rigor, NULL=auto (criticality-based)
    constraint_intensity: Mapped[float | None] = mapped_column(Float, nullable=True, default=None)
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
    __table_args__ = (
        CheckConstraint(
            "scene_tokens_reserved >= 0",
            name="ck_scene_run_states_tokens_reserved_nonnegative",
        ),
        CheckConstraint(
            "provider_attempts_used >= 0",
            name="ck_scene_run_states_provider_attempts_used_nonnegative",
        ),
        CheckConstraint(
            "provider_attempt_budget >= 0",
            name="ck_scene_run_states_provider_attempt_budget_nonnegative",
        ),
    )

    scene_id: Mapped[str] = mapped_column(ForeignKey("scene_cards.scene_id"), primary_key=True)
    scene_status: Mapped[str] = mapped_column(String, default="ready")
    current_bundle_id: Mapped[str | None] = mapped_column(String, nullable=True)
    current_bundle_hash: Mapped[str | None] = mapped_column(String, nullable=True)
    current_neutral_draft_row_id: Mapped[str | None] = mapped_column(String, nullable=True)
    current_style_draft_row_id: Mapped[str | None] = mapped_column(String, nullable=True)
    current_final_scene_row_id: Mapped[str | None] = mapped_column(String, nullable=True)
    # 治理 §4.3：最近有效正文指针——与 current_* 不同，失败/重写路径不清空，
    # 任何后续失败都能回退到该版本（仅项目级运行时失效才重置）
    latest_valid_draft_row_id: Mapped[str | None] = mapped_column(String, nullable=True)
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
    # §6 dispersion signal — last Best-of-N candidate Jaccard dispersion (0.0–1.0)
    candidate_dispersion_score: Mapped[float | None] = mapped_column(Float, nullable=True, default=None)
    # §6 criticality classification result for this run
    criticality_level: Mapped[str | None] = mapped_column(String, nullable=True, default=None)
    criticality_reasons_json: Mapped[list[str] | None] = mapped_column(JSON, nullable=True, default=None)
    # Wave 3（治理 §5.5/§6.1）：运行策略 + 场景 token 预算（与 attempt_budget
    # 次数预算双轨）。预算按场景生命周期累计，自动流程不得重置（§7.12），
    # 扩容唯一入口是作者显式 topup（留审计）。
    run_policy: Mapped[str | None] = mapped_column(String, nullable=True, default=None)
    scene_token_budget: Mapped[int | None] = mapped_column(Integer, nullable=True, default=None)
    scene_tokens_used: Mapped[int] = mapped_column(Integer, default=0)
    scene_tokens_reserved: Mapped[int] = mapped_column(
        Integer,
        default=0,
        server_default="0",
    )
    scene_budget_basis_json: Mapped[dict[str, Any] | None] = mapped_column(
        JSON,
        nullable=True,
        default=None,
    )
    provider_attempts_used: Mapped[int] = mapped_column(
        Integer,
        default=0,
        server_default="0",
    )
    provider_attempt_budget: Mapped[int] = mapped_column(
        Integer,
        default=DEFAULT_PROVIDER_ATTEMPT_BUDGET,
        server_default=str(DEFAULT_PROVIDER_ATTEMPT_BUDGET),
    )
    active_execution_id: Mapped[str | None] = mapped_column(String, nullable=True)
    run_execution_status: Mapped[str | None] = mapped_column(String, nullable=True)
    run_checkpoint: Mapped[str | None] = mapped_column(String, nullable=True)
    run_checkpoint_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    active_run_job_id: Mapped[str | None] = mapped_column(String, nullable=True)
    # 作者稿提升为权威正文后，叙事事件是否已明确与当前 FinalScene 对齐。
    # v1 只允许作者显式确认 facts_unchanged；需要事件重建的稿件不得静默放行。
    narrative_sync_status: Mapped[str] = mapped_column(String, default="synced")
    narrative_sync_final_scene_row_id: Mapped[str | None] = mapped_column(String, nullable=True)
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
    __table_args__ = (Index("ix_scene_bundles_scene", "scene_id"),)

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


class SceneQualityContract(Base):
    __tablename__ = "scene_quality_contracts"
    __table_args__ = (
        CheckConstraint(
            "status IN ('active','superseded')",
            name="ck_scene_quality_contracts_status",
        ),
    )

    contract_id: Mapped[str] = mapped_column(String, primary_key=True)
    scene_id: Mapped[str] = mapped_column(String)
    chapter_id: Mapped[str] = mapped_column(String)
    contract_version: Mapped[str] = mapped_column(String, default="scene_quality_contract_v1")
    contract_hash: Mapped[str] = mapped_column(String)
    source_snapshot_hash: Mapped[str] = mapped_column(String)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String, default="active")
    created_by: Mapped[str] = mapped_column(String, default="scene_quality")
    created_at: Mapped[str] = mapped_column(String, default=utcnow)
    updated_at: Mapped[str] = mapped_column(String, default=utcnow, onupdate=utcnow)


class SceneExecutionContract(Base):
    __tablename__ = "scene_execution_contracts"
    __table_args__ = (
        CheckConstraint(
            "status IN ('active','blocked','stale','superseded')",
            name="ck_scene_execution_contracts_status",
        ),
    )

    contract_id: Mapped[str] = mapped_column(String, primary_key=True)
    scene_id: Mapped[str] = mapped_column(String)
    chapter_id: Mapped[str] = mapped_column(String)
    project_id: Mapped[str | None] = mapped_column(String, nullable=True)
    contract_version: Mapped[str] = mapped_column(String, default="scene_execution_contract_v1")
    source_snapshot_hash: Mapped[str] = mapped_column(String)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    missing_fields_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String, default="active", server_default="active")
    created_by: Mapped[str] = mapped_column(String, default="scene_execution")
    created_at: Mapped[str] = mapped_column(String, default=utcnow)
    updated_at: Mapped[str] = mapped_column(String, default=utcnow, onupdate=utcnow)


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
    __table_args__ = (
        CheckConstraint(
            "estimated_tokens >= 0",
            name="ck_llm_calls_estimated_tokens_nonnegative",
        ),
        CheckConstraint(
            "reserved_tokens >= 0",
            name="ck_llm_calls_reserved_tokens_nonnegative",
        ),
        CheckConstraint(
            "budget_charged_tokens >= 0",
            name="ck_llm_calls_budget_charged_tokens_nonnegative",
        ),
        CheckConstraint(
            "budget_charged_tokens <= reserved_tokens",
            name="ck_llm_calls_budget_charged_within_reservation",
        ),
        CheckConstraint(
            "accounting_status IN ('reserved','settled','failed','released','rejected','usage_exceeds_reservation')",
            name="ck_llm_calls_accounting_status",
        ),
        Index("ix_llm_calls_scene_created", "scene_id", "created_at"),
        Index("ix_llm_calls_scope_created", "scope_type", "scope_id", "created_at"),
        Index("ix_llm_calls_run_job", "run_job_id"),
        Index("ix_llm_calls_execution_step", "execution_id", "execution_step_key"),
        Index(
            "uq_llm_calls_execution_step_claim",
            "execution_id",
            "execution_step_key",
            unique=True,
            sqlite_where=text(
                "execution_id IS NOT NULL AND execution_step_key IS NOT NULL "
                "AND NOT (request_dispatched_at IS NULL "
                "AND accounting_status IN ('released','rejected'))"
            ),
            postgresql_where=text(
                "execution_id IS NOT NULL AND execution_step_key IS NOT NULL "
                "AND NOT (request_dispatched_at IS NULL "
                "AND accounting_status IN ('released','rejected'))"
            ),
        ),
        Index("ix_llm_calls_accounting_status", "accounting_status"),
    )

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
    project_id: Mapped[str | None] = mapped_column(String, nullable=True)
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
    scope_type: Mapped[str] = mapped_column(String)
    scope_id: Mapped[str] = mapped_column(String)
    run_job_id: Mapped[str | None] = mapped_column(String, nullable=True)
    execution_id: Mapped[str | None] = mapped_column(String, nullable=True)
    execution_step_key: Mapped[str | None] = mapped_column(String, nullable=True)
    estimated_tokens: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    reserved_tokens: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    budget_charged_tokens: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    usage_is_estimate: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        server_default="1",
    )
    accounting_status: Mapped[str] = mapped_column(
        String,
        default="reserved",
        server_default="reserved",
    )
    request_dispatched_at: Mapped[str | None] = mapped_column(String, nullable=True)
    settled_at: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[str] = mapped_column(String, default=utcnow)


class LlmCallAttempt(Base):
    __tablename__ = "llm_call_attempts"
    __table_args__ = (
        UniqueConstraint(
            "llm_call_id",
            "provider_attempt_no",
            name="uq_llm_call_attempts_call_ordinal",
        ),
        CheckConstraint(
            "provider_attempt_no >= 0",
            name="ck_llm_call_attempts_provider_attempt_no_nonnegative",
        ),
        CheckConstraint(
            "request_max_output_tokens >= 0",
            name="ck_llm_call_attempts_request_max_output_tokens_nonnegative",
        ),
        CheckConstraint(
            "prompt_tokens >= 0",
            name="ck_llm_call_attempts_prompt_tokens_nonnegative",
        ),
        CheckConstraint(
            "completion_tokens >= 0",
            name="ck_llm_call_attempts_completion_tokens_nonnegative",
        ),
        CheckConstraint(
            "total_tokens >= 0",
            name="ck_llm_call_attempts_total_tokens_nonnegative",
        ),
        CheckConstraint(
            "estimated_tokens >= 0",
            name="ck_llm_call_attempts_estimated_tokens_nonnegative",
        ),
        CheckConstraint(
            "reserved_tokens >= 0",
            name="ck_llm_call_attempts_reserved_tokens_nonnegative",
        ),
        CheckConstraint(
            "budget_charged_tokens >= 0",
            name="ck_llm_call_attempts_budget_charged_tokens_nonnegative",
        ),
        CheckConstraint(
            "budget_charged_tokens <= reserved_tokens",
            name="ck_llm_call_attempts_budget_charged_within_reservation",
        ),
        CheckConstraint(
            "latency_ms >= 0",
            name="ck_llm_call_attempts_latency_ms_nonnegative",
        ),
        CheckConstraint(
            "accounting_status IN ('reserved','settled','failed','released','rejected','usage_exceeds_reservation')",
            name="ck_llm_call_attempts_accounting_status",
        ),
        CheckConstraint(
            "dispatch_kind IN ('initial','transport_retry','response_parse_retry','api_mode_degrade','structured_output_degrade','missing_text_degrade','system_probe')",
            name="ck_llm_call_attempts_dispatch_kind",
        ),
        Index("ix_llm_call_attempts_call_status", "llm_call_id", "accounting_status"),
    )

    attempt_id: Mapped[str] = mapped_column(String, primary_key=True)
    llm_call_id: Mapped[str] = mapped_column(ForeignKey("llm_calls.llm_call_id"))
    provider_attempt_no: Mapped[int] = mapped_column(Integer)
    dispatch_kind: Mapped[str] = mapped_column(String)
    request_max_output_tokens: Mapped[int] = mapped_column(
        Integer,
        default=0,
        server_default="0",
    )
    provider_request_id: Mapped[str | None] = mapped_column(String, nullable=True)
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    total_tokens: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    estimated_tokens: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    reserved_tokens: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    budget_charged_tokens: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    usage_is_estimate: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        server_default="1",
    )
    accounting_status: Mapped[str] = mapped_column(String)
    request_dispatched_at: Mapped[str | None] = mapped_column(String, nullable=True)
    settled_at: Mapped[str | None] = mapped_column(String, nullable=True)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    error_code: Mapped[str | None] = mapped_column(String, nullable=True)
    error_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[str] = mapped_column(String, default=utcnow)


class SceneDraft(Base):
    __tablename__ = "scene_drafts"
    __table_args__ = (Index("ix_scene_drafts_scene", "scene_id"),)

    row_id: Mapped[str] = mapped_column(String, primary_key=True)
    scene_id: Mapped[str] = mapped_column(String)
    chapter_id: Mapped[str] = mapped_column(String)
    stage: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String, default="active", server_default="active")
    content: Mapped[str] = mapped_column(Text)
    source_bundle_id: Mapped[str] = mapped_column(String)
    source_bundle_hash: Mapped[str] = mapped_column(String)
    generation_llm_call_id: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[str] = mapped_column(String, default=utcnow)


class QcReport(Base):
    __tablename__ = "qc_reports"
    __table_args__ = (Index("ix_qc_reports_scene", "scene_id"),)

    qc_report_id: Mapped[str] = mapped_column(String, primary_key=True)
    scene_id: Mapped[str | None] = mapped_column(String, nullable=True)
    chapter_id: Mapped[str | None] = mapped_column(String, nullable=True)
    qc_type: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String, default="active")
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
    failure_class: Mapped[str | None] = mapped_column(String, nullable=True)
    auto_rewrite_eligible: Mapped[int | None] = mapped_column(Integer, nullable=True)
    contract_field_refs_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    promotion_blockers_json: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
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


class AutoRewriteRun(Base):
    __tablename__ = "auto_rewrite_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('diagnosed','candidate_ready','human_review_required','promoted','rolled_back','blocked')",
            name="ck_auto_rewrite_runs_status",
        ),
        CheckConstraint(
            "branch IN ('full_scene','local_patch','human_review','diagnose_only')",
            name="ck_auto_rewrite_runs_branch",
        ),
    )

    run_id: Mapped[str] = mapped_column(String, primary_key=True)
    scene_id: Mapped[str] = mapped_column(String)
    chapter_id: Mapped[str] = mapped_column(String)
    contract_id: Mapped[str | None] = mapped_column(String, nullable=True)
    contract_hash: Mapped[str | None] = mapped_column(String, nullable=True)
    mode: Mapped[str] = mapped_column(String, default="auto")
    branch: Mapped[str] = mapped_column(String)
    failure_class: Mapped[str | None] = mapped_column(String, nullable=True)
    source_final_scene_row_id: Mapped[str | None] = mapped_column(String, nullable=True)
    candidate_draft_row_id: Mapped[str | None] = mapped_column(String, nullable=True)
    promoted_final_scene_row_id: Mapped[str | None] = mapped_column(String, nullable=True)
    rollback_target_final_scene_row_id: Mapped[str | None] = mapped_column(String, nullable=True)
    llm_call_id: Mapped[str | None] = mapped_column(String, nullable=True)
    gate_results_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    policy_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    promotion_blockers_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String)
    actor_ref: Mapped[str] = mapped_column(String, default="operator")
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


class WorkProfile(Base):
    __tablename__ = "work_profiles"
    __table_args__ = (
        CheckConstraint("scope_type IN ('global','chapter')", name="ck_work_profiles_scope_type"),
        CheckConstraint("status IN ('active','archived')", name="ck_work_profiles_status"),
    )

    profile_id: Mapped[str] = mapped_column(String, primary_key=True)
    scope_type: Mapped[str] = mapped_column(String, default="global")
    scope_ref_id: Mapped[str] = mapped_column(String, default="global")
    profile_key: Mapped[str] = mapped_column(String, default="strong_plot")
    display_name: Mapped[str] = mapped_column(String, default="强情节")
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    profile_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String, default="active")
    created_by: Mapped[str] = mapped_column(String, default="author_profile")
    created_at: Mapped[str] = mapped_column(String, default=utcnow)
    updated_at: Mapped[str] = mapped_column(String, default=utcnow, onupdate=utcnow)


class AuthorDraft(Base):
    __tablename__ = "author_drafts"
    __table_args__ = (
        CheckConstraint("object_type IN ('scene','chapter','project')", name="ck_author_drafts_object_type"),
        CheckConstraint("status IN ('current','superseded','archived')", name="ck_author_drafts_status"),
    )

    draft_id: Mapped[str] = mapped_column(String, primary_key=True)
    object_type: Mapped[str] = mapped_column(String)
    object_id: Mapped[str] = mapped_column(String)
    source_text_ref: Mapped[str] = mapped_column(String)
    content: Mapped[str] = mapped_column(Text)
    revision_no: Mapped[int] = mapped_column(Integer, default=1)
    # 草稿保存与权威正文提升是两个独立动作；这两个字段记录最近一次成功提升，
    # 也为 promote-canonical 提供 revision + FinalScene 双重 CAS 的持久化证据。
    last_promoted_revision_no: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_promoted_final_scene_row_id: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String, default="current")
    created_by: Mapped[str] = mapped_column(String, default="author_draft")
    updated_by: Mapped[str] = mapped_column(String, default="author_draft")
    created_at: Mapped[str] = mapped_column(String, default=utcnow)
    updated_at: Mapped[str] = mapped_column(String, default=utcnow, onupdate=utcnow)


class AuthorDraftProposal(Base):
    __tablename__ = "author_draft_proposals"
    __table_args__ = (
        CheckConstraint("object_type IN ('scene','chapter','project')", name="ck_author_draft_proposals_object_type"),
        CheckConstraint(
            "status IN ('candidate','accepted','rejected','superseded')",
            name="ck_author_draft_proposals_status",
        ),
    )

    proposal_id: Mapped[str] = mapped_column(String, primary_key=True)
    draft_id: Mapped[str] = mapped_column(String)
    object_type: Mapped[str] = mapped_column(String)
    object_id: Mapped[str] = mapped_column(String)
    proposal_type: Mapped[str] = mapped_column(String, default="scene_draft")
    proposal_source: Mapped[str] = mapped_column(String, default="single_request")
    content: Mapped[str] = mapped_column(Text)
    rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_llm_call_id: Mapped[str | None] = mapped_column(String, nullable=True)
    target_range_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    before_text_hash: Mapped[str | None] = mapped_column(String, nullable=True)
    replacement_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    proposal_kind: Mapped[str] = mapped_column(String, default="whole_draft")
    source_evaluation_id: Mapped[str | None] = mapped_column(String, nullable=True)
    merge_status: Mapped[str] = mapped_column(String, default="pending")
    status: Mapped[str] = mapped_column(String, default="candidate")
    author_decision_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[str] = mapped_column(String, default="author_draft_proposal")
    created_at: Mapped[str] = mapped_column(String, default=utcnow)
    updated_at: Mapped[str] = mapped_column(String, default=utcnow, onupdate=utcnow)


class AuthorDraftEvent(Base):
    __tablename__ = "author_draft_events"
    __table_args__ = (
        CheckConstraint(
            "event_type IN ("
            "'created','edited','candidate_inserted','candidate_saved','candidate_rejected',"
            "'proposal_applied','proposal_rejected'"
            ")",
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


class AuthorDraftRevision(Base):
    """正文修订快照（FE-ALIGN F2）：每次 revision_no 推进时存一行完整内容。"""

    __tablename__ = "author_draft_revisions"
    __table_args__ = (
        UniqueConstraint("draft_id", "revision_no", name="uq_author_draft_revisions_draft_rev"),
        Index("ix_author_draft_revisions_draft", "draft_id"),
    )

    draft_revision_id: Mapped[str] = mapped_column(String, primary_key=True)
    draft_id: Mapped[str] = mapped_column(String)
    revision_no: Mapped[int] = mapped_column(Integer)
    content: Mapped[str] = mapped_column(Text)
    words: Mapped[int] = mapped_column(Integer, default=0)
    origin: Mapped[str] = mapped_column(String, default="edited")
    created_by: Mapped[str] = mapped_column(String, default="author_draft")
    created_at: Mapped[str] = mapped_column(String, default=utcnow)


class AuthorStructureCandidate(Base):
    __tablename__ = "author_structure_candidates"
    __table_args__ = (
        CheckConstraint("object_type IN ('scene','chapter','project')", name="ck_author_structure_candidates_object_type"),
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
    __table_args__ = (
        Index("ix_final_scenes_scene", "scene_id"),
        Index("ix_final_scenes_chapter", "chapter_id"),
    )

    row_id: Mapped[str] = mapped_column(String, primary_key=True)
    scene_id: Mapped[str] = mapped_column(String)
    chapter_id: Mapped[str] = mapped_column(String)
    content: Mapped[str] = mapped_column(Text)
    content_hash: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String, default="approved")
    source_bundle_id: Mapped[str] = mapped_column(String)
    source_bundle_hash: Mapped[str] = mapped_column(String)
    source_kind: Mapped[str] = mapped_column(String, default="generation")
    source_author_draft_id: Mapped[str | None] = mapped_column(String, nullable=True)
    source_author_draft_revision_no: Mapped[int | None] = mapped_column(Integer, nullable=True)
    parent_final_scene_row_id: Mapped[str | None] = mapped_column(String, nullable=True)
    superseded_by_final_scene_row_id: Mapped[str | None] = mapped_column(String, nullable=True)
    created_by: Mapped[str] = mapped_column(String, default="system")
    generation_llm_call_id: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[str] = mapped_column(String, default=utcnow)


class SceneMemory(Base):
    __tablename__ = "scene_memories"
    __table_args__ = (
        Index("ix_scene_memories_scene", "scene_id"),
        Index("ix_scene_memories_chapter", "chapter_id"),
    )

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
    __table_args__ = (Index("ix_chapter_memories_chapter", "chapter_id"),)

    row_id: Mapped[str] = mapped_column(String, primary_key=True)
    chapter_id: Mapped[str] = mapped_column(String)
    aggregate_stage: Mapped[str] = mapped_column(String)
    content: Mapped[str] = mapped_column(Text)
    # §2 summary tower: "事实从日志查，氛围从摘要读". memory_kind labels how the
    # content may be used downstream — "mixed" (legacy, both), "factual" (state
    # cross-reference only), "atmosphere" (tone/mood far-horizon, never as facts).
    memory_kind: Mapped[str] = mapped_column(String, default="mixed")
    source_review_id: Mapped[str | None] = mapped_column(String, nullable=True)
    active_flag: Mapped[int] = mapped_column(Integer, default=0)
    runtime_eligible: Mapped[int] = mapped_column(Integer, default=0)
    runtime_eligibility_basis: Mapped[str] = mapped_column(String, default="stage_blocked")
    effective_at: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[str] = mapped_column(String, default=utcnow)


class VolumeSummary(Base):
    """§2 summary tower — volume/book-level far-horizon ATMOSPHERE summary.

    Blueprint §2: the summary tower is a read-only auxiliary layer supplying
    far-horizon tone/atmosphere context. It must NEVER be a fact-bearing source —
    facts are projected from the event log. This rolls up chapter memories into a
    volume-level digest used as far-horizon mood context for generation.
    """
    __tablename__ = "volume_summaries"

    row_id: Mapped[str] = mapped_column(String, primary_key=True)
    project_id: Mapped[str] = mapped_column(String)
    volume_seq: Mapped[int] = mapped_column(Integer)
    chapter_id_start: Mapped[str | None] = mapped_column(String, nullable=True)
    chapter_id_end: Mapped[str | None] = mapped_column(String, nullable=True)
    chapter_count: Mapped[int] = mapped_column(Integer, default=0)
    # Atmosphere-only far-horizon context (tone, mood, thematic arc). NOT facts.
    atmosphere_summary: Mapped[str] = mapped_column(Text, default="")
    # Optional structured factual digest derived from event log (state milestones).
    factual_digest: Mapped[str | None] = mapped_column(Text, nullable=True)
    active_flag: Mapped[int] = mapped_column(Integer, default=1)
    runtime_eligible: Mapped[int] = mapped_column(Integer, default=1)
    runtime_eligibility_basis: Mapped[str] = mapped_column(String, default="direct_read")
    created_at: Mapped[str] = mapped_column(String, default=utcnow)
    updated_at: Mapped[str] = mapped_column(String, default=utcnow, onupdate=utcnow)


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
    __table_args__ = (Index("ix_attempt_tracker_scene", "scene_id"),)

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
    __table_args__ = (Index("ix_chapter_run_jobs_scene_created", "scene_id", "created_at"),)

    job_id: Mapped[str] = mapped_column(String, primary_key=True)
    chapter_id: Mapped[str | None] = mapped_column(String, nullable=True)
    scene_id: Mapped[str | None] = mapped_column(String, nullable=True)
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
        # onceTask: 同一作品同一 dedupe_key 只允许一张卡（NULL 不参与唯一性）。
        # 镜像迁移 0050 的唯一索引，使测试的 create_all 与生产迁移同样强制该唯一性。
        Index("ux_review_items_project_dedupe", "project_id", "dedupe_key", unique=True),
        # 审计 P-9 热路径索引（迁移 0060）
        Index("ix_review_items_project_state", "project_id", "state"),
        Index("ix_review_items_scene", "scene_id"),
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
    # FE-ALIGN P5: 待办收件箱卡片模型（原型 ws-review 五类卡；legacy 行这些列为 NULL，
    # 响应里把 status pending/approved/rejected 映射成统一 state open/resolved）。
    # 卡片行 item_type="fe_card"、status 恒 "pending"（CheckConstraint 兼容），生命周期走 state。
    project_id: Mapped[str | None] = mapped_column(String, nullable=True)
    kind: Mapped[str | None] = mapped_column(String, nullable=True)
    priority: Mapped[int | None] = mapped_column(Integer, nullable=True)
    provenance_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    card_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    actions_json: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON, nullable=True)
    state: Mapped[str | None] = mapped_column(String, nullable=True)
    snooze_until: Mapped[str | None] = mapped_column(String, nullable=True)
    resolved_action_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    dedupe_key: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[str] = mapped_column(String, default=utcnow)
    updated_at: Mapped[str] = mapped_column(String, default=utcnow, onupdate=utcnow)


class ReviewDerivedSnooze(Base):
    """FE-ALIGN P5: 实时派生待办的稍后记录（按内容指纹 id 存——指纹变化即重新浮现）。"""

    __tablename__ = "review_derived_snoozes"

    project_id: Mapped[str] = mapped_column(String, primary_key=True)
    fingerprint: Mapped[str] = mapped_column(String, primary_key=True)
    snooze_until: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[str] = mapped_column(String, default=utcnow)


class HumanReviewEvent(Base):
    __tablename__ = "human_review_events"
    __table_args__ = (
        Index("ix_human_review_events_scene", "scene_id"),
        Index("ix_human_review_events_status", "status"),
    )

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


class ProjectBacktrackItem(Base):
    __tablename__ = "project_backtrack_items"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending','resolved','superseded')",
            name="ck_project_backtrack_items_status",
        ),
    )

    item_id: Mapped[str] = mapped_column(String, primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("story_projects.project_id"))
    chapter_id: Mapped[str | None] = mapped_column(String, nullable=True)
    scene_id: Mapped[str | None] = mapped_column(String, nullable=True)
    scope: Mapped[str] = mapped_column(String)
    target_ref: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String, default="pending")
    problem_summary: Mapped[str] = mapped_column(Text)
    recommended_fix: Mapped[str] = mapped_column(Text)
    reason_codes_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    source_qc_report_id: Mapped[str | None] = mapped_column(String, nullable=True)
    source_contract_id: Mapped[str | None] = mapped_column(String, nullable=True)
    resolution_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[str] = mapped_column(String, default="scene_triage")
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
    # Blueprint §5: project-level foreshadow tracking for cross-chapter lifecycle
    project_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    chapter_id: Mapped[str] = mapped_column(String)
    scene_id: Mapped[str | None] = mapped_column(String, nullable=True)
    text: Mapped[str] = mapped_column(Text)
    tracker_status: Mapped[str] = mapped_column(String, default="open")
    theme_tag: Mapped[str | None] = mapped_column(String, nullable=True)
    reinforce_plan_json: Mapped[list[dict] | None] = mapped_column(JSON, nullable=True, default=list)
    plant_method: Mapped[str | None] = mapped_column(Text, nullable=True)
    payoff_method: Mapped[str | None] = mapped_column(Text, nullable=True)
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


class NarrativeEvent(Base):
    """Append-only narrative event log — the single source of truth for story state.

    Every fact about characters, locations, relationships, and information flow
    is recorded as an event tied to a scene. Character state at any point is
    reconstructed by replaying events up to that scene.
    """
    __tablename__ = "narrative_events"

    event_id: Mapped[str] = mapped_column(String, primary_key=True)
    project_id: Mapped[str] = mapped_column(String, index=True)
    scene_id: Mapped[str] = mapped_column(String, index=True)
    chapter_id: Mapped[str] = mapped_column(String, index=True)
    scene_seq: Mapped[int] = mapped_column(Integer, default=0)
    event_type: Mapped[str] = mapped_column(String, index=True)
    entity_type: Mapped[str] = mapped_column(String)
    entity_id: Mapped[str] = mapped_column(String, index=True)
    fact_key: Mapped[str] = mapped_column(String)
    fact_value: Mapped[str] = mapped_column(String)
    confidence: Mapped[str] = mapped_column(String, default="high")
    causal_predecessor_id: Mapped[str | None] = mapped_column(String, nullable=True)
    # Blueprint §2: each event carries theme tags for theme-aware queries
    theme_tags: Mapped[list[str] | None] = mapped_column(JSON, nullable=True, default=list)
    # Blueprint §2: forward-pointing obligation IDs (foreshadow / causal obligations)
    obligation_ids: Mapped[list[str] | None] = mapped_column(JSON, nullable=True, default=list)
    source_text_excerpt: Mapped[str | None] = mapped_column(String, nullable=True)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[str] = mapped_column(String, default=utcnow)

    __table_args__ = (
        Index("ix_narrative_events_entity_scene", "entity_id", "scene_seq"),
        Index("ix_narrative_events_project_scene", "project_id", "scene_seq"),
        Index(
            "ix_narrative_events_project_chapter_scene",
            "project_id",
            "chapter_id",
            "scene_id",
        ),
        Index(
            "ix_narrative_events_project_entity_scene",
            "project_id",
            "entity_id",
            "scene_id",
        ),
    )


class ReconcileFault(Base):
    __tablename__ = "reconcile_faults"

    fault_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    fault_scope: Mapped[str] = mapped_column(String)
    severity: Mapped[str] = mapped_column(String)
    object_ref: Mapped[str] = mapped_column(String)
    details_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[str] = mapped_column(String, default=utcnow)


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


# ---------------------------------------------------------------------------
# Wave 5（结果闭环治理 §6.2）— 质量实验通道：匿名 A/B 人类盲评三张表。
# 实验通道**不写 FinalScene**，只写实验产物；实验失败不影响生产状态（§5.1）。
# ---------------------------------------------------------------------------


class EvaluationExperiment(Base):
    __tablename__ = "evaluation_experiments"

    experiment_id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String)
    hypothesis: Mapped[str] = mapped_column(String, default="")
    treatment_policy_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    control_policy_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String, default="collecting")
    # §6.2 项目隔离：实验快照须与作者近期生产终选场隔离（另建种子项目或时间隔离）。
    isolation_mode: Mapped[str | None] = mapped_column(String, nullable=True)
    snapshot_source_ref: Mapped[str | None] = mapped_column(String, nullable=True)
    # synthetic 默认拒绝进入生产策略门；只有显式声明 human 且冻结题包完整时，
    # 报告才允许给出可执行的默认策略决定。
    evidence_provenance: Mapped[str] = mapped_column(String, default="synthetic")
    # Hidden benchmark contents stay outside the production database.  Only the
    # frozen manifest/rubric hashes are bound to a human blind-evaluation run.
    # Kept as an explicit reference rather than a physical FK because SQLite
    # cannot add that FK to the long-lived experiment table without rebuilding
    # it.  QualityEvidenceService validates the frozen manifest fail-closed.
    benchmark_manifest_id: Mapped[str | None] = mapped_column(String, nullable=True)
    benchmark_manifest_hash: Mapped[str | None] = mapped_column(String, nullable=True)
    hidden_rubric_hash: Mapped[str | None] = mapped_column(String, nullable=True)
    frozen_at: Mapped[str | None] = mapped_column(String, nullable=True)
    frozen_pair_manifest_hash: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[str] = mapped_column(String, default=utcnow)


class EvaluationPair(Base):
    __tablename__ = "evaluation_pairs"

    pair_id: Mapped[str] = mapped_column(String, primary_key=True)
    experiment_id: Mapped[str] = mapped_column(String, index=True)
    # §6.2：每个快照至多一个有效对比对（服务层强制唯一）。
    scene_snapshot_hash: Mapped[str] = mapped_column(String, index=True)
    left_artifact_ref: Mapped[str | None] = mapped_column(String, nullable=True)
    right_artifact_ref: Mapped[str | None] = mapped_column(String, nullable=True)
    # 冻结纯文本——next-pair 直供前端（只出 pair_id + 左右文本）。
    left_text: Mapped[str] = mapped_column(Text, default="")
    right_text: Mapped[str] = mapped_column(Text, default="")
    # 隐藏盲化键：{"treatment_slot": "left"|"right"}。**永不序列化给前端**，投票后 reveal。
    blind_mapping_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    token_cost_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    no_contrast: Mapped[int] = mapped_column(Integer, default=0)
    # 题材标签（可选）：报告分题材差异用；进入冻结清单哈希，冻结后改标签即篡改。
    genre: Mapped[str | None] = mapped_column(String, nullable=True)
    # 场景功能必须参与冻结哈希与分层报告，不能只是展示标签。
    scene_function: Mapped[str | None] = mapped_column(String, nullable=True)
    # Hidden-manifest experiments bind both arms to completed benchmark results
    # for one exact frozen case.  These are service-validated references because
    # SQLite cannot add physical FKs to this long-lived table without rebuilding.
    treatment_benchmark_result_id: Mapped[str | None] = mapped_column(String, nullable=True)
    control_benchmark_result_id: Mapped[str | None] = mapped_column(String, nullable=True)
    benchmark_case_id_hash: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[str] = mapped_column(String, default=utcnow)


class EvaluationVote(Base):
    __tablename__ = "evaluation_votes"

    vote_id: Mapped[str] = mapped_column(String, primary_key=True)
    pair_id: Mapped[str] = mapped_column(String, index=True)
    choice: Mapped[str] = mapped_column(String)  # left | right | tie
    reviewer_ref: Mapped[str | None] = mapped_column(String, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[str] = mapped_column(String, default=utcnow)


# ---------------------------------------------------------------------------
# 第二阶段质量证据：隐藏题包只落不可逆哈希；生成结果、真人价值观测与
# 题材×场景功能策略分开存证。任何表都不保存隐藏答案或 rubric 正文。
# ---------------------------------------------------------------------------


class QualityBenchmarkManifest(Base):
    __tablename__ = "quality_benchmark_manifests"
    __table_args__ = (
        CheckConstraint("case_count > 0", name="ck_quality_benchmark_manifests_case_count_positive"),
        CheckConstraint("split_kind = 'hidden'", name="ck_quality_benchmark_manifests_hidden_split"),
        CheckConstraint(
            "status IN ('frozen','retired')",
            name="ck_quality_benchmark_manifests_status",
        ),
        Index("ix_quality_benchmark_manifests_hash", "manifest_hash", unique=True),
    )

    manifest_id: Mapped[str] = mapped_column(String, primary_key=True)
    schema_version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    manifest_version: Mapped[str] = mapped_column(String)
    split_kind: Mapped[str] = mapped_column(String, default="hidden", server_default="hidden")
    manifest_hash: Mapped[str] = mapped_column(String)
    public_cases_hash: Mapped[str] = mapped_column(String)
    rubric_hash: Mapped[str] = mapped_column(String)
    case_count: Mapped[int] = mapped_column(Integer)
    isolation_mode: Mapped[str] = mapped_column(String)
    storage_ref: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String, default="frozen", server_default="frozen")
    created_at: Mapped[str] = mapped_column(String, default=utcnow)


class QualityStrategyPolicy(Base):
    __tablename__ = "quality_strategy_policies"
    __table_args__ = (
        CheckConstraint(
            "best_of_n_n >= 1 AND best_of_n_n <= 5",
            name="ck_quality_strategy_policies_best_of_n_positive",
        ),
        CheckConstraint(
            "policy_version >= 1",
            name="ck_quality_strategy_policies_version_positive",
        ),
        CheckConstraint(
            "best_of_n_requested IN (0,1)",
            name="ck_quality_strategy_policies_best_of_n_boolean",
        ),
        CheckConstraint(
            "status IN ('active','retired')",
            name="ck_quality_strategy_policies_status",
        ),
        UniqueConstraint(
            "genre",
            "scene_function",
            "policy_version",
            name="uq_quality_strategy_policy_scope_version",
        ),
        Index(
            "ix_quality_strategy_policies_scope_status",
            "genre",
            "scene_function",
            "status",
        ),
    )

    policy_id: Mapped[str] = mapped_column(String, primary_key=True)
    policy_version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    genre: Mapped[str] = mapped_column(String, default="*", server_default="*")
    scene_function: Mapped[str] = mapped_column(String, default="*", server_default="*")
    weights_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    thresholds_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    best_of_n_requested: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    best_of_n_n: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    evidence_experiment_id: Mapped[str | None] = mapped_column(
        ForeignKey("evaluation_experiments.experiment_id"),
        nullable=True,
    )
    benchmark_manifest_id: Mapped[str | None] = mapped_column(
        ForeignKey("quality_benchmark_manifests.manifest_id"),
        nullable=True,
    )
    status: Mapped[str] = mapped_column(String, default="active", server_default="active")
    created_by: Mapped[str] = mapped_column(String, default="operator", server_default="operator")
    created_at: Mapped[str] = mapped_column(String, default=utcnow)
    updated_at: Mapped[str] = mapped_column(String, default=utcnow, onupdate=utcnow)


class QualityBenchmarkRun(Base):
    __tablename__ = "quality_benchmark_runs"
    __table_args__ = (
        CheckConstraint("case_count_expected > 0", name="ck_quality_benchmark_runs_expected_positive"),
        CheckConstraint("case_count_recorded >= 0", name="ck_quality_benchmark_runs_recorded_nonnegative"),
        CheckConstraint(
            "status IN ('collecting','completed','invalid')",
            name="ck_quality_benchmark_runs_status",
        ),
        CheckConstraint(
            "generation_arm IN ('treatment','control','unassigned')",
            name="ck_quality_benchmark_runs_generation_arm",
        ),
        Index("ix_quality_benchmark_runs_manifest_status", "manifest_id", "status"),
    )

    run_id: Mapped[str] = mapped_column(String, primary_key=True)
    manifest_id: Mapped[str] = mapped_column(ForeignKey("quality_benchmark_manifests.manifest_id"))
    manifest_hash: Mapped[str] = mapped_column(String)
    rubric_hash: Mapped[str] = mapped_column(String)
    policy_id: Mapped[str | None] = mapped_column(
        ForeignKey("quality_strategy_policies.policy_id"),
        nullable=True,
    )
    generator_ref: Mapped[str] = mapped_column(String)
    generation_policy_hash: Mapped[str] = mapped_column(String)
    generation_arm: Mapped[str] = mapped_column(String, default="unassigned", server_default="unassigned")
    status: Mapped[str] = mapped_column(String, default="collecting", server_default="collecting")
    case_count_expected: Mapped[int] = mapped_column(Integer)
    case_count_recorded: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    created_at: Mapped[str] = mapped_column(String, default=utcnow)
    completed_at: Mapped[str | None] = mapped_column(String, nullable=True)


class QualityBenchmarkResult(Base):
    __tablename__ = "quality_benchmark_results"
    __table_args__ = (
        CheckConstraint(
            "cost_tokens IS NULL OR cost_tokens >= 0",
            name="ck_quality_benchmark_results_cost_nonnegative",
        ),
        CheckConstraint(
            "latency_ms IS NULL OR latency_ms >= 0",
            name="ck_quality_benchmark_results_latency_nonnegative",
        ),
        CheckConstraint(
            "cost_micros IS NULL OR cost_micros >= 0",
            name="ck_quality_benchmark_results_cost_micros_nonnegative",
        ),
        CheckConstraint(
            "((cost_micros IS NULL AND cost_currency IS NULL AND cost_basis IS NULL) OR "
            "(cost_micros IS NOT NULL AND cost_currency IS NOT NULL AND cost_basis IS NOT NULL))",
            name="ck_quality_benchmark_results_cost_tuple_complete",
        ),
        CheckConstraint(
            "cost_basis IS NULL OR cost_basis IN ('estimated','actual','billed')",
            name="ck_quality_benchmark_results_cost_basis",
        ),
        CheckConstraint(
            "prompt_leakage_check = 'passed'",
            name="ck_quality_benchmark_results_prompt_leakage_passed",
        ),
        UniqueConstraint("run_id", "case_id_hash", name="uq_quality_benchmark_result_run_case"),
        Index(
            "ix_quality_benchmark_results_strategy_cell",
            "genre",
            "scene_function",
            "run_id",
        ),
    )

    result_id: Mapped[str] = mapped_column(String, primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("quality_benchmark_runs.run_id"))
    case_id_hash: Mapped[str] = mapped_column(String)
    genre: Mapped[str] = mapped_column(String)
    scene_function: Mapped[str] = mapped_column(String)
    artifact_ref: Mapped[str] = mapped_column(String)
    generation_input_hash: Mapped[str] = mapped_column(String)
    generation_prompt_hash: Mapped[str] = mapped_column(String)
    output_hash: Mapped[str] = mapped_column(String)
    prompt_leakage_check: Mapped[str] = mapped_column(
        String,
        default="passed",
        server_default="passed",
    )
    automated_metrics_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    cost_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cost_micros: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cost_currency: Mapped[str | None] = mapped_column(String, nullable=True)
    cost_basis: Mapped[str | None] = mapped_column(String, nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[str] = mapped_column(String, default=utcnow)


class QualityValueObservation(Base):
    __tablename__ = "quality_value_observations"
    __table_args__ = (
        CheckConstraint("provenance = 'human'", name="ck_quality_value_observations_human_only"),
        CheckConstraint(
            "human_edit_distance IS NULL OR human_edit_distance >= 0",
            name="ck_quality_value_observations_edit_distance_nonnegative",
        ),
        CheckConstraint(
            "human_edit_distance_ratio IS NULL OR "
            "(human_edit_distance_ratio >= 0 AND human_edit_distance_ratio <= 1)",
            name="ck_quality_value_observations_edit_ratio_range",
        ),
        CheckConstraint(
            "follow_read_intent IS NULL OR (follow_read_intent >= 1 AND follow_read_intent <= 5)",
            name="ck_quality_value_observations_follow_read_range",
        ),
        UniqueConstraint(
            "result_id",
            "reviewer_ref",
            name="uq_quality_value_observation_result_reviewer",
        ),
        Index("ix_quality_value_observations_result", "result_id"),
    )

    observation_id: Mapped[str] = mapped_column(String, primary_key=True)
    result_id: Mapped[str] = mapped_column(ForeignKey("quality_benchmark_results.result_id"))
    reviewer_ref: Mapped[str] = mapped_column(String)
    provenance: Mapped[str] = mapped_column(String)
    source_text_hash: Mapped[str | None] = mapped_column(String, nullable=True)
    edited_text_hash: Mapped[str | None] = mapped_column(String, nullable=True)
    human_edit_distance: Mapped[int | None] = mapped_column(Integer, nullable=True)
    human_edit_distance_ratio: Mapped[float | None] = mapped_column(Float, nullable=True)
    first_usable: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    follow_read_intent: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[str] = mapped_column(String, default=utcnow)


# ---------------------------------------------------------------------------
# Style Reference (v1.1) — 11 张表
# 参见 plans/style-reference-v1-1-fancy-shannon.md 与
# 《风格参考模块重构执行手册 v1.1》§4。
# ---------------------------------------------------------------------------


class StyleReferenceBook(Base):
    __tablename__ = "style_reference_books"
    __table_args__ = (
        UniqueConstraint("text_checksum", name="uq_style_reference_books_text_checksum"),
        Index("ix_style_reference_books_status_updated_at", "status", "updated_at"),
    )

    book_id: Mapped[str] = mapped_column(String, primary_key=True)
    title: Mapped[str] = mapped_column(String)
    author_label: Mapped[str | None] = mapped_column(String, nullable=True)
    source_kind: Mapped[str] = mapped_column(String)
    source_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    cloud_policy: Mapped[str] = mapped_column(String)
    text_checksum: Mapped[str] = mapped_column(String)
    total_chars: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String, default="pending")
    stats_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[str] = mapped_column(String, default=utcnow)
    updated_at: Mapped[str] = mapped_column(String, default=utcnow, onupdate=utcnow)


class StyleReferenceParagraph(Base):
    __tablename__ = "style_reference_paragraphs"
    __table_args__ = (
        Index(
            "ix_style_reference_paragraphs_book_type",
            "book_id",
            "paragraph_type",
        ),
        Index(
            "ix_style_reference_paragraphs_book_index",
            "book_id",
            "paragraph_index",
        ),
    )

    paragraph_id: Mapped[str] = mapped_column(String, primary_key=True)
    book_id: Mapped[str] = mapped_column(ForeignKey("style_reference_books.book_id"))
    paragraph_index: Mapped[int] = mapped_column(Integer)
    paragraph_type: Mapped[str] = mapped_column(String)
    start_offset: Mapped[int] = mapped_column(Integer)
    end_offset: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    char_count: Mapped[int] = mapped_column(Integer)
    classifier_confidence: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[str] = mapped_column(String, default=utcnow)


class StyleReferenceRun(Base):
    __tablename__ = "style_reference_runs"
    __table_args__ = (
        Index("ix_style_reference_runs_book_status", "book_id", "status"),
    )

    run_id: Mapped[str] = mapped_column(String, primary_key=True)
    book_id: Mapped[str] = mapped_column(ForeignKey("style_reference_books.book_id"))
    status: Mapped[str] = mapped_column(String, default="pending")
    phase: Mapped[str] = mapped_column(String, default="ingest")
    coverage_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    started_at: Mapped[str | None] = mapped_column(String, nullable=True)
    finished_at: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[str] = mapped_column(String, default=utcnow)
    updated_at: Mapped[str] = mapped_column(String, default=utcnow, onupdate=utcnow)


class StyleReferenceExtraction(Base):
    __tablename__ = "style_reference_extractions"
    __table_args__ = (
        Index(
            "ix_style_reference_extractions_book_layer_sub",
            "book_id",
            "layer",
            "sub_dimension",
        ),
        Index(
            "ix_style_reference_extractions_run_status",
            "run_id",
            "status",
        ),
    )

    extraction_id: Mapped[str] = mapped_column(String, primary_key=True)
    book_id: Mapped[str] = mapped_column(ForeignKey("style_reference_books.book_id"))
    run_id: Mapped[str] = mapped_column(ForeignKey("style_reference_runs.run_id"))
    layer: Mapped[str] = mapped_column(String)
    sub_dimension: Mapped[str] = mapped_column(String)
    llm_call_id: Mapped[str | None] = mapped_column(String, nullable=True)
    raw_payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String, default="pending")
    validation_errors_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    purpose: Mapped[str] = mapped_column(String, default="extract")
    created_at: Mapped[str] = mapped_column(String, default=utcnow)
    updated_at: Mapped[str] = mapped_column(String, default=utcnow, onupdate=utcnow)


class StyleReferenceQuote(Base):
    __tablename__ = "style_reference_quotes"
    __table_args__ = (
        Index("ix_style_reference_quotes_book", "book_id"),
    )

    quote_id: Mapped[str] = mapped_column(String, primary_key=True)
    book_id: Mapped[str] = mapped_column(ForeignKey("style_reference_books.book_id"))
    # paragraph_id 可空:支持 anchor_kind=counter_example 的合成 quote 不指向真实段落
    paragraph_id: Mapped[str | None] = mapped_column(
        ForeignKey("style_reference_paragraphs.paragraph_id"), nullable=True
    )
    span_start: Mapped[int] = mapped_column(Integer)
    span_end: Mapped[int] = mapped_column(Integer)
    quote_text: Mapped[str] = mapped_column(Text)
    illustrates_dims: Mapped[list[str]] = mapped_column(JSON, default=list)
    extracted_features: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[str] = mapped_column(String, default=utcnow)


class StyleReferenceFinding(Base):
    __tablename__ = "style_reference_findings"
    __table_args__ = (
        Index(
            "ix_style_reference_findings_book_sub_kind",
            "book_id",
            "sub_dimension",
            "finding_kind",
        ),
        UniqueConstraint("review_id", name="uq_style_reference_findings_review_id"),
        # PR-3 hotfix 0038:UNIQUE 复合 4 列(原 3 列与 §6.5 0-8 条 obs 输出矛盾)
        # 详见 plans/style-reference-v1-1-fancy-shannon.md §"v1.2 文档修订清单 #8"
        UniqueConstraint(
            "extraction_id",
            "sub_dimension",
            "finding_kind",
            "statement_hash",
            name="uq_style_reference_findings_extract_sub_kind_hash",
        ),
    )

    finding_id: Mapped[str] = mapped_column(String, primary_key=True)
    book_id: Mapped[str] = mapped_column(ForeignKey("style_reference_books.book_id"))
    run_id: Mapped[str] = mapped_column(ForeignKey("style_reference_runs.run_id"))
    extraction_id: Mapped[str] = mapped_column(
        ForeignKey("style_reference_extractions.extraction_id")
    )
    sub_dimension: Mapped[str] = mapped_column(String)
    finding_kind: Mapped[str] = mapped_column(String)
    statement: Mapped[str] = mapped_column(Text)
    # PR-3 hotfix 0038:statement 的 SHA256[:16],用于 UNIQUE 复合;应用层 / repository
    # 在 create_finding 时自动填充
    statement_hash: Mapped[str] = mapped_column(String)
    confidence: Mapped[str] = mapped_column(String, default="medium")
    # 立项 B — 合成时的基线置信度。NULL = 尚无用户反馈(confidence 即基线);
    # 首次反馈时由应用层回填为当时的 confidence,使反馈调档可重算/可逆。
    base_confidence: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String, default="pending")
    review_id: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[str] = mapped_column(String, default=utcnow)
    updated_at: Mapped[str] = mapped_column(String, default=utcnow, onupdate=utcnow)


class StyleReferenceEvidence(Base):
    __tablename__ = "style_reference_evidences"
    __table_args__ = (
        UniqueConstraint(
            "finding_id",
            "quote_id",
            name="uq_style_reference_evidences_finding_quote",
        ),
    )

    evidence_id: Mapped[str] = mapped_column(String, primary_key=True)
    finding_id: Mapped[str] = mapped_column(ForeignKey("style_reference_findings.finding_id"))
    quote_id: Mapped[str] = mapped_column(ForeignKey("style_reference_quotes.quote_id"))
    anchor_kind: Mapped[str] = mapped_column(String)
    is_synthetic: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[str] = mapped_column(String, default=utcnow)


class StyleReferenceProfile(Base):
    __tablename__ = "style_reference_profiles"
    __table_args__ = (
        Index(
            "ix_style_reference_profiles_book_status",
            "book_id",
            "status",
        ),
        Index("ix_style_reference_profiles_version_tag", "version_tag"),
    )

    profile_id: Mapped[str] = mapped_column(String, primary_key=True)
    book_id: Mapped[str] = mapped_column(ForeignKey("style_reference_books.book_id"))
    run_id: Mapped[str] = mapped_column(ForeignKey("style_reference_runs.run_id"))
    title: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String, default="draft")
    profile_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    coverage_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    source_finding_ids_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    version_tag: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[str] = mapped_column(String, default=utcnow)
    updated_at: Mapped[str] = mapped_column(String, default=utcnow, onupdate=utcnow)


class StyleReferenceInjectionBinding(Base):
    __tablename__ = "style_reference_injection_bindings"
    __table_args__ = (
        Index(
            "ix_style_reference_injection_bindings_profile_scope_ref",
            "profile_id",
            "scope",
            "scope_ref_id",
        ),
        Index(
            "ix_style_reference_injection_bindings_task_type",
            "task_type",
        ),
        # 并发 apply 的「先查后建」竞态兜底:同 (profile, scope, scope_ref, task)
        # 不允许重复 binding(否则注入选取顺序不确定)
        UniqueConstraint(
            "profile_id",
            "scope",
            "scope_ref_id",
            "task_type",
            name="uq_style_reference_injection_bindings_target",
        ),
    )

    binding_id: Mapped[str] = mapped_column(String, primary_key=True)
    profile_id: Mapped[str] = mapped_column(ForeignKey("style_reference_profiles.profile_id"))
    scope: Mapped[str] = mapped_column(String)
    scope_ref_id: Mapped[str | None] = mapped_column(String, nullable=True)
    task_type: Mapped[str] = mapped_column(String)
    strategy: Mapped[str] = mapped_column(String)
    config_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String, default="active")
    created_at: Mapped[str] = mapped_column(String, default=utcnow)
    updated_at: Mapped[str] = mapped_column(String, default=utcnow, onupdate=utcnow)


class StyleReferenceValidationReport(Base):
    __tablename__ = "style_reference_validation_reports"
    __table_args__ = (
        Index(
            "ix_style_reference_validation_reports_profile_target",
            "profile_id",
            "target_ref_id",
        ),
        Index(
            "ix_style_reference_validation_reports_verdict",
            "verdict",
        ),
    )

    report_id: Mapped[str] = mapped_column(String, primary_key=True)
    profile_id: Mapped[str] = mapped_column(ForeignKey("style_reference_profiles.profile_id"))
    target_kind: Mapped[str] = mapped_column(String)
    target_ref_id: Mapped[str | None] = mapped_column(String, nullable=True)
    verdict: Mapped[str] = mapped_column(String)
    quantitative_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    semantic_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    plagiarism_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    forbidden_hits_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    mode_executed: Mapped[str] = mapped_column(String, default="async_full")
    created_at: Mapped[str] = mapped_column(String, default=utcnow)


class StyleReferenceBannedTerm(Base):
    __tablename__ = "style_reference_banned_terms"
    __table_args__ = (
        UniqueConstraint(
            "profile_id",
            "term",
            "scope",
            name="uq_style_reference_banned_terms_profile_term_scope",
        ),
    )

    term_id: Mapped[str] = mapped_column(String, primary_key=True)
    profile_id: Mapped[str] = mapped_column(ForeignKey("style_reference_profiles.profile_id"))
    term: Mapped[str] = mapped_column(String)
    replacement_hint: Mapped[str | None] = mapped_column(String, nullable=True)
    source: Mapped[str] = mapped_column(String)
    scope: Mapped[str] = mapped_column(String, default="generation")
    created_at: Mapped[str] = mapped_column(String, default=utcnow)
    updated_at: Mapped[str] = mapped_column(String, default=utcnow, onupdate=utcnow)


class StyleReferenceMetricEvent(Base):
    """PR-10 §13 — 可观测性事件流(append-only,无 FK)。

    InjectionService / qc gate / ValidationOrchestrator / SceneAutoRewriteService
    各调用点写 1 行;MetricsAggregator 按 event_kind + 时间窗口 group by。
    event_kind 5 个允许值(由文档约束,**不**是 Python Enum):
    injection_invoked / qc_gate_decided / validation_executed /
    auto_rewrite_triggered / auto_rewrite_completed
    """

    __tablename__ = "style_reference_metric_events"
    __table_args__ = (
        Index("ix_sr_metric_events_kind_created", "event_kind", "created_at"),
        Index("ix_sr_metric_events_profile_created", "profile_id", "created_at"),
    )

    event_id: Mapped[str] = mapped_column(String, primary_key=True)
    event_kind: Mapped[str] = mapped_column(String)
    target_kind: Mapped[str | None] = mapped_column(String, nullable=True)
    target_ref_id: Mapped[str | None] = mapped_column(String, nullable=True)
    profile_id: Mapped[str | None] = mapped_column(String, nullable=True)
    binding_id: Mapped[str | None] = mapped_column(String, nullable=True)
    outcome: Mapped[str | None] = mapped_column(String, nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    context_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[str] = mapped_column(String, default=utcnow)


class StyleReferenceFindingFeedback(Base):
    """立项 B — finding 的用户反馈(👍/👎)持续校准回路。

    一人(operator_ref)对一条 finding 仅一票(uq 约束);改向投票 = 更新该行 vote。
    聚合 net = #up − #down(去重用户),按 config/style_reference/feedback.yaml 阈值
    在 finding.base_confidence 基础上 ±1 档写回 finding.confidence。
    """

    __tablename__ = "style_reference_finding_feedback"
    __table_args__ = (
        UniqueConstraint(
            "finding_id",
            "operator_ref",
            name="uq_style_reference_finding_feedback_finding_operator",
        ),
        Index("ix_sr_finding_feedback_finding", "finding_id"),
    )

    feedback_id: Mapped[str] = mapped_column(String, primary_key=True)
    # ondelete CASCADE：运行连接默认强制 FK；purge_derived_data 仍显式删除，
    # 作为维护期开关关闭时的兜底并保留清晰的删除审计顺序。
    finding_id: Mapped[str] = mapped_column(
        ForeignKey("style_reference_findings.finding_id", ondelete="CASCADE")
    )
    operator_ref: Mapped[str] = mapped_column(String)
    vote: Mapped[str] = mapped_column(String)  # "up" | "down"
    created_at: Mapped[str] = mapped_column(String, default=utcnow)
    updated_at: Mapped[str] = mapped_column(String, default=utcnow, onupdate=utcnow)
