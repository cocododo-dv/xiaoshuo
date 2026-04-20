from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict

from novel_system.api.response import ok
from novel_system.services.errors import DomainError
from novel_system.services.literary_eval import (
    BaselineLiteraryCaseGenerator,
    LLMLiteraryCaseGenerator,
    LiteraryEvalRunner,
    load_literary_eval_suite,
)
from novel_system.services.llm_client import LLMClient, load_model_routing_config
from novel_system.services.system_config import load_llm_provider_runtime_configs
from novel_system.settings import get_settings

router = APIRouter(tags=["literary_eval"])


class LiteraryEvalRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Literal["baseline", "live"] = "baseline"
    suite_path: str | None = None
    model: str | None = None


@router.get("/api/v1/literary-eval/latest")
def latest_literary_eval_report(request: Request):
    path = _latest_report_path()
    if not path.exists():
        return ok({"report": None}, req_id=getattr(request.state, "request_id", None))
    return ok({"report": json.loads(path.read_text(encoding="utf-8"))}, req_id=getattr(request.state, "request_id", None))


@router.post("/api/v1/literary-eval/run")
def run_literary_eval(payload: LiteraryEvalRunRequest, request: Request):
    suite_path = Path(payload.suite_path) if payload.suite_path else _default_suite_path()
    suite = load_literary_eval_suite(suite_path)
    generator = _generator_for_mode(payload.mode, model=payload.model)
    report = LiteraryEvalRunner(suite, generator=generator).run(output_path=_latest_report_path())
    report["mode"] = payload.mode
    report["suite_path"] = str(suite_path)
    _latest_report_path().write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return ok({"report": report}, req_id=getattr(request.state, "request_id", None))


def _latest_report_path() -> Path:
    configured = os.environ.get("NOVEL_SYSTEM_LITERARY_EVAL_REPORT_PATH")
    return Path(configured) if configured else Path.cwd() / ".codex-run" / "literary_eval_latest.json"


def _default_suite_path() -> Path:
    return Path(__file__).resolve().parents[5] / "config" / "evals" / "literary_small.yaml"


def _generator_for_mode(mode: str, *, model: str | None):
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
    task_config = routing.node_routing.get("literary_eval_live") or routing.node_routing.get("style_draft")
    if task_config is None and model is None:
        raise DomainError(
            "LITERARY_EVAL_LIVE_MODEL_MISSING",
            "Live literary eval requires a model override or task_routing.stylize.",
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
        if provider_config.api_key or provider_config.access_token:
            return True
    return False
