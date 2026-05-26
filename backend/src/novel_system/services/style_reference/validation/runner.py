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

from sqlalchemy.orm import Session

from novel_system.db.session import SessionLocal
from novel_system.services.errors import DomainError
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
        profile = self.repo.get_profile(profile_id)
        if profile is None:
            raise DomainError(
                "STYLE_REFERENCE_PROFILE_NOT_FOUND",
                f"profile {profile_id!r} not found",
                status_code=404,
            )

        if req.mode == ValidationMode.SYNC_ONLY:
            return self._run_sync_only(profile_id, profile, req)
        return self._run_async_full(profile_id, profile, req)

    # ---------------------------------------------------------- sync_only

    def _run_sync_only(self, profile_id: str, profile, req: ValidateRequest) -> ValidateResponse:
        from novel_system.services.style_reference.validation import run_sync_validate

        report = run_sync_validate(req.generated_text, profile, self.session)
        report_id = self._persist_report(
            profile_id=profile_id,
            req=req,
            verdict=report.verdict.value,
            mode=ValidationMode.SYNC_ONLY,
            quantitative_json=[],
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
    """后台 thread 入口:独立 session,跑 4 路,更新 report 行。"""
    from novel_system.services.style_reference.validation import (
        _compute_full_verdict,
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
            bg_repo = StyleReferenceRepository(bg_session)
            profile = bg_repo.get_profile(profile_id)
            if profile is None:
                logger.warning("async_worker: profile %s vanished", profile_id)
                return

            quotes = [q.quote_text for q in bg_repo.list_quotes(profile.book_id)]
            plag = check_plagiarism(generated_text, quotes)
            forbid_local = check_forbidden_local(generated_text, profile_id, bg_session)
            quant = check_quantitative(generated_text, profile)

            semantic: list = []
            forbid_sem: list = []
            if llm_enabled and llm_client is not None:
                try:
                    semantic = check_semantic(generated_text, profile, llm_client)
                except Exception as exc:  # pylint: disable=broad-except
                    logger.warning("async_worker semantic failed: %s", exc)
                try:
                    forbid_sem = check_forbidden_semantic(
                        generated_text, profile, bg_session, llm_client
                    )
                except Exception as exc:  # pylint: disable=broad-except
                    logger.warning("async_worker forbidden_semantic failed: %s", exc)

            all_forbid = list(forbid_local) + list(forbid_sem)
            verdict = _compute_full_verdict(
                quant=quant, semantic=semantic, plag=plag, forbid=all_forbid
            )

            row = bg_repo.get_validation_report(report_id)
            if row is None:
                logger.warning("async_worker: report %s vanished", report_id)
                return
            row.verdict = verdict.value
            row.quantitative_json = [q.model_dump() for q in quant]
            row.semantic_json = [s.model_dump() for s in semantic]
            row.plagiarism_json = plag.model_dump()
            row.forbidden_hits_json = [h.model_dump() for h in all_forbid]
            bg_session.flush()
            bg_session.commit()
    except Exception as exc:  # pylint: disable=broad-except
        logger.exception("async_worker fatal: %s", exc)
        try:
            with SessionLocal() as fb_session:
                fb_row = fb_session.get(
                    __import__(
                        "novel_system.db.models", fromlist=["StyleReferenceValidationReport"]
                    ).StyleReferenceValidationReport,
                    report_id,
                )
                if fb_row is not None:
                    fb_row.verdict = "fail"
                    fb_session.commit()
        except Exception:  # pylint: disable=broad-except
            pass
