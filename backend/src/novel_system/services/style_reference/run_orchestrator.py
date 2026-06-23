"""RunOrchestrator — Style Reference 抽取 run 编排。

§14:启动 run + LLMRequiredError + 按 layers 调度四层 extractor
(language / narrative / scene / theme,见 _LAYER_EXTRACTOR_MAP),默认四层全跑。
"""

from __future__ import annotations

import logging
import random
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy.orm import Session

from novel_system.services.errors import DomainError
from novel_system.services.style_reference.dimensions import Layer
from novel_system.services.style_reference.errors import LLMRequiredError
from novel_system.services.style_reference.extractors import (
    BaseExtractor,
    ExtractionRetryPolicy,
    ExtractionRunResult,
    LanguageExtractor,
    NarrativeExtractor,
    SceneExtractor,
    ThemeExtractor,
)
from novel_system.services.style_reference.policy import ensure_cloud_llm_allowed
from novel_system.services.style_reference.repository import StyleReferenceRepository
from novel_system.services.style_reference.schemas import RunPhase, RunStatus

logger = logging.getLogger(__name__)

# RUNNING 超过该时长的 run 视为僵尸(进程崩溃 / 连接中断遗留),
# 下次同书启动新 run 时自动降级 FAILED,避免永久卡死。
STALE_RUN_TIMEOUT_MINUTES = 60

# 后台抽取串行执行(单 worker):抽取是重 LLM 负载,串行同时规避 SQLite 写争用;
# 排队中的 run 保持 RUNNING + progress.layers_done=0,由僵尸回收兜底。
_RUN_EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="sr_extract")


# layer.value → BaseExtractor 子类
_LAYER_EXTRACTOR_MAP: dict[Layer, type[BaseExtractor]] = {
    Layer.LANGUAGE: LanguageExtractor,
    Layer.NARRATIVE: NarrativeExtractor,
    Layer.SCENE: SceneExtractor,
    Layer.THEME: ThemeExtractor,
}


@dataclass
class RunResult:
    """run 编排执行后的摘要。"""

    run_id: str
    book_id: str
    status: str
    layers: list[str] = field(default_factory=list)
    sub_dim_results: list[ExtractionRunResult] = field(default_factory=list)


