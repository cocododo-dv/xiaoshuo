from __future__ import annotations

import json
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy.orm import Session

from novel_system.services.errors import DomainError
from novel_system.services.llm_accounting import (
    LLMCallContext,
    execute_accounted_call,
    mark_postprocess_failure,
)
from novel_system.services.llm_client import LLMRequest
from novel_system.services.literary_quality import automated_diagnostic_assessment


DEFAULT_PASS_THRESHOLD = 0.72
DIMENSION_WEIGHTS = {
    "required_terms": 0.16,
    "style_cues": 0.10,
    "banned_terms": 0.10,
    "length": 0.08,
    "character_contradiction": 0.09,
    "dialogue_edge": 0.07,
    "image_necessity": 0.07,
    "ending_drive": 0.08,
    "model_voice": 0.10,
    "expository_dialogue": 0.06,
    "choice_pressure": 0.05,
    "summary_ending": 0.03,
    "image_homogeneity": 0.01,
}


class LiteraryEvalLLMResponseInvalid(DomainError, ValueError):
    """模型返回的 JSON 不满足 literary eval 输出契约。

    同时继承 ValueError:本模块对"值不合法"一贯抛 ValueError,CLI(tools/literary_eval.py)
    与既有调用方按 ValueError 捕获;继承 DomainError 则让 /literary-eval/run 路由走
    错误信封(409 + 字段定位 + llm_call_id),而不是塌成 500 INTERNAL_ERROR。
    """


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
    model_voice_banned_terms: tuple[str, ...]
    expository_dialogue_banned_terms: tuple[str, ...]
    choice_pressure_cues: tuple[str, ...]
    summary_ending_banned_terms: tuple[str, ...]
    image_variety_cues: tuple[str, ...]
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
    automated_assessment: dict[str, Any]


def load_literary_eval_suite(source: str | Path | Mapping[str, Any]) -> LiteraryEvalSuite:
    payload = _load_payload(source)
    suite_id = _require_str(payload, "suite_id")
    pass_threshold = _optional_float(payload, "pass_threshold", DEFAULT_PASS_THRESHOLD)
    description = str(payload.get("description") or "")
    raw_cases = payload.get("cases")
    if not isinstance(raw_cases, Sequence) or isinstance(raw_cases, (str, bytes)) or not raw_cases:
        raise ValueError("literary eval suite must define a non-empty cases list")

    cases = tuple(_load_case(item, suite_threshold=pass_threshold) for item in raw_cases)
    _require_unique_case_ids(cases)
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
        "model_voice": _banned_term_score(text, case.model_voice_banned_terms),
        "expository_dialogue": _banned_term_score(text, case.expository_dialogue_banned_terms),
        "choice_pressure": _term_hit_score(text, case.choice_pressure_cues),
        "summary_ending": _banned_term_score(text, case.summary_ending_banned_terms),
        "image_homogeneity": _term_hit_score(text, case.image_variety_cues),
    }
    raw_score = round(sum(dimensions[key] * weight for key, weight in DIMENSION_WEIGHTS.items()), 4)
    automated_assessment = automated_diagnostic_assessment(
        text,
        raw_diagnostic_score=raw_score,
    )
    score = automated_assessment["score"]
    issues = _score_issues(case, text, dimensions)
    if automated_assessment["evidence_sufficiency"] < 0.5:
        issues.append(
            "insufficient prose evidence: automated cue checks cannot establish literary quality"
        )
    return LiteraryEvalScore(
        score=score,
        passed=score >= case.pass_threshold,
        dimensions=dimensions,
        issues=issues,
        automated_assessment=automated_assessment,
    )


