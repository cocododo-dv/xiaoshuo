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
