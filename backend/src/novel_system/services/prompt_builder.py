from __future__ import annotations

import copy
import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import yaml

from novel_system.services.hash_engine import canonical_json, normalize
from novel_system.services.context_budget import (
    CONTINUITY_DROP_ORDER,
    SECTION_SPECS,
    PromptSection as _PromptSection,
    apply_context_budget,
    collect_prompt_sections as _collect_sections,
    estimate_tokens as _estimate_tokens,
)


class PromptConfigurationError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class PromptTemplate:
    name: str
    version: str
    input_token_budget: int
    system_prompt: str
    task_prompt: str
    structured_schema: dict[str, Any]


SUPPORTED_SCHEMA_TYPES = {"object", "array", "string", "number", "integer", "boolean", "null"}


class PromptBuilder:
    def __init__(self, template_path: str | Path | None = None) -> None:
        self._templates = load_prompt_templates(template_path)

    def build(
        self,
        bundle_snapshot: Mapping[str, Any],
        template_name: str,
        *,
        max_input_tokens: int | None = None,
    ) -> dict[str, Any]:
        template = self._templates[template_name]
        snapshot = _normalize_mapping(bundle_snapshot)
        sections = _collect_sections(snapshot)
        structured_schema = _clone_jsonish(template.structured_schema)
        context_budget = apply_context_budget(
            system_prompt=template.system_prompt,
            task_prompt=template.task_prompt,
            bundle_snapshot=snapshot,
            sections=sections,
            max_input_tokens=max_input_tokens or template.input_token_budget,
        )
        budget = context_budget["budget"]
        system_prompt = template.system_prompt
        user_prompt = context_budget["user_prompt"]
        final_estimate = _estimate_tokens(system_prompt) + _estimate_tokens(user_prompt)
        budget["estimated_input_tokens"] = final_estimate
        budget["remaining_input_tokens"] = budget["target_input_tokens"] - final_estimate

        prompt_hash = hashlib.sha256(
            canonical_json(
                {
                    "template_name": template.name,
                    "template_version": template.version,
                    "system_prompt": system_prompt,
                    "user_prompt": user_prompt,
                    "structured_schema": structured_schema,
                }
            ).encode("utf-8")
        ).hexdigest()

        return {
            "template_name": template.name,
            "template_version": template.version,
            "system_prompt": system_prompt,
            "user_prompt": user_prompt,
            "structured_schema": structured_schema,
            "prompt_hash": prompt_hash,
            "token_budget": budget,
            "continuity_warning": context_budget["continuity_warning"],
        }


def load_prompt_templates(path: str | Path | None = None) -> dict[str, PromptTemplate]:
    config_path = Path(path) if path is not None else _default_prompts_config_path()
    try:
        raw_payload = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise PromptConfigurationError("prompts config could not be parsed") from exc
    if not isinstance(raw_payload, dict):
        raise PromptConfigurationError("prompts config must decode to a mapping")

    templates_payload = raw_payload.get("templates")
    if not isinstance(templates_payload, dict):
        raise PromptConfigurationError("prompts config must define a templates mapping")

    templates: dict[str, PromptTemplate] = {}
    for template_name, payload in templates_payload.items():
        if not isinstance(template_name, str):
            raise PromptConfigurationError("template names must be strings")
        templates[template_name] = _load_prompt_template(template_name, payload)
    return templates


def _default_prompts_config_path() -> Path:
    return Path(__file__).resolve().parents[4] / "config" / "prompts.yaml"


def _load_prompt_template(template_name: str, payload: Any) -> PromptTemplate:
    if not isinstance(payload, Mapping):
        raise PromptConfigurationError(f"template {template_name} must be a mapping")

    required_fields = (
        "version",
        "input_token_budget",
        "system_prompt",
        "task_prompt",
        "structured_schema",
    )
    missing_fields = [field for field in required_fields if field not in payload]
    if missing_fields:
        raise PromptConfigurationError(
            f"template {template_name} is missing required fields: {', '.join(missing_fields)}"
        )

    version = _require_string_field(template_name, payload, "version")
    system_prompt = _require_string_field(template_name, payload, "system_prompt")
    task_prompt = _require_string_field(template_name, payload, "task_prompt")
    input_token_budget = _require_positive_int_field(template_name, payload, "input_token_budget")

    structured_schema = payload["structured_schema"]
    if not isinstance(structured_schema, Mapping):
        raise PromptConfigurationError(f"template {template_name}.structured_schema must be a mapping")
    normalized_schema = _normalize_mapping(structured_schema)
    _validate_structured_schema(normalized_schema, f"template {template_name}.structured_schema", top_level=True)

    return PromptTemplate(
        name=template_name,
        version=_normalize_text(version),
        input_token_budget=input_token_budget,
        system_prompt=_normalize_text(system_prompt),
        task_prompt=_normalize_text(task_prompt),
        structured_schema=_clone_jsonish(normalized_schema),
    )


