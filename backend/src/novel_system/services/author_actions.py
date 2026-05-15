from __future__ import annotations

from typing import Any


def author_action(
    title: str,
    message: str,
    *,
    target_view: str,
    target_ref: str,
    primary_button_label: str,
    evidence_summary: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "title": title,
        "message": message,
        "target_view": target_view,
        "target_ref": target_ref,
        "primary_button_label": primary_button_label,
        "evidence_summary": [str(item) for item in (evidence_summary or []) if str(item).strip()],
    }


def llm_setup_action(*, llm_enabled: bool, generation_mode: str, missing_routes: list[str] | None = None) -> dict[str, Any]:
    evidence = [f"llm_enabled={str(bool(llm_enabled)).lower()}", f"generation_mode={generation_mode}"]
    for route in missing_routes or []:
        evidence.append(f"missing_route={route}")
    return author_action(
        "需要先启用真实模型",
        "当前还没有可用的 LLM 运行配置。配置 provider、密钥/地址并测试通过后，再开始章节起草。",
        target_view="config",
        target_ref="system_config:llm",
        primary_button_label="去系统配置",
        evidence_summary=evidence,
    )
