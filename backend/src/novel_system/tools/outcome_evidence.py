from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from novel_system.services.outcome_evidence import (
    EvidenceProvenance,
    read_manifest,
    require_provenance,
    validate_manifest_evidence,
)


def _main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Outcome evidence manifest tools"
    )
    subparsers = parser.add_subparsers(required=True)
    validate_parser = subparsers.add_parser("validate")
    validate_parser.add_argument("manifest")
    validate_parser.add_argument("--artifact-root")
    validate_parser.add_argument(
        "--require-provenance",
        action="append",
        choices=("synthetic", "offline", "real_model", "human"),
        default=[],
    )
    args = parser.parse_args(argv)

    try:
        manifest = read_manifest(args.manifest)
        artifact_root = (
            Path(args.artifact_root)
            if args.artifact_root is not None
            else Path(args.manifest).parent
        )
        evidence_errors = validate_manifest_evidence(manifest, artifact_root)
        if evidence_errors:
            raise ValueError("; ".join(evidence_errors))
        required: set[EvidenceProvenance] = set(args.require_provenance)
        if required:
            require_provenance(manifest, required)
    except ValueError as exc:
        print(
            json.dumps({"valid": False, "error": str(exc)}, ensure_ascii=False),
            file=sys.stderr,
        )
        return 1

    print(
        json.dumps(
            {"valid": True, "run_id": manifest.run_id},
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
