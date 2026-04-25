from __future__ import annotations

import uuid

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.exc import OperationalError

from novel_system.api.response import error
from novel_system.api.routes import (
    author_drafts,
    chapter_manuscripts,
    chapters,
    domain,
    indexing,
    interop,
    knowledge,
    literary_eval,
    longform_control,
    reference_books,
    review,
    scenes,
    style_profile,
    system_config,
    writer_deep_review,
    writer_review,
)
from novel_system.db import models  # noqa: F401
from novel_system.db.base import Base
from novel_system.db.session import engine
from novel_system.services.database_errors import is_database_busy_error
from novel_system.services.errors import DomainError


def _operator_ref_from_request(request: Request) -> str:
    actor_ref = (request.headers.get("X-Operator-Ref") or "").strip()
    return actor_ref or "operator"


def create_app() -> FastAPI:
    Base.metadata.create_all(bind=engine())
    app = FastAPI(title="Novel System P2")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def request_id_middleware(request: Request, call_next):
        request.state.request_id = f"req_{uuid.uuid4().hex[:12]}"
        request.state.operator_ref = _operator_ref_from_request(request)
        return await call_next(request)

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
        return error(
            "INTERNAL_ERROR",
            str(exc) or "internal server error",
            status_code=500,
            details={"retryable": False},
            req_id=getattr(request.state, "request_id", None),
        )

    app.include_router(chapters.router)
    app.include_router(author_drafts.router)
    app.include_router(chapter_manuscripts.router)
    app.include_router(longform_control.router)
    app.include_router(scenes.router)
    app.include_router(writer_review.router)
    app.include_router(writer_deep_review.router)
    app.include_router(review.router)
    app.include_router(domain.router)
    app.include_router(knowledge.router)
    app.include_router(reference_books.router)
    app.include_router(indexing.router)
    app.include_router(interop.router)
    app.include_router(system_config.router)
    app.include_router(literary_eval.router)
    app.include_router(style_profile.router)
    return app
