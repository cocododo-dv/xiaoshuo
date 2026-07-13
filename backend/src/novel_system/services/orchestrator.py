from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

_LOGGER = logging.getLogger(__name__)

from novel_system.db.models import AttemptTracker, ChapterGoal, FinalScene, QcReport, SceneCard, SceneDraft, SceneRunState
from novel_system.services.errors import DomainError
from novel_system.services.aggregator import Aggregator
from novel_system.services.archiver import Archiver
from novel_system.services.bundle_builder import BundleBuilder
from novel_system.services.llm_task_runner import LLMNodeRunner
from novel_system.services.near_final import NearFinalAcceptanceService, NearFinalPlanningService
from novel_system.services.qc_engine import HardQcEngine, SoftQcEngine
from novel_system.services.scene_blueprint import SceneBlueprintService
from novel_system.services.scene_execution import SceneExecutionContractService
from novel_system.services.scene_generation import SceneGenerationService, versioned_scene_artifact_id
from novel_system.services.version_manager import VersionManager


class Orchestrator:
    def __init__(
        self,
        session: Session,
        *,
        scene_generation_service: SceneGenerationService | None = None,
        hard_qc_engine: HardQcEngine | None = None,
        soft_qc_engine: SoftQcEngine | None = None,
        planning_service: NearFinalPlanningService | None = None,
        near_final_service: NearFinalAcceptanceService | None = None,
    ) -> None:
        self.session = session
        self.bundle_builder = BundleBuilder(session)
        self.archiver = Archiver(session)
        self.aggregator = Aggregator(session)
        self.version_manager = VersionManager(session)
        llm_runner = LLMNodeRunner(session)
        self.llm_runner = llm_runner
        self.scene_generation_service = scene_generation_service or SceneGenerationService(session, llm_runner=llm_runner)
        self.hard_qc_engine = hard_qc_engine or HardQcEngine(session, llm_runner=llm_runner)
        self.soft_qc_engine = soft_qc_engine or SoftQcEngine(session, llm_runner=llm_runner)
        self.scene_blueprint_service = SceneBlueprintService(session, llm_runner=llm_runner)
        self.execution_contract_service = SceneExecutionContractService(session)
        self.planning_service = planning_service or NearFinalPlanningService(session, llm_runner=llm_runner)
        self.near_final_service = near_final_service or NearFinalAcceptanceService(session, llm_runner=llm_runner)

    def run_scene(
        self,
        scene_id: str,
        from_step: str = "bundle",
        resume: bool = False,
        author_note: str | None = None,
        run_policy: str = "reliable",
    ) -> dict:
        # Wave 2/3（治理 §5.4/§5.5）：run_policy 现已落列（Wave 3 迁移 0062）。
        # reliable（默认）：Q2/Q3 警告随稿归档；strict：存在 Q2 时停在可归档的
        # quality_warning，由作者经 adopt-current 显式接受；auto 保留（按
        # criticality 决策），当前按 reliable 处理。Q0/Q1 阻断与模式无关。
        self.version_manager.recover_stuck_jobs()
        scene = self.session.get(SceneCard, scene_id)
        if scene is None:
            raise DomainError("SCENE_NOT_FOUND", "scene not found", status_code=404)
        state = self.session.get(SceneRunState, scene_id)
        if state is None:
            # FE 目录直接建的场景没有运行时状态行（scenes POST 才会建）：按同一约定补建
            state = SceneRunState(scene_id=scene_id, scene_status="ready")
            self.session.add(state)
            self.session.flush()
        contract = self.execution_contract_service.get_or_create(scene_id, actor_ref="orchestrator")
        if contract.status != "active":
            detail_reason = "scene execution contract is not ready for drafting"
            if contract.status == "blocked":
                missing_fields = list(contract.missing_fields_json or [])
                detail_reason = "scene execution contract is missing required fields"
                raise DomainError(
                    "SCENE_EXECUTION_CONTRACT_BLOCKED",
                    detail_reason,
                    status_code=409,
                    details={
                        "scene_id": scene_id,
                        "execution_contract_id": contract.contract_id,
                        "status": contract.status,
                        "missing_fields": missing_fields,
                    },
                )
            raise DomainError(
                "SCENE_EXECUTION_CONTRACT_BLOCKED",
                detail_reason,
                status_code=409,
                details={
                    "scene_id": scene_id,
                    "execution_contract_id": contract.contract_id,
                    "status": contract.status,
                    "missing_fields": list(contract.missing_fields_json or []),
                },
            )
        self._prepare_state_for_run(state)
        # Wave 3（§6.1）：本次运行的生效策略落列（预算/使用量不在 _prepare 重置，§7.12）
        state.run_policy = run_policy
        self.scene_blueprint_service.ensure_for_scene(scene_id)
        planning = self.planning_service.ensure_scene_planning(scene_id)
        bundle = self.bundle_builder.build(scene_id, "P2")

        # Wave 3（§4.6/§5.5）：确立场景 token 预算 = 5 × 单发基线（已设不覆盖）
        from novel_system.services import scene_budget
        from novel_system.services.llm_client import load_model_routing_config

        routing_config = load_model_routing_config()
        scene_budget.ensure_budget(
            state,
            scene_budget.estimate_baseline_tokens(self.session, bundle["snapshot"]),
            provider_attempt_budget=routing_config.retry_budget["provider_attempt_budget"],
        )

        from novel_system.services.scene_criticality import classify_scene
        chapter = self.session.get(ChapterGoal, scene.chapter_id)
        chapter_seq = chapter.display_order if chapter and chapter.display_order is not None else None
        # §6.4 / §16: feed consecutive transition count and constraint_intensity
        _consecutive_trans = self._consecutive_transition_count(scene)
        criticality = classify_scene(
            scene,
            chapter_seq=chapter_seq,
            consecutive_transition_count=_consecutive_trans,
            constraint_intensity=getattr(scene, "constraint_intensity", None),
        )
        _LOGGER.info(
            "scene %s criticality=%s reasons=%s best_of_n=%d",
            scene_id, criticality.level, criticality.reasons, criticality.best_of_n,
        )
        # §6 Defect D: persist criticality classification for API exposure
        state.criticality_level = criticality.level
        state.criticality_reasons_json = criticality.reasons

        # §10 / §12: pre-generation tension + theme diagnostics
        self._run_pre_generation_diagnostics(scene, chapter)

        neutral_generation = self.scene_generation_service.generate_neutral_draft(scene_id, bundle)
        neutral_content = neutral_generation.content

        hard_qc = self.hard_qc_engine.evaluate(
            scene_id=scene_id,
            bundle=bundle,
            neutral_draft_row_id=neutral_generation.row_id,
            neutral_content=neutral_content,
        )
        if not hard_qc.should_continue:
            self.session.flush()
            # Wave 2 项 5：所有早退结果都携带 author_state 契约（含 latest_valid 指针）
            return self._with_author_projection(scene_id, state, {
                "scene_status": state.scene_status,
                "current_bundle_id": bundle["bundle_id"],
                "current_bundle_hash": bundle["bundle_snapshot_hash"],
                "current_qc_report_id": state.current_qc_report_id,
                "current_human_review_event_id": state.current_human_review_event_id,
                "hard_qc": {
                    "branch": hard_qc.branch,
                    "qc_report_id": hard_qc.qc_report_id,
                    "human_review_event_id": hard_qc.human_review_event_id,
                    "resolution_code": hard_qc.resolution_code,
                    "next_action": hard_qc.next_action,
                    "stop_reason": hard_qc.stop_reason,
                },
            })

        # Wave 3（§5.5 成本分配）：初始 N（关键 3/标准 2/过渡 1），低分散在预算内
        # 渐进补候选至上限（关键 5/标准 3）——不再一次生成后整批无上限重试。
        n_candidates = self._best_of_n_count(contract, criticality=criticality)
        candidate_summaries: list[dict[str, Any]] = []
        if n_candidates > 1:
            candidates = self.scene_generation_service.generate_style_draft_candidates(
                scene_id,
                bundle,
                neutral_draft_row_id=neutral_generation.row_id,
                neutral_content=neutral_content,
                author_note=author_note,
                n_candidates=n_candidates,
                max_candidates=criticality.max_best_of_n if criticality else n_candidates,
            )
            # 标准场景：机器下限选择（adversarial #1）继续管线；关键场景在下方暂停终选。
            from novel_system.services.literary_quality import adversarial_rank_score
            for idx, cand in enumerate(candidates):
                cand_score = adversarial_rank_score(cand.content)
                candidate_summaries.append({
                    "row_id": cand.row_id,
                    "rank": idx,
                    "adversarial_score": round(cand_score, 3),
                    "content_preview": (cand.content or "")[:300],
                    "selected": idx == 0,
                })

            style_generation = candidates[0]
        else:
            style_generation = self.scene_generation_service.generate_style_draft(
                scene_id,
                bundle,
                neutral_draft_row_id=neutral_generation.row_id,
                neutral_content=neutral_content,
                author_note=author_note,
            )
            candidates = [style_generation]

        hard_qc_payload = {
            "branch": hard_qc.branch,
            "qc_report_id": hard_qc.qc_report_id,
            "human_review_event_id": hard_qc.human_review_event_id,
            "resolution_code": hard_qc.resolution_code,
            "next_action": hard_qc.next_action,
            "stop_reason": hard_qc.stop_reason,
        }

        # Wave 3（§5.5）：关键场景在候选生成后暂停编排——确定性坏稿淘汰 →
        # 匿名终选 gate；作者选择后经 resume-after-selection 从批判修订/QC 继续。
        # 「§6.3 终选决定质量上界，归人」从推荐信号升级为强制暂停。
        if criticality.human_gate:
            offered_row_ids = self._offer_candidates_for_selection(scene, state, bundle, candidates)
            if offered_row_ids is not None:
                self.session.flush()
                return self._with_author_projection(scene_id, state, {
                    "scene_status": state.scene_status,
                    "current_bundle_id": bundle["bundle_id"],
                    "current_bundle_hash": bundle["bundle_snapshot_hash"],
                    "current_qc_report_id": state.current_qc_report_id,
                    "current_human_review_event_id": state.current_human_review_event_id,
                    "hard_qc": hard_qc_payload,
                    "planning": planning,
                    "run_policy": run_policy,
                    # 盲化：暂停响应只报数量，不带分数/预览（候选经盲化视图取用）
                    "candidate_count": len(offered_row_ids),
                    "candidate_selection_required": True,
                })

        return self._finalize_after_style(
            scene=scene,
            state=state,
            contract=contract,
            bundle=bundle,
            criticality=criticality,
            planning=planning,
            hard_qc_payload=hard_qc_payload,
            style_generation=style_generation,
            candidate_summaries=candidate_summaries if candidate_summaries else None,
            candidates_total=len(candidates),
            run_policy=run_policy,
        )

    def _finalize_after_style(
        self,
        *,
        scene: SceneCard,
        state: SceneRunState,
        contract,
        bundle: dict[str, Any],
        criticality,
        planning,
        hard_qc_payload: dict[str, Any],
        style_generation,
        candidate_summaries: list[dict[str, Any]] | None,
        candidates_total: int,
        run_policy: str,
    ) -> dict:
        """§5.5 顺序的后半段：批判修订 → 软 QC → near-final → 严格停点 → 归档。

        run_scene 与 resume_after_selection 共用。可选支出（LLM 批判、补丁、
        near-final 重写）过预算闸（§5.8 预算耗尽停止新调用、交付最佳稿）；
        候选补满上限的场按 §5.5 固定预算优先级放弃 LLM 批判与补丁。
        """
        from novel_system.services import scene_budget

        scene_id = scene.scene_id
        strict_mode = run_policy == "strict"
        gave_up_optional = (
            criticality is not None
            and criticality.max_best_of_n > 1
            and candidates_total >= criticality.max_best_of_n
        )

        def _optional_spend_allowed() -> bool:
            return (not gave_up_optional) and scene_budget.can_spend(state, scene_budget.budget_unit(state))

        # §8 reflexion-style auto-critique pass (after best-of-N selection, before soft QC).
        # Default: rule-based pass only. Opt-in (NOVEL_SYSTEM_LLM_AUTO_CRITIQUE_ENABLED +
        # llm_enabled) layers the independent LLM editor critic on top — degrades to
        # rule-only on any runner error, never blocks (blueprint §8 + §15 honest-bounds).
        critique = None
        try:
            from novel_system.services.auto_critique import llm_auto_critique
            # Wave 3（§5.5/§5.8）：LLM 批判是可选支出——预算不足或候选已补满上限
            # 时降级为纯规则批判（runner=None），不烧新调用。
            _critique_runner = self._resolve_auto_critique_runner() if _optional_spend_allowed() else None
            critique = llm_auto_critique(
                style_generation.content,
                scene_context=self._scene_critique_context(scene, contract),
                session=self.session,
                llm_runner=_critique_runner,
                skip_critique=criticality.skip_critique,
            )
        except Exception:
            _LOGGER.warning("auto-critique degraded for scene %s", scene_id, exc_info=True)
        if critique is not None and critique.should_rewrite:
            _LOGGER.info(
                "auto-critique flagged %d dimensions for scene %s: %s",
                len(critique.flagged_dimensions), scene_id, critique.flagged_dimensions,
            )
            if not _optional_spend_allowed():
                # §5.5 预算优先级：补丁排最后——预算不足/候选补满即放弃，保留未修订稿
                _LOGGER.warning("critique patch skipped for scene %s (budget/candidate cap)", scene_id)
            else:
                # 补丁生成失败与 critique 本身失败分开兜底：保留未修订稿继续主流程，
                # 但失败必须以 WARNING 可见（scene_generation 内部已落 AttemptTracker/LlmCall）。
                try:
                    from novel_system.services.auto_critique import format_critique_brief
                    critique_brief = self._pov_desensitize_brief(
                        scene, contract, format_critique_brief(critique),
                    )
                    style_generation = self.scene_generation_service.generate_style_patch(
                        scene_id,
                        bundle,
                        source_style_draft_row_id=style_generation.row_id,
                        source_style_content=style_generation.content,
                        rewrite_brief=critique_brief,
                        source_qc_report_id=f"auto_critique_{scene_id}",
                    )
                except Exception:
                    _LOGGER.warning(
                        "auto-critique patch failed for scene %s; keeping unpatched style draft",
                        scene_id,
                        exc_info=True,
                    )

        soft_qc = self.soft_qc_engine.evaluate(
            scene_id=scene_id,
            bundle=bundle,
            source_draft_row_id=style_generation.row_id,
            source_draft_content=style_generation.content,
        )

        final_generation = style_generation
        if soft_qc.branch == "patch":
            if not _optional_spend_allowed():
                # §5.8 预算耗尽停止新调用：跳过软补丁，带既有稿继续（QC 报告已留意见）
                _LOGGER.warning("soft patch skipped for scene %s (budget/candidate cap)", scene_id)
            else:
                rewrite_brief = self._pov_desensitize_brief(
                    scene, contract, self._rewrite_brief_from_report(soft_qc.qc_report_id),
                )
                final_generation = self.scene_generation_service.generate_style_patch(
                    scene_id,
                    bundle,
                    source_style_draft_row_id=style_generation.row_id,
                    source_style_content=style_generation.content,
                    rewrite_brief=rewrite_brief,
                    source_qc_report_id=soft_qc.qc_report_id,
                )
                soft_qc = self.soft_qc_engine.evaluate(
                    scene_id=scene_id,
                    bundle=bundle,
                    source_draft_row_id=final_generation.row_id,
                    source_draft_content=final_generation.content,
                )

        if soft_qc.branch == "human_review_required":
            # Wave 2：软 QC 只在 verified Q0/Q1 时才会走到这里（LLM-only 意见已在
            # 引擎内降级为 waive）——这是真硬阻断，正文保留、契约随行。
            self.session.flush()
            return self._with_author_projection(scene_id, state, {
                "scene_status": state.scene_status,
                "current_bundle_id": bundle["bundle_id"],
                "current_bundle_hash": bundle["bundle_snapshot_hash"],
                "current_qc_report_id": state.current_qc_report_id,
                "current_human_review_event_id": state.current_human_review_event_id,
                "hard_qc": hard_qc_payload,
                "soft_qc": self._soft_qc_result_payload(soft_qc),
                "planning": planning,
            })

        rewrite_count = 0
        near_final = self.near_final_service.evaluate_scene(
            scene_id,
            bundle=bundle,
            source_draft_row_id=final_generation.row_id,
            source_content=final_generation.content,
        )
        if not near_final["pass_flag"] and near_final.get("should_rewrite"):
            if not _optional_spend_allowed():
                # §5.8：预算耗尽不烧重写，直接交付当前最好稿（意见随 carry note 留痕）
                _LOGGER.warning("near-final rewrite skipped for scene %s (budget/candidate cap)", scene_id)
            else:
                rewrite_count = 1
                final_generation = self.scene_generation_service.generate_near_final_rewrite(
                    scene_id,
                    bundle,
                    source_draft_row_id=final_generation.row_id,
                    source_content=final_generation.content,
                    revision_brief=self._near_final_rewrite_brief(near_final),
                    source_evaluation_id=str(near_final.get("evaluation_id") or ""),
                )
                near_final = self.near_final_service.evaluate_scene(
                    scene_id,
                    bundle=bundle,
                    source_draft_row_id=final_generation.row_id,
                    source_content=final_generation.content,
                )
        near_final_payload = self._near_final_result_payload(near_final, rewrite_count=rewrite_count)
        # Wave 2（§5.4 / Wave 2 项 4）：near-final 是 LLM 提案层（Q2/Q3）——达自动
        # 修订上限（软补丁 ≤1 + 准终稿重写 ≤1 = 2 次）后不再断头，交付当前最好稿；
        # 其 requires_human_review 亦为提案，不得产生 human_review_required 断头。
        near_final_warnings = self._near_final_warning_findings(near_final)

        # 严格模式停点：存在 Q2 级警告（软 QC 报告或 near-final 未过）时不自动归档，
        # 停在可归档的 quality_warning，由作者经 adopt-current 显式接受（留审计）。
        if strict_mode:
            strict_warnings = self._collect_q2_warnings(state, near_final_warnings)
            if strict_warnings:
                state.scene_status = "quality_warning_pending_acceptance"
                self.session.flush()
                result = self._with_author_projection(scene_id, state, {
                    "scene_status": state.scene_status,
                    "current_bundle_id": bundle["bundle_id"],
                    "current_bundle_hash": bundle["bundle_snapshot_hash"],
                    "current_qc_report_id": state.current_qc_report_id,
                    "current_human_review_event_id": state.current_human_review_event_id,
                    "hard_qc": hard_qc_payload,
                    "soft_qc": self._soft_qc_result_payload(soft_qc),
                    "planning": planning,
                    "near_final": near_final_payload,
                    "run_policy": run_policy,
                })
                result["quality_warnings"] = self._merged_warnings(result.get("quality_warnings"), near_final_warnings)
                return result

        # Wave 3：旧的 near-final 后置 critical_scene_human_gate 被前移的候选终选
        # gate 取代（§5.5 顺序——终选在批判修订/硬检查之前，此处不再二次人工门）。

        final_row_id = versioned_scene_artifact_id("final_scene", scene_id, bundle)
        soft_risk_acceptance_event_id = self._soft_risk_acceptance_event_id(soft_qc)
        carry_notes_json = self._carry_notes_from_report(soft_qc.qc_report_id) if soft_qc.branch == "waive" else []
        if soft_risk_acceptance_event_id:
            carry_notes_json.append(
                {
                    "kind": "soft_risk_acceptance",
                    "human_review_event_id": soft_risk_acceptance_event_id,
                    "qc_report_id": soft_qc.qc_report_id,
                }
            )
        if not near_final.get("pass_flag"):
            # Wave 2：达修订上限仍未过的 near-final 意见随稿归档留痕（作者行动建议）
            carry_notes_json.append(
                {
                    "kind": "near_final_unresolved",
                    "failure_class": near_final.get("failure_class"),
                    "rewrite_count": rewrite_count,
                    "recommended_action": "author_review_optional_fix",
                }
            )
        self.session.add(
            FinalScene(
                row_id=final_row_id,
                scene_id=scene_id,
                chapter_id=scene.chapter_id,
                content=final_generation.content,
                status="near_final_ready",
                source_bundle_id=bundle["bundle_id"],
                source_bundle_hash=bundle["bundle_snapshot_hash"],
                generation_llm_call_id=final_generation.llm_call_id,
            )
        )
        self.session.flush()
        state.current_final_scene_row_id = final_row_id
        finalize_details = {
            "source_style_draft_row_id": final_generation.row_id,
            "source_qc_report_id": soft_qc.qc_report_id,
            "final_generation_llm_call_id": final_generation.llm_call_id,
        }
        if soft_risk_acceptance_event_id:
            finalize_details["soft_risk_acceptance_event_id"] = soft_risk_acceptance_event_id
        self.session.add(
            AttemptTracker(
                scene_id=scene_id,
                chapter_id=scene.chapter_id,
                step="finalize",
                status="completed",
                source_bundle_id=bundle["bundle_id"],
                details_json=finalize_details,
            )
        )
        self.session.flush()

        archive_result = self.archiver.archive_final_scene(
            scene_id,
            final_row_id,
            qc_report_id=soft_qc.qc_report_id,
            carry_notes_json=carry_notes_json,
        )
        self._record_narrative_events(scene, contract, final_generation.content)
        self._index_scene_to_vector_store(scene, final_generation.content)

        chapter_near_final = None
        if scene.is_chapter_last == 1:
            self.aggregator.run_final_aggregate(scene.chapter_id)
            # §2 summary tower: roll up a volume-level atmosphere summary at span boundaries
            try:
                self.aggregator.maybe_aggregate_volume(scene.chapter_id)
            except Exception:
                _LOGGER.warning(
                    "volume aggregation degraded for chapter %s", scene.chapter_id, exc_info=True
                )
            chapter_near_final = self.near_final_service.evaluate_chapter(scene.chapter_id)
            self._detect_and_store_style_drift(scene)

        result = self._with_author_projection(scene_id, state, {
            "scene_status": archive_result["scene_status"],
            "current_bundle_id": bundle["bundle_id"],
            "current_bundle_hash": bundle["bundle_snapshot_hash"],
            "current_final_scene_row_id": final_row_id,
            "current_qc_report_id": state.current_qc_report_id,
            "current_human_review_event_id": state.current_human_review_event_id,
            "hard_qc": hard_qc_payload,
            "soft_qc": self._soft_qc_result_payload(soft_qc),
            "planning": planning,
            "near_final": near_final_payload,
            "chapter_near_final": chapter_near_final,
            "style_candidates": candidate_summaries if candidate_summaries else None,
            "run_policy": run_policy,
        })
        result["quality_warnings"] = self._merged_warnings(result.get("quality_warnings"), near_final_warnings)
        if near_final_warnings and "author_review_optional_fix" not in (result.get("recommended_actions") or []):
            result["recommended_actions"] = [*(result.get("recommended_actions") or []), "author_review_optional_fix"]
        return result

    def _consecutive_transition_count(self, scene: SceneCard) -> int:
        """Count how many consecutive transition-level scenes precede *scene* in this chapter.

        Used by §6.4 probabilistic promotion: after 3+ consecutive transitions,
        the next transition is elevated to standard to break the "温吞" rhythm.
        """
        from novel_system.services.scene_criticality import classify_scene
        preceding = list(self.session.execute(
            select(SceneCard).where(
                SceneCard.chapter_id == scene.chapter_id,
                SceneCard.scene_seq < scene.scene_seq,
                SceneCard.trashed_flag == 0,
            ).order_by(SceneCard.scene_seq.desc())
        ).scalars().all())
        count = 0
        for prev in preceding:
            crit = classify_scene(prev)  # quick: no DB queries, pure field inspection
            if crit.level == "transition":
                count += 1
            else:
                break
        return count

    @staticmethod
    def _prepare_state_for_run(state: SceneRunState) -> None:
        preserve_hard_retry_state = (
            state.current_final_scene_row_id is None
            and state.scene_status in {"hard_qc_partial_rewrite_required", "hard_qc_full_rewrite_required"}
        )
        state.current_bundle_id = None
        state.current_bundle_hash = None
        state.current_neutral_draft_row_id = None
        state.current_style_draft_row_id = None
        state.current_final_scene_row_id = None
        state.current_human_review_event_id = None
        state.current_qc_report_id = None
        state.total_attempt_count = 0
        state.soft_patch_count = 0
        if not preserve_hard_retry_state:
            state.hard_partial_rewrite_count = 0
            state.hard_full_rewrite_count = 0
            state.repeat_issue_key = None
            state.repeat_issue_count = 0

    def _pov_desensitize_brief(self, scene: SceneCard, contract, brief: list[str]) -> list[str]:
        """Wave 4（§5.6/§7.11/不变量 11）：回灌自动补丁提示词前做 POV 证据脱敏。

        引用了非 POV 已知秘密的 brief 条目不得进入自动补丁——剔除后只能走作者确认修订。
        硬 QC 自身始终读全量权威状态，不经此路径。pov 缺失或项目无秘密时无副作用；
        脱敏失败降级为原 brief（不阻断主流程），失败以 WARNING 可见。
        """
        if not brief:
            return brief
        try:
            from novel_system.services.pov_knowledge_projection import (
                PovKnowledgeProjection,
            )
            payload = getattr(contract, "payload_json", None) or {}
            pov = scene.pov_character_id or payload.get("pov_character_id")
            if not pov:
                return brief
            project_id = scene.project_id or payload.get("project_id") or (
                scene.chapter_id.rsplit("_", 1)[0] if "_" in scene.chapter_id else scene.chapter_id
            )
            return PovKnowledgeProjection(self.session).redact_brief(
                brief, project_id, scene.scene_seq or 0,
                pov_character_id=pov,
                onstage_character_ids=scene.onstage_chars_json or [],
            )
        except Exception:
            _LOGGER.warning(
                "pov brief desensitization degraded for scene %s; keeping raw brief",
                scene.scene_id, exc_info=True,
            )
            return brief

    def _rewrite_brief_from_report(self, qc_report_id: str) -> list[str]:
        report = self.session.get(QcReport, qc_report_id)
        if report is None:
            return []
        entries = report.rewrite_brief_json or []
        rewrite_brief: list[str] = []
        for entry in entries:
            if isinstance(entry, dict):
                instruction = entry.get("instruction")
                if isinstance(instruction, str) and instruction.strip():
                    rewrite_brief.append(instruction.strip())
        return rewrite_brief

    def _carry_notes_from_report(self, qc_report_id: str) -> list[dict[str, Any]]:
        report = self.session.get(QcReport, qc_report_id)
        if report is None:
            return []
        carry_notes: list[dict[str, Any]] = []
        for entry in report.rewrite_brief_json or []:
            if not isinstance(entry, dict):
                continue
            if entry.get("kind") != "carry_forward_note":
                continue
            note_scope = entry.get("note_scope")
            carry_note_text = entry.get("carry_note_text")
            if isinstance(note_scope, str) and note_scope.strip() and isinstance(carry_note_text, str) and carry_note_text.strip():
                carry_notes.append(
                    {
                        "kind": "carry_forward_note",
                        "note_scope": note_scope.strip(),
                        "carry_note_text": carry_note_text.strip(),
                    }
                )
        return carry_notes

    @staticmethod
    def _soft_risk_acceptance_event_id(soft_qc) -> str | None:
        stop_reason = str(getattr(soft_qc, "stop_reason", "") or "")
        prefix = "accepted_soft_risk:"
        if not stop_reason.startswith(prefix):
            return None
        event_id = stop_reason[len(prefix) :].strip()
        return event_id or None

    @staticmethod
    def _near_final_rewrite_brief(near_final: dict[str, Any]) -> list[str]:
        rewrite_brief: list[str] = []
        for entry in near_final.get("revision_brief") or []:
            if isinstance(entry, dict):
                action = entry.get("action") or entry.get("instruction") or entry.get("recommendation")
                if isinstance(action, str) and action.strip():
                    rewrite_brief.append(action.strip())
            elif isinstance(entry, str) and entry.strip():
                rewrite_brief.append(entry.strip())
        if not rewrite_brief:
            rewrite_brief.append(
                "Rewrite the full scene so forced choice, paid cost, relationship turn, and ending action are visible."
            )
        return rewrite_brief

    def _with_author_projection(self, scene_id: str, state: SceneRunState, payload: dict[str, Any]) -> dict[str, Any]:
        """Wave 2 项 5：run 结果（含全部早退路径）统一附 §5.3 作者状态契约。"""
        from novel_system.services.author_state import compute_author_state

        projection = compute_author_state(self.session, scene_id, state)
        return {**payload, **projection}

    @staticmethod
    def _near_final_warning_findings(near_final: dict[str, Any]) -> list[dict[str, Any]]:
        """near-final 未过 → Q2/Q3 警告条目（LLM 提案层，不阻断）。"""
        if near_final.get("pass_flag"):
            return []
        failure_class = str(near_final.get("failure_class") or "near_final_unresolved")
        level = "Q3" if failure_class == "prose_model_voice" else "Q2"
        first_finding = next(
            (item for item in near_final.get("findings") or [] if isinstance(item, dict)),
            {},
        )
        return [
            {
                "issue_key": f"near_final_{failure_class}",
                "quality_level": level,
                "message": str(first_finding.get("issue") or failure_class),
                "recommended_action": "author_review_optional_fix",
                "verified_by": None,
            }
        ]

    def _collect_q2_warnings(self, state: SceneRunState, near_final_warnings: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """严格模式停点判据：当前 QC 报告的 Q2 条目 + near-final Q2 警告（Q3 只诊断不停）。"""
        warnings = [item for item in near_final_warnings if item.get("quality_level") == "Q2"]
        report = self.session.get(QcReport, state.current_qc_report_id) if state.current_qc_report_id else None
        for issue in (report.issues_json or []) if report else []:
            if isinstance(issue, dict) and issue.get("quality_level") == "Q2":
                warnings.append(issue)
        return warnings

    @staticmethod
    def _merged_warnings(existing: Any, additions: list[dict[str, Any]]) -> list[dict[str, Any]]:
        merged = [item for item in (existing or []) if isinstance(item, dict)]
        merged.extend(additions)
        return merged

    @staticmethod
    def _near_final_result_payload(near_final: dict[str, Any], *, rewrite_count: int) -> dict[str, Any]:
        return {
            "near_final_status": near_final.get("near_final_status"),
            "pass_flag": bool(near_final.get("pass_flag")),
            "overall_score": near_final.get("overall_score"),
            "failure_class": near_final.get("failure_class"),
            "requires_human_review": bool(near_final.get("requires_human_review")),
            "evaluation_id": near_final.get("evaluation_id"),
            "revision_candidate_id": near_final.get("revision_candidate_id"),
            "should_rewrite": bool(near_final.get("should_rewrite")),
            "rewrite_count": rewrite_count,
            "findings": near_final.get("findings") or [],
            "revision_brief": near_final.get("revision_brief") or [],
        }

    def _record_narrative_events(self, scene: SceneCard, contract, content: str) -> None:
        """Extract all 7 event types from approved scene and log to event sourcing.

        Blueprint §2: event log is the single source of truth.
        """
        try:
            from novel_system.services.narrative_event_log import NarrativeEventLog
            log = NarrativeEventLog(self.session)
            payload = contract.payload_json or {}
            project_id = (
                scene.project_id
                or payload.get("project_id")
                or (scene.chapter_id.rsplit("_", 1)[0] if "_" in scene.chapter_id else scene.chapter_id)
            )
            pov = scene.pov_character_id or payload.get("pov_character_id")
            onstage = scene.onstage_chars_json or []
            all_chars = list(dict.fromkeys(([pov] if pov else []) + [c for c in onstage if c != pov]))
            base = dict(project_id=project_id, scene_id=scene.scene_id, chapter_id=scene.chapter_id)

            # --- 1. character_state: appeared_in_scene ---
            for char_id in all_chars:
                if not char_id:
                    continue
                log.log_event(
                    **base,
                    event_type="character_state",
                    entity_type="character",
                    entity_id=char_id,
                    fact_key="appeared_in_scene",
                    fact_value=scene.scene_id,
                    source_text_excerpt=content[:200] if content else None,
                )

            # --- 2. character_state: exit_change ---
            exit_change = scene.exit_change or payload.get("exit_change") or ""
            if exit_change and pov:
                log.log_event(
                    **base,
                    event_type="character_state",
                    entity_type="character",
                    entity_id=pov,
                    fact_key="exit_change",
                    fact_value=exit_change[:500],
                )

            # --- 3. location_change ---
            location = scene.location or payload.get("location")
            if location:
                for char_id in all_chars:
                    if not char_id:
                        continue
                    log.log_event(
                        **base,
                        event_type="location_change",
                        entity_type="character",
                        entity_id=char_id,
                        fact_key="location",
                        fact_value=location[:200],
                    )

            # --- 4. character_learns: from writer_brief must_reveal ---
            writer_brief = scene.writer_brief_json or {}
            must_reveal = writer_brief.get("must_reveal")
            if must_reveal and pov:
                reveal_text = must_reveal if isinstance(must_reveal, str) else str(must_reveal)
                log.log_event(
                    **base,
                    event_type="character_learns",
                    entity_type="character",
                    entity_id=pov,
                    fact_key="scene_revelation",
                    fact_value=reveal_text[:500],
                )

            # --- 5. relation_change: from scene blueprint relationship_turn ---
            self._record_relation_events(log, scene, base, pov, all_chars)

            # --- 6. foreshadow_plant / foreshadow_resolve ---
            self._record_foreshadow_events(log, scene, base)

            # --- 7. (opt-in) prose-grounded events: what the TEXT actually realized,
            # not just what the spec planned. Advisory (confidence="extracted"). ---
            self._record_prose_events(log, scene, base, content)

            self.session.flush()
        except Exception:
            _LOGGER.warning(
                "narrative event recording degraded for scene %s", scene.scene_id, exc_info=True
            )

    def _resolve_auto_critique_runner(self):
        """§8 gate: the independent LLM editor critic is layered on ONLY when both
        ``llm_enabled`` and ``llm_auto_critique_enabled`` are set (opt-in); otherwise the
        critic runner is ``None`` and ``llm_auto_critique`` degrades to the rule-based pass.
        Extracted from ``run_scene`` so the opt-in gate is unit-testable in isolation
        (blueprint §8 + §15 honest-bounds)."""
        from novel_system.settings import get_settings
        settings = get_settings()
        return self.llm_runner if (settings.llm_enabled and settings.llm_auto_critique_enabled) else None

    def _record_prose_events(self, log, scene: SceneCard, base: dict, content: str) -> None:
        """§2 (opt-in): extract events from the ACTUAL generated prose so model drift away
        from the spec is captured. Tagged confidence="extracted" + source="prose" → advisory
        only, never a hard consistency blocker (blueprint §15 honest-bounds). Degrades to a
        no-op when disabled, no runner, or on any error."""
        from novel_system.settings import get_settings
        settings = get_settings()
        if not (settings.llm_enabled and getattr(settings, "llm_event_extraction_enabled", False)):
            return
        if not (content and content.strip()):
            return
        try:
            from novel_system.services.prose_event_extractor import extract_events_from_prose
            for ev in extract_events_from_prose(content, llm_runner=self.llm_runner):
                log.log_event(
                    **base,
                    event_type=ev.event_type,
                    entity_type="relation" if ev.event_type == "relation_change" else "character",
                    entity_id=ev.entity_id,
                    fact_key=ev.fact_key,
                    fact_value=ev.fact_value,
                    confidence="extracted",
                    source_text_excerpt=ev.evidence or content[:200],
                    payload={"source": "prose"},
                )
        except Exception:
            _LOGGER.warning(
                "prose event extraction degraded for scene %s", scene.scene_id, exc_info=True
            )

    def _record_relation_events(
        self, log, scene: SceneCard, base: dict, pov: str | None, all_chars: list[str],
    ) -> None:
        """Extract relation_change events from scene blueprint and writer brief."""
        from novel_system.db.models import SceneBlueprint
        blueprint = self.session.execute(
            select(SceneBlueprint)
            .where(SceneBlueprint.scene_id == scene.scene_id, SceneBlueprint.status.in_(("accepted", "draft")))
            .order_by(SceneBlueprint.created_at.desc())
        ).scalars().first()
        relationship_turn = None
        if blueprint and blueprint.blueprint_json:
            relationship_turn = blueprint.blueprint_json.get("relationship_turn")
        if not relationship_turn:
            relationship_turn = (scene.writer_brief_json or {}).get("relationship_turn")
        if relationship_turn and pov and len(all_chars) >= 2:
            other = next((c for c in all_chars if c != pov), pov)
            log.log_event(
                **base,
                event_type="relation_change",
                entity_type="relation",
                entity_id=f"{pov}--{other}",
                fact_key="relationship_turn",
                fact_value=str(relationship_turn)[:500],
            )

    def _record_foreshadow_events(self, log, scene: SceneCard, base: dict) -> None:
        """Record foreshadow_plant / foreshadow_reinforce / foreshadow_resolve from ForeshadowTracker.

        Blueprint §5: reinforcement execution must be tracked as narrative events,
        not just as directives — otherwise the system 'thinks' it reinforced but
        the text may never have included the hint.
        """
        from novel_system.db.models import ForeshadowTracker
        from novel_system.services.foreshadow_lifecycle import ForeshadowLifecycleService

        trackers = self.session.execute(
            select(ForeshadowTracker).where(
                ForeshadowTracker.scene_id == scene.scene_id,
                ForeshadowTracker.active_flag == 1,
            )
        ).scalars().all()
        for tracker in trackers:
            if tracker.tracker_status == "open":
                log.log_event(
                    **base,
                    event_type="foreshadow_plant",
                    entity_type="foreshadow",
                    entity_id=tracker.foreshadow_id,
                    fact_key="planted",
                    fact_value=tracker.text[:500] if tracker.text else "foreshadow planted",
                )
            elif tracker.tracker_status == "resolved":
                log.log_event(
                    **base,
                    event_type="foreshadow_resolve",
                    entity_type="foreshadow",
                    entity_id=tracker.foreshadow_id,
                    fact_key="resolved",
                    fact_value=tracker.text[:500] if tracker.text else "foreshadow resolved",
                )

        # Blueprint §5 reinforcement tracking: check if this scene had reinforcement
        # directives and record them as narrative events for audit trail.
        try:
            lifecycle = ForeshadowLifecycleService(self.session)
            report = lifecycle.scene_actions(scene.scene_id)
            for action in report.actions:
                if action.action == "reinforce":
                    log.log_event(
                        **base,
                        event_type="foreshadow_reinforce",
                        entity_type="foreshadow",
                        entity_id=action.foreshadow_id,
                        fact_key="reinforced",
                        fact_value=f"Reinforcement directed: {action.reason}"[:500],
                    )
        except Exception:
            pass  # non-critical — don't block scene finalization

    @staticmethod
    def _index_scene_to_vector_store(scene: SceneCard, content: str) -> None:
        """Index approved scene content into the vector store for semantic retrieval (§3 Track 3)."""
        try:
            # 必须走 get_vector_store() 工厂：memory 后端是进程级单例、chroma 后端持久化。
            # 裸 new InMemoryVectorStore() 写进的是函数返回即销毁的实例字典（审计 P-7）。
            from novel_system.services.vector_store import get_vector_store
            project_id = scene.project_id or (scene.chapter_id.rsplit("_", 1)[0] if "_" in scene.chapter_id else scene.chapter_id)
            collection_name = f"scenes_{project_id}"
            store = get_vector_store()
            existing = store.load_collection(collection_name) if store.collection_exists(collection_name) else []
            existing_ids = {doc["id"] for doc in existing}
            if scene.scene_id not in existing_ids:
                existing.append({"id": scene.scene_id, "text": (content or "")[:600]})
                store.write_collection(collection_name, existing)
        except Exception:
            _LOGGER.warning("vector store indexing degraded for scene %s", scene.scene_id, exc_info=True)

    def _detect_and_store_style_drift(self, scene: SceneCard) -> None:
        """Run style drift detection at chapter boundary and store correction prompt.

        Blueprint §9 drift correction loop: when drift is detected at chapter end,
        store the correction guidance scoped to the NEXT chapter so the bundle_builder
        picks it up for subsequent generation. This closes the detect→correct feedback loop.
        """
        try:
            from novel_system.services.style_drift_detector import (
                detect_chapter_drift,
                format_drift_correction_prompt,
                format_drift_dimensions_for_bundle,
                drift_corrective_ptype_priority,
            )
            from novel_system.db.models import LongformStructureGuidance
            import uuid

            baseline = self._load_style_baseline(scene)
            report = detect_chapter_drift(self.session, scene.chapter_id, baseline)
            if not report.has_drift:
                return

            correction = format_drift_correction_prompt(report)
            if not correction:
                return

            # Find the next chapter to scope the correction guidance correctly
            next_chapter = self._find_next_chapter(scene)
            if next_chapter:
                scope_type = "chapter"
                scope_ref_id = next_chapter.chapter_id
            else:
                # No next chapter found — store globally so it's picked up by any future chapter
                scope_type = "global"
                scope_ref_id = "global"

            # Supersede any prior drift guidance for the same scope
            from novel_system.db.models import LongformStructureGuidance as LSG
            prior_drift = self.session.execute(
                select(LSG).where(
                    LSG.scope_type == scope_type,
                    LSG.scope_ref_id == scope_ref_id,
                    LSG.guidance_id.like("drift_%"),
                    LSG.status == "approved",
                )
            ).scalars().all()
            for prior in prior_drift:
                prior.status = "superseded"

            # §9 Defect B: store both text guidance AND structured drift data
            # so the injection service can do "show" (few-shot) in addition to "tell" (text)
            ptype_priority = drift_corrective_ptype_priority(report)
            drift_bundle_data = format_drift_dimensions_for_bundle(report)
            recommendation = {}
            if ptype_priority:
                recommendation["drift_ptype_priority"] = ptype_priority
            if drift_bundle_data:
                recommendation["drift_dimensions"] = drift_bundle_data

            guidance = LongformStructureGuidance(
                guidance_id=f"drift_{uuid.uuid4().hex[:12]}",
                scope_type=scope_type,
                scope_ref_id=scope_ref_id,
                content=correction,
                recommendation_json=recommendation,
                status="approved",
                runtime_eligible=1,
                source_review_id=f"auto_drift_{scene.chapter_id}",
            )
            self.session.add(guidance)
            self.session.flush()
            _LOGGER.info(
                "§9 style drift correction stored: chapter %s → scope %s/%s, %d dimensions drifting",
                scene.chapter_id, scope_type, scope_ref_id, len(report.drifts),
            )
        except Exception:
            _LOGGER.warning(
                "style drift detection degraded for chapter %s", scene.chapter_id, exc_info=True
            )

    def _find_next_chapter(self, scene: SceneCard) -> ChapterGoal | None:
        """Find the next chapter after the scene's chapter, by display_order."""
        try:
            current = self.session.get(ChapterGoal, scene.chapter_id)
            if current is None or current.display_order is None:
                return None
            return self.session.execute(
                select(ChapterGoal)
                .where(
                    ChapterGoal.project_id == scene.project_id,
                    ChapterGoal.display_order > current.display_order,
                )
                .order_by(ChapterGoal.display_order.asc())
            ).scalars().first()
        except Exception:
            return None

    def _load_style_baseline(self, scene: SceneCard) -> dict[str, float] | None:
        """Load baseline metrics from style reference profile if available."""
        try:
            from novel_system.db.models import StyleReferenceInjectionBinding, StyleReferenceProfile
            binding = self.session.execute(
                select(StyleReferenceInjectionBinding).where(
                    StyleReferenceInjectionBinding.scope == "project",
                    StyleReferenceInjectionBinding.scope_ref_id == scene.project_id,
                    StyleReferenceInjectionBinding.status == "active",
                ).order_by(StyleReferenceInjectionBinding.created_at.desc())
            ).scalars().first()
            if not binding:
                return None
            profile = self.session.get(StyleReferenceProfile, binding.profile_id)
            if profile and profile.profile_json:
                metrics = profile.profile_json.get("metrics_baseline")
                if isinstance(metrics, dict):
                    return metrics
            return None
        except Exception:
            return None

    @staticmethod
    def _best_of_n_count(contract, *, criticality=None) -> int:
        from novel_system.settings import get_settings
        if not get_settings().llm_enabled:
            return 1
        if criticality is not None:
            # Wave 3（§5.5 成本分配）：初始 N；低分散在预算内渐进补到 max_best_of_n
            return criticality.initial_best_of_n
        payload = contract.payload_json or {}
        crucible = payload.get("scene_crucible") or ""
        if crucible and len(crucible) > 10:
            return 3
        return 1

    def _offer_candidates_for_selection(self, scene, state, bundle, candidates) -> list[str] | None:
        """Wave 3（§4.4/§5.5）：确定性坏稿淘汰后建立匿名候选终选 gate。

        机器只淘汰空文本与来源安全 Q0 命中的无效候选（不按机器分数删，
        §4.4）；全部无效时返回 None——管线继续，由 QC 层裁决，不装作可选。
        blinded_order 是随机置换（§5.5 展示顺序必须随机化并记录）。
        """
        import random
        import uuid
        from novel_system.db.models import HumanReviewEvent
        from novel_system.services.source_safety import scan_source_safety

        valid_row_ids: list[str] = []
        for cand in candidates:
            content = (getattr(cand, "content", "") or "").strip()
            if not content:
                continue
            if not scan_source_safety(content).get("safe", True):
                continue
            valid_row_ids.append(cand.row_id)
        if not valid_row_ids:
            _LOGGER.warning(
                "no deterministically valid candidate to offer for scene %s; pipeline continues",
                scene.scene_id,
            )
            return None
        blinded_order = list(valid_row_ids)
        random.shuffle(blinded_order)
        event = HumanReviewEvent(
            event_id=f"hre_sel_{uuid.uuid4().hex[:12]}",
            scene_id=scene.scene_id,
            chapter_id=scene.chapter_id,
            object_ref=f"candidate_selection:{scene.scene_id}",
            event_source="candidate_selection",
            priority="high",
            status="awaiting_review",
            allowed_actions_json=["select", "reopen"],
            details_json={
                "gate_type": "style_candidate_selection",
                "candidate_row_ids": valid_row_ids,
                "blinded_order": blinded_order,
                "decision_status": "awaiting",
                "selected_row_id": None,
                "tokens_used": int(state.scene_tokens_used or 0),
                "decision_history": [],
            },
            default_action="select",
        )
        self.session.add(event)
        state.scene_status = "awaiting_candidate_selection"
        state.current_human_review_event_id = event.event_id
        self.session.flush()
        return valid_row_ids

    def _latest_selection_gate(self, scene_id: str):
        from novel_system.db.models import HumanReviewEvent
        events = self.session.execute(
            select(HumanReviewEvent)
            .where(
                HumanReviewEvent.scene_id == scene_id,
                HumanReviewEvent.event_source == "candidate_selection",
            )
            .order_by(HumanReviewEvent.created_at.desc(), HumanReviewEvent.event_id.desc())
        ).scalars().all()
        for event in events:
            if (event.details_json or {}).get("gate_type") == "style_candidate_selection":
                return event
        return None

    def resume_after_selection(self, scene_id: str) -> dict:
        """Wave 3（§5.5/§6.3）：作者终选后从批判修订/QC 续跑到归档。

        前置：场景停在 awaiting_candidate_selection 且终选 gate 已 selected。
        选中稿即后续批判/软 QC/near-final 的输入（§4.4 上限归人）。
        """
        scene = self.session.get(SceneCard, scene_id)
        if scene is None:
            raise DomainError("SCENE_NOT_FOUND", "scene not found", status_code=404)
        state = self.session.get(SceneRunState, scene_id)
        if state is None or state.scene_status != "awaiting_candidate_selection":
            raise DomainError(
                "RESUME_NOT_AVAILABLE",
                "scene is not awaiting candidate selection",
                status_code=409,
                details={"scene_id": scene_id, "scene_status": getattr(state, "scene_status", None)},
            )
        gate = self._latest_selection_gate(scene_id)
        details = dict(gate.details_json or {}) if gate is not None else {}
        selected_row_id = details.get("selected_row_id")
        if gate is None or details.get("decision_status") != "selected" or not selected_row_id:
            raise DomainError(
                "SELECTION_REQUIRED",
                "author terminal selection is required before resuming",
                status_code=409,
                details={"scene_id": scene_id},
            )
        draft = self.session.get(SceneDraft, selected_row_id)
        if draft is None or not (draft.content or "").strip():
            raise DomainError(
                "CANDIDATE_NOT_FOUND",
                f"selected candidate {selected_row_id} not found or empty",
                status_code=409,
                details={"scene_id": scene_id, "selected_row_id": selected_row_id},
            )

        bundle = self._rebuild_bundle(state)
        contract = self.execution_contract_service.get_or_create(scene_id, actor_ref="orchestrator")
        from novel_system.services.scene_criticality import classify_scene
        chapter = self.session.get(ChapterGoal, scene.chapter_id)
        criticality = classify_scene(
            scene,
            chapter_seq=chapter.display_order if chapter and chapter.display_order is not None else None,
            constraint_intensity=getattr(scene, "constraint_intensity", None),
        )
        planning = self.planning_service.ensure_scene_planning(scene_id)

        state.current_style_draft_row_id = draft.row_id
        state.latest_valid_draft_row_id = draft.row_id
        gate.status = "resolved"
        gate.details_json = {**details, "resumed": True}
        self.session.flush()

        from types import SimpleNamespace
        style_generation = SimpleNamespace(
            row_id=draft.row_id,
            content=draft.content,
            llm_call_id=draft.generation_llm_call_id,
        )
        hard_qc_payload = {
            "branch": "continue",
            "qc_report_id": state.current_qc_report_id,
            "human_review_event_id": None,
            "resolution_code": "resume_after_selection",
            "next_action": "pass",
            "stop_reason": None,
        }
        candidates_total = len(details.get("candidate_row_ids") or []) or 1
        return self._finalize_after_style(
            scene=scene,
            state=state,
            contract=contract,
            bundle=bundle,
            criticality=criticality,
            planning=planning,
            hard_qc_payload=hard_qc_payload,
            style_generation=style_generation,
            candidate_summaries=None,
            candidates_total=candidates_total,
            run_policy=state.run_policy or "reliable",
        )

    def _rebuild_bundle(self, state: SceneRunState) -> dict[str, Any]:
        from novel_system.db.models import SceneBundle
        row = self.session.get(SceneBundle, state.current_bundle_id) if state.current_bundle_id else None
        if row is None:
            raise DomainError(
                "BUNDLE_NOT_FOUND",
                "frozen bundle for resume not found — rerun the scene",
                status_code=409,
                details={"bundle_id": state.current_bundle_id},
            )
        return {
            "bundle_id": row.bundle_id,
            "bundle_snapshot_hash": row.bundle_snapshot_hash,
            "snapshot": row.frozen_snapshot_json or {},
        }

    def _scene_critique_context(self, scene: SceneCard, contract):
        """Build the §8 SceneContext for the LLM editor critic (best-effort; the critic
        degrades gracefully when fields are absent)."""
        from novel_system.services.auto_critique import SceneContext
        payload = getattr(contract, "payload_json", None) or {}
        brief = getattr(scene, "writer_brief_json", None) or {}
        tension = brief.get("tension_target")
        return SceneContext(
            scene_goal=str(getattr(scene, "scene_goal", "") or payload.get("scene_goal") or ""),
            tension_target=tension if isinstance(tension, int) else None,
            cost_requirement=str(payload.get("cost_requirement") or brief.get("cost_requirement") or ""),
        )

    def _run_pre_generation_diagnostics(self, scene: SceneCard, chapter: ChapterGoal | None) -> None:
        """Blueprint §10/§12: pre-generation tension curve + theme relevance diagnostics.

        These checks are non-blocking (logged as warnings) — the execution contract
        handles hard blocking. This provides early feedback on rhythm and theme health.
        """
        # §10: tension curve adjacent-tag and monotony check
        if chapter is not None:
            try:
                from novel_system.services.tension_curve import TensionCurveService
                tension_svc = TensionCurveService(self.session)
                tension_report = tension_svc.validate_chapter(chapter.chapter_id)
                for v in tension_report.violations:
                    _LOGGER.warning(
                        "§10 tension violation in chapter %s scene %s: [%s] %s",
                        chapter.chapter_id, v.scene_id, v.violation_type, v.message,
                    )
                # §10: chapter-end hook type adjacency check
                hook_violations = tension_svc.validate_chapter_hooks(chapter.chapter_id)
                for hv in hook_violations:
                    _LOGGER.warning(
                        "§10 hook violation in chapter %s scene %s: [%s] %s",
                        chapter.chapter_id, hv.scene_id, hv.violation_type, hv.message,
                    )
            except Exception:
                _LOGGER.debug("tension curve diagnostics skipped", exc_info=True)

        # §12: theme relevance check
        project_id = scene.project_id
        if project_id:
            try:
                from novel_system.services.theme_anchor import ThemeAnchorService
                theme_svc = ThemeAnchorService(self.session)
                idea = theme_svc.get_controlling_idea(project_id)
                if idea:
                    check = theme_svc.check_scene_relevance(scene, idea)
                    if not check.relevant:
                        _LOGGER.warning(
                            "§12 theme relevance warning for scene %s: %s — %s",
                            scene.scene_id, check.connection, check.suggestion,
                        )
            except Exception:
                _LOGGER.debug("theme relevance diagnostics skipped", exc_info=True)

    @staticmethod
    def _soft_qc_result_payload(soft_qc) -> dict[str, str | None]:
        return {
            "branch": soft_qc.branch,
            "qc_report_id": soft_qc.qc_report_id,
            "human_review_event_id": soft_qc.human_review_event_id,
            "resolution_code": soft_qc.resolution_code,
            "next_action": soft_qc.next_action,
            "stop_reason": soft_qc.stop_reason,
        }
