from __future__ import annotations

import json
import time
from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import OperationalError

from novel_system.db.models import (
    AttemptTracker,
    ChapterGoal,
    ChapterState,
    FinalScene,
    GenerationPlanningArtifact,
    HumanReviewEvent,
    LlmCall,
    LlmCallAttempt,
    QcReport,
    RelationProfile,
    RevisionCandidate,
    SceneCard,
    SceneBlueprint,
    SceneDraft,
    SceneRunState,
    VoiceProfile,
    WriterEvaluation,
)
from novel_system.services.errors import DomainError
from novel_system.db.session import SessionLocal
from novel_system.services.llm_client import LLMClient, LLMRequest, LLMResponse
from novel_system.services.llm_task_runner import (
    _execution_owner_lease_seconds,
    LLMNodeExecutionError,
    LLMNodeRunner,
    begin_llm_execution,
    end_llm_execution,
)
from novel_system.services.idempotency import owner_lease_grace_seconds, owner_lease_ttl_seconds
from novel_system.services.orchestrator import Orchestrator
from novel_system.services.near_final import NearFinalPlanningService
from novel_system.services.qc_engine import HardQcEngine, SoftQcEngine
from novel_system.services.qc_engine import SoftQcDecision
from novel_system.services.scene_generation import SceneGenerationService
from novel_system.services.scene_blueprint import SceneBlueprintService
from novel_system.services.scene_run_checkpoint import (
    SceneRunCheckpointService,
    chapter_scene_execution_id,
    idempotency_execution_id,
    scene_job_execution_id,
)


def _state(session, *, scene_id: str = "SC_CHECKPOINT") -> SceneRunState:
    state = SceneRunState(scene_id=scene_id)
    session.add(state)
    session.commit()
    return state


def test_execution_ids_are_stable_at_each_entrypoint() -> None:
    assert idempotency_execution_id("request-123") == "idempotency:request-123"
    assert scene_job_execution_id("scene_job_123") == "scene_job_123"
    assert chapter_scene_execution_id("chapter_job_123", "SC01") == "chapter_job_123:SC01"


def test_same_execution_resumes_after_last_durable_checkpoint(session) -> None:
    _state(session)
    checkpoints = SceneRunCheckpointService(session)

    first = checkpoints.acquire_execution("SC_CHECKPOINT", "idempotency:req-1")
    assert first.resumed is False
    assert first.next_node == "budget_ready"

    checkpoints.save_checkpoint(
        scene_id="SC_CHECKPOINT",
        execution_id="idempotency:req-1",
        node_key="budget_ready",
        artifact_refs={"budget_basis_hash": "sha256:budget"},
    )
    session.commit()

    resumed = checkpoints.acquire_execution("SC_CHECKPOINT", "idempotency:req-1")
    assert resumed.resumed is True
    assert resumed.last_node == "budget_ready"
    assert resumed.next_node == "planning_ready"
    assert resumed.checkpoint_json["artifact_refs"] == {"budget_basis_hash": "sha256:budget"}


def test_active_execution_blocks_competitor_and_terminal_execution_can_be_superseded(session) -> None:
    state = _state(session)
    checkpoints = SceneRunCheckpointService(session)
    checkpoints.acquire_execution(state.scene_id, "exec-a")
    session.commit()

    with pytest.raises(DomainError) as active_error:
        checkpoints.acquire_execution(state.scene_id, "exec-b")
    assert active_error.value.code == "RUN_EXECUTION_IN_PROGRESS"

    checkpoints.mark_failed(state.scene_id, "exec-a")
    session.commit()
    replacement = checkpoints.acquire_execution(state.scene_id, "exec-b")
    assert replacement.resumed is False
    session.commit()

    with pytest.raises(DomainError) as old_retry:
        checkpoints.acquire_execution(state.scene_id, "exec-a")
    assert old_retry.value.code == "RUN_EXECUTION_SUPERSEDED"


def test_concurrent_execution_cas_has_one_winner_and_old_retry_is_read_only(session) -> None:
    state = _state(session, scene_id="SC_EXECUTION_RACE")
    barrier = Barrier(2)

    def _contend(execution_id: str) -> tuple[str, str]:
        contender = SessionLocal()
        try:
            barrier.wait(timeout=5)
            try:
                SceneRunCheckpointService(contender).acquire_execution(state.scene_id, execution_id)
                contender.commit()
                return ("won", execution_id)
            except OperationalError:
                # SQLite may surface the losing simultaneous write as BUSY before
                # the winning commit becomes visible. Re-read after the lock clears;
                # the durable result must still be the execution-owner fence.
                contender.rollback()
                time.sleep(0.05)
                try:
                    SceneRunCheckpointService(contender).acquire_execution(state.scene_id, execution_id)
                    contender.commit()
                    return ("won", execution_id)
                except DomainError as exc:
                    contender.rollback()
                    return (exc.code, execution_id)
            except DomainError as exc:
                contender.rollback()
                return (exc.code, execution_id)
        finally:
            contender.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(_contend, ("exec-race-a", "exec-race-b")))

    winners = [execution_id for outcome, execution_id in outcomes if outcome == "won"]
    losers = [outcome for outcome, _execution_id in outcomes if outcome != "won"]
    assert len(winners) == 1
    assert losers == ["RUN_EXECUTION_IN_PROGRESS"]
    winner = winners[0]

    session.expire_all()
    state = session.get(SceneRunState, state.scene_id)
    assert state is not None
    assert state.active_execution_id == winner
    state.scene_tokens_used = 31
    state.scene_tokens_reserved = 7
    state.provider_attempts_used = 2
    session.flush()
    checkpoints = SceneRunCheckpointService(session)
    checkpoints.save_checkpoint(
        scene_id=state.scene_id,
        execution_id=winner,
        node_key="budget_ready",
        artifact_refs={"budget_basis_hash": "sha256:race"},
    )
    checkpoints.mark_failed(state.scene_id, winner)
    session.commit()

    replacement = "exec-race-next"
    checkpoints.acquire_execution(state.scene_id, replacement)
    session.commit()
    session.refresh(state)
    snapshot = {
        "active_execution_id": state.active_execution_id,
        "run_checkpoint": state.run_checkpoint,
        "run_checkpoint_json": dict(state.run_checkpoint_json or {}),
        "scene_tokens_used": state.scene_tokens_used,
        "scene_tokens_reserved": state.scene_tokens_reserved,
        "provider_attempts_used": state.provider_attempts_used,
    }

    with pytest.raises(DomainError) as old_retry:
        checkpoints.acquire_execution(state.scene_id, winner)
    assert old_retry.value.code == "RUN_EXECUTION_SUPERSEDED"
    session.rollback()
    session.refresh(state)
    assert {
        "active_execution_id": state.active_execution_id,
        "run_checkpoint": state.run_checkpoint,
        "run_checkpoint_json": dict(state.run_checkpoint_json or {}),
        "scene_tokens_used": state.scene_tokens_used,
        "scene_tokens_reserved": state.scene_tokens_reserved,
        "provider_attempts_used": state.provider_attempts_used,
    } == snapshot


def test_selection_resume_checkpoint_handoff_has_one_cas_owner(session) -> None:
    _seed_resume_scene(session)
    scene_id = "CH_RESUME_SC01"
    checkpoints = SceneRunCheckpointService(session)
    old_execution = "idempotency:selection-origin"
    checkpoints.acquire_execution(scene_id, old_execution)
    for node in (
        "budget_ready",
        "planning_ready",
        "bundle_ready",
        "neutral_ready",
        "hard_qc_ready",
        "style_ready",
        "selection_wait",
    ):
        checkpoints.save_checkpoint(
            scene_id=scene_id,
            execution_id=old_execution,
            node_key=node,
            artifact_refs={"selection_context": "durable"} if node == "selection_wait" else None,
        )
    checkpoints.mark_waiting_selection(scene_id, old_execution)
    session.commit()
    barrier = Barrier(2)

    def _resume_contender(execution_id: str) -> tuple[str, str]:
        contender = SessionLocal()
        try:
            barrier.wait(timeout=5)
            try:
                SceneRunCheckpointService(contender).acquire_selection_resume(scene_id, execution_id)
                contender.commit()
                return ("won", execution_id)
            except OperationalError:
                contender.rollback()
                time.sleep(0.05)
                try:
                    SceneRunCheckpointService(contender).acquire_selection_resume(scene_id, execution_id)
                    contender.commit()
                    return ("won", execution_id)
                except DomainError as exc:
                    contender.rollback()
                    return (exc.code, execution_id)
            except DomainError as exc:
                contender.rollback()
                return (exc.code, execution_id)
        finally:
            contender.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(
            pool.map(
                _resume_contender,
                ("idempotency:selection-resume-a", "idempotency:selection-resume-b"),
            )
        )
    winners = [execution_id for outcome, execution_id in outcomes if outcome == "won"]
    assert len(winners) == 1
    assert [outcome for outcome, _ in outcomes if outcome != "won"] == ["RUN_EXECUTION_IN_PROGRESS"]
    winner = winners[0]

    session.expire_all()
    state = session.get(SceneRunState, scene_id)
    assert state.active_execution_id == winner
    assert state.run_execution_status == "active"
    assert state.run_checkpoint == "selection_wait"
    assert state.run_checkpoint_json["execution_id"] == winner
    assert state.run_checkpoint_json["artifact_refs"]["selection_context"] == "durable"
    assert old_execution in state.run_checkpoint_json["superseded_execution_ids"]

    before = dict(state.run_checkpoint_json)
    with pytest.raises(DomainError) as stale_terminal:
        checkpoints.mark_failed(scene_id, old_execution)
    assert stale_terminal.value.code == "RUN_EXECUTION_SUPERSEDED"
    session.rollback()
    session.refresh(state)
    assert state.active_execution_id == winner
    assert state.run_execution_status == "active"
    assert state.run_checkpoint_json == before


def test_checkpoint_rejects_wrong_execution_and_out_of_order_node(session) -> None:
    state = _state(session)
    checkpoints = SceneRunCheckpointService(session)
    checkpoints.acquire_execution(state.scene_id, "exec-a")

    with pytest.raises(DomainError) as wrong_owner:
        checkpoints.save_checkpoint(
            scene_id=state.scene_id,
            execution_id="exec-b",
            node_key="budget_ready",
        )
    assert wrong_owner.value.code == "RUN_EXECUTION_SUPERSEDED"

    with pytest.raises(DomainError) as out_of_order:
        checkpoints.save_checkpoint(
            scene_id=state.scene_id,
            execution_id="exec-a",
            node_key="bundle_ready",
        )
    assert out_of_order.value.code == "RUN_CHECKPOINT_CORRUPT"


def test_cancelled_execution_has_durable_terminal_checkpoint_and_can_be_superseded(session) -> None:
    state = _state(session, scene_id="SC_CANCELLED_CHECKPOINT")
    checkpoints = SceneRunCheckpointService(session)
    checkpoints.acquire_execution(state.scene_id, "exec-cancelled")
    checkpoints.save_checkpoint(
        scene_id=state.scene_id,
        execution_id="exec-cancelled",
        node_key="budget_ready",
        artifact_refs={"scene_token_budget": 100},
    )
    checkpoints.mark_cancelled(state.scene_id, "exec-cancelled")
    session.commit()

    session.refresh(state)
    assert state.run_execution_status == "cancelled"
    assert state.run_checkpoint == "cancelled"
    assert state.run_checkpoint_json["node_key"] == "cancelled"
    assert state.run_checkpoint_json["cancelled_from_node"] == "budget_ready"

    with pytest.raises(DomainError) as same_execution:
        checkpoints.acquire_execution(state.scene_id, "exec-cancelled")
    assert same_execution.value.code == "RUN_EXECUTION_CANCELLED"

    claim = checkpoints.acquire_execution(state.scene_id, "exec-replacement")
    assert claim.resumed is False
    assert claim.last_node is None
    assert "exec-cancelled" in claim.checkpoint_json["superseded_execution_ids"]

    with pytest.raises(DomainError) as stale_owner:
        checkpoints.mark_failed(state.scene_id, "exec-cancelled")
    assert stale_owner.value.code == "RUN_EXECUTION_SUPERSEDED"


def test_settled_or_dispatched_ledger_without_output_is_blocked(session) -> None:
    state = _state(session, scene_id="SC_LEDGER_MISSING")
    state.scene_token_budget = 100
    state.scene_tokens_reserved = 0
    state.scene_tokens_used = 10
    session.add(
        LlmCall(
            llm_call_id="call-settled-missing",
            provider="fake",
            model="fake",
            step="neutral_draft",
            scene_id=state.scene_id,
            scope_type="scene",
            scope_id=state.scene_id,
            execution_id="exec-ledger",
            execution_step_key="neutral_draft",
            estimated_tokens=20,
            reserved_tokens=20,
            budget_charged_tokens=10,
            accounting_status="settled",
            request_dispatched_at="2026-07-13T00:00:00+00:00",
            settled_at="2026-07-13T00:00:01+00:00",
        )
    )
    session.commit()

    with pytest.raises(DomainError) as exc_info:
        SceneRunCheckpointService(session).reconcile_step_output(
            scene_id=state.scene_id,
            execution_id="exec-ledger",
            execution_step_key="neutral_draft",
            output_exists=False,
        )
    assert exc_info.value.code == "RUN_CHECKPOINT_OUTPUT_MISSING"


def test_undispatched_reservation_is_released_for_checkpoint_retry(session) -> None:
    state = _state(session, scene_id="SC_LEDGER_RELEASE")
    state.scene_token_budget = 100
    state.scene_tokens_reserved = 20
    session.add(
        LlmCall(
            llm_call_id="call-reserved-undispatched",
            provider="fake",
            model="fake",
            step="style_draft",
            scene_id=state.scene_id,
            scope_type="scene",
            scope_id=state.scene_id,
            execution_id="exec-ledger",
            execution_step_key="style_draft:1",
            estimated_tokens=20,
            reserved_tokens=20,
            budget_charged_tokens=0,
            accounting_status="reserved",
            request_dispatched_at=None,
        )
    )
    session.add(
        LlmCallAttempt(
            attempt_id="attempt-reserved-undispatched",
            llm_call_id="call-reserved-undispatched",
            provider_attempt_no=0,
            dispatch_kind="initial",
            request_max_output_tokens=10,
            estimated_tokens=20,
            reserved_tokens=20,
            budget_charged_tokens=0,
            accounting_status="reserved",
            request_dispatched_at=None,
        )
    )
    session.commit()

    outcome = SceneRunCheckpointService(session).reconcile_step_output(
        scene_id=state.scene_id,
        execution_id="exec-ledger",
        execution_step_key="style_draft:1",
        output_exists=False,
    )
    session.commit()

    session.refresh(state)
    call = session.get(LlmCall, "call-reserved-undispatched")
    attempt = session.get(LlmCallAttempt, "attempt-reserved-undispatched")
    assert outcome == "retry"
    assert call.accounting_status == "released"
    assert call.reserved_tokens == attempt.reserved_tokens == 20
    assert call.budget_charged_tokens == attempt.budget_charged_tokens == 0
    assert attempt.accounting_status == "released"
    assert attempt.settled_at is not None
    assert state.scene_tokens_reserved == 0


class _CountingGenerationClient:
    def __init__(self) -> None:
        self.requests: list[LLMRequest] = []

    def generate(self, request: LLMRequest) -> LLMResponse:
        self.requests.append(request)
        payload = {"scene_text": f"durable draft {len(self.requests)}"}
        return _response(payload, f"generation-{len(self.requests)}")


class _PlanningCheckpointClient:
    def __init__(self) -> None:
        self.requests: list[LLMRequest] = []

    def generate(self, request: LLMRequest) -> LLMResponse:
        self.requests.append(request)
        if request.node_id == "scene_blueprint":
            payload = {
                "visible_desire": "prove the checkpoint",
                "forced_choice": "continue or retreat",
                "price_paid": "lose time",
                "information_release": "the ledger is durable",
                "relationship_turn": "trust shifts",
                "image_anchor": "a checkpoint lamp",
                "ending_action": "the lamp turns green",
                "next_scene_pull": "what survives the retry",
                "anti_summary_rule": "end on the lamp",
            }
        elif request.node_id == "chapter_story_architecture":
            payload = {"ending_question": "does the checkpoint survive"}
        elif request.node_id == "character_pressure_blueprint":
            payload = {"wrong_belief": "a retry must start over"}
        else:
            raise AssertionError(f"unexpected planning request {request.node_id}")
        return _response(payload, f"planning-{request.node_id}-{len(self.requests)}")


class _FailBundleAfterPlanning:
    def build(self, *args, **kwargs):  # noqa: ANN002, ANN003, ANN201
        raise RuntimeError("stop after planning checkpoint")


def _planning_checkpoint_orchestrator(session, client: _PlanningCheckpointClient) -> Orchestrator:
    orchestrator = Orchestrator(
        session,
        scene_generation_service=_FailBeforeNeutral(),
        planning_service=NearFinalPlanningService(session, llm_client=client),
    )
    orchestrator.scene_blueprint_service = SceneBlueprintService(session, llm_client=client)
    return orchestrator


class _FailSecondCandidateOnceClient(_CountingGenerationClient):
    def generate(self, request: LLMRequest) -> LLMResponse:
        self.requests.append(request)
        if len(self.requests) == 3:
            raise ValueError("candidate two failed once")
        payload = {"scene_text": f"durable draft {len(self.requests)}"}
        return _response(payload, f"generation-{len(self.requests)}")


class _FailDeTemplateClient(_CountingGenerationClient):
    def generate(self, request: LLMRequest) -> LLMResponse:
        self.requests.append(request)
        if request.node_id == "style_patch":
            raise ValueError("de-template provider failed")
        payload = {"scene_text": f"durable draft {len(self.requests)}"}
        return _response(payload, f"generation-{len(self.requests)}")


class _FailFourthGenerationClient(_CountingGenerationClient):
    def generate(self, request: LLMRequest) -> LLMResponse:
        self.requests.append(request)
        if len(self.requests) == 4:
            raise ValueError("next candidate failed after de-template")
        payload = {"scene_text": f"durable draft {len(self.requests)}"}
        return _response(payload, f"generation-{len(self.requests)}")


class _SettledButUnparseableGenerationClient(_CountingGenerationClient):
    def generate(self, request: LLMRequest) -> LLMResponse:
        self.requests.append(request)
        return _response({"unexpected": "provider succeeded without scene_text"}, "generation-unparseable")


class _HardPassClient:
    def generate(self, request: LLMRequest) -> LLMResponse:
        return _response(
            {
                "resolution_code": "hard_pass",
                "pass_flag": True,
                "next_action": "pass",
                "issues": [],
                "rewrite_brief": [],
            },
            "hard-pass",
        )


