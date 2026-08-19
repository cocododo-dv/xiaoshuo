from __future__ import annotations

import argparse
import json
from pathlib import Path

from novel_system.services.style_reference.rag_evaluation import (
    default_rag_ab_manifest_path,
    run_rag_content_independence_ab,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run the frozen StyleReference RAG content-independence A/B diagnostic."
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=default_rag_ab_manifest_path(),
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    report = run_rag_content_independence_ab(args.manifest)
    serialized = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(serialized, encoding="utf-8")
    print(serialized, end="")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
