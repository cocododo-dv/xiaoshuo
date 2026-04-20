from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from novel_system.api.deps import get_session
from novel_system.api.response import ok
from novel_system.services.demo_workflows import DragonXianxiaDemoService
from novel_system.services.idempotency import execute_with_idempotency

router = APIRouter(tags=["demo_workflows"])


@router.get("/api/v1/demo/dragon-xianxia/status")
def dragon_xianxia_status(request: Request, session: Session = Depends(get_session)):
    return ok(
        DragonXianxiaDemoService(session).status(),
        req_id=getattr(request.state, "request_id", None),
    )


@router.post("/api/v1/demo/dragon-xianxia/run")
def run_dragon_xianxia_demo(payload: dict, request: Request, session: Session = Depends(get_session)):
    actor_ref = getattr(request.state, "operator_ref", None) or "operator"
    result, status = execute_with_idempotency(
        session,
        idempotency_key=request.headers.get("X-Idempotency-Key"),
        method="POST",
        path_template="/api/v1/demo/dragon-xianxia/run",
        payload=payload or {},
        action=lambda: DragonXianxiaDemoService(session).run(),
        actor_ref=actor_ref,
    )
    headers = {"X-Idempotency-Status": status} if status else {}
    return ok(result, req_id=getattr(request.state, "request_id", None), headers=headers)
