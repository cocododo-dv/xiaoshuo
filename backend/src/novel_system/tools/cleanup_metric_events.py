"""CLI:清理超过 ``days_threshold`` 天的 style_reference_metric_events 行。

PR-11 §"PR-11 已敲定决策":提供 cleanup 能力,**不接 scheduled job**;
运维手工或外部 cron 直接调本 CLI。

二段确认:默认 dry-run(只统计);加 ``--execute --yes`` 才真删。

Examples
--------
    # 干跑(查看会删除的行数,默认 90 天阈值)
    python -m novel_system.tools.cleanup_metric_events

    # 真删 30 天前的数据(无确认 prompt,供外部 cron 用)
    python -m novel_system.tools.cleanup_metric_events --days 30 --execute --yes
"""

from __future__ import annotations

import argparse
import json
import sys

from novel_system.db.session import SessionLocal
from novel_system.services.style_reference.cleanup import cleanup_metric_events


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cleanup_metric_events",
        description="Cleanup style_reference_metric_events older than --days days.",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=90,
        help="保留最近 N 天的事件(默认 90)。",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="实际执行 DELETE(默认 dry-run,只统计)。",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="无确认 prompt(供 cron / 自动化用)。",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.days < 0:
        print("--days 必须 >= 0", file=sys.stderr)
        return 2

    dry_run = not args.execute
    if not dry_run and not args.yes:
        confirm = input(
            f"将删除 created_at < now - {args.days} 天 的所有 metric_events,确认?(y/N): "
        )
        if confirm.strip().lower() != "y":
            print("已取消", file=sys.stderr)
            return 1

    try:
        with SessionLocal() as session:
            result = cleanup_metric_events(
                session,
                days_threshold=args.days,
                dry_run=dry_run,
            )
            if not dry_run:
                session.commit()
    except Exception as exc:  # noqa: BLE001 — CLI 顶层,打印后退出
        print(f"cleanup 失败:{exc}", file=sys.stderr)
        return 3

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
