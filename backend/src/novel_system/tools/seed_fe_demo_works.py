"""FE-ALIGN Phase 2/3: 两部种子作品（潮汐档案 / 盐镇来信）的后端 demo seed。

原型 design/ws-works.jsx 的 WS_WORKS_SEED 后端化：项目档案、写作统计基线、
雪花步骤状态、目录（章/场景树，含戏剧卡/线索/张力——数据来自
fe_demo_catalog.json，由 frontend-react/scripts/export-demo-catalog.mjs 从
前端种子 ARR_CHAPTERS / CAT_SALT_CHAPTERS 导出）、在写场景的正文草稿。

目录写入复用 CatalogService.import_catalog —— 与一次性迁移走同一代码路径。
幂等：按固定 project_id 清理后重建。由 seed_demo 调用（dev.ps1 的
skip-demo-seed 开关在上游生效）。
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

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
from novel_system.services.catalog import CatalogService
from novel_system.services.writing_stats import (
    WRITING_STATS_TZ,
    WritingStatsService,
    count_words,
)

DEMO_WORK_IDS = ("tide", "salt")

_CATALOG_JSON = Path(__file__).with_name("fe_demo_catalog.json")

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


_LIBRARY_JSON = Path(__file__).with_name("fe_demo_library.json")

# 原型 kind 展示词 → 后端实体 kind
_ENTITY_KIND_MAP = {
    "地点": "location",
    "场所": "location",
    "物品": "item",
    "线索": "item",
    "信物": "item",
    "机构": "faction",
    "组织": "faction",
    "阵营": "faction",
}


def _seed_tide_library(session: Session) -> None:
    """原型 ws-library-data 的后端化：人物→StoryCharacter、世界→LibraryEntity、
    大事记→TimelineEvent、links→LibraryRelation（事件端点不建边——关系表只接受
    character/entity ref）。"""
    from novel_system.db.models import (
        LibraryEntity,
        LibraryRelation,
        StoryCharacter,
        TimelineEvent,
    )

    if not _LIBRARY_JSON.exists():
        return
    entries = json.loads(_LIBRARY_JSON.read_text(encoding="utf-8")).get("tide") or []
    for model in (LibraryRelation, TimelineEvent, LibraryEntity):
        session.execute(delete(model).where(model.project_id == "tide"))
    session.execute(delete(StoryCharacter).where(StoryCharacter.project_id == "tide"))
    session.flush()

    ref_of: dict[str, str] = {}
    for entry in entries:
        extras = {
            key: entry.get(key)
            for key in ("code", "accent", "glyph", "blurb", "facts", "appears", "arc", "state", "pinned", "updated")
            if entry.get(key) is not None
        }
        if entry["cat"] == "people":
            session.add(
                StoryCharacter(
                    character_id=entry["id"],
                    project_id="tide",
                    display_name=entry["name"],
                    role=entry.get("kind") or None,
                    summary_json={"one_line": entry.get("summary") or "", "fe_details": extras},
                    status="active",
                )
            )
            ref_of[entry["id"]] = f"character:{entry['id']}"
        elif entry["cat"] == "world":
            session.add(
                LibraryEntity(
                    entity_id=entry["id"],
                    project_id="tide",
                    kind=_ENTITY_KIND_MAP.get(str(entry.get("kind") or ""), "concept"),
                    name=entry["name"],
                    aliases_json=[],
                    summary=entry.get("summary") or "",
                    details_json=extras,
                    tags_json=list(entry.get("tags") or []),
                    status="active",
                )
            )
            ref_of[entry["id"]] = f"entity:{entry['id']}"
        elif entry["cat"] == "events":
            facts = {f.get("k"): f.get("v") for f in (entry.get("facts") or []) if isinstance(f, dict)}
            appears = list(entry.get("appears") or [])
            session.add(
                TimelineEvent(
                    event_id=entry["id"],
                    project_id="tide",
                    label=entry["name"],
                    time_label=str(facts.get("时间") or facts.get("时点") or entry.get("summary") or ""),
                    chapter_ref=appears[0] if appears else None,
                    entity_refs_json=[],
                    note=entry.get("blurb") or entry.get("summary") or "",
                    display_order=None,
                )
            )
    session.flush()

    # links → 关系边（端点限 character/entity；目标是事件的链接进事件 entity_refs）
    event_ids = {e["id"] for e in entries if e["cat"] == "events"}
    seen_pairs: set[tuple[str, str]] = set()
    for entry in entries:
        source_ref = ref_of.get(entry["id"])
        for link in entry.get("links") or []:
            target_id = link.get("id")
            if target_id in event_ids and source_ref:
                event = session.get(TimelineEvent, target_id)
                if event is not None:
                    refs = list(event.entity_refs_json or [])
                    if source_ref not in refs:
                        refs.append(source_ref)
                        event.entity_refs_json = refs
                continue
            target_ref = ref_of.get(target_id)
            if not source_ref or not target_ref:
                continue
            pair = tuple(sorted((source_ref, target_ref)))
            if pair in seen_pairs:
                continue
            seen_pairs.add(pair)
            session.add(
                LibraryRelation(
                    relation_id=f"REL_DEMO_{len(seen_pairs):03d}",
                    project_id="tide",
                    from_ref=source_ref,
                    to_ref=target_ref,
                    kind=str(link.get("type") or "related"),
                    note=str(link.get("rel") or ""),
                )
            )
    session.flush()


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
    catalogs = json.loads(_CATALOG_JSON.read_text(encoding="utf-8"))
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
        catalog_chapters=catalogs["tide"],
        steps=_TIDE_STEPS,
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
        catalog_chapters=catalogs["salt"],
        steps=_SALT_STEPS,
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
    catalog_chapters: list[dict],
    steps: dict[str, str],
    resume_lines: list[str],
    paused_days_ago: int,
    words_total: int,
    streak_days: int,
    streak_last_day: str | None,
) -> None:
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

    # 目录：与一次性迁移同一条代码路径（带「待写」占位章的过滤——
    # lf2 的 planned 占位行不属于真实目录）
    chapters = [c for c in catalog_chapters if str(c.get("title") or "").strip() not in ("", "（待写）")]
    catalog = CatalogService(session)
    catalog.import_catalog(project_id, {"chapters": chapters})

    # 当前章的在写场景（state=writing）挂正文草稿，resume 卡读其末两行
    # （ARR 数据里多章带 writing 场景，必须限定在 current 章内）
    writing_scene = None
    if project.current_chapter_id:
        writing_scene = session.execute(
            select(SceneCard).where(
                SceneCard.chapter_id == project.current_chapter_id,
                SceneCard.state == "writing",
                SceneCard.trashed_flag == 0,
            ).order_by(SceneCard.scene_seq.asc())
        ).scalars().first()
    if writing_scene is not None:
        paused_at = (datetime.now(WRITING_STATS_TZ) - timedelta(days=paused_days_ago)).isoformat()
        content = _prose(resume_lines, int(writing_scene.words_current or 0) or 800)
        draft = AuthorDraft(
            draft_id=f"author_draft_scene_{writing_scene.scene_id}_demo",
            object_type="scene",
            object_id=writing_scene.scene_id,
            source_text_ref="demo_seed",
            content=content,
            revision_no=1,
            status="current",
            created_by="demo_seed",
            updated_by="demo_seed",
        )
        session.add(draft)
        session.flush()
        draft.updated_at = paused_at
        writing_scene.words_current = count_words(content)
        # 在写场景所在章立为当前章（import 已按 item.current 设置过；这里兜底）
        if not project.current_chapter_id:
            project.current_chapter_id = writing_scene.chapter_id

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

    if project_id == "tide":
        _seed_tide_review_cards(session)
        _seed_tide_library(session)

    WritingStatsService(session).seed_stats(
        project_id,
        words_total=words_total,
        streak_days=streak_days,
        streak_last_day=streak_last_day,
    )


def _seed_tide_review_cards(session: Session) -> None:
    """原型 ws-review RV_SEED 的后端化（effect 指向真实章节行；dedupe 幂等）。"""
    from novel_system.db.models import ReviewItem
    from novel_system.services.review_cards import ReviewCardService

    session.execute(
        delete(ReviewItem).where(
            ReviewItem.project_id == "tide", ReviewItem.item_type == "fe_card"
        )
    )
    session.flush()
    chapters = session.execute(
        select(ChapterGoal)
        .where(ChapterGoal.project_id == "tide", ChapterGoal.trashed_flag == 0)
        .order_by(ChapterGoal.display_order.asc())
    ).scalars().all()
    by_no = {index + 1: chapter for index, chapter in enumerate(chapters)}
    cards = ReviewCardService(session)
    if 6 in by_no:
        cards.create_card(
            {
                "project_id": "tide",
                "kind": "decision",
                "priority": 2,
                "title": "第 6 章标题在两个候选间未定",
                "source": "章节编排",
                "where": "第 6 章 · 标题",
                "detail": "「周岚的钥匙」直白点题、呼应线索；「她留下的钥匙」更含蓄、留悬念。选定后会直接改写目录里第 6 章的标题。",
                "options": ["周岚的钥匙", "她留下的钥匙"],
                "dedupe_key": "demo:tide:ch06-title",
                "actions": [
                    {"label": "用「周岚的钥匙」", "intent": "primary", "op": "resolve",
                     "effect": {"type": "rename_chapter", "chapter_id": by_no[6].chapter_id, "title": "周岚的钥匙"}},
                    {"label": "用「她留下的钥匙」", "intent": "ghost", "op": "resolve",
                     "effect": {"type": "rename_chapter", "chapter_id": by_no[6].chapter_id, "title": "她留下的钥匙"}},
                    {"label": "再想想", "intent": "quiet", "op": "snooze"},
                ],
            },
            actor_ref="demo_seed",
        )
    if 7 in by_no:
        cards.create_card(
            {
                "project_id": "tide",
                "kind": "qc",
                "priority": 2,
                "title": "第 7 章节奏过快，建议补一段反应场景",
                "source": "文学质检",
                "where": "第 7 章 · SC 03 之后",
                "detail": "连续三个主动场景之间没有喘息，读者情绪曲线缺少回落。建议在 SC 03 后插入 200–400 字的反应节拍，让林岑消化「钥匙」的发现。采纳会直接在目录第 7 章 SC 03 后插入一个待写的反应场。",
                "dedupe_key": "demo:tide:ch07-reaction",
                "actions": [
                    {"label": "去章节编排看结构", "intent": "primary", "op": "nav", "nav_to": "author"},
                    {"label": "采纳 · 插入反应场", "intent": "ghost", "op": "resolve",
                     "effect": {"type": "insert_scene", "chapter_id": by_no[7].chapter_id, "at": 3,
                                "scene": {"title": "回廊喘息 · 反应拍", "kind": "reactive", "state": "todo",
                                          "brief": {"reaction": "让林岑消化「钥匙」的发现", "dilemma": "夜班时间所剩无几", "decision": "（待规划）"}}}},
                    {"label": "忽略", "intent": "quiet", "op": "resolve"},
                ],
            },
            actor_ref="demo_seed",
        )
    cards.create_card(
        {
            "project_id": "tide",
            "kind": "risk",
            "priority": 2,
            "title": "时间线：第 3 章与第 5 章季节描写不一致",
            "source": "时间线",
            "where": "第 3 章 → 第 5 章",
            "detail": "第 3 章写「初秋的潮气」，第 5 章却出现「初夏蝉鸣」，但两章间隔仅约十天。需统一季节锚点。",
            "dedupe_key": "demo:tide:season",
            "actions": [
                {"label": "打开时间线", "intent": "primary", "op": "nav", "nav_to": "library"},
                {"label": "标记为已核", "intent": "quiet", "op": "resolve"},
            ],
        },
        actor_ref="demo_seed",
    )
    cards.create_card(
        {
            "project_id": "tide",
            "kind": "note",
            "priority": 3,
            "title": "批注 · 「潮声」意象是否前后呼应",
            "source": "写作房间",
            "where": "第 8 章 · 第 12 段",
            "detail": "你给这段留过一条批注：开篇用「潮声」作记忆触发，结尾是否应让它再次响起，形成回环？",
            "dedupe_key": "demo:tide:note-tide-sound",
            "actions": [
                {"label": "回到该段", "intent": "primary", "op": "nav", "nav_to": "writer", "nav_scene": "ch08s3"},
                {"label": "标记已读", "intent": "quiet", "op": "resolve"},
            ],
        },
        actor_ref="demo_seed",
    )
    cards.create_card(
        {
            "project_id": "tide",
            "kind": "qc",
            "priority": 3,
            "title": "全书「潮汐」一词出现 47 次，可能过载",
            "source": "文学质检",
            "where": "全书 · 用词",
            "detail": "核心意象高频复现有记忆点，但密度偏高易显刻意。可在非关键段落用「水位」「退潮」等近义替换 8–10 处。",
            "dedupe_key": "demo:tide:word-overload",
            "actions": [
                {"label": "在深改姿态里看", "intent": "primary", "op": "nav", "nav_to": "writer", "nav_posture": "deep"},
                {"label": "知道了", "intent": "quiet", "op": "resolve"},
            ],
        },
        actor_ref="demo_seed",
    )
    session.flush()
