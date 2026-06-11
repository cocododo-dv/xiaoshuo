from __future__ import annotations

import uuid
import logging

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.exc import OperationalError

from novel_system.api.response import error
from novel_system.api.routes import (
    author_drafts,
    author_desk,
    catalog,
    chapter_manuscripts,
    chapters,
    domain,
    indexing,
    interop,
    knowledge,
    library,
    longform_tower,
    literary_eval,
    literary_quality,
    longform_control,
    longform_editor,
    project_overview,
    projects,
    reference_safety,
    review,
    scenes,
    snowflake,
    snowflake_workspace,
    style_profile,
    style_reference,
    system_config,
    work_profile,
    writer_room,
    writer_deep_review,
    writer_review,
)
from novel_system.db import models  # noqa: F401
from novel_system.db.base import Base
from novel_system.db.session import engine
from novel_system.services.database_errors import is_database_busy_error
from novel_system.services.errors import DomainError
from novel_system.settings import get_settings


logger = logging.getLogger(__name__)


def _operator_ref_from_request(request: Request) -> str:
    actor_ref = (request.headers.get("X-Operator-Ref") or "").strip()
    return actor_ref or "operator"


def create_app() -> FastAPI:
    app_settings = get_settings(include_runtime_config=False)
    if app_settings.auto_create_tables:
        Base.metadata.create_all(bind=engine())
    app = FastAPI(title="Novel System P2")
    allow_origins = list(app_settings.cors_origins)
    allow_credentials = app_settings.cors_allow_credentials and "*" not in allow_origins
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allow_origins,
        allow_credentials=allow_credentials,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def request_id_middleware(request: Request, call_next):
        request.state.request_id = f"req_{uuid.uuid4().hex[:12]}"
        request.state.operator_ref = _operator_ref_from_request(request)
        response = await call_next(request)
        response.headers["X-Request-Id"] = request.state.request_id
        return response

    @app.exception_handler(DomainError)
    async def domain_error_handler(request: Request, exc: DomainError):
        return error(
            exc.code,
            exc.message,
            status_code=exc.status_code,
            details=exc.details,
            req_id=getattr(request.state, "request_id", None),
        )

    @app.exception_handler(OperationalError)
    async def operational_error_handler(request: Request, exc: OperationalError):
        if is_database_busy_error(exc):
            return error(
                "DATABASE_BUSY",
                "database is busy; retry after the current long-running operation finishes",
                status_code=503,
                details={"retryable": True},
                req_id=getattr(request.state, "request_id", None),
            )
        return error(
            "DATABASE_OPERATION_FAILED",
            "database operation failed",
            status_code=500,
            details={"retryable": False},
            req_id=getattr(request.state, "request_id", None),
        )

    @app.exception_handler(Exception)
    async def unhandled_error_handler(request: Request, exc: Exception):
        req_id = getattr(request.state, "request_id", None)
        logger.exception("Unhandled API error request_id=%s", req_id)
        return error(
            "INTERNAL_ERROR",
            str(exc) if app_settings.expose_error_detail else "internal server error",
            status_code=500,
            details={"retryable": False},
            req_id=req_id,
        )

    app.include_router(catalog.router)
    app.include_router(chapters.router)
    app.include_router(projects.router)
    app.include_router(project_overview.router)
    app.include_router(author_drafts.router)
    app.include_router(author_desk.router)
    app.include_router(chapter_manuscripts.router)
    app.include_router(longform_control.router)
    app.include_router(longform_editor.router)
    app.include_router(scenes.router)
    app.include_router(snowflake.router)
    app.include_router(snowflake_workspace.router)
    app.include_router(writer_room.router)
    app.include_router(writer_review.router)
    app.include_router(writer_deep_review.router)
    app.include_router(review.router)
    app.include_router(domain.router)
    app.include_router(library.router)
    app.include_router(longform_tower.router)
    app.include_router(knowledge.router)
    app.include_router(reference_safety.router)
    app.include_router(indexing.router)
    app.include_router(interop.router)
    app.include_router(system_config.router)
    app.include_router(work_profile.router)
    app.include_router(literary_eval.router)
    app.include_router(literary_quality.router)
    app.include_router(style_profile.router)
    app.include_router(style_reference.router)
    return app
