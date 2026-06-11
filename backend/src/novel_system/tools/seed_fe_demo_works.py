"""FE-ALIGN Phase 2: 两部种子作品（潮汐档案 / 盐镇来信）的后端 demo seed。

原型 design/ws-works.jsx 的 WS_WORKS_SEED 后端化：项目档案、写作统计基线、
章节/场景骨架（含 fe_display 展示态与 GCS brief）、续写场景的正文草稿、
雪花步骤状态。由 seed_demo 调用（dev.ps1 的 skip-demo-seed 开关在上游生效）。

幂等：按固定 project_id 清理后重建。
"""
from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from novel_system.db.models import (
    AuthorDraft,
    ChapterGoal,
    ProjectWritingStats,
    SceneCard,
    SnowflakeStepRun,
    StoryProject,
    utcnow,
)
from novel_system.services.writing_stats import WRITING_STATS_TZ, WritingStatsService

DEMO_WORK_IDS = ("tide", "salt")

_TIDE_CHAPTERS = [
    ("盐钟残片", "approved", 100, False),
    ("潮汐记录室", "approved", 100, False),
    ("被改写的人", "approved", 100, False),
    ("回声讲堂", "approved", 100, False),
    ("夜班指南", "review", 80, False),
    ("周岚的钥匙", "draft", 88, False),
    ("三号档案箱", "draft", 70, False),
    ("返回的潮声", "writing", 12, True),
]

_SALT_CHAPTERS = [
    ("盐场的早班", "approved", 100, False),
    ("藤椅与旧匣", "review", 76, False),
    ("没寄出的信", "writing", 34, True),
]

# 雪花步骤状态（按 SNOWFLAKE_STEP_CATALOG 的 step_key 顺序；映射见 project_overview）：
# approved→done；pending_review 且为首个未过闸步→active；其余 pending_review→warn；缺行→todo。
_TIDE_STEPS = {
    "book_brief": "approved",
    "one_sentence_summary": "approved",
    "one_paragraph_summary": "approved",
    "character_sheets": "approved",
    "short_synopsis": "approved",
    "character_synopses": "pending_review",  # active：角色背景 · 周岚
    "long_synopsis": "approved",
    "character_bibles": "pending_review",  # warn：角色全档案
    "scene_list": "approved",
    "scene_details": "approved",
}

_SALT_STEPS = {
    "book_brief": "approved",
    "one_sentence_summary": "approved",
    "one_paragraph_summary": "pending_review",  # active：一段话
    "character_sheets": "approved",
    "short_synopsis": "pending_review",  # warn：一页梗概
}

_TIDE_RESUME_LINES = [
    "潮汐表第三页的墨迹还没干透，林岑却已经认出，那不是她昨夜留下的笔迹。",
    "走廊尽头只剩一盏灯。No.31 的编号在屏幕上轻轻跳了一下，像是有人也在另一端，读着同一行字。",
]

_SALT_RESUME_LINES = [
    "怀梅把信纸对折了三次，折痕压得很重，像是要把那些没说出口的话一并压进去。",
    "堂屋的方向没有声音，可她知道，祖父就坐在那张吱呀作响的藤椅上，等着她走，又怕她真走。",
]

_FILLER = "夜里的修复台只剩一台老式读卡器还亮着，潮声从通风井里渗进来，混着纸页翻动的细响。"


def _prose(lines: list[str], target_chars: int) -> str:
    """演示正文：以中性填充句铺到目标字数附近，签名句压尾（resume 卡读末两行）。"""
    paragraphs: list[str] = []
    total = sum(len(line) for line in lines)
    while total < target_chars - len(_FILLER):
        paragraphs.append(_FILLER)
        total += len(_FILLER)
    paragraphs.extend(lines)
    return "\n".join(paragraphs)


def cleanup_fe_demo_works(session: Session) -> None:
    scene_ids = [
        row
        for row in session.execute(
            select(SceneCard.scene_id).where(SceneCard.project_id.in_(DEMO_WORK_IDS))
        ).scalars().all()
    ]
    if scene_ids:
        session.execute(
            delete(AuthorDraft).where(
                AuthorDraft.object_type == "scene", AuthorDraft.object_id.in_(scene_ids)
            )
        )
    session.execute(delete(SceneCard).where(SceneCard.project_id.in_(DEMO_WORK_IDS)))
    session.execute(delete(ChapterGoal).where(ChapterGoal.project_id.in_(DEMO_WORK_IDS)))
    session.execute(delete(SnowflakeStepRun).where(SnowflakeStepRun.project_id.in_(DEMO_WORK_IDS)))
    session.execute(delete(ProjectWritingStats).where(ProjectWritingStats.project_id.in_(DEMO_WORK_IDS)))
    session.execute(delete(StoryProject).where(StoryProject.project_id.in_(DEMO_WORK_IDS)))
    session.flush()


