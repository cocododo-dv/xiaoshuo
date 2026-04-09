from __future__ import annotations

import uuid

from fastapi.responses import JSONResponse


def request_id() -> str:
    return f"req_{uuid.uuid4().hex[:12]}"


def ok(data: dict, *, req_id: str | None = None, headers: dict[str, str] | None = None) -> JSONResponse:
    return JSONResponse(
        {"ok": True, "data": data, "error": None, "request_id": req_id or request_id()},
        headers=headers or {},
    )


def error(code: str, message: str, *, status_code: int, details: dict | None = None, req_id: str | None = None) -> JSONResponse:
    return JSONResponse(
        {
            "ok": False,
            "data": None,
            "error": {"code": code, "message": message, "details": details or {}},
            "request_id": req_id or request_id(),
        },
        status_code=status_code,
    )
