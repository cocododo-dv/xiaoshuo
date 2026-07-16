"""Redact legacy prose from durable LLM audit payloads.

Revision ID: 20260716_0073
Revises: 20260716_0072
Create Date: 2026-07-16

The ledger rows, accounting values, prompt hashes and replay/checkpoint hashes
remain intact.  Only diagnostic JSON/text that could duplicate prompts, drafts,
model output or provider error bodies is converted to bounded fingerprints.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

import sqlalchemy as sa
from alembic import op

revision = "20260716_0073"
down_revision = "20260716_0072"
branch_labels = None
depends_on = None

_BATCH_SIZE = 500

# Frozen migration-local snapshot of the v2 audit sanitizer.  Alembic
# migrations must not import the live service helper: that helper can evolve,
# while this historical data rewrite must remain deterministic forever.
_AUDIT_SCHEMA_VERSION = 2
_AUDIT_SUMMARY_BYTE_CAP = 16_384
_AUDIT_COLLECTION_ITEM_CAP = 32
_AUDIT_FIELD_CAP = 64
_AUDIT_DEPTH_CAP = 4
_AUDIT_IDENTIFIER_CHAR_CAP = 256

_SAFE_ATOM = re.compile(r"^[A-Za-z0-9/][A-Za-z0-9_.:/@+\-]*$")
_SAFE_FIELD = re.compile(r"^[A-Za-z_][A-Za-z0-9_.\-]*$")
_HASHED_IDENTIFIER = re.compile(r"^sha256:[0-9a-f]{64};chars=[0-9]+$")
_FINGERPRINT_KINDS = frozenset({"text_fingerprint", "json_fingerprint"})
_SAFE_LITERAL_KEYS = frozenset(
    {
        "_accounting_provider_execution_mode",
        "accounting_status",
        "api_mode",
        "credential_mode",
        "dispatch_kind",
        "endpoint",
        "error_code",
        "error_type",
        "finish_reason",
        "kind",
        "model",
        "model_profile",
        "next_action",
        "node_id",
        "provider",
        "provider_id",
        "reasoning_level",
        "response_format",
        "route_node",
        "scope_type",
        "status",
        "step",
        "step_key",
        "task_key",
        "task_name",
        "template_name",
        "template_version",
        "top_level_type",
    }
)
_SAFE_LITERAL_SUFFIXES = (
    "_code",
    "_hash",
    "_id",
    "_key",
    "_mode",
    "_status",
    "_type",
    "_version",
)
_SAFE_LITERAL_LIST_KEYS = frozenset({"included_sections"})
_UNTRUSTED_IDENTIFIER_KEYS = frozenset({"provider_request_id", "request_id"})
_CONTENT_KEYS = frozenset(
    {
        "content",
        "details_text",
        "draft",
        "error_text",
        "manuscript",
        "message",
        "messages",
        "outline",
        "outline_text",
        "postprocess_error",
        "prompt",
        "prompt_text",
        "raw_output",
        "response_body",
        "scene_text",
        "source_draft_content",
        "structured_output",
        "system_prompt",
        "text",
        "user_prompt",
    }
)


def _text_fingerprint(value: str) -> dict[str, Any]:
    encoded = value.encode("utf-8")
    return {
        "kind": "text_fingerprint",
        "char_count": len(value),
        "utf8_bytes": len(encoded),
        "sha256": hashlib.sha256(encoded).hexdigest(),
    }


def _json_fingerprint(value: Any) -> dict[str, Any]:
    canonical = _canonical_json(value)
    result: dict[str, Any] = {
        "kind": "json_fingerprint",
        "top_level_type": _json_type_name(value),
        "json_bytes": len(canonical),
        "sha256": hashlib.sha256(canonical).hexdigest(),
    }
    if isinstance(value, dict):
        keys = [
            _safe_field_name(key)
            for key in list(value)[:_AUDIT_COLLECTION_ITEM_CAP]
        ]
        result.update(
            {
                "top_level_item_count": len(value),
                "top_level_fields": keys,
                "fields_omitted": max(0, len(value) - len(keys)),
            }
        )
    elif isinstance(value, (list, tuple)):
        result["top_level_item_count"] = len(value)
    return result


def _message_fingerprints(messages: Any) -> dict[str, Any]:
    if not isinstance(messages, (list, tuple)):
        return {"count": 0, "invalid_payload": _json_fingerprint(messages)}
    items: list[dict[str, Any]] = []
    for message in messages[:_AUDIT_COLLECTION_ITEM_CAP]:
        if not isinstance(message, dict):
            items.append({"invalid_message": _json_fingerprint(message)})
            continue
        role = _bounded_identifier(message.get("role"))
        content = message.get("content")
        item: dict[str, Any] = {
            "role": role or "unknown",
            "content": _text_fingerprint(str(content or "")),
        }
        if "name" in message:
            item["name"] = _bounded_identifier(message.get("name"))
        items.append(item)
    return {
        "count": len(messages),
        "items": items,
        "items_omitted": max(0, len(messages) - len(items)),
    }


def _bounded_identifier(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value)
    if _HASHED_IDENTIFIER.fullmatch(text):
        return text
    if len(text) <= _AUDIT_IDENTIFIER_CHAR_CAP and _SAFE_ATOM.fullmatch(text):
        return text
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return f"sha256:{digest};chars={len(text)}"


def _fingerprint_identifier(value: Any) -> str | None:
    """Frozen fail-closed sanitizer for externally controlled identifiers."""

    if value is None:
        return None
    text = str(value)
    if _HASHED_IDENTIFIER.fullmatch(text):
        return text
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return f"sha256:{digest};chars={len(text)}"


def _audit_error_text(value: Any, *, error_code: Any = None) -> str | None:
    if value is None:
        return None
    text = str(value)
    code = _bounded_identifier(error_code) or "ERROR"
    already_redacted = re.compile(
        rf"^{re.escape(code)};message_sha256=[0-9a-f]{{64}};message_chars=[0-9]+$"
    )
    if already_redacted.fullmatch(text):
        return text
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return f"{code};message_sha256={digest};message_chars={len(text)}"


def _sanitize_audit_summary(payload: Any) -> dict[str, Any]:
    raw_fingerprint = _json_fingerprint(payload)
    if isinstance(payload, dict):
        sanitized = _sanitize_dict(payload, depth=0)
    else:
        sanitized = {"value": _sanitize_value(payload, key=None, depth=0)}
    sanitized["_audit_schema_version"] = _AUDIT_SCHEMA_VERSION
    if _serialized_size(sanitized) <= _AUDIT_SUMMARY_BYTE_CAP:
        return sanitized

    compact: dict[str, Any] = {
        "_audit_schema_version": _AUDIT_SCHEMA_VERSION,
        "_audit_compacted": True,
        "payload": raw_fingerprint,
    }
    for key, value in sanitized.items():
        if key.startswith("_audit_") or not _is_contract_key(key):
            continue
        compact[key] = value
        if len(compact) >= _AUDIT_COLLECTION_ITEM_CAP:
            break
    if _serialized_size(compact) <= _AUDIT_SUMMARY_BYTE_CAP:
        return compact
    return {
        "_audit_schema_version": _AUDIT_SCHEMA_VERSION,
        "_audit_compacted": True,
        "payload": raw_fingerprint,
    }


def _sanitize_dict(payload: dict[Any, Any], *, depth: int) -> dict[str, Any]:
    if _looks_like_fingerprint(payload):
        return _validated_fingerprint(payload)
    if depth >= _AUDIT_DEPTH_CAP:
        return _json_fingerprint(payload)

    items = list(payload.items())
    items.sort(key=lambda item: (not _is_contract_key(str(item[0])),))
    selected = items[:_AUDIT_FIELD_CAP]
    result: dict[str, Any] = {}
    for raw_key, value in selected:
        key = _safe_field_name(raw_key)
        result[key] = _sanitize_value(value, key=str(raw_key), depth=depth + 1)
    omitted = len(items) - len(selected)
    if omitted:
        result["_omitted_field_count"] = omitted
        result["_omitted_payload"] = _json_fingerprint(
            dict(items[_AUDIT_FIELD_CAP:])
        )
    return result


def _sanitize_value(value: Any, *, key: str | None, depth: int) -> Any:
    normalized_key = (key or "").lower()
    if isinstance(value, dict) and _looks_like_fingerprint(value):
        return _validated_fingerprint(value)
    if normalized_key in _UNTRUSTED_IDENTIFIER_KEYS:
        return _fingerprint_identifier(value)
    if normalized_key == "messages":
        if isinstance(value, dict) and isinstance(value.get("items"), list):
            return _validated_message_summary(value)
        return _message_fingerprints(value)
    if normalized_key in _CONTENT_KEYS:
        return (
            _text_fingerprint(value)
            if isinstance(value, str)
            else _json_fingerprint(value)
        )
    if isinstance(value, str):
        if _is_safe_literal_key(normalized_key):
            return _bounded_identifier(value)
        return _text_fingerprint(value)
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, dict):
        return _sanitize_dict(value, depth=depth)
    if isinstance(value, (list, tuple)):
        if depth >= _AUDIT_DEPTH_CAP:
            return _json_fingerprint(value)
        selected = list(value[:_AUDIT_COLLECTION_ITEM_CAP])
        result = [
            _sanitize_value(
                item,
                key=normalized_key if normalized_key in _SAFE_LITERAL_LIST_KEYS else None,
                depth=depth + 1,
            )
            for item in selected
        ]
        if len(value) > len(selected):
            result.append(
                {
                    "_items_omitted": len(value) - len(selected),
                    "_omitted_payload": _json_fingerprint(value[len(selected):]),
                }
            )
        return result
    return _json_fingerprint(value)


def _looks_like_fingerprint(payload: dict[Any, Any]) -> bool:
    return (
        payload.get("kind") in _FINGERPRINT_KINDS
        and isinstance(payload.get("sha256"), str)
    )


def _validated_message_summary(payload: dict[Any, Any]) -> dict[str, Any]:
    raw_items = payload.get("items")
    assert isinstance(raw_items, list)
    items: list[dict[str, Any]] = []
    for raw_item in raw_items[:_AUDIT_COLLECTION_ITEM_CAP]:
        if not isinstance(raw_item, dict):
            items.append({"invalid_message": _json_fingerprint(raw_item)})
            continue
        content = raw_item.get("content")
        item: dict[str, Any] = {
            "role": _bounded_identifier(raw_item.get("role")) or "unknown",
            "content": (
                _validated_fingerprint(content)
                if isinstance(content, dict) and _looks_like_fingerprint(content)
                else _text_fingerprint(str(content or ""))
            ),
        }
        if raw_item.get("name") is not None:
            item["name"] = _bounded_identifier(raw_item.get("name"))
        items.append(item)
    count = payload.get("count")
    count = count if isinstance(count, int) and count >= 0 else len(items)
    return {
        "count": count,
        "items": items,
        "items_omitted": max(0, count - len(items)),
    }


def _validated_fingerprint(payload: dict[Any, Any]) -> dict[str, Any]:
    kind = str(payload.get("kind"))
    result: dict[str, Any] = {
        "kind": kind,
        "sha256": _bounded_identifier(payload.get("sha256")),
    }
    for key in (
        "char_count",
        "utf8_bytes",
        "json_bytes",
        "top_level_item_count",
        "fields_omitted",
    ):
        value = payload.get(key)
        if isinstance(value, int) and value >= 0:
            result[key] = value
    if kind == "json_fingerprint":
        result["top_level_type"] = (
            _bounded_identifier(payload.get("top_level_type")) or "unknown"
        )
        fields = payload.get("top_level_fields")
        if isinstance(fields, list):
            result["top_level_fields"] = [
                _safe_field_name(field)
                for field in fields[:_AUDIT_COLLECTION_ITEM_CAP]
            ]
    return result


def _is_safe_literal_key(key: str) -> bool:
    return (
        key in _SAFE_LITERAL_KEYS
        or key in _SAFE_LITERAL_LIST_KEYS
        or key.endswith(_SAFE_LITERAL_SUFFIXES)
    )


def _is_contract_key(key: str) -> bool:
    lowered = key.lower()
    if _is_safe_literal_key(lowered):
        return True
    return lowered.endswith(
        ("_count", "_tokens", "_chars", "_bytes", "_present", "_retryable")
    ) or lowered in {
        "attempt_count",
        "max_retries",
        "retryable",
        "token_budget",
        "continuity_warning",
    }


def _safe_field_name(value: Any) -> str:
    text = str(value)
    if len(text) <= 64 and _SAFE_FIELD.fullmatch(text):
        return text
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:24]
    return f"field_sha256_{digest}"


def _canonical_json(value: Any) -> bytes:
    try:
        rendered = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=_json_default,
        )
    except (TypeError, ValueError):
        rendered = json.dumps(
            {"type": type(value).__name__},
            sort_keys=True,
            separators=(",", ":"),
        )
    return rendered.encode("utf-8")


def _json_default(value: Any) -> dict[str, str]:
    return {"unsupported_type": type(value).__name__}


def _json_type_name(value: Any) -> str:
    if isinstance(value, dict):
        return "object"
    if isinstance(value, (list, tuple)):
        return "array"
    if isinstance(value, str):
        return "string"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)):
        return "number"
    if value is None:
        return "null"
    return "unsupported"


def _serialized_size(value: Any) -> int:
    return len(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    )


def _columns(bind, table_name: str) -> set[str]:
    inspector = sa.inspect(bind)
    if not inspector.has_table(table_name):
        return set()
    return {str(column["name"]) for column in inspector.get_columns(table_name)}


def _new_stats(*, dry_run: bool, batch_size: int) -> dict[str, Any]:
    return {
        "mode": "dry_run" if dry_run else "execute",
        "batch_size": batch_size,
        "tables": {
            table: {"scanned": 0, "would_change": 0, "changed": 0}
            for table in ("llm_calls", "llm_call_attempts", "operation_logs")
        },
        "totals": {"scanned": 0, "would_change": 0, "changed": 0},
    }


def _finish_stats(stats: dict[str, Any]) -> dict[str, Any]:
    for field in ("scanned", "would_change", "changed"):
        stats["totals"][field] = sum(
            int(table_stats[field]) for table_stats in stats["tables"].values()
        )
    return stats


def _commit_batch(bind, *, commit_batches: bool, dry_run: bool) -> None:
    if commit_batches and not dry_run:
        bind.commit()


def _redacted_operation_payload(payload: Any) -> Any:
    if not isinstance(payload, dict) or "request_payload" not in payload:
        return payload
    if payload.get("_request_payload_audit_version") == _AUDIT_SCHEMA_VERSION:
        return payload

    redacted = dict(payload)
    request_payload = redacted.pop("request_payload")
    redacted["_request_payload_audit_version"] = _AUDIT_SCHEMA_VERSION
    redacted["request_payload_summary"] = _json_fingerprint(request_payload)
    recovery_payload = {
        key: _bounded_identifier(request_payload.get(key))
        for key in ("review_id", "job_id")
        if isinstance(request_payload, dict) and request_payload.get(key) is not None
    }
    confirmation = (
        request_payload.get("risk_confirmation")
        if isinstance(request_payload, dict)
        else None
    )
    if isinstance(confirmation, dict):
        reason = confirmation.get("reason")
        if isinstance(reason, str) and reason.strip():
            reason = reason.strip()
            recovery_payload["risk_confirmation"] = {
                "acknowledged": confirmation.get("acknowledged") is True,
                "reason": reason[:512],
                "reason_sha256": hashlib.sha256(reason.encode("utf-8")).hexdigest(),
                "reason_chars": len(reason),
                "reason_truncated": len(reason) > 512,
                "severity": str(confirmation.get("severity") or "high")[:32],
            }
    if recovery_payload:
        redacted["request_payload"] = recovery_payload
    return redacted


def redact_legacy_llm_audit(
    bind,
    *,
    dry_run: bool = False,
    commit_batches: bool = False,
    batch_size: int = _BATCH_SIZE,
) -> dict[str, Any]:
    """Scan or irreversibly redact legacy audit payloads.

    ``dry_run`` never issues UPDATE/COMMIT.  ``commit_batches`` is intended for
    the standalone maintenance command; Alembic leaves it false so the
    migration transaction remains under Alembic's control.
    """

    if batch_size <= 0:
        raise ValueError("batch_size must be positive")
    if dry_run and commit_batches:
        raise ValueError("dry_run cannot commit batches")
    stats = _new_stats(dry_run=dry_run, batch_size=batch_size)
    call_columns = _columns(bind, "llm_calls")
    required_calls = {
        "llm_call_id",
        "request_payload_summary",
        "response_payload_summary",
        "native_reasoning_json",
    }
    if required_calls.issubset(call_columns):
        calls = sa.table(
            "llm_calls",
            sa.column("llm_call_id", sa.String),
            sa.column("request_payload_summary", sa.JSON),
            sa.column("response_payload_summary", sa.JSON),
            sa.column("native_reasoning_json", sa.JSON),
        )
        last_id: str | None = None
        while True:
            query = sa.select(
                calls.c.llm_call_id,
                calls.c.request_payload_summary,
                calls.c.response_payload_summary,
                calls.c.native_reasoning_json,
            ).order_by(calls.c.llm_call_id).limit(batch_size)
            if last_id is not None:
                query = query.where(calls.c.llm_call_id > last_id)
            rows = list(bind.execute(query).mappings())
            if not rows:
                break
            for row in rows:
                table_stats = stats["tables"]["llm_calls"]
                table_stats["scanned"] += 1
                values = {
                    "request_payload_summary": (
                        _sanitize_audit_summary(row["request_payload_summary"])
                        if row["request_payload_summary"] is not None
                        else None
                    ),
                    "response_payload_summary": (
                        _sanitize_audit_summary(row["response_payload_summary"])
                        if row["response_payload_summary"] is not None
                        else None
                    ),
                    "native_reasoning_json": (
                        _sanitize_audit_summary(row["native_reasoning_json"])
                        if row["native_reasoning_json"] is not None
                        else None
                    ),
                }
                if any(values[key] != row[key] for key in values):
                    table_stats["would_change"] += 1
                    if not dry_run:
                        bind.execute(
                            sa.update(calls)
                            .where(calls.c.llm_call_id == row["llm_call_id"])
                            .values(**values)
                        )
                        table_stats["changed"] += 1
            last_id = str(rows[-1]["llm_call_id"])
            _commit_batch(bind, commit_batches=commit_batches, dry_run=dry_run)

    attempt_columns = _columns(bind, "llm_call_attempts")
    required_attempts = {
        "attempt_id",
        "provider_request_id",
        "error_code",
        "error_text",
    }
    if required_attempts.issubset(attempt_columns):
        attempts = sa.table(
            "llm_call_attempts",
            sa.column("attempt_id", sa.String),
            sa.column("provider_request_id", sa.String),
            sa.column("error_code", sa.String),
            sa.column("error_text", sa.Text),
        )
        last_id = None
        while True:
            query = sa.select(
                attempts.c.attempt_id,
                attempts.c.provider_request_id,
                attempts.c.error_code,
                attempts.c.error_text,
            ).order_by(attempts.c.attempt_id).limit(batch_size)
            if last_id is not None:
                query = query.where(attempts.c.attempt_id > last_id)
            rows = list(bind.execute(query).mappings())
            if not rows:
                break
            for row in rows:
                table_stats = stats["tables"]["llm_call_attempts"]
                table_stats["scanned"] += 1
                values = {
                    "provider_request_id": _fingerprint_identifier(
                        row["provider_request_id"]
                    ),
                    "error_text": _audit_error_text(
                        row["error_text"],
                        error_code=row["error_code"],
                    ),
                }
                if any(values[key] != row[key] for key in values):
                    table_stats["would_change"] += 1
                    if not dry_run:
                        bind.execute(
                            sa.update(attempts)
                            .where(attempts.c.attempt_id == row["attempt_id"])
                            .values(**values)
                        )
                        table_stats["changed"] += 1
            last_id = str(rows[-1]["attempt_id"])
            _commit_batch(bind, commit_batches=commit_batches, dry_run=dry_run)

    operation_columns = _columns(bind, "operation_logs")
    if {"operation_id", "payload_json"}.issubset(operation_columns):
        operations = sa.table(
            "operation_logs",
            sa.column("operation_id", sa.Integer),
            sa.column("payload_json", sa.JSON),
        )
        last_operation_id = 0
        while True:
            rows = list(
                bind.execute(
                    sa.select(operations.c.operation_id, operations.c.payload_json)
                    .where(operations.c.operation_id > last_operation_id)
                    .order_by(operations.c.operation_id)
                    .limit(batch_size)
                ).mappings()
            )
            if not rows:
                break
            for row in rows:
                table_stats = stats["tables"]["operation_logs"]
                table_stats["scanned"] += 1
                payload = row["payload_json"]
                redacted = _redacted_operation_payload(payload)
                if redacted != payload:
                    table_stats["would_change"] += 1
                    if not dry_run:
                        bind.execute(
                            sa.update(operations)
                            .where(operations.c.operation_id == row["operation_id"])
                            .values(payload_json=redacted)
                        )
                        table_stats["changed"] += 1
            last_operation_id = int(rows[-1]["operation_id"])
            _commit_batch(bind, commit_batches=commit_batches, dry_run=dry_run)
    return _finish_stats(stats)


def upgrade() -> None:
    redact_legacy_llm_audit(op.get_bind(), dry_run=False, commit_batches=False)


def downgrade() -> None:
    # Redacted prose and provider error bodies must not be reconstructed.
    pass
