from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from novel_system.services.literary_eval import (
    BaselineLiteraryCaseGenerator,
    LLMLiteraryCaseGenerator,
    LiteraryEvalRunner,
    load_literary_eval_suite,
)
from novel_system.services.llm_client import LLMClient, load_model_routing_config
from novel_system.services.system_config import load_llm_provider_runtime_configs
from novel_system.settings import get_settings


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the small literary quality eval suite.")
    parser.add_argument(
        "--suite",
        default=str(_default_suite_path()),
        help="Path to a literary eval suite YAML file.",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Optional JSON report path.",
    )
    parser.add_argument(
        "--mode",
        choices=["baseline", "live"],
        default="baseline",
        help="baseline scores suite baseline_text; live calls the configured LLM provider.",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="Live LLM model override. Defaults to models.yaml task_routing.stylize.model.",
    )
    args = parser.parse_args(argv)

    suite = load_literary_eval_suite(args.suite)
    generator = _generator_for_mode(args.mode, model=args.model)
    result = LiteraryEvalRunner(suite, generator=generator).run(output_path=args.output)
    print(json.dumps(result["summary"], ensure_ascii=False, indent=2))
    return 0


def _generator_for_mode(mode: str, *, model: str | None):
    if mode == "baseline":
        return BaselineLiteraryCaseGenerator()

    settings = get_settings()
    if not settings.llm_enabled:
        raise SystemExit("live literary eval requires NOVEL_SYSTEM_LLM_ENABLED=true")

    routing = load_model_routing_config()
    task_config = routing.node_routing.get("literary_eval_live") or routing.node_routing.get("style_draft")
    if task_config is None and model is None:
        raise SystemExit("live literary eval requires --model or task_routing.stylize")
    provider_configs = load_llm_provider_runtime_configs()
    if not _live_credentials_available(
        settings.llm_api_key,
        provider_configs,
        provider_id=task_config.provider_id if task_config is not None else None,
    ):
        raise SystemExit("live literary eval requires a configured API key or credential-free local provider")
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


def _default_suite_path() -> Path:
    return Path(__file__).resolve().parents[4] / "config" / "evals" / "literary_small.yaml"


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
