"""FE-ALIGN Phase 2: 写作统计服务端化（决策 D2：服务端计算，时区 Asia/Shanghai）。

数据源：正文保存主路径（AuthorDraftService.save）在保存时上报 words_delta，
不另开上报端点。today/streak 规则照抄原型 design/ws-catalog.jsx：

- catAddToday: 只记正向增量；自然日切换时今日计数清零重记。
- catBumpStreak: 当天首次正向增量记账 —— 昨天也写过则 +1，否则重记为 1。
- catEffectiveStreak: 展示态 —— 最后记账日是今天或昨天则取 streak，否则 0。

字数口径与写作器一致（wrCountOf）：剥掉 HTML 标签后去全部空白字符的字符数。
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from novel_system.db.models import ProjectWritingStats, StoryProject, utcnow

WRITING_STATS_TZ = ZoneInfo("Asia/Shanghai")

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def count_words(text: str | None) -> int:
    """原型口径：el.innerText.replace(/\\s/g, "").length —— 中文按字符计数。"""
    if not text:
        return 0
    stripped = _TAG_RE.sub("", text)
    return len(_WS_RE.sub("", stripped))


def _local_day(now: datetime) -> str:
    return now.astimezone(WRITING_STATS_TZ).date().isoformat()


def _yesterday(day: str) -> str:
    return (datetime.fromisoformat(day) - timedelta(days=1)).date().isoformat()


class WritingStatsService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def _row(self, project_id: str, *, create: bool = False) -> ProjectWritingStats | None:
        row = self.session.get(ProjectWritingStats, project_id)
        if row is None and create:
            row = ProjectWritingStats(project_id=project_id)
            self.session.add(row)
            self.session.flush()
        return row

    def record_words_delta(
        self, project_id: str, delta: int, *, now: datetime | None = None
    ) -> ProjectWritingStats:
        """正文保存埋点：净增减都计入 words_total；今日/连续天数只认正向增量。"""
        moment = now or datetime.now(WRITING_STATS_TZ)
        today = _local_day(moment)
        row = self._row(project_id, create=True)
        row.words_total = max(0, int(row.words_total or 0) + int(delta))
        if delta > 0:
            if row.day != today:
                row.day = today
                row.words_today = 0
            row.words_today = int(row.words_today or 0) + int(delta)
            self._bump_streak(row, today)
        row.last_active_at = moment.astimezone(WRITING_STATS_TZ).isoformat()
        self.session.flush()
        return row

    @staticmethod
    def _bump_streak(row: ProjectWritingStats, today: str) -> None:
        if row.streak_last_day == today:
            return
        yesterday = _yesterday(today)
        row.streak_days = (int(row.streak_days or 0) + 1) if row.streak_last_day == yesterday else 1
        row.streak_last_day = today

    def stats_payload(
        self, project_id: str, *, now: datetime | None = None
    ) -> dict[str, Any]:
        moment = now or datetime.now(WRITING_STATS_TZ)
        today = _local_day(moment)
        yesterday = _yesterday(today)
        row = self._row(project_id)
        project = self.session.get(StoryProject, project_id)
        words_target_daily = getattr(project, "words_target_daily", None) if project else None
        if row is None:
            return {
                "words_total": 0,
                "words_today": 0,
                "words_target_daily": words_target_daily,
                "streak_days": 0,
                "last_active_at": None,
            }
        effective_streak = (
            int(row.streak_days or 0)
            if row.streak_last_day in (today, yesterday)
            else 0
        )
        return {
            "words_total": int(row.words_total or 0),
            "words_today": int(row.words_today or 0) if row.day == today else 0,
            "words_target_daily": words_target_daily,
            "streak_days": effective_streak,
            "last_active_at": row.last_active_at,
        }

    def seed_stats(
        self,
        project_id: str,
        *,
        words_total: int = 0,
        streak_days: int = 0,
        streak_last_day: str | None = None,
        last_active_at: str | None = None,
    ) -> ProjectWritingStats:
        """demo seed 用：直接写入统计基线（不走增量记账）。"""
        row = self._row(project_id, create=True)
        row.words_total = int(words_total)
        row.streak_days = int(streak_days)
        row.streak_last_day = streak_last_day
        row.day = None
        row.words_today = 0
        row.last_active_at = last_active_at or utcnow()
        self.session.flush()
        return row
