"""ValidationOrchestrator — sync_only / async_full 双路径(PR-7 §7.1)。

sync_only:仅 plag + forbidden_local,毫秒级落 report → 立返完整 sync_result。
async_full:落 pending report(verdict 空)+ ThreadPoolExecutor 起后台 thread
跑 quant + semantic + plag + forbid_semantic,主线程立即返 polling_url。
"""

from __future__ import annotations

import logging
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from sqlalchemy import update
from sqlalchemy.orm import Session

from novel_system.db.models import StyleReferenceValidationReport, utcnow
from novel_system.db.session import SessionLocal
from novel_system.services.llm_accounting import (
    LLMAccountingError,
    is_llm_control_plane_failure,
)
from novel_system.services.errors import DomainError
from novel_system.services.style_reference._llm_helper import LLMNodeError
from novel_system.services.style_reference.repository import StyleReferenceRepository
from novel_system.services.style_reference.schemas import (
    ValidateRequest,
    ValidateResponse,
    ValidationMode,
    ValidationReport,
    ValidationTargetKind,
)

logger = logging.getLogger(__name__)


# 模块级单 worker;PR-7 简化(SQLite 写并发本就受限)
_EXECUTOR = ThreadPoolExecutor(max_workers=2, thread_name_prefix="sr_validate")


class ValidationOrchestrator:
    """sync/async 双路径 validation 编排。"""

    def __init__(
        self,
        session: Session,
        *,
        llm_client: Any | None = None,
        llm_enabled: bool | None = None,
    ) -> None:
        self.session = session
        self.repo = StyleReferenceRepository(session)
        self._llm_client = llm_client
        if llm_enabled is None:
            from novel_system.settings import get_settings

            llm_enabled = bool(get_settings().llm_enabled)
        self._llm_enabled = llm_enabled

    def validate(self, profile_id: str, req: ValidateRequest) -> ValidateResponse:
        import time as _time

        from novel_system.services.style_reference.metrics_recorder import MetricsRecorder

        profile = self.repo.get_profile(profile_id)
        if profile is None:
            raise DomainError(
                "STYLE_REFERENCE_PROFILE_NOT_FOUND",
                f"profile {profile_id!r} not found",
                status_code=404,
            )

        started_at = _time.perf_counter()
        if req.mode == ValidationMode.SYNC_ONLY:
            response = self._run_sync_only(profile_id, profile, req)
        else:
            response = self._run_async_full(profile_id, profile, req)
        latency_ms = int((_time.perf_counter() - started_at) * 1000)

        # PR-10 §13 — sync_only 知道 verdict;async_full 此时只立返 polling_url,
        # outcome="dispatched"(后台 worker 完成后另写 completed 事件较复杂,本 PR 不做)
        outcome = (
            response.sync_result.verdict.value if response.sync_result is not None else "dispatched"
        )
        MetricsRecorder.record(
            self.session,
            "validation_executed",
            target_kind=req.target_kind.value if req.target_kind else None,
            target_ref_id=req.target_ref_id,
            profile_id=profile_id,
            outcome=outcome,
            latency_ms=latency_ms,
            context={"mode": req.mode.value},
        )
        return response

    # ---------------------------------------------------------- sync_only

    def _run_sync_only(self, profile_id: str, profile, req: ValidateRequest) -> ValidateResponse:
        from novel_system.services.style_reference.validation import run_sync_validate

        report = run_sync_validate(req.generated_text, profile, self.session)
        report_id = self._persist_report(
            profile_id=profile_id,
            req=req,
            verdict=report.verdict.value,
            mode=ValidationMode.SYNC_ONLY,
            quantitative_json=report.quantitative_json,
            semantic_json=[],
            plagiarism_json=report.plagiarism_json,
            forbidden_hits_json=report.forbidden_hits_json,
        )
        return ValidateResponse(
            report_id=report_id,
            mode_executed=ValidationMode.SYNC_ONLY,
            sync_result=report,
            polling_url=None,
        )

    # --------------------------------------------------------- async_full

    def _run_async_full(self, profile_id: str, profile, req: ValidateRequest) -> ValidateResponse:
        # 先落 pending report(verdict="" 表示 pending)
        report_id = self._persist_report(
            profile_id=profile_id,
            req=req,
            verdict="",
            mode=ValidationMode.ASYNC_FULL,
            quantitative_json=[],
            semantic_json=[],
            plagiarism_json={},
            forbidden_hits_json=[],
        )
        # 释放主 session 缓存,确保后台 thread 看到最新行
        self.session.commit()

        # 起后台 thread;捕获参数 by value(不能传 session)
        _EXECUTOR.submit(
            _async_worker,
            report_id=report_id,
            profile_id=profile_id,
            generated_text=req.generated_text,
            llm_client=self._llm_client,
            llm_enabled=self._llm_enabled,
        )

        return ValidateResponse(
            report_id=report_id,
            mode_executed=ValidationMode.ASYNC_FULL,
            sync_result=None,
            polling_url=f"/api/v2/style-reference/reports/{report_id}",
        )

    # ------------------------------------------------------------ persist

    def _persist_report(
        self,
        *,
        profile_id: str,
        req: ValidateRequest,
        verdict: str,
        mode: ValidationMode,
        quantitative_json: list,
        semantic_json: list,
        plagiarism_json: dict,
        forbidden_hits_json: list,
    ) -> str:
        report_id = f"sr_rep_{uuid.uuid4().hex[:12]}"
        target_kind = (
            req.target_kind.value
            if isinstance(req.target_kind, ValidationTargetKind)
            else str(req.target_kind)
        )
        self.repo.create_validation_report(
            report_id=report_id,
            profile_id=profile_id,
            target_kind=target_kind,
            target_ref_id=req.target_ref_id,
            verdict=verdict,
            quantitative_json=quantitative_json,
            semantic_json=semantic_json,
            plagiarism_json=plagiarism_json,
            forbidden_hits_json=forbidden_hits_json,
            mode_executed=mode.value,
            status=("completed" if mode == ValidationMode.SYNC_ONLY else "queued"),
            retryable=False,
            started_at=(utcnow() if mode == ValidationMode.SYNC_ONLY else None),
            heartbeat_at=utcnow(),
            finished_at=(utcnow() if mode == ValidationMode.SYNC_ONLY else None),
        )
        return report_id


