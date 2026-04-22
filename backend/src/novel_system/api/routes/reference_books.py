from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from novel_system.api.deps import get_session
from novel_system.api.response import ok
from novel_system.services.idempotency import execute_with_idempotency
from novel_system.services.reference_learning import ReferenceLearningService

router = APIRouter(tags=["reference_books"])


class ImportPathRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    file_path: str
    title: str | None = None
    author_label: str | None = None
    cloud_policy: str
    analysis_focus: str = "style_structure"


class StartRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    batch_size: int = Field(default=8, ge=5, le=8)


class ApplyProfileRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scope: str
    scope_ref_id: str | None = None


@router.post("/api/v1/reference-books/import-path")
def import_reference_book_path(
    payload: ImportPathRequest,
    request: Request,
    session: Session = Depends(get_session),
):
    actor_ref = getattr(request.state, "operator_ref", None) or "operator"
    body = payload.model_dump(mode="json")
    result, status = execute_with_idempotency(
        session,
        idempotency_key=request.headers.get("X-Idempotency-Key"),
        method="POST",
        path_template="/api/v1/reference-books/import-path",
        payload=body,
        action=lambda: ReferenceLearningService(session).import_path(**body),
        actor_ref=actor_ref,
    )
    headers = {"X-Idempotency-Status": status} if status else {}
    return ok(result, req_id=getattr(request.state, "request_id", None), headers=headers)


@router.post("/api/v1/reference-books/import-upload")
async def import_reference_book_upload(
    request: Request,
    file: UploadFile = File(...),
    title: str | None = Form(default=None),
    author_label: str | None = Form(default=None),
    cloud_policy: str = Form(...),
    analysis_focus: str = Form(default="style_structure"),
    session: Session = Depends(get_session),
):
    actor_ref = getattr(request.state, "operator_ref", None) or "operator"
    raw_bytes = await file.read()
    payload: dict[str, Any] = {
        "file_name": file.filename,
        "title": title,
        "author_label": author_label,
        "cloud_policy": cloud_policy,
        "analysis_focus": analysis_focus,
    }
    result, status = execute_with_idempotency(
        session,
        idempotency_key=request.headers.get("X-Idempotency-Key"),
        method="POST",
        path_template="/api/v1/reference-books/import-upload",
        payload=payload,
        action=lambda: ReferenceLearningService(session).import_bytes(
            raw_bytes=raw_bytes,
            source_kind="upload",
            **payload,
        ),
        actor_ref=actor_ref,
    )
    headers = {"X-Idempotency-Status": status} if status else {}
    return ok(result, req_id=getattr(request.state, "request_id", None), headers=headers)


@router.get("/api/v1/reference-books")
def list_reference_books(request: Request, session: Session = Depends(get_session)):
    return ok(
        ReferenceLearningService(session).list_books(),
        req_id=getattr(request.state, "request_id", None),
    )


@router.get("/api/v1/reference-books/{book_id}")
def reference_book_detail(book_id: str, request: Request, session: Session = Depends(get_session)):
    return ok(
        ReferenceLearningService(session).detail(book_id),
        req_id=getattr(request.state, "request_id", None),
    )


@router.get("/api/v1/reference-books/{book_id}/segments/{segment_id}/excerpt")
def reference_book_segment_excerpt(
    book_id: str,
    segment_id: str,
    request: Request,
    session: Session = Depends(get_session),
):
    return ok(
        ReferenceLearningService(session).segment_excerpt(book_id, segment_id),
        req_id=getattr(request.state, "request_id", None),
    )


@router.post("/api/v1/reference-books/{book_id}/runs")
def start_reference_learning_run(
    book_id: str,
    payload: StartRunRequest,
    request: Request,
    session: Session = Depends(get_session),
):
    actor_ref = getattr(request.state, "operator_ref", None) or "operator"
    body = payload.model_dump(mode="json")
    result, status = execute_with_idempotency(
        session,
        idempotency_key=request.headers.get("X-Idempotency-Key"),
        method="POST",
        path_template="/api/v1/reference-books/{book_id}/runs",
        payload={"book_id": book_id, **body},
        action=lambda: ReferenceLearningService(session).start_run(book_id, batch_size=payload.batch_size),
        actor_ref=actor_ref,
    )
    headers = {"X-Idempotency-Status": status} if status else {}
    return ok(result, req_id=getattr(request.state, "request_id", None), headers=headers)


@router.post("/api/v1/reference-books/{book_id}/runs/{run_id}/advance")
def advance_reference_learning_run(
    book_id: str,
    run_id: str,
    request: Request,
    session: Session = Depends(get_session),
):
    actor_ref = getattr(request.state, "operator_ref", None) or "operator"
    result, status = execute_with_idempotency(
        session,
        idempotency_key=request.headers.get("X-Idempotency-Key"),
        method="POST",
        path_template="/api/v1/reference-books/{book_id}/runs/{run_id}/advance",
        payload={"book_id": book_id, "run_id": run_id},
        action=lambda: ReferenceLearningService(session).advance_run(book_id, run_id),
        actor_ref=actor_ref,
    )
    headers = {"X-Idempotency-Status": status} if status else {}
    return ok(result, req_id=getattr(request.state, "request_id", None), headers=headers)


@router.post("/api/v1/reference-books/{book_id}/profiles/{profile_id}/apply")
def apply_reference_profile(
    book_id: str,
    profile_id: str,
    payload: ApplyProfileRequest,
    request: Request,
    session: Session = Depends(get_session),
):
    actor_ref = getattr(request.state, "operator_ref", None) or "operator"
    body = payload.model_dump(mode="json")
    result, status = execute_with_idempotency(
        session,
        idempotency_key=request.headers.get("X-Idempotency-Key"),
        method="POST",
        path_template="/api/v1/reference-books/{book_id}/profiles/{profile_id}/apply",
        payload={"book_id": book_id, "profile_id": profile_id, **body},
        action=lambda: ReferenceLearningService(session).apply_profile(book_id, profile_id, **body),
        actor_ref=actor_ref,
    )
    headers = {"X-Idempotency-Status": status} if status else {}
    return ok(result, req_id=getattr(request.state, "request_id", None), headers=headers)
