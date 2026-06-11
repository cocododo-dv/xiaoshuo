"""FE-ALIGN Phase 5: 实时派生待办（原型 ws-review rvDerived 的后端化）。

纯读函数：每次 GET 时从工作台真相（雪花步骤 / 目录 / 起草状态）现算，
不落库。三条语义（简报 ⚠️）：
① live=True，端点拒绝无动作 resolve；
② 源头修好，下次 GET 自动消失；
③ id 带内容指纹 —— 状况变化即新 id，即使旧指纹曾 snooze 也重新浮现
   （snooze 记录按指纹存 review_derived_snoozes）。

首批三类：雪花步骤空缺/不完整、目录结构异常（空章/成稿无字）、产出待办
（审阅中章待批准 / 全场成稿可送审 —— 对齐原型第 5 类派生）。
"""
from __future__ import annotations

import hashlib
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from novel_system.db.models import SnowflakeStepRun, StoryProject
from novel_system.services.catalog import CatalogService
from novel_system.services.snowflake_steps import list_step_definitions


def _fingerprint(*parts: Any) -> str:
    return hashlib.sha256("|".join(str(p) for p in parts).encode("utf-8")).hexdigest()[:10]


def _gate_satisfied(run: SnowflakeStepRun | None) -> bool:
    if run is None:
        return False
    if run.status in {"approved", "skipped"}:
        return True
    return run.status == "stale" and bool(run.stale_accepted_at)


def derive_cards(session: Session, project_id: str) -> list[dict[str, Any]]:
    project = session.get(StoryProject, project_id)
    if project is None:
        return []
    cards: list[dict[str, Any]] = []
    cards.extend(_snowflake_gaps(session, project_id))
    cards.extend(_catalog_anomalies(session, project))
    return cards


def _snowflake_gaps(session: Session, project_id: str) -> list[dict[str, Any]]:
    rows = session.execute(
        select(SnowflakeStepRun)
        .where(SnowflakeStepRun.project_id == project_id)
        .order_by(SnowflakeStepRun.version.asc(), SnowflakeStepRun.created_at.asc())
    ).scalars().all()
    latest: dict[str, SnowflakeStepRun] = {}
    for row in rows:
        if row.status != "superseded":
            latest[row.step_key] = row
    if not latest:
        return []  # 还没开始雪花：不催
    steps = list_step_definitions()
    cards: list[dict[str, Any]] = []
    max_satisfied_index = max(
        (index for index, step in enumerate(steps) if _gate_satisfied(latest.get(step["step_key"]))),
        default=-1,
    )
    for index, step in enumerate(steps):
        run = latest.get(step["step_key"])
        if _gate_satisfied(run):
            continue
        drafted = run is not None and run.status == "pending_review"
        gap_behind = index < max_satisfied_index  # 后续步骤已确认，本步却是空缺/未确认
        if not drafted and not gap_behind:
            continue  # 顺序推进中的「下一步」不算异常
        status_sig = run.status if run is not None else "missing"
        cards.append(
            {
                "id": f"derived:snowflake:{step['step_key']}:{_fingerprint(status_sig)}",
                "live": True,
                "kind": "idea",
                "priority": 1 if gap_behind else 2,
                "title": (
                    f"雪花「{step['label']}」{'已被跳过遗留空缺' if status_sig == 'missing' else '已起草未确认'}"
                ),
                "where": f"构思 · {step['label']}",
                "source": "雪花构思",
                "time": "实时",
                "detail": (
                    f"「{step['label']}」"
                    + ("缺失，而它之后的步骤已确认——补全后这条会自动消失。" if status_sig == "missing"
                       else "停在草稿态。回去确认（或显式跳过）后这条会自动消失。")
                ),
                "actions": [
                    {"label": "去补全", "intent": "primary", "op": "nav", "nav_to": "snowflake", "nav_step": step["step_key"]},
                    {"label": "稍后再说", "intent": "quiet", "op": "snooze"},
                ],
            }
        )
    return cards


