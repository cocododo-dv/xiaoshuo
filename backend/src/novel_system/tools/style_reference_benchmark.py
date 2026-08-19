"""准备、检查和评分跨内容风格参考基准。

示例（从 backend 目录执行）::

    python -m novel_system.tools.style_reference_benchmark inspect
    python -m novel_system.tools.style_reference_benchmark prepare
    python -m novel_system.tools.style_reference_benchmark score --results .style-benchmark/results.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

from novel_system.services.style_reference.benchmark import (
    build_blind_review_artifacts,
    load_style_benchmark,
    load_style_benchmark_manifest,
    run_live_benchmark_workspace,
    score_style_benchmark,
)
from novel_system.services.style_reference.benchmark.workspace import (
    prepare_generation_workspace,
    write_json,
)


_WORKSPACE_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_PUBLIC = (
    _WORKSPACE_ROOT
    / "config"
    / "evals"
    / "style_reference"
    / "style_benchmark_v1.public.json"
)
DEFAULT_PRIVATE = (
    _WORKSPACE_ROOT
    / "config"
    / "evals"
    / "style_reference"
    / "style_benchmark_v1.private.json"
)
DEFAULT_OUTPUT_DIR = _WORKSPACE_ROOT / "backend" / ".style-benchmark"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    inspect = subparsers.add_parser("inspect", help="校验公私清单并仅打印安全摘要")
    _add_manifest_args(inspect, include_private=True)

    prepare = subparsers.add_parser(
        "prepare", help="只读公开清单，准备训练语料与生成矩阵"
    )
    _add_manifest_args(prepare, include_private=False)
    prepare.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)

    score = subparsers.add_parser("score", help="用隐藏整篇留出作品评分完整生成矩阵")
    _add_manifest_args(score, include_private=True)
    score.add_argument("--results", type=Path, required=True)
    score.add_argument(
        "--report", type=Path, default=DEFAULT_OUTPUT_DIR / "report.json"
    )
    score.add_argument(
        "--blind-packet", type=Path, default=DEFAULT_OUTPUT_DIR / "blind_packet.json"
    )
    score.add_argument(
        "--blind-key", type=Path, default=DEFAULT_OUTPUT_DIR / "blind_key.json"
    )
    score.add_argument("--blind-seed", default="style-benchmark-v1")

    live = subparsers.add_parser(
        "run-live",
        help="在隔离数据库中运行现有风格模块的完整 24 单元基准并自动评分",
    )
    _add_manifest_args(live, include_private=True)
    live.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR / "live")
    live.add_argument("--resume", action="store_true")
    live.add_argument("--blind-seed", default="style-benchmark-v1")
    return parser


def _add_manifest_args(
    parser: argparse.ArgumentParser, *, include_private: bool
) -> None:
    parser.add_argument("--public", type=Path, default=DEFAULT_PUBLIC)
    if include_private:
        parser.add_argument("--private", type=Path, default=DEFAULT_PRIVATE)


def main(argv: Sequence[str] | None = None) -> int:
    _configure_utf8_stdio()
    args = _parser().parse_args(argv)
    if args.command == "prepare":
        manifest = load_style_benchmark_manifest(
            args.public, workspace_root=_WORKSPACE_ROOT
        )
        result = prepare_generation_workspace(manifest, args.output_dir)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    if args.command == "run-live":
        # 严格边界：生成阶段只加载公开清单。隐藏清单在 24 个单元全部生成完后
        # 才由评分阶段读取，绝不传入 live runner。
        manifest = load_style_benchmark_manifest(
            args.public, workspace_root=_WORKSPACE_ROOT
        )
        client = _configured_live_client()
        output_dir = args.output_dir.expanduser().resolve()
        results = run_live_benchmark_workspace(
            manifest,
            llm_client=client,
            output_dir=output_dir,
            resume=args.resume,
            progress=_print_progress,
        )
        bundle = load_style_benchmark(
            args.public, args.private, workspace_root=_WORKSPACE_ROOT
        )
        report = score_style_benchmark(bundle, results)
        packet, answer_key = build_blind_review_artifacts(
            bundle,
            results,
            seed=args.blind_seed,
        )
        write_json(output_dir / "report.json", report)
        write_json(output_dir / "blind_packet.json", packet)
        write_json(output_dir / "blind_key.json", answer_key)
        print(
            json.dumps(
                {
                    "benchmark_passed": report["benchmark_passed"],
                    "summary": report["summary"],
                    "results": str((output_dir / "results.json").resolve()),
                    "report": str((output_dir / "report.json").resolve()),
                    "blind_packet": str((output_dir / "blind_packet.json").resolve()),
                    "blind_key": str((output_dir / "blind_key.json").resolve()),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0 if report["benchmark_passed"] else 2

    bundle = load_style_benchmark(
        args.public, args.private, workspace_root=_WORKSPACE_ROOT
    )
    if args.command == "inspect":
        print(json.dumps(bundle.safe_summary(), ensure_ascii=False, indent=2))
        return 0

    report = score_style_benchmark(bundle, args.results)
    packet, answer_key = build_blind_review_artifacts(
        bundle,
        args.results,
        seed=args.blind_seed,
    )
    write_json(args.report, report)
    write_json(args.blind_packet, packet)
    write_json(args.blind_key, answer_key)
    print(
        json.dumps(
            {
                "benchmark_passed": report["benchmark_passed"],
                "summary": report["summary"],
                "report": str(args.report.resolve()),
                "blind_packet": str(args.blind_packet.resolve()),
                "blind_key": str(args.blind_key.resolve()),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if report["benchmark_passed"] else 2


def _configured_live_client():  # noqa: ANN202
    from novel_system.services.llm_client import LLMClient, load_model_routing_config
    from novel_system.services.system_config import load_llm_provider_runtime_configs
    from novel_system.settings import get_settings

    settings = get_settings()
    if not settings.llm_enabled:
        raise SystemExit("run-live 需要在系统设置中启用 LLM")
    routing = load_model_routing_config()
    required_nodes = (
        "style_ref_extract_language",
        "style_ref_extract_narrative",
        "style_ref_extract_scene",
        "style_ref_extract_theme",
        "style_ref_supplement_evidence",
        "style_ref_synthesize_profile",
        "neutral_draft",
        "style_draft",
        "style_patch",
    )
    missing_routes = [
        node_id for node_id in required_nodes if node_id not in routing.node_routing
    ]
    if missing_routes:
        raise SystemExit(f"run-live 缺少模型路由: {', '.join(missing_routes)}")
    provider_configs = load_llm_provider_runtime_configs()
    missing_credentials: list[str] = []
    for node_id in required_nodes:
        task = routing.node_routing[node_id]
        provider_config = (
            provider_configs.get(task.provider_id) if task.provider_id else None
        )
        credential_mode = (
            getattr(provider_config, "credential_mode", None)
            or task.credential_mode
            or "api_key"
        )
        has_key = bool(
            settings.llm_api_key
            or (
                getattr(provider_config, "api_key", None)
                if provider_config is not None
                else None
            )
        )
        enabled = provider_config is None or bool(
            getattr(provider_config, "enabled", False)
        )
        if not enabled or (credential_mode != "none" and not has_key):
            missing_credentials.append(f"{node_id}:{task.provider_id or task.provider}")
    if missing_credentials:
        raise SystemExit(
            "run-live 的路由没有可用凭据或 provider 未启用: "
            + ", ".join(sorted(set(missing_credentials)))
        )
    return LLMClient(
        provider=settings.llm_provider,
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key,
        timeout_seconds=settings.llm_timeout_seconds,
        provider_configs=provider_configs,
    )


def _print_progress(event: str, payload) -> None:  # noqa: ANN001
    print(json.dumps({"event": event, **dict(payload)}, ensure_ascii=False), flush=True)


def _configure_utf8_stdio() -> None:
    """让 Windows 控制台/重定向日志中的中文诊断保持可读。"""

    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8", errors="replace")


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