class RunOrchestrator:
    """启动 run + 按 layers 调度 extractors + 落 4 表 + 更新 run.status。"""

    def __init__(
        self,
        session: Session,
        *,
        llm_client: Any | None = None,
        llm_enabled: bool | None = None,
        retry_policy: ExtractionRetryPolicy | None = None,
        rng: random.Random | None = None,
    ) -> None:
        self.session = session
        self.repo = StyleReferenceRepository(session)
        self._llm_client = llm_client
        if llm_enabled is None:
            from novel_system.settings import get_settings

            llm_enabled = bool(get_settings().llm_enabled)
        self._llm_enabled = llm_enabled
        self._retry_policy = retry_policy or ExtractionRetryPolicy()
        self._rng = rng or random.Random()

    def start_extract_run(
        self,
        book_id: str,
        *,
        layers: list[Layer] | None = None,
        idempotency_key: str | None = None,  # noqa: ARG002 (预留 PR-4 路由层接入)
        background: bool = False,
    ) -> RunResult:
        """启动一次抽取 run;LLM 不可用 raise DomainError(STYLE_REFERENCE_LLM_REQUIRED)。

        ``background=True`` 时立即返回 RUNNING 的 RunResult,抽取在后台线程
        独立 session 中执行;调用方轮询 ``GET /runs/{run_id}`` 读取
        ``coverage_json["progress"]``(按 layer 粒度)与最终状态。
        """
        if not self._llm_enabled or self._llm_client is None:
            raise LLMRequiredError(operation="start_extract_run")

        book = self.repo.get_book(book_id)
        if book is None:
            raise DomainError(
                "STYLE_REFERENCE_BOOK_NOT_FOUND",
                f"book {book_id!r} not found",
                status_code=404,
            )
        # 附录 B — local_only 的书禁止把段落送往云端 LLM
        ensure_cloud_llm_allowed(book, operation="start_extract_run")
        # 僵尸 run 回收:同书遗留的超时 RUNNING run 降级 FAILED
        self._reap_stale_runs(book_id)

        layers = layers or [Layer.LANGUAGE, Layer.NARRATIVE, Layer.SCENE, Layer.THEME]
        unknown = [layer for layer in layers if layer not in _LAYER_EXTRACTOR_MAP]
        if unknown:
            raise DomainError(
                "STYLE_REFERENCE_LAYER_NOT_SUPPORTED",
                f"unsupported style-reference layer(s): {unknown!r}; "
                f"supported = {[layer.value for layer in _LAYER_EXTRACTOR_MAP]}",
                status_code=400,
            )

        run_id = f"sr_run_{uuid.uuid4().hex[:12]}"
        self.repo.create_run(
            run_id=run_id,
            book_id=book_id,
            status=RunStatus.RUNNING.value,
            phase=RunPhase.EXTRACT.value,
            coverage_json={
                "progress": {
                    "layers_total": len(layers),
                    "layers_done": 0,
                    "current_layer": layers[0].value,
                }
            },
            started_at=_utcnow_iso(),
        )

        if not background:
            return self._execute(run_id, book_id, layers, progress_commits=False)

        # 后台模式:先把 run 行落盘,worker 用独立 session 接管
        self.session.commit()
        _RUN_EXECUTOR.submit(
            _background_run_worker,
            run_id=run_id,
            book_id=book_id,
            layer_values=[layer.value for layer in layers],
            llm_client=self._llm_client,
            retry_policy=self._retry_policy,
        )
        return RunResult(
            run_id=run_id,
            book_id=book_id,
            status=RunStatus.RUNNING.value,
            layers=[layer.value for layer in layers],
            sub_dim_results=[],
        )

    def _execute(
        self,
        run_id: str,
        book_id: str,
        layers: list[Layer],
        *,
        progress_commits: bool,
    ) -> RunResult:
        """逐层执行抽取并更新 run 状态。

        ``progress_commits=True``(后台模式)时每层完成后 commit 进度,并在
        层边界协作响应 cancel;inline 模式不做中间 commit(整请求单事务,
        失败可整体回滚)。
        """
        sub_dim_results: list[ExtractionRunResult] = []
        try:
            for i, layer in enumerate(layers):
                if progress_commits and self._is_cancelled(run_id):
                    self.repo.update_run(
                        run_id,
                        status=RunStatus.CANCELLED.value,
                        finished_at=_utcnow_iso(),
                    )
                    self.session.commit()
                    return RunResult(
                        run_id=run_id,
                        book_id=book_id,
                        status=RunStatus.CANCELLED.value,
                        layers=[la.value for la in layers],
                        sub_dim_results=sub_dim_results,
                    )
                self._write_progress(run_id, layers, layers_done=i, current=layer)
                if progress_commits:
                    self.session.commit()
                extractor_cls = _LAYER_EXTRACTOR_MAP[layer]
                extractor = extractor_cls(
                    self.session,
                    self._llm_client,
                    run_id=run_id,
                    book_id=book_id,
                    retry_policy=self._retry_policy,
                    rng=self._rng,
                )
                sub_dim_results.extend(extractor.extract_all_sub_dimensions())
        except Exception:
            self.repo.update_run(
                run_id, status=RunStatus.FAILED.value, finished_at=_utcnow_iso()
            )
            if progress_commits:
                self.session.commit()
            raise

        run = self.repo.get_run(run_id)
        coverage = dict(run.coverage_json or {}) if run is not None else {}
        coverage["progress"] = {
            "layers_total": len(layers),
            "layers_done": len(layers),
            "current_layer": None,
        }
        coverage["sub_dimensions"] = {
            r.sub_dimension.value: {
                "findings": len(r.findings),
                "extractions": r.extractions_created,
            }
            for r in sub_dim_results
        }
        self.repo.update_run(
            run_id,
            status=RunStatus.DONE.value,
            phase=RunPhase.DONE.value,
            finished_at=_utcnow_iso(),
            coverage_json=coverage,
        )
        if progress_commits:
            self.session.commit()

        return RunResult(
            run_id=run_id,
            book_id=book_id,
            status=RunStatus.DONE.value,
            layers=[layer.value for layer in layers],
            sub_dim_results=sub_dim_results,
        )

    def _is_cancelled(self, run_id: str) -> bool:
        run = self.repo.get_run(run_id)
        if run is None:
            return True
        # 后台 session:refresh 拿到其他事务提交的 cancel
        self.session.refresh(run)
        return run.status == RunStatus.CANCELLED.value

    def _write_progress(
        self,
        run_id: str,
        layers: list[Layer],
        *,
        layers_done: int,
        current: Layer | None,
    ) -> None:
        run = self.repo.get_run(run_id)
        if run is None:
            return
        coverage = dict(run.coverage_json or {})
        coverage["progress"] = {
            "layers_total": len(layers),
            "layers_done": layers_done,
            "current_layer": current.value if current is not None else None,
        }
        self.repo.update_run(run_id, coverage_json=coverage)

    def _reap_stale_runs(self, book_id: str) -> int:
        """把同书超时仍 RUNNING 的僵尸 run 降级 FAILED,返回回收数量。

        run 在 HTTP 请求内同步执行;RUNNING 超过 STALE_RUN_TIMEOUT_MINUTES
        只可能是进程崩溃 / 连接中断遗留,不存在仍在执行的可能。
        """
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=STALE_RUN_TIMEOUT_MINUTES)
        reaped = 0
        for run in self.repo.list_runs(book_id=book_id, status=RunStatus.RUNNING.value):
            started = _parse_iso(run.started_at or run.created_at)
            if started is None or started > cutoff:
                continue
            self.repo.update_run(
                run.run_id,
                status=RunStatus.FAILED.value,
                finished_at=_utcnow_iso(),
                coverage_json={
                    **(run.coverage_json or {}),
                    "failure_reason": "stale_running_reaped",
                },
            )
            reaped += 1
            logger.warning("reaped stale RUNNING run %s (book %s)", run.run_id, book_id)
        return reaped


def _background_run_worker(
    *,
    run_id: str,
    book_id: str,
    layer_values: list[str],
    llm_client: Any,
    retry_policy: ExtractionRetryPolicy,
) -> None:
    """后台抽取入口:独立 session 执行 _execute(progress_commits=True)。

    _execute 自身已在异常路径把 run 标 FAILED 并 commit;此处兜底捕获
    (含 session 构造失败),保证线程不带异常退出。
    """
    from novel_system.db.session import SessionLocal

    try:
        with SessionLocal() as session:
            orch = RunOrchestrator(
                session,
                llm_client=llm_client,
                llm_enabled=True,
                retry_policy=retry_policy,
            )
            orch._execute(
                run_id,
                book_id,
                [Layer(value) for value in layer_values],
                progress_commits=True,
            )
    except Exception:  # pylint: disable=broad-except
        logger.exception("background extract run %s failed", run_id)


def _utcnow_iso() -> str:
    from novel_system.db.models import utcnow

    return utcnow()


def _parse_iso(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        parsed = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed
