from __future__ import annotations

import base64
import hashlib
import time
import uuid
from dataclasses import replace
from pathlib import Path
from typing import Any

import httpx
import yaml
from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from novel_system.db.models import OperationLog, SystemConfigSnapshot, SystemSecret, utcnow
from novel_system.db.session import SessionLocal
from novel_system.services.errors import DomainError
from novel_system.services.hash_engine import normalize
from novel_system.services.llm_client import LLMConfigurationError, SUPPORTED_PROVIDERS, parse_model_routing_config
from novel_system.services.prompt_builder import PromptConfigurationError, parse_prompt_templates


CONFIG_CATEGORIES = ("api", "models", "prompts", "allowlists", "hash_contract")
YAML_CONFIG_FILES = {
    "models": "models.yaml",
    "prompts": "prompts.yaml",
    "allowlists": "allowlists.yaml",
    "hash_contract": "hash_contract.yaml",
}
LLM_API_KEY_SECRET_ID = "llm_api_key"


def repo_config_dir() -> Path:
    return Path(__file__).resolve().parents[4] / "config"


def load_active_config_payload(category: str) -> dict[str, Any] | None:
    try:
        with SessionLocal() as session:
            snapshot = _active_snapshot(session, category)
            if snapshot is None:
                return None
            return dict(snapshot.parsed_json or {})
    except SQLAlchemyError:
        return None


def load_active_config_yaml(category: str) -> str | None:
    try:
        with SessionLocal() as session:
            snapshot = _active_snapshot(session, category)
            return snapshot.yaml_raw if snapshot is not None else None
    except SQLAlchemyError:
        return None


def apply_active_api_config(settings):
    payload = load_active_config_payload("api")
    api_key = load_secret_value(LLM_API_KEY_SECRET_ID)
    if not payload and not api_key:
        return settings

    llm_payload = _coerce_api_payload(payload or {})
    return replace(
        settings,
        llm_provider=llm_payload.get("provider", settings.llm_provider),
        llm_base_url=llm_payload.get("base_url", settings.llm_base_url),
        llm_enabled=llm_payload.get("enabled", settings.llm_enabled),
        llm_timeout_seconds=llm_payload.get("timeout_seconds", settings.llm_timeout_seconds),
        llm_api_key=api_key or settings.llm_api_key,
    )


def load_secret_value(secret_id: str) -> str | None:
    try:
        with SessionLocal() as session:
            secret = session.get(SystemSecret, secret_id)
            if secret is None:
                return None
            return _decrypt_secret(secret.encrypted_value)
    except (SQLAlchemyError, DomainError, InvalidToken):
        return None