class _FailAfterStyle:
    def __init__(self) -> None:
        self.calls = 0

    def evaluate(self, **kwargs):  # noqa: ANN003, ANN201
        self.calls += 1
        raise RuntimeError("fail after style checkpoint")


class _UnexpectedHardPromptBuilder:
    def build(self, *args, **kwargs):  # noqa: ANN002, ANN003, ANN201
        raise RuntimeError("unexpected hard QC prompt failure")


class _UnexpectedSoftQcRunner:
    def run(self, *args, **kwargs):  # noqa: ANN002, ANN003, ANN201
        raise RuntimeError("unexpected soft QC runner failure")


class _PassSoftQc:
    def __init__(self, session) -> None:
        self.session = session
        self.calls = 0

    def evaluate(
        self,
        *,
        scene_id,
        bundle,
        source_draft_row_id,
        source_draft_content,
        execution_step_key="soft_qc:0",
    ):  # noqa: ANN001, ANN201
        self.calls += 1
        report_id = f"qc_{scene_id}_soft_resume"
        report = self.session.get(QcReport, report_id)
        if report is None:
            report = QcReport(
                qc_report_id=report_id,
                scene_id=scene_id,
                chapter_id="CH_RESUME",
                qc_type="soft_qc",
                source_draft_row_id=source_draft_row_id,
                source_bundle_id=bundle["bundle_id"],
                resolution_code="soft_pass",
                pass_flag=1,
                next_action="pass",
                issues_json=[],
                rewrite_brief_json=[],
            )
            self.session.add(report)
        state = self.session.get(SceneRunState, scene_id)
        state.current_qc_report_id = report_id
        llm_call_id = f"llm_{scene_id}_{execution_step_key}"
        if self.session.get(LlmCall, llm_call_id) is None:
            self.session.add(
                LlmCall(
                    llm_call_id=llm_call_id,
                    provider="fake",
                    model="fake",
                    step="soft_qc",
                    scene_id=scene_id,
                    chapter_id="CH_RESUME",
                    scope_type="scene",
                    scope_id=scene_id,
                    execution_id=state.active_execution_id,
                    execution_step_key=execution_step_key,
                    estimated_tokens=0,
                    reserved_tokens=0,
                    budget_charged_tokens=0,
                    accounting_status="settled",
                    request_dispatched_at="2026-07-13T00:00:00Z",
                    settled_at="2026-07-13T00:00:01Z",
                )
            )
            self.session.add(
                AttemptTracker(
                    scene_id=scene_id,
                    chapter_id="CH_RESUME",
                    step="soft_qc",
                    status="continue",
                    source_bundle_id=bundle["bundle_id"],
                    details_json={
                        "qc_report_id": report_id,
                        "resolution_code": "soft_pass",
                        "next_action": "pass",
                        "source_draft_row_id": source_draft_row_id,
                        "human_review_event_id": None,
                        "rewrite_brief": [],
                        "llm_call_id": llm_call_id,
                        "execution_step_key": execution_step_key,
                    },
                )
            )
        return SoftQcDecision(
            branch="continue",
            qc_report_id=report_id,
            human_review_event_id=None,
            resolution_code="soft_pass",
            next_action="pass",
            should_continue=True,
            llm_call_id=llm_call_id,
            execution_step_key=execution_step_key,
        )


class _SequencedSoftQc:
    def __init__(self, session, branches: dict[str, str]) -> None:
        self.session = session
        self.branches = branches
        self.calls: list[str] = []

    def evaluate(
        self,
        *,
        scene_id,
        bundle,
        source_draft_row_id,
        source_draft_content,
        execution_step_key="soft_qc:0",
    ):  # noqa: ANN001, ANN201
        del source_draft_content
        self.calls.append(execution_step_key)
        branch = self.branches[execution_step_key]
        values = {
            "patch": ("soft_patch", 0, "patch", [{"instruction": "tighten the checkpoint"}]),
            "continue": ("soft_pass", 1, "pass", []),
            "waive": (
                "soft_waive",
                1,
                "pass_with_notes",
                [{"kind": "carry_forward_note", "note_scope": "scene_memory", "carry_note_text": "keep note"}],
            ),
            "human_review_required": (
                "soft_block_human",
                0,
                "human_review_required",
                [{"instruction": "author must review"}],
            ),
        }
        resolution_code, pass_flag, next_action, rewrite_brief = values[branch]
        suffix = execution_step_key.replace(":", "_")
        report_id = f"qc_{scene_id}_{suffix}"
        llm_call_id = f"llm_{scene_id}_{suffix}"
        state = self.session.get(SceneRunState, scene_id)
        if self.session.get(QcReport, report_id) is None:
            self.session.add(
                QcReport(
                    qc_report_id=report_id,
                    scene_id=scene_id,
                    chapter_id="CH_RESUME",
                    qc_type="soft_qc",
                    source_draft_row_id=source_draft_row_id,
                    source_bundle_id=bundle["bundle_id"],
                    resolution_code=resolution_code,
                    pass_flag=pass_flag,
                    next_action=next_action,
                    issues_json=[],
                    rewrite_brief_json=rewrite_brief,
                )
            )
            self.session.add(
                LlmCall(
                    llm_call_id=llm_call_id,
                    provider="fake",
                    model="fake",
                    step="soft_qc",
                    scene_id=scene_id,
                    chapter_id="CH_RESUME",
                    scope_type="scene",
                    scope_id=scene_id,
                    execution_id=state.active_execution_id,
                    execution_step_key=execution_step_key,
                    estimated_tokens=0,
                    reserved_tokens=0,
                    budget_charged_tokens=0,
                    accounting_status="settled",
                    request_dispatched_at="2026-07-13T00:00:00Z",
                    settled_at="2026-07-13T00:00:01Z",
                )
            )
            self.session.add(
                AttemptTracker(
                    scene_id=scene_id,
                    chapter_id="CH_RESUME",
                    step="soft_qc",
                    status=branch,
                    source_bundle_id=bundle["bundle_id"],
                    details_json={
                        "qc_report_id": report_id,
                        "resolution_code": resolution_code,
                        "next_action": next_action,
                        "source_draft_row_id": source_draft_row_id,
                        "human_review_event_id": None,
                        "rewrite_brief": rewrite_brief,
                        "llm_call_id": llm_call_id,
                        "execution_step_key": execution_step_key,
                    },
                )
            )
        human_review_event_id = f"review_{scene_id}" if branch == "human_review_required" else None
        if human_review_event_id is not None and self.session.get(HumanReviewEvent, human_review_event_id) is None:
            self.session.add(
                HumanReviewEvent(
                    event_id=human_review_event_id,
                    scene_id=scene_id,
                    chapter_id="CH_RESUME",
                    object_ref=source_draft_row_id,
                    event_source="scene_generation",
                    priority="high",
                    status="needs_followup",
                    allowed_actions_json=["inspect"],
                    result_status_map_json={"inspect": "needs_followup"},
                    details_json={
                        "replay_context": {
                            "current_qc_report_id": report_id,
                            "source_draft_row_id": source_draft_row_id,
                            "source_bundle_id": bundle["bundle_id"],
                        }
                    },
                    default_action="inspect",
                )
            )
        state.current_qc_report_id = report_id
        state.current_human_review_event_id = human_review_event_id
        if branch == "human_review_required":
            state.scene_status = "human_review_required"
        return SoftQcDecision(
            branch=branch,
            qc_report_id=report_id,
            human_review_event_id=human_review_event_id,
            resolution_code=resolution_code,
            next_action=next_action,
            should_continue=branch in {"continue", "waive"},
            stop_reason="blocking_soft_qc_issue" if branch == "human_review_required" else None,
            llm_call_id=llm_call_id,
            execution_step_key=execution_step_key,
        )


class _FailNearFinal:
    def __init__(self) -> None:
        self.calls = 0

    def evaluate_scene(self, *args, **kwargs):  # noqa: ANN002, ANN003, ANN201
        self.calls += 1
        raise RuntimeError("fail after soft checkpoint")


class _PassNearFinal:
    def __init__(self, session) -> None:
        self.session = session
        self.calls = 0

    def evaluate_scene(self, *args, **kwargs):  # noqa: ANN002, ANN003, ANN201
        self.calls += 1
        scene_id = args[0]
        bundle = kwargs["bundle"]
        source_draft_row_id = kwargs["source_draft_row_id"]
        execution_step_key = kwargs["execution_step_key"]
        state = self.session.get(SceneRunState, scene_id)
        llm_call_id = f"llm_{scene_id}_{execution_step_key}"
        self.session.add(
            LlmCall(
                llm_call_id=llm_call_id,
                provider="fake",
                model="fake",
                step="near_final_acceptance_review",
                scene_id=scene_id,
                chapter_id="CH_RESUME",
                scope_type="scene",
                scope_id=scene_id,
                execution_id=state.active_execution_id,
                execution_step_key=execution_step_key,
                estimated_tokens=0,
                reserved_tokens=0,
                budget_charged_tokens=0,
                accounting_status="settled",
                request_dispatched_at="2026-07-13T00:00:00Z",
                settled_at="2026-07-13T00:00:01Z",
            )
        )
        self.session.add(
            WriterEvaluation(
                evaluation_id="near-final-resume-eval",
                object_type="scene",
                object_id=scene_id,
                chapter_id="CH_RESUME",
                scene_id=scene_id,
                rubric_id="near_final_acceptance_v1",
                source_text_ref=f"source_draft:{source_draft_row_id}",
                source_bundle_id=bundle["bundle_id"],
                evaluator_llm_call_id=llm_call_id,
                lens="near_final_acceptance",
                overall_score=1.0,
                scores_json={},
                findings_json=[],
                revision_brief_json=[],
                status="completed",
            )
        )
        self.session.add(
            AttemptTracker(
                scene_id=scene_id,
                chapter_id="CH_RESUME",
                step="near_final_acceptance_review",
                status="near_final_ready",
                source_bundle_id=bundle["bundle_id"],
                details_json={
                    "evaluation_id": "near-final-resume-eval",
                    "revision_candidate_id": None,
                    "source_draft_row_id": source_draft_row_id,
                    "llm_call_id": llm_call_id,
                    "failure_class": None,
                    "execution_step_key": execution_step_key,
                },
            )
        )
        return {
            "near_final_status": "near_final_ready",
            "pass_flag": True,
            "overall_score": 1.0,
            "failure_class": None,
            "requires_human_review": False,
            "evaluation_id": "near-final-resume-eval",
            "revision_candidate_id": None,
            "should_rewrite": False,
            "findings": [],
            "revision_brief": [],
        }


class _SequencedNearFinal:
    def __init__(self, session, outcomes: dict[str, str]) -> None:
        self.session = session
        self.outcomes = outcomes
        self.calls: list[str] = []

    def evaluate_scene(self, *args, **kwargs):  # noqa: ANN002, ANN003, ANN201
        scene_id = args[0]
        bundle = kwargs["bundle"]
        source_draft_row_id = kwargs["source_draft_row_id"]
        source_content = kwargs["source_content"]
        execution_step_key = kwargs["execution_step_key"]
        self.calls.append(execution_step_key)
        outcome = self.outcomes[execution_step_key]
        suffix = execution_step_key.replace(":", "_")
        evaluation_id = f"near_final_eval_{scene_id}_{suffix}"
        llm_call_id = f"llm_{scene_id}_{suffix}"
        candidate_id = None if outcome == "pass" else f"revision_{scene_id}_{suffix}"
        if outcome == "pass":
            near_final_status = "near_final_ready"
            pass_flag = True
            failure_class = None
            requires_human_review = False
            should_rewrite = False
            findings = []
            revision_brief = []
            overall_score = 0.9
        else:
            near_final_status = "human_review_required" if outcome == "human" else "revision_required"
            pass_flag = False
            failure_class = "reference_safety" if outcome == "human" else "prose_model_voice"
            requires_human_review = outcome == "human"
            should_rewrite = outcome == "rewrite"
            findings = [{"dimension": "prose_freshness", "issue": "needs revision"}]
            revision_brief = [{"dimension": "prose_freshness", "action": "rewrite once"}]
            overall_score = 0.5
        state = self.session.get(SceneRunState, scene_id)
        self.session.add(
            LlmCall(
                llm_call_id=llm_call_id,
                provider="fake",
                model="fake",
                step="near_final_acceptance_review",
                scene_id=scene_id,
                chapter_id="CH_RESUME",
                scope_type="scene",
                scope_id=scene_id,
                execution_id=state.active_execution_id,
                execution_step_key=execution_step_key,
                estimated_tokens=0,
                reserved_tokens=0,
                budget_charged_tokens=0,
                accounting_status="settled",
                request_dispatched_at="2026-07-13T00:00:00Z",
                settled_at="2026-07-13T00:00:01Z",
            )
        )
        self.session.add(
            WriterEvaluation(
                evaluation_id=evaluation_id,
                object_type="scene",
                object_id=scene_id,
                chapter_id="CH_RESUME",
                scene_id=scene_id,
                rubric_id="near_final_acceptance_v1",
                source_text_ref=f"source_draft:{source_draft_row_id}",
                source_bundle_id=bundle["bundle_id"],
                evaluator_llm_call_id=llm_call_id,
                lens="near_final_acceptance",
                overall_score=overall_score,
                scores_json={"prose_freshness": overall_score},
                findings_json=findings,
                failure_class=failure_class,
                auto_rewrite_eligible=1 if should_rewrite else 0,
                contract_field_refs_json={},
                promotion_blockers_json=[] if should_rewrite or pass_flag else [failure_class],
                revision_brief_json=revision_brief,
                requires_human_review=1 if requires_human_review else 0,
                status="completed",
            )
        )
        if candidate_id is not None:
            self.session.add(
                RevisionCandidate(
                    revision_id=candidate_id,
                    evaluation_id=evaluation_id,
                    object_type="scene",
                    object_id=scene_id,
                    chapter_id="CH_RESUME",
                    scene_id=scene_id,
                    revision_type="near_final_scene_rewrite",
                    source_text_ref=f"source_draft:{source_draft_row_id}",
                    proposed_text=source_content,
                    instruction_json=revision_brief,
                    diff_summary_json={"failure_class": failure_class},
                    patches_json=[],
                    apply_mode="manual_or_regenerate",
                    target_text_ref=f"source_draft:{source_draft_row_id}",
                    status="candidate",
                    created_by="near_final_acceptance",
                )
            )
        if outcome == "pass":
            for candidate in self.session.execute(
                select(RevisionCandidate).where(
                    RevisionCandidate.scene_id == scene_id,
                    RevisionCandidate.status == "candidate",
                )
            ).scalars().all():
                candidate.status = "superseded"
        self.session.add(
            AttemptTracker(
                scene_id=scene_id,
                chapter_id="CH_RESUME",
                step="near_final_acceptance_review",
                status=near_final_status,
                source_bundle_id=bundle["bundle_id"],
                details_json={
                    "evaluation_id": evaluation_id,
                    "revision_candidate_id": candidate_id,
                    "source_draft_row_id": source_draft_row_id,
                    "llm_call_id": llm_call_id,
                    "failure_class": failure_class,
                    "execution_step_key": execution_step_key,
                },
            )
        )
        return {
            "near_final_status": near_final_status,
            "pass_flag": pass_flag,
            "overall_score": overall_score,
            "scores": {"prose_freshness": overall_score},
            "failure_class": failure_class,
            "requires_human_review": requires_human_review,
            "evaluation_id": evaluation_id,
            "revision_candidate_id": candidate_id,
            "should_rewrite": should_rewrite,
            "findings": findings,
            "revision_brief": revision_brief,
        }


class _FailArchiveOnce:
    def archive_final_scene(self, *args, **kwargs):  # noqa: ANN002, ANN003, ANN201
        raise RuntimeError("fail after near-final checkpoint")


class _FailBeforeNeutral:
    def generate_neutral_draft(self, *args, **kwargs):  # noqa: ANN002, ANN003, ANN201
        raise RuntimeError("stop at bundle checkpoint")


class _FailBeforeHardQc:
    def evaluate(self, *args, **kwargs):  # noqa: ANN002, ANN003, ANN201
        raise RuntimeError("stop after neutral retry")


