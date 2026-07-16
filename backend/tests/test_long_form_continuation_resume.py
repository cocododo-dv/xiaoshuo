from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace

import pytest

from novel_system.db.models import (
    AttemptTracker,
    ChapterGoal,
    LlmCall,
    SceneCard,
    SceneDraft,
    SceneRunState,
    StoryProject,
)
from novel_system.services.llm_task_runner import (
    begin_llm_execution,
    current_llm_execution_id,
    end_llm_execution,
)
from novel_system.services.errors import DomainError
from novel_system.services.scene_generation import SceneGenerationService
from novel_system.services.scene_run_checkpoint import SceneRunCheckpointService


def _scene() -> SceneCard:
    return SceneCard(
        scene_id="CH_CONT_SC01",
        chapter_id="CH_CONT",
        project_id="PROJ_CONT",
        scene_seq=1,
        pov_character_id="CHAR_A",
        onstage_chars_json=["CHAR_A"],
        location="checkpoint room",
        scene_goal="continue durably",
        beats_json=["segment", "resume"],
        must_include_text="",
        target_length_band="long",
        scene_type="reveal",
        is_chapter_last=0,
    )


def _bundle() -> dict[str, object]:
    return {
        "bundle_id": "bundle_CH_CONT_SC01_v1",
        "bundle_snapshot_hash": "bundle_hash_continuation_resume",
        "snapshot": {"scene_id": "CH_CONT_SC01"},
    }


class _PromptBuilder:
    def build(self, snapshot, template_name):  # noqa: ANN001
        return {
            "template_name": template_name,
            "template_version": "test",
            "system_prompt": "BASE_SYSTEM",
            "user_prompt": "BASE_USER",
            "structured_schema": {
                "type": "object",
                "required": ["scene_text"],
                "properties": {"scene_text": {"type": "string"}},
            },
            "token_budget": {
                "target_input_tokens": 1000,
                "estimated_input_tokens": 0,
                "remaining_input_tokens": 1000,
            },
        }


class _SegmentLedgerRunner:
    def __init__(self, session, scene: SceneCard, *, fail_once_step: str | None = None) -> None:
        self.session = session
        self.scene = scene
        self.fail_once_step = fail_once_step
        self.failed_once = False
        self.calls: list[str] = []

    def run(self, **kwargs):  # noqa: ANN003
        step_key = kwargs["execution_step_key"]
        self.calls.append(step_key)
        if step_key == self.fail_once_step and not self.failed_once:
            self.failed_once = True
            raise ValueError("segment two failed once")
        index = int(step_key.rsplit(":", 1)[-1])
        llm_call_id = f"llm_call_cont_segment_{index}"
        self.session.add(
            LlmCall(
                llm_call_id=llm_call_id,
                provider="fake",
                model="fake",
                step="long_form_continuation",
                scene_id=self.scene.scene_id,
                chapter_id=self.scene.chapter_id,
                scope_type="scene",
                scope_id=self.scene.scene_id,
                execution_id=current_llm_execution_id(),
                execution_step_key=step_key,
                estimated_tokens=3,
                reserved_tokens=3,
                budget_charged_tokens=3,
                prompt_tokens=1,
                completion_tokens=2,
                total_tokens=3,
                accounting_status="settled",
                request_dispatched_at="2026-07-14T00:00:00+00:00",
                settled_at="2026-07-14T00:00:01+00:00",
            )
        )
        self.session.flush()
        return SimpleNamespace(
            llm_call_id=llm_call_id,
            response=SimpleNamespace(structured_output={"scene_text": f"segment-{index}"}),
        )


def _service(session, monkeypatch, *, fail_once_step: str | None = None):  # noqa: ANN201
    scene = _scene()
    session.add(StoryProject(project_id=scene.project_id, title="Continuation", outline_text=""))
    session.add(
        ChapterGoal(
            chapter_id=scene.chapter_id,
            project_id=scene.project_id,
            planned_scene_count=1,
            chapter_goal="continue durably",
        )
    )
    session.add(scene)
    session.add(SceneRunState(scene_id=scene.scene_id, scene_status="ready"))
    session.flush()
    runner = _SegmentLedgerRunner(session, scene, fail_once_step=fail_once_step)
    service = SceneGenerationService(session, llm_runner=runner)
    service._prompt_builder_instance = _PromptBuilder()
    monkeypatch.setattr(
        "novel_system.services.scene_generation.get_llm_node_spec",
        lambda node_id: SimpleNamespace(refresh_every_chars=10),
    )
    return scene, runner, service


