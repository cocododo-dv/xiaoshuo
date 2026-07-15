"""Apply a verified human blind-evaluation report to the production policy file."""
from __future__ import annotations

import argparse
import json
import os
import sys

from novel_system.services.evaluation_experiment import EvaluationExperimentService
from novel_system.services.outcome_governance_policy import apply_evaluation_report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="apply an eligible blind-evaluation policy decision")
    parser.add_argument(
        "--experiment",
        "--db",  # 兼容别名（历史文档写的是 --db，但它接的是实验 ID 不是数据库）
        dest="experiment_id",
        required=True,
        metavar="EXPERIMENT_ID",
        help="盲评实验 ID",
    )
    parser.add_argument(
        "--database-url",
        help="隔离实验库的 SQLAlchemy URL；缺省时用当前环境的 NOVEL_SYSTEM_DATABASE_URL",
    )
    parser.add_argument("--config", help="override the production policy JSON path")
    args = parser.parse_args(argv)

    if args.database_url:
        os.environ["NOVEL_SYSTEM_DATABASE_URL"] = args.database_url

    from novel_system.db.session import SessionLocal, reset_engine

    if args.database_url:
        reset_engine()

    with SessionLocal() as session:
        report = EvaluationExperimentService(session).build_report(args.experiment_id)
    try:
        payload = apply_evaluation_report(report, path=args.config)
    except ValueError as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
