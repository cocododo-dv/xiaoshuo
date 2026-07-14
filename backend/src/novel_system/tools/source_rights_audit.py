"""盘点并可显式降级缺少云端发送权声明的历史风格参考书。"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from novel_system.db.models import StyleReferenceBook
from novel_system.db.session import SessionLocal
from novel_system.services.style_reference.policy import cloud_llm_allowed
from novel_system.services.style_reference.schemas import CloudPolicy


MISSING_RIGHTS_REASON = "missing_declared_send_rights"
INVALID_POLICY_REASON = "invalid_cloud_policy"
KNOWN_CLOUD_POLICIES = {
    CloudPolicy.SEGMENTS_ONLY.value,
    CloudPolicy.ALLOW_FULL_CLOUD.value,
}


def _downgraded_at() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def audit_source_rights(session: Session, *, apply: bool = False) -> dict[str, Any]:
    """报告历史违规；仅在 ``apply=True`` 时幂等降级为 ``local_only``。"""
    books = list(
        session.scalars(
            select(StyleReferenceBook).order_by(StyleReferenceBook.book_id)
        ).all()
    )
    violations_with_reasons = [
        (
            book,
            MISSING_RIGHTS_REASON
            if book.cloud_policy in KNOWN_CLOUD_POLICIES
            else INVALID_POLICY_REASON,
        )
        for book in books
        if book.cloud_policy != CloudPolicy.LOCAL_ONLY.value
        and not cloud_llm_allowed(book)
    ]
    violations = [
        {
            "book_id": book.book_id,
            "cloud_policy": book.cloud_policy,
            "reason": reason,
        }
        for book, reason in violations_with_reasons
    ]

    downgraded_count = 0
    if apply:
        try:
            downgraded_at = _downgraded_at()
            for book, reason in violations_with_reasons:
                previous_policy = book.cloud_policy
                stats = (
                    dict(book.stats_json)
                    if isinstance(book.stats_json, dict)
                    else {"legacy_stats_json": book.stats_json}
                )
                stats["rights_policy_migration"] = {
                    "previous_cloud_policy": previous_policy,
                    "reason": reason,
                    "downgraded_at": downgraded_at,
                }
                book.stats_json = stats
                book.cloud_policy = CloudPolicy.LOCAL_ONLY.value
            session.commit()
            downgraded_count = len(violations_with_reasons)
        except Exception:
            session.rollback()
            raise

    return {
        "clean": apply or not violations,
        "violation_count": len(violations),
        "downgraded_count": downgraded_count,
        "violations": violations,
    }


def _print_report(report: dict[str, Any], *, as_json: bool) -> None:
    if as_json:
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
        return
    print(
        f"clean={report['clean']} violation_count={report['violation_count']} "
        f"downgraded_count={report['downgraded_count']}"
    )
    for violation in report["violations"]:
        print(
            f"  {violation['book_id']}: cloud_policy={violation['cloud_policy']} "
            f"reason={violation['reason']}"
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="盘点缺少显式云端发送权声明的历史风格参考书"
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="将违规记录降级为 local_only（默认只读盘点）",
    )
    parser.add_argument("--json", action="store_true", help="输出稳定 JSON 报告")
    args = parser.parse_args(argv)

    session: Session | None = None
    try:
        session = SessionLocal()
        report = audit_source_rights(session, apply=args.apply)
    except Exception as exc:  # noqa: BLE001 - CLI 顶层需稳定映射退出码
        if session is not None:
            session.rollback()
        error = {"clean": False, "error": str(exc)}
        if args.json:
            print(
                json.dumps(error, ensure_ascii=False, sort_keys=True),
                file=sys.stderr,
            )
        else:
            print(f"source rights audit failed: {exc}", file=sys.stderr)
        return 2
    finally:
        if session is not None:
            session.close()

    _print_report(report, as_json=args.json)
    if args.apply:
        return 0
    return 0 if report["clean"] else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
