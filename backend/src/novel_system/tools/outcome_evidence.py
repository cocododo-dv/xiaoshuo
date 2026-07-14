from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from novel_system.services.outcome_evidence import (
    EvidenceProvenance,
    read_manifest,
    require_provenance,
    validate_c0_gate_profile,
    validate_c1b_gate_profile,
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
        "--profile",
        choices=("c0", "c1b"),
        help="require a complete validation profile",
    )
    validate_parser.add_argument(
        "--require-provenance",
        action="append",
        choices=("synthetic", "offline", "real_model", "human"),
        default=[],
    )
    args = parser.parse_args(argv)

    try:
        manifest = read_manifest(
            args.manifest,
            c1b_strict=args.profile == "c1b",
        )
        artifact_root = (
            Path(args.artifact_root)
            if args.artifact_root is not None
            else Path(args.manifest).parent
        )
        artifact_snapshots: dict[str, bytes] = {}
        evidence_errors = validate_manifest_evidence(
            manifest,
            artifact_root,
            profile="c1b" if args.profile == "c1b" else None,
            snapshot_sink=(
                artifact_snapshots if args.profile == "c1b" else None
            ),
        )
        if args.profile == "c0":
            evidence_errors.extend(validate_c0_gate_profile(manifest))
        elif args.profile == "c1b":
            evidence_errors.extend(
                validate_c1b_gate_profile(manifest, artifact_snapshots)
            )
        if evidence_errors:
            raise ValueError("; ".join(evidence_errors))
        required: set[EvidenceProvenance] = set(args.require_provenance)
        if required:
            require_provenance(manifest, required)
    except (OSError, RuntimeError, ValueError) as exc:
        print(
            json.dumps({"valid": False, "error": str(exc)}, ensure_ascii=False),
            file=sys.stderr,
        )
        return 1

    result: dict[str, object] = {"valid": True, "run_id": manifest.run_id}
    if args.profile == "c1b":
        result.update(
            {
                "profile": "c1b",
                "conclusion": "C1B_OFFLINE_EVIDENCE_VALIDATED",
            }
        )
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
