"""隔离、可断点续跑的 Style Reference 真实生成基准。

执行链严格复用产品服务：启发式摄取训练作品 → LLM 四层抽取 → Profile 合成 →
项目绑定 → neutral_draft → style_draft。基准数据库独立于用户主库；每个生成单元
完成后原子写 checkpoint，24 个单元不因中途失败全部作废。
"""

from __future__ import annotations

import hashlib
import json
import random
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from novel_system.db.base import Base
from novel_system.db.models import (
    ChapterGoal,
    ChapterState,
    LlmCall,
    SceneCard,
    SceneDraft,
    SceneRunState,
    StoryProject,
)
from novel_system.services.bundle_builder import BundleBuilder
from novel_system.services.errors import DomainError
from novel_system.services.llm_client import (
    LLMRequest,
    LLMResponse,
    OnlineAccountedExecution,
)
from novel_system.services.llm_providers.base import LLMAttemptHook
from novel_system.services.scene_generation import (
    SceneGenerationService,
    versioned_scene_artifact_id,
)
from novel_system.services.style_reference.benchmark.manifest import (
    STYLE_BENCHMARK_SCHEMA_VERSION,
    BenchmarkAuthor,
    BenchmarkCase,
    StyleBenchmarkError,
    StyleBenchmarkManifest,
    hash_text,
)
from novel_system.services.style_reference.benchmark.workspace import write_json
from novel_system.services.style_reference.ingest import IngestService
from novel_system.services.style_reference.materialization import MaterializationService
from novel_system.services.style_reference.profile_synthesizer import ProfileSynthesizer
from novel_system.services.style_reference.repository import StyleReferenceRepository
from novel_system.services.style_reference.run_orchestrator import RunOrchestrator
from novel_system.services.style_reference.schemas import (
    BindingScope,
    BindingStatus,
    InjectionStrategy,
    RunStatus,
    TaskType,
)


ProgressCallback = Callable[[str, Mapping[str, Any]], None]


@dataclass(frozen=True, slots=True)
class RecordedPrompt:
    node_id: str
    model: str
    provider: str | None
    messages: tuple[dict[str, Any], ...]

    @property
    def text(self) -> str:
        parts = []
        for message in self.messages:
            role = str(message.get("role") or "unknown").upper()
            parts.append(f"[{role}]\n{message.get('content') or ''}")
        return "\n\n".join(parts)


class PromptRecordingClient(OnlineAccountedExecution):
    """转发真实 accounted client，同时只在内存保留本次运行实际提示词。"""

    def __init__(self, delegate: OnlineAccountedExecution) -> None:
        self.delegate = delegate
        self.records: list[RecordedPrompt] = []

    def generate_accounted(
        self,
        request: LLMRequest,
        *,
        accounting_hook: LLMAttemptHook,
    ) -> LLMResponse:
        self.records.append(
            RecordedPrompt(
                node_id=str(request.node_id or ""),
                model=request.model,
                provider=request.provider,
                messages=tuple(deepcopy(request.messages)),
            )
        )
        return self.delegate.generate_accounted(
            request, accounting_hook=accounting_hook
        )

    def __getattr__(self, name: str) -> Any:
        return getattr(self.delegate, name)

    def prompt_for_call(
        self, session: Session, llm_call_id: str, *, since: int
    ) -> RecordedPrompt:
        call = session.get(LlmCall, llm_call_id)
        if call is None:
            raise StyleBenchmarkError(f"生成调用审计行不存在: {llm_call_id}")
        candidates = [
            record for record in self.records[since:] if record.node_id == call.node_id
        ]
        if not candidates:
            raise StyleBenchmarkError(f"未捕获生成调用的实际提示词: {llm_call_id}")
        return candidates[-1]

    def combined_prompt_text(self, *, since: int) -> str:
        records = self.records[since:]
        if not records:
            raise StyleBenchmarkError("生成步骤没有捕获到任何实际提示词")
        return "\n\n".join(
            f"[LLM_CALL {index + 1} node={record.node_id}]\n{record.text}"
            for index, record in enumerate(records)
        )


