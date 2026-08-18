from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from novel_system.api.deps import get_session
from novel_system.api.response import ok
from novel_system.services.idempotency import execute_with_idempotency
from novel_system.services.interop_center import InteropCenterService

router = APIRouter(tags=["interop"])


class BundleWorksheetYamlRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    worksheet_yaml: str = Field(min_length=1, max_length=2_000_000)


@router.post("/api/v1/interop/preview/bundle-worksheet")
def preview_bundle_worksheet(
    body: BundleWorksheetYamlRequest,
    request: Request,
    session: Session = Depends(get_session),
):
    # idempotency-exempt: deterministic read-only preview; no DB/file/provider side effect.
    payload = InteropCenterService(session).preview_yaml(body.worksheet_yaml)
    return ok(payload, req_id=getattr(request.state, "request_id", None))


@router.post("/api/v1/interop/import/bundle-worksheet")
def import_bundle_worksheet(
    body: BundleWorksheetYamlRequest,
    request: Request,
    session: Session = Depends(get_session),
):
    actor_ref = getattr(request.state, "operator_ref", None) or "operator"
    result, status = execute_with_idempotency(
        session,
        idempotency_key=request.headers.get("X-Idempotency-Key"),
        method="POST",
        path_template="/api/v1/interop/import/bundle-worksheet",
        payload={"worksheet_yaml": body.worksheet_yaml},
        action=lambda: InteropCenterService(session).import_yaml(body.worksheet_yaml, actor_ref=actor_ref),
        actor_ref=actor_ref,
    )
    headers = {"X-Idempotency-Status": status} if status else {}
    return ok(result, req_id=getattr(request.state, "request_id", None), headers=headers)


@router.get("/api/v1/interop/export/bundle-worksheet/{bundle_id}")
def export_bundle_worksheet(bundle_id: str, request: Request, session: Session = Depends(get_session)):
    payload = InteropCenterService(session).export_bundle(bundle_id)
    return ok(payload, req_id=getattr(request.state, "request_id", None))


@router.get("/api/v1/replay/final-scene/{row_id}")
def replay_final_scene(row_id: str, request: Request, session: Session = Depends(get_session)):
    payload = InteropCenterService(session).replay_final_scene(row_id)
    return ok(payload, req_id=getattr(request.state, "request_id", None))


@router.get("/api/v1/replay/draft/{row_id}")
def replay_draft(row_id: str, request: Request, session: Session = Depends(get_session)):
    payload = InteropCenterService(session).replay_draft(row_id)
    return ok(payload, req_id=getattr(request.state, "request_id", None))
