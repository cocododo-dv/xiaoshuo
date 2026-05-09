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
RUNTIME_MIN_INPUT_BUDGETS = {
    "hard_qc": 3600,
    "soft_qc": 3600,
    "style_draft": 4200,
}
CHARACTER_CONTINUITY_INSTRUCTION = (
    "Preserve character identity and pronoun continuity across the scene. "
    "Do not change a character's gender, role, or name cues from the scene card, POV voice, "
    "relation digest, previous scene memory, or source draft. "
    "When pronouns are ambiguous, repeat the character name."
)
DRAFTING_TEMPLATE_NAMES = {
    "neutral_draft",
    "style_draft",
    "scene_literary_rewrite",
    "near_final_rewrite",
    "project_outline_plan",
    "scene_blueprint",
    "chapter_story_architecture",
    "character_pressure_blueprint",
    "snowflake_generate_logline",
    "snowflake_generate_one_paragraph",
    "snowflake_generate_character_lineup",
    "snowflake_generate_plot_beats",
    "snowflake_generate_scene_plan",
    "snowflake_generate_character_plan",
    "snowflake_workspace_assistant",
    "snowflake_scene_triage_suggest",
}
HARD_QC_TEMPLATE_NAMES = {
    "hard_qc",
    "soft_qc",
    "near_final_acceptance_review",
}
CHAPTER_REVIEW_TEMPLATE_NAMES = {
    "chapter_summary",
    "chapter_near_final_review",
    "writer_chapter_diagnosis",
    "writer_chapter_revision",
    "writer_deep_review",
    "writer_reference_application_review",
}


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
        task_prompt = _append_runtime_template_instruction(template.task_prompt, template.name)
        task_prompt = _append_schema_instruction(task_prompt, structured_schema)
        target_input_tokens = max_input_tokens
        if target_input_tokens is None:
            target_input_tokens = max(template.input_token_budget, RUNTIME_MIN_INPUT_BUDGETS.get(template.name, 0))
        context_budget = apply_context_budget(
            system_prompt=template.system_prompt,
            task_prompt=task_prompt,
            bundle_snapshot=snapshot,
            sections=sections,
            max_input_tokens=target_input_tokens,
            task_kind=_task_kind_for_template(template.name),
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
    if path is None:
        from novel_system.services.system_config import load_active_config_payload

        raw_payload = load_active_config_payload("prompts")
        if raw_payload is None:
            config_path = _default_prompts_config_path()
            try:
                raw_payload = yaml.safe_load(config_path.read_text(encoding="utf-8"))
            except yaml.YAMLError as exc:
                raise PromptConfigurationError("prompts config could not be parsed") from exc
    else:
        config_path = Path(path)
        try:
            raw_payload = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        except yaml.YAMLError as exc:
            raise PromptConfigurationError("prompts config could not be parsed") from exc
    return parse_prompt_templates(raw_payload)


def _task_kind_for_template(template_name: str) -> str:
    if template_name in HARD_QC_TEMPLATE_NAMES:
        return "hard_qc"
    if template_name in CHAPTER_REVIEW_TEMPLATE_NAMES:
        return "chapter_review"
    if template_name in DRAFTING_TEMPLATE_NAMES:
        return "drafting"
    return "default"


def parse_prompt_templates(raw_payload: Any) -> dict[str, PromptTemplate]:
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
    _align_schema_with_runtime_contract(template_name, normalized_schema)
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


def _append_schema_instruction(user_prompt: str, structured_schema: Mapping[str, Any]) -> str:
    required = structured_schema.get("required")
    required_keys = [item for item in required if isinstance(item, str)] if isinstance(required, list) else []
    enum_instruction = _enum_instruction(structured_schema)
    suffix_lines: list[str] = []
    if not required_keys:
        suffix_lines.append("Return only valid JSON. Do not wrap it in markdown fences.")
    else:
        suffix_lines.append(f"Required top-level JSON keys: {', '.join(required_keys)}.")
        if enum_instruction:
            suffix_lines.append(enum_instruction)
        suffix_lines.append("Return only valid JSON. Do not wrap it in markdown fences.")
    return f"{user_prompt}\n" + "\n".join(suffix_lines)


def _append_runtime_template_instruction(user_prompt: str, template_name: str) -> str:
    instructions = {
        "neutral_draft": (
            "Write prose in the same language as the chapter goal and scene card. "
            "If the chapter goal or scene card contains Chinese text, scene_text must be Chinese prose; "
            "do not translate Chinese settings, beats, or required text into English."
        ),
        "style_draft": (
            "Preserve the source draft language; do not translate the scene while styling it. "
            "If the draft or scene card is Chinese, scene_text must remain Chinese prose."
        ),
        "hard_qc": (
            "If the draft under review is Chinese, write issue messages and rewrite_brief in Chinese; "
            "preserve Chinese character names exactly and do not romanize or translate them."
        ),
        "soft_qc": (
            "If the draft under review is Chinese, write issue messages and rewrite_brief in Chinese; "
            "preserve Chinese character names exactly and do not romanize or translate them."
        ),
    }
    instruction = instructions.get(template_name)
    if instruction:
        instruction = f"{instruction} {CHARACTER_CONTINUITY_INSTRUCTION}"
    if not instruction or instruction in user_prompt:
        return user_prompt
    return f"{user_prompt}\n{instruction}"


def _align_schema_with_runtime_contract(template_name: str, schema: dict[str, Any]) -> None:
    if template_name not in {"hard_qc", "soft_qc"}:
        return
    properties = schema.get("properties")
    required = schema.get("required")
    if not isinstance(properties, dict) or not isinstance(required, list):
        return

    if template_name == "hard_qc":
        properties.setdefault("rewrite_brief", {"type": "array", "items": {"type": "string"}})
        if "rewrite_brief" not in required:
            required.append("rewrite_brief")
        _merge_schema_property(
            properties,
            "resolution_code",
            {"enum": ["hard_pass", "hard_fail_partial", "hard_fail_full", "hard_block_human"]},
        )
        _merge_schema_property(
            properties,
            "next_action",
            {"enum": ["pass", "partial_rewrite", "full_rewrite", "human_review_required"]},
        )
        return

    _merge_schema_property(
        properties,
        "resolution_code",
        {"enum": ["soft_pass", "soft_patch", "soft_waive", "soft_block_human"]},
    )
    _merge_schema_property(
        properties,
        "next_action",
        {"enum": ["pass", "patch", "pass_with_notes", "human_review_required"]},
    )


def _merge_schema_property(properties: dict[str, Any], property_name: str, updates: dict[str, Any]) -> None:
    property_schema = properties.get(property_name)
    if isinstance(property_schema, dict):
        property_schema.update(updates)


def _enum_instruction(structured_schema: Mapping[str, Any]) -> str:
    properties = structured_schema.get("properties")
    if not isinstance(properties, Mapping):
        return ""
    instructions: list[str] = []
    for key, property_schema in properties.items():
        if not isinstance(key, str) or not isinstance(property_schema, Mapping):
            continue
        enum_values = property_schema.get("enum")
        if isinstance(enum_values, list) and enum_values and all(isinstance(item, str) for item in enum_values):
            instructions.append(f"{key} must be one of: {', '.join(enum_values)}")
    if not instructions:
        return ""
    return "Allowed JSON enum values: " + "; ".join(instructions) + "."


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