def test_long_form_continuation_resumes_from_first_missing_segment(session, monkeypatch) -> None:
    scene, runner, service = _service(
        session,
        monkeypatch,
        fail_once_step="long_form_continuation:1",
    )
    checkpoints: list[tuple[object, dict]] = []
    reconciled: list[str] = []
    refresh_contexts: list[str] = []
    original_inject = service._inject_style_reference

    def record_refresh(prompt, scene_arg, **kwargs):  # noqa: ANN001, ANN003
        refresh_contexts.append(kwargs.get("context_text") or "")
        return original_inject(prompt, scene_arg, **kwargs)

    monkeypatch.setattr(service, "_inject_style_reference", record_refresh)

    def checkpoint(index, segment_result, cumulative_descriptor):  # noqa: ANN001
        assert index == segment_result.segment_index
        checkpoints.append((segment_result, deepcopy(cumulative_descriptor)))
        session.commit()

    token = begin_llm_execution("exec-continuation-resume")
    try:
        with pytest.raises(ValueError, match="segment two failed once"):
            service.generate_long_form_continuation(
                scene.scene_id,
                _bundle(),
                source_draft_row_id="draft_style_source",
                source_content="source",
                target_continuation_chars=25,
                segment_checkpoint=checkpoint,
                step_reconciler=reconciled.append,
            )
        session.rollback()
        assert len(checkpoints) == 1
        first_run_refresh_count = len(refresh_contexts)
        first_call = session.get(LlmCall, checkpoints[0][0].llm_call_id)
        first_call_accounting = (
            first_call.accounting_status,
            first_call.reserved_tokens,
            first_call.budget_charged_tokens,
            first_call.total_tokens,
        )

        result = service.generate_long_form_continuation(
            scene.scene_id,
            _bundle(),
            source_draft_row_id="draft_style_source",
            source_content="source",
            target_continuation_chars=25,
            segment_checkpoint=checkpoint,
            step_reconciler=reconciled.append,
            resume_segments=[checkpoints[0][0]],
            resume_cumulative_descriptor=checkpoints[0][1],
        )
    finally:
        end_llm_execution(token)

    assert runner.calls == [
        "long_form_continuation:0",
        "long_form_continuation:1",
        "long_form_continuation:1",
        "long_form_continuation:2",
    ]
    assert reconciled == runner.calls
    retry_refreshes = refresh_contexts[first_run_refresh_count:]
    assert retry_refreshes[0] == "source"
    assert retry_refreshes[1].endswith("source\nsegment-0")
    assert result.content == "segment-0segment-1segment-2"
    assert session.query(SceneDraft).filter_by(stage="long_form_continuation_segment").count() == 3
    session.refresh(first_call)
    assert (
        first_call.accounting_status,
        first_call.reserved_tokens,
        first_call.budget_charged_tokens,
        first_call.total_tokens,
    ) == first_call_accounting
    assert session.query(LlmCall).filter_by(execution_step_key="long_form_continuation:0").count() == 1
    assert sum(
        1
        for attempt in session.query(AttemptTracker).filter_by(
            scene_id=scene.scene_id,
            step="long_form_continuation",
            status="completed",
        )
        if (attempt.details_json or {}).get("segment_index") == 0
    ) == 1


def _durable_segments_then_fail_finalization(session, monkeypatch):  # noqa: ANN201
    scene, runner, service = _service(session, monkeypatch)
    checkpoints: list[tuple[object, dict]] = []

    def checkpoint(index, segment_result, cumulative_descriptor):  # noqa: ANN001
        checkpoints.append((segment_result, deepcopy(cumulative_descriptor)))
        session.commit()

    def reconcile(_step_key: str) -> None:
        return None

    original_finalize = service._persist_long_form_final
    failed_once = False

    def fail_finalization_once(**kwargs):  # noqa: ANN003
        nonlocal failed_once
        if not failed_once:
            failed_once = True
            raise RuntimeError("finalization failed after all segments")
        return original_finalize(**kwargs)

    monkeypatch.setattr(service, "_persist_long_form_final", fail_finalization_once)
    token = begin_llm_execution("exec-continuation-finalization")
    try:
        with pytest.raises(RuntimeError, match="finalization failed after all segments"):
            service.generate_long_form_continuation(
                scene.scene_id,
                _bundle(),
                source_draft_row_id="draft_style_source",
                source_content="source",
                target_continuation_chars=25,
                segment_checkpoint=checkpoint,
                step_reconciler=reconcile,
            )
    finally:
        end_llm_execution(token)
    session.rollback()
    assert len(checkpoints) == 3
    return scene, runner, service, checkpoints, checkpoint, reconcile


