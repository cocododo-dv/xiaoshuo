from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

import yaml
from sqlalchemy.orm import Session

from novel_system.services.errors import DomainError
from novel_system.services.hash_engine import canonical_json
from novel_system.services.hash_engine import normalize
from novel_system.services.llm_task_runner import LLMNodeExecutionError, LLMNodeRunner
from novel_system.services.prompt_builder import PromptBuilder
from novel_system.settings import get_settings


STYLE_FEATURE_CONTRACT_VERSION = "STYLE_FEATURE_CONTRACT_v1"

STYLE_FEATURE_NAMES: tuple[str, ...] = (
    "rhythm",
    "syntax",
    "imagery",
    "narrative_distance",
    "emotion_curve",
    "paragraph_density",
    "dialogue_ratio",
)

FEATURE_KEYWORDS: dict[str, tuple[str, ...]] = {
    "rhythm": ("rhythm", "cadence", "pause", "beat", "pressure", "节奏", "停顿", "收尾", "压迫"),
    "syntax": ("syntax", "sentence", "clause", "line", "clipped", "short", "long", "句法", "短句", "长句"),
    "imagery": ("imagery", "image", "tactile", "gesture", "door", "paper", "意象", "触感", "动作"),
    "narrative_distance": ("pov", "interior", "internal", "distance", "narration", "视角", "内心", "叙事"),
    "emotion_curve": ("emotion", "tension", "suspicion", "urgency", "情绪", "张力", "怀疑", "紧迫"),
    "paragraph_density": ("paragraph", "density", "line break", "hard-ending", "段落", "换行", "密度"),
    "dialogue_ratio": ("dialogue", "spoken", "对白", "台词"),
}


class StyleProfileService:
    @staticmethod
    def contract_payload() -> dict[str, Any]:
        example = {
            "style_profile": {
                "contract_version": STYLE_FEATURE_CONTRACT_VERSION,
                "features": {
                    "rhythm": {"guidance": ["Use short pressure beats before a longer release sentence."]},
                    "syntax": {"guidance": ["Alternate clipped clauses with one sensory sentence."]},
                    "imagery": {"guidance": ["Anchor abstract tension in tactile objects and gestures."]},
                    "narrative_distance": {"guidance": ["Stay close to observable action; avoid full explanation."]},
                    "emotion_curve": {"guidance": ["Move from routine attention to suspicion, then urgency."]},
                    "paragraph_density": {"guidance": ["Use compact paragraphs with hard visual turns."]},
                    "dialogue_ratio": {"guidance": ["Keep dialogue sparse and let silence carry pressure."]},
                },
                "calibration_lines": ["The gate clicked shut like a verdict."],
                "banned_moves": ["Do not copy named-author phrasing or signature expressions."],
            }
        }
        return {
            "contract_version": STYLE_FEATURE_CONTRACT_VERSION,
            "feature_names": list(STYLE_FEATURE_NAMES),
            "example_yaml": yaml.safe_dump(example, allow_unicode=True, sort_keys=False),
        }

    @staticmethod
    def build_profile_from_texts(
        *,
        sample_texts: Iterable[str] = (),
        style_rules: Iterable[str] = (),
        style_observations: Iterable[str] = (),
        calibration_lines: Iterable[str] = (),
        banned_moves: Iterable[str] = (),
    ) -> dict[str, Any] | None:
        source_texts = [
            *list(sample_texts),
            *list(style_rules),
            *list(style_observations),
        ]
        return StyleProfileService.build_profile(
            sample_texts=source_texts,
            calibration_lines=(_TextPayload(text=line) for line in calibration_lines),
            banned_rule_clusters=(_TextPayload(content=line) for line in banned_moves),
        )

    @staticmethod
    def render_profile_yaml(profile: Mapping[str, Any] | None) -> str:
        return yaml.safe_dump(
            {"style_profile": dict(profile) if isinstance(profile, Mapping) else {}},
            allow_unicode=True,
            sort_keys=False,
        )

    @staticmethod
    def parse_profile_yaml(profile_yaml: str) -> dict[str, Any] | None:
        parsed = _parse_structured_profile(_normalize_text(profile_yaml))
        return dict(parsed) if isinstance(parsed, Mapping) else None

    @staticmethod
    def build_profile(
        *,
        sample_texts: Iterable[str] = (),
        style_rules: Iterable[Any] = (),
        style_observations: Iterable[Any] = (),
        calibration_lines: Iterable[Any] = (),
        banned_rule_clusters: Iterable[Any] = (),
        voice_profile: Any | None = None,
    ) -> dict[str, Any] | None:
        feature_guidance = {name: [] for name in STYLE_FEATURE_NAMES}
        calibration_texts = _row_texts(calibration_lines, ("text", "content"))
        banned_moves = _row_texts(banned_rule_clusters, ("content", "text"))

        source_lines = []
        source_lines.extend(_normalize_sample_texts(sample_texts))
        source_lines.extend(_row_texts(style_rules, ("content", "text")))
        source_lines.extend(_row_texts(style_observations, ("text", "content")))
        if voice_profile is not None:
            source_lines.extend(_row_texts((voice_profile,), ("content", "text")))

        if not source_lines and not calibration_texts and not banned_moves:
            return None

        for line in source_lines:
            structured_profile = _parse_structured_profile(line)
            if structured_profile is not None:
                _merge_structured_profile(
                    feature_guidance,
                    structured_profile,
                    calibration_texts=calibration_texts,
                    banned_moves=banned_moves,
                )
                continue

            matched_features = _matched_features(line)
            if not matched_features:
                matched_features = ("rhythm",)
            for feature_name in matched_features:
                if line not in feature_guidance[feature_name]:
                    feature_guidance[feature_name].append(line)

        return {
            "contract_version": STYLE_FEATURE_CONTRACT_VERSION,
            "features": {
                name: {"guidance": feature_guidance[name]}
                for name in STYLE_FEATURE_NAMES
            },
            "calibration_lines": calibration_texts,
            "banned_moves": banned_moves,
        }

    @staticmethod
    def render_profile_digest(profile: Mapping[str, Any]) -> str:
        return json.dumps(profile, ensure_ascii=False, sort_keys=True, indent=2)


