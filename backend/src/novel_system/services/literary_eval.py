from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from novel_system.services.llm_client import LLMRequest


DEFAULT_PASS_THRESHOLD = 0.72
DIMENSION_WEIGHTS = {
    "required_terms": 0.24,
    "style_cues": 0.16,
    "banned_terms": 0.18,
    "length": 0.10,
    "character_contradiction": 0.10,
    "dialogue_edge": 0.08,
    "image_necessity": 0.07,
    "ending_drive": 0.07,
}


@dataclass(frozen=True, slots=True)
class LiteraryEvalCase:
    case_id: str
    title: str
    prompt: str
    required_terms: tuple[str, ...]
    style_cues: tuple[str, ...]
    banned_terms: tuple[str, ...]
    character_contradiction_cues: tuple[str, ...]
    dialogue_edge_cues: tuple[str, ...]
    image_necessity_cues: tuple[str, ...]
    ending_drive_cues: tuple[str, ...]
    min_chars: int
    max_chars: int
    pass_threshold: float
    baseline_text: str | None = None


@dataclass(frozen=True, slots=True)
class LiteraryEvalSuite:
    suite_id: str
    cases: tuple[LiteraryEvalCase, ...]
    pass_threshold: float
    description: str = ""


@dataclass(frozen=True, slots=True)
class LiteraryEvalScore:
    score: float
    passed: bool
    dimensions: dict[str, float]
    issues: list[str]


def load_literary_eval_suite(source: str | Path | Mapping[str, Any]) -> LiteraryEvalSuite:
    payload = _load_payload(source)
    suite_id = _require_str(payload, "suite_id")
    pass_threshold = _optional_float(payload, "pass_threshold", DEFAULT_PASS_THRESHOLD)
    description = str(payload.get("description") or "")
    raw_cases = payload.get("cases")
    if not isinstance(raw_cases, Sequence) or isinstance(raw_cases, (str, bytes)) or not raw_cases:
        raise ValueError("literary eval suite must define a non-empty cases list")

    cases = tuple(_load_case(item, suite_threshold=pass_threshold) for item in raw_cases)
    return LiteraryEvalSuite(
        suite_id=suite_id,
        description=description,
        pass_threshold=pass_threshold,
        cases=cases,
    )


def score_literary_case(case: LiteraryEvalCase, generated_text: str) -> LiteraryEvalScore:
    text = generated_text.strip()
    dimensions = {
        "required_terms": _term_hit_score(text, case.required_terms),
        "style_cues": _term_hit_score(text, case.style_cues),
        "banned_terms": _banned_term_score(text, case.banned_terms),
        "length": _length_score(text, min_chars=case.min_chars, max_chars=case.max_chars),
        "character_contradiction": _term_hit_score(text, case.character_contradiction_cues),
        "dialogue_edge": _term_hit_score(text, case.dialogue_edge_cues),
        "image_necessity": _term_hit_score(text, case.image_necessity_cues),
        "ending_drive": _term_hit_score(text, case.ending_drive_cues),
    }
    score = round(sum(dimensions[key] * weight for key, weight in DIMENSION_WEIGHTS.items()), 4)
    issues = _score_issues(case, text, dimensions)
    return LiteraryEvalScore(
        score=score,
        passed=score >= case.pass_threshold,
        dimensions=dimensions,
        issues=issues,
    )


