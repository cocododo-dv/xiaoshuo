from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest
from sqlalchemy import event, select

from novel_system.db.models import IdempotencyKey, LlmCall, LlmCallAttempt, OperationLog
from novel_system.services.idempotency import execute_with_idempotency
from novel_system.services.llm_accounting import (
    LLMAccountingRejected,
    LLMCallContext,
    record_rejected_call,
)
from novel_system.services.llm_audit import (
    AUDIT_SUMMARY_BYTE_CAP,
    audit_error_text,
    bounded_identifier,
    fingerprint_identifier,
    sanitize_audit_summary,
)
from novel_system.services.llm_client import LLMRequest
from novel_system.tools.llm_audit_scrub import (
    main as scrub_main,
    scrub_database,
    scrub_llm_audit_data,
)


SECRET = "绝密作者正文-DO-NOT-PERSIST"
ASCII_API_KEY_LIKE_SECRET = "sk-proj-ULTRA_SECRET_MANUSCRIPT_42"


def _serialized(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _add_legacy_audit_rows(
    session,
    *,
    suffix: str,
    provider_request_id: str = SECRET,
) -> tuple[str, str, str]:
    call_id = f"legacy-privacy-call-{suffix}"
    attempt_id = f"legacy-privacy-attempt-{suffix}"
    operation_ref = f"legacy-privacy-{suffix}"
    parent = LlmCall(
        llm_call_id=call_id,
        provider="test",
        model="test",
        node_id="privacy",
        prompt_hash="a" * 64,
        step="privacy",
        project_id="privacy-project",
        request_payload_summary={
            "messages": [{"role": "user", "content": SECRET}],
            "source_draft_content": SECRET,
        },
        response_payload_summary={
            "request_id": provider_request_id,
            "structured_output": {"scene_text": SECRET},
        },
        native_reasoning_json={"reasoning_text": SECRET},
        scope_type="project",
        scope_id="privacy-project",
        estimated_tokens=0,
        reserved_tokens=0,
        budget_charged_tokens=0,
        accounting_status="failed",
    )
    session.add(parent)
    session.add(
        LlmCallAttempt(
            attempt_id=attempt_id,
            llm_call_id=parent.llm_call_id,
            provider_attempt_no=0,
            dispatch_kind="initial",
            request_max_output_tokens=0,
            provider_request_id=provider_request_id,
            prompt_tokens=0,
            completion_tokens=0,
            total_tokens=0,
            estimated_tokens=0,
            reserved_tokens=0,
            budget_charged_tokens=0,
            accounting_status="failed",
            latency_ms=0,
            error_code="PROVIDER_ERROR",
            error_text=SECRET,
        )
    )
    session.add(
        OperationLog(
            event_type="idempotency_started",
            object_type="idempotency_key",
            object_ref=operation_ref,
            payload_json={
                "request_hash": "b" * 64,
                "request_payload": {
                    "review_id": "review-recovery-safe",
                    "author_note": SECRET,
                    "content": SECRET,
                },
            },
        )
    )
    session.commit()
    return call_id, attempt_id, operation_ref


def test_audit_summary_is_content_free_and_strictly_bounded() -> None:
    payload = {
        "messages": [
            {"role": "system", "content": SECRET * 1_000},
            {"role": "user", "content": f"author_note={SECRET}" * 1_000},
        ],
        "source_draft_content": SECRET * 2_000,
        "structured_output": {"scene_text": SECRET * 2_000},
        **{f"untrusted_{index}": SECRET * 100 for index in range(2_000)},
    }

    summary = sanitize_audit_summary(payload)
    rendered = _serialized(summary)

    assert SECRET not in rendered
    assert len(rendered.encode("utf-8")) <= AUDIT_SUMMARY_BYTE_CAP
    assert summary["messages"]["count"] == 2
    assert summary["messages"]["items"][1]["role"] == "user"
    assert summary["source_draft_content"]["kind"] == "text_fingerprint"
    assert summary["structured_output"]["kind"] == "json_fingerprint"
    assert sanitize_audit_summary(summary)["messages"] == summary["messages"]


def test_redacted_identifiers_and_errors_are_idempotent() -> None:
    identifier = bounded_identifier(SECRET)
    private_identifier = fingerprint_identifier(ASCII_API_KEY_LIKE_SECRET)
    error = audit_error_text(SECRET, error_code="PROVIDER_ERROR")

    assert identifier is not None
    assert SECRET not in identifier
    assert bounded_identifier(identifier) == identifier
    assert private_identifier is not None
    assert ASCII_API_KEY_LIKE_SECRET not in private_identifier
    assert fingerprint_identifier(private_identifier) == private_identifier
    assert error is not None
    assert SECRET not in error
    assert audit_error_text(error, error_code="PROVIDER_ERROR") == error


def test_external_request_ids_are_fingerprinted_inside_audit_summaries() -> None:
    summary = sanitize_audit_summary(
        {
            "request_id": ASCII_API_KEY_LIKE_SECRET,
            "provider_request_id": ASCII_API_KEY_LIKE_SECRET,
        }
    )

    expected = fingerprint_identifier(ASCII_API_KEY_LIKE_SECRET)
    assert summary["request_id"] == expected
    assert summary["provider_request_id"] == expected
    assert ASCII_API_KEY_LIKE_SECRET not in _serialized(summary)
    assert sanitize_audit_summary(summary) == summary


def test_rejected_llm_call_persists_only_fingerprints(session) -> None:
    request = LLMRequest(
        model="privacy-test",
        messages=[
            {"role": "system", "content": SECRET * 100},
            {"role": "user", "content": f"author_note={SECRET}" * 100},
        ],
        temperature=0.2,
        max_output_tokens=64,
        response_format="json_object",
        provider="openai_compatible",
        node_id="privacy_test",
    )
    call_id = record_rejected_call(
        session,
        request,
        LLMCallContext(
            scope_type="project",
            scope_id="privacy-project",
            project_id="privacy-project",
            node_id="privacy_test",
            step="privacy_test",
        ),
        LLMAccountingRejected(
            "PRIVACY_TEST_REJECTION",
            f"provider echoed {SECRET}",
            details={"provider_body": SECRET * 1_000},
        ),
        request_payload_summary={
            "source_draft_content": SECRET * 1_000,
            "nested": {"author_note": SECRET * 1_000},
        },
        response_payload_summary={
            "structured_output": {"scene_text": SECRET * 1_000},
            "message": SECRET * 1_000,
        },
    )

    stored = session.get(LlmCall, call_id)
    assert stored is not None
    rendered = _serialized(
        {
            "request": stored.request_payload_summary,
            "response": stored.response_payload_summary,
        }
    )
    assert SECRET not in rendered
    request_bytes = len(_serialized(stored.request_payload_summary).encode("utf-8"))
    response_bytes = len(_serialized(stored.response_payload_summary).encode("utf-8"))
    assert request_bytes <= AUDIT_SUMMARY_BYTE_CAP
    assert response_bytes <= AUDIT_SUMMARY_BYTE_CAP
    assert stored.prompt_hash
    assert session.query(LlmCallAttempt).count() == 0


def test_idempotency_log_omits_request_body_and_replay_still_works(session) -> None:
    payload = {
        "scene_id": "SC_PRIVACY",
        "author_note": SECRET * 500,
        "content": SECRET * 500,
    }

    first, status = execute_with_idempotency(
        session,
        idempotency_key="privacy-idempotency",
        method="POST",
        path_template="/privacy-test",
        payload=payload,
        action=lambda: {"ok": True},
    )
    replay, replay_status = execute_with_idempotency(
        session,
        idempotency_key="privacy-idempotency",
        method="POST",
        path_template="/privacy-test",
        payload=payload,
        action=lambda: {"ok": False},
    )

    started = session.scalars(
        select(OperationLog).where(OperationLog.event_type == "idempotency_started")
    ).one()
    rendered = _serialized(started.payload_json)
    assert SECRET not in rendered
    assert "request_payload" not in started.payload_json
    assert started.payload_json["_request_payload_audit_version"] == 2
    assert started.payload_json["request_payload_summary"]["kind"] == "json_fingerprint"
    assert first["ok"] is True
    assert status is None
    assert replay["ok"] is True
    assert replay_status == "replayed"
    # response_json is the authoritative replay value, not a diagnostic audit copy.
    assert session.get(IdempotencyKey, "privacy-idempotency").response_json == first


def test_operational_scrubber_dry_run_execute_and_idempotence(session) -> None:
    call_id, attempt_id, operation_ref = _add_legacy_audit_rows(
        session,
        suffix="operational",
    )
    engine = session.get_bind()
    write_statements: list[str] = []

    def capture_writes(
        _connection,
        _cursor,
        statement,
        _parameters,
        _context,
        _executemany,
    ) -> None:
        if statement.lstrip().upper().startswith(("UPDATE", "INSERT", "DELETE", "REPLACE")):
            write_statements.append(statement)

    event.listen(engine, "before_cursor_execute", capture_writes)
    try:
        dry_run = scrub_llm_audit_data(
            session.connection(),
            dry_run=True,
            batch_size=1,
        )
    finally:
        event.remove(engine, "before_cursor_execute", capture_writes)

    assert write_statements == []
    assert dry_run["mode"] == "dry_run"
    assert dry_run["totals"] == {"scanned": 3, "would_change": 3, "changed": 0}
    assert SECRET in _serialized(session.get(LlmCall, call_id).request_payload_summary)
    session.rollback()

    database_path = Path(str(engine.url.database))
    session.close()
    executed = scrub_database(database_path, dry_run=False, batch_size=1)
    repeated = scrub_database(database_path, dry_run=False, batch_size=1)

    assert executed["mode"] == "execute"
    assert executed["totals"] == {"scanned": 3, "would_change": 3, "changed": 3}
    assert repeated["totals"] == {"scanned": 3, "would_change": 0, "changed": 0}

    from novel_system.db.session import SessionLocal

    verification_session = SessionLocal()
    try:
        stored = verification_session.get(LlmCall, call_id)
        attempt = verification_session.get(LlmCallAttempt, attempt_id)
        operation = verification_session.scalars(
            select(OperationLog).where(OperationLog.object_ref == operation_ref)
        ).one()
        rendered = _serialized(
            {
                "request": stored.request_payload_summary,
                "response": stored.response_payload_summary,
                "reasoning": stored.native_reasoning_json,
                "attempt_request_id": attempt.provider_request_id,
                "attempt_error": attempt.error_text,
                "operation": operation.payload_json,
            }
        )
        assert SECRET not in rendered
        assert operation.payload_json["_request_payload_audit_version"] == 2
        assert operation.payload_json["request_payload"] == {
            "review_id": "review-recovery-safe"
        }
    finally:
        verification_session.close()


def test_scrubber_cli_dry_run_emits_only_stats(
    session,
    capsys,
) -> None:
    database_path = Path(str(session.get_bind().url.database))
    session.commit()

    exit_code = scrub_main(
        [
            "--database",
            str(database_path),
            "--dry-run",
            "--batch-size",
            "1",
        ]
    )
    output = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert output["schema"] == "llm-audit-scrub-v1"
    assert output["mode"] == "dry_run"
    assert output["totals"] == {"scanned": 0, "would_change": 0, "changed": 0}
    assert "rows" not in output


def test_legacy_redaction_migration_scrubs_llm_and_operation_rows(session) -> None:
    call_id, attempt_id, operation_ref = _add_legacy_audit_rows(
        session,
        suffix="migration",
    )

    migration_path = (
        Path(__file__).parents[1]
        / "alembic"
        / "versions"
        / "20260716_0073_redact_llm_audit_payloads.py"
    )
    spec = importlib.util.spec_from_file_location("migration_0073", migration_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    dry_run = module.redact_legacy_llm_audit(
        session.connection(),
        dry_run=True,
        batch_size=1,
    )
    assert dry_run["totals"] == {"scanned": 3, "would_change": 3, "changed": 0}
    assert SECRET in _serialized(session.get(LlmCall, call_id).request_payload_summary)
    session.rollback()

    executed = module.redact_legacy_llm_audit(
        session.connection(),
        dry_run=False,
        batch_size=1,
    )
    session.commit()
    session.expire_all()

    stored = session.get(LlmCall, call_id)
    attempt = session.get(LlmCallAttempt, attempt_id)
    operation = session.scalars(
        select(OperationLog).where(OperationLog.object_ref == operation_ref)
    ).one()
    rendered = _serialized(
        {
            "request": stored.request_payload_summary,
            "response": stored.response_payload_summary,
            "reasoning": stored.native_reasoning_json,
            "attempt_request_id": attempt.provider_request_id,
            "attempt_error": attempt.error_text,
            "operation": operation.payload_json,
        }
    )
    assert executed["totals"] == {"scanned": 3, "would_change": 3, "changed": 3}
    assert SECRET not in rendered
    assert operation.payload_json["_request_payload_audit_version"] == 2
    assert operation.payload_json["request_payload"] == {
        "review_id": "review-recovery-safe"
    }
    assert operation.payload_json["request_payload_summary"]["kind"] == "json_fingerprint"
    assert attempt.error_text == audit_error_text(SECRET, error_code="PROVIDER_ERROR")

    repeated = module.redact_legacy_llm_audit(
        session.connection(),
        dry_run=False,
        batch_size=1,
    )
    session.commit()
    assert repeated["totals"] == {"scanned": 3, "would_change": 0, "changed": 0}


def test_0073_upgrade_and_scrub_cli_hash_api_key_like_provider_id(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A readable protocol-shaped value is still untrusted provider data."""

    from alembic import command
    from alembic.config import Config

    from novel_system.db.session import SessionLocal, reset_engine

    database_path = tmp_path / "privacy-upgrade.db"
    fake_root = tmp_path / "migration-root"
    backups_dir = fake_root / "backups"
    backups_dir.mkdir(parents=True)
    (backups_dir / "style_reference_legacy_preflight.json").write_text(
        "[]",
        encoding="utf-8",
    )
    backend_dir = Path(__file__).resolve().parents[1]
    config = Config(str(backend_dir / "alembic.ini"))
    config.set_main_option("script_location", str(backend_dir / "alembic"))

    with monkeypatch.context() as migration_env:
        migration_env.setenv(
            "NOVEL_SYSTEM_DATABASE_URL",
            f"sqlite:///{database_path.as_posix()}",
        )
        migration_env.setenv("STYLE_REFERENCE_REPO_ROOT", str(fake_root))
        reset_engine()
        try:
            command.upgrade(config, "20260716_0072")
            reset_engine()
            with SessionLocal() as legacy_session:
                _add_legacy_audit_rows(
                    legacy_session,
                    suffix="ascii-provider-id",
                    provider_request_id=ASCII_API_KEY_LIKE_SECRET,
                )

            reset_engine()
            command.upgrade(config, "head")
            reset_engine()
            with SessionLocal() as verification_session:
                attempt = verification_session.get(
                    LlmCallAttempt,
                    "legacy-privacy-attempt-ascii-provider-id",
                )
                parent = verification_session.get(
                    LlmCall,
                    "legacy-privacy-call-ascii-provider-id",
                )
                assert attempt is not None
                assert parent is not None
                assert attempt.provider_request_id == fingerprint_identifier(
                    ASCII_API_KEY_LIKE_SECRET
                )
                assert ASCII_API_KEY_LIKE_SECRET not in attempt.provider_request_id
                assert parent.response_payload_summary["request_id"] == (
                    fingerprint_identifier(ASCII_API_KEY_LIKE_SECRET)
                )
                assert ASCII_API_KEY_LIKE_SECRET not in _serialized(
                    parent.response_payload_summary
                )

            first = scrub_database(database_path, dry_run=False, batch_size=1)
            repeated = scrub_database(database_path, dry_run=False, batch_size=1)
            assert first["totals"] == {
                "scanned": 3,
                "would_change": 0,
                "changed": 0,
            }
            assert repeated["totals"] == first["totals"]
        finally:
            reset_engine()