class SystemConfigService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def overview(self) -> dict[str, Any]:
        categories = {}
        for category in CONFIG_CATEGORIES:
            categories[category] = self._category_payload(category)
        history = self.session.execute(
            select(SystemConfigSnapshot).order_by(
                SystemConfigSnapshot.created_at.desc(),
                SystemConfigSnapshot.category.asc(),
                SystemConfigSnapshot.version.desc(),
            )
        ).scalars().all()
        return {
            "runtime": {
                "admin_configured": bool(_admin_token()),
                "secret_configured": bool(_config_secret()),
                "supported_categories": list(CONFIG_CATEGORIES),
            },
            "categories": categories,
            "history": [_serialize_snapshot(snapshot) for snapshot in history],
        }

    def create_draft(
        self,
        *,
        category: str,
        yaml_raw: str,
        secrets: dict[str, str] | None,
        actor_ref: str,
    ) -> dict[str, Any]:
        _ensure_category(category)
        parsed, validation = validate_config(category, yaml_raw)
        if not validation["ok"]:
            raise DomainError(
                "CONFIG_VALIDATION_FAILED",
                validation["message"],
                status_code=422,
                details=validation,
            )

        version = self._next_version(category)
        snapshot = SystemConfigSnapshot(
            snapshot_id=f"config_{category}_{uuid.uuid4().hex[:12]}",
            category=category,
            version=version,
            yaml_raw=yaml_raw,
            parsed_json=parsed,
            validation_json=validation,
            status="draft",
            active_flag=0,
            created_by=actor_ref,
        )
        self.session.add(snapshot)
        secret_payload = self._save_secrets(category=category, secrets=secrets or {}, actor_ref=actor_ref)
        self.session.commit()
        return {
            "snapshot": _serialize_snapshot(snapshot),
            "secrets": secret_payload,
        }

    def activate(self, snapshot_id: str, *, actor_ref: str) -> dict[str, Any]:
        snapshot = self.session.get(SystemConfigSnapshot, snapshot_id)
        if snapshot is None:
            raise DomainError("CONFIG_SNAPSHOT_NOT_FOUND", "config snapshot was not found", status_code=404)
        validation = dict(snapshot.validation_json or {})
        if validation.get("ok") is not True:
            raise DomainError(
                "CONFIG_VALIDATION_FAILED",
                validation.get("message") or "config snapshot is not valid",
                status_code=422,
                details=validation,
            )

        previous = _active_snapshot(self.session, snapshot.category)
        if previous is not None and previous.snapshot_id != snapshot.snapshot_id:
            previous.active_flag = 0
            previous.status = "superseded"

        snapshot.active_flag = 1
        snapshot.status = "active"
        snapshot.activated_at = utcnow()
        self.session.add(
            OperationLog(
                event_type="system_config_activated",
                object_type="system_config",
                object_ref=snapshot.snapshot_id,
                payload_json={
                    "actor_ref": actor_ref,
                    "category": snapshot.category,
                    "version": snapshot.version,
                    "previous_snapshot_id": previous.snapshot_id if previous is not None else None,
                    "validation": validation,
                },
            )
        )
        self.session.commit()
        return {"snapshot": _serialize_snapshot(snapshot)}

    def export_category(self, category: str) -> dict[str, Any]:
        _ensure_category(category)
        payload = self._category_payload(category)
        return {
            "category": category,
            "source": payload["source"],
            "yaml_raw": payload["yaml_raw"],
        }

    def test_provider(self, *, payload: dict[str, Any]) -> dict[str, Any]:
        provider_payload = _coerce_api_payload(payload)
        provider = provider_payload.get("provider", "openai_compatible")
        if provider not in SUPPORTED_PROVIDERS:
            raise DomainError("CONFIG_PROVIDER_UNSUPPORTED", f"unsupported provider {provider}", status_code=422)

        base_url = str(provider_payload.get("base_url") or "").rstrip("/")
        if not base_url:
            raise DomainError("CONFIG_PROVIDER_INVALID", "provider base_url is required", status_code=422)

        api_key = payload.get("api_key") or load_secret_value(LLM_API_KEY_SECRET_ID)
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        started_at = time.perf_counter()
        try:
            response = httpx.get(f"{base_url}/models", headers=headers, timeout=provider_payload.get("timeout_seconds", 10.0))
        except httpx.RequestError as exc:
            return {
                "ok": False,
                "status_code": None,
                "latency_ms": int((time.perf_counter() - started_at) * 1000),
                "message": str(exc),
            }

        return {
            "ok": response.is_success,
            "status_code": response.status_code,
            "latency_ms": int((time.perf_counter() - started_at) * 1000),
            "message": "provider probe succeeded" if response.is_success else _provider_error_summary(response),
        }

    def _category_payload(self, category: str) -> dict[str, Any]:
        active = _active_snapshot(self.session, category)
        if active is not None:
            payload = {
                "category": category,
                "source": "database_active",
                "yaml_raw": active.yaml_raw,
                "parsed": active.parsed_json,
                "validation": active.validation_json,
                "active_snapshot": _serialize_snapshot(active),
            }
        else:
            yaml_raw, parsed, validation, source = default_config_payload(category)
            payload = {
                "category": category,
                "source": source,
                "yaml_raw": yaml_raw,
                "parsed": parsed,
                "validation": validation,
                "active_snapshot": None,
            }
        if category == "api":
            payload["secrets"] = {LLM_API_KEY_SECRET_ID: self._secret_status(LLM_API_KEY_SECRET_ID)}
        return payload

    def _next_version(self, category: str) -> int:
        current = self.session.execute(
            select(func.max(SystemConfigSnapshot.version)).where(SystemConfigSnapshot.category == category)
        ).scalar_one_or_none()
        return int(current or 0) + 1

    def _save_secrets(self, *, category: str, secrets: dict[str, str], actor_ref: str) -> dict[str, Any]:
        if category != "api" or LLM_API_KEY_SECRET_ID not in secrets:
            return {LLM_API_KEY_SECRET_ID: self._secret_status(LLM_API_KEY_SECRET_ID)} if category == "api" else {}
        raw_value = str(secrets.get(LLM_API_KEY_SECRET_ID) or "").strip()
        if not raw_value:
            return {LLM_API_KEY_SECRET_ID: self._secret_status(LLM_API_KEY_SECRET_ID)}
        secret = self.session.get(SystemSecret, LLM_API_KEY_SECRET_ID)
        encrypted = _encrypt_secret(raw_value)
        if secret is None:
            secret = SystemSecret(
                secret_id=LLM_API_KEY_SECRET_ID,
                encrypted_value=encrypted,
                value_hint=_mask_secret(raw_value),
                updated_by=actor_ref,
            )
        else:
            secret.encrypted_value = encrypted
            secret.value_hint = _mask_secret(raw_value)
            secret.updated_by = actor_ref
        self.session.add(secret)
        return {LLM_API_KEY_SECRET_ID: self._secret_status(LLM_API_KEY_SECRET_ID, secret=secret)}

    def _secret_status(self, secret_id: str, *, secret: SystemSecret | None = None) -> dict[str, Any]:
        item = secret or self.session.get(SystemSecret, secret_id)
        return {
            "configured": item is not None,
            "hint": item.value_hint if item is not None else None,
            "updated_at": item.updated_at if item is not None else None,
        }


