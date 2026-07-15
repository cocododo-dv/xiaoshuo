"""Apply a verified human blind-evaluation report to the production policy file."""
from __future__ import annotations

import argparse
import json
import sys

from novel_system.services.evaluation_experiment import EvaluationExperimentService
from novel_system.services.outcome_governance_policy import apply_evaluation_report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="apply an eligible blind-evaluation policy decision")
    parser.add_argument("--db", required=True, metavar="EXPERIMENT_ID")
    parser.add_argument("--config", help="override the production policy JSON path")
    args = parser.parse_args(argv)

    from novel_system.db.session import SessionLocal

    with SessionLocal() as session:
        report = EvaluationExperimentService(session).build_report(args.db)
    try:
        payload = apply_evaluation_report(report, path=args.config)
    except ValueError as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
