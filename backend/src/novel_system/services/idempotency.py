from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import Any, Callable

from sqlalchemy.orm import Session

from novel_system.db.models import IdempotencyKey, OperationLog
from novel_system.services.errors import DomainError
from novel_system.settings import get_settings


def utcnow() -> datetime:
    return datetime.now(UTC)


def canonical_request_hash(method: str, path_template: str, payload: Any) -> str:
    body = json.dumps(payload or {}, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    raw = f"{method.upper()}::{path_template}::{body}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def execute_with_idempotency(
    session: Session,
    *,
    idempotency_key: str | None,
    method: str,
    path_template: str,
    payload: Any,
    action: Callable[[], dict],
) -> tuple[dict, str | None]:
    if not idempotency_key:
        raise DomainError("IDEMPOTENCY_KEY_REQUIRED", "missing X-Idempotency-Key", status_code=400)

    request_hash = canonical_request_hash(method, path_template, payload)
    record = session.get(IdempotencyKey, idempotency_key)
    now = utcnow()
    lease_expires_at = (now + timedelta(seconds=get_settings().idempotency_ttl_seconds)).isoformat()

    if record is None:
        record = IdempotencyKey(
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            status="started",
            worker_id="http",
            attempt_no=1,
            heartbeat_at=now.isoformat(),
            lease_expires_at=lease_expires_at,
        )
        session.add(record)
        session.flush()
    else:
        if record.request_hash != request_hash:
            raise DomainError(
                "IDEMPOTENCY_KEY_REUSED_WITH_DIFFERENT_PAYLOAD",
                "idempotency key reused with different payload",
                status_code=409,
            )
        if record.status == "succeeded":
            return record.response_json or {}, "replayed"
        if record.status == "started" and record.lease_expires_at and record.lease_expires_at > now.isoformat():
            raise DomainError(
                "IDEMPOTENCY_REQUEST_IN_PROGRESS",
                "request with the same idempotency key is still running",
                status_code=409,
            )
        record.status = "started"
        record.attempt_no += 1
        record.worker_id = "http"
        record.heartbeat_at = now.isoformat()
        record.lease_expires_at = lease_expires_at
        session.add(
            OperationLog(
                event_type="lease_reclaim",
                object_type="idempotency_key",
                object_ref=idempotency_key,
                payload_json={"attempt_no": record.attempt_no},
            )
        )

    try:
        result = action()
        record.status = "succeeded"
        record.response_json = result
        record.heartbeat_at = now.isoformat()
        record.lease_expires_at = lease_expires_at
        session.add(
            OperationLog(
                event_type="idempotency_succeeded",
                object_type="idempotency_key",
                object_ref=idempotency_key,
                payload_json={"request_hash": request_hash},
            )
        )
        session.commit()
        return result, None
    except DomainError:
        record.status = "failed"
        session.commit()
        raise
    except Exception as exc:
        record.status = "failed"
        session.commit()
        raise DomainError("INTERNAL_ERROR", str(exc), status_code=500) from exc