def validate_config(category: str, yaml_raw: str) -> tuple[dict[str, Any], dict[str, Any]]:
    try:
        parsed = _parse_yaml_mapping(yaml_raw)
        if category == "api":
            normalized_api = {"llm": _validate_api_config(parsed)}
            return normalized_api, {"ok": True, "message": "api config is valid"}
        if category == "models":
            parse_model_routing_config(parsed)
            return parsed, {"ok": True, "message": "models config is valid"}
        if category == "prompts":
            parse_prompt_templates(parsed)
            return parsed, {"ok": True, "message": "prompts config is valid"}
        if category in {"allowlists", "hash_contract"}:
            return parsed, {"ok": True, "message": f"{category} config is valid"}
    except (yaml.YAMLError, ValueError, LLMConfigurationError, PromptConfigurationError) as exc:
        return {}, {"ok": False, "message": str(exc)}

    raise DomainError("CONFIG_CATEGORY_UNSUPPORTED", f"unsupported config category {category}", status_code=404)


def default_config_payload(category: str) -> tuple[str, dict[str, Any], dict[str, Any], str]:
    _ensure_category(category)
    if category == "api":
        from novel_system.settings import get_settings

        settings = get_settings(include_runtime_config=False)
        parsed = {
            "llm": {
                "provider": settings.llm_provider,
                "base_url": settings.llm_base_url,
                "enabled": settings.llm_enabled,
                "timeout_seconds": settings.llm_timeout_seconds,
            }
        }
        yaml_raw = yaml.safe_dump(parsed, allow_unicode=True, sort_keys=False)
        return yaml_raw, parsed, {"ok": True, "message": "api config is valid"}, "env_default"

    path = repo_config_dir() / YAML_CONFIG_FILES[category]
    yaml_raw = path.read_text(encoding="utf-8")
    parsed, validation = validate_config(category, yaml_raw)
    return yaml_raw, parsed, validation, "repo_default"


def require_admin_token(header_value: str | None) -> None:
    token = _admin_token()
    if not token or header_value != token:
        raise DomainError("ADMIN_TOKEN_REQUIRED", "valid X-Admin-Token is required", status_code=403)