class StyleProfileExtractionService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self._prompt_builder = PromptBuilder()

    def extract(self, payload: dict[str, Any]) -> dict[str, Any]:
        if get_settings().llm_enabled:
            return self._extract_with_llm(payload)
        profile = StyleProfileService.build_profile_from_texts(**payload)
        return {
            "profile": profile,
            "profile_yaml": StyleProfileService.render_profile_yaml(profile),
            "source": "offline_deterministic",
            "llm_call_id": None,
        }

    def _extract_with_llm(self, payload: dict[str, Any]) -> dict[str, Any]:
        snapshot = {
            "sample_texts": _coerce_text_list(payload.get("sample_texts")),
            "style_rules": _coerce_text_list(payload.get("style_rules")),
            "style_observations": _coerce_text_list(payload.get("style_observations")),
            "calibration_lines": _coerce_text_list(payload.get("calibration_lines")),
            "banned_moves": _coerce_text_list(payload.get("banned_moves")),
            "contract_version": STYLE_FEATURE_CONTRACT_VERSION,
            "feature_names": list(STYLE_FEATURE_NAMES),
            "safety": {
                "extract_abstract_craft_only": True,
                "do_not_reuse_protected_phrasing": True,
            },
        }
        prompt = self._prompt_builder.build(snapshot, "style_profile_extract")
        bundle_hash = hashlib.sha256(canonical_json(snapshot).encode("utf-8")).hexdigest()
        try:
            result = LLMNodeRunner(self.session).run(
                scene_id="style_profile_extract",
                chapter_id="global",
                bundle_id="style_profile_extract:global",
                bundle_hash=bundle_hash,
                node_id="style_profile_extract",
                step="style_profile_extract",
                prompt=prompt,
                user_prompt=prompt["user_prompt"],
                offline_client_factory=lambda: None,
            )
        except LLMNodeExecutionError as exc:
            raise DomainError(
                "STYLE_PROFILE_EXTRACT_LLM_FAILED",
                exc.message,
                status_code=409,
                details={
                    "llm_call_id": exc.llm_call_id,
                    "node_id": "style_profile_extract",
                    "error_code": exc.error_code,
                    "next_action": "configure_style_profile_extract_route_and_retry",
                    "response_summary": exc.response_summary,
                },
            ) from exc
        profile = _normalize_style_profile_payload(result.response.structured_output or {})
        return {
            "profile": profile,
            "profile_yaml": StyleProfileService.render_profile_yaml(profile),
            "source": "llm",
            "llm_call_id": result.llm_call_id,
        }


class StyleScoreService:
    @staticmethod
    def report_summary(report: Any) -> dict[str, Any] | None:
        payload = _object_payload(report)
        style_score = payload.get("style_score")
        style_dimensions = _list_payload(payload.get("style_dimensions"))
        style_deviations = _list_payload(payload.get("style_deviations"))

        if style_score is None and not style_dimensions and not style_deviations:
            return None
        return {
            "style_score": style_score,
            "style_dimensions": style_dimensions,
            "style_deviations": style_deviations,
        }

    @staticmethod
    def rewrite_brief_entry(report: Any) -> dict[str, Any] | None:
        summary = StyleScoreService.report_summary(report)
        if summary is None:
            return None
        return {"kind": "style_score", **summary}

    @staticmethod
    def summary_from_rewrite_brief(entries: Iterable[Any]) -> dict[str, Any] | None:
        for entry in entries:
            if not isinstance(entry, Mapping):
                continue
            if entry.get("kind") != "style_score":
                continue
            return {
                "style_score": entry.get("style_score"),
                "style_dimensions": _list_payload(entry.get("style_dimensions")),
                "style_deviations": _list_payload(entry.get("style_deviations")),
            }
        return None


