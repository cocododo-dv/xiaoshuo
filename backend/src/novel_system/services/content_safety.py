"""Deterministic, auditable content-risk triage for manuscript publication.

The classifier intentionally reports heuristics instead of claiming semantic
understanding. It blocks only unattended publication of a few compound high-
risk patterns; an author can acknowledge an exact finding code on the exact
publication action. Dark themes remain writable and ordinary genre violence is
advisory rather than censored.
"""

from __future__ import annotations

import re
from typing import Any, Iterable

from novel_system.settings import get_settings


CONTENT_SAFETY_SCHEMA_VERSION = 1

_SEXUAL_TERMS = (
    "性交",
    "做爱",
    "性行为",
    "性关系",
    "阴茎",
    "阴道",
    "口交",
    "sex with",
    "sexual intercourse",
)
_MINOR_TERMS = (
    "未成年",
    "小学生",
    "初中生",
    "儿童",
    "幼童",
    "男童",
    "女童",
    "underage",
    "minor child",
)
_NONCONSENSUAL_SEXUAL_TERMS = (
    "强奸",
    "性侵",
    "迷奸",
    "强迫性交",
    "rape",
    "sexual assault",
)
_SELF_HARM_TERMS = ("自杀", "轻生", "结束生命", "suicide", "kill myself")
_SELF_HARM_METHOD_TERMS = (
    "剂量",
    "割腕",
    "绳结",
    "上吊",
    "跳楼",
    "一氧化碳",
    "安眠药",
    "具体步骤",
    "dosage",
    "method",
)
_GRAPHIC_VIOLENCE_TERMS = ("肢解", "开膛", "剥皮", "内脏流出", "碎尸", "dismember", "disembowel")
_TARGETED_HATE_TERMS = ("消灭所有", "清除全部", "天生低等", "不配活着", "exterminate all", "born inferior")


class ContentSafetyService:
    @staticmethod
    def assess(
        content: str,
        *,
        acknowledged_codes: Iterable[str] = (),
        mode: str | None = None,
    ) -> dict[str, Any]:
        text = str(content or "")
        lowered = text.lower()
        acknowledged = {str(code).strip() for code in acknowledged_codes if str(code).strip()}
        configured_mode = mode or get_settings(include_runtime_config=False).content_safety_mode
        findings: list[dict[str, Any]] = []

        sexual = _matches(lowered, _SEXUAL_TERMS)
        minor = _matches(lowered, _MINOR_TERMS)
        minor.extend(_minor_age_matches(lowered))
        if sexual and minor:
            findings.append(
                _finding(
                    "sexual_content_with_minor_indicators",
                    "high",
                    sexual[:3] + minor[:3],
                    "文本同时出现明确性内容与未成年指示；必须由作者核对人物年龄和叙事目的。",
                    review_required=True,
                )
            )

        nonconsensual = _matches(lowered, _NONCONSENSUAL_SEXUAL_TERMS)
        if nonconsensual:
            findings.append(
                _finding(
                    "nonconsensual_sexual_violence",
                    "high",
                    nonconsensual[:4],
                    "文本出现非自愿性暴力指示；自动归档前需作者确认它不是无意生成或剥削性描写。",
                    review_required=True,
                )
            )

        self_harm = _matches(lowered, _SELF_HARM_TERMS)
        self_harm_method = _matches(lowered, _SELF_HARM_METHOD_TERMS)
        if self_harm and self_harm_method:
            findings.append(
                _finding(
                    "actionable_self_harm_detail",
                    "high",
                    self_harm[:2] + self_harm_method[:3],
                    "文本可能同时包含自伤意图与可操作方法细节；需人工核对必要性、准确性与呈现方式。",
                    review_required=True,
                )
            )
        elif self_harm:
            findings.append(
                _finding(
                    "self_harm_theme",
                    "medium",
                    self_harm[:3],
                    "文本涉及自伤主题；建议作者检查触发内容、后果呈现与读者预警。",
                    review_required=False,
                )
            )

        graphic = _matches(lowered, _GRAPHIC_VIOLENCE_TERMS)
        if graphic:
            findings.append(
                _finding(
                    "graphic_violence",
                    "medium",
                    graphic[:4],
                    "文本包含强烈身体伤害指示；建议确认分级、必要性与读者预警。",
                    review_required=False,
                )
            )

        targeted_hate = _matches(lowered, _TARGETED_HATE_TERMS)
        if targeted_hate:
            findings.append(
                _finding(
                    "targeted_hate_rhetoric",
                    "medium",
                    targeted_hate[:4],
                    "文本出现针对群体的贬损或清除式表达；需检查叙事立场与上下文是否清楚。",
                    review_required=False,
                )
            )

        blockers: list[str] = []
        warnings: list[dict[str, Any]] = []
        recognized_acknowledged: set[str] = set()
        for finding in findings:
            code = finding["code"]
            is_acknowledged = code in acknowledged
            if is_acknowledged:
                recognized_acknowledged.add(code)
            finding["acknowledged"] = is_acknowledged
            finding["blocking"] = bool(
                configured_mode == "review"
                and finding["review_required"]
                and not is_acknowledged
            )
            if finding["blocking"]:
                blockers.append(f"content_safety_review:{code}")
            else:
                warnings.append(
                    {
                        "issue_key": f"content_safety:{code}",
                        "quality_level": "safety_review",
                        "blocking": False,
                        "message": finding["message"],
                        "acknowledged": is_acknowledged,
                    }
                )
        return {
            "schema_version": CONTENT_SAFETY_SCHEMA_VERSION,
            "mode": configured_mode,
            "findings": findings,
            "blocking_codes": blockers,
            "warnings": warnings,
            "requires_human_review": any(item["review_required"] for item in findings),
            # Ignore prefilled/unknown codes: only a code that corresponds to a
            # finding on this exact text can become part of the audit record.
            "acknowledged_codes": sorted(recognized_acknowledged),
            "limitations": [
                "启发式不能可靠判断人物真实年龄、同意关系、叙事立场或教育/调查语境。",
                "未命中不代表内容安全；跨语言隐喻、委婉表达与长距离语义关系仍是盲区。",
                "命中只触发人工复核，不应被解释为法律结论、平台分级或作品价值判断。",
            ],
        }


def _matches(text: str, terms: tuple[str, ...]) -> list[str]:
    return list(dict.fromkeys(term for term in terms if term in text))


def _minor_age_matches(text: str) -> list[str]:
    matches = []
    for raw in re.findall(r"(?<!\d)([0-9]|1[0-7])\s*(?:岁|years? old)", text):
        matches.append(f"age:{raw}")
    return list(dict.fromkeys(matches))


def _finding(
    code: str,
    severity: str,
    evidence_terms: list[str],
    message: str,
    *,
    review_required: bool,
) -> dict[str, Any]:
    return {
        "code": code,
        "severity": severity,
        "confidence": "heuristic",
        "evidence_terms": list(dict.fromkeys(evidence_terms)),
        "message": message,
        "review_required": review_required,
    }
