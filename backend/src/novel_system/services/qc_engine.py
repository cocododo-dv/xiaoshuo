from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError
from sqlalchemy.orm import Session

from novel_system.contracts.qc import SoftQCOutput
from novel_system.db.models import AttemptTracker, QcReport, SceneCard, SceneRunState
from novel_system.services.context_budget import finalize_request_budget
from novel_system.services.human_review_manager import HumanReviewManager
from novel_system.services.llm_client import LLMClient, LLMRequest, LLMResponse, load_model_routing_config
from novel_system.services.prompt_builder import PromptBuilder
from novel_system.services.qc_validator import QCValidationError, validate_qc_report
from novel_system.services.style_profile import StyleScoreService
from novel_system.services.system_config import load_llm_provider_runtime_configs
from novel_system.settings import get_settings


CONTINUITY_BUDGET_ISSUE_KEY = "continuity_budget_exceeded"
CONTINUITY_BUDGET_MESSAGE = "Prompt still exceeds the safe input budget after deterministic continuity compaction."
CONTINUITY_BUDGET_REWRITE = "Split the scene and retry QC with a smaller continuity scope."
HARD_QC_REQUIRED_ISSUE_KEYS = {"missing_required_text", "missing_hard_constraint"}
HARD_QC_STYLE_ONLY_ISSUE_KEYS = {"style_compliance", "style_rule_violation", "style_profile_drift"}


@dataclass(slots=True)
class HardQcDecision:
    branch: str
    qc_report_id: str
    human_review_event_id: str | None
    resolution_code: str
    next_action: str
    should_continue: bool
    stop_reason: str | None = None


@dataclass(slots=True)
class SoftQcDecision:
    branch: str
    qc_report_id: str
    human_review_event_id: str | None
    resolution_code: str
    next_action: str
    should_continue: bool
    stop_reason: str | None = None


class OfflineHardQcClient:
    def generate(self, request: LLMRequest) -> LLMResponse:
        structured_output = {
            "resolution_code": "hard_pass",
            "pass_flag": True,
            "next_action": "pass",
            "issues": [],
            "rewrite_brief": [],
        }
        return LLMResponse(
            request_id=f"offline_hard_qc_{uuid.uuid4().hex[:8]}",
            provider="offline_deterministic",
            model=request.model,
            text=json.dumps(structured_output),
            structured_output=structured_output,
            response_format=request.response_format,
            raw_response={
                "id": f"offline_hard_qc_{uuid.uuid4().hex[:8]}",
                "model": request.model,
                "usage": {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
                "finish_reason": "offline_fallback",
            },
            usage={"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
            finish_reason="offline_fallback",
        )


class OfflineSoftQcClient:
    def generate(self, request: LLMRequest) -> LLMResponse:
        structured_output = {
            "resolution_code": "soft_pass",
            "pass_flag": True,
            "next_action": "pass",
            "issues": [],
            "rewrite_brief": [],
            "carry_forward_note": False,
            "note_scope": None,
            "carry_note_text": None,
        }
        return LLMResponse(
            request_id=f"offline_soft_qc_{uuid.uuid4().hex[:8]}",
            provider="offline_deterministic",
            model=request.model,
            text=json.dumps(structured_output),
            structured_output=structured_output,
            response_format=request.response_format,
            raw_response={
                "id": f"offline_soft_qc_{uuid.uuid4().hex[:8]}",
                "model": request.model,
                "usage": {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
                "finish_reason": "offline_fallback",
            },
            usage={"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
            finish_reason="offline_fallback",
        )


def _requires_scene_split(continuity_warning: Any) -> bool:
    return isinstance(continuity_warning, dict) and bool(continuity_warning.get("requires_scene_split"))


def _continuity_warning_message(continuity_warning: Any) -> str:
    if isinstance(continuity_warning, dict):
        message = continuity_warning.get("message")
        if isinstance(message, str) and message:
            return message
    return CONTINUITY_BUDGET_MESSAGE


def _continuity_warning_issue_key(continuity_warning: Any) -> str:
    if isinstance(continuity_warning, dict):
        code = continuity_warning.get("code")
        if isinstance(code, str) and code:
            return code
    return CONTINUITY_BUDGET_ISSUE_KEY


def _issue_blob(issues: list[Any], rewrite_brief: list[Any]) -> str:
    parts: list[str] = []
    for issue in issues:
        if isinstance(issue, dict):
            parts.append(str(issue.get("issue_key") or ""))
            parts.append(str(issue.get("message") or ""))
    parts.extend(str(item) for item in rewrite_brief)
    return "\n".join(parts)


def _contains_forbidden_term(forbidden_text: Any, content: str) -> bool:
    if not isinstance(forbidden_text, str) or not forbidden_text.strip():
        return False
    return any(term in content for term in _constraint_terms(forbidden_text))


def _constraint_terms(text: str) -> list[str]:
    return [term.strip() for term in re.split(r"[,，、;；\n]+", text) if len(term.strip()) >= 2]


def _scene_card_source_texts(scene: SceneCard) -> list[str]:
    texts = [scene.must_include_text, scene.hook, scene.exit_change, scene.scene_goal, scene.location]
    beats = scene.beats_json if isinstance(scene.beats_json, list) else []
    texts.extend(item for item in beats if isinstance(item, str))
    return [text for text in texts if isinstance(text, str) and text.strip()]


def _source_field_satisfied(source_text: str, content: str) -> bool:
    source_text = source_text.strip()
    if source_text in content:
        return True
    fragments = _significant_fragments(source_text)
    if not fragments:
        return False
    matched = [fragment for fragment in fragments if fragment in content]
    return len(matched) >= min(2, len(fragments))


def _issue_mentions_source(issue_blob: str, source_text: str) -> bool:
    source_text = source_text.strip()
    if source_text and source_text in issue_blob:
        return True
    return any(fragment in issue_blob for fragment in _significant_fragments(source_text))


def _significant_fragments(text: str) -> list[str]:
    fragments: list[str] = []
    fragments.extend(match.lower() for match in re.findall(r"[A-Za-z0-9][A-Za-z0-9_-]{2,}", text))
    for sequence in re.findall(r"[\u4e00-\u9fff]{3,}", text):
        fragments.extend(sequence[index : index + 3] for index in range(0, max(len(sequence) - 2, 0)))
    seen: set[str] = set()
    unique: list[str] = []
    for fragment in fragments:
        if fragment in seen:
            continue
        seen.add(fragment)
        unique.append(fragment)
    return unique


def _reported_duplicate_appears_once(issue_blob: str, content: str) -> bool:
    quoted = re.findall(r"['‘“\"]([^'’”\"]{3,})['’”\"]", issue_blob)
    return bool(quoted) and all(content.count(fragment) <= 1 for fragment in quoted)


class HardQcEngine:
    def __init__(
        self,
        session: Session,
        *,
        llm_client: Any | None = None,
        human_review_manager: HumanReviewManager | None = None,
    ) -> None:
        self.session = session
        self.prompt_builder = PromptBuilder()
        self.routing_config = load_model_routing_config()
        self.settings = get_settings()
        self._llm_client = llm_client
        self.human_review_manager = human_review_manager or HumanReviewManager(session)

    def evaluate(
        self,
        *,
        scene_id: str,
        bundle: dict[str, Any],
        neutral_draft_row_id: str,
        neutral_content: str,
    ) -> HardQcDecision:
        scene = self.session.get(SceneCard, scene_id)
        state = self.session.get(SceneRunState, scene_id)
        try:
            prompt = self.prompt_builder.build(bundle["snapshot"], "hard_qc")
            final_user_prompt = self._build_user_prompt(prompt["user_prompt"], neutral_content)
            final_budget = finalize_request_budget(
                system_prompt=prompt["system_prompt"],
                user_prompt=final_user_prompt,
                base_budget=prompt["token_budget"],
            )
            prompt["token_budget"] = final_budget["budget"]
            prompt["continuity_warning"] = final_budget["continuity_warning"]
            continuity_warning = prompt.get("continuity_warning")
            if _requires_scene_split(continuity_warning):
                self._clear_downstream_outputs(state)
                return self._human_review_decision(
                    scene=scene,
                    state=state,
                    bundle=bundle,
                    neutral_draft_row_id=neutral_draft_row_id,
                    failure_reason=(
                        "hard_qc prompt exceeded the safe continuity budget after deterministic compaction; "
                        "split the scene before retrying QC."
                    ),
                    trigger_reason="hard_qc_continuity_budget_exceeded",
                    fallback_payload=self._fallback_block_payload(
                        issue_key=_continuity_warning_issue_key(continuity_warning),
                        message=_continuity_warning_message(continuity_warning),
                        rewrite_brief=[CONTINUITY_BUDGET_REWRITE],
                        continuity_warning=continuity_warning,
                    ),
                    continuity_warning=continuity_warning,
                )
            task_config = self.routing_config.node_routing["hard_qc"]
            request = LLMRequest(
                model=task_config.model,
                messages=[
                    {"role": "system", "content": prompt["system_prompt"]},
                    {"role": "user", "content": final_user_prompt},
                ],
                temperature=task_config.temperature,
                max_output_tokens=task_config.max_output_tokens,
                response_format=task_config.response_format,
                provider=task_config.provider,
                node_id="hard_qc",
                provider_id=task_config.provider_id,
                account_id=task_config.account_id,
                reasoning_level=task_config.reasoning_level,
                api_mode=task_config.api_mode,
                credential_mode=task_config.credential_mode,
                provider_options=task_config.provider_options,
                response_schema=_response_schema(prompt),
            )
            response = self._client().generate(request)
            payload = response.structured_output or {}
        except Exception as exc:
            return self._human_review_decision(
                scene=scene,
                state=state,
                bundle=bundle,
                neutral_draft_row_id=neutral_draft_row_id,
                failure_reason=f"hard_qc execution failed before a valid QC payload was produced: {exc}",
                trigger_reason="hard_qc_execution_failed",
                fallback_payload=self._fallback_block_payload(
                    issue_key="hard_qc_execution_failed",
                    message=f"QC execution failed: {exc}",
                ),
            )
        try:
            report = validate_qc_report("hard_qc", payload)
        except (QCValidationError, ValidationError) as exc:
            return self._human_review_decision(
                scene=scene,
                state=state,
                bundle=bundle,
                neutral_draft_row_id=neutral_draft_row_id,
                failure_reason=f"hard_qc validation failed: {exc}",
                trigger_reason="invalid_hard_qc_payload",
                fallback_payload=self._fallback_block_payload(
                    issue_key="invalid_hard_qc_payload",
                    message=f"QC payload validation failed: {exc}",
                ),
            )

        payload = self._apply_deterministic_sanity(scene, neutral_content, report.model_dump())
        report = validate_qc_report("hard_qc", payload)
        payload = report.model_dump()
        qc_report = self._persist_qc_report(
            scene=scene,
            state=state,
            bundle=bundle,
            neutral_draft_row_id=neutral_draft_row_id,
            payload=payload,
        )
        branch = self._branch_for(report.next_action)
        self._apply_issue_tracking(state, payload["issues"])
        self._apply_branch_counters(state, branch)

        circuit_breaker_reason = self._circuit_breaker_reason(state, branch)
        if circuit_breaker_reason is not None:
            return self._escalate_existing_report(
                scene=scene,
                state=state,
                bundle=bundle,
                neutral_draft_row_id=neutral_draft_row_id,
                qc_report=qc_report,
                branch=branch,
                failure_reason=self._failure_reason_for_circuit_breaker(circuit_breaker_reason, branch),
                trigger_reason=circuit_breaker_reason,
            )

        if branch == "human_review_required":
            self._clear_downstream_outputs(state)
            return self._escalate_existing_report(
                scene=scene,
                state=state,
                bundle=bundle,
                neutral_draft_row_id=neutral_draft_row_id,
                qc_report=qc_report,
                branch=branch,
                failure_reason="hard_qc explicitly requested human review before style generation.",
                trigger_reason="hard_qc_requested_human_review",
            )

        if branch == "rewrite_partial":
            self._clear_downstream_outputs(state)
            state.scene_status = "hard_qc_partial_rewrite_required"
        elif branch == "rewrite_full":
            self._clear_downstream_outputs(state)
            state.scene_status = "hard_qc_full_rewrite_required"

        self._record_attempt(
            scene_id=scene.scene_id,
            chapter_id=scene.chapter_id,
            source_bundle_id=bundle["bundle_id"],
            branch=branch,
            qc_report_id=qc_report.qc_report_id,
            resolution_code=qc_report.resolution_code or "",
            next_action=qc_report.next_action or "",
            human_review_event_id=None,
        )
        self.session.flush()
        return HardQcDecision(
            branch=branch,
            qc_report_id=qc_report.qc_report_id,
            human_review_event_id=None,
            resolution_code=qc_report.resolution_code or "",
            next_action=qc_report.next_action or "",
            should_continue=branch == "continue",
        )

    @staticmethod
    def _build_user_prompt(base_prompt: str, neutral_content: str) -> str:
        return f"{base_prompt}\n\n## Draft Under Review\n{neutral_content}".strip()

    @staticmethod
    def _branch_for(next_action: str) -> str:
        return {
            "pass": "continue",
            "partial_rewrite": "rewrite_partial",
            "full_rewrite": "rewrite_full",
            "human_review_required": "human_review_required",
        }[next_action]

    @staticmethod
    def _fallback_block_payload(
        *,
        issue_key: str,
        message: str,
        rewrite_brief: list[str] | None = None,
        continuity_warning: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        issue = {"issue_key": issue_key, "message": message}
        if continuity_warning is not None:
            issue["continuity_warning"] = continuity_warning
        return {
            "resolution_code": "hard_block_human",
            "pass_flag": False,
            "next_action": "human_review_required",
            "issues": [issue],
            "rewrite_brief": rewrite_brief or [],
        }

    @staticmethod
    def _serialize_rewrite_brief(rewrite_brief: list[str]) -> list[dict[str, str]]:
        return [{"instruction": item} for item in rewrite_brief]

    @staticmethod
    def _primary_issue_key(issues: list[dict[str, Any]]) -> str | None:
        for issue in issues:
            issue_key = issue.get("issue_key")
            if isinstance(issue_key, str) and issue_key:
                return issue_key
        return None

    def _apply_deterministic_sanity(self, scene: SceneCard, neutral_content: str, payload: dict[str, Any]) -> dict[str, Any]:
        issues = payload.get("issues")
        if not isinstance(issues, list) or not issues:
            return payload
        rewrite_brief = payload.get("rewrite_brief")
        issue_blob = _issue_blob(issues, rewrite_brief if isinstance(rewrite_brief, list) else [])
        filtered = [
            issue
            for issue in issues
            if not (
                isinstance(issue, dict)
                and self._issue_contradicts_deterministic_scene_card(scene, neutral_content, issue, issue_blob)
            )
        ]
        if len(filtered) == len(issues):
            return payload
        if filtered:
            return {**payload, "issues": filtered}
        return {
            **payload,
            "resolution_code": "hard_pass",
            "pass_flag": True,
            "next_action": "pass",
            "issues": [],
            "rewrite_brief": [],
        }

    def _issue_contradicts_deterministic_scene_card(
        self,
        scene: SceneCard,
        neutral_content: str,
        issue: dict[str, Any],
        issue_blob: str,
    ) -> bool:
        issue_key = str(issue.get("issue_key") or "").strip()
        if issue_key == "forbidden_text":
            return not _contains_forbidden_term(scene.forbidden_text, neutral_content)
        if issue_key in HARD_QC_STYLE_ONLY_ISSUE_KEYS or issue_key.startswith("style_"):
            return True
        if issue_key in HARD_QC_REQUIRED_ISSUE_KEYS:
            return self._source_field_satisfies_reported_issue(scene.must_include_text, neutral_content, issue_blob) or any(
                self._source_field_satisfies_reported_issue(source_text, neutral_content, issue_blob)
                for source_text in _scene_card_source_texts(scene)
            )
        if issue_key == "unsupported_event":
            return any(
                self._source_field_satisfies_reported_issue(source_text, neutral_content, issue_blob)
                for source_text in _scene_card_source_texts(scene)
            )
        if issue_key == "duplicate_text":
            return _reported_duplicate_appears_once(issue_blob, neutral_content)
        return False

    @staticmethod
    def _source_field_satisfies_reported_issue(source_text: Any, neutral_content: str, issue_blob: str) -> bool:
        if not isinstance(source_text, str) or not source_text.strip():
            return False
        return _source_field_satisfied(source_text, neutral_content) and _issue_mentions_source(issue_blob, source_text)

    def _persist_qc_report(
        self,
        *,
        scene: SceneCard,
        state: SceneRunState,
        bundle: dict[str, Any],
        neutral_draft_row_id: str,
        payload: dict[str, Any],
    ) -> QcReport:
        qc_report = QcReport(
            qc_report_id=f"qc_report_{scene.scene_id}_{uuid.uuid4().hex[:12]}",
            scene_id=scene.scene_id,
            chapter_id=scene.chapter_id,
            qc_type="hard_qc",
            source_draft_row_id=neutral_draft_row_id,
            source_bundle_id=bundle["bundle_id"],
            resolution_code=payload["resolution_code"],
            pass_flag=1 if payload["pass_flag"] else 0,
            next_action=payload["next_action"],
            issues_json=payload["issues"],
            rewrite_brief_json=self._serialize_rewrite_brief(payload["rewrite_brief"]),
        )
        self.session.add(qc_report)
        self.session.flush()
        state.current_qc_report_id = qc_report.qc_report_id
        return qc_report

    def _apply_issue_tracking(self, state: SceneRunState, issues: list[dict[str, Any]]) -> None:
        issue_key = self._primary_issue_key(issues)
        if issue_key is None:
            state.repeat_issue_key = None
            state.repeat_issue_count = 0
            return
        if state.repeat_issue_key == issue_key:
            state.repeat_issue_count += 1
        else:
            state.repeat_issue_key = issue_key
            state.repeat_issue_count = 1

    @staticmethod
    def _apply_branch_counters(state: SceneRunState, branch: str) -> None:
        if branch == "rewrite_partial":
            state.hard_partial_rewrite_count += 1
        elif branch == "rewrite_full":
            state.hard_full_rewrite_count += 1

    @staticmethod
    def _circuit_breaker_reason(state: SceneRunState, branch: str) -> str | None:
        if state.repeat_issue_key and state.repeat_issue_count >= 2:
            return "repeat_issue_key_limit"
        if branch == "rewrite_partial" and state.hard_partial_rewrite_count > 2:
            return "hard_partial_rewrite_limit"
        if branch == "rewrite_full" and state.hard_full_rewrite_count > 1:
            return "hard_full_rewrite_limit"
        if state.total_attempt_count >= state.attempt_budget:
            return "attempt_budget_exhausted"
        return None

    @staticmethod
    def _failure_reason_for_circuit_breaker(trigger_reason: str, branch: str) -> str:
        if trigger_reason == "repeat_issue_key_limit":
            return "hard_qc surfaced the same issue key at least twice; human review is required."
        if trigger_reason == "hard_partial_rewrite_limit":
            return "hard_qc exceeded the partial rewrite limit; human review is required."
        if trigger_reason == "hard_full_rewrite_limit":
            return "hard_qc exceeded the full rewrite limit; human review is required."
        if trigger_reason == "attempt_budget_exhausted":
            return "scene generation exhausted the configured total attempt budget; human review is required."
        return f"hard_qc branch {branch} triggered the generation circuit breaker."

    def _record_attempt(
        self,
        *,
        scene_id: str,
        chapter_id: str,
        source_bundle_id: str,
        branch: str,
        qc_report_id: str,
        resolution_code: str,
        next_action: str,
        human_review_event_id: str | None,
    ) -> None:
        self.session.add(
            AttemptTracker(
                scene_id=scene_id,
                chapter_id=chapter_id,
                step="hard_qc",
                status=branch,
                source_bundle_id=source_bundle_id,
                details_json={
                    "qc_report_id": qc_report_id,
                    "resolution_code": resolution_code,
                    "next_action": next_action,
                    "human_review_event_id": human_review_event_id,
                },
            )
        )

    @staticmethod
    def _clear_downstream_outputs(state: SceneRunState) -> None:
        state.current_style_draft_row_id = None
        state.current_final_scene_row_id = None

    def _human_review_decision(
        self,
        *,
        scene: SceneCard,
        state: SceneRunState,
        bundle: dict[str, Any],
        neutral_draft_row_id: str,
        failure_reason: str,
        trigger_reason: str,
        fallback_payload: dict[str, Any],
        continuity_warning: dict[str, Any] | None = None,
    ) -> HardQcDecision:
        qc_report = self._persist_qc_report(
            scene=scene,
            state=state,
            bundle=bundle,
            neutral_draft_row_id=neutral_draft_row_id,
            payload=fallback_payload,
        )
        return self._escalate_existing_report(
            scene=scene,
            state=state,
            bundle=bundle,
            neutral_draft_row_id=neutral_draft_row_id,
            qc_report=qc_report,
            branch="human_review_required",
            failure_reason=failure_reason,
            trigger_reason=trigger_reason,
            continuity_warning=continuity_warning,
        )

    def _escalate_existing_report(
        self,
        *,
        scene: SceneCard,
        state: SceneRunState,
        bundle: dict[str, Any],
        neutral_draft_row_id: str,
        qc_report: QcReport,
        branch: str,
        failure_reason: str,
        trigger_reason: str,
        continuity_warning: dict[str, Any] | None = None,
    ) -> HardQcDecision:
        replay_context = {
            "scene_id": scene.scene_id,
            "chapter_id": scene.chapter_id,
            "source_bundle_id": bundle["bundle_id"],
            "source_bundle_hash": bundle["bundle_snapshot_hash"],
            "neutral_draft_row_id": neutral_draft_row_id,
            "current_qc_report_id": qc_report.qc_report_id,
            "scene_status_before_block": state.scene_status,
            "total_attempt_count": state.total_attempt_count,
        }
        if continuity_warning is not None:
            replay_context["continuity_warning"] = continuity_warning
        event = self.human_review_manager.create_generation_blocker_event(
            scene_id=scene.scene_id,
            chapter_id=scene.chapter_id,
            object_ref=neutral_draft_row_id,
            target_type="scene_draft",
            target_id=neutral_draft_row_id,
            target_ref=f"scene_draft:{neutral_draft_row_id}",
            failure_reason=failure_reason,
            trigger_reason=trigger_reason,
            recommended_action="human_review_required",
            replay_context=replay_context,
        )
        state.current_human_review_event_id = event.event_id
        state.scene_status = "human_review_required"
        self._record_attempt(
            scene_id=scene.scene_id,
            chapter_id=scene.chapter_id,
            source_bundle_id=bundle["bundle_id"],
            branch="human_review_required",
            qc_report_id=qc_report.qc_report_id,
            resolution_code=qc_report.resolution_code or "",
            next_action=qc_report.next_action or "",
            human_review_event_id=event.event_id,
        )
        self.session.flush()
        return HardQcDecision(
            branch="human_review_required",
            qc_report_id=qc_report.qc_report_id,
            human_review_event_id=event.event_id,
            resolution_code=qc_report.resolution_code or "",
            next_action=qc_report.next_action or "",
            should_continue=False,
            stop_reason=trigger_reason,
        )

    def _client(self) -> Any:
        if self._llm_client is not None:
            return self._llm_client
        if not self.settings.llm_enabled:
            return OfflineHardQcClient()
        return LLMClient(
            provider=self.settings.llm_provider,
            base_url=self.settings.llm_base_url,
            api_key=self.settings.llm_api_key,
            timeout_seconds=self.settings.llm_timeout_seconds,
            provider_configs=load_llm_provider_runtime_configs(),
        )


class SoftQcEngine:
    def __init__(
        self,
        session: Session,
        *,
        llm_client: Any | None = None,
        human_review_manager: HumanReviewManager | None = None,
    ) -> None:
        self.session = session
        self.prompt_builder = PromptBuilder()
        self.routing_config = load_model_routing_config()
        self.settings = get_settings()
        self._llm_client = llm_client
        self.human_review_manager = human_review_manager or HumanReviewManager(session)

    def evaluate(
        self,
        *,
        scene_id: str,
        bundle: dict[str, Any],
        source_draft_row_id: str,
        source_draft_content: str,
    ) -> SoftQcDecision:
        scene = self.session.get(SceneCard, scene_id)
        state = self.session.get(SceneRunState, scene_id)
        try:
            prompt = self.prompt_builder.build(bundle["snapshot"], "soft_qc")
            final_user_prompt = self._build_user_prompt(prompt["user_prompt"], source_draft_content)
            final_budget = finalize_request_budget(
                system_prompt=prompt["system_prompt"],
                user_prompt=final_user_prompt,
                base_budget=prompt["token_budget"],
            )
            prompt["token_budget"] = final_budget["budget"]
            prompt["continuity_warning"] = final_budget["continuity_warning"]
            continuity_warning = prompt.get("continuity_warning")
            if _requires_scene_split(continuity_warning):
                self._clear_downstream_outputs(state)
                return self._human_review_decision(
                    scene=scene,
                    state=state,
                    bundle=bundle,
                    source_draft_row_id=source_draft_row_id,
                    failure_reason=(
                        "soft_qc prompt exceeded the safe continuity budget after deterministic compaction; "
                        "split the scene before retrying QC."
                    ),
                    trigger_reason="soft_qc_continuity_budget_exceeded",
                    fallback_payload=self._fallback_block_payload(
                        issue_key=_continuity_warning_issue_key(continuity_warning),
                        message=_continuity_warning_message(continuity_warning),
                        rewrite_brief=[CONTINUITY_BUDGET_REWRITE],
                        continuity_warning=continuity_warning,
                    ),
                    continuity_warning=continuity_warning,
                )
            task_config = self.routing_config.node_routing["soft_qc"]
            request = LLMRequest(
                model=task_config.model,
                messages=[
                    {"role": "system", "content": prompt["system_prompt"]},
                    {"role": "user", "content": final_user_prompt},
                ],
                temperature=task_config.temperature,
                max_output_tokens=task_config.max_output_tokens,
                response_format=task_config.response_format,
                provider=task_config.provider,
                node_id="soft_qc",
                provider_id=task_config.provider_id,
                account_id=task_config.account_id,
                reasoning_level=task_config.reasoning_level,
                api_mode=task_config.api_mode,
                credential_mode=task_config.credential_mode,
                provider_options=task_config.provider_options,
                response_schema=_response_schema(prompt),
            )
            response = self._client().generate(request)
            payload = response.structured_output or {}
        except Exception as exc:
            return self._human_review_decision(
                scene=scene,
                state=state,
                bundle=bundle,
                source_draft_row_id=source_draft_row_id,
                failure_reason=f"soft_qc execution failed before a valid QC payload was produced: {exc}",
                trigger_reason="soft_qc_execution_failed",
                fallback_payload=self._fallback_block_payload(
                    issue_key="soft_qc_execution_failed",
                    message=f"soft QC execution failed: {exc}",
                ),
            )
        try:
            report = validate_qc_report("soft_qc", payload)
        except (QCValidationError, ValidationError) as exc:
            return self._human_review_decision(
                scene=scene,
                state=state,
                bundle=bundle,
                source_draft_row_id=source_draft_row_id,
                failure_reason=f"soft_qc validation failed: {exc}",
                trigger_reason="invalid_soft_qc_payload",
                fallback_payload=self._fallback_block_payload(
                    issue_key="invalid_soft_qc_payload",
                    message=f"soft QC payload validation failed: {exc}",
                ),
            )

        payload = report.model_dump()
        branch = self._branch_for(report.next_action)
        if branch == "patch" and state.soft_patch_count >= 1:
            payload = self._waive_repeat_patch_payload(payload)
            report = validate_qc_report("soft_qc", payload)
            payload = report.model_dump()
            branch = "waive"

        qc_report = self._persist_qc_report(
            scene=scene,
            state=state,
            bundle=bundle,
            source_draft_row_id=source_draft_row_id,
            payload=payload,
        )

        if branch == "human_review_required":
            self._clear_downstream_outputs(state)
            return self._escalate_existing_report(
                scene=scene,
                state=state,
                bundle=bundle,
                source_draft_row_id=source_draft_row_id,
                qc_report=qc_report,
                branch=branch,
                failure_reason="soft_qc explicitly requested human review before finalization.",
                trigger_reason="soft_qc_requested_human_review",
            )

        self._apply_issue_tracking(state, payload["issues"])
        if branch == "patch":
            state.scene_status = "soft_qc_patch_required"
        elif branch == "waive":
            state.scene_status = "soft_qc_passed_with_notes"
        else:
            state.scene_status = "soft_qc_passed"

        self._record_attempt(
            scene_id=scene.scene_id,
            chapter_id=scene.chapter_id,
            source_bundle_id=bundle["bundle_id"],
            source_draft_row_id=source_draft_row_id,
            branch=branch,
            qc_report_id=qc_report.qc_report_id,
            resolution_code=qc_report.resolution_code or "",
            next_action=qc_report.next_action or "",
            human_review_event_id=None,
            rewrite_brief=payload["rewrite_brief"],
        )
        self.session.flush()
        return SoftQcDecision(
            branch=branch,
            qc_report_id=qc_report.qc_report_id,
            human_review_event_id=None,
            resolution_code=qc_report.resolution_code or "",
            next_action=qc_report.next_action or "",
            should_continue=branch in {"continue", "waive"},
        )

    @staticmethod
    def _build_user_prompt(base_prompt: str, draft_content: str) -> str:
        return f"{base_prompt}\n\n## Draft Under Review\n{draft_content}".strip()

    @staticmethod
    def _branch_for(next_action: str) -> str:
        return {
            "pass": "continue",
            "patch": "patch",
            "pass_with_notes": "waive",
            "human_review_required": "human_review_required",
        }[next_action]

    @staticmethod
    def _fallback_block_payload(
        *,
        issue_key: str,
        message: str,
        rewrite_brief: list[str] | None = None,
        continuity_warning: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        issue = {"issue_key": issue_key, "message": message}
        if continuity_warning is not None:
            issue["continuity_warning"] = continuity_warning
        return {
            "resolution_code": "soft_block_human",
            "pass_flag": False,
            "next_action": "human_review_required",
            "issues": [issue],
            "rewrite_brief": rewrite_brief or [],
            "carry_forward_note": False,
            "note_scope": None,
            "carry_note_text": None,
        }

    @staticmethod
    def _waive_repeat_patch_payload(payload: dict[str, Any]) -> dict[str, Any]:
        rewrite_brief = [item for item in payload.get("rewrite_brief", []) if isinstance(item, str) and item.strip()]
        carry_note_text = "Repeated soft QC patch request after one controlled patch pass."
        if rewrite_brief:
            carry_note_text = f"{carry_note_text} Carry forward: {'; '.join(item.strip() for item in rewrite_brief)}"
        return {
            **payload,
            "resolution_code": "soft_waive",
            "pass_flag": True,
            "next_action": "pass_with_notes",
            "carry_forward_note": True,
            "note_scope": "scene_memory",
            "carry_note_text": carry_note_text,
        }

    @staticmethod
    def _serialize_rewrite_brief(report: Any) -> list[dict[str, Any]]:
        entries = [{"instruction": item} for item in report.rewrite_brief]
        if report.resolution_code == "soft_waive" and report.carry_forward_note:
            entries.append(
                {
                    "kind": "carry_forward_note",
                    "note_scope": report.note_scope,
                    "carry_note_text": report.carry_note_text,
                }
            )
        style_entry = StyleScoreService.rewrite_brief_entry(report)
        if style_entry is not None:
            entries.append(style_entry)
        return entries

    @staticmethod
    def _primary_issue_key(issues: list[dict[str, Any]]) -> str | None:
        for issue in issues:
            issue_key = issue.get("issue_key")
            if isinstance(issue_key, str) and issue_key:
                return issue_key
        return None

    def _persist_qc_report(
        self,
        *,
        scene: SceneCard,
        state: SceneRunState,
        bundle: dict[str, Any],
        source_draft_row_id: str,
        payload: dict[str, Any],
    ) -> QcReport:
        report = SoftQCOutput.model_validate(
            {
                **payload,
                "issues": [
                    {
                        "issue_key": issue.get("issue_key", "ok"),
                        "message": issue.get("message", ""),
                    }
                    for issue in payload["issues"]
                ],
            }
        )
        qc_report = QcReport(
            qc_report_id=f"qc_report_{scene.scene_id}_{uuid.uuid4().hex[:12]}",
            scene_id=scene.scene_id,
            chapter_id=scene.chapter_id,
            qc_type="soft_qc",
            source_draft_row_id=source_draft_row_id,
            source_bundle_id=bundle["bundle_id"],
            resolution_code=payload["resolution_code"],
            pass_flag=1 if payload["pass_flag"] else 0,
            next_action=payload["next_action"],
            issues_json=payload["issues"],
            rewrite_brief_json=self._serialize_rewrite_brief(report=report),
        )
        self.session.add(qc_report)
        self.session.flush()
        state.current_qc_report_id = qc_report.qc_report_id
        return qc_report

    def _apply_issue_tracking(self, state: SceneRunState, issues: list[dict[str, Any]]) -> None:
        issue_key = self._primary_issue_key(issues)
        if issue_key is None:
            state.repeat_issue_key = None
            state.repeat_issue_count = 0
            return
        if state.repeat_issue_key == issue_key:
            state.repeat_issue_count += 1
        else:
            state.repeat_issue_key = issue_key
            state.repeat_issue_count = 1

    def _record_attempt(
        self,
        *,
        scene_id: str,
        chapter_id: str,
        source_bundle_id: str,
        source_draft_row_id: str,
        branch: str,
        qc_report_id: str,
        resolution_code: str,
        next_action: str,
        human_review_event_id: str | None,
        rewrite_brief: list[str],
    ) -> None:
        self.session.add(
            AttemptTracker(
                scene_id=scene_id,
                chapter_id=chapter_id,
                step="soft_qc",
                status=branch,
                source_bundle_id=source_bundle_id,
                details_json={
                    "qc_report_id": qc_report_id,
                    "resolution_code": resolution_code,
                    "next_action": next_action,
                    "source_draft_row_id": source_draft_row_id,
                    "human_review_event_id": human_review_event_id,
                    "rewrite_brief": rewrite_brief,
                },
            )
        )

    @staticmethod
    def _clear_downstream_outputs(state: SceneRunState) -> None:
        state.current_style_draft_row_id = None
        state.current_final_scene_row_id = None

    def _human_review_decision(
        self,
        *,
        scene: SceneCard,
        state: SceneRunState,
        bundle: dict[str, Any],
        source_draft_row_id: str,
        failure_reason: str,
        trigger_reason: str,
        fallback_payload: dict[str, Any],
        continuity_warning: dict[str, Any] | None = None,
    ) -> SoftQcDecision:
        qc_report = self._persist_qc_report(
            scene=scene,
            state=state,
            bundle=bundle,
            source_draft_row_id=source_draft_row_id,
            payload=fallback_payload,
        )
        return self._escalate_existing_report(
            scene=scene,
            state=state,
            bundle=bundle,
            source_draft_row_id=source_draft_row_id,
            qc_report=qc_report,
            branch="human_review_required",
            failure_reason=failure_reason,
            trigger_reason=trigger_reason,
            continuity_warning=continuity_warning,
        )

    def _escalate_existing_report(
        self,
        *,
        scene: SceneCard,
        state: SceneRunState,
        bundle: dict[str, Any],
        source_draft_row_id: str,
        qc_report: QcReport,
        branch: str,
        failure_reason: str,
        trigger_reason: str,
        continuity_warning: dict[str, Any] | None = None,
    ) -> SoftQcDecision:
        replay_context = {
            "scene_id": scene.scene_id,
            "chapter_id": scene.chapter_id,
            "source_bundle_id": bundle["bundle_id"],
            "source_bundle_hash": bundle["bundle_snapshot_hash"],
            "source_draft_row_id": source_draft_row_id,
            "current_qc_report_id": qc_report.qc_report_id,
            "scene_status_before_block": state.scene_status,
            "soft_patch_count": state.soft_patch_count,
        }
        if continuity_warning is not None:
            replay_context["continuity_warning"] = continuity_warning
        event = self.human_review_manager.create_generation_blocker_event(
            scene_id=scene.scene_id,
            chapter_id=scene.chapter_id,
            object_ref=source_draft_row_id,
            target_type="scene_draft",
            target_id=source_draft_row_id,
            target_ref=f"scene_draft:{source_draft_row_id}",
            failure_reason=failure_reason,
            trigger_reason=trigger_reason,
            recommended_action="human_review_required",
            replay_context=replay_context,
        )
        state.current_human_review_event_id = event.event_id
        state.scene_status = "human_review_required"
        self._record_attempt(
            scene_id=scene.scene_id,
            chapter_id=scene.chapter_id,
            source_bundle_id=bundle["bundle_id"],
            source_draft_row_id=source_draft_row_id,
            branch="human_review_required",
            qc_report_id=qc_report.qc_report_id,
            resolution_code=qc_report.resolution_code or "",
            next_action=qc_report.next_action or "",
            human_review_event_id=event.event_id,
            rewrite_brief=qc_report.rewrite_brief_json or [],
        )
        self.session.flush()
        return SoftQcDecision(
            branch="human_review_required",
            qc_report_id=qc_report.qc_report_id,
            human_review_event_id=event.event_id,
            resolution_code=qc_report.resolution_code or "",
            next_action=qc_report.next_action or "",
            should_continue=False,
            stop_reason=trigger_reason,
        )

    def _client(self) -> Any:
        if self._llm_client is not None:
            return self._llm_client
        if not self.settings.llm_enabled:
            return OfflineSoftQcClient()
        return LLMClient(
            provider=self.settings.llm_provider,
            base_url=self.settings.llm_base_url,
            api_key=self.settings.llm_api_key,
            timeout_seconds=self.settings.llm_timeout_seconds,
            provider_configs=load_llm_provider_runtime_configs(),
        )


def _response_schema(prompt: dict[str, Any]) -> dict[str, Any]:
    return {"name": str(prompt["template_name"]), "schema": prompt["structured_schema"]}