def test_long_form_finalization_retry_reuses_all_durable_segments(session, monkeypatch) -> None:
    scene, runner, service, checkpoints, checkpoint, reconcile = _durable_segments_then_fail_finalization(
        session,
        monkeypatch,
    )
    provider_calls = list(runner.calls)
    base_call_rows = session.query(LlmCall).count()
    segment_attempt_rows = session.query(SceneDraft).filter_by(stage="long_form_continuation_segment").count()
    token = begin_llm_execution("exec-continuation-finalization")
    try:
        result = service.generate_long_form_continuation(
            scene.scene_id,
            _bundle(),
            source_draft_row_id="draft_style_source",
            source_content="source",
            target_continuation_chars=25,
            segment_checkpoint=checkpoint,
            step_reconciler=reconcile,
            resume_segments=[item[0] for item in checkpoints],
            resume_cumulative_descriptor=checkpoints[-1][1],
        )
    finally:
        end_llm_execution(token)

    assert runner.calls == provider_calls
    assert session.query(LlmCall).count() == base_call_rows
    assert session.query(SceneDraft).filter_by(stage="long_form_continuation_segment").count() == segment_attempt_rows
    assert result.content == "segment-0segment-1segment-2"
    assert session.query(SceneDraft).filter_by(stage="long_form_continuation").one().content == result.content


@pytest.mark.parametrize(
    ("mutation", "expected_code"),
    [("missing", "RUN_CHECKPOINT_OUTPUT_MISSING"), ("tampered", "RUN_CHECKPOINT_CORRUPT")],
)
def test_long_form_resume_rejects_missing_or_tampered_segment(
    session,
    monkeypatch,
    mutation: str,
    expected_code: str,
) -> None:
    from novel_system.services.errors import DomainError

    scene, runner, service, checkpoints, checkpoint, reconcile = _durable_segments_then_fail_finalization(
        session,
        monkeypatch,
    )
    row = session.get(SceneDraft, checkpoints[1][0].row_id)
    if mutation == "missing":
        session.delete(row)
    else:
        row.content = "tampered segment"
    session.commit()
    provider_calls = list(runner.calls)
    token = begin_llm_execution("exec-continuation-finalization")
    try:
        with pytest.raises(DomainError) as exc_info:
            service.generate_long_form_continuation(
                scene.scene_id,
                _bundle(),
                source_draft_row_id="draft_style_source",
                source_content="source",
                target_continuation_chars=25,
                segment_checkpoint=checkpoint,
                step_reconciler=reconcile,
                resume_segments=[item[0] for item in checkpoints],
                resume_cumulative_descriptor=checkpoints[-1][1],
            )
    finally:
        end_llm_execution(token)
    assert exc_info.value.code == expected_code
    assert runner.calls == provider_calls


@pytest.mark.parametrize("changed_parameter", ["target", "refresh"])
def test_long_form_resume_rejects_changed_generation_parameters(
    session,
    monkeypatch,
    changed_parameter: str,
) -> None:
    from novel_system.services.errors import DomainError

    scene, runner, service, checkpoints, checkpoint, reconcile = _durable_segments_then_fail_finalization(
        session,
        monkeypatch,
    )
    provider_calls = list(runner.calls)
    target_chars = 35 if changed_parameter == "target" else 25
    if changed_parameter == "refresh":
        monkeypatch.setattr(
            "novel_system.services.scene_generation.get_llm_node_spec",
            lambda node_id: SimpleNamespace(refresh_every_chars=5),
        )
    token = begin_llm_execution("exec-continuation-finalization")
    try:
        with pytest.raises(DomainError) as exc_info:
            service.generate_long_form_continuation(
                scene.scene_id,
                _bundle(),
                source_draft_row_id="draft_style_source",
                source_content="source",
                target_continuation_chars=target_chars,
                segment_checkpoint=checkpoint,
                step_reconciler=reconcile,
                resume_segments=[item[0] for item in checkpoints],
                resume_cumulative_descriptor=checkpoints[-1][1],
            )
    finally:
        end_llm_execution(token)
    assert exc_info.value.code == "RUN_CHECKPOINT_CORRUPT"
    assert runner.calls == provider_calls


def test_durable_long_form_reconciles_settled_missing_segment_before_provider(
    session,
    monkeypatch,
) -> None:
    scene, runner, service = _service(session, monkeypatch)
    execution_id = "exec-continuation-settled-missing"
    session.add(
        LlmCall(
            llm_call_id="llm_call_cont_settled_missing_0",
            provider="fake",
            model="fake",
            step="long_form_continuation",
            scene_id=scene.scene_id,
            chapter_id=scene.chapter_id,
            scope_type="scene",
            scope_id=scene.scene_id,
            execution_id=execution_id,
            execution_step_key="long_form_continuation:0",
            estimated_tokens=3,
            reserved_tokens=3,
            budget_charged_tokens=3,
            prompt_tokens=1,
            completion_tokens=2,
            total_tokens=3,
            accounting_status="settled",
            request_dispatched_at="2026-07-14T00:00:00+00:00",
            settled_at="2026-07-14T00:00:01+00:00",
        )
    )
    session.commit()
    reconciled: list[str] = []

    def reconcile(step_key: str) -> None:
        reconciled.append(step_key)
        SceneRunCheckpointService(session).reconcile_step_output(
            scene_id=scene.scene_id,
            execution_id=execution_id,
            execution_step_key=step_key,
            output_exists=False,
        )

    token = begin_llm_execution(execution_id)
    try:
        with pytest.raises(DomainError) as exc_info:
            service.generate_long_form_continuation(
                scene.scene_id,
                _bundle(),
                source_draft_row_id="draft_style_source",
                source_content="source",
                target_continuation_chars=25,
                segment_checkpoint=lambda *args: session.commit(),
                step_reconciler=reconcile,
            )
    finally:
        end_llm_execution(token)

    assert exc_info.value.code == "RUN_CHECKPOINT_OUTPUT_MISSING"
    assert reconciled == ["long_form_continuation:0"]
    assert runner.calls == []


def test_durable_long_form_callback_requires_step_reconciler(session, monkeypatch) -> None:
    scene, runner, service = _service(session, monkeypatch)
    token = begin_llm_execution("exec-continuation-missing-reconciler")
    try:
        with pytest.raises(DomainError) as exc_info:
            service.generate_long_form_continuation(
                scene.scene_id,
                _bundle(),
                source_draft_row_id="draft_style_source",
                source_content="source",
                target_continuation_chars=25,
                segment_checkpoint=lambda *args: session.commit(),
            )
    finally:
        end_llm_execution(token)

    assert exc_info.value.code == "RUN_CHECKPOINT_CORRUPT"
    assert runner.calls == []


def test_durable_long_form_step_reconciler_requires_checkpoint_callback(session, monkeypatch) -> None:
    scene, runner, service = _service(session, monkeypatch)
    token = begin_llm_execution("exec-continuation-missing-checkpoint")
    try:
        with pytest.raises(DomainError) as exc_info:
            service.generate_long_form_continuation(
                scene.scene_id,
                _bundle(),
                source_draft_row_id="draft_style_source",
                source_content="source",
                target_continuation_chars=25,
                step_reconciler=lambda _step_key: None,
            )
    finally:
        end_llm_execution(token)

    assert exc_info.value.code == "RUN_CHECKPOINT_CORRUPT"
    assert runner.calls == []


@pytest.mark.parametrize(
    "resume_kwargs",
    (
        {"resume_segments": [SimpleNamespace(row_id="missing-segment")]},
        {"resume_cumulative_descriptor": {"descriptor_hash": "non-empty"}},
    ),
)
def test_long_form_resume_inputs_require_durable_callback_pair(
    session,
    monkeypatch,
    resume_kwargs: dict,
) -> None:
    scene, runner, service = _service(session, monkeypatch)
    token = begin_llm_execution("exec-continuation-resume-contract")
    try:
        with pytest.raises(DomainError) as exc_info:
            service.generate_long_form_continuation(
                scene.scene_id,
                _bundle(),
                source_draft_row_id="draft_style_source",
                source_content="source",
                target_continuation_chars=25,
                **resume_kwargs,
            )
    finally:
        end_llm_execution(token)

    assert exc_info.value.code == "RUN_CHECKPOINT_CORRUPT"
    assert runner.calls == []


def test_legacy_long_form_without_callback_remains_compatible(session, monkeypatch) -> None:
    scene, runner, service = _service(session, monkeypatch)
    token = begin_llm_execution("exec-continuation-legacy")
    try:
        result = service.generate_long_form_continuation(
            scene.scene_id,
            _bundle(),
            source_draft_row_id="draft_style_source",
            source_content="source",
            target_continuation_chars=25,
        )
    finally:
        end_llm_execution(token)

    assert result.content == "segment-0segment-1segment-2"
    assert runner.calls == [
        "long_form_continuation:0",
        "long_form_continuation:1",
        "long_form_continuation:2",
    ]