def _active_snapshot(session: Session, category: str) -> SystemConfigSnapshot | None:
    return session.execute(
        select(SystemConfigSnapshot)
        .where(SystemConfigSnapshot.category == category, SystemConfigSnapshot.active_flag == 1)
        .order_by(SystemConfigSnapshot.version.desc(), SystemConfigSnapshot.created_at.desc())
    ).scalars().first()


def _serialize_snapshot(snapshot: SystemConfigSnapshot) -> dict[str, Any]:
    return {
        "snapshot_id": snapshot.snapshot_id,
        "category": snapshot.category,
        "version": snapshot.version,
        "yaml_raw": snapshot.yaml_raw,
        "parsed": snapshot.parsed_json,
        "validation": snapshot.validation_json,
        "status": snapshot.status,
        "active": bool(snapshot.active_flag),
        "created_by": snapshot.created_by,
        "created_at": snapshot.created_at,
        "activated_at": snapshot.activated_at,
    }


def _ensure_category(category: str) -> None:
    if category not in CONFIG_CATEGORIES:
        raise DomainError("CONFIG_CATEGORY_UNSUPPORTED", f"unsupported config category {category}", status_code=404)


def _parse_yaml_mapping(yaml_raw: str) -> dict[str, Any]:
    payload = yaml.safe_load(yaml_raw) if yaml_raw.strip() else {}
    if payload is None:
        payload = {}
    if not isinstance(payload, dict):
        raise ValueError("config YAML must decode to a mapping")
    normalized = normalize(payload)
    if not isinstance(normalized, dict):
        raise ValueError("config YAML must normalize to a mapping")
    return normalized


def _validate_api_config(parsed: dict[str, Any]) -> dict[str, Any]:
    llm = _coerce_api_payload(parsed)
    provider = str(llm.get("provider") or "openai_compatible")
    if provider not in SUPPORTED_PROVIDERS:
        raise ValueError(f"unsupported provider {provider}")

    base_url = str(llm.get("base_url") or "").strip()
    if not base_url:
        raise ValueError("llm.base_url is required")

    timeout_seconds = _float_value(llm.get("timeout_seconds", 30.0), "llm.timeout_seconds")
    if timeout_seconds <= 0:
        raise ValueError("llm.timeout_seconds must be greater than 0")

    return {
        "provider": provider,
        "base_url": base_url,
        "enabled": _bool_value(llm.get("enabled", False)),
        "timeout_seconds": timeout_seconds,
    }


def _coerce_api_payload(payload: dict[str, Any]) -> dict[str, Any]:
    llm = payload.get("llm") if isinstance(payload.get("llm"), dict) else payload
    if not isinstance(llm, dict):
        raise ValueError("api config must include an llm mapping")
    return llm


def _bool_value(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _float_value(value: Any, field: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be a valid number") from exc


def _encrypt_secret(value: str) -> str:
    return _fernet().encrypt(value.encode("utf-8")).decode("utf-8")


def _decrypt_secret(value: str) -> str:
    return _fernet().decrypt(value.encode("utf-8")).decode("utf-8")


def _fernet() -> Fernet:
    secret = _config_secret()
    if not secret:
        raise DomainError("CONFIG_SECRET_REQUIRED", "NOVEL_SYSTEM_CONFIG_SECRET is required to manage secrets", 403)
    key = base64.urlsafe_b64encode(hashlib.sha256(secret.encode("utf-8")).digest())
    return Fernet(key)


def _mask_secret(value: str) -> str:
    if len(value) <= 8:
        return "*" * len(value)
    return f"{value[:3]}...{value[-4:]}"


def _admin_token() -> str | None:
    from novel_system.settings import get_settings

    return get_settings(include_runtime_config=False).admin_token


def _config_secret() -> str | None:
    from novel_system.settings import get_settings

    return get_settings(include_runtime_config=False).config_secret


def _provider_error_summary(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return response.text[:200] if response.text else f"provider returned status {response.status_code}"
    if isinstance(payload, dict):
        error = payload.get("error")
        if isinstance(error, dict) and isinstance(error.get("message"), str):
            return error["message"]
        if isinstance(payload.get("message"), str):
            return payload["message"]
    return f"provider returned status {response.status_code}"