class LiteraryEvalRunner:
    def __init__(
        self,
        suite: LiteraryEvalSuite,
        *,
        generator: Callable[[LiteraryEvalCase], str | Mapping[str, Any]],
        eval_run_id: str | None = None,
    ) -> None:
        _require_unique_case_ids(suite.cases)
        self.suite = suite
        self.generator = generator
        generator_run_id = getattr(generator, "eval_run_id", None)
        if generator_run_id is not None:
            generator_run_id = _require_identifier(
                generator_run_id,
                "generator eval_run_id",
            )
        if eval_run_id is None:
            self.eval_run_id = generator_run_id or new_literary_eval_run_id()
        else:
            runner_run_id = _require_identifier(eval_run_id, "runner eval_run_id")
            if generator_run_id is not None and generator_run_id != runner_run_id:
                raise ValueError(
                    "literary eval eval_run_id mismatch: "
                    f"runner={runner_run_id!r}, generator={generator_run_id!r}"
                )
            self.eval_run_id = runner_run_id

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
                    "diagnostic_passed": score.passed,
                    "human_verified": False,
                    "dimensions": score.dimensions,
                    "issues": score.issues,
                    "automated_assessment": score.automated_assessment,
                    "generation": generation_metadata,
                }
            )

        passed_count = sum(1 for item in case_results if item["passed"])
        mean_score = round(
            sum(float(item["score"]) for item in case_results) / len(case_results),
            4,
        )
        result = {
            "eval_run_id": self.eval_run_id,
            "suite_id": self.suite.suite_id,
            "description": self.suite.description,
            "summary": {
                "case_count": len(case_results),
                "passed_count": passed_count,
                "failed_count": len(case_results) - passed_count,
                "mean_score": mean_score,
                "pass_threshold": self.suite.pass_threshold,
            },
            "evidence_governance": {
                "provenance": "automated_diagnostic",
                "rubric_visibility": "hidden_from_live_generator",
                "policy_evidence_eligible": False,
                "claim": "diagnostic_floor_only",
                "upper_bound_requires": "frozen_hidden_human_evidence",
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
        session: Session,
        eval_run_id: str,
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
        self.session = session
        self.eval_run_id = _require_identifier(eval_run_id, "eval_run_id")
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
        request = self._request(case)
        llm_call_id = _literary_eval_llm_call_id(self.eval_run_id, case.case_id)
        response = execute_accounted_call(
            self.session,
            self.llm_client,
            request,
            LLMCallContext(
                scope_type="literary_eval_case",
                scope_id=f"{self.eval_run_id}:{case.case_id}",
                node_id="literary_eval_live",
                step=f"case:{case.case_id}",
            ),
            llm_call_id=llm_call_id,
        )
        structured_output = response.structured_output or {}
        scene_text = structured_output.get("scene_text")
        if not isinstance(scene_text, str) or not scene_text.strip():
            mark_postprocess_failure(
                self.session,
                llm_call_id,
                error_code="LLM_RESPONSE_INVALID_SCHEMA",
                error_text="literary eval llm response missing scene_text",
            )
            # 与 chapter_plan_llm / snowflake_workspace_llm 的 *_LLM_RESPONSE_INVALID_SCHEMA
            # 同一套 details 形状,前端按 error_code / next_action 统一处理。
            raise LiteraryEvalLLMResponseInvalid(
                "LITERARY_EVAL_LLM_RESPONSE_INVALID_SCHEMA",
                "literary eval llm response missing scene_text",
                status_code=409,
                details={
                    "llm_call_id": llm_call_id,
                    "node_id": "literary_eval_live",
                    "case_id": case.case_id,
                    "error_code": "LLM_RESPONSE_INVALID_SCHEMA",
                    "missing_field": "scene_text",
                    "next_action": "retry_or_adjust_prompt_schema",
                },
            )
        return {
            "generated_text": scene_text.strip(),
            "provider": response.provider,
            "model": response.model,
            "llm_call_id": llm_call_id,
            "provider_request_id": response.request_id,
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
                        "Avoid AI-flavored prose: no summary-style closing sentence, no dialogue that states facts "
                        "both characters already know, no conflict that resolves without cost. "
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


def new_literary_eval_run_id() -> str:
    return f"literary_eval_{uuid.uuid4().hex}"


def _literary_eval_llm_call_id(eval_run_id: str, case_id: str) -> str:
    seed = f"{_require_identifier(eval_run_id, 'eval_run_id')}:{_require_identifier(case_id, 'case_id')}"
    return f"llm_eval_{uuid.uuid5(uuid.NAMESPACE_URL, seed).hex}"


def _require_identifier(value: str, name: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise ValueError(f"literary eval {name} must be a non-empty string")
    return normalized


def _require_unique_case_ids(cases: Sequence[LiteraryEvalCase]) -> None:
    seen: set[str] = set()
    for case in cases:
        if case.case_id in seen:
            raise ValueError(f"literary eval suite duplicate case_id: {case.case_id}")
        seen.add(case.case_id)


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
        model_voice_banned_terms=_text_tuple(case_payload.get("model_voice_banned_terms")),
        expository_dialogue_banned_terms=_text_tuple(case_payload.get("expository_dialogue_banned_terms")),
        choice_pressure_cues=_text_tuple(case_payload.get("choice_pressure_cues")),
        summary_ending_banned_terms=_text_tuple(case_payload.get("summary_ending_banned_terms")),
        image_variety_cues=_text_tuple(case_payload.get("image_variety_cues")),
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
    for cue in case.choice_pressure_cues:
        if cue.lower() not in lowered:
            issues.append(f"missing choice pressure cue: {cue}")
    for cue in case.image_variety_cues:
        if cue.lower() not in lowered:
            issues.append(f"missing image variety cue: {cue}")
    for term in case.banned_terms:
        if term.lower() in lowered:
            issues.append(f"contains banned term: {term}")
    for term in case.model_voice_banned_terms:
        if term.lower() in lowered:
            issues.append(f"contains model voice term: {term}")
    for term in case.expository_dialogue_banned_terms:
        if term.lower() in lowered:
            issues.append(f"contains expository dialogue term: {term}")
    for term in case.summary_ending_banned_terms:
        if term.lower() in lowered:
            issues.append(f"contains summary ending term: {term}")
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
    # Only author-visible task constraints belong in the generation prompt.
    # The scoring cue/banned-term lists are deliberately withheld; exposing
    # them taught the model how to keyword-stuff the evaluator.
    return "\n".join(
        [
            f"Case ID: {case.case_id}",
            f"Title: {case.title}",
            "",
            "## Writing Task",
            case.prompt,
            "",
            "## Explicit Story Requirements",
            f"required story elements: {_joined_terms(case.required_terms)}",
            f"length band: {case.min_chars}-{case.max_chars} characters",
            "",
            "The literary scoring rubric is hidden. Write a coherent scene naturally; do not list or keyword-stuff cues.",
            "",
            "Return JSON exactly like: {\"scene_text\": \"...\"}",
        ]
    )


def _joined_terms(terms: tuple[str, ...]) -> str:
    return "; ".join(terms) if terms else "-"