def _response(payload: dict, request_id: str) -> LLMResponse:
    return LLMResponse(
        request_id=request_id,
        provider="fake-provider",
        model="fake-model",
        text=json.dumps(payload),
        structured_output=payload,
        response_format="json_object",
        raw_response={
            "id": request_id,
            "model": "fake-model",
            "usage": {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
            "finish_reason": "stop",
        },
        usage={"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
        finish_reason="stop",
    )


def _seed_resume_scene(session) -> None:
    session.add(ChapterGoal(chapter_id="CH_RESUME", planned_scene_count=1, chapter_goal="resume safely"))
    session.add(ChapterState(chapter_id="CH_RESUME", current_phase="drafting"))
    session.add(
        SceneCard(
            scene_id="CH_RESUME_SC01",
            chapter_id="CH_RESUME",
            scene_seq=1,
            pov_character_id="CHAR_A",
            onstage_chars_json=["CHAR_A", "CHAR_B"],
            location="checkpoint room",
            scene_goal="prove the checkpoint",
            beats_json=["write", "fail", "resume"],
            must_include_text="",
            target_length_band="short",
            scene_type="transition",
            is_chapter_last=0,
        )
    )
    session.add(SceneRunState(scene_id="CH_RESUME_SC01", scene_status="ready"))
    session.add(
        VoiceProfile(
            row_id="voice_resume_v1",
            voice_profile_id="VOICE_CHAR_A",
            version=1,
            character_id="CHAR_A",
            content="concise",
            active_flag=1,
        )
    )
    session.add(
        RelationProfile(
            row_id="relation_resume_v1",
            relation_profile_id="REL_CHAR_A_CHAR_B",
            left_character_id="CHAR_A",
            right_character_id="CHAR_B",
            version=1,
            content="uneasy allies",
            active_flag=1,
        )
    )
    session.commit()


def _select_first_checkpoint_candidate(session, scene_id: str) -> tuple[str, str]:
    gate = session.execute(
        select(HumanReviewEvent)
        .where(
            HumanReviewEvent.scene_id == scene_id,
            HumanReviewEvent.event_source == "candidate_selection",
        )
        .order_by(HumanReviewEvent.created_at.desc(), HumanReviewEvent.event_id.desc())
    ).scalars().first()
    assert gate is not None
    details = dict(gate.details_json or {})
    selected_row_id = details["candidate_row_ids"][0]
    gate.details_json = {
        **details,
        "decision_status": "selected",
        "selected_row_id": selected_row_id,
    }
    state = session.get(SceneRunState, scene_id)
    state.current_style_draft_row_id = selected_row_id
    state.latest_valid_draft_row_id = selected_row_id
    session.commit()
    return gate.event_id, selected_row_id


def _selection_resume_orchestrator(
    session,
    *,
    generation_client,
    soft_qc,
    near_final,
) -> Orchestrator:
    return Orchestrator(
        session,
        scene_generation_service=SceneGenerationService(session, llm_client=generation_client),
        hard_qc_engine=HardQcEngine(session, llm_client=_HardPassClient()),
        soft_qc_engine=soft_qc,
        near_final_service=near_final,
    )


def test_unexpected_hard_qc_prompt_failure_is_fail_closed_without_report_or_checkpoint(session) -> None:
    _seed_resume_scene(session)
    generation_client = _CountingGenerationClient()
    hard_qc = HardQcEngine(session, llm_client=_HardPassClient())
    hard_qc.prompt_builder = _UnexpectedHardPromptBuilder()

    with pytest.raises(RuntimeError, match="unexpected hard QC prompt failure"):
        Orchestrator(
            session,
            scene_generation_service=SceneGenerationService(session, llm_client=generation_client),
            hard_qc_engine=hard_qc,
            soft_qc_engine=_FailAfterStyle(),
        ).run_scene("CH_RESUME_SC01", execution_id="idempotency:hard-qc-unexpected")

    state = session.get(SceneRunState, "CH_RESUME_SC01")
    assert state.run_checkpoint == "neutral_ready"
    assert "qc_report_id" not in (state.run_checkpoint_json.get("artifact_refs") or {})
    assert session.scalar(
        select(func.count()).select_from(QcReport).where(
            QcReport.scene_id == "CH_RESUME_SC01",
            QcReport.qc_type == "hard_qc",
        )
    ) == 0
    assert session.scalar(
        select(func.count()).select_from(LlmCall).where(
            LlmCall.scene_id == "CH_RESUME_SC01",
            LlmCall.step == "hard_qc",
        )
    ) == 0
    assert len(generation_client.requests) == 1


def test_unexpected_soft_qc_runner_failure_is_fail_closed_without_report_checkpoint(session) -> None:
    _seed_resume_scene(session)
    generation_client = _CountingGenerationClient()
    soft_qc = SoftQcEngine(session, llm_runner=_UnexpectedSoftQcRunner())

    with pytest.raises(RuntimeError, match="unexpected soft QC runner failure"):
        Orchestrator(
            session,
            scene_generation_service=SceneGenerationService(session, llm_client=generation_client),
            hard_qc_engine=HardQcEngine(session, llm_client=_HardPassClient()),
            soft_qc_engine=soft_qc,
            near_final_service=_FailNearFinal(),
        ).run_scene("CH_RESUME_SC01", execution_id="idempotency:soft-qc-unexpected")

    state = session.get(SceneRunState, "CH_RESUME_SC01")
    assert state.run_checkpoint == "soft_qc_ready"
    assert state.run_checkpoint_json["sub_index"] == 0
    refs = state.run_checkpoint_json.get("artifact_refs") or {}
    assert "soft_qc_report_id" not in refs
    assert "soft_qc_llm_call_id" not in refs
    assert session.scalar(
        select(func.count()).select_from(QcReport).where(
            QcReport.scene_id == "CH_RESUME_SC01",
            QcReport.qc_type == "soft_qc",
        )
    ) == 0
    assert session.scalar(
        select(func.count()).select_from(LlmCall).where(
            LlmCall.scene_id == "CH_RESUME_SC01",
            LlmCall.step == "soft_qc",
        )
    ) == 0
    assert len(generation_client.requests) == 2


def test_failure_audit_snapshot_fault_persists_unrecoverable_fence_in_file_database(session) -> None:
    _seed_resume_scene(session)
    scene_id = "CH_RESUME_SC01"
    execution_id = "idempotency:audit-snapshot-fault"
    generation_client = _CountingGenerationClient()
    late_failure = _FailAfterStyle()
    first = Orchestrator(
        session,
        scene_generation_service=SceneGenerationService(session, llm_client=generation_client),
        hard_qc_engine=HardQcEngine(session, llm_client=_HardPassClient()),
        soft_qc_engine=late_failure,
    )

    def fail_snapshot(*_args, **_kwargs):  # noqa: ANN002, ANN003, ANN202
        raise RuntimeError("failure audit snapshot exploded")

    first._capture_failure_audits = fail_snapshot
    with pytest.raises(RuntimeError, match="fail after style checkpoint"):
        first.run_scene(scene_id, execution_id=execution_id)

    verifier = SessionLocal()
    try:
        state = verifier.get(SceneRunState, scene_id)
        assert state is not None
        assert state.active_execution_id == execution_id
        assert state.run_execution_status == "cancelled"
        assert state.run_checkpoint == "cancelled"
        fence = state.run_checkpoint_json["unrecoverable_failure_audit"]
        assert fence["phase"] == "snapshot"
        assert fence["error_type"] == "RuntimeError"
    finally:
        verifier.close()

    provider_calls = len(generation_client.requests)
    session.expire_all()
    with pytest.raises(DomainError) as retry:
        Orchestrator(
            session,
            scene_generation_service=SceneGenerationService(session, llm_client=generation_client),
            hard_qc_engine=HardQcEngine(session, llm_client=_HardPassClient()),
            soft_qc_engine=late_failure,
        ).run_scene(scene_id, execution_id=execution_id)
    assert retry.value.code == "RUN_EXECUTION_CANCELLED"
    assert len(generation_client.requests) == provider_calls


def test_selection_resume_audit_restore_fault_persists_unrecoverable_fence_in_file_database(session) -> None:
    _seed_resume_scene(session)
    scene_id = "CH_RESUME_SC01"
    scene = session.get(SceneCard, scene_id)
    scene.constraint_intensity = 0.9
    session.commit()
    generation_client = _CountingGenerationClient()
    soft_qc = _PassSoftQc(session)
    failing_near_final = _FailNearFinal()
    paused = _selection_resume_orchestrator(
        session,
        generation_client=generation_client,
        soft_qc=soft_qc,
        near_final=failing_near_final,
    ).run_scene(scene_id, execution_id="idempotency:audit-restore-origin")
    assert paused["scene_status"] == "awaiting_candidate_selection"
    _select_first_checkpoint_candidate(session, scene_id)
    execution_id = "idempotency:audit-restore-resume"
    first = _selection_resume_orchestrator(
        session,
        generation_client=generation_client,
        soft_qc=soft_qc,
        near_final=failing_near_final,
    )

    def fail_restore(*_args, **_kwargs):  # noqa: ANN002, ANN003, ANN202
        raise RuntimeError("failure audit restore exploded")

    first._restore_failure_audits = fail_restore
    with pytest.raises(RuntimeError, match="fail after soft checkpoint"):
        first.resume_after_selection(scene_id, execution_id=execution_id)

    verifier = SessionLocal()
    try:
        state = verifier.get(SceneRunState, scene_id)
        assert state is not None
        assert state.active_execution_id == execution_id
        assert state.run_execution_status == "cancelled"
        assert state.run_checkpoint == "cancelled"
        fence = state.run_checkpoint_json["unrecoverable_failure_audit"]
        assert fence["phase"] == "restore"
        assert fence["error_type"] == "RuntimeError"
    finally:
        verifier.close()

    provider_calls = len(generation_client.requests)
    soft_calls = soft_qc.calls
    near_calls = failing_near_final.calls
    session.expire_all()
    with pytest.raises(DomainError) as retry:
        _selection_resume_orchestrator(
            session,
            generation_client=generation_client,
            soft_qc=soft_qc,
            near_final=failing_near_final,
        ).resume_after_selection(scene_id, execution_id=execution_id)
    assert retry.value.code == "RUN_EXECUTION_CANCELLED"
    assert len(generation_client.requests) == provider_calls
    assert soft_qc.calls == soft_calls
    assert failing_near_final.calls == near_calls


def test_selection_resume_same_execution_continues_after_complete_soft_subcursor(session) -> None:
    _seed_resume_scene(session)
    scene_id = "CH_RESUME_SC01"
    scene = session.get(SceneCard, scene_id)
    scene.constraint_intensity = 0.9
    session.commit()
    generation_client = _CountingGenerationClient()
    soft_qc = _PassSoftQc(session)
    failing_near_final = _FailNearFinal()
    origin = _selection_resume_orchestrator(
        session,
        generation_client=generation_client,
        soft_qc=soft_qc,
        near_final=failing_near_final,
    )
    paused = origin.run_scene(scene_id, execution_id="idempotency:selection-soft-origin")
    assert paused["scene_status"] == "awaiting_candidate_selection"
    gate_id, selected_row_id = _select_first_checkpoint_candidate(session, scene_id)
    resume_execution_id = "idempotency:selection-soft-resume"

    with pytest.raises(RuntimeError, match="fail after soft checkpoint"):
        _selection_resume_orchestrator(
            session,
            generation_client=generation_client,
            soft_qc=soft_qc,
            near_final=failing_near_final,
        ).resume_after_selection(scene_id, execution_id=resume_execution_id)

    state = session.get(SceneRunState, scene_id)
    assert state.run_execution_status == "failed"
    assert state.run_checkpoint == "soft_qc_ready"
    assert state.run_checkpoint_json["sub_index"] == 3
    handoff_refs = state.run_checkpoint_json["artifact_refs"]
    gate = session.get(HumanReviewEvent, gate_id)
    assert handoff_refs["selected_row_id"] == selected_row_id
    assert gate.status == "resolved"
    assert gate.details_json["resumed"] is True
    assert handoff_refs["soft_input_source_draft_row_id"] == selected_row_id
    provider_calls = len(generation_client.requests)
    style_call_ids = list(
        session.execute(
            select(LlmCall.llm_call_id)
            .where(LlmCall.scene_id == scene_id, LlmCall.step.in_(("style_draft", "de_template")))
            .order_by(LlmCall.llm_call_id)
        ).scalars()
    )

    result = _selection_resume_orchestrator(
        session,
        generation_client=generation_client,
        soft_qc=soft_qc,
        near_final=_PassNearFinal(session),
    ).resume_after_selection(scene_id, execution_id=resume_execution_id)

    assert result["scene_status"] == "archived"
    assert soft_qc.calls == 1
    assert len(generation_client.requests) == provider_calls
    assert list(
        session.execute(
            select(LlmCall.llm_call_id)
            .where(LlmCall.scene_id == scene_id, LlmCall.step.in_(("style_draft", "de_template")))
            .order_by(LlmCall.llm_call_id)
        ).scalars()
    ) == style_call_ids
    assert session.scalar(
        select(func.count()).select_from(HumanReviewEvent).where(
            HumanReviewEvent.scene_id == scene_id,
            HumanReviewEvent.event_source == "candidate_selection",
        )
    ) == 1
    assert session.get(HumanReviewEvent, gate_id).details_json["resumed"] is True


def test_selection_resume_same_execution_continues_after_partial_near_final_subcursor(session) -> None:
    _seed_resume_scene(session)
    scene_id = "CH_RESUME_SC01"
    scene = session.get(SceneCard, scene_id)
    scene.constraint_intensity = 0.9
    session.commit()
    generation_client = _CountingGenerationClient()
    soft_qc = _PassSoftQc(session)
    near_final = _SequencedNearFinal(
        session,
        {"near_final_acceptance:0": "rewrite", "near_final_acceptance:1": "pass"},
    )
    origin = _selection_resume_orchestrator(
        session,
        generation_client=generation_client,
        soft_qc=soft_qc,
        near_final=near_final,
    )
    paused = origin.run_scene(scene_id, execution_id="idempotency:selection-near-origin")
    assert paused["scene_status"] == "awaiting_candidate_selection"
    gate_id, selected_row_id = _select_first_checkpoint_candidate(session, scene_id)
    resume_execution_id = "idempotency:selection-near-resume"
    first = _selection_resume_orchestrator(
        session,
        generation_client=generation_client,
        soft_qc=soft_qc,
        near_final=near_final,
    )
    original_reconcile = first._reconcile_execution_step

    def stop_before_rewrite(step_key: str) -> None:
        if step_key == "near_final_rewrite:0":
            raise RuntimeError("stop selection resume after near eval0")
        original_reconcile(step_key)

    first._reconcile_execution_step = stop_before_rewrite
    with pytest.raises(RuntimeError, match="stop selection resume after near eval0"):
        first.resume_after_selection(scene_id, execution_id=resume_execution_id)

    state = session.get(SceneRunState, scene_id)
    assert state.run_execution_status == "failed"
    assert state.run_checkpoint == "near_final_ready"
    assert state.run_checkpoint_json["sub_index"] == 0
    handoff_refs = state.run_checkpoint_json["artifact_refs"]
    gate = session.get(HumanReviewEvent, gate_id)
    assert handoff_refs["selected_row_id"] == selected_row_id
    assert gate.status == "resolved"
    assert gate.details_json["resumed"] is True
    assert handoff_refs["soft_input_source_draft_row_id"] == selected_row_id
    provider_calls = len(generation_client.requests)

    result = _selection_resume_orchestrator(
        session,
        generation_client=generation_client,
        soft_qc=soft_qc,
        near_final=near_final,
    ).resume_after_selection(scene_id, execution_id=resume_execution_id)

    assert result["scene_status"] == "archived"
    assert soft_qc.calls == 1
    assert near_final.calls == ["near_final_acceptance:0", "near_final_acceptance:1"]
    assert len(generation_client.requests) == provider_calls + 1
    assert session.scalar(
        select(func.count()).select_from(HumanReviewEvent).where(
            HumanReviewEvent.scene_id == scene_id,
            HumanReviewEvent.event_source == "candidate_selection",
        )
    ) == 1


def test_committed_neutral_and_style_checkpoint_resume_without_new_call_or_charge(session) -> None:
    _seed_resume_scene(session)
    generation_client = _CountingGenerationClient()
    late_failure = _FailAfterStyle()

    def orchestrator() -> Orchestrator:
        return Orchestrator(
            session,
            scene_generation_service=SceneGenerationService(session, llm_client=generation_client),
            hard_qc_engine=HardQcEngine(session, llm_client=_HardPassClient()),
            soft_qc_engine=late_failure,
        )

    with pytest.raises(RuntimeError, match="fail after style checkpoint"):
        orchestrator().run_scene("CH_RESUME_SC01", execution_id="idempotency:resume-one")

    state = session.get(SceneRunState, "CH_RESUME_SC01")
    assert state.run_checkpoint == "soft_qc_ready"
    assert state.run_checkpoint_json["sub_index"] == 0
    first_used = state.scene_tokens_used
    first_attempts = state.total_attempt_count
    assert len(session.execute(select(SceneDraft)).scalars().all()) == 2
    assert len(generation_client.requests) == 2
    execution_calls = session.execute(
        select(LlmCall).where(LlmCall.execution_id == "idempotency:resume-one")
    ).scalars().all()
    assert {call.execution_step_key for call in execution_calls} >= {
        "neutral_draft",
        "hard_qc:0",
        "style_draft:0",
    }

    with pytest.raises(RuntimeError, match="fail after style checkpoint"):
        orchestrator().run_scene("CH_RESUME_SC01", execution_id="idempotency:resume-one")

    session.refresh(state)
    assert state.run_checkpoint == "soft_qc_ready"
    assert state.run_checkpoint_json["sub_index"] == 0
    assert state.scene_tokens_used == first_used
    assert state.total_attempt_count == first_attempts
    assert len(session.execute(select(SceneDraft)).scalars().all()) == 2
    assert len(session.execute(select(LlmCall)).scalars().all()) >= 2
    assert len(generation_client.requests) == 2


@pytest.mark.parametrize(
    ("fail_before_step", "first_sub_index"),
    [
        ("planning:chapter_architecture", 0),
        ("planning:character_pressure", 1),
        ("bundle", 3),
    ],
)
def test_planning_subcheckpoints_resume_from_next_provider_without_replay(
    session,
    monkeypatch,
    fail_before_step: str,
    first_sub_index: int,
) -> None:
    _seed_resume_scene(session)
    execution_id = f"idempotency:planning-substep-{first_sub_index}"
    client = _PlanningCheckpointClient()
    planning_indices: list[int] = []
    original_save = SceneRunCheckpointService.save_checkpoint

    def observe_save(self, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003, ANN202
        if kwargs.get("node_key") == "planning_ready":
            planning_indices.append(kwargs.get("sub_index"))
        return original_save(self, *args, **kwargs)

    monkeypatch.setattr(SceneRunCheckpointService, "save_checkpoint", observe_save)
    first = _planning_checkpoint_orchestrator(session, client)
    if fail_before_step == "bundle":
        first.bundle_builder = _FailBundleAfterPlanning()
    else:
        original_reconcile = first._reconcile_execution_step
        failed = False

        def fail_once(step_key: str) -> None:
            nonlocal failed
            if step_key == fail_before_step and not failed:
                failed = True
                raise RuntimeError(f"stop before {step_key}")
            original_reconcile(step_key)

        first._reconcile_execution_step = fail_once

    expected_error = "stop after planning checkpoint" if fail_before_step == "bundle" else f"stop before {fail_before_step}"
    with pytest.raises(RuntimeError, match=expected_error):
        first.run_scene("CH_RESUME_SC01", execution_id=execution_id)

    state = session.get(SceneRunState, "CH_RESUME_SC01")
    assert state.run_checkpoint == "planning_ready"
    assert state.run_checkpoint_json["sub_index"] == first_sub_index
    requests_after_failure = [request.node_id for request in client.requests]

    resumed = _planning_checkpoint_orchestrator(session, client)
    resumed.bundle_builder = _FailBundleAfterPlanning()
    with pytest.raises(RuntimeError, match="stop after planning checkpoint"):
        resumed.run_scene("CH_RESUME_SC01", execution_id=execution_id)

    session.refresh(state)
    assert state.run_checkpoint == "planning_ready"
    assert state.run_checkpoint_json["sub_index"] == 3
    assert [request.node_id for request in client.requests] == [
        "scene_blueprint",
        "chapter_story_architecture",
        "character_pressure_blueprint",
    ]
    assert [request.node_id for request in client.requests[: len(requests_after_failure)]] == requests_after_failure
    assert planning_indices == [0, 1, 2, 3]
    refs = state.run_checkpoint_json["artifact_refs"]
    hashes = state.run_checkpoint_json["artifact_hashes"]
    for prefix, step_key in (
        ("planning_scene_blueprint", "scene_blueprint"),
        ("planning_chapter_architecture", "planning:chapter_architecture"),
        ("planning_character_pressure", "planning:character_pressure"),
    ):
        assert refs[f"{prefix}_row_id"]
        assert refs[f"{prefix}_execution_step_key"] == step_key
        assert refs[f"{prefix}_llm_call_id"]
        assert refs[f"{prefix}_artifact_execution_id"] == execution_id
        assert hashes[prefix]
    assert hashes["planning"]
    assert refs["planning"]["chapter_architecture"]["row_id"] == refs["planning_chapter_architecture_row_id"]
    assert refs["planning"]["character_pressure"]["row_id"] == refs["planning_character_pressure_row_id"]


def test_missing_partial_planning_blueprint_blocks_before_next_provider(session) -> None:
    _seed_resume_scene(session)
    execution_id = "idempotency:planning-partial-missing"
    client = _PlanningCheckpointClient()
    first = _planning_checkpoint_orchestrator(session, client)
    original_reconcile = first._reconcile_execution_step

    def fail_before_architecture(step_key: str) -> None:
        if step_key == "planning:chapter_architecture":
            raise RuntimeError("stop before architecture")
        original_reconcile(step_key)

    first._reconcile_execution_step = fail_before_architecture
    with pytest.raises(RuntimeError, match="stop before architecture"):
        first.run_scene("CH_RESUME_SC01", execution_id=execution_id)
    state = session.get(SceneRunState, "CH_RESUME_SC01")
    row_id = state.run_checkpoint_json["artifact_refs"]["planning_scene_blueprint_row_id"]
    session.delete(session.get(SceneBlueprint, row_id))
    session.commit()
    provider_count = len(client.requests)

    with pytest.raises(DomainError) as missing:
        _planning_checkpoint_orchestrator(session, client).run_scene(
            "CH_RESUME_SC01",
            execution_id=execution_id,
        )

    assert missing.value.code == "RUN_CHECKPOINT_OUTPUT_MISSING"
    assert len(client.requests) == provider_count


def test_tampered_partial_chapter_architecture_blocks_before_character_provider(session) -> None:
    _seed_resume_scene(session)
    execution_id = "idempotency:planning-partial-corrupt"
    client = _PlanningCheckpointClient()
    first = _planning_checkpoint_orchestrator(session, client)
    original_reconcile = first._reconcile_execution_step

    def fail_before_character(step_key: str) -> None:
        if step_key == "planning:character_pressure":
            raise RuntimeError("stop before character pressure")
        original_reconcile(step_key)

    first._reconcile_execution_step = fail_before_character
    with pytest.raises(RuntimeError, match="stop before character pressure"):
        first.run_scene("CH_RESUME_SC01", execution_id=execution_id)
    state = session.get(SceneRunState, "CH_RESUME_SC01")
    row_id = state.run_checkpoint_json["artifact_refs"]["planning_chapter_architecture_row_id"]
    artifact = session.get(GenerationPlanningArtifact, row_id)
    artifact.payload_json = {"ending_question": "tampered"}
    session.commit()
    provider_count = len(client.requests)

    with pytest.raises(DomainError) as corrupt:
        _planning_checkpoint_orchestrator(session, client).run_scene(
            "CH_RESUME_SC01",
            execution_id=execution_id,
        )

    assert corrupt.value.code == "RUN_CHECKPOINT_CORRUPT"
    assert len(client.requests) == provider_count


def test_new_execution_reuses_previous_active_planning_artifacts_with_fenced_provenance(session) -> None:
    _seed_resume_scene(session)
    client = _PlanningCheckpointClient()
    old_execution = "idempotency:planning-origin"
    first = _planning_checkpoint_orchestrator(session, client)
    first.bundle_builder = _FailBundleAfterPlanning()
    with pytest.raises(RuntimeError, match="stop after planning checkpoint"):
        first.run_scene("CH_RESUME_SC01", execution_id=old_execution)
    assert [request.node_id for request in client.requests] == [
        "scene_blueprint",
        "chapter_story_architecture",
        "character_pressure_blueprint",
    ]

    new_execution = "idempotency:planning-reuser"
    for _attempt in range(2):
        reused = _planning_checkpoint_orchestrator(session, client)
        reused.bundle_builder = _FailBundleAfterPlanning()
        with pytest.raises(RuntimeError, match="stop after planning checkpoint"):
            reused.run_scene("CH_RESUME_SC01", execution_id=new_execution)

    state = session.get(SceneRunState, "CH_RESUME_SC01")
    refs = state.run_checkpoint_json["artifact_refs"]
    hashes = state.run_checkpoint_json["artifact_hashes"]
    assert state.active_execution_id == new_execution
    assert state.run_checkpoint_json["sub_index"] == 3
    assert len(client.requests) == 3
    for prefix in (
        "planning_scene_blueprint",
        "planning_chapter_architecture",
        "planning_character_pressure",
    ):
        assert refs[f"{prefix}_reused"] is True
        assert refs[f"{prefix}_artifact_execution_id"] == old_execution
        assert hashes[f"{prefix}_provenance"]


def test_partial_planning_resume_prefers_checkpoint_row_over_newer_active_artifact(session) -> None:
    _seed_resume_scene(session)
    execution_id = "idempotency:planning-checkpoint-row-wins"
    client = _PlanningCheckpointClient()
    first = _planning_checkpoint_orchestrator(session, client)
    original_reconcile = first._reconcile_execution_step

    def fail_before_character(step_key: str) -> None:
        if step_key == "planning:character_pressure":
            raise RuntimeError("stop before character pressure")
        original_reconcile(step_key)

    first._reconcile_execution_step = fail_before_character
    with pytest.raises(RuntimeError, match="stop before character pressure"):
        first.run_scene("CH_RESUME_SC01", execution_id=execution_id)
    state = session.get(SceneRunState, "CH_RESUME_SC01")
    checkpoint_row_id = state.run_checkpoint_json["artifact_refs"]["planning_chapter_architecture_row_id"]
    checkpoint_row = session.get(GenerationPlanningArtifact, checkpoint_row_id)
    checkpoint_row.status = "superseded"
    session.add(
        GenerationPlanningArtifact(
            row_id="planning_chapter_story_architecture_CH_RESUME_zzzzzzzzzz",
            artifact_type="chapter_story_architecture",
            object_type="chapter",
            object_id="CH_RESUME",
            chapter_id="CH_RESUME",
            scene_id=None,
            payload_json={"ending_question": "newer unrelated architecture"},
            llm_call_id=None,
            source_bundle_id="newer-source",
            source_bundle_hash="newer-hash",
            status="active",
            created_by="other-scene",
            created_at="2099-01-01T00:00:00+00:00",
        )
    )
    session.commit()

    resumed = _planning_checkpoint_orchestrator(session, client)
    resumed.bundle_builder = _FailBundleAfterPlanning()
    with pytest.raises(RuntimeError, match="stop after planning checkpoint"):
        resumed.run_scene("CH_RESUME_SC01", execution_id=execution_id)

    session.refresh(state)
    assert state.run_checkpoint_json["artifact_refs"]["planning"]["chapter_architecture"]["row_id"] == checkpoint_row_id
    assert [request.node_id for request in client.requests] == [
        "scene_blueprint",
        "chapter_story_architecture",
        "character_pressure_blueprint",
    ]


def test_settled_provider_parse_failure_restores_ledger_and_blocks_same_execution_retry(session) -> None:
    _seed_resume_scene(session)
    generation_client = _SettledButUnparseableGenerationClient()
    execution_id = "idempotency:settled-before-product"

    def orchestrator() -> Orchestrator:
        return Orchestrator(
            session,
            scene_generation_service=SceneGenerationService(session, llm_client=generation_client),
            hard_qc_engine=HardQcEngine(session, llm_client=_HardPassClient()),
        )

    with pytest.raises(ValueError, match="missing scene_text"):
        orchestrator().run_scene("CH_RESUME_SC01", execution_id=execution_id)

    state = session.get(SceneRunState, "CH_RESUME_SC01")
    calls = session.execute(
        select(LlmCall).where(
            LlmCall.scene_id == "CH_RESUME_SC01",
            LlmCall.execution_id == execution_id,
            LlmCall.execution_step_key == "neutral_draft",
        )
    ).scalars().all()
    assert len(calls) == 1
    assert calls[0].accounting_status == "settled"
    assert calls[0].request_dispatched_at is not None
    assert session.execute(
        select(SceneDraft).where(SceneDraft.generation_llm_call_id == calls[0].llm_call_id)
    ).scalars().all() == []
    assert state.scene_tokens_used == session.scalar(
        select(func.sum(LlmCall.budget_charged_tokens)).where(
            LlmCall.scene_id == "CH_RESUME_SC01",
            LlmCall.execution_id == execution_id,
        )
    )
    provider_calls = len(generation_client.requests)

    with pytest.raises(DomainError) as exc_info:
        orchestrator().run_scene("CH_RESUME_SC01", execution_id=execution_id)

    assert exc_info.value.code == "RUN_CHECKPOINT_OUTPUT_MISSING"
    assert len(generation_client.requests) == provider_calls == 1


def test_same_execution_retry_before_first_checkpoint_is_resumed_and_preserves_current_pointer(session, monkeypatch) -> None:
    _seed_resume_scene(session)
    execution_id = "idempotency:failed-before-first-checkpoint"

    def fail_before_checkpoint(self, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003
        raise RuntimeError("failed before first checkpoint")

    monkeypatch.setattr(Orchestrator, "_run_scene_pipeline", fail_before_checkpoint)
    with pytest.raises(RuntimeError, match="failed before first checkpoint"):
        Orchestrator(session).run_scene("CH_RESUME_SC01", execution_id=execution_id)

    state = session.get(SceneRunState, "CH_RESUME_SC01")
    assert state.run_checkpoint is None
    state.current_neutral_draft_row_id = "preserve-on-same-execution-retry"
    session.commit()

    observed: list[str | None] = []

    def observe_then_fail(self, scene_id, **kwargs):  # noqa: ANN001, ANN003
        observed.append(self.session.get(SceneRunState, scene_id).current_neutral_draft_row_id)
        raise RuntimeError("same execution retry")

    monkeypatch.setattr(Orchestrator, "_run_scene_pipeline", observe_then_fail)
    with pytest.raises(RuntimeError, match="same execution retry"):
        Orchestrator(session).run_scene("CH_RESUME_SC01", execution_id=execution_id)

    assert observed == ["preserve-on-same-execution-retry"]


def test_best_of_n_blocks_dispatched_missing_second_candidate_without_repeating_provider(session, monkeypatch) -> None:
    _seed_resume_scene(session)
    generation_client = _FailSecondCandidateOnceClient()
    late_failure = _FailAfterStyle()
    monkeypatch.setattr(Orchestrator, "_best_of_n_count", staticmethod(lambda contract, criticality=None: 2))

    def orchestrator() -> Orchestrator:
        return Orchestrator(
            session,
            scene_generation_service=SceneGenerationService(session, llm_client=generation_client),
            hard_qc_engine=HardQcEngine(session, llm_client=_HardPassClient()),
            soft_qc_engine=late_failure,
        )

    with pytest.raises(ValueError, match="candidate two failed once"):
        orchestrator().run_scene("CH_RESUME_SC01", execution_id="idempotency:resume-candidates")

    state = session.get(SceneRunState, "CH_RESUME_SC01")
    assert state.run_checkpoint == "hard_qc_ready"
    assert state.run_checkpoint_json["sub_index"] == 1
    assert state.run_checkpoint_json["artifact_refs"]["style_candidate_row_ids"] == [
        "draft_style_cand_CH_RESUME_SC01_v1_0"
    ]
    assert len(generation_client.requests) == 3

    with pytest.raises(DomainError) as exc_info:
        orchestrator().run_scene("CH_RESUME_SC01", execution_id="idempotency:resume-candidates")

    assert exc_info.value.code == "RUN_CHECKPOINT_OUTPUT_MISSING"
    session.refresh(state)
    assert state.run_checkpoint == "hard_qc_ready"
    assert state.run_checkpoint_json["artifact_refs"]["style_candidate_row_ids"] == [
        "draft_style_cand_CH_RESUME_SC01_v1_0"
    ]
    assert len(generation_client.requests) == 3
    draft_ids = session.execute(select(SceneDraft.row_id).order_by(SceneDraft.row_id)).scalars().all()
    assert draft_ids == [
        "draft_neutral_CH_RESUME_SC01_v1",
        "draft_style_cand_CH_RESUME_SC01_v1_0",
    ]
    candidate_steps = session.execute(
        select(LlmCall.execution_step_key).where(
            LlmCall.execution_id == "idempotency:resume-candidates",
            LlmCall.step == "style_draft",
        )
    ).scalars().all()
    assert sorted(candidate_steps) == ["style_draft:0", "style_draft:1"]


def test_best_of_n_releases_undispatched_second_candidate_reservation_then_retries_once(session, monkeypatch) -> None:
    _seed_resume_scene(session)
    generation_client = _CountingGenerationClient()
    late_failure = _FailAfterStyle()
    execution_id = "idempotency:resume-undispatched-candidate"
    monkeypatch.setattr(Orchestrator, "_best_of_n_count", staticmethod(lambda contract, criticality=None: 2))

    def orchestrator() -> Orchestrator:
        return Orchestrator(
            session,
            scene_generation_service=SceneGenerationService(session, llm_client=generation_client),
            hard_qc_engine=HardQcEngine(session, llm_client=_HardPassClient()),
            soft_qc_engine=late_failure,
        )

    first = orchestrator()
    original_reconcile = first._reconcile_execution_step

    def crash_after_second_candidate_reservation(step_key: str) -> None:
        original_reconcile(step_key)
        if step_key != "style_draft:1":
            return
        state = session.get(SceneRunState, "CH_RESUME_SC01")
        state.scene_tokens_reserved += 17
        session.add(
            LlmCall(
                llm_call_id="call-undispatched-style-candidate-1",
                provider="fake",
                model="fake",
                step="style_draft",
                scene_id="CH_RESUME_SC01",
                chapter_id="CH_RESUME",
                scope_type="scene",
                scope_id="CH_RESUME_SC01",
                execution_id=execution_id,
                execution_step_key="style_draft:1",
                estimated_tokens=17,
                reserved_tokens=17,
                budget_charged_tokens=0,
                accounting_status="reserved",
            )
        )
        session.add(
            LlmCallAttempt(
                attempt_id="attempt-undispatched-style-candidate-1",
                llm_call_id="call-undispatched-style-candidate-1",
                provider_attempt_no=0,
                dispatch_kind="initial",
                request_max_output_tokens=10,
                estimated_tokens=17,
                reserved_tokens=17,
                budget_charged_tokens=0,
                accounting_status="reserved",
            )
        )
        session.commit()
        raise RuntimeError("crash after candidate reservation")

    first._reconcile_execution_step = crash_after_second_candidate_reservation
    with pytest.raises(RuntimeError, match="crash after candidate reservation"):
        first.run_scene("CH_RESUME_SC01", execution_id=execution_id)

    assert len(generation_client.requests) == 2
    with pytest.raises(RuntimeError, match="fail after style checkpoint"):
        orchestrator().run_scene("CH_RESUME_SC01", execution_id=execution_id)

    state = session.get(SceneRunState, "CH_RESUME_SC01")
    released = session.get(LlmCall, "call-undispatched-style-candidate-1")
    assert released.accounting_status == "released"
    assert state.scene_tokens_reserved == 0
    assert state.run_checkpoint == "soft_qc_ready"
    assert state.run_checkpoint_json["sub_index"] == 0
    assert len(generation_client.requests) == 3
    assert set(state.run_checkpoint_json["artifact_refs"]["candidate_row_ids"]) == {
        "draft_style_cand_CH_RESUME_SC01_v1_1",
        "draft_style_cand_CH_RESUME_SC01_v1_0",
    }


def test_missing_settled_style_output_blocks_before_any_new_provider_call(session) -> None:
    _seed_resume_scene(session)
    generation_client = _CountingGenerationClient()
    late_failure = _FailAfterStyle()

    def orchestrator() -> Orchestrator:
        return Orchestrator(
            session,
            scene_generation_service=SceneGenerationService(session, llm_client=generation_client),
            hard_qc_engine=HardQcEngine(session, llm_client=_HardPassClient()),
            soft_qc_engine=late_failure,
        )

    with pytest.raises(RuntimeError, match="fail after style checkpoint"):
        orchestrator().run_scene("CH_RESUME_SC01", execution_id="idempotency:missing-output")

    state = session.get(SceneRunState, "CH_RESUME_SC01")
    style_row = session.get(SceneDraft, state.run_checkpoint_json["artifact_refs"]["style_draft_row_id"])
    assert style_row is not None
    session.delete(style_row)
    session.commit()
    before_calls = session.scalar(select(func.count()).select_from(LlmCall))
    before_tokens = state.scene_tokens_used
    before_provider = len(generation_client.requests)

    with pytest.raises(DomainError) as exc_info:
        orchestrator().run_scene("CH_RESUME_SC01", execution_id="idempotency:missing-output")

    assert exc_info.value.code == "RUN_CHECKPOINT_OUTPUT_MISSING"
    session.refresh(state)
    assert len(generation_client.requests) == before_provider
    assert session.scalar(select(func.count()).select_from(LlmCall)) == before_calls
    assert state.scene_tokens_used == before_tokens


def test_successful_run_commits_terminal_macro_checkpoint(session) -> None:
    _seed_resume_scene(session)
    result = Orchestrator(
        session,
        scene_generation_service=SceneGenerationService(session, llm_client=_CountingGenerationClient()),
        hard_qc_engine=HardQcEngine(session, llm_client=_HardPassClient()),
    ).run_scene("CH_RESUME_SC01", execution_id="idempotency:terminal-checkpoint")

    assert result["scene_status"] == "archived"
    state = session.get(SceneRunState, "CH_RESUME_SC01")
    assert state is not None
    assert state.run_checkpoint == "archived"
    assert state.run_execution_status == "completed"
    assert state.run_checkpoint_json["artifact_refs"]["final_scene_row_id"] == state.current_final_scene_row_id


def test_soft_qc_checkpoint_resume_does_not_repeat_qc_or_generation(session) -> None:
    _seed_resume_scene(session)
    generation_client = _CountingGenerationClient()
    soft_qc = _PassSoftQc(session)
    near_final = _FailNearFinal()

    def orchestrator() -> Orchestrator:
        return Orchestrator(
            session,
            scene_generation_service=SceneGenerationService(session, llm_client=generation_client),
            hard_qc_engine=HardQcEngine(session, llm_client=_HardPassClient()),
            soft_qc_engine=soft_qc,
            near_final_service=near_final,
        )

    for _attempt in range(2):
        with pytest.raises(RuntimeError, match="fail after soft checkpoint"):
            orchestrator().run_scene("CH_RESUME_SC01", execution_id="idempotency:soft-resume")

    state = session.get(SceneRunState, "CH_RESUME_SC01")
    assert state is not None
    assert state.run_checkpoint == "soft_qc_ready"
    assert soft_qc.calls == 1
    assert near_final.calls == 2
    assert len(generation_client.requests) == 2


def test_soft_qc0_checkpoint_resumes_at_patch_without_replaying_qc0(session) -> None:
    _seed_resume_scene(session)
    generation_client = _CountingGenerationClient()
    soft_qc = _SequencedSoftQc(
        session,
        {"soft_qc:0": "patch", "soft_qc:1": "continue"},
    )
    near_final = _FailNearFinal()

    def orchestrator() -> Orchestrator:
        return Orchestrator(
            session,
            scene_generation_service=SceneGenerationService(session, llm_client=generation_client),
            hard_qc_engine=HardQcEngine(session, llm_client=_HardPassClient()),
            soft_qc_engine=soft_qc,
            near_final_service=near_final,
        )

    first = orchestrator()
    original_reconcile = first._reconcile_execution_step

    def stop_before_patch(execution_step_key: str) -> None:
        if execution_step_key == "soft_patch:soft_qc:0":
            raise RuntimeError("stop after soft QC0 checkpoint")
        original_reconcile(execution_step_key)

    first._reconcile_execution_step = stop_before_patch
    with pytest.raises(RuntimeError, match="stop after soft QC0 checkpoint"):
        first.run_scene("CH_RESUME_SC01", execution_id="idempotency:soft-qc0-resume")

    state = session.get(SceneRunState, "CH_RESUME_SC01")
    assert state.run_checkpoint == "soft_qc_ready"
    assert state.run_checkpoint_json["sub_index"] == 1
    assert state.run_checkpoint_json["artifact_refs"]["soft_qc0_report_id"] == "qc_CH_RESUME_SC01_soft_qc_0"
    provider_calls = len(generation_client.requests)
    tokens_used = state.scene_tokens_used

    with pytest.raises(RuntimeError, match="fail after soft checkpoint"):
        orchestrator().run_scene("CH_RESUME_SC01", execution_id="idempotency:soft-qc0-resume")

    session.refresh(state)
    assert state.run_checkpoint_json["sub_index"] == 3
    assert state.run_checkpoint_json["artifact_refs"]["soft_final_qc_round"] == 1
    assert soft_qc.calls == ["soft_qc:0", "soft_qc:1"]
    assert len(generation_client.requests) == provider_calls + 1
    assert state.scene_tokens_used > tokens_used
    assert len(
        session.execute(
            select(LlmCall).where(
                LlmCall.scene_id == "CH_RESUME_SC01",
                LlmCall.execution_step_key == "soft_qc:0",
            )
        ).scalars().all()
    ) == 1
    assert len(
        [
            attempt
            for attempt in session.execute(
                select(AttemptTracker).where(
                    AttemptTracker.scene_id == "CH_RESUME_SC01",
                    AttemptTracker.step == "soft_qc",
                )
            ).scalars().all()
            if (attempt.details_json or {}).get("execution_step_key") == "soft_qc:0"
        ]
    ) == 1


def test_soft_patch_checkpoint_resumes_at_qc1_without_replaying_patch(session) -> None:
    _seed_resume_scene(session)
    generation_client = _CountingGenerationClient()
    soft_qc = _SequencedSoftQc(
        session,
        {"soft_qc:0": "patch", "soft_qc:1": "continue"},
    )
    near_final = _FailNearFinal()

    def orchestrator() -> Orchestrator:
        return Orchestrator(
            session,
            scene_generation_service=SceneGenerationService(session, llm_client=generation_client),
            hard_qc_engine=HardQcEngine(session, llm_client=_HardPassClient()),
            soft_qc_engine=soft_qc,
            near_final_service=near_final,
        )

    first = orchestrator()
    original_reconcile = first._reconcile_execution_step

    def stop_before_qc1(execution_step_key: str) -> None:
        if execution_step_key == "soft_qc:1":
            raise RuntimeError("stop after soft patch checkpoint")
        original_reconcile(execution_step_key)

    first._reconcile_execution_step = stop_before_qc1
    with pytest.raises(RuntimeError, match="stop after soft patch checkpoint"):
        first.run_scene("CH_RESUME_SC01", execution_id="idempotency:soft-patch-resume")

    state = session.get(SceneRunState, "CH_RESUME_SC01")
    assert state.run_checkpoint == "soft_qc_ready"
    assert state.run_checkpoint_json["sub_index"] == 2
    patch_row_id = state.run_checkpoint_json["artifact_refs"]["soft_patch_draft_row_id"]
    provider_calls = len(generation_client.requests)
    tokens_used = state.scene_tokens_used

    with pytest.raises(RuntimeError, match="fail after soft checkpoint"):
        orchestrator().run_scene("CH_RESUME_SC01", execution_id="idempotency:soft-patch-resume")

    session.refresh(state)
    assert state.run_checkpoint_json["sub_index"] == 3
    assert state.run_checkpoint_json["artifact_refs"]["soft_final_draft_row_id"] == patch_row_id
    assert soft_qc.calls == ["soft_qc:0", "soft_qc:1"]
    assert len(generation_client.requests) == provider_calls
    assert state.scene_tokens_used == tokens_used
    assert len(
        session.execute(
            select(LlmCall).where(
                LlmCall.scene_id == "CH_RESUME_SC01",
                LlmCall.execution_step_key == "soft_patch:soft_qc:0",
            )
        ).scalars().all()
    ) == 1
    assert len(
        [
            attempt
            for attempt in session.execute(
                select(AttemptTracker).where(
                    AttemptTracker.scene_id == "CH_RESUME_SC01",
                    AttemptTracker.step == "soft_patch",
                )
            ).scalars().all()
            if (attempt.details_json or {}).get("row_id") == patch_row_id
        ]
    ) == 1


def test_soft_qc_without_patch_advances_directly_to_complete_subcursor(session) -> None:
    _seed_resume_scene(session)
    generation_client = _CountingGenerationClient()
    soft_qc = _SequencedSoftQc(session, {"soft_qc:0": "continue"})
    near_final = _FailNearFinal()

    def orchestrator() -> Orchestrator:
        return Orchestrator(
            session,
            scene_generation_service=SceneGenerationService(session, llm_client=generation_client),
            hard_qc_engine=HardQcEngine(session, llm_client=_HardPassClient()),
            soft_qc_engine=soft_qc,
            near_final_service=near_final,
        )

    for _attempt in range(2):
        with pytest.raises(RuntimeError, match="fail after soft checkpoint"):
            orchestrator().run_scene("CH_RESUME_SC01", execution_id="idempotency:soft-no-patch")

    state = session.get(SceneRunState, "CH_RESUME_SC01")
    refs = state.run_checkpoint_json["artifact_refs"]
    assert state.run_checkpoint_json["sub_index"] == 3
    assert refs["soft_final_qc_round"] == 0
    assert refs["soft_completion_skip_reason"] == "no_patch_requested"
    assert refs["soft_final_draft_row_id"] == refs["soft_input_draft_row_id"]
    assert soft_qc.calls == ["soft_qc:0"]
    assert len(generation_client.requests) == 2


def test_soft_qc_budget_skip_persists_branch_without_patch_call(session, monkeypatch) -> None:
    from novel_system.services import scene_budget

    _seed_resume_scene(session)
    monkeypatch.setattr(scene_budget, "can_spend", lambda *args, **kwargs: False)
    generation_client = _CountingGenerationClient()
    soft_qc = _SequencedSoftQc(session, {"soft_qc:0": "patch"})
    near_final = _FailNearFinal()
    orchestrator = Orchestrator(
        session,
        scene_generation_service=SceneGenerationService(session, llm_client=generation_client),
        hard_qc_engine=HardQcEngine(session, llm_client=_HardPassClient()),
        soft_qc_engine=soft_qc,
        near_final_service=near_final,
    )

    with pytest.raises(RuntimeError, match="fail after soft checkpoint"):
        orchestrator.run_scene("CH_RESUME_SC01", execution_id="idempotency:soft-budget-skip")

    state = session.get(SceneRunState, "CH_RESUME_SC01")
    refs = state.run_checkpoint_json["artifact_refs"]
    assert state.run_checkpoint_json["sub_index"] == 3
    assert refs["soft_qc0_control"] == {
        "patch_allowed": False,
        "skip_reason": "budget_or_candidate_cap",
    }
    assert refs["soft_final_qc_round"] == 0
    assert refs["soft_qc_branch"] == "patch"
    assert refs.get("soft_patch_draft_row_id") is None
    assert len(generation_client.requests) == 2


def test_soft_qc_human_review_branch_is_complete_and_resume_safe(session) -> None:
    _seed_resume_scene(session)
    generation_client = _CountingGenerationClient()
    soft_qc = _SequencedSoftQc(session, {"soft_qc:0": "human_review_required"})

    def orchestrator() -> Orchestrator:
        return Orchestrator(
            session,
            scene_generation_service=SceneGenerationService(session, llm_client=generation_client),
            hard_qc_engine=HardQcEngine(session, llm_client=_HardPassClient()),
            soft_qc_engine=soft_qc,
        )

    first = orchestrator().run_scene(
        "CH_RESUME_SC01",
        execution_id="idempotency:soft-human-review",
    )
    provider_calls = len(generation_client.requests)
    second = orchestrator().run_scene(
        "CH_RESUME_SC01",
        execution_id="idempotency:soft-human-review",
    )

    state = session.get(SceneRunState, "CH_RESUME_SC01")
    refs = state.run_checkpoint_json["artifact_refs"]
    assert first["scene_status"] == second["scene_status"] == "human_review_required"
    assert first["soft_qc"]["branch"] == second["soft_qc"]["branch"] == "human_review_required"
    assert state.run_checkpoint_json["sub_index"] == 3
    assert refs["soft_final_qc_round"] == 0
    assert refs["soft_completion_skip_reason"] == "human_review_required"
    assert soft_qc.calls == ["soft_qc:0"]
    assert len(generation_client.requests) == provider_calls


def test_complete_soft_prefix_missing_qc0_blocks_without_provider_replay(session) -> None:
    _seed_resume_scene(session)
    generation_client = _CountingGenerationClient()
    soft_qc = _SequencedSoftQc(
        session,
        {"soft_qc:0": "patch", "soft_qc:1": "continue"},
    )
    near_final = _FailNearFinal()

    def orchestrator() -> Orchestrator:
        return Orchestrator(
            session,
            scene_generation_service=SceneGenerationService(session, llm_client=generation_client),
            hard_qc_engine=HardQcEngine(session, llm_client=_HardPassClient()),
            soft_qc_engine=soft_qc,
            near_final_service=near_final,
        )

    with pytest.raises(RuntimeError, match="fail after soft checkpoint"):
        orchestrator().run_scene("CH_RESUME_SC01", execution_id="idempotency:soft-prefix-missing")
    state = session.get(SceneRunState, "CH_RESUME_SC01")
    report_id = state.run_checkpoint_json["artifact_refs"]["soft_qc0_report_id"]
    session.delete(session.get(QcReport, report_id))
    session.commit()
    provider_calls = len(generation_client.requests)
    calls = list(soft_qc.calls)

    with pytest.raises(DomainError) as missing:
        orchestrator().run_scene("CH_RESUME_SC01", execution_id="idempotency:soft-prefix-missing")

    assert missing.value.code == "RUN_CHECKPOINT_OUTPUT_MISSING"
    assert soft_qc.calls == calls
    assert len(generation_client.requests) == provider_calls


def test_complete_soft_prefix_tampered_qc0_blocks_without_provider_replay(session) -> None:
    _seed_resume_scene(session)
    generation_client = _CountingGenerationClient()
    soft_qc = _SequencedSoftQc(
        session,
        {"soft_qc:0": "patch", "soft_qc:1": "continue"},
    )
    near_final = _FailNearFinal()

    def orchestrator() -> Orchestrator:
        return Orchestrator(
            session,
            scene_generation_service=SceneGenerationService(session, llm_client=generation_client),
            hard_qc_engine=HardQcEngine(session, llm_client=_HardPassClient()),
            soft_qc_engine=soft_qc,
            near_final_service=near_final,
        )

    with pytest.raises(RuntimeError, match="fail after soft checkpoint"):
        orchestrator().run_scene("CH_RESUME_SC01", execution_id="idempotency:soft-prefix-tamper")
    state = session.get(SceneRunState, "CH_RESUME_SC01")
    report_id = state.run_checkpoint_json["artifact_refs"]["soft_qc0_report_id"]
    report = session.get(QcReport, report_id)
    report.rewrite_brief_json = [{"instruction": "tampered QC0"}]
    session.commit()
    provider_calls = len(generation_client.requests)
    calls = list(soft_qc.calls)

    with pytest.raises(DomainError) as corrupt:
        orchestrator().run_scene("CH_RESUME_SC01", execution_id="idempotency:soft-prefix-tamper")

    assert corrupt.value.code == "RUN_CHECKPOINT_CORRUPT"
    assert soft_qc.calls == calls
    assert len(generation_client.requests) == provider_calls


def test_auto_critique_patch_is_durable_soft_input_subcheckpoint(session, monkeypatch) -> None:
    from novel_system.services.auto_critique import CritiqueResult

    _seed_resume_scene(session)
    monkeypatch.setattr(
        "novel_system.services.auto_critique.llm_auto_critique",
        lambda *args, **kwargs: CritiqueResult(
            should_rewrite=True,
            directives=["tighten the opening"],
            dimension_scores={"syntax_monotony": 0.1},
            flagged_dimensions=["syntax_monotony"],
        ),
    )
    generation_client = _CountingGenerationClient()
    first = Orchestrator(
        session,
        scene_generation_service=SceneGenerationService(session, llm_client=generation_client),
        hard_qc_engine=HardQcEngine(session, llm_client=_HardPassClient()),
        soft_qc_engine=_FailAfterStyle(),
    )

    with pytest.raises(RuntimeError, match="fail after style checkpoint"):
        first.run_scene("CH_RESUME_SC01", execution_id="idempotency:auto-critique-input")

    state = session.get(SceneRunState, "CH_RESUME_SC01")
    refs = state.run_checkpoint_json["artifact_refs"]
    input_draft = session.get(SceneDraft, refs["soft_input_draft_row_id"])
    assert state.run_checkpoint_json["sub_index"] == 0
    assert refs["soft_auto_critique_outcome"] == "patched"
    assert refs["soft_input_execution_step_key"] == "soft_patch:auto_critique:0"
    assert refs["soft_input_source_draft_row_id"] != refs["soft_input_draft_row_id"]
    assert input_draft.stage == "style_patch"
    assert len(generation_client.requests) == 3


def test_de_template_selected_soft_input_resumes_from_sub0(session, monkeypatch) -> None:
    _seed_resume_scene(session)
    monkeypatch.setattr(
        "novel_system.services.scene_generation._anti_template_quality_gate",
        lambda *args, **kwargs: {
            "triggered": True,
            "rewrite_pass": 1,
            "score": 0.0,
            "risk_dimensions": ["model_voice"],
            "quality_signal_ids": ["quality:test"],
            "findings": [],
        },
    )
    generation_client = _CountingGenerationClient()
    first = Orchestrator(
        session,
        scene_generation_service=SceneGenerationService(session, llm_client=generation_client),
        hard_qc_engine=HardQcEngine(session, llm_client=_HardPassClient()),
        soft_qc_engine=_FailAfterStyle(),
    )
    with pytest.raises(RuntimeError, match="fail after style checkpoint"):
        first.run_scene("CH_RESUME_SC01", execution_id="idempotency:de-template-soft-input")

    state = session.get(SceneRunState, "CH_RESUME_SC01")
    refs = state.run_checkpoint_json["artifact_refs"]
    selected = session.get(SceneDraft, refs["soft_input_draft_row_id"])
    assert state.run_checkpoint_json["sub_index"] == 0
    assert selected.stage == "de_template"
    provider_calls = len(generation_client.requests)

    with pytest.raises(RuntimeError, match="fail after soft checkpoint"):
        Orchestrator(
            session,
            scene_generation_service=SceneGenerationService(session, llm_client=generation_client),
            hard_qc_engine=HardQcEngine(session, llm_client=_HardPassClient()),
            soft_qc_engine=_PassSoftQc(session),
            near_final_service=_FailNearFinal(),
        ).run_scene("CH_RESUME_SC01", execution_id="idempotency:de-template-soft-input")

    assert len(generation_client.requests) == provider_calls


def test_style_base_checkpoint_resumes_only_de_template_after_interruption(session, monkeypatch) -> None:
    _seed_resume_scene(session)
    monkeypatch.setattr(
        "novel_system.services.scene_generation._anti_template_quality_gate",
        lambda *args, **kwargs: {
            "triggered": True,
            "rewrite_pass": 1,
            "score": 0.0,
            "risk_dimensions": ["model_voice"],
            "quality_signal_ids": ["quality:resume-base"],
            "findings": [],
        },
    )
    generation_client = _CountingGenerationClient()
    execution_id = "idempotency:style-base-de-template-resume"
    first = Orchestrator(
        session,
        scene_generation_service=SceneGenerationService(session, llm_client=generation_client),
        hard_qc_engine=HardQcEngine(session, llm_client=_HardPassClient()),
        soft_qc_engine=_FailAfterStyle(),
    )
    original_reconcile = first._reconcile_execution_step

    def interrupt_before_de_template(step_key: str) -> None:
        original_reconcile(step_key)
        if step_key == "style_draft:0:de_template":
            raise RuntimeError("interrupt after durable style base")

    first._reconcile_execution_step = interrupt_before_de_template
    with pytest.raises(RuntimeError, match="interrupt after durable style base"):
        first.run_scene("CH_RESUME_SC01", execution_id=execution_id)

    state = session.get(SceneRunState, "CH_RESUME_SC01")
    work_items = state.run_checkpoint_json["artifact_refs"]["style_work_items"]
    assert state.run_checkpoint == "hard_qc_ready"
    assert state.run_checkpoint_json["sub_index"] == 0
    assert len(work_items) == 1
    assert work_items[0]["slot_key"] == "initial:0"
    assert work_items[0]["base"]["row_id"] == "draft_style_CH_RESUME_SC01_v1"
    assert work_items[0]["final"] is None
    assert [request.node_id for request in generation_client.requests] == ["neutral_draft", "style_draft"]
    base_call = session.get(LlmCall, work_items[0]["base"]["llm_call_id"])
    base_accounting = (
        base_call.accounting_status,
        base_call.reserved_tokens,
        base_call.budget_charged_tokens,
        base_call.total_tokens,
    )

    with pytest.raises(RuntimeError, match="fail after style checkpoint"):
        Orchestrator(
            session,
            scene_generation_service=SceneGenerationService(session, llm_client=generation_client),
            hard_qc_engine=HardQcEngine(session, llm_client=_HardPassClient()),
            soft_qc_engine=_FailAfterStyle(),
        ).run_scene("CH_RESUME_SC01", execution_id=execution_id)

    session.refresh(state)
    work_items = state.run_checkpoint_json["artifact_refs"]["style_work_items"]
    assert work_items[0]["gate_decision"]["triggered"] is True
    assert work_items[0]["final"]["stage"] == "de_template"
    assert work_items[0]["final"]["source_base_row_id"] == work_items[0]["base"]["row_id"]
    assert [request.node_id for request in generation_client.requests].count("style_draft") == 1
    assert [request.node_id for request in generation_client.requests].count("style_patch") == 1
    session.refresh(base_call)
    assert (
        base_call.accounting_status,
        base_call.reserved_tokens,
        base_call.budget_charged_tokens,
        base_call.total_tokens,
    ) == base_accounting
    assert session.scalar(
        select(func.count()).select_from(AttemptTracker).where(
            AttemptTracker.scene_id == "CH_RESUME_SC01",
            AttemptTracker.step == "style_draft",
            AttemptTracker.status == "completed",
        )
    ) == 1
    assert session.scalar(
        select(func.count()).select_from(SceneDraft).where(
            SceneDraft.row_id == work_items[0]["base"]["row_id"]
        )
    ) == 1


def test_failed_de_template_is_a_durable_final_outcome_and_is_not_replayed(session, monkeypatch) -> None:
    _seed_resume_scene(session)
    monkeypatch.setattr(
        "novel_system.services.scene_generation._anti_template_quality_gate",
        lambda *args, **kwargs: {
            "triggered": True,
            "rewrite_pass": 1,
            "score": 0.0,
            "risk_dimensions": ["model_voice"],
            "quality_signal_ids": ["quality:failed-de-template"],
            "findings": [],
        },
    )
    generation_client = _FailDeTemplateClient()
    execution_id = "idempotency:failed-de-template-final"

    with pytest.raises(RuntimeError, match="fail after style checkpoint"):
        Orchestrator(
            session,
            scene_generation_service=SceneGenerationService(session, llm_client=generation_client),
            hard_qc_engine=HardQcEngine(session, llm_client=_HardPassClient()),
            soft_qc_engine=_FailAfterStyle(),
        ).run_scene("CH_RESUME_SC01", execution_id=execution_id)

    state = session.get(SceneRunState, "CH_RESUME_SC01")
    item = state.run_checkpoint_json["artifact_refs"]["style_work_items"][0]
    outcome = item["de_template_outcome"]
    assert outcome["status"] == "failed"
    assert outcome["execution_step_key"] == "style_draft:0:de_template"
    assert outcome["accounting_status"] == "failed"
    assert item["gate_decision"]["triggered"] is True
    assert item["final"]["row_id"] == item["base"]["row_id"]
    provider_calls = len(generation_client.requests)

    with pytest.raises(RuntimeError, match="fail after soft checkpoint"):
        Orchestrator(
            session,
            scene_generation_service=SceneGenerationService(session, llm_client=generation_client),
            hard_qc_engine=HardQcEngine(session, llm_client=_HardPassClient()),
            soft_qc_engine=_PassSoftQc(session),
            near_final_service=_FailNearFinal(),
        ).run_scene("CH_RESUME_SC01", execution_id=execution_id)

    assert len(generation_client.requests) == provider_calls
    assert session.scalar(
        select(func.count()).select_from(AttemptTracker).where(
            AttemptTracker.scene_id == "CH_RESUME_SC01",
            AttemptTracker.step == "de_template",
            AttemptTracker.status == "failed",
        )
    ) == 1


def test_failed_de_template_recovery_rejects_error_code_detached_from_parent_call(
    session,
    monkeypatch,
) -> None:
    _seed_resume_scene(session)
    monkeypatch.setattr(
        "novel_system.services.scene_generation._anti_template_quality_gate",
        lambda *args, **kwargs: {
            "triggered": True,
            "rewrite_pass": 1,
            "score": 0.0,
            "risk_dimensions": ["model_voice"],
            "quality_signal_ids": ["quality:failed-de-template-error-code"],
            "findings": [],
        },
    )
    generation_client = _FailDeTemplateClient()
    execution_id = "idempotency:failed-de-template-error-code"
    with pytest.raises(RuntimeError, match="fail after style checkpoint"):
        Orchestrator(
            session,
            scene_generation_service=SceneGenerationService(session, llm_client=generation_client),
            hard_qc_engine=HardQcEngine(session, llm_client=_HardPassClient()),
            soft_qc_engine=_FailAfterStyle(),
        ).run_scene("CH_RESUME_SC01", execution_id=execution_id)

    state = session.get(SceneRunState, "CH_RESUME_SC01")
    payload = deepcopy(state.run_checkpoint_json)
    item = payload["artifact_refs"]["style_work_items"][0]
    outcome = item["de_template_outcome"]
    parent_call = session.get(LlmCall, outcome["llm_call_id"])
    assert parent_call.error_code == outcome["error_code"]
    tampered_error_code = "TAMPERED_DE_TEMPLATE_ERROR"
    outcome["error_code"] = tampered_error_code
    payload["artifact_hashes"]["style_work_items"] = Orchestrator._json_hash(
        payload["artifact_refs"]["style_work_items"]
    )
    state.run_checkpoint_json = payload
    failed_attempt = next(
        attempt
        for attempt in session.execute(
            select(AttemptTracker).where(
                AttemptTracker.scene_id == "CH_RESUME_SC01",
                AttemptTracker.step == "de_template",
                AttemptTracker.status == "failed",
            )
        ).scalars()
        if (attempt.details_json or {}).get("llm_call_id") == parent_call.llm_call_id
    )
    failed_attempt.details_json = {
        **(failed_attempt.details_json or {}),
        "error_code": tampered_error_code,
    }
    session.commit()
    provider_calls = len(generation_client.requests)

    with pytest.raises(DomainError) as exc_info:
        Orchestrator(
            session,
            scene_generation_service=SceneGenerationService(session, llm_client=generation_client),
            hard_qc_engine=HardQcEngine(session, llm_client=_HardPassClient()),
            soft_qc_engine=_PassSoftQc(session),
            near_final_service=_FailNearFinal(),
        ).run_scene("CH_RESUME_SC01", execution_id=execution_id)

    assert exc_info.value.code == "RUN_CHECKPOINT_CORRUPT"
    assert len(generation_client.requests) == provider_calls


def test_best_of_n_resumes_candidate_de_template_without_replaying_its_base(session, monkeypatch) -> None:
    _seed_resume_scene(session)
    monkeypatch.setattr(Orchestrator, "_best_of_n_count", staticmethod(lambda contract, criticality=None: 2))
    monkeypatch.setattr(
        "novel_system.services.scene_generation._anti_template_quality_gate",
        lambda *args, **kwargs: {
            "triggered": True,
            "rewrite_pass": 1,
            "score": 0.0,
            "risk_dimensions": ["model_voice"],
            "quality_signal_ids": ["quality:candidate-resume-base"],
            "findings": [],
        },
    )
    generation_client = _CountingGenerationClient()
    execution_id = "idempotency:candidate-base-de-template-resume"
    first = Orchestrator(
        session,
        scene_generation_service=SceneGenerationService(session, llm_client=generation_client),
        hard_qc_engine=HardQcEngine(session, llm_client=_HardPassClient()),
        soft_qc_engine=_FailAfterStyle(),
    )
    original_reconcile = first._reconcile_execution_step

    def interrupt_first_candidate_de_template(step_key: str) -> None:
        original_reconcile(step_key)
        if step_key == "style_draft:0:de_template":
            raise RuntimeError("interrupt candidate after base")

    first._reconcile_execution_step = interrupt_first_candidate_de_template
    with pytest.raises(RuntimeError, match="interrupt candidate after base"):
        first.run_scene("CH_RESUME_SC01", execution_id=execution_id)

    state = session.get(SceneRunState, "CH_RESUME_SC01")
    items = state.run_checkpoint_json["artifact_refs"]["style_work_items"]
    assert state.run_checkpoint_json["sub_index"] == 0
    assert [(item["slot_key"], item["final"]) for item in items] == [("initial:0", None)]

    with pytest.raises(RuntimeError, match="fail after style checkpoint"):
        Orchestrator(
            session,
            scene_generation_service=SceneGenerationService(session, llm_client=generation_client),
            hard_qc_engine=HardQcEngine(session, llm_client=_HardPassClient()),
            soft_qc_engine=_FailAfterStyle(),
        ).run_scene("CH_RESUME_SC01", execution_id=execution_id)

    session.refresh(state)
    items = state.run_checkpoint_json["artifact_refs"]["style_work_items"]
    assert [item["slot_key"] for item in items] == ["initial:0", "initial:1"]
    assert all(item["de_template_outcome"]["status"] == "completed" for item in items)
    assert [request.node_id for request in generation_client.requests].count("style_draft") == 2
    assert [request.node_id for request in generation_client.requests].count("style_patch") == 2


def test_completed_candidate_de_template_survives_next_candidate_failure(session, monkeypatch) -> None:
    _seed_resume_scene(session)
    monkeypatch.setattr(Orchestrator, "_best_of_n_count", staticmethod(lambda contract, criticality=None: 2))
    monkeypatch.setattr(
        "novel_system.services.scene_generation._anti_template_quality_gate",
        lambda *args, **kwargs: {
            "triggered": True,
            "rewrite_pass": 1,
            "score": 0.0,
            "risk_dimensions": ["model_voice"],
            "quality_signal_ids": ["quality:next-candidate-failure"],
            "findings": [],
        },
    )
    generation_client = _FailFourthGenerationClient()
    execution_id = "idempotency:de-template-then-next-candidate-fails"

    def orchestrator() -> Orchestrator:
        return Orchestrator(
            session,
            scene_generation_service=SceneGenerationService(session, llm_client=generation_client),
            hard_qc_engine=HardQcEngine(session, llm_client=_HardPassClient()),
            soft_qc_engine=_FailAfterStyle(),
        )

    with pytest.raises(ValueError, match="next candidate failed after de-template"):
        orchestrator().run_scene("CH_RESUME_SC01", execution_id=execution_id)

    state = session.get(SceneRunState, "CH_RESUME_SC01")
    items = state.run_checkpoint_json["artifact_refs"]["style_work_items"]
    assert state.run_checkpoint_json["sub_index"] == 1
    assert len(items) == 1
    assert items[0]["de_template_outcome"]["status"] == "completed"
    completed_row_id = items[0]["final"]["row_id"]
    provider_calls = len(generation_client.requests)

    with pytest.raises(DomainError) as exc_info:
        orchestrator().run_scene("CH_RESUME_SC01", execution_id=execution_id)
    assert exc_info.value.code == "RUN_CHECKPOINT_OUTPUT_MISSING"
    assert len(generation_client.requests) == provider_calls
    session.refresh(state)
    assert state.run_checkpoint_json["artifact_refs"]["style_work_items"][0]["final"]["row_id"] == completed_row_id


def test_progressive_topup_resumes_its_locked_base_without_replay(session, monkeypatch) -> None:
    _seed_resume_scene(session)
    scene = session.get(SceneCard, "CH_RESUME_SC01")
    scene.constraint_intensity = 0.5
    session.commit()
    monkeypatch.setattr(Orchestrator, "_best_of_n_count", staticmethod(lambda contract, criticality=None: 2))
    monkeypatch.setattr("novel_system.services.scene_generation._candidate_dispersion", lambda contents: 0.0)
    monkeypatch.setattr(
        "novel_system.services.scene_generation._anti_template_quality_gate",
        lambda *args, **kwargs: {
            "triggered": True,
            "rewrite_pass": 1,
            "score": 0.0,
            "risk_dimensions": ["model_voice"],
            "quality_signal_ids": ["quality:topup-resume"],
            "findings": [],
        },
    )
    generation_client = _CountingGenerationClient()
    execution_id = "idempotency:topup-base-de-template-resume"
    first = Orchestrator(
        session,
        scene_generation_service=SceneGenerationService(session, llm_client=generation_client),
        hard_qc_engine=HardQcEngine(session, llm_client=_HardPassClient()),
        soft_qc_engine=_FailAfterStyle(),
    )
    original_reconcile = first._reconcile_execution_step

    def interrupt_topup_de_template(step_key: str) -> None:
        original_reconcile(step_key)
        if step_key == "style_draft:topup:1:de_template":
            raise RuntimeError("interrupt topup after base")

    first._reconcile_execution_step = interrupt_topup_de_template
    with pytest.raises(RuntimeError, match="interrupt topup after base"):
        first.run_scene("CH_RESUME_SC01", execution_id=execution_id)

    state = session.get(SceneRunState, "CH_RESUME_SC01")
    items = state.run_checkpoint_json["artifact_refs"]["style_work_items"]
    assert state.run_checkpoint_json["sub_index"] == 4
    assert [item["slot_key"] for item in items] == ["initial:0", "initial:1", "topup:1"]
    assert items[-1]["final"] is None

    with pytest.raises(RuntimeError, match="fail after style checkpoint"):
        Orchestrator(
            session,
            scene_generation_service=SceneGenerationService(session, llm_client=generation_client),
            hard_qc_engine=HardQcEngine(session, llm_client=_HardPassClient()),
            soft_qc_engine=_FailAfterStyle(),
        ).run_scene("CH_RESUME_SC01", execution_id=execution_id)

    session.refresh(state)
    items = state.run_checkpoint_json["artifact_refs"]["style_work_items"]
    assert items[-1]["de_template_outcome"]["status"] == "completed"
    assert [request.node_id for request in generation_client.requests].count("style_draft") == 3
    assert [request.node_id for request in generation_client.requests].count("style_patch") == 3


def test_no_anti_template_trigger_persists_base_equals_final(session, monkeypatch) -> None:
    _seed_resume_scene(session)
    monkeypatch.setattr(
        "novel_system.services.scene_generation._anti_template_quality_gate",
        lambda *args, **kwargs: {
            "triggered": False,
            "rewrite_pass": 0,
            "score": 1.0,
            "risk_dimensions": [],
            "quality_signal_ids": [],
            "findings": [],
        },
    )
    generation_client = _CountingGenerationClient()

    with pytest.raises(RuntimeError, match="fail after style checkpoint"):
        Orchestrator(
            session,
            scene_generation_service=SceneGenerationService(session, llm_client=generation_client),
            hard_qc_engine=HardQcEngine(session, llm_client=_HardPassClient()),
            soft_qc_engine=_FailAfterStyle(),
        ).run_scene("CH_RESUME_SC01", execution_id="idempotency:no-de-template-required")

    state = session.get(SceneRunState, "CH_RESUME_SC01")
    item = state.run_checkpoint_json["artifact_refs"]["style_work_items"][0]
    assert item["gate_decision"]["triggered"] is False
    assert item["de_template_outcome"] == {"status": "not_required"}
    assert item["base"]["row_id"] == item["final"]["row_id"]
    assert item["base"]["content_hash"] == item["final"]["content_hash"]
    assert item["base"]["llm_call_id"] == item["final"]["llm_call_id"]


@pytest.mark.parametrize(
    ("mutation", "expected_code"),
    [("delete", "RUN_CHECKPOINT_OUTPUT_MISSING"), ("tamper", "RUN_CHECKPOINT_CORRUPT")],
)
def test_completed_de_template_recovery_validates_its_base_lineage(
    session,
    monkeypatch,
    mutation: str,
    expected_code: str,
) -> None:
    _seed_resume_scene(session)
    monkeypatch.setattr(
        "novel_system.services.scene_generation._anti_template_quality_gate",
        lambda *args, **kwargs: {
            "triggered": True,
            "rewrite_pass": 1,
            "score": 0.0,
            "risk_dimensions": ["model_voice"],
            "quality_signal_ids": ["quality:lineage-validation"],
            "findings": [],
        },
    )
    generation_client = _CountingGenerationClient()
    execution_id = f"idempotency:de-template-lineage-{mutation}"

    with pytest.raises(RuntimeError, match="fail after style checkpoint"):
        Orchestrator(
            session,
            scene_generation_service=SceneGenerationService(session, llm_client=generation_client),
            hard_qc_engine=HardQcEngine(session, llm_client=_HardPassClient()),
            soft_qc_engine=_FailAfterStyle(),
        ).run_scene("CH_RESUME_SC01", execution_id=execution_id)

    state = session.get(SceneRunState, "CH_RESUME_SC01")
    item = state.run_checkpoint_json["artifact_refs"]["style_work_items"][0]
    assert item["base"]["row_id"] != item["final"]["row_id"]
    base = session.get(SceneDraft, item["base"]["row_id"])
    if mutation == "delete":
        session.delete(base)
    else:
        base.content = "tampered durable style base"
    session.commit()
    provider_calls = len(generation_client.requests)

    with pytest.raises(DomainError) as exc_info:
        Orchestrator(
            session,
            scene_generation_service=SceneGenerationService(session, llm_client=generation_client),
            hard_qc_engine=HardQcEngine(session, llm_client=_HardPassClient()),
            soft_qc_engine=_FailAfterStyle(),
        ).run_scene("CH_RESUME_SC01", execution_id=execution_id)
    assert exc_info.value.code == expected_code
    assert len(generation_client.requests) == provider_calls


def test_near_final_checkpoint_resume_archives_without_repeating_prior_nodes(session) -> None:
    _seed_resume_scene(session)
    generation_client = _CountingGenerationClient()
    soft_qc = _PassSoftQc(session)
    near_final = _PassNearFinal(session)

    def orchestrator() -> Orchestrator:
        return Orchestrator(
            session,
            scene_generation_service=SceneGenerationService(session, llm_client=generation_client),
            hard_qc_engine=HardQcEngine(session, llm_client=_HardPassClient()),
            soft_qc_engine=soft_qc,
            near_final_service=near_final,
        )

    first = orchestrator()
    first.archiver = _FailArchiveOnce()
    with pytest.raises(RuntimeError, match="fail after near-final checkpoint"):
        first.run_scene("CH_RESUME_SC01", execution_id="idempotency:near-final-resume")

    state = session.get(SceneRunState, "CH_RESUME_SC01")
    assert state is not None
    assert state.run_checkpoint == "near_final_ready"
    final_row_id = state.run_checkpoint_json["artifact_refs"]["final_scene_row_id"]
    provider_calls = len(generation_client.requests)

    result = orchestrator().run_scene(
        "CH_RESUME_SC01",
        execution_id="idempotency:near-final-resume",
    )

    assert result["scene_status"] == "archived"
    session.refresh(state)
    assert state.run_checkpoint == "archived"
    assert state.current_final_scene_row_id == final_row_id
    assert soft_qc.calls == 1
    assert near_final.calls == 1
    assert len(generation_client.requests) == provider_calls


def test_near_eval0_checkpoint_resumes_at_rewrite_without_replaying_eval0(session) -> None:
    _seed_resume_scene(session)
    generation_client = _CountingGenerationClient()
    soft_qc = _PassSoftQc(session)
    near_final = _SequencedNearFinal(
        session,
        {"near_final_acceptance:0": "rewrite", "near_final_acceptance:1": "pass"},
    )

    def orchestrator() -> Orchestrator:
        return Orchestrator(
            session,
            scene_generation_service=SceneGenerationService(session, llm_client=generation_client),
            hard_qc_engine=HardQcEngine(session, llm_client=_HardPassClient()),
            soft_qc_engine=soft_qc,
            near_final_service=near_final,
        )

    first = orchestrator()
    original_reconcile = first._reconcile_execution_step

    def stop_before_rewrite(step_key: str) -> None:
        if step_key == "near_final_rewrite:0":
            raise RuntimeError("stop after near eval0 checkpoint")
        original_reconcile(step_key)

    first._reconcile_execution_step = stop_before_rewrite
    with pytest.raises(RuntimeError, match="stop after near eval0 checkpoint"):
        first.run_scene("CH_RESUME_SC01", execution_id="idempotency:near-eval0-resume")

    state = session.get(SceneRunState, "CH_RESUME_SC01")
    assert state.run_checkpoint == "near_final_ready"
    assert state.run_checkpoint_json["sub_index"] == 0
    assert state.run_checkpoint_json["artifact_refs"]["near_eval0_evaluation_id"]
    provider_calls = len(generation_client.requests)

    resumed = orchestrator()
    resumed.archiver = _FailArchiveOnce()
    with pytest.raises(RuntimeError, match="fail after near-final checkpoint"):
        resumed.run_scene("CH_RESUME_SC01", execution_id="idempotency:near-eval0-resume")

    session.refresh(state)
    assert state.run_checkpoint_json["sub_index"] == 3
    assert near_final.calls == ["near_final_acceptance:0", "near_final_acceptance:1"]
    assert len(generation_client.requests) == provider_calls + 1
    assert len(
        session.execute(
            select(LlmCall).where(
                LlmCall.scene_id == "CH_RESUME_SC01",
                LlmCall.execution_step_key == "near_final_acceptance:0",
            )
        ).scalars().all()
    ) == 1


def test_near_rewrite_checkpoint_resumes_at_eval1_without_replaying_rewrite(session) -> None:
    _seed_resume_scene(session)
    generation_client = _CountingGenerationClient()
    soft_qc = _PassSoftQc(session)
    near_final = _SequencedNearFinal(
        session,
        {"near_final_acceptance:0": "rewrite", "near_final_acceptance:1": "pass"},
    )

    def orchestrator() -> Orchestrator:
        return Orchestrator(
            session,
            scene_generation_service=SceneGenerationService(session, llm_client=generation_client),
            hard_qc_engine=HardQcEngine(session, llm_client=_HardPassClient()),
            soft_qc_engine=soft_qc,
            near_final_service=near_final,
        )

    first = orchestrator()
    original_reconcile = first._reconcile_execution_step

    def stop_before_eval1(step_key: str) -> None:
        if step_key == "near_final_acceptance:1":
            raise RuntimeError("stop after near rewrite checkpoint")
        original_reconcile(step_key)

    first._reconcile_execution_step = stop_before_eval1
    with pytest.raises(RuntimeError, match="stop after near rewrite checkpoint"):
        first.run_scene("CH_RESUME_SC01", execution_id="idempotency:near-rewrite-resume")

    state = session.get(SceneRunState, "CH_RESUME_SC01")
    assert state.run_checkpoint == "near_final_ready"
    assert state.run_checkpoint_json["sub_index"] == 1
    rewrite_row_id = state.run_checkpoint_json["artifact_refs"]["near_rewrite_draft_row_id"]
    provider_calls = len(generation_client.requests)
    tokens_used = state.scene_tokens_used

    resumed = orchestrator()
    resumed.archiver = _FailArchiveOnce()
    with pytest.raises(RuntimeError, match="fail after near-final checkpoint"):
        resumed.run_scene("CH_RESUME_SC01", execution_id="idempotency:near-rewrite-resume")

    session.refresh(state)
    assert state.run_checkpoint_json["sub_index"] == 3
    assert state.run_checkpoint_json["artifact_refs"]["near_final_source_draft_row_id"] == rewrite_row_id
    assert near_final.calls == ["near_final_acceptance:0", "near_final_acceptance:1"]
    assert len(generation_client.requests) == provider_calls
    assert state.scene_tokens_used == tokens_used
    assert len(
        session.execute(
            select(LlmCall).where(
                LlmCall.scene_id == "CH_RESUME_SC01",
                LlmCall.execution_step_key == "near_final_rewrite:0",
            )
        ).scalars().all()
    ) == 1


def test_near_eval1_checkpoint_resumes_at_finalization_without_replaying_eval1(session) -> None:
    _seed_resume_scene(session)
    generation_client = _CountingGenerationClient()
    near_final = _SequencedNearFinal(
        session,
        {"near_final_acceptance:0": "rewrite", "near_final_acceptance:1": "pass"},
    )

    def orchestrator() -> Orchestrator:
        return Orchestrator(
            session,
            scene_generation_service=SceneGenerationService(session, llm_client=generation_client),
            hard_qc_engine=HardQcEngine(session, llm_client=_HardPassClient()),
            soft_qc_engine=_PassSoftQc(session),
            near_final_service=near_final,
        )

    first = orchestrator()

    def stop_after_eval1(*args, **kwargs):  # noqa: ANN002, ANN003, ANN202
        raise RuntimeError("stop after near eval1 checkpoint")

    first._near_final_warning_findings = stop_after_eval1
    with pytest.raises(RuntimeError, match="stop after near eval1 checkpoint"):
        first.run_scene("CH_RESUME_SC01", execution_id="idempotency:near-eval1-resume")

    state = session.get(SceneRunState, "CH_RESUME_SC01")
    assert state.run_checkpoint == "near_final_ready"
    assert state.run_checkpoint_json["sub_index"] == 2
    provider_calls = len(generation_client.requests)
    calls = list(near_final.calls)

    resumed = orchestrator()
    resumed.archiver = _FailArchiveOnce()
    with pytest.raises(RuntimeError, match="fail after near-final checkpoint"):
        resumed.run_scene("CH_RESUME_SC01", execution_id="idempotency:near-eval1-resume")

    session.refresh(state)
    assert state.run_checkpoint_json["sub_index"] == 3
    assert near_final.calls == calls
    assert len(generation_client.requests) == provider_calls


def test_near_final_budget_skip_completes_without_rewrite_or_eval_replay(session, monkeypatch) -> None:
    from novel_system.services import scene_budget

    _seed_resume_scene(session)
    monkeypatch.setattr(scene_budget, "can_spend", lambda *args, **kwargs: False)
    generation_client = _CountingGenerationClient()
    near_final = _SequencedNearFinal(session, {"near_final_acceptance:0": "rewrite"})
    orchestrator = Orchestrator(
        session,
        scene_generation_service=SceneGenerationService(session, llm_client=generation_client),
        hard_qc_engine=HardQcEngine(session, llm_client=_HardPassClient()),
        soft_qc_engine=_PassSoftQc(session),
        near_final_service=near_final,
    )
    orchestrator.archiver = _FailArchiveOnce()

    with pytest.raises(RuntimeError, match="fail after near-final checkpoint"):
        orchestrator.run_scene("CH_RESUME_SC01", execution_id="idempotency:near-budget-skip")

    state = session.get(SceneRunState, "CH_RESUME_SC01")
    refs = state.run_checkpoint_json["artifact_refs"]
    assert state.run_checkpoint_json["sub_index"] == 3
    assert refs["near_final_rewrite_count"] == 0
    assert refs["near_final_skip_reason"] == "budget_or_candidate_cap"
    assert refs.get("near_rewrite_draft_row_id") is None
    assert near_final.calls == ["near_final_acceptance:0"]
    assert len(generation_client.requests) == 2


def test_near_final_human_review_proposal_archives_without_eval_replay(session) -> None:
    _seed_resume_scene(session)
    generation_client = _CountingGenerationClient()
    near_final = _SequencedNearFinal(session, {"near_final_acceptance:0": "human"})

    def orchestrator() -> Orchestrator:
        return Orchestrator(
            session,
            scene_generation_service=SceneGenerationService(session, llm_client=generation_client),
            hard_qc_engine=HardQcEngine(session, llm_client=_HardPassClient()),
            soft_qc_engine=_PassSoftQc(session),
            near_final_service=near_final,
        )

    first = orchestrator()
    first.archiver = _FailArchiveOnce()
    with pytest.raises(RuntimeError, match="fail after near-final checkpoint"):
        first.run_scene("CH_RESUME_SC01", execution_id="idempotency:near-human-proposal")
    provider_calls = len(generation_client.requests)

    result = orchestrator().run_scene(
        "CH_RESUME_SC01",
        execution_id="idempotency:near-human-proposal",
    )

    assert result["scene_status"] == "archived"
    assert result["near_final"]["requires_human_review"] is True
    assert near_final.calls == ["near_final_acceptance:0"]
    assert len(generation_client.requests) == provider_calls


def test_strict_near_final_warning_resume_does_not_replay_eval(session) -> None:
    _seed_resume_scene(session)
    generation_client = _CountingGenerationClient()
    near_final = _SequencedNearFinal(session, {"near_final_acceptance:0": "human"})

    def orchestrator() -> Orchestrator:
        return Orchestrator(
            session,
            scene_generation_service=SceneGenerationService(session, llm_client=generation_client),
            hard_qc_engine=HardQcEngine(session, llm_client=_HardPassClient()),
            soft_qc_engine=_PassSoftQc(session),
            near_final_service=near_final,
        )

    first = orchestrator().run_scene(
        "CH_RESUME_SC01",
        run_policy="strict",
        execution_id="idempotency:near-strict-warning",
    )
    provider_calls = len(generation_client.requests)
    second = orchestrator().run_scene(
        "CH_RESUME_SC01",
        run_policy="strict",
        execution_id="idempotency:near-strict-warning",
    )

    state = session.get(SceneRunState, "CH_RESUME_SC01")
    assert first["scene_status"] == second["scene_status"] == "quality_warning_pending_acceptance"
    assert state.run_checkpoint == "near_final_ready"
    assert state.run_checkpoint_json["sub_index"] == 0
    assert state.current_final_scene_row_id is None
    assert near_final.calls == ["near_final_acceptance:0"]
    assert len(generation_client.requests) == provider_calls


def _completed_near_rewrite_checkpoint(session, execution_id: str):  # noqa: ANN201
    generation_client = _CountingGenerationClient()
    near_final = _SequencedNearFinal(
        session,
        {"near_final_acceptance:0": "rewrite", "near_final_acceptance:1": "pass"},
    )

    def orchestrator() -> Orchestrator:
        return Orchestrator(
            session,
            scene_generation_service=SceneGenerationService(session, llm_client=generation_client),
            hard_qc_engine=HardQcEngine(session, llm_client=_HardPassClient()),
            soft_qc_engine=_PassSoftQc(session),
            near_final_service=near_final,
        )

    first = orchestrator()
    first.archiver = _FailArchiveOnce()
    with pytest.raises(RuntimeError, match="fail after near-final checkpoint"):
        first.run_scene("CH_RESUME_SC01", execution_id=execution_id)
    return generation_client, near_final, orchestrator


def test_complete_near_prefix_missing_eval0_blocks_without_provider_replay(session) -> None:
    _seed_resume_scene(session)
    generation_client, near_final, orchestrator = _completed_near_rewrite_checkpoint(
        session,
        "idempotency:near-prefix-eval-missing",
    )
    state = session.get(SceneRunState, "CH_RESUME_SC01")
    eval0_id = state.run_checkpoint_json["artifact_refs"]["near_eval0_evaluation_id"]
    session.delete(session.get(WriterEvaluation, eval0_id))
    session.commit()
    provider_calls = len(generation_client.requests)
    calls = list(near_final.calls)

    with pytest.raises(DomainError) as missing:
        orchestrator().run_scene(
            "CH_RESUME_SC01",
            execution_id="idempotency:near-prefix-eval-missing",
        )

    assert missing.value.code == "RUN_CHECKPOINT_OUTPUT_MISSING"
    assert near_final.calls == calls
    assert len(generation_client.requests) == provider_calls


def test_complete_near_prefix_tampered_rewrite_blocks_without_provider_replay(session) -> None:
    _seed_resume_scene(session)
    generation_client, near_final, orchestrator = _completed_near_rewrite_checkpoint(
        session,
        "idempotency:near-prefix-rewrite-tamper",
    )
    state = session.get(SceneRunState, "CH_RESUME_SC01")
    rewrite_id = state.run_checkpoint_json["artifact_refs"]["near_rewrite_draft_row_id"]
    rewrite = session.get(SceneDraft, rewrite_id)
    rewrite.content += " tampered"
    session.commit()
    provider_calls = len(generation_client.requests)
    calls = list(near_final.calls)

    with pytest.raises(DomainError) as corrupt:
        orchestrator().run_scene(
            "CH_RESUME_SC01",
            execution_id="idempotency:near-prefix-rewrite-tamper",
        )

    assert corrupt.value.code == "RUN_CHECKPOINT_CORRUPT"
    assert near_final.calls == calls
    assert len(generation_client.requests) == provider_calls


def test_complete_near_prefix_missing_candidate_blocks_without_provider_replay(session) -> None:
    _seed_resume_scene(session)
    generation_client, near_final, orchestrator = _completed_near_rewrite_checkpoint(
        session,
        "idempotency:near-prefix-candidate-missing",
    )
    state = session.get(SceneRunState, "CH_RESUME_SC01")
    candidate_id = state.run_checkpoint_json["artifact_refs"]["near_eval0_revision_candidate_id"]
    session.delete(session.get(RevisionCandidate, candidate_id))
    session.commit()
    provider_calls = len(generation_client.requests)
    calls = list(near_final.calls)

    with pytest.raises(DomainError) as missing:
        orchestrator().run_scene(
            "CH_RESUME_SC01",
            execution_id="idempotency:near-prefix-candidate-missing",
        )

    assert missing.value.code == "RUN_CHECKPOINT_OUTPUT_MISSING"
    assert near_final.calls == calls
    assert len(generation_client.requests) == provider_calls


def test_near_final_resume_revalidates_complete_soft_prefix(session) -> None:
    _seed_resume_scene(session)
    generation_client = _CountingGenerationClient()
    near_final = _PassNearFinal(session)

    def orchestrator() -> Orchestrator:
        return Orchestrator(
            session,
            scene_generation_service=SceneGenerationService(session, llm_client=generation_client),
            hard_qc_engine=HardQcEngine(session, llm_client=_HardPassClient()),
            soft_qc_engine=_PassSoftQc(session),
            near_final_service=near_final,
        )

    first = orchestrator()
    first.archiver = _FailArchiveOnce()
    with pytest.raises(RuntimeError, match="fail after near-final checkpoint"):
        first.run_scene("CH_RESUME_SC01", execution_id="idempotency:near-soft-prefix")
    state = session.get(SceneRunState, "CH_RESUME_SC01")
    soft_qc0_id = state.run_checkpoint_json["artifact_refs"]["soft_qc0_report_id"]
    session.delete(session.get(QcReport, soft_qc0_id))
    session.commit()
    provider_calls = len(generation_client.requests)

    with pytest.raises(DomainError) as missing:
        orchestrator().run_scene("CH_RESUME_SC01", execution_id="idempotency:near-soft-prefix")

    assert missing.value.code == "RUN_CHECKPOINT_OUTPUT_MISSING"
    assert near_final.calls == 1
    assert len(generation_client.requests) == provider_calls


def test_post_archive_failure_retries_missing_side_effects_before_archived_checkpoint(session) -> None:
    _seed_resume_scene(session)
    generation_client = _CountingGenerationClient()

    def orchestrator() -> Orchestrator:
        return Orchestrator(
            session,
            scene_generation_service=SceneGenerationService(session, llm_client=generation_client),
            hard_qc_engine=HardQcEngine(session, llm_client=_HardPassClient()),
        )

    first = orchestrator()
    post_archive_attempts = 0

    def _fail_post_archive(*args, **kwargs):  # noqa: ANN002, ANN003, ANN202
        nonlocal post_archive_attempts
        post_archive_attempts += 1
        if post_archive_attempts == 1:
            raise RuntimeError("post archive failure")

    first._record_narrative_events = _fail_post_archive
    with pytest.raises(RuntimeError, match="post archive failure"):
        first.run_scene("CH_RESUME_SC01", execution_id="idempotency:archived-replay")

    state = session.get(SceneRunState, "CH_RESUME_SC01")
    assert state is not None
    assert state.run_checkpoint == "near_final_ready"
    assert state.run_execution_status == "failed"
    provider_calls = len(generation_client.requests)

    resumed = orchestrator()
    resumed._record_narrative_events = _fail_post_archive
    replay = resumed.run_scene(
        "CH_RESUME_SC01",
        execution_id="idempotency:archived-replay",
    )

    assert replay["scene_status"] == "archived"
    session.refresh(state)
    assert state.run_checkpoint == "archived"
    assert state.run_execution_status == "completed"
    assert post_archive_attempts == 2
    assert len(generation_client.requests) == provider_calls


def test_missing_soft_qc_checkpoint_row_blocks_without_repeating_provider(session) -> None:
    _seed_resume_scene(session)
    generation_client = _CountingGenerationClient()
    soft_qc = _PassSoftQc(session)
    near_final = _FailNearFinal()

    def orchestrator() -> Orchestrator:
        return Orchestrator(
            session,
            scene_generation_service=SceneGenerationService(session, llm_client=generation_client),
            hard_qc_engine=HardQcEngine(session, llm_client=_HardPassClient()),
            soft_qc_engine=soft_qc,
            near_final_service=near_final,
        )

    with pytest.raises(RuntimeError, match="fail after soft checkpoint"):
        orchestrator().run_scene("CH_RESUME_SC01", execution_id="idempotency:soft-missing")
    state = session.get(SceneRunState, "CH_RESUME_SC01")
    report_id = state.run_checkpoint_json["artifact_refs"]["soft_qc_report_id"]
    session.delete(session.get(QcReport, report_id))
    session.commit()
    provider_calls = len(generation_client.requests)

    with pytest.raises(DomainError) as missing:
        orchestrator().run_scene("CH_RESUME_SC01", execution_id="idempotency:soft-missing")
    assert missing.value.code == "RUN_CHECKPOINT_OUTPUT_MISSING"
    assert soft_qc.calls == 1
    assert len(generation_client.requests) == provider_calls


def test_corrupt_soft_qc_report_content_hash_blocks_without_repeating_provider(session) -> None:
    _seed_resume_scene(session)
    generation_client = _CountingGenerationClient()
    soft_qc = _PassSoftQc(session)
    near_final = _FailNearFinal()

    def orchestrator() -> Orchestrator:
        return Orchestrator(
            session,
            scene_generation_service=SceneGenerationService(session, llm_client=generation_client),
            hard_qc_engine=HardQcEngine(session, llm_client=_HardPassClient()),
            soft_qc_engine=soft_qc,
            near_final_service=near_final,
        )

    with pytest.raises(RuntimeError, match="fail after soft checkpoint"):
        orchestrator().run_scene("CH_RESUME_SC01", execution_id="idempotency:soft-report-corrupt")
    state = session.get(SceneRunState, "CH_RESUME_SC01")
    report_id = state.run_checkpoint_json["artifact_refs"]["soft_qc_report_id"]
    report = session.get(QcReport, report_id)
    report.rewrite_brief_json = [{"instruction": "tampered carry note"}]
    session.commit()
    provider_calls = len(generation_client.requests)

    with pytest.raises(DomainError) as corrupt:
        orchestrator().run_scene("CH_RESUME_SC01", execution_id="idempotency:soft-report-corrupt")

    assert corrupt.value.code == "RUN_CHECKPOINT_CORRUPT"
    assert soft_qc.calls == 1
    assert len(generation_client.requests) == provider_calls


def test_corrupt_near_final_checkpoint_source_blocks_without_repeating_provider(session) -> None:
    _seed_resume_scene(session)
    generation_client = _CountingGenerationClient()
    soft_qc = _PassSoftQc(session)
    near_final = _PassNearFinal(session)

    def orchestrator() -> Orchestrator:
        return Orchestrator(
            session,
            scene_generation_service=SceneGenerationService(session, llm_client=generation_client),
            hard_qc_engine=HardQcEngine(session, llm_client=_HardPassClient()),
            soft_qc_engine=soft_qc,
            near_final_service=near_final,
        )

    first = orchestrator()
    first.archiver = _FailArchiveOnce()
    with pytest.raises(RuntimeError, match="fail after near-final checkpoint"):
        first.run_scene("CH_RESUME_SC01", execution_id="idempotency:near-corrupt")
    state = session.get(SceneRunState, "CH_RESUME_SC01")
    final_row_id = state.run_checkpoint_json["artifact_refs"]["final_scene_row_id"]
    final_scene = session.get(FinalScene, final_row_id)
    final_scene.source_bundle_hash = "sha256:tampered"
    session.commit()
    provider_calls = len(generation_client.requests)

    with pytest.raises(DomainError) as corrupt:
        orchestrator().run_scene("CH_RESUME_SC01", execution_id="idempotency:near-corrupt")
    assert corrupt.value.code == "RUN_CHECKPOINT_CORRUPT"
    assert soft_qc.calls == 1
    assert near_final.calls == 1
    assert len(generation_client.requests) == provider_calls


def test_corrupt_near_final_carry_notes_hash_blocks_without_repeating_provider(session) -> None:
    _seed_resume_scene(session)
    generation_client = _CountingGenerationClient()
    soft_qc = _PassSoftQc(session)
    near_final = _PassNearFinal(session)

    def orchestrator() -> Orchestrator:
        return Orchestrator(
            session,
            scene_generation_service=SceneGenerationService(session, llm_client=generation_client),
            hard_qc_engine=HardQcEngine(session, llm_client=_HardPassClient()),
            soft_qc_engine=soft_qc,
            near_final_service=near_final,
        )

    first = orchestrator()
    first.archiver = _FailArchiveOnce()
    with pytest.raises(RuntimeError, match="fail after near-final checkpoint"):
        first.run_scene("CH_RESUME_SC01", execution_id="idempotency:near-carry-corrupt")
    state = session.get(SceneRunState, "CH_RESUME_SC01")
    payload = dict(state.run_checkpoint_json)
    refs = dict(payload["artifact_refs"])
    refs["carry_notes"] = [*(refs.get("carry_notes") or []), {"kind": "tampered"}]
    payload["artifact_refs"] = refs
    state.run_checkpoint_json = payload
    session.commit()
    provider_calls = len(generation_client.requests)

    with pytest.raises(DomainError) as corrupt:
        orchestrator().run_scene("CH_RESUME_SC01", execution_id="idempotency:near-carry-corrupt")

    assert corrupt.value.code == "RUN_CHECKPOINT_CORRUPT"
    assert soft_qc.calls == 1
    assert near_final.calls == 1
    assert len(generation_client.requests) == provider_calls


def test_corrupt_hard_qc_source_binding_blocks_checkpoint_resume(session) -> None:
    _seed_resume_scene(session)
    generation_client = _CountingGenerationClient()
    late_failure = _FailAfterStyle()

    def orchestrator() -> Orchestrator:
        return Orchestrator(
            session,
            scene_generation_service=SceneGenerationService(session, llm_client=generation_client),
            hard_qc_engine=HardQcEngine(session, llm_client=_HardPassClient()),
            soft_qc_engine=late_failure,
        )

    with pytest.raises(RuntimeError, match="fail after style checkpoint"):
        orchestrator().run_scene("CH_RESUME_SC01", execution_id="idempotency:hard-corrupt")
    state = session.get(SceneRunState, "CH_RESUME_SC01")
    hard_report_id = state.run_checkpoint_json["artifact_refs"]["qc_report_id"]
    report = session.get(QcReport, hard_report_id)
    report.source_draft_row_id = "draft_from_another_execution"
    session.commit()
    provider_calls = len(generation_client.requests)

    with pytest.raises(DomainError) as corrupt:
        orchestrator().run_scene("CH_RESUME_SC01", execution_id="idempotency:hard-corrupt")
    assert corrupt.value.code == "RUN_CHECKPOINT_CORRUPT"
    assert len(generation_client.requests) == provider_calls


def test_corrupt_soft_qc_decision_hash_blocks_checkpoint_resume(session) -> None:
    _seed_resume_scene(session)
    generation_client = _CountingGenerationClient()
    soft_qc = _PassSoftQc(session)
    near_final = _FailNearFinal()

    def orchestrator() -> Orchestrator:
        return Orchestrator(
            session,
            scene_generation_service=SceneGenerationService(session, llm_client=generation_client),
            hard_qc_engine=HardQcEngine(session, llm_client=_HardPassClient()),
            soft_qc_engine=soft_qc,
            near_final_service=near_final,
        )

    with pytest.raises(RuntimeError, match="fail after soft checkpoint"):
        orchestrator().run_scene("CH_RESUME_SC01", execution_id="idempotency:soft-corrupt")
    state = session.get(SceneRunState, "CH_RESUME_SC01")
    checkpoint = dict(state.run_checkpoint_json)
    refs = dict(checkpoint["artifact_refs"])
    refs["soft_qc_branch"] = "waive"
    checkpoint["artifact_refs"] = refs
    state.run_checkpoint_json = checkpoint
    session.commit()
    provider_calls = len(generation_client.requests)

    with pytest.raises(DomainError) as corrupt:
        orchestrator().run_scene("CH_RESUME_SC01", execution_id="idempotency:soft-corrupt")
    assert corrupt.value.code == "RUN_CHECKPOINT_CORRUPT"
    assert soft_qc.calls == 1
    assert len(generation_client.requests) == provider_calls


def test_provider_owner_lease_tracks_each_request_timeout_and_restores_default(session, monkeypatch) -> None:
    _seed_resume_scene(session)
    events: list[tuple[str, int]] = []

    class _TimeoutClient:
        def generate(self, request: LLMRequest) -> LLMResponse:
            events.append(("provider", int(request.timeout_seconds or 0)))
            return _response({"scene_text": "timeout lease"}, f"timeout-{request.timeout_seconds}")

    def _budget(**kwargs):  # noqa: ANN003, ANN202
        return {"budget": kwargs["base_budget"], "continuity_warning": {}}

    monkeypatch.setattr("novel_system.services.llm_task_runner.finalize_request_budget", _budget)

    def _task(timeout_seconds: int) -> SimpleNamespace:
        return SimpleNamespace(
            model="fake-model",
            temperature=0.2,
            max_output_tokens=128,
            response_format="json_object",
            provider="fake-provider",
            timeout_seconds=timeout_seconds,
            provider_id="provider-1",
            account_id="account-1",
            reasoning_level="medium",
            api_mode="responses",
            credential_mode=None,
            provider_options={},
        )

    routes = SimpleNamespace(
        node_routing={"short": _task(10), "long": _task(70)},
        task_routing={},
    )
    runner = LLMNodeRunner(session, llm_client=_TimeoutClient(), routing_config=routes)

    def _renew(*, lease_seconds: int) -> None:
        events.append(("lease", lease_seconds))

    token = begin_llm_execution("exec-timeout", lease_renewer=_renew)
    try:
        for node_id in ("short", "long"):
            runner.run(
                scene_id="CH_RESUME_SC01",
                chapter_id="CH_RESUME",
                bundle_id="bundle-timeout",
                bundle_hash="sha256:timeout",
                node_id=node_id,
                step=node_id,
                prompt={
                    "system_prompt": "system",
                    "token_budget": {},
                    "template_name": node_id,
                    "template_version": "v1",
                },
                user_prompt="user",
                offline_client_factory=lambda: _TimeoutClient(),
            )
    finally:
        end_llm_execution(token)

    grace = owner_lease_grace_seconds()
    default_ttl = owner_lease_ttl_seconds()
    assert events == [
        ("lease", max(default_ttl, 10 + grace)),
        ("provider", 10),
        ("lease", default_ttl),
        ("lease", max(default_ttl, 70 + grace)),
        ("provider", 70),
        ("lease", default_ttl),
    ]


def test_owner_lease_envelope_never_shrinks_default_and_covers_all_llm_retries(monkeypatch) -> None:
    monkeypatch.setattr("novel_system.services.idempotency.owner_lease_ttl_seconds", lambda: 30)
    monkeypatch.setattr("novel_system.services.idempotency.owner_lease_grace_seconds", lambda: 5)

    assert _execution_owner_lease_seconds(
        request_timeout_seconds=10,
        client=object(),
    ) == 30

    client = LLMClient(
        provider="openai_compatible",
        base_url="https://provider.invalid/v1",
        api_key="test",
        timeout_seconds=70,
        max_retries=2,
        retry_backoff_seconds=1.0,
    )
    physical_attempts = (2 + 1) * (3 + 1)
    backoff_envelope = int((3 + 1) * 2 * 30 * 1.2)
    assert _execution_owner_lease_seconds(
        request_timeout_seconds=70,
        client=client,
    ) >= physical_attempts * 70 + backoff_envelope + 5


def test_dispatch_truth_allows_predispatch_retry_but_blocks_unknown_provider_outcome(session, monkeypatch) -> None:
    _seed_resume_scene(session)

    def _budget(**kwargs):  # noqa: ANN003, ANN202
        return {"budget": kwargs["base_budget"], "continuity_warning": {}}

    monkeypatch.setattr("novel_system.services.llm_task_runner.finalize_request_budget", _budget)
    task = SimpleNamespace(
        model="fake-model",
        temperature=0.2,
        max_output_tokens=128,
        response_format="json_object",
        provider="fake-provider",
        timeout_seconds=10,
        provider_id="provider-1",
        account_id="account-1",
        reasoning_level="medium",
        api_mode="responses",
        credential_mode=None,
        provider_options={},
    )
    routes = SimpleNamespace(node_routing={"dispatch-test": task}, task_routing={})
    prompt = {
        "system_prompt": "system",
        "token_budget": {},
        "template_name": "dispatch-test",
        "template_version": "v1",
    }

    class _MustNotDispatch:
        def generate(self, request):  # noqa: ANN001, ANN201
            raise AssertionError("provider must not be called")

    def _lost_before_dispatch(*, lease_seconds: int) -> None:
        raise DomainError("RUN_OWNER_LEASE_LOST", "lost before provider", status_code=409)

    token = begin_llm_execution("exec-predispatch", lease_renewer=_lost_before_dispatch)
    try:
        with pytest.raises(LLMNodeExecutionError):
            LLMNodeRunner(session, llm_client=_MustNotDispatch(), routing_config=routes).run(
                scene_id="CH_RESUME_SC01",
                chapter_id="CH_RESUME",
                bundle_id="bundle-dispatch",
                bundle_hash="sha256:dispatch",
                node_id="dispatch-test",
                step="dispatch-test",
                prompt=prompt,
                user_prompt="user",
                offline_client_factory=_MustNotDispatch,
            )
    finally:
        end_llm_execution(token)
    pre_call = session.execute(
        select(LlmCall).where(LlmCall.execution_id == "exec-predispatch")
    ).scalar_one()
    assert pre_call.request_dispatched_at is None
    assert pre_call.accounting_status == "rejected"
    assert SceneRunCheckpointService(session).reconcile_step_output(
        scene_id="CH_RESUME_SC01",
        execution_id="exec-predispatch",
        execution_step_key="dispatch-test",
        output_exists=False,
    ) == "retry"

    class _UnknownProviderOutcome:
        def generate(self, request):  # noqa: ANN001, ANN201
            raise TimeoutError("provider outcome unknown")

    token = begin_llm_execution("exec-dispatched")
    try:
        with pytest.raises(LLMNodeExecutionError):
            LLMNodeRunner(session, llm_client=_UnknownProviderOutcome(), routing_config=routes).run(
                scene_id="CH_RESUME_SC01",
                chapter_id="CH_RESUME",
                bundle_id="bundle-dispatch",
                bundle_hash="sha256:dispatch",
                node_id="dispatch-test",
                step="dispatch-test",
                prompt=prompt,
                user_prompt="user",
                offline_client_factory=_UnknownProviderOutcome,
            )
    finally:
        end_llm_execution(token)
    dispatched_call = session.execute(
        select(LlmCall).where(LlmCall.execution_id == "exec-dispatched")
    ).scalar_one()
    assert dispatched_call.request_dispatched_at is not None
    with pytest.raises(DomainError) as unknown:
        SceneRunCheckpointService(session).reconcile_step_output(
            scene_id="CH_RESUME_SC01",
            execution_id="exec-dispatched",
            execution_step_key="dispatch-test",
            output_exists=False,
        )
    assert unknown.value.code == "RUN_CHECKPOINT_OUTPUT_MISSING"


def test_real_pipeline_blocks_settled_ledger_before_repeating_neutral_provider(session) -> None:
    _seed_resume_scene(session)
    execution_id = "idempotency:settled-narrow-window"
    with pytest.raises(RuntimeError, match="stop at bundle checkpoint"):
        Orchestrator(session, scene_generation_service=_FailBeforeNeutral()).run_scene(
            "CH_RESUME_SC01",
            execution_id=execution_id,
        )
    state = session.get(SceneRunState, "CH_RESUME_SC01")
    assert state.run_checkpoint == "bundle_ready"
    session.add(
        LlmCall(
            llm_call_id="settled-neutral-window",
            scope_type="scene",
            scope_id="CH_RESUME_SC01",
            provider="fake",
            model="fake",
            node_id="neutral_draft",
            step="neutral_draft",
            scene_id="CH_RESUME_SC01",
            chapter_id="CH_RESUME",
            execution_id=execution_id,
            execution_step_key="neutral_draft",
            accounting_status="settled",
            request_dispatched_at="2026-07-13T00:00:00+00:00",
            settled_at="2026-07-13T00:00:01+00:00",
        )
    )
    session.commit()
    generation_client = _CountingGenerationClient()

    with pytest.raises(DomainError) as blocked:
        Orchestrator(
            session,
            scene_generation_service=SceneGenerationService(session, llm_client=generation_client),
        ).run_scene("CH_RESUME_SC01", execution_id=execution_id)
    assert blocked.value.code == "RUN_CHECKPOINT_OUTPUT_MISSING"
    assert generation_client.requests == []


def test_real_pipeline_releases_undispatched_reservation_then_calls_neutral_once(session) -> None:
    _seed_resume_scene(session)
    execution_id = "idempotency:reserved-narrow-window"
    with pytest.raises(RuntimeError, match="stop at bundle checkpoint"):
        Orchestrator(session, scene_generation_service=_FailBeforeNeutral()).run_scene(
            "CH_RESUME_SC01",
            execution_id=execution_id,
        )
    state = session.get(SceneRunState, "CH_RESUME_SC01")
    state.scene_tokens_reserved = 20
    session.add(
        LlmCall(
            llm_call_id="reserved-neutral-window",
            scope_type="scene",
            scope_id="CH_RESUME_SC01",
            provider="fake",
            model="fake",
            node_id="neutral_draft",
            step="neutral_draft",
            scene_id="CH_RESUME_SC01",
            chapter_id="CH_RESUME",
            execution_id=execution_id,
            execution_step_key="neutral_draft",
            estimated_tokens=20,
            reserved_tokens=20,
            accounting_status="reserved",
            request_dispatched_at=None,
        )
    )
    session.add(
        LlmCallAttempt(
            attempt_id="attempt-reserved-neutral-window",
            llm_call_id="reserved-neutral-window",
            provider_attempt_no=0,
            dispatch_kind="initial",
            request_max_output_tokens=10,
            estimated_tokens=20,
            reserved_tokens=20,
            accounting_status="reserved",
            request_dispatched_at=None,
        )
    )
    session.commit()
    generation_client = _CountingGenerationClient()

    with pytest.raises(RuntimeError, match="stop after neutral retry"):
        Orchestrator(
            session,
            scene_generation_service=SceneGenerationService(session, llm_client=generation_client),
            hard_qc_engine=_FailBeforeHardQc(),
        ).run_scene("CH_RESUME_SC01", execution_id=execution_id)

    session.refresh(state)
    reserved_call = session.get(LlmCall, "reserved-neutral-window")
    assert reserved_call.accounting_status == "released"
    assert state.scene_tokens_reserved == 0
    assert state.run_checkpoint == "neutral_ready"
    assert len(generation_client.requests) == 1
