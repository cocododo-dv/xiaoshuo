from __future__ import annotations

import base64
import hashlib
import time
import uuid
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

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
from novel_system.services.llm_client import (
    DEFAULT_PROVIDER_BASE_URLS,
    LLMConfigurationError,
    ProviderRuntimeConfig,
    SUPPORTED_CREDENTIAL_MODES,
    SUPPORTED_PROVIDERS,
    build_oauth_state,
    parse_model_routing_config,
    validate_oauth_state,
)
from novel_system.services.prompt_builder import PromptConfigurationError, parse_prompt_templates


CONFIG_CATEGORIES = ("api", "models", "prompts", "allowlists", "hash_contract")
YAML_CONFIG_FILES = {
    "models": "models.yaml",
    "prompts": "prompts.yaml",
    "allowlists": "allowlists.yaml",
    "hash_contract": "hash_contract.yaml",
}
LLM_API_KEY_SECRET_ID = "llm_api_key"
LLM_PROVIDER_SECRET_PREFIX = "llm_provider"
LLM_NODE_STATUSES = {
    "neutral_draft": "active",
    "style_draft": "active",
    "style_patch": "active",
    "hard_qc": "active",
    "soft_qc": "active",
    "literary_eval_live": "active",
    "style_profile_extract": "reserved",
    "chapter_summary": "reserved",
    "continuity_compression": "reserved",
    "archive": "reserved",
    "chapter_aggregate": "reserved",
}


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
    providers = _provider_payloads_from_llm(llm_payload)
    if providers:
        provider_id = str(llm_payload.get("default_provider_id") or next(iter(providers.keys())))
        provider_payload = providers.get(provider_id) or next(iter(providers.values()))
        provider_secret = load_secret_value(llm_provider_api_key_secret_id(provider_id))
        return replace(
            settings,
            llm_provider=provider_payload.get("provider_type", provider_payload.get("provider", settings.llm_provider)),
            llm_base_url=provider_payload.get("base_url", settings.llm_base_url),
            llm_enabled=llm_payload.get("enabled", provider_payload.get("enabled", settings.llm_enabled)),
            llm_timeout_seconds=llm_payload.get("timeout_seconds", settings.llm_timeout_seconds),
            llm_api_key=provider_secret or api_key or settings.llm_api_key,
        )
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


def llm_provider_api_key_secret_id(provider_id: str) -> str:
    return f"{LLM_PROVIDER_SECRET_PREFIX}:{provider_id}:api_key"


def llm_provider_oauth_secret_id(provider_id: str) -> str:
    return f"{LLM_PROVIDER_SECRET_PREFIX}:{provider_id}:oauth2"


def llm_provider_oauth_pending_secret_id(provider_id: str) -> str:
    return f"{LLM_PROVIDER_SECRET_PREFIX}:{provider_id}:oauth_pending"