class LiteraryEvalRunner:
    def __init__(
        self,
        suite: LiteraryEvalSuite,
        *,
        generator: Callable[[LiteraryEvalCase], str | Mapping[str, Any]],
    ) -> None:
        self.suite = suite
        self.generator = generator

    def run(self, *, output_path: str | Path | None = None) -> dict[str, Any]:
        case_results = []
        for case in self.suite.cases:
            generated = self.generator(case)
            generated_text, generation_metadata = _generated_text_and_metadata(generated)
            score = score_literary_case(case, generated_text)
            case_results.append(
                {
                    "case_id": case.case_id,
                    "title": case.title,
                    "prompt": case.prompt,
                    "generated_text": generated_text,
                    "score": score.score,
                    "passed": score.passed,
                    "dimensions": score.dimensions,
                    "issues": score.issues,
                    "generation": generation_metadata,
                }
            )

        passed_count = sum(1 for item in case_results if item["passed"])
        mean_score = round(
            sum(float(item["score"]) for item in case_results) / len(case_results),
            4,
        )
        result = {
            "suite_id": self.suite.suite_id,
            "description": self.suite.description,
            "summary": {
                "case_count": len(case_results),
                "passed_count": passed_count,
                "failed_count": len(case_results) - passed_count,
                "mean_score": mean_score,
                "pass_threshold": self.suite.pass_threshold,
            },
            "cases": case_results,
        }
        if output_path is not None:
            path = Path(output_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        return result


class BaselineLiteraryCaseGenerator:
    def __call__(self, case: LiteraryEvalCase) -> dict[str, Any]:
        if not case.baseline_text:
            raise ValueError(f"literary eval case {case.case_id} is missing baseline_text")
        return {
            "generated_text": case.baseline_text,
            "mode": "baseline_text",
        }


class LLMLiteraryCaseGenerator:
    def __init__(
        self,
        llm_client: Any,
        *,
        model: str,
        provider: str = "openai_compatible",
        provider_id: str | None = None,
        account_id: str | None = None,
        reasoning_level: str = "medium",
        api_mode: str = "responses",
        credential_mode: str | None = None,
        provider_options: dict[str, Any] | None = None,
        temperature: float = 0.75,
        max_output_tokens: int = 1200,
    ) -> None:
        self.llm_client = llm_client
        self.model = model
        self.provider = provider
        self.provider_id = provider_id
        self.account_id = account_id
        self.reasoning_level = reasoning_level
        self.api_mode = api_mode
        self.credential_mode = credential_mode
        self.provider_options = provider_options or {}
        self.temperature = temperature
        self.max_output_tokens = max_output_tokens

    def __call__(self, case: LiteraryEvalCase) -> dict[str, Any]:
        response = self.llm_client.generate(self._request(case))
        structured_output = response.structured_output or {}
        scene_text = structured_output.get("scene_text")
        if not isinstance(scene_text, str) or not scene_text.strip():
            raise ValueError("literary eval llm response missing scene_text")
        return {
            "generated_text": scene_text.strip(),
            "provider": response.provider,
            "model": response.model,
            "request_id": response.request_id,
            "usage": response.usage,
            "finish_reason": response.finish_reason,
        }

    def _request(self, case: LiteraryEvalCase) -> LLMRequest:
        return LLMRequest(
            model=self.model,
            provider=self.provider,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are generating original fiction for a style-feature evaluation. "
                        "Do not imitate a living or named author's protected expression. "
                        "Return JSON with one field: scene_text."
                    ),
                },
                {"role": "user", "content": _case_user_prompt(case)},
            ],
            temperature=self.temperature,
            max_output_tokens=self.max_output_tokens,
            response_format="json_object",
            node_id="literary_eval_live",
            provider_id=self.provider_id,
            account_id=self.account_id,
            reasoning_level=self.reasoning_level,  # type: ignore[arg-type]
            api_mode=self.api_mode,  # type: ignore[arg-type]
            credential_mode=self.credential_mode,  # type: ignore[arg-type]
            provider_options=self.provider_options,
        )


def _load_payload(source: str | Path | Mapping[str, Any]) -> dict[str, Any]:
    if isinstance(source, Mapping):
        return dict(source)
    path = Path(source)
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ValueError(f"literary eval suite could not be parsed: {path}") from exc
    if not isinstance(payload, Mapping):
        raise ValueError("literary eval suite must decode to a mapping")
    return dict(payload)


def _load_case(payload: Any, *, suite_threshold: float) -> LiteraryEvalCase:
    if not isinstance(payload, Mapping):
        raise ValueError("literary eval cases must be mappings")
    case_payload = dict(payload)
    min_chars = _optional_int(case_payload, "min_chars", 80)
    max_chars = _optional_int(case_payload, "max_chars", 900)
    if min_chars <= 0 or max_chars < min_chars:
        raise ValueError("literary eval case length bounds are invalid")
    return LiteraryEvalCase(
        case_id=_require_str(case_payload, "case_id"),
        title=_require_str(case_payload, "title"),
        prompt=_require_str(case_payload, "prompt"),
        required_terms=_text_tuple(case_payload.get("required_terms")),
        style_cues=_text_tuple(case_payload.get("style_cues")),
        banned_terms=_text_tuple(case_payload.get("banned_terms")),
        character_contradiction_cues=_text_tuple(case_payload.get("character_contradiction_cues")),
        dialogue_edge_cues=_text_tuple(case_payload.get("dialogue_edge_cues")),
        image_necessity_cues=_text_tuple(case_payload.get("image_necessity_cues")),
        ending_drive_cues=_text_tuple(case_payload.get("ending_drive_cues")),
        min_chars=min_chars,
        max_chars=max_chars,
        pass_threshold=_optional_float(case_payload, "pass_threshold", suite_threshold),
        baseline_text=_optional_str(case_payload, "baseline_text"),
    )


