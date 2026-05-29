"""旧 reference_learning 数据层的备份与清理。

PR-1 决策(plans/style-reference-v1-1-fancy-shannon.md):
- backup_legacy_to_json: 把旧 reference_profiles 表整体 dump 到
  backups/style_reference_legacy_{YYYYMMDD_HHMMSS}.json,UTC 时间戳。
  表已被 drop 时返回 0 行结果,不抛错(便于幂等重跑)。
- purge_legacy_review_items: 三路并清 review_items 中的孤立残留:
    1) review_id LIKE 'review_reffind_%'  (代码事实,reference_learning.py:506-507)
    2) review_id LIKE 'review_apply_%'    (文档字面 + 实际生成,reference_learning.py:610/626)
    3) candidate_payload_json.source IN {reference_book_learning, reference_profile_apply} 的兜底
- cleanup_legacy_state: 编排两者,供 reset_style_reference CLI 与 migration 0036 前置使用。
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

LEGACY_BACKUP_PREFIX = "style_reference_legacy_"
LEGACY_BACKUP_SUFFIX = ".json"

LEGACY_REVIEW_PREFIXES = ("review_reffind_", "review_apply_")
LEGACY_REVIEW_SOURCES = ("reference_book_learning", "reference_profile_apply")


def _utc_timestamp() -> str:
    return datetime.now(UTC).strftime("%Y%m%d_%H%M%S")


def default_backup_dir(repo_root: Path | None = None) -> Path:
    """`backups/` 相对仓库根的固定位置。"""
    root = repo_root or Path(__file__).resolve().parents[5]
    return root / "backups"


def find_existing_backups(backup_dir: Path) -> list[Path]:
    if not backup_dir.exists():
        return []
    return sorted(backup_dir.glob(f"{LEGACY_BACKUP_PREFIX}*{LEGACY_BACKUP_SUFFIX}"))


def backup_legacy_to_json(
    session: Session,
    backup_dir: Path | None = None,
    *,
    timestamp: str | None = None,
) -> tuple[Path, int]:
    """从旧 reference_profiles 表导出 JSON 备份。

    返回 (路径, 行数)。若表已被 drop,row_count = 0 且文件仍写入(便于后续 glob 断言通过)。
    """
    backup_dir = backup_dir or default_backup_dir()
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = timestamp or _utc_timestamp()
    target = backup_dir / f"{LEGACY_BACKUP_PREFIX}{stamp}{LEGACY_BACKUP_SUFFIX}"

    rows: list[dict[str, Any]] = []
    try:
        result = session.execute(text("SELECT * FROM reference_profiles"))
        for row in result.mappings():
            rows.append(dict(row))
    except OperationalError:
        # 表已被 drop;允许幂等重跑,不抛错
        rows = []

    payload = {
        "exported_at": datetime.now(UTC).isoformat(),
        "source_table": "reference_profiles",
        "row_count": len(rows),
        "profiles": rows,
    }
    target.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    return target, len(rows)


def purge_legacy_review_items(session: Session) -> dict[str, int]:
    """三路并清旧 reference 模块在 review_items 中的孤立行。

    返回每路删除计数,供 CLI / 测试断言。
    """
    counts: dict[str, int] = {}

    for prefix in LEGACY_REVIEW_PREFIXES:
        result = session.execute(
            text("DELETE FROM review_items WHERE review_id LIKE :pattern"),
            {"pattern": f"{prefix}%"},
        )
        counts[prefix] = int(result.rowcount or 0)

    # 兜底:source 在 LEGACY_REVIEW_SOURCES 中、但 review_id 既不是 reffind 也不是 apply 前缀的孤儿行。
    # 注:sqlite 通过 json_extract 读 JSON 字段。
    orphan_clauses = " AND ".join(
        f"review_id NOT LIKE '{prefix}%'" for prefix in LEGACY_REVIEW_PREFIXES
    )
    placeholders = ", ".join(f"'{src}'" for src in LEGACY_REVIEW_SOURCES)
    orphan_sql = (
        "DELETE FROM review_items WHERE "
        f"json_extract(candidate_payload_json, '$.source') IN ({placeholders}) "
        f"AND {orphan_clauses}"
    )
    result = session.execute(text(orphan_sql))
    counts["orphan_source"] = int(result.rowcount or 0)

    return counts


def cleanup_legacy_state(
    session: Session,
    *,
    backup_dir: Path | None = None,
    do_backup: bool = True,
    do_purge: bool = True,
) -> dict[str, Any]:
    """编排 backup + purge,返回执行摘要。

    供 `tools/reset_style_reference.py` 与 migration 0036 的前置流程使用。
    """
    summary: dict[str, Any] = {"backup": None, "purge": None}

    if do_backup:
        path, row_count = backup_legacy_to_json(session, backup_dir=backup_dir)
        summary["backup"] = {"path": str(path), "row_count": row_count}

    if do_purge:
        summary["purge"] = purge_legacy_review_items(session)

    return summary


# ---------------------------------------------------------------------------
# PR-11 — metric_events 表 cleanup(append-only,定期按 created_at 删旧数据)
# ---------------------------------------------------------------------------


def cleanup_metric_events(
    session: Session,
    *,
    days_threshold: int = 90,
    dry_run: bool = True,
) -> dict[str, Any]:
    """删除 ``style_reference_metric_events`` 中超过 ``days_threshold`` 天的事件。

    ``dry_run=True``(默认)只统计,不执行 DELETE;``dry_run=False`` 真删。
    返回执行摘要 dict,包含 ``deleted_count`` / ``oldest_kept_at`` /
    ``dry_run`` / ``days_threshold`` / ``cutoff`` / ``executed_at``。

    本函数 flush 但不 commit;由调用方(CLI / 测试)负责事务提交。
    """
    from datetime import timedelta

    now = datetime.now(UTC)
    cutoff_dt = now - timedelta(days=int(days_threshold))
    cutoff = cutoff_dt.strftime("%Y-%m-%dT%H:%M:%SZ")

    count_row = session.execute(
        text(
            "SELECT COUNT(*) FROM style_reference_metric_events "
            "WHERE created_at < :cutoff"
        ),
        {"cutoff": cutoff},
    ).scalar()
    deleted_count = int(count_row or 0)

    oldest_kept = session.execute(
        text(
            "SELECT MIN(created_at) FROM style_reference_metric_events "
            "WHERE created_at >= :cutoff"
        ),
        {"cutoff": cutoff},
    ).scalar()

    if not dry_run and deleted_count > 0:
        session.execute(
            text(
                "DELETE FROM style_reference_metric_events WHERE created_at < :cutoff"
            ),
            {"cutoff": cutoff},
        )
        session.flush()

    return {
        "deleted_count": deleted_count,
        "oldest_kept_at": oldest_kept,
        "dry_run": dry_run,
        "days_threshold": int(days_threshold),
        "cutoff": cutoff,
        "executed_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
