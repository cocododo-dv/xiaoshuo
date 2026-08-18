from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, Header, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from novel_system.api.deps import get_session
from novel_system.api.mutations import optional_idempotent_response
from novel_system.api.response import ok
from novel_system.services.errors import DomainError
from novel_system.services.literary_eval import (
    BaselineLiteraryCaseGenerator,
    LLMLiteraryCaseGenerator,
    LiteraryEvalRunner,
    load_literary_eval_suite,
    new_literary_eval_run_id,
)
from novel_system.services.llm_client import LLMClient, load_model_routing_config
from novel_system.services.system_config import load_llm_provider_runtime_configs
from novel_system.services.system_config import require_admin_token
from novel_system.settings import get_settings

router = APIRouter(tags=["literary_eval"])


class LiteraryEvalRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    mode: Literal["baseline", "live"] = "baseline"
    suite_path: str | None = Field(default=None, max_length=2048)
    model: str | None = Field(default=None, min_length=1, max_length=255)


@router.get("/api/v1/literary-eval/latest")
def latest_literary_eval_report(request: Request):
    path = _latest_report_path()
    if not path.exists():
        return ok({"report": None}, req_id=getattr(request.state, "request_id", None))
    return ok({"report": json.loads(path.read_text(encoding="utf-8"))}, req_id=getattr(request.state, "request_id", None))


@router.post("/api/v1/literary-eval/run")
def run_literary_eval(
    payload: LiteraryEvalRunRequest,
    request: Request,
    x_admin_token: str | None = Header(default=None, alias="X-Admin-Token"),
    session: Session = Depends(get_session),
):
    body = payload.model_dump(mode="json")
    if payload.suite_path is not None:
        require_admin_token(
            x_admin_token,
            client_host=request.client.host if request.client is not None else None,
        )

    def run() -> dict:
        suite_path = _resolve_suite_path(payload.suite_path)
        suite = load_literary_eval_suite(suite_path)
        eval_run_id = new_literary_eval_run_id()
        generator = _generator_for_mode(
            payload.mode,
            model=payload.model,
            session=session,
            eval_run_id=eval_run_id,
        )
        report = LiteraryEvalRunner(
            suite,
            generator=generator,
            eval_run_id=eval_run_id,
        ).run(output_path=_latest_report_path())
        report["mode"] = payload.mode
        report["suite_path"] = str(suite_path)
        _latest_report_path().write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        return {"report": report}

    return optional_idempotent_response(
        request,
        session,
        method="POST",
        path_template="/api/v1/literary-eval/run",
        payload=body,
        action=run,
    )


def _latest_report_path() -> Path:
    return get_settings(include_runtime_config=False).literary_eval_report_path


def _default_suite_path() -> Path:
    return Path(__file__).resolve().parents[5] / "config" / "evals" / "literary_small.yaml"


def _resolve_suite_path(configured_path: str | None) -> Path:
    if configured_path is None:
        return _default_suite_path()

    candidate = Path(configured_path).expanduser()
    if not candidate.is_absolute():
        raise DomainError(
            "LITERARY_EVAL_SUITE_PATH_INVALID",
            "custom literary eval suite paths must be absolute",
            status_code=400,
        )
    if candidate.suffix.lower() not in {".yaml", ".yml"}:
        raise DomainError(
            "LITERARY_EVAL_SUITE_FORMAT_UNSUPPORTED",
            "literary eval suites must use .yaml or .yml",
            status_code=400,
        )
    try:
        resolved = candidate.resolve(strict=True)
    except FileNotFoundError as exc:
        raise DomainError(
            "LITERARY_EVAL_SUITE_NOT_FOUND",
            "literary eval suite does not exist",
            status_code=404,
        ) from exc
    except OSError as exc:
        raise DomainError(
            "LITERARY_EVAL_SUITE_PATH_INVALID",
            "literary eval suite path could not be resolved",
            status_code=400,
        ) from exc
    if not resolved.is_file():
        raise DomainError(
            "LITERARY_EVAL_SUITE_PATH_INVALID",
            "literary eval suite path must point to a regular file",
            status_code=400,
        )

    roots: list[Path] = []
    for configured_root in get_settings(
        include_runtime_config=False
    ).literary_eval_suite_roots:
        try:
            root = configured_root.expanduser().resolve(strict=True)
        except (FileNotFoundError, OSError):
            continue
        if root.is_dir():
            roots.append(root)
    if not roots:
        raise DomainError(
            "LITERARY_EVAL_SUITE_ROOT_INVALID",
            "no configured literary eval suite root is available",
            status_code=503,
        )
    if not any(resolved.is_relative_to(root) for root in roots):
        raise DomainError(
            "LITERARY_EVAL_SUITE_PATH_FORBIDDEN",
            "literary eval suite is outside the configured roots",
            status_code=403,
        )
    return resolved


def _generator_for_mode(
    mode: str,
    *,
    model: str | None,
    session: Session,
    eval_run_id: str,
):
    if mode == "baseline":
        return BaselineLiteraryCaseGenerator()

    settings = get_settings()
    if not settings.llm_enabled:
        raise DomainError(
            "LITERARY_EVAL_LIVE_DISABLED",
            "Live literary eval requires NOVEL_SYSTEM_LLM_ENABLED=true.",
            status_code=400,
        )

    routing = load_model_routing_config()
    task_config = routing.node_routing.get("literary_eval_live")
    if task_config is None and model is None:
        raise DomainError(
            "LITERARY_EVAL_LIVE_MODEL_MISSING",
            "Live literary eval requires a model override or a configured literary_eval_live node route.",
            status_code=400,
        )
    provider_configs = load_llm_provider_runtime_configs()
    if not _live_credentials_available(
        settings.llm_api_key,
        provider_configs,
        provider_id=task_config.provider_id if task_config is not None else None,
    ):
        raise DomainError(
            "LITERARY_EVAL_LIVE_CREDENTIALS_MISSING",
            "Live literary eval requires a configured API key or credential-free local provider.",
            status_code=400,
        )
    client = LLMClient(
        provider=settings.llm_provider,
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key,
        timeout_seconds=settings.llm_timeout_seconds,
        provider_configs=provider_configs,
    )
    return LLMLiteraryCaseGenerator(
        client,
        session=session,
        eval_run_id=eval_run_id,
        model=model or task_config.model,
        provider=task_config.provider if task_config is not None else settings.llm_provider,
        provider_id=task_config.provider_id if task_config is not None else None,
        account_id=task_config.account_id if task_config is not None else None,
        reasoning_level=task_config.reasoning_level if task_config is not None else "medium",
        api_mode=task_config.api_mode if task_config is not None else "responses",
        credential_mode=task_config.credential_mode if task_config is not None else None,
        provider_options=task_config.provider_options if task_config is not None else {},
        temperature=task_config.temperature if task_config is not None else 0.75,
        max_output_tokens=task_config.max_output_tokens if task_config is not None else 1200,
    )


def _live_credentials_available(api_key: str | None, provider_configs: dict, *, provider_id: str | None) -> bool:
    if api_key:
        return True
    candidates = [provider_configs[provider_id]] if provider_id and provider_id in provider_configs else provider_configs.values()
    for provider_config in candidates:
        if not provider_config.enabled:
            continue
        if provider_config.credential_mode == "none":
            return True
        if provider_config.api_key:
            return True
    return False