def _catalog_anomalies(session: Session, project: StoryProject) -> list[dict[str, Any]]:
    catalog = CatalogService(session)
    cards: list[dict[str, Any]] = []
    chapters = catalog.chapter_rows(project.project_id)
    for index, chapter in enumerate(chapters):
        payload = catalog.chapter_payload(project, chapter, index)
        scenes = payload["scenes"]
        no = payload["no"]
        title = payload["title"]
        if not scenes:
            cards.append(
                {
                    "id": f"derived:catalog:empty:{chapter.chapter_id}:{_fingerprint(title)}",
                    "live": True,
                    "kind": "qc",
                    "priority": 2,
                    "title": f"第 {no} 章《{title}》还没有任何场景",
                    "where": f"章节编排 · 第 {no} 章",
                    "source": "章节编排",
                    "time": "实时",
                    "detail": "空章无法进入起草与成稿流程。去编排台加场景，或删除这一章。加上场景后这条会自动消失。",
                    "actions": [
                        {"label": "去编排", "intent": "primary", "op": "nav", "nav_to": "author"},
                        {"label": "稍后再说", "intent": "quiet", "op": "snooze"},
                    ],
                }
            )
            continue
        empty_done = [s for s in scenes if s["state"] == "done" and not s["words"]]
        if empty_done:
            sig = _fingerprint(*(s["scene_id"] for s in empty_done))
            cards.append(
                {
                    "id": f"derived:catalog:hollow:{chapter.chapter_id}:{sig}",
                    "live": True,
                    "kind": "qc",
                    "priority": 2,
                    "title": f"第 {no} 章有 {len(empty_done)} 场标了成稿却没有正文",
                    "where": f"章节编排 · 第 {no} 章",
                    "source": "起草队列",
                    "time": "实时",
                    "detail": "场景状态是 done 但字数为 0 —— either 正文没保存，or 状态标错。修正后这条会自动消失。",
                    "actions": [
                        {"label": "去写作器看", "intent": "primary", "op": "nav", "nav_to": "writer"},
                        {"label": "稍后再说", "intent": "quiet", "op": "snooze"},
                    ],
                }
            )
        if payload["state"] == "review":
            cards.append(
                {
                    "id": f"derived:catalog:review:{chapter.chapter_id}:{_fingerprint(payload['words']['cur'])}",
                    "live": True,
                    "kind": "decision",
                    "priority": 1,
                    "title": f"第 {no} 章《{title}》待你批准",
                    "where": f"成稿中心 · 第 {no} 章",
                    "source": "成稿中心",
                    "time": "实时",
                    "detail": f"本章 {len(scenes)} 场、{payload['words']['cur']:,} 字，正在审阅中。批准为终稿，或退回小修。",
                    "actions": [
                        {"label": "去审阅", "intent": "primary", "op": "nav", "nav_to": "manuscripts"},
                        {"label": "稍后再说", "intent": "quiet", "op": "snooze"},
                    ],
                }
            )
        elif payload["state"] == "writing" and scenes and all(s["state"] == "done" for s in scenes):
            cards.append(
                {
                    "id": f"derived:catalog:submit:{chapter.chapter_id}:{_fingerprint(len(scenes))}",
                    "live": True,
                    "kind": "qc",
                    "priority": 2,
                    "title": f"第 {no} 章全部场景已成稿 · 可送审",
                    "where": f"成稿中心 · 第 {no} 章",
                    "source": "成稿中心",
                    "time": "实时",
                    "detail": f"《{title}》的 {len(scenes)} 场全部完成。在成稿中心送入审阅，进入批准流程。",
                    "actions": [
                        {"label": "去送审", "intent": "primary", "op": "nav", "nav_to": "manuscripts"},
                        {"label": "稍后再说", "intent": "quiet", "op": "snooze"},
                    ],
                }
            )
    return cards