def _async_worker(
    *,
    report_id: str,
    profile_id: str,
    generated_text: str,
    llm_client: Any | None,
    llm_enabled: bool,
) -> None:
    """Run async validation after winning the durable queued->running CAS."""

    from novel_system.services.style_reference.policy import cloud_llm_allowed
    from novel_system.services.style_reference.validation import (
        _compute_full_verdict,
        _load_plagiarism_corpus,
        check_forbidden_semantic,
        check_plagiarism,
        check_quantitative,
        check_semantic,
    )
    from novel_system.services.style_reference.validation.forbidden_local import (
        check_forbidden_local,
    )

    try:
        with SessionLocal() as bg_session:
            claimed_at = utcnow()
            claimed = bg_session.execute(
                update(StyleReferenceValidationReport)
                .where(
                    StyleReferenceValidationReport.report_id == report_id,
                    StyleReferenceValidationReport.status == "queued",
                )
                .values(
                    status="running",
                    started_at=claimed_at,
                    heartbeat_at=claimed_at,
                    finished_at=None,
                    error_code=None,
                    error_text=None,
                    retryable=False,
                )
                .execution_options(synchronize_session=False)
            )
            if claimed.rowcount != 1:
                bg_session.rollback()
                logger.info("async validation %s dispatch was already claimed", report_id)
                return
            bg_session.commit()

            bg_repo = StyleReferenceRepository(bg_session)
            profile = bg_repo.get_profile(profile_id)
            if profile is None:
                raise DomainError(
                    "STYLE_REFERENCE_PROFILE_NOT_FOUND",
                    "style reference profile disappeared before validation started",
                    status_code=404,
                )

            corpus = _load_plagiarism_corpus(bg_repo, profile.book_id)
            plag = check_plagiarism(generated_text, corpus)
            forbid_local = check_forbidden_local(generated_text, profile_id, bg_session)
            quant = check_quantitative(generated_text, profile)
            _heartbeat_report(bg_session, report_id)

            book = bg_repo.get_book(profile.book_id)
            policy_allows_llm = cloud_llm_allowed(book) if book is not None else True
            semantic: list = []
            forbid_sem: list = []
            semantic_degraded = False
            if llm_enabled and llm_client is not None and policy_allows_llm:
                try:
                    semantic = check_semantic(
                        generated_text,
                        profile,
                        bg_session,
                        llm_client,
                        report_id=report_id,
                    )
                except Exception as exc:  # pylint: disable=broad-except
                    if isinstance(exc, LLMAccountingError) or is_llm_control_plane_failure(exc):
                        raise
                    if not isinstance(exc, LLMNodeError):
                        raise
                    semantic_degraded = True
                    logger.warning("async_worker semantic failed: %s", exc)
                _heartbeat_report(bg_session, report_id)
                try:
                    forbid_sem = check_forbidden_semantic(
                        generated_text,
                        profile,
                        bg_session,
                        llm_client,
                        report_id=report_id,
                    )
                except Exception as exc:  # pylint: disable=broad-except
                    if isinstance(exc, LLMAccountingError) or is_llm_control_plane_failure(exc):
                        raise
                    if not isinstance(exc, LLMNodeError):
                        raise
                    semantic_degraded = True
                    logger.warning("async_worker forbidden_semantic failed: %s", exc)
                _heartbeat_report(bg_session, report_id)

            all_forbid = list(forbid_local) + list(forbid_sem)
            verdict = _compute_full_verdict(
                quant=quant,
                semantic=semantic,
                plag=plag,
                forbid=all_forbid,
                semantic_degraded=semantic_degraded,
            )
            finished_at = utcnow()
            completed = bg_session.execute(
                update(StyleReferenceValidationReport)
                .where(
                    StyleReferenceValidationReport.report_id == report_id,
                    StyleReferenceValidationReport.status == "running",
                )
                .values(
                    verdict=verdict.value,
                    status="completed",
                    quantitative_json=[q.model_dump() for q in quant],
                    semantic_json=[s.model_dump() for s in semantic],
                    plagiarism_json=plag.model_dump(),
                    forbidden_hits_json=[h.model_dump() for h in all_forbid],
                    heartbeat_at=finished_at,
                    finished_at=finished_at,
                    error_code=None,
                    error_text=None,
                    retryable=False,
                )
                .execution_options(synchronize_session=False)
            )
            if completed.rowcount != 1:
                bg_session.rollback()
                logger.warning("async validation %s lost its running state", report_id)
                return
            bg_session.commit()
    except Exception as exc:  # pylint: disable=broad-except
        logger.exception("async_worker fatal: %s", exc)
        _mark_validation_failed(report_id, exc)