def _normalize_style_profile_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    profile_payload = payload.get("style_profile") if isinstance(payload.get("style_profile"), Mapping) else payload
    features_payload = profile_payload.get("features") if isinstance(profile_payload.get("features"), Mapping) else {}
    features: dict[str, dict[str, list[str]]] = {}
    for feature_name in STYLE_FEATURE_NAMES:
        feature_payload = features_payload.get(feature_name) if isinstance(features_payload, Mapping) else {}
        if isinstance(feature_payload, Mapping):
            guidance = feature_payload.get("guidance")
        else:
            guidance = feature_payload
        features[feature_name] = {"guidance": _coerce_text_list(guidance)}
    return {
        "contract_version": str(profile_payload.get("contract_version") or STYLE_FEATURE_CONTRACT_VERSION),
        "features": features,
        "calibration_lines": _coerce_text_list(profile_payload.get("calibration_lines")),
        "banned_moves": _coerce_text_list(profile_payload.get("banned_moves")),
    }


def _row_texts(rows: Iterable[Any], field_names: tuple[str, ...]) -> list[str]:
    texts: list[str] = []
    for row in rows:
        for field_name in field_names:
            value = getattr(row, field_name, None)
            if isinstance(value, str) and value.strip():
                normalized = _normalize_text(value)
                if normalized:
                    texts.append(normalized)
                break
    return texts


def _normalize_sample_texts(sample_texts: Iterable[str]) -> list[str]:
    texts: list[str] = []
    for sample_text in sample_texts:
        if isinstance(sample_text, str) and sample_text.strip():
            normalized = _normalize_text(sample_text)
            if normalized:
                texts.append(normalized)
    return texts


def _parse_structured_profile(text: str) -> Mapping[str, Any] | None:
    for loader in (json.loads, yaml.safe_load):
        try:
            payload = loader(text)
        except Exception:
            continue
        if not isinstance(payload, Mapping):
            continue
        profile = payload.get("style_profile")
        if isinstance(profile, Mapping):
            return profile
        if isinstance(payload.get("features"), Mapping):
            return payload
    return None


def _merge_structured_profile(
    feature_guidance: dict[str, list[str]],
    profile: Mapping[str, Any],
    *,
    calibration_texts: list[str],
    banned_moves: list[str],
) -> None:
    features = profile.get("features")
    if isinstance(features, Mapping):
        for feature_name in STYLE_FEATURE_NAMES:
            feature_payload = features.get(feature_name)
            if isinstance(feature_payload, Mapping):
                guidance = feature_payload.get("guidance")
            else:
                guidance = feature_payload
            for item in _coerce_text_list(guidance):
                _append_unique(feature_guidance[feature_name], item)

    for item in _coerce_text_list(profile.get("calibration_lines")):
        _append_unique(calibration_texts, item)
    for item in _coerce_text_list(profile.get("banned_moves")):
        _append_unique(banned_moves, item)


def _matched_features(line: str) -> tuple[str, ...]:
    lowered = line.lower()
    return tuple(
        feature_name
        for feature_name, keywords in FEATURE_KEYWORDS.items()
        if any(keyword.lower() in lowered for keyword in keywords)
    )


def _coerce_text_list(value: Any) -> list[str]:
    if isinstance(value, str):
        normalized = _normalize_text(value)
        return [normalized] if normalized else []
    if isinstance(value, Iterable) and not isinstance(value, (str, bytes, Mapping)):
        texts = []
        for item in value:
            if isinstance(item, str):
                normalized = _normalize_text(item)
                if normalized:
                    texts.append(normalized)
        return texts
    return []


def _append_unique(items: list[str], item: str) -> None:
    if item not in items:
        items.append(item)


def _object_payload(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    if hasattr(value, "model_dump"):
        payload = value.model_dump(mode="json", exclude_none=True)
        return dict(payload) if isinstance(payload, Mapping) else {}
    return {
        key: getattr(value, key)
        for key in ("style_score", "style_dimensions", "style_deviations")
        if hasattr(value, key)
    }


def _list_payload(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, Iterable) or isinstance(value, (str, bytes, Mapping)):
        return []
    items: list[dict[str, Any]] = []
    for item in value:
        payload = _object_payload(item)
        if payload:
            items.append(payload)
    return items


def _normalize_text(text: str) -> str:
    normalized = normalize(text)
    if not isinstance(normalized, str):
        raise ValueError("text must normalize to a string")
    return normalized


@dataclass(frozen=True, slots=True)
class _TextPayload:
    text: str | None = None
    content: str | None = None
