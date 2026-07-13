from __future__ import annotations

import importlib
import json
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select

from novel_system.db.models import (
    StyleReferenceBook,
    StyleReferenceParagraph,
    StyleReferenceProfile,
    StyleReferenceQuote,
    StyleReferenceRun,
)


def _audit_tool():
    return importlib.import_module("novel_system.tools.source_rights_audit")


def _book(
    book_id: str,
    *,
    cloud_policy: str,
    stats_json: dict,
) -> StyleReferenceBook:
    return StyleReferenceBook(
        book_id=book_id,
        title=book_id,
        source_kind="upload",
        cloud_policy=cloud_policy,
        text_checksum=f"checksum-{book_id}",
        total_chars=100,
        status="ready",
        stats_json=stats_json,
    )


def _seed_books(session) -> dict[str, StyleReferenceBook]:
    books = {
        "clean_cloud": _book(
            "book-01-clean-cloud",
            cloud_policy="allow_full_cloud",
            stats_json={
                "marker": "clean-cloud",
                "rights_declaration": {"declared": True, "send_rights": True},
            },
        ),
        "missing": _book(
            "book-02-missing",
            cloud_policy="segments_only",
            stats_json={"marker": "missing"},
        ),
        "declared_false": _book(
            "book-03-declared-false",
            cloud_policy="allow_full_cloud",
            stats_json={
                "marker": "declared-false",
                "rights_declaration": {
                    "declared": False,
                    "send_rights": True,
                    "declared_by": "legacy-user",
                },
            },
        ),
        "local": _book(
            "book-04-local",
            cloud_policy="local_only",
            stats_json={"marker": "local"},
        ),
    }
    session.add_all(books.values())
    session.flush()
    return books


def _expected_violations() -> list[dict[str, str]]:
    return [
        {
            "book_id": "book-02-missing",
            "cloud_policy": "segments_only",
            "reason": "missing_declared_send_rights",
        },
        {
            "book_id": "book-03-declared-false",
            "cloud_policy": "allow_full_cloud",
            "reason": "missing_declared_send_rights",
        },
    ]