def _require_string_field(template_name: str, payload: Mapping[str, Any], field: str) -> str:
    value = payload[field]
    if not isinstance(value, str):
        raise PromptConfigurationError(f"template {template_name}.{field} must be a string")
    return value


def _require_positive_int_field(template_name: str, payload: Mapping[str, Any], field: str) -> int:
    value = payload[field]
    if isinstance(value, bool) or not isinstance(value, int):
        raise PromptConfigurationError(f"template {template_name}.{field} must be an integer")
    if value <= 0:
        raise PromptConfigurationError(f"template {template_name}.{field} must be greater than 0")
    return value


def _normalize_mapping(payload: Mapping[str, Any]) -> dict[str, Any]:
    normalized = normalize(dict(payload))
    if not isinstance(normalized, dict):
        raise ValueError("payload must normalize to a mapping")
    return normalized


def _normalize_text(text: str) -> str:
    normalized = normalize(text)
    if not isinstance(normalized, str):
        raise ValueError("text must normalize to a string")
    return normalized


def _clone_jsonish(value: Any) -> Any:
    return copy.deepcopy(value)


def _validate_structured_schema(schema: Mapping[str, Any], context: str, *, top_level: bool = False) -> None:
    schema_type = schema.get("type")
    if schema_type is not None and not isinstance(schema_type, str):
        raise PromptConfigurationError(f"{context}.type must be a string")
    if isinstance(schema_type, str) and schema_type not in SUPPORTED_SCHEMA_TYPES:
        raise PromptConfigurationError(f"{context}.type has unsupported value {schema_type}")
    if top_level and schema_type != "object":
        raise PromptConfigurationError(f"{context}.type must be 'object'")

    properties = schema.get("properties")
    if top_level and not isinstance(properties, Mapping):
        raise PromptConfigurationError(f"{context}.properties must be a mapping")
    if properties is not None:
        if not isinstance(properties, Mapping):
            raise PromptConfigurationError(f"{context}.properties must be a mapping")
        for property_name, property_schema in properties.items():
            if not isinstance(property_name, str):
                raise PromptConfigurationError(f"{context}.properties keys must be strings")
            if not isinstance(property_schema, Mapping):
                raise PromptConfigurationError(f"{context}.properties.{property_name} must be a mapping")
            normalized_property_schema = _normalize_mapping(property_schema)
            _validate_structured_schema(normalized_property_schema, f"{context}.properties.{property_name}")

    required = schema.get("required")
    if top_level and not isinstance(required, list):
        raise PromptConfigurationError(f"{context}.required must be a list of strings")
    if required is not None:
        if not isinstance(required, list) or any(not isinstance(item, str) for item in required):
            raise PromptConfigurationError(f"{context}.required must be a list of strings")

    additional_properties = schema.get("additionalProperties")
    if additional_properties is not None and not isinstance(additional_properties, bool):
        raise PromptConfigurationError(f"{context}.additionalProperties must be a boolean")
    if (
        additional_properties is False
        and top_level
        and isinstance(required, list)
        and isinstance(properties, Mapping)
    ):
        undeclared_required = [item for item in required if item not in properties]
        if undeclared_required:
            raise PromptConfigurationError(
                f"{context}.required contains entries not declared in properties: "
                f"{', '.join(undeclared_required)}"
            )

    items = schema.get("items")
    if items is not None:
        if not isinstance(items, Mapping):
            raise PromptConfigurationError(f"{context}.items must be a mapping")
        normalized_items = _normalize_mapping(items)
        _validate_structured_schema(normalized_items, f"{context}.items")
