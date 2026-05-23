"""CLI:旧 reference_learning 数据层的备份与清理。

子命令(PR-1 决策,plans/style-reference-v1-1-fancy-shannon.md):
- `--backup`            仅生成 backups/style_reference_legacy_*.json
- `--purge-reviews`     仅清理 review_items 中三类孤立残留
- `--backup-and-purge`  顺序执行 backup + purge

二段确认:`--purge-reviews` 与 `--backup-and-purge` 默认 dry-run,加 `--execute --yes` 才真删。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from novel_system.db.session import SessionLocal
from novel_system.services.style_reference.cleanup import (
    backup_legacy_to_json,
    cleanup_legacy_state,
    default_backup_dir,
    find_existing_backups,
    purge_legacy_review_items,
)


def _run_backup(backup_dir: Path | None) -> dict[str, object]:
    with SessionLocal() as session:
        path, row_count = backup_legacy_to_json(session, backup_dir=backup_dir)
    return {
        "mode": "backup",
        "path": str(path),
        "row_count": row_count,
        "status": "ok",
    }


def _run_purge(*, execute: bool) -> dict[str, object]:
    if not execute:
        return {
            "mode": "purge",
            "status": "confirmation_required",
            "hint": "pass --execute --yes to perform the destructive purge",
        }
    with SessionLocal() as session:
        counts = purge_legacy_review_items(session)
        session.commit()
    return {
        "mode": "purge",
        "deleted_counts": counts,
        "status": "ok",
    }


def _run_backup_and_purge(
    *,
    backup_dir: Path | None,
    execute: bool,
) -> dict[str, object]:
    if not execute:
        return {
            "mode": "backup_and_purge",
            "status": "confirmation_required",
            "hint": "pass --execute --yes to perform the destructive purge",
        }
    with SessionLocal() as session:
        summary = cleanup_legacy_state(
            session,
            backup_dir=backup_dir,
            do_backup=True,
            do_purge=True,
        )
        session.commit()
    summary["mode"] = "backup_and_purge"
    summary["status"] = "ok"
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Backup & purge legacy reference_learning state. "
            "PR-1 of style_reference refactor; see plans/style-reference-v1-1-fancy-shannon.md."
        ),
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--backup",
        action="store_true",
        help="dump reference_profiles to backups/style_reference_legacy_*.json",
    )
    group.add_argument(
        "--purge-reviews",
        action="store_true",
        help="delete legacy review_items rows (review_reffind_% / review_apply_% / orphan source)",
    )
    group.add_argument(
        "--backup-and-purge",
        action="store_true",
        help="run backup then purge in one go",
    )
    group.add_argument(
        "--list-backups",
        action="store_true",
        help="list existing backup files (read-only)",
    )

    parser.add_argument(
        "--backup-dir",
        type=Path,
        default=None,
        help="override default backups/ directory (relative to repo root)",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="actually perform destructive purge (required for --purge-reviews / --backup-and-purge)",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="confirm the destructive purge",
    )

    args = parser.parse_args(argv)

    if args.list_backups:
        backups = find_existing_backups(args.backup_dir or default_backup_dir())
        payload = {
            "mode": "list_backups",
            "backup_dir": str(args.backup_dir or default_backup_dir()),
            "files": [str(p) for p in backups],
            "status": "ok",
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    if args.backup:
        result = _run_backup(args.backup_dir)
    elif args.purge_reviews:
        result = _run_purge(execute=args.execute and args.yes)
    else:
        result = _run_backup_and_purge(
            backup_dir=args.backup_dir,
            execute=args.execute and args.yes,
        )

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
