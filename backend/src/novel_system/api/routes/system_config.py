from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Header, Request
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from novel_system.api.deps import get_session
from novel_system.api.response import ok
from novel_system.services.system_config import SystemConfigService, require_admin_token

router = APIRouter(tags=["system_config"])


class SystemConfigDraftRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category: str
    yaml_raw: str
    secrets: dict[str, str] | None = None


class ProviderProbeRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    provider: str | None = None
    base_url: str | None = None
    api_key: str | None = None
    timeout_seconds: float | None = None


class LlmProviderConfigRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    provider_id: str
    provider_type: str
    account_id: str | None = None
    base_url: str | None = None
    enabled: bool = True
    credential_mode: str = "api_key"
    api_mode: str | None = None
    models: list[str] | None = None
    scopes: list[str] | None = None
    provider_options: dict[str, Any] | None = None
    api_key: str | None = None


class LlmNodeRoutesRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    node_routing: dict[str, Any]
    retry_budget: dict[str, Any] | None = None
    job_runtime: dict[str, Any] | None = None
    activate: bool = False


class LlmOAuthStartRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    provider_id: str
    account_id: str
    client_id: str
    client_secret: str | None = None
    redirect_uri: str
    scopes: list[str] | None = None


@router.get("/api/v1/system-config")
def system_config_overview(request: Request, session: Session = Depends(get_session)):
    return ok(SystemConfigService(session).overview(), req_id=getattr(request.state, "request_id", None))


@router.post("/api/v1/system-config/drafts")
def create_system_config_draft(
    payload: SystemConfigDraftRequest,
    request: Request,
    session: Session = Depends(get_session),
    x_admin_token: str | None = Header(default=None, alias="X-Admin-Token"),
):
    require_admin_token(x_admin_token)
    actor_ref = getattr(request.state, "operator_ref", None) or "operator"
    result = SystemConfigService(session).create_draft(
        category=payload.category,
        yaml_raw=payload.yaml_raw,
        secrets=payload.secrets,
        actor_ref=actor_ref,
    )
    return ok(result, req_id=getattr(request.state, "request_id", None))


@router.post("/api/v1/system-config/{snapshot_id}/activate")
def activate_system_config_snapshot(
    snapshot_id: str,
    request: Request,
    session: Session = Depends(get_session),
    x_admin_token: str | None = Header(default=None, alias="X-Admin-Token"),
):
    require_admin_token(x_admin_token)
    actor_ref = getattr(request.state, "operator_ref", None) or "operator"
    return ok(
        SystemConfigService(session).activate(snapshot_id, actor_ref=actor_ref),
        req_id=getattr(request.state, "request_id", None),
    )


@router.post("/api/v1/system-config/test-provider")
def test_system_config_provider(
    payload: ProviderProbeRequest,
    session: Session = Depends(get_session),
    x_admin_token: str | None = Header(default=None, alias="X-Admin-Token"),
):
    require_admin_token(x_admin_token)
    return ok(SystemConfigService(session).test_provider(payload=payload.model_dump()), req_id=None)


@router.get("/api/v1/system-config/export/{category}")
def export_system_config_category(category: str, request: Request, session: Session = Depends(get_session)):
    return ok(
        SystemConfigService(session).export_category(category),
        req_id=getattr(request.state, "request_id", None),
    )


@router.get("/api/v1/system-config/llm")
def system_config_llm_overview(request: Request, session: Session = Depends(get_session)):
    return ok(SystemConfigService(session).llm_overview(), req_id=getattr(request.state, "request_id", None))


@router.post("/api/v1/system-config/llm/providers")
def save_system_config_llm_provider(
    payload: LlmProviderConfigRequest,
    request: Request,
    session: Session = Depends(get_session),
    x_admin_token: str | None = Header(default=None, alias="X-Admin-Token"),
):
    require_admin_token(x_admin_token)
    actor_ref = getattr(request.state, "operator_ref", None) or "operator"
    return ok(
        SystemConfigService(session).save_llm_provider(payload=payload.model_dump(mode="json", exclude_none=True), actor_ref=actor_ref),
        req_id=getattr(request.state, "request_id", None),
    )


@router.post("/api/v1/system-config/llm/node-routes")
def save_system_config_llm_node_routes(
    payload: LlmNodeRoutesRequest,
    request: Request,
    session: Session = Depends(get_session),
    x_admin_token: str | None = Header(default=None, alias="X-Admin-Token"),
):
    require_admin_token(x_admin_token)
    actor_ref = getattr(request.state, "operator_ref", None) or "operator"
    return ok(
        SystemConfigService(session).save_llm_node_routes(payload=payload.model_dump(mode="json", exclude_none=True), actor_ref=actor_ref),
        req_id=getattr(request.state, "request_id", None),
    )


@router.post("/api/v1/system-config/llm/providers/{provider_id}/probe")
def probe_system_config_llm_provider(
    provider_id: str,
    payload: ProviderProbeRequest | None = None,
    session: Session = Depends(get_session),
    x_admin_token: str | None = Header(default=None, alias="X-Admin-Token"),
):
    require_admin_token(x_admin_token)
    return ok(
        SystemConfigService(session).probe_llm_provider(provider_id=provider_id, payload=payload.model_dump(mode="json", exclude_none=True) if payload else {}),
        req_id=None,
    )


@router.post("/api/v1/system-config/llm/oauth/{provider_type}/start")
def start_system_config_llm_oauth(
    provider_type: str,
    payload: LlmOAuthStartRequest,
    session: Session = Depends(get_session),
    x_admin_token: str | None = Header(default=None, alias="X-Admin-Token"),
):
    require_admin_token(x_admin_token)
    return ok(
        SystemConfigService(session).start_llm_oauth(provider_type=provider_type, payload=payload.model_dump(mode="json", exclude_none=True)),
        req_id=None,
    )


@router.get("/api/v1/system-config/llm/oauth/callback")
def finish_system_config_llm_oauth(
    request: Request,
    state: str,
    code: str | None = None,
    error: str | None = None,
    session: Session = Depends(get_session),
):
    actor_ref = getattr(request.state, "operator_ref", None) or "oauth_callback"
    return ok(
        SystemConfigService(session).finish_llm_oauth(state=state, code=code, error=error, actor_ref=actor_ref),
        req_id=getattr(request.state, "request_id", None),
    )