def test_dry_run_reports_only_violations_without_mutation_or_commit(
    session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tool = _audit_tool()
    books = _seed_books(session)
    before = {
        key: (book.cloud_policy, dict(book.stats_json))
        for key, book in books.items()
    }

    def unexpected_commit() -> None:
        raise AssertionError("dry-run must not commit")

    monkeypatch.setattr(session, "commit", unexpected_commit)

    report = tool.audit_source_rights(session, apply=False)

    assert report == {
        "clean": False,
        "violation_count": 2,
        "downgraded_count": 0,
        "violations": _expected_violations(),
    }
    assert {
        key: (book.cloud_policy, book.stats_json)
        for key, book in books.items()
    } == before


def test_apply_downgrades_only_violations_preserves_data_and_is_idempotent(
    session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tool = _audit_tool()
    books = _seed_books(session)
    session.add_all(
        [
            StyleReferenceParagraph(
                paragraph_id="paragraph-preserved",
                book_id=books["missing"].book_id,
                paragraph_index=0,
                paragraph_type="narration",
                start_offset=0,
                end_offset=9,
                text="preserved",
                char_count=9,
                classifier_confidence=0.9,
            ),
            StyleReferenceRun(
                run_id="run-preserved",
                book_id=books["missing"].book_id,
                status="done",
                phase="done",
            ),
            StyleReferenceQuote(
                quote_id="quote-preserved",
                book_id=books["missing"].book_id,
                paragraph_id="paragraph-preserved",
                span_start=0,
                span_end=9,
                quote_text="preserved",
                illustrates_dims=["rhythm"],
                extracted_features={"marker": "quote"},
            ),
        ]
    )
    session.flush()
    session.add(
        StyleReferenceProfile(
            profile_id="profile-preserved",
            book_id=books["missing"].book_id,
            run_id="run-preserved",
            title="preserved",
            status="active",
            profile_json={"marker": "profile"},
            coverage_json={},
            source_finding_ids_json=[],
        )
    )
    session.flush()

    real_commit = session.commit
    commit_calls = 0

    def tracked_commit() -> None:
        nonlocal commit_calls
        commit_calls += 1
        real_commit()

    monkeypatch.setattr(session, "commit", tracked_commit)

    report = tool.audit_source_rights(session, apply=True)

    assert report == {
        "clean": True,
        "violation_count": 2,
        "downgraded_count": 2,
        "violations": _expected_violations(),
    }
    assert commit_calls == 1
    assert books["clean_cloud"].cloud_policy == "allow_full_cloud"
    assert books["local"].cloud_policy == "local_only"
    assert books["missing"].cloud_policy == "local_only"
    assert books["declared_false"].cloud_policy == "local_only"

    for key, previous_policy in (
        ("missing", "segments_only"),
        ("declared_false", "allow_full_cloud"),
    ):
        stats = books[key].stats_json
        assert stats["marker"] in {"missing", "declared-false"}
        migration = stats["rights_policy_migration"]
        assert migration["previous_cloud_policy"] == previous_policy
        assert migration["reason"] == "missing_declared_send_rights"
        assert isinstance(migration["downgraded_at"], str)
        assert migration["downgraded_at"].endswith("Z")

    assert "rights_declaration" not in books["missing"].stats_json
    assert books["declared_false"].stats_json["rights_declaration"] == {
        "declared": False,
        "send_rights": True,
        "declared_by": "legacy-user",
    }
    assert session.scalar(select(func.count(StyleReferenceParagraph.paragraph_id))) == 1
    assert session.scalar(select(func.count(StyleReferenceProfile.profile_id))) == 1
    assert session.scalar(select(func.count(StyleReferenceQuote.quote_id))) == 1

    monkeypatch.setattr(session, "commit", real_commit)
    second_report = tool.audit_source_rights(session, apply=True)
    assert second_report == {
        "clean": True,
        "violation_count": 0,
        "downgraded_count": 0,
        "violations": [],
    }


def test_apply_rolls_back_and_reraises_on_commit_failure(
    session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tool = _audit_tool()
    _seed_books(session)
    real_rollback = session.rollback
    rollback_calls = 0

    def failed_commit() -> None:
        raise RuntimeError("commit failed")

    def tracked_rollback() -> None:
        nonlocal rollback_calls
        rollback_calls += 1
        real_rollback()

    monkeypatch.setattr(session, "commit", failed_commit)
    monkeypatch.setattr(session, "rollback", tracked_rollback)

    with pytest.raises(RuntimeError, match="commit failed"):
        tool.audit_source_rights(session, apply=True)

    assert rollback_calls == 1


def test_unknown_cloud_policies_are_reported_and_downgraded(session) -> None:
    tool = _audit_tool()
    rights = {"declared": True, "send_rights": True}
    session.add_all(
        [
            _book(
                "book-empty-policy",
                cloud_policy="",
                stats_json={"rights_declaration": rights, "marker": "empty"},
            ),
            _book(
                "book-unknown-policy",
                cloud_policy="legacy_cloud",
                stats_json={"rights_declaration": rights, "marker": "unknown"},
            ),
        ]
    )
    session.flush()

    dry_run = tool.audit_source_rights(session, apply=False)
    assert dry_run == {
        "clean": False,
        "violation_count": 2,
        "downgraded_count": 0,
        "violations": [
            {
                "book_id": "book-empty-policy",
                "cloud_policy": "",
                "reason": "invalid_cloud_policy",
            },
            {
                "book_id": "book-unknown-policy",
                "cloud_policy": "legacy_cloud",
                "reason": "invalid_cloud_policy",
            },
        ],
    }

    applied = tool.audit_source_rights(session, apply=True)
    assert applied["clean"] is True
    assert applied["downgraded_count"] == 2
    assert session.get(StyleReferenceBook, "book-empty-policy").cloud_policy == "local_only"
    assert session.get(StyleReferenceBook, "book-unknown-policy").cloud_policy == "local_only"
    assert (
        session.get(StyleReferenceBook, "book-empty-policy")
        .stats_json["rights_policy_migration"]["reason"]
        == "invalid_cloud_policy"
    )
    assert (
        session.get(StyleReferenceBook, "book-unknown-policy")
        .stats_json["rights_policy_migration"]["reason"]
        == "invalid_cloud_policy"
    )


@pytest.mark.parametrize(
    ("book_id", "legacy_stats"),
    [
        (
            "book-legacy-list",
            ["first", {"nested": [1, 2, 3]}, 17, False],
        ),
        ("book-legacy-scalar", "legacy-stats-value"),
        ("book-legacy-null", None),
    ],
)
def test_apply_preserves_non_dict_stats_json(
    session,
    book_id: str,
    legacy_stats: object,
) -> None:
    tool = _audit_tool()
    session.add(
        _book(
            book_id,
            cloud_policy="segments_only",
            stats_json=legacy_stats,
        )
    )
    session.flush()

    report = tool.audit_source_rights(session, apply=True)

    assert report["downgraded_count"] == 1
    migrated = session.get(StyleReferenceBook, book_id).stats_json
    assert migrated["legacy_stats_json"] == legacy_stats
    assert set(migrated) == {"legacy_stats_json", "rights_policy_migration"}
    assert migrated["rights_policy_migration"]["previous_cloud_policy"] == "segments_only"
    assert (
        migrated["rights_policy_migration"]["reason"]
        == "missing_declared_send_rights"
    )


def test_cli_dry_run_violation_returns_one_with_stable_json(session, capsys) -> None:
    tool = _audit_tool()
    _seed_books(session)
    session.commit()

    first_code = tool.main(["--json"])
    first = capsys.readouterr()
    second_code = tool.main(["--json"])
    second = capsys.readouterr()

    assert first_code == second_code == 1
    assert first.err == second.err == ""
    assert first.out == second.out
    assert json.loads(first.out) == {
        "clean": False,
        "violation_count": 2,
        "downgraded_count": 0,
        "violations": _expected_violations(),
    }


def test_cli_clean_dry_run_returns_zero(session, capsys) -> None:
    tool = _audit_tool()
    session.add(
        _book(
            "book-clean-local",
            cloud_policy="local_only",
            stats_json={"marker": "clean"},
        )
    )
    session.commit()

    exit_code = tool.main(["--json"])

    assert exit_code == 0
    assert json.loads(capsys.readouterr().out)["clean"] is True


def test_cli_apply_success_returns_zero_and_downgrades(session, capsys) -> None:
    tool = _audit_tool()
    books = _seed_books(session)
    session.commit()

    exit_code = tool.main(["--apply", "--json"])

    output = capsys.readouterr()
    assert exit_code == 0
    assert output.err == ""
    assert json.loads(output.out)["clean"] is True
    session.expire_all()
    assert session.get(StyleReferenceBook, books["missing"].book_id).cloud_policy == "local_only"
    assert (
        session.get(StyleReferenceBook, books["declared_false"].book_id).cloud_policy
        == "local_only"
    )


def test_cli_session_initialization_exception_returns_two_with_stable_json(
    monkeypatch: pytest.MonkeyPatch,
    capsys,
) -> None:
    tool = _audit_tool()

    def fail_session_init():
        raise RuntimeError("session init failed")

    monkeypatch.setattr(tool, "SessionLocal", fail_session_init)

    first_code = tool.main(["--json"])
    first = capsys.readouterr()
    second_code = tool.main(["--json"])
    second = capsys.readouterr()

    assert first_code == second_code == 2
    assert first.out == second.out == ""
    assert first.err == second.err
    assert json.loads(first.err) == {
        "clean": False,
        "error": "session init failed",
    }


def test_cli_exception_rolls_back_and_returns_two(
    monkeypatch: pytest.MonkeyPatch,
    capsys,
) -> None:
    tool = _audit_tool()
    fake_session = SimpleNamespace(rollback_calls=0, close_calls=0)

    def rollback() -> None:
        fake_session.rollback_calls += 1

    def close() -> None:
        fake_session.close_calls += 1

    fake_session.rollback = rollback
    fake_session.close = close
    monkeypatch.setattr(tool, "SessionLocal", lambda: fake_session)

    def fail_audit(_session, *, apply: bool):
        raise RuntimeError(f"audit failed apply={apply}")

    monkeypatch.setattr(tool, "audit_source_rights", fail_audit)

    exit_code = tool.main(["--apply", "--json"])

    output = capsys.readouterr()
    assert exit_code == 2
    assert fake_session.rollback_calls == 1
    assert fake_session.close_calls == 1
    assert output.out == ""
    assert json.loads(output.err) == {
        "clean": False,
        "error": "audit failed apply=True",
    }