def load_llm_provider_runtime_configs() -> dict[str, ProviderRuntimeConfig]:
    payload = load_active_config_payload("api") or {}
    llm_payload = _coerce_api_payload(payload) if payload else {}
    providers = _provider_payloads_from_llm(llm_payload)
    if not providers:
        from novel_system.settings import get_settings

        settings = get_settings(include_runtime_config=False)
        provider_id = settings.llm_provider
        providers = {
            provider_id: {
                "provider_id": provider_id,
                "provider_type": settings.llm_provider,
                "base_url": settings.llm_base_url,
                "credential_mode": "api_key" if settings.llm_api_key else "none",
                "enabled": settings.llm_enabled,
                "timeout_seconds": settings.llm_timeout_seconds,
            }
        }

    runtime_configs: dict[str, ProviderRuntimeConfig] = {}
    for provider_id, provider_payload in providers.items():
        credential_mode = str(provider_payload.get("credential_mode") or "api_key")
        secret_id = (
            llm_provider_oauth_secret_id(provider_id)
            if credential_mode == "oauth2"
            else llm_provider_api_key_secret_id(provider_id)
        )
        secret_value = load_secret_value(secret_id)
        legacy_api_key = load_secret_value(LLM_API_KEY_SECRET_ID) if provider_id in {"openai_compatible", "openai"} else None
        oauth_payload: dict[str, Any] = {}
        if credential_mode == "oauth2" and secret_value:
            try:
                loaded = yaml.safe_load(secret_value)
                oauth_payload = loaded if isinstance(loaded, dict) else {"access_token": secret_value}
            except yaml.YAMLError:
                oauth_payload = {"access_token": secret_value}
        runtime_configs[provider_id] = ProviderRuntimeConfig(
            provider_id=provider_id,
            provider_type=str(provider_payload.get("provider_type") or provider_payload.get("provider") or provider_id),
            account_id=_optional_text(provider_payload.get("account_id")),
            base_url=_normalize_provider_base_url(
                provider_payload.get("base_url") or DEFAULT_PROVIDER_BASE_URLS.get(str(provider_payload.get("provider_type")), "")
            ),
            api_key=(secret_value or legacy_api_key) if credential_mode == "api_key" else None,
            credential_mode=credential_mode if credential_mode in SUPPORTED_CREDENTIAL_MODES else "api_key",
            api_mode=str(provider_payload.get("api_mode") or "chat"),  # type: ignore[arg-type]
            enabled=_bool_value(provider_payload.get("enabled", True)),
            models=tuple(str(item) for item in provider_payload.get("models", []) if isinstance(item, str)),
            access_token=_optional_text(oauth_payload.get("access_token")),
            refresh_token=_optional_text(oauth_payload.get("refresh_token")),
            token_expires_at=_optional_text(provider_payload.get("expires_at") or oauth_payload.get("expires_at")),
            scopes=tuple(str(item) for item in provider_payload.get("scopes", oauth_payload.get("scopes", [])) if isinstance(item, str)),
            provider_options=dict(provider_payload.get("provider_options") or {}),
        )
    return runtime_configs


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
        provider = str(provider_payload.get("provider_type") or provider_payload.get("provider") or "openai_compatible")
        if provider not in SUPPORTED_PROVIDERS:
            raise DomainError("CONFIG_PROVIDER_UNSUPPORTED", f"unsupported provider {provider}", status_code=422)

        base_url = _normalize_provider_base_url(provider_payload.get("base_url"))
        if not base_url:
            raise DomainError("CONFIG_PROVIDER_INVALID", "provider base_url is required", status_code=422)

        provider_id = _optional_text(provider_payload.get("provider_id"))
        default_credential_mode = "none" if provider_id and not provider_payload.get("api_key") else "api_key"
        credential_mode = str(provider_payload.get("credential_mode") or default_credential_mode)
        api_key = None
        if credential_mode == "api_key":
            provider_secret = load_secret_value(llm_provider_api_key_secret_id(provider_id)) if provider_id else None
            api_key = provider_payload.get("api_key") or provider_secret or load_secret_value(LLM_API_KEY_SECRET_ID)
        elif credential_mode == "oauth2" and provider_id:
            oauth_secret = load_secret_value(llm_provider_oauth_secret_id(provider_id))
            if oauth_secret:
                try:
                    oauth_payload = yaml.safe_load(oauth_secret)
                    if isinstance(oauth_payload, dict):
                        api_key = oauth_payload.get("access_token")
                    else:
                        api_key = oauth_secret
                except yaml.YAMLError:
                    api_key = oauth_secret
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        timeout_value = provider_payload.get("timeout_seconds")
        timeout_seconds = _float_value(10.0 if timeout_value is None else timeout_value, "timeout_seconds")
        started_at = time.perf_counter()
        try:
            response = httpx.get(f"{base_url}/models", headers=headers, timeout=timeout_seconds)
        except httpx.RequestError as exc:
            return {
                "ok": False,
                "status_code": None,
                "latency_ms": int((time.perf_counter() - started_at) * 1000),
                "message": str(exc),
                "checks": {
                    "connection": {
                        "ok": False,
                        "status_code": None,
                        "message": str(exc),
                    }
                },
            }

        latency_ms = int((time.perf_counter() - started_at) * 1000)
        checks: dict[str, Any] = {
            "connection": {
                "ok": response.is_success,
                "status_code": response.status_code,
                "latency_ms": latency_ms,
                "message": "model list endpoint reached" if response.is_success else _provider_error_summary(response),
            }
        }
        if not response.is_success:
            return {
                "ok": False,
                "status_code": response.status_code,
                "latency_ms": latency_ms,
                "message": _provider_error_summary(response),
                "checks": checks,
            }

        model_ids = _extract_model_ids(response)
        requested_model = _requested_probe_model(provider_payload)
        if requested_model:
            model_ok = requested_model in model_ids
            checks["model"] = {
                "ok": model_ok,
                "requested_model": requested_model,
                "available_models": model_ids,
            }
            if not model_ok:
                available_hint = "、".join(model_ids[:5]) if model_ids else "未能从 /models 解析到模型列表"
                return {
                    "ok": False,
                    "status_code": response.status_code,
                    "latency_ms": latency_ms,
                    "message": f"模型 {requested_model} 未在服务返回的模型列表中出现。可用模型：{available_hint}",
                    "checks": checks,
                }

        should_check_completion = bool(requested_model) and _bool_value(provider_payload.get("check_completion", False))
        if should_check_completion:
            completion_result = _probe_chat_completion(
                provider=provider,
                base_url=base_url,
                headers=headers,
                model=str(requested_model),
                timeout_seconds=timeout_seconds,
            )
            checks["completion"] = completion_result
            if completion_result["ok"] is not True:
                return {
                    "ok": False,
                    "status_code": completion_result.get("status_code") or response.status_code,
                    "latency_ms": int((time.perf_counter() - started_at) * 1000),
                    "message": completion_result["message"],
                    "checks": checks,
                }

        message = (
            f"模型 {requested_model} 可用：连接、模型名、生成均通过"
            if requested_model and checks.get("completion", {}).get("ok") is True
            else (f"模型 {requested_model} 已在服务列表中找到" if requested_model else "provider probe succeeded")
        )
        return {
            "ok": True,
            "status_code": response.status_code,
            "latency_ms": int((time.perf_counter() - started_at) * 1000),
            "message": message,
            "checks": checks,
        }

    def llm_overview(self) -> dict[str, Any]:
        api_payload = self._category_payload("api")
        models_payload = self._category_payload("models")
        llm_payload = _coerce_api_payload(dict(api_payload.get("parsed") or {}))
        providers = {
            provider_id: self._serialize_provider(provider_id, provider_payload)
            for provider_id, provider_payload in _provider_payloads_from_llm(llm_payload).items()
        }
        try:
            routing = parse_model_routing_config(models_payload.get("parsed") or {})
            node_routes = {
                node_id: _serialize_task_config(node_id, task_config)
                for node_id, task_config in routing.node_routing.items()
            }
        except LLMConfigurationError:
            node_routes = {}
        for node_id, status in LLM_NODE_STATUSES.items():
            node_routes.setdefault(
                node_id,
                {
                    "node_id": node_id,
                    "status": status,
                    "configured": False,
                },
            )
            node_routes[node_id]["status"] = status
        _annotate_node_route_readiness(node_routes=node_routes, providers=providers)
        return {
            "provider_catalog": _provider_catalog(),
            "providers": providers,
            "node_routes": node_routes,
            "readiness": _llm_readiness_summary(providers=providers, node_routes=node_routes),
            "api_snapshot": api_payload.get("active_snapshot"),
            "models_snapshot": models_payload.get("active_snapshot"),
        }

    def save_llm_provider(self, *, payload: dict[str, Any], actor_ref: str) -> dict[str, Any]:
        provider = _normalize_provider_payload(payload)
        provider_id = provider["provider_id"]
        api_key = _optional_text(payload.get("api_key"))
        llm_payload = self._current_api_llm_payload()
        providers = _provider_payloads_from_llm(llm_payload)
        providers[provider_id] = {key: value for key, value in provider.items() if key != "api_key"}
        llm_payload["providers"] = providers
        llm_payload["default_provider_id"] = llm_payload.get("default_provider_id") or provider_id
        llm_payload["enabled"] = True if provider["enabled"] else _bool_value(llm_payload.get("enabled", True))
        llm_payload.setdefault("timeout_seconds", 30.0)
        snapshot = self._store_config_snapshot(
            category="api",
            parsed={"llm": llm_payload},
            validation={"ok": True, "message": "api config is valid"},
            status="active",
            active=True,
            actor_ref=actor_ref,
        )
        secret_status = self._secret_status(llm_provider_api_key_secret_id(provider_id))
        if provider["credential_mode"] == "none":
            existing_secret = self.session.get(SystemSecret, llm_provider_api_key_secret_id(provider_id))
            if existing_secret is not None:
                self.session.delete(existing_secret)
            secret_status = _none_secret_status()
        elif api_key:
            secret_status = self._save_secret_value(
                secret_id=llm_provider_api_key_secret_id(provider_id),
                raw_value=api_key,
                actor_ref=actor_ref,
                secret_type="api_key",
                metadata={
                    "provider_id": provider_id,
                    "provider_type": provider["provider_type"],
                    "account_id": provider.get("account_id"),
                },
            )
        provider_view = self._serialize_provider(provider_id, provider)
        provider_view["secret"] = secret_status
        self.session.commit()
        return {
            "provider": provider_view,
            "snapshot": _serialize_snapshot(snapshot),
        }

    def save_llm_node_routes(self, *, payload: dict[str, Any], actor_ref: str) -> dict[str, Any]:
        config_payload = {
            "node_routing": dict(payload.get("node_routing") or {}),
            "retry_budget": dict(payload.get("retry_budget") or {}),
            "job_runtime": dict(payload.get("job_runtime") or {}),
        }
        routing_config = parse_model_routing_config(config_payload)
        if _bool_value(payload.get("activate", False)):
            _validate_activating_node_route_bindings(
                node_routing=routing_config.node_routing,
                providers=self.llm_overview()["providers"],
            )
        snapshot = self._store_config_snapshot(
            category="models",
            parsed=config_payload,
            validation={"ok": True, "message": "models config is valid"},
            status="active" if _bool_value(payload.get("activate", False)) else "draft",
            active=_bool_value(payload.get("activate", False)),
            actor_ref=actor_ref,
        )
        self.session.commit()
        return {"snapshot": _serialize_snapshot(snapshot)}

    def probe_llm_provider(self, *, provider_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        provider = self.llm_overview()["providers"].get(provider_id)
        if provider is None:
            raise DomainError("CONFIG_PROVIDER_NOT_FOUND", f"provider {provider_id} was not found", status_code=404)
        probe_payload = dict(provider)
        probe_payload.update(payload or {})
        return self.test_provider(payload=probe_payload)

    def start_llm_oauth(self, *, provider_type: str, payload: dict[str, Any]) -> dict[str, Any]:
        if provider_type != "gemini":
            raise DomainError(
                "CONFIG_OAUTH_UNSUPPORTED",
                f"oauth2 is not supported for {provider_type} in this release",
                status_code=422,
            )
        secret = _config_secret()
        if not secret:
            raise DomainError("CONFIG_SECRET_REQUIRED", "NOVEL_SYSTEM_CONFIG_SECRET is required to manage oauth", 403)
        provider_id = _required_text(payload.get("provider_id"), "provider_id")
        account_id = _required_text(payload.get("account_id"), "account_id")
        client_id = _required_text(payload.get("client_id"), "client_id")
        redirect_uri = _required_text(payload.get("redirect_uri"), "redirect_uri")
        client_secret = _optional_text(payload.get("client_secret"))
        scopes = payload.get("scopes") if isinstance(payload.get("scopes"), list) else []
        if not scopes:
            scopes = ["https://www.googleapis.com/auth/cloud-platform"]
        state = build_oauth_state(
            provider_type=provider_type,
            provider_id=provider_id,
            account_id=account_id,
            redirect_path="/api/v1/system-config/llm/oauth/callback",
            secret=secret,
        )
        params = urlencode(
            {
                "client_id": client_id,
                "redirect_uri": redirect_uri,
                "response_type": "code",
                "scope": " ".join(str(item) for item in scopes),
                "access_type": "offline",
                "prompt": "consent",
                "state": state,
            }
        )
        self._save_secret_value(
            secret_id=llm_provider_oauth_pending_secret_id(provider_id),
            raw_value=client_secret or "",
            actor_ref="oauth_start",
            secret_type="oauth_pending",
            metadata={
                "provider_type": provider_type,
                "provider_id": provider_id,
                "account_id": account_id,
                "client_id": client_id,
                "redirect_uri": redirect_uri,
                "scopes": [str(item) for item in scopes],
                "state": state,
            },
        )
        self.session.commit()
        return {
            "provider_type": provider_type,
            "provider_id": provider_id,
            "account_id": account_id,
            "authorization_url": f"https://accounts.google.com/o/oauth2/v2/auth?{params}",
            "state": state,
            "scopes": scopes,
        }

    def finish_llm_oauth(self, *, state: str, code: str | None, error: str | None, actor_ref: str) -> dict[str, Any]:
        if error:
            raise DomainError("CONFIG_OAUTH_DENIED", f"oauth provider returned error: {error}", status_code=400)
        if not code:
            raise DomainError("CONFIG_OAUTH_CODE_REQUIRED", "oauth callback requires code", status_code=400)
        secret = _config_secret()
        if not secret:
            raise DomainError("CONFIG_SECRET_REQUIRED", "NOVEL_SYSTEM_CONFIG_SECRET is required to manage oauth", 403)
        try:
            state_payload = validate_oauth_state(state, secret=secret)
        except LLMConfigurationError as exc:
            raise DomainError("CONFIG_OAUTH_STATE_INVALID", "invalid oauth state", status_code=400) from exc
        if state_payload.get("provider_type") != "gemini":
            raise DomainError("CONFIG_OAUTH_UNSUPPORTED", "oauth callback only supports gemini", status_code=422)

        provider_id = _required_text(state_payload.get("provider_id"), "provider_id")
        account_id = _required_text(state_payload.get("account_id"), "account_id")
        pending_secret = self.session.get(SystemSecret, llm_provider_oauth_pending_secret_id(provider_id))
        pending_metadata = pending_secret.metadata_json if pending_secret is not None else {}
        client_id = _required_text(pending_metadata.get("client_id"), "client_id")
        redirect_uri = _required_text(pending_metadata.get("redirect_uri"), "redirect_uri")
        client_secret = _decrypt_secret(pending_secret.encrypted_value) if pending_secret is not None else ""
        token_payload: dict[str, Any] = {
            "code": code,
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        }
        if client_secret:
            token_payload["client_secret"] = client_secret

        try:
            response = httpx.post("https://oauth2.googleapis.com/token", data=token_payload, timeout=20.0)
        except httpx.RequestError as exc:
            raise DomainError("CONFIG_OAUTH_TOKEN_EXCHANGE_FAILED", str(exc), status_code=502) from exc
        if not response.is_success:
            raise DomainError(
                "CONFIG_OAUTH_TOKEN_EXCHANGE_FAILED",
                _provider_error_summary(response),
                status_code=502,
            )
        try:
            token_response = response.json()
        except ValueError as exc:
            raise DomainError("CONFIG_OAUTH_TOKEN_EXCHANGE_FAILED", "oauth token response was not JSON", status_code=502) from exc
        access_token = _required_text(token_response.get("access_token"), "access_token")
        expires_at = _oauth_expires_at(token_response.get("expires_in"))
        scopes = pending_metadata.get("scopes") if isinstance(pending_metadata.get("scopes"), list) else []
        token_secret = yaml.safe_dump(
            {
                "access_token": access_token,
                "refresh_token": _optional_text(token_response.get("refresh_token")),
                "expires_at": expires_at,
                "scopes": [str(item) for item in scopes],
                "token_type": _optional_text(token_response.get("token_type")),
                "account_id": account_id,
            },
            allow_unicode=True,
            sort_keys=False,
        )
        secret_status = self._save_secret_value(
            secret_id=llm_provider_oauth_secret_id(provider_id),
            raw_value=token_secret,
            actor_ref=actor_ref,
            secret_type="oauth2",
            metadata={
                "provider_id": provider_id,
                "provider_type": "gemini",
                "account_id": account_id,
                "scopes": [str(item) for item in scopes],
                "token_type": _optional_text(token_response.get("token_type")),
            },
            expires_at=expires_at,
        )
        if pending_secret is not None:
            self.session.delete(pending_secret)

        llm_payload = self._current_api_llm_payload()
        providers = _provider_payloads_from_llm(llm_payload)
        provider_payload = dict(providers.get(provider_id) or {})
        provider_payload.update(
            {
                "provider_id": provider_id,
                "provider_type": "gemini",
                "account_id": account_id,
                "base_url": provider_payload.get("base_url") or DEFAULT_PROVIDER_BASE_URLS["gemini"],
                "enabled": True,
                "credential_mode": "oauth2",
                "api_mode": provider_payload.get("api_mode") or "chat",
                "scopes": [str(item) for item in scopes],
                "models": provider_payload.get("models") or [],
                "provider_options": dict(provider_payload.get("provider_options") or {}),
            }
        )
        providers[provider_id] = _normalize_provider_payload(provider_payload)
        llm_payload["providers"] = providers
        llm_payload["default_provider_id"] = llm_payload.get("default_provider_id") or provider_id
        snapshot = self._store_config_snapshot(
            category="api",
            parsed={"llm": llm_payload},
            validation={"ok": True, "message": "api config is valid"},
            status="active",
            active=True,
            actor_ref=actor_ref,
        )
        provider_view = self._serialize_provider(provider_id, providers[provider_id])
        provider_view["secret"] = secret_status
        self.session.commit()
        return {
            "provider": provider_view,
            "snapshot": _serialize_snapshot(snapshot),
            "state": {"provider_type": "gemini", "provider_id": provider_id, "account_id": account_id},
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

    def _current_api_llm_payload(self) -> dict[str, Any]:
        active = _active_snapshot(self.session, "api")
        if active is not None:
            return _coerce_api_payload(dict(active.parsed_json or {}))
        _, parsed, _, _ = default_config_payload("api")
        return _coerce_api_payload(parsed)

    def _store_config_snapshot(
        self,
        *,
        category: str,
        parsed: dict[str, Any],
        validation: dict[str, Any],
        status: str,
        active: bool,
        actor_ref: str,
    ) -> SystemConfigSnapshot:
        if active:
            previous = _active_snapshot(self.session, category)
            if previous is not None:
                previous.active_flag = 0
                previous.status = "superseded"
        yaml_raw = yaml.safe_dump(parsed, allow_unicode=True, sort_keys=False)
        snapshot = SystemConfigSnapshot(
            snapshot_id=f"config_{category}_{uuid.uuid4().hex[:12]}",
            category=category,
            version=self._next_version(category),
            yaml_raw=yaml_raw,
            parsed_json=parsed,
            validation_json=validation,
            status=status,
            active_flag=1 if active else 0,
            activated_at=utcnow() if active else None,
            created_by=actor_ref,
        )
        self.session.add(snapshot)
        return snapshot

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
        status = self._save_secret_value(
            secret_id=LLM_API_KEY_SECRET_ID,
            raw_value=raw_value,
            actor_ref=actor_ref,
            secret_type="api_key",
            metadata={"provider_id": "legacy", "provider_type": "openai_compatible"},
        )
        return {LLM_API_KEY_SECRET_ID: status}

    def _save_secret_value(
        self,
        *,
        secret_id: str,
        raw_value: str,
        actor_ref: str,
        secret_type: str,
        metadata: dict[str, Any],
        expires_at: str | None = None,
    ) -> dict[str, Any]:
        secret = self.session.get(SystemSecret, secret_id)
        encrypted = _encrypt_secret(raw_value)
        if secret is None:
            secret = SystemSecret(
                secret_id=secret_id,
                encrypted_value=encrypted,
                value_hint=_mask_secret(raw_value),
                secret_type=secret_type,
                metadata_json=metadata,
                expires_at=expires_at,
                updated_by=actor_ref,
            )
        else:
            secret.encrypted_value = encrypted
            secret.value_hint = _mask_secret(raw_value)
            secret.secret_type = secret_type
            secret.metadata_json = metadata
            secret.expires_at = expires_at
            secret.updated_by = actor_ref
        self.session.add(secret)
        return self._secret_status(secret_id, secret=secret)

    def _secret_status(self, secret_id: str, *, secret: SystemSecret | None = None) -> dict[str, Any]:
        item = secret or self.session.get(SystemSecret, secret_id)
        return {
            "configured": item is not None,
            "hint": item.value_hint if item is not None else None,
            "secret_type": item.secret_type if item is not None else None,
            "metadata": item.metadata_json if item is not None else {},
            "expires_at": item.expires_at if item is not None else None,
            "updated_at": item.updated_at if item is not None else None,
        }

    def _serialize_provider(self, provider_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        credential_mode = str(payload.get("credential_mode") or "api_key")
        secret_id = llm_provider_oauth_secret_id(provider_id) if credential_mode == "oauth2" else llm_provider_api_key_secret_id(provider_id)
        secret_status = _none_secret_status() if credential_mode == "none" else self._secret_status(secret_id)
        return {
            "provider_id": provider_id,
            "provider_type": payload.get("provider_type") or payload.get("provider"),
            "account_id": payload.get("account_id"),
            "base_url": payload.get("base_url"),
            "enabled": _bool_value(payload.get("enabled", True)),
            "credential_mode": credential_mode,
            "api_mode": payload.get("api_mode", "chat"),
            "models": list(payload.get("models") or []),
            "scopes": list(payload.get("scopes") or []),
            "provider_options": dict(payload.get("provider_options") or {}),
            "secret": secret_status,
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


def require_admin_token(header_value: str | None, *, client_host: str | None = None) -> None:
    token = _admin_token()
    if token:
        if header_value == token:
            return
        raise DomainError("ADMIN_TOKEN_REQUIRED", "valid X-Admin-Token is required", status_code=403)
    if _is_loopback_client(client_host):
        return
    raise DomainError(
        "ADMIN_TOKEN_REQUIRED",
        "valid X-Admin-Token is required; local setup mode only accepts loopback requests",
        status_code=403,
    )


def _is_loopback_client(client_host: str | None) -> bool:
    return str(client_host or "").strip().lower() in {"127.0.0.1", "::1", "localhost"}


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
    providers = _provider_payloads_from_llm(llm)
    if providers:
        normalized_providers = {
            provider_id: _normalize_provider_payload({"provider_id": provider_id, **provider_payload})
            for provider_id, provider_payload in providers.items()
        }
        timeout_seconds = _float_value(llm.get("timeout_seconds", 30.0), "llm.timeout_seconds")
        if timeout_seconds <= 0:
            raise ValueError("llm.timeout_seconds must be greater than 0")
        return {
            "enabled": _bool_value(llm.get("enabled", True)),
            "timeout_seconds": timeout_seconds,
            "default_provider_id": llm.get("default_provider_id") or next(iter(normalized_providers.keys())),
            "providers": normalized_providers,
        }

    provider = str(llm.get("provider") or "openai_compatible")
    if provider not in SUPPORTED_PROVIDERS:
        raise ValueError(f"unsupported provider {provider}")

    base_url = _normalize_provider_base_url(llm.get("base_url"))
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


def _provider_payloads_from_llm(llm: dict[str, Any]) -> dict[str, dict[str, Any]]:
    providers = llm.get("providers")
    if isinstance(providers, dict):
        return {
            str(provider_id): dict(provider_payload)
            for provider_id, provider_payload in providers.items()
            if isinstance(provider_payload, dict)
        }
    return {}


def _normalize_provider_base_url(value: Any) -> str:
    base_url = str(value or "").strip().rstrip("/")
    for suffix in ("/chat/completions", "/completions", "/responses", "/models"):
        if base_url.endswith(suffix):
            base_url = base_url[: -len(suffix)].rstrip("/")
            break
    return base_url


def _normalize_provider_payload(payload: dict[str, Any]) -> dict[str, Any]:
    provider_id = _required_text(payload.get("provider_id"), "provider_id")
    provider_type = str(payload.get("provider_type") or payload.get("provider") or "").strip()
    if provider_type not in SUPPORTED_PROVIDERS:
        raise ValueError(f"unsupported provider {provider_type}")
    credential_mode = str(payload.get("credential_mode") or "api_key")
    if credential_mode not in SUPPORTED_CREDENTIAL_MODES:
        raise ValueError(f"unsupported credential_mode {credential_mode}")
    base_url = _normalize_provider_base_url(payload.get("base_url") or DEFAULT_PROVIDER_BASE_URLS.get(provider_type))
    if not base_url:
        raise ValueError("provider base_url is required")
    models = payload.get("models") if isinstance(payload.get("models"), list) else []
    scopes = payload.get("scopes") if isinstance(payload.get("scopes"), list) else []
    provider_options = payload.get("provider_options") if isinstance(payload.get("provider_options"), dict) else {}
    return {
        "provider_id": provider_id,
        "provider_type": provider_type,
        "account_id": _optional_text(payload.get("account_id")),
        "base_url": base_url,
        "enabled": _bool_value(payload.get("enabled", True)),
        "credential_mode": credential_mode,
        "api_mode": str(payload.get("api_mode") or ("responses" if provider_type in {"openai", "openai_compatible"} else "chat")),
        "models": [str(model) for model in models if isinstance(model, str) and model.strip()],
        "scopes": [str(scope) for scope in scopes if isinstance(scope, str) and scope.strip()],
        "provider_options": dict(provider_options),
    }


def _provider_catalog() -> dict[str, dict[str, Any]]:
    return {
        "openai_compatible": {
            "label": "本地 / OpenAI 兼容",
            "credential_modes": ["none", "api_key"],
            "default_base_url": DEFAULT_PROVIDER_BASE_URLS["openai_compatible"],
        },
        "openai": {
            "label": "OpenAI",
            "credential_modes": ["api_key"],
            "default_base_url": DEFAULT_PROVIDER_BASE_URLS["openai"],
        },
        "anthropic": {
            "label": "Claude / Anthropic",
            "credential_modes": ["api_key"],
            "default_base_url": DEFAULT_PROVIDER_BASE_URLS["anthropic"],
        },
        "deepseek": {
            "label": "DeepSeek",
            "credential_modes": ["api_key"],
            "default_base_url": DEFAULT_PROVIDER_BASE_URLS["deepseek"],
        },
        "zhipu_glm": {
            "label": "智谱 GLM",
            "credential_modes": ["api_key"],
            "default_base_url": DEFAULT_PROVIDER_BASE_URLS["zhipu_glm"],
        },
        "gemini": {
            "label": "Gemini / Google",
            "credential_modes": ["api_key", "oauth2"],
            "default_base_url": DEFAULT_PROVIDER_BASE_URLS["gemini"],
        },
    }


def _none_secret_status() -> dict[str, Any]:
    return {
        "configured": False,
        "hint": None,
        "secret_type": "none",
        "metadata": {},
        "expires_at": None,
        "updated_at": None,
    }


def _serialize_task_config(node_id: str, task_config) -> dict[str, Any]:
    return {
        "node_id": node_id,
        "status": LLM_NODE_STATUSES.get(node_id, "active"),
        "configured": True,
        "provider": task_config.provider,
        "provider_id": task_config.provider_id,
        "account_id": task_config.account_id,
        "model": task_config.model,
        "temperature": task_config.temperature,
        "max_output_tokens": task_config.max_output_tokens,
        "response_format": task_config.response_format,
        "reasoning_level": task_config.reasoning_level,
        "api_mode": task_config.api_mode,
        "credential_mode": task_config.credential_mode,
        "provider_options": task_config.provider_options,
    }


def _provider_view_ready(provider: dict[str, Any]) -> bool:
    if provider.get("enabled") is False:
        return False
    credential_mode = str(provider.get("credential_mode") or "api_key")
    if credential_mode == "none":
        return True
    secret = provider.get("secret") if isinstance(provider.get("secret"), dict) else {}
    return secret.get("configured") is True


def _route_readiness(route: dict[str, Any], providers: dict[str, dict[str, Any]]) -> dict[str, Any]:
    status = str(route.get("status") or "active")
    provider_id = _optional_text(route.get("provider_id"))
    model = _optional_text(route.get("model"))
    configured = bool(route.get("configured") or provider_id or model)
    if status == "reserved":
        return {
            "ready": False,
            "provider_ready": False,
            "provider_missing": False,
            "model_missing": False,
            "readiness_reason": "reserved",
        }
    if not configured:
        return {
            "ready": False,
            "provider_ready": False,
            "provider_missing": False,
            "model_missing": False,
            "readiness_reason": "not_configured",
        }

    if not provider_id:
        return {
            "ready": False,
            "provider_ready": False,
            "provider_missing": True,
            "model_missing": False,
            "readiness_reason": "provider_id_missing",
        }
    provider = providers.get(provider_id)
    if provider is None:
        return {
            "ready": False,
            "provider_ready": False,
            "provider_missing": True,
            "model_missing": False,
            "readiness_reason": f"provider_not_found:{provider_id}",
        }

    provider_ready = _provider_view_ready(provider)
    if not model:
        return {
            "ready": False,
            "provider_ready": provider_ready,
            "provider_missing": False,
            "model_missing": True,
            "readiness_reason": "model_missing",
        }
    models = [str(model) for model in provider.get("models") or []]
    model_missing = bool(models and model not in models)
    ready = provider_ready and not model_missing
    reason = "ready"
    if not provider_ready:
        reason = "provider_not_ready"
    elif model_missing:
        reason = f"model_not_listed:{model}"
    return {
        "ready": ready,
        "provider_ready": provider_ready,
        "provider_missing": False,
        "model_missing": model_missing,
        "readiness_reason": reason,
    }


def _annotate_node_route_readiness(
    *,
    node_routes: dict[str, dict[str, Any]],
    providers: dict[str, dict[str, Any]],
) -> None:
    for route in node_routes.values():
        route.update(_route_readiness(route, providers))


def _llm_readiness_summary(
    *,
    providers: dict[str, dict[str, Any]],
    node_routes: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    provider_count = len(providers)
    active_provider_count = sum(1 for provider in providers.values() if _provider_view_ready(provider))
    active_routes = [
        route
        for route in node_routes.values()
        if route.get("status") != "reserved"
        and (route.get("configured") or route.get("provider_id") or route.get("model"))
    ]
    ready_routes = [route for route in active_routes if route.get("ready") is True]
    blocked_routes = [route for route in active_routes if route.get("ready") is not True]
    return {
        "provider_count": provider_count,
        "active_provider_count": active_provider_count,
        "configured_route_count": len(active_routes),
        "active_route_count": len(active_routes),
        "ready_route_count": len(ready_routes),
        "blocked_route_count": len(blocked_routes),
        "blocked_routes": [
            {
                "node_id": route.get("node_id"),
                "provider_id": route.get("provider_id"),
                "model": route.get("model"),
                "reason": route.get("readiness_reason"),
            }
            for route in blocked_routes
        ],
        "ready": active_provider_count > 0 and len(ready_routes) > 0 and not blocked_routes,
    }


def _validate_activating_node_route_bindings(
    *,
    node_routing: dict[str, Any],
    providers: dict[str, dict[str, Any]],
) -> None:
    missing_bindings: list[str] = []
    missing_models: list[str] = []
    not_ready_providers: list[str] = []
    for node_id, task_config in node_routing.items():
        if LLM_NODE_STATUSES.get(node_id) == "reserved":
            continue
        provider_id = task_config.provider_id
        if not provider_id or provider_id not in providers:
            missing_bindings.append(f"{node_id}:{provider_id or 'missing_provider_id'}")
            continue
        if not _provider_view_ready(providers[provider_id]):
            not_ready_providers.append(f"{node_id}:{provider_id}")
        models = [str(model) for model in providers[provider_id].get("models") or []]
        if not _optional_text(task_config.model):
            missing_models.append(f"{node_id}:{provider_id}:missing_model")
        elif models and task_config.model not in models:
            missing_models.append(f"{node_id}:{provider_id}:{task_config.model}")

    if missing_bindings:
        raise DomainError(
            "CONFIG_ROUTE_PROVIDER_MISSING",
            "active LLM node routes must reference an existing provider_id: " + ", ".join(missing_bindings),
            status_code=422,
        )
    if not_ready_providers:
        raise DomainError(
            "CONFIG_ROUTE_PROVIDER_NOT_READY",
            "active LLM node routes must reference an enabled provider with configured credentials: "
            + ", ".join(not_ready_providers),
            status_code=422,
        )
    if missing_models:
        raise DomainError(
            "CONFIG_ROUTE_MODEL_MISSING",
            "active LLM node routes must use a model listed by their provider config: " + ", ".join(missing_models),
            status_code=422,
        )


def _required_text(value: Any, field: str) -> str:
    if isinstance(value, str) and value.strip():
        return value.strip()
    raise ValueError(f"{field} is required")


def _optional_text(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _oauth_expires_at(expires_in: Any) -> str | None:
    try:
        seconds = int(expires_in)
    except (TypeError, ValueError):
        return None
    return (datetime.now(UTC) + timedelta(seconds=max(seconds, 0))).isoformat()


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


def _requested_probe_model(payload: dict[str, Any]) -> str | None:
    explicit_model = _optional_text(payload.get("model"))
    if explicit_model:
        return explicit_model
    models = payload.get("models")
    if isinstance(models, list):
        for model in models:
            candidate = _optional_text(model)
            if candidate:
                return candidate
    return None


def _extract_model_ids(response: httpx.Response) -> list[str]:
    try:
        payload = response.json()
    except ValueError:
        return []
    candidates: list[Any] = []
    if isinstance(payload, dict):
        for key in ("data", "models"):
            value = payload.get(key)
            if isinstance(value, list):
                candidates.extend(value)
        if not candidates:
            candidates.append(payload)
    elif isinstance(payload, list):
        candidates.extend(payload)

    model_ids: list[str] = []
    for item in candidates:
        if isinstance(item, str):
            model_ids.append(item)
        elif isinstance(item, dict):
            for key in ("id", "name", "model"):
                value = _optional_text(item.get(key))
                if value:
                    model_ids.append(value)
                    break
    return list(dict.fromkeys(model_ids))


def _probe_chat_completion(
    *,
    provider: str,
    base_url: str,
    headers: dict[str, str],
    model: str,
    timeout_seconds: float,
) -> dict[str, Any]:
    if provider not in {"openai", "openai_compatible", "deepseek", "zhipu_glm"}:
        return {
            "ok": None,
            "status_code": None,
            "message": f"completion check skipped for provider {provider}",
        }
    try:
        response = httpx.post(
            f"{base_url}/chat/completions",
            headers=headers,
            json={
                "model": model,
                "messages": [{"role": "user", "content": "ping"}],
                "temperature": 0,
                "max_tokens": 8,
                "stream": False,
            },
            timeout=timeout_seconds,
        )
    except httpx.RequestError as exc:
        return {
            "ok": False,
            "status_code": None,
            "message": str(exc),
        }
    return {
        "ok": response.is_success,
        "status_code": response.status_code,
        "message": "minimal completion succeeded" if response.is_success else _provider_error_summary(response),
    }


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