def seed_fe_demo_works(session: Session) -> list[str]:
    cleanup_fe_demo_works(session)
    now_sh = datetime.now(WRITING_STATS_TZ)
    yesterday = (now_sh - timedelta(days=1)).date().isoformat()

    _seed_work(
        session,
        project_id="tide",
        title="潮汐档案",
        genre="悬疑 · 长篇",
        mark="汐",
        accent="crimson",
        synopsis_line="近未来沿海城市的档案修复师林岑，发现旧潮汐记录正被某种规律重写——一部关于记忆与权力的悬疑长篇。",
        target_word_count=120000,
        target_chapter_count=24,
        words_target_daily=1500,
        chapters=_TIDE_CHAPTERS,
        steps=_TIDE_STEPS,
        scene_title="夜班修复台 · 二次发现",
        scene_brief={
            "goal": "在馆长发现前，独自核对 No.31 的真伪",
            "conflict": "馆长晚归，仍在馆中走动",
            "setback": "系统提示「读取异常」，记录开始自我改写",
        },
        scene_kind="proactive",
        scene_seq=3,
        scene_words=1240,
        resume_lines=_TIDE_RESUME_LINES,
        paused_days_ago=3,
        words_total=38420,
        streak_days=6,
        streak_last_day=yesterday,
    )

    _seed_work(
        session,
        project_id="salt",
        title="盐镇来信",
        genre="年代 · 家族",
        mark="盐",
        accent="gold",
        synopsis_line="八十年代末，盐场子弟苏怀梅离乡前写下最后一封没寄出的信，牵出三代人围绕一片废弃盐田的隐忍与亏欠——一部缓慢生长的家族长篇。",
        target_word_count=100000,
        target_chapter_count=20,
        words_target_daily=1200,
        chapters=_SALT_CHAPTERS,
        steps=_SALT_STEPS,
        scene_title="盐田尽头 · 没寄出的信",
        scene_brief={
            "goal": "把信塞进祖父的旧木匣，赶在天亮前离开盐镇",
            "conflict": "祖父半夜起身，坐在堂屋没有开灯",
            "setback": "木匣里早已躺着另一封字迹相同的信",
        },
        scene_kind="proactive",
        scene_seq=1,
        scene_words=760,
        resume_lines=_SALT_RESUME_LINES,
        paused_days_ago=1,
        words_total=12600,
        streak_days=0,
        streak_last_day=None,
    )
    # 项目列表按 created_at 倒序 —— 把 salt 拨早 1 秒，保证潮汐档案居首
    # （原型 WS_WORKS_SEED 顺序：tide 为默认作品）。
    tide = session.get(StoryProject, "tide")
    salt = session.get(StoryProject, "salt")
    if tide and salt and salt.created_at >= tide.created_at:
        salt.created_at = (
            datetime.fromisoformat(tide.created_at) - timedelta(seconds=1)
        ).isoformat()
    session.flush()
    return list(DEMO_WORK_IDS)


def _seed_work(
    session: Session,
    *,
    project_id: str,
    title: str,
    genre: str,
    mark: str,
    accent: str,
    synopsis_line: str,
    target_word_count: int,
    target_chapter_count: int,
    words_target_daily: int,
    chapters: list[tuple[str, str, int, bool]],
    steps: dict[str, str],
    scene_title: str,
    scene_brief: dict[str, str],
    scene_kind: str,
    scene_seq: int,
    scene_words: int,
    resume_lines: list[str],
    paused_days_ago: int,
    words_total: int,
    streak_days: int,
    streak_last_day: str | None,
) -> None:
    writing_chapter_id = None
    project = StoryProject(
        project_id=project_id,
        title=title,
        genre=genre,
        mark=mark,
        accent=accent,
        synopsis_line=synopsis_line,
        target_word_count=target_word_count,
        target_chapter_count=target_chapter_count,
        words_target_daily=words_target_daily,
        is_demo=1,
        outline_text=synopsis_line,
        planning_mode="snowflake",
        snowflake_workflow_mode="explore",
        approved_chapter_ids_json=[],
    )
    session.add(project)
    session.flush()

    for index, (chapter_title, state, pct, active) in enumerate(chapters):
        chapter_id = f"{project_id}-ch{index + 1:02d}"
        if active:
            writing_chapter_id = chapter_id
        session.add(
            ChapterGoal(
                chapter_id=chapter_id,
                project_id=project_id,
                planned_scene_count=1,
                chapter_goal=chapter_title,
                writer_brief_json={
                    "title": chapter_title,
                    "fe_display": {"state": state, "pct": pct, "active": active},
                },
            )
        )
    session.flush()

    # 在写章的场景骨架 + 续写场景（带 GCS brief 与正文草稿）
    if writing_chapter_id:
        for seq in range(1, scene_seq + 1):
            is_resume_scene = seq == scene_seq
            scene_id = f"{writing_chapter_id}-sc{seq:02d}"
            session.add(
                SceneCard(
                    scene_id=scene_id,
                    chapter_id=writing_chapter_id,
                    project_id=project_id,
                    scene_seq=seq,
                    scene_goal=scene_title if is_resume_scene else f"场景 {seq}",
                    scene_type=scene_kind,
                    writer_brief_json={
                        "title": scene_title if is_resume_scene else f"场景 {seq}",
                        "primary_form": scene_kind,
                        **(scene_brief if is_resume_scene else {}),
                        "fe_display": {"writing": is_resume_scene},
                    },
                )
            )
        session.flush()
        resume_scene_id = f"{writing_chapter_id}-sc{scene_seq:02d}"
        paused_at = (datetime.now(WRITING_STATS_TZ) - timedelta(days=paused_days_ago)).isoformat()
        draft = AuthorDraft(
            draft_id=f"author_draft_scene_{resume_scene_id}_demo",
            object_type="scene",
            object_id=resume_scene_id,
            source_text_ref="demo_seed",
            content=_prose(resume_lines, scene_words),
            revision_no=1,
            status="current",
            created_by="demo_seed",
            updated_by="demo_seed",
        )
        session.add(draft)
        session.flush()
        draft.updated_at = paused_at
        project.current_chapter_id = writing_chapter_id

    for step_key, status in steps.items():
        session.add(
            SnowflakeStepRun(
                step_run_id=f"{project_id}-step-{step_key}",
                project_id=project_id,
                step_key=step_key,
                version=1,
                status=status,
                draft_json={"summary": "演示数据"},
                approved_at=utcnow() if status == "approved" else None,
            )
        )
    session.flush()

    WritingStatsService(session).seed_stats(
        project_id,
        words_total=words_total,
        streak_days=streak_days,
        streak_last_day=streak_last_day,
    )