def _require_str(payload: Mapping[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"literary eval field {key} must be a non-empty string")
    return value.strip()


def _optional_float(payload: Mapping[str, Any], key: str, default: float) -> float:
    value = payload.get(key, default)
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"literary eval field {key} must be a number") from exc
    if parsed < 0 or parsed > 1:
        raise ValueError(f"literary eval field {key} must be between 0 and 1")
    return parsed


def _optional_str(payload: Mapping[str, Any], key: str) -> str | None:
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"literary eval field {key} must be a non-empty string")
    return value.strip()


def _optional_int(payload: Mapping[str, Any], key: str, default: int) -> int:
    value = payload.get(key, default)
    if isinstance(value, bool):
        raise ValueError(f"literary eval field {key} must be an integer")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"literary eval field {key} must be an integer") from exc
    return parsed


def _text_tuple(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise ValueError("literary eval term lists must be arrays of strings")
    items = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise ValueError("literary eval term lists must contain non-empty strings")
        items.append(item.strip())
    return tuple(items)


def _term_hit_score(text: str, terms: tuple[str, ...]) -> float:
    if not terms:
        return 1.0
    lowered = text.lower()
    hits = sum(1 for term in terms if term.lower() in lowered)
    return round(hits / len(terms), 4)


def _banned_term_score(text: str, terms: tuple[str, ...]) -> float:
    if not terms:
        return 1.0
    lowered = text.lower()
    hits = sum(1 for term in terms if term.lower() in lowered)
    return 1.0 if hits == 0 else 0.0


def _length_score(text: str, *, min_chars: int, max_chars: int) -> float:
    length = len(text)
    if min_chars <= length <= max_chars:
        return 1.0
    if length < min_chars:
        return round(length / min_chars, 4)
    return round(max_chars / length, 4)


def _score_issues(
    case: LiteraryEvalCase,
    text: str,
    dimensions: Mapping[str, float],
) -> list[str]:
    lowered = text.lower()
    issues: list[str] = []
    for term in case.required_terms:
        if term.lower() not in lowered:
            issues.append(f"missing required term: {term}")
    for cue in case.style_cues:
        if cue.lower() not in lowered:
            issues.append(f"missing style cue: {cue}")
    for cue in case.character_contradiction_cues:
        if cue.lower() not in lowered:
            issues.append(f"missing character contradiction cue: {cue}")
    for cue in case.dialogue_edge_cues:
        if cue.lower() not in lowered:
            issues.append(f"missing dialogue edge cue: {cue}")
    for cue in case.image_necessity_cues:
        if cue.lower() not in lowered:
            issues.append(f"missing image necessity cue: {cue}")
    for cue in case.ending_drive_cues:
        if cue.lower() not in lowered:
            issues.append(f"missing ending drive cue: {cue}")
    for term in case.banned_terms:
        if term.lower() in lowered:
            issues.append(f"contains banned term: {term}")
    if dimensions["length"] < 1.0:
        issues.append(f"outside length band: {len(text)} chars not in {case.min_chars}-{case.max_chars}")
    return issues


def _generated_text_and_metadata(generated: str | Mapping[str, Any]) -> tuple[str, dict[str, Any]]:
    if isinstance(generated, str):
        return generated, {}
    if not isinstance(generated, Mapping):
        raise ValueError("literary eval generator must return text or a mapping")
    text = generated.get("generated_text") or generated.get("scene_text") or generated.get("text")
    if not isinstance(text, str):
        raise ValueError("literary eval generator mapping must include generated_text")
    metadata = {
        key: value
        for key, value in generated.items()
        if key not in {"generated_text", "scene_text", "text"}
    }
    return text, metadata


def _case_user_prompt(case: LiteraryEvalCase) -> str:
    return "\n".join(
        [
            f"Case ID: {case.case_id}",
            f"Title: {case.title}",
            "",
            "## Writing Task",
            case.prompt,
            "",
            "## Evaluation Constraints",
            f"required terms: {_joined_terms(case.required_terms)}",
            f"style cues: {_joined_terms(case.style_cues)}",
            f"character contradiction cues: {_joined_terms(case.character_contradiction_cues)}",
            f"dialogue edge cues: {_joined_terms(case.dialogue_edge_cues)}",
            f"image necessity cues: {_joined_terms(case.image_necessity_cues)}",
            f"ending drive cues: {_joined_terms(case.ending_drive_cues)}",
            f"banned terms: {_joined_terms(case.banned_terms)}",
            f"length band: {case.min_chars}-{case.max_chars} characters",
            "",
            "Return JSON exactly like: {\"scene_text\": \"...\"}",
        ]
    )


def _joined_terms(terms: tuple[str, ...]) -> str:
    return "; ".join(terms) if terms else "-"