class StyleBenchmarkLiveRunner:
    def __init__(
        self,
        session: Session,
        manifest: StyleBenchmarkManifest,
        *,
        llm_client: OnlineAccountedExecution,
        results_path: str | Path,
        resume: bool = False,
        progress: ProgressCallback | None = None,
    ) -> None:
        self.session = session
        self.manifest = manifest
        self.client = (
            llm_client
            if isinstance(llm_client, PromptRecordingClient)
            else PromptRecordingClient(llm_client)
        )
        self.results_path = Path(results_path).expanduser().resolve()
        self.resume = resume
        self.progress = progress or (lambda _event, _payload: None)
        self.repo = StyleReferenceRepository(session)
        self.project_id = f"style_bench_{manifest.public_manifest_hash[:16]}"
        self._payload = self._load_or_initialize_results()

    def run(self) -> dict[str, Any]:
        self._seed_project()
        profiles, bindings = self._ensure_profiles_and_bindings()
        # 抽取/合成可能产生大量提示记录；评分只需要逐个生成单元的真实提示，
        # 在进入生成矩阵前释放训练语料相关记录，避免无谓常驻内存。
        self.client.records.clear()
        self._set_active_binding(bindings, active_author_id=None)
        self.session.commit()

        for case in self.manifest.cases:
            neutral = self._ensure_neutral(case, bindings)
            for author in self.manifest.authors:
                self._ensure_styled(case, author, neutral, profiles, bindings)
        self._set_active_binding(bindings, active_author_id=None)
        self.session.commit()
        self.progress(
            "completed", {"generation_count": len(self._payload["generations"])}
        )
        return deepcopy(self._payload)

    def _ensure_profiles_and_bindings(self):  # noqa: ANN201
        profiles: dict[str, Any] = {}
        bindings: dict[str, Any] = {}
        for author in self.manifest.authors:
            self.progress("profile_started", {"author_id": author.author_id})
            profile = self._ensure_profile(author)
            applied = MaterializationService(self.session).apply_profile(
                profile.profile_id,
                scope=BindingScope.PROJECT,
                scope_ref_id=self.project_id,
                task_type=TaskType.SCENE_GENERATION,
                strategy=InjectionStrategy.MIXED,
                config_json={
                    "intensity": 100,
                    "include_positive": True,
                    "include_forbidden": True,
                    "include_metric": True,
                },
            )
            binding = self.repo.get_binding(applied.binding_id)
            if binding is None:
                raise StyleBenchmarkError(f"profile binding 未落库: {author.author_id}")
            profiles[author.author_id] = profile
            bindings[author.author_id] = binding
            self.session.commit()
            self.progress(
                "profile_ready",
                {
                    "author_id": author.author_id,
                    "profile_id": profile.profile_id,
                    "binding_id": binding.binding_id,
                },
            )
        return profiles, bindings

    def _ensure_profile(self, author: BenchmarkAuthor):  # noqa: ANN201
        expected_label = self._book_author_label(author)
        books = [
            book
            for book in self.repo.list_books()
            if book.author_label == expected_label
        ]
        if len(books) > 1:
            raise StyleBenchmarkError(
                f"作者 {author.author_id} 存在多个 benchmark book"
            )
        if books:
            book = books[0]
        else:
            ingested = IngestService(self.session, llm_enabled=False).ingest_upload(
                author.anonymous_training_text.encode("utf-8"),
                file_name=f"{self._corpus_alias(author)}.txt",
                title=f"Anonymous style benchmark corpus {self._corpus_alias(author)}",
                author_label=expected_label,
                cloud_policy="segments_only",
                rights_declaration={
                    "declared": True,
                    "analysis_rights": True,
                    "send_rights": True,
                    "declared_by": "style_benchmark_runner",
                },
            )
            book = ingested.book
            self.session.commit()

        profiles = [
            profile
            for profile in self.repo.list_profiles(book_id=book.book_id)
            if not (profile.coverage_json or {}).get("stale")
            and profile.status != "archived"
        ]
        if profiles:
            profiles.sort(key=lambda row: (row.created_at or "", row.profile_id))
            return profiles[-1]

        completed_runs = self.repo.list_runs(
            book_id=book.book_id, status=RunStatus.DONE.value
        )
        if completed_runs:
            completed_runs.sort(key=lambda row: (row.created_at or "", row.run_id))
            run = completed_runs[-1]
        else:
            seed_material = f"{self.manifest.public_manifest_hash}:{author.author_id}"
            seed = int(
                hashlib.sha256(seed_material.encode("utf-8")).hexdigest()[:16],
                16,
            )
            run_orchestrator = RunOrchestrator(
                self.session,
                llm_client=self.client,
                llm_enabled=True,
                rng=random.Random(seed),
            )
            resumable_runs = [
                candidate
                for candidate in self.repo.list_runs(book_id=book.book_id)
                if candidate.status in {
                    RunStatus.RUNNING.value,
                    RunStatus.FAILED.value,
                }
            ]
            if self.resume and resumable_runs:
                resumable_runs.sort(
                    key=lambda row: (row.created_at or "", row.run_id)
                )
                run_result = run_orchestrator.resume_extract_run(
                    resumable_runs[-1].run_id
                )
            else:
                run_result = run_orchestrator.start_extract_run(
                    book.book_id,
                    background=False,
                )
            run = self.repo.get_run(run_result.run_id)
            if run is None or run.status != RunStatus.DONE.value:
                raise StyleBenchmarkError(f"作者 {author.author_id} 的风格抽取未完成")
            self.session.commit()

        profile = ProfileSynthesizer(
            self.session,
            llm_client=self.client,
            llm_enabled=True,
        ).synthesize(book.book_id, run.run_id)
        self.session.commit()
        return profile

    def _ensure_neutral(
        self, case: BenchmarkCase, bindings: Mapping[str, Any]
    ) -> dict[str, Any]:
        existing = self._existing_sample(case.case_id, "neutral", None)
        if existing is not None:
            self._assert_resumable_neutral(existing)
            return existing
        self._set_active_binding(bindings, active_author_id=None)
        bundle = BundleBuilder(self.session).build(self._scene_id(case))
        reference_profile_ids = (
            bundle["snapshot"]
            .get("source_version_refs", {})
            .get("reference_profile_ids")
            or []
        )
        if reference_profile_ids:
            raise StyleBenchmarkError(
                f"场景 {case.case_id} 的中性 bundle 意外包含风格 profile"
            )
        expected_row_id = versioned_scene_artifact_id(
            "draft_neutral", self._scene_id(case), bundle
        )
        if self.session.get(SceneDraft, expected_row_id) is not None:
            raise StyleBenchmarkError(
                f"场景 {case.case_id} 已有中性数据库产物但缺少提示词 checkpoint；"
                "为保证泄漏审计完整，不能自动重跑，请使用新的输出目录"
            )
        before = len(self.client.records)
        try:
            result = SceneGenerationService(
                self.session, llm_client=self.client
            ).generate_neutral_draft(
                self._scene_id(case),
                bundle,
            )
        except DomainError as exc:
            # 场景正文不会写入 checkpoint；只输出无正文的结构化失败原因，方便
            # 判断是事实、长度还是完整性门，并保证 --resume 能从该单元重试。
            self.session.rollback()
            self.progress(
                "generation_failed",
                {
                    "case_id": case.case_id,
                    "arm": "neutral",
                    "error_code": exc.code,
                    "details": dict(exc.details or {}),
                },
            )
            raise
        self.session.commit()
        prompt = self.client.prompt_for_call(
            self.session, result.llm_call_id, since=before
        )
        actual_prompt_text = self.client.combined_prompt_text(since=before)
        call = self.session.get(LlmCall, result.llm_call_id)
        sample = {
            "case_id": case.case_id,
            "arm": "neutral",
            "target_author_id": None,
            "generated_text": result.content,
            "actual_prompt_text": actual_prompt_text,
            "generation_metadata": {
                "generation_path": "neutral_draft",
                "reference_profile_ids": [],
                "scene_draft_row_id": result.row_id,
                "bundle_hash": result.bundle_hash,
                "model": getattr(call, "model", None) or prompt.model,
                "provider": getattr(call, "provider", None) or prompt.provider,
                "llm_call_id": result.llm_call_id,
                "prompt_hash": getattr(call, "prompt_hash", None),
            },
        }
        self._checkpoint(sample)
        self.progress(
            "generation_completed", {"case_id": case.case_id, "arm": "neutral"}
        )
        return sample

    def _ensure_styled(
        self,
        case: BenchmarkCase,
        author: BenchmarkAuthor,
        neutral: Mapping[str, Any],
        profiles: Mapping[str, Any],
        bindings: Mapping[str, Any],
    ) -> dict[str, Any]:
        existing = self._existing_sample(case.case_id, "styled", author.author_id)
        if existing is not None:
            self._assert_resumable_styled(
                existing,
                author,
                profiles[author.author_id].profile_id,
                neutral,
            )
            return existing
        neutral_metadata = neutral.get("generation_metadata") or {}
        neutral_row_id = str(neutral_metadata.get("scene_draft_row_id") or "")
        neutral_row = self.session.get(SceneDraft, neutral_row_id)
        if neutral_row is None or neutral_row.content != neutral["generated_text"]:
            raise StyleBenchmarkError(
                f"场景 {case.case_id} 的中性 checkpoint 与隔离数据库不一致，不能安全续跑"
            )
        self._set_active_binding(bindings, active_author_id=author.author_id)
        bundle = BundleBuilder(self.session).build(self._scene_id(case))
        expected_profiles = (
            bundle["snapshot"]
            .get("source_version_refs", {})
            .get("reference_profile_ids")
        )
        if expected_profiles != [profiles[author.author_id].profile_id]:
            raise StyleBenchmarkError(
                f"场景 {case.case_id} 未解析到唯一目标 profile: {author.author_id}"
            )
        expected_base_row_id = versioned_scene_artifact_id(
            "draft_style", self._scene_id(case), bundle
        )
        if self.session.get(SceneDraft, expected_base_row_id) is not None:
            raise StyleBenchmarkError(
                f"场景 {case.case_id}/{author.author_id} 已有风格数据库产物但缺少提示词 "
                "checkpoint；为保证泄漏审计完整，不能自动重跑，请使用新的输出目录"
            )
        before = len(self.client.records)
        result = SceneGenerationService(
            self.session, llm_client=self.client
        ).generate_style_draft(
            self._scene_id(case),
            bundle,
            neutral_draft_row_id=neutral_row_id,
            neutral_content=str(neutral["generated_text"]),
        )
        self.session.commit()
        prompt = self.client.prompt_for_call(
            self.session, result.llm_call_id, since=before
        )
        actual_prompt_text = self.client.combined_prompt_text(since=before)
        call = self.session.get(LlmCall, result.llm_call_id)
        sample = {
            "case_id": case.case_id,
            "arm": "styled",
            "target_author_id": author.author_id,
            "generated_text": result.content,
            "actual_prompt_text": actual_prompt_text,
            "generation_metadata": {
                "generation_path": "style_reference_module",
                "style_reference_profile_id": profiles[author.author_id].profile_id,
                "reference_profile_ids": list(expected_profiles),
                "training_corpus_checksum": author.training_checksum,
                "source_neutral_sha256": hash_text(str(neutral["generated_text"])),
                "scene_draft_row_id": result.row_id,
                "bundle_hash": result.bundle_hash,
                "model": getattr(call, "model", None) or prompt.model,
                "provider": getattr(call, "provider", None) or prompt.provider,
                "llm_call_id": result.llm_call_id,
                "prompt_hash": getattr(call, "prompt_hash", None),
            },
        }
        self._checkpoint(sample)
        self.progress(
            "generation_completed",
            {
                "case_id": case.case_id,
                "arm": "styled",
                "target_author_id": author.author_id,
            },
        )
        return sample

    def _seed_project(self) -> None:
        project = self.session.get(StoryProject, self.project_id)
        if project is None:
            self.session.add(
                StoryProject(
                    project_id=self.project_id,
                    title=f"Style benchmark {self.manifest.manifest_version}",
                    genre="cross_content_style_benchmark",
                    outline_text="Isolated benchmark; not a user manuscript.",
                    planning_mode="outline_driven",
                )
            )
        # The isolated live runner deliberately uses ``autoflush=False`` so
        # LLM checkpoints control every durable boundary.  Flush each FK tier
        # explicitly: relying on incidental ``Session.get`` autoflush made the
        # unit-test session pass while a real empty benchmark database tried to
        # insert chapter_goals before its story_projects parent.
        self.session.flush()

        for index, case in enumerate(self.manifest.cases, start=1):
            chapter_id = self._chapter_id(case)
            if self.session.get(ChapterGoal, chapter_id) is None:
                self.session.add(
                    ChapterGoal(
                        chapter_id=chapter_id,
                        project_id=self.project_id,
                        planned_scene_count=1,
                        display_order=index,
                        chapter_goal=case.prompt,
                    )
                )
        self.session.flush()

        for case in self.manifest.cases:
            chapter_id = self._chapter_id(case)
            if self.session.get(ChapterState, chapter_id) is None:
                self.session.add(
                    ChapterState(chapter_id=chapter_id, current_phase="drafting")
                )
            scene_id = self._scene_id(case)
            if self.session.get(SceneCard, scene_id) is None:
                self.session.add(
                    SceneCard(
                        scene_id=scene_id,
                        chapter_id=chapter_id,
                        project_id=self.project_id,
                        scene_seq=1,
                        scene_goal=case.prompt,
                        beats_json=[group[0] for group in case.required_term_groups],
                        must_include_text="；".join(
                            "|".join(group) for group in case.required_term_groups
                        ),
                        target_length_band=f"{case.min_chars}-{case.max_chars} Chinese characters",
                        scene_type=case.scene_function,
                        is_chapter_last=1,
                        onstage_chars_json=[],
                    )
                )
        self.session.flush()

        for case in self.manifest.cases:
            scene_id = self._scene_id(case)
            if self.session.get(SceneRunState, scene_id) is None:
                self.session.add(SceneRunState(scene_id=scene_id, scene_status="ready"))
        self.session.commit()

    def _set_active_binding(
        self, bindings: Mapping[str, Any], *, active_author_id: str | None
    ) -> None:
        for author_id, binding in bindings.items():
            binding.status = (
                BindingStatus.ACTIVE.value
                if author_id == active_author_id
                else BindingStatus.DISABLED.value
            )
        self.session.flush()

    def _load_or_initialize_results(self) -> dict[str, Any]:
        if self.results_path.exists():
            if not self.resume:
                raise StyleBenchmarkError(
                    f"结果文件已存在；为防覆盖请使用 resume: {self.results_path}"
                )
            try:
                payload = json.loads(self.results_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise StyleBenchmarkError("续跑结果文件不可读") from exc
            if not isinstance(payload, dict):
                raise StyleBenchmarkError("续跑结果根节点必须是对象")
            if payload.get("schema_version") != STYLE_BENCHMARK_SCHEMA_VERSION:
                raise StyleBenchmarkError("续跑结果 schema_version 与运行器不兼容")
            if (
                payload.get("benchmark_id") != self.manifest.benchmark_id
                or payload.get("manifest_version") != self.manifest.manifest_version
                or payload.get("public_manifest_hash")
                != self.manifest.public_manifest_hash
            ):
                raise StyleBenchmarkError("续跑结果与当前冻结公开清单不一致")
            if not isinstance(payload.get("generations"), list):
                raise StyleBenchmarkError("续跑 generations 必须是列表")
            self._validate_partial_generations(payload["generations"])
            return payload
        return {
            "schema_version": STYLE_BENCHMARK_SCHEMA_VERSION,
            "benchmark_id": self.manifest.benchmark_id,
            "manifest_version": self.manifest.manifest_version,
            "public_manifest_hash": self.manifest.public_manifest_hash,
            "generations": [],
        }

    def _existing_sample(
        self,
        case_id: str,
        arm: str,
        target_author_id: str | None,
    ) -> dict[str, Any] | None:
        matches = [
            row
            for row in self._payload["generations"]
            if row.get("case_id") == case_id
            and row.get("arm") == arm
            and row.get("target_author_id") == target_author_id
        ]
        if len(matches) > 1:
            raise StyleBenchmarkError(
                f"续跑结果单元重复: {(case_id, arm, target_author_id)}"
            )
        return matches[0] if matches else None

    def _assert_resumable_neutral(self, sample: Mapping[str, Any]) -> None:
        metadata = sample.get("generation_metadata") or {}
        row_id = str(metadata.get("scene_draft_row_id") or "")
        row = self.session.get(SceneDraft, row_id)
        if row is None or row.content != sample.get("generated_text"):
            raise StyleBenchmarkError("中性结果 checkpoint 缺少匹配的隔离数据库正文")
        if metadata.get("reference_profile_ids") != []:
            raise StyleBenchmarkError(
                "中性结果 checkpoint 声明了风格 profile，拒绝续跑"
            )
        if (
            metadata.get("generation_path") != "neutral_draft"
            or not str(sample.get("actual_prompt_text") or "").strip()
        ):
            raise StyleBenchmarkError("中性结果 checkpoint 的生成路径或提示词证据无效")

    def _assert_resumable_styled(
        self,
        sample: Mapping[str, Any],
        author: BenchmarkAuthor,
        profile_id: str,
        neutral: Mapping[str, Any],
    ) -> None:
        metadata = sample.get("generation_metadata") or {}
        row_id = str(metadata.get("scene_draft_row_id") or "")
        row = self.session.get(SceneDraft, row_id)
        if row is None or row.content != sample.get("generated_text"):
            raise StyleBenchmarkError("风格结果 checkpoint 缺少匹配的隔离数据库正文")
        if (
            metadata.get("style_reference_profile_id") != profile_id
            or metadata.get("reference_profile_ids") != [profile_id]
            or metadata.get("training_corpus_checksum") != author.training_checksum
            or metadata.get("source_neutral_sha256")
            != hash_text(str(neutral.get("generated_text") or ""))
            or metadata.get("generation_path") != "style_reference_module"
            or not str(sample.get("actual_prompt_text") or "").strip()
        ):
            raise StyleBenchmarkError(
                f"风格结果 checkpoint 与当前 profile/训练语料不一致: {author.author_id}"
            )

    def _validate_partial_generations(self, generations: list[Any]) -> None:
        expected = {(case.case_id, "neutral", None) for case in self.manifest.cases} | {
            (case.case_id, "styled", author.author_id)
            for case in self.manifest.cases
            for author in self.manifest.authors
        }
        seen: set[tuple[str, str, str | None]] = set()
        for index, row in enumerate(generations):
            if not isinstance(row, Mapping):
                raise StyleBenchmarkError(f"续跑 generations[{index}] 必须是对象")
            key = (
                row.get("case_id"),
                row.get("arm"),
                row.get("target_author_id"),
            )
            if key not in expected:
                raise StyleBenchmarkError(f"续跑结果包含矩阵外单元: {key}")
            if key in seen:
                raise StyleBenchmarkError(f"续跑结果单元重复: {key}")
            seen.add(key)
            if not str(row.get("generated_text") or "").strip():
                raise StyleBenchmarkError(f"续跑 generations[{index}] 缺少正文")
            if not str(row.get("actual_prompt_text") or "").strip():
                raise StyleBenchmarkError(f"续跑 generations[{index}] 缺少实际提示词")
            if not isinstance(row.get("generation_metadata"), Mapping):
                raise StyleBenchmarkError(f"续跑 generations[{index}] 缺少生成元数据")

    def _checkpoint(self, sample: dict[str, Any]) -> None:
        if self._existing_sample(
            sample["case_id"], sample["arm"], sample["target_author_id"]
        ):
            raise StyleBenchmarkError("拒绝覆盖已完成的 benchmark 单元")
        self._payload["generations"].append(sample)
        self._payload["generations"].sort(
            key=lambda row: (
                row["case_id"],
                row["arm"],
                row.get("target_author_id") or "",
            )
        )
        write_json(self.results_path, self._payload)

    def _book_author_label(self, author: BenchmarkAuthor) -> str:
        return f"style-benchmark:{self.manifest.public_manifest_hash}:{self._corpus_alias(author)}"

    def _corpus_alias(self, author: BenchmarkAuthor) -> str:
        return author.anonymous_corpus_id

    def _chapter_id(self, case: BenchmarkCase) -> str:
        return f"SB_{self.manifest.public_manifest_hash[:8]}_{case.case_id}_CH"

    def _scene_id(self, case: BenchmarkCase) -> str:
        return f"SB_{self.manifest.public_manifest_hash[:8]}_{case.case_id}_SC01"


def run_live_benchmark_workspace(
    manifest: StyleBenchmarkManifest,
    *,
    llm_client: OnlineAccountedExecution,
    output_dir: str | Path,
    resume: bool = False,
    progress: ProgressCallback | None = None,
) -> dict[str, Any]:
    root = Path(output_dir).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    database_path = root / "benchmark.db"
    results_path = root / "results.json"
    if results_path.exists() and not database_path.exists():
        raise StyleBenchmarkError(
            f"结果 checkpoint 存在但隔离数据库缺失，不能证明中性稿与风格稿血缘: {results_path}"
        )
    if database_path.exists() and not resume and not results_path.exists():
        raise StyleBenchmarkError(
            f"隔离数据库已存在但没有结果 checkpoint；请换目录或人工核实后使用 resume: {database_path}"
        )
    engine = create_engine(f"sqlite:///{database_path.as_posix()}")

    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(
        dbapi_connection, _connection_record
    ) -> None:  # noqa: ANN001
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(bind=engine)
    local_session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    try:
        with local_session() as session:
            return StyleBenchmarkLiveRunner(
                session,
                manifest,
                llm_client=llm_client,
                results_path=results_path,
                resume=resume,
                progress=progress,
            ).run()
    finally:
        engine.dispose()