def _heartbeat_report(session: Session, report_id: str) -> None:
    """Publish progress without persisting any copy of the validated prose."""

    touched = session.execute(
        update(StyleReferenceValidationReport)
        .where(
            StyleReferenceValidationReport.report_id == report_id,
            StyleReferenceValidationReport.status == "running",
        )
        .values(heartbeat_at=utcnow())
        .execution_options(synchronize_session=False)
    )
    if touched.rowcount != 1:
        session.rollback()
        raise DomainError(
            "STYLE_REFERENCE_VALIDATION_OWNER_LOST",
            "async validation no longer owns its report",
            status_code=409,
        )
    session.commit()


def _mark_validation_failed(report_id: str, exc: Exception) -> None:
    if isinstance(exc, LLMAccountingError) or is_llm_control_plane_failure(exc):
        error_code = "STYLE_REFERENCE_VALIDATION_CONTROL_PLANE_FAILED"
    elif isinstance(exc, DomainError):
        error_code = exc.code
    else:
        error_code = "STYLE_REFERENCE_VALIDATION_FAILED"
    try:
        with SessionLocal() as session:
            finished_at = utcnow()
            failed = session.execute(
                update(StyleReferenceValidationReport)
                .where(
                    StyleReferenceValidationReport.report_id == report_id,
                    StyleReferenceValidationReport.status.in_(("queued", "running")),
                )
                .values(
                    verdict="fail",
                    status="failed",
                    error_code=error_code,
                    error_text="async validation failed; submit the text again to retry",
                    retryable=True,
                    heartbeat_at=finished_at,
                    finished_at=finished_at,
                )
                .execution_options(synchronize_session=False)
            )
            if failed.rowcount:
                session.commit()
            else:
                session.rollback()
    except Exception:  # pragma: no cover - final worker boundary
        logger.exception("failed to persist async validation failure for %s", report_id)
