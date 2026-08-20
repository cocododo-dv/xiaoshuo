"""MaterializationService — profile → ReviewItem → 4 集合自动分发。

参见《风格参考模块重构执行手册 v1.1》§3 / §10 与 plans/style-reference-v1-1-fancy-shannon.md
§"Materialization 流程"。

PR-4 决策:按 sub_dim layer 自动分发(用户拍板选 A):
- observation + language.*           → item_type=style_rule_set     → style_rules
- observation + narrative.*/scene.*/theme.* → item_type=narrative_pattern → narrative_patterns
- forbidden_pattern (任 sub_dim)     → item_type=banned_rule_cluster  → banned_rule_clusters
- profile.calibration_guidance       → item_type=calibration_candidate → calibration_lines

ReviewItem 写入时 review_id 用前缀 `review_style_ref_apply_`(与旧 review_apply_*
物理隔离),candidate_payload_json.source="style_reference_apply"。

approve 时由仓库现有 `services/versioning/review_materialization.py:
ReviewMaterializationService.materialize_review(review_id)` 通过
review_items.target_collection Computed 列自动写入 4 集合。
"""

from __future__ import annotations

import hashlib
import logging
import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from novel_system.db.models import ReviewItem
from novel_system.services.errors import DomainError
from novel_system.services.style_reference.repository import StyleReferenceRepository
from novel_system.services.style_reference.schemas import (
    BindingScope,
    BindingStatus,
    InjectionStrategy,
    ProfileStatus,
    TaskType,
)

logger = logging.getLogger(__name__)


REVIEW_PREFIX = "review_style_ref_apply_"
REVIEW_CALIB_PREFIX = "review_style_ref_calib_"
PAYLOAD_SOURCE = "style_reference_apply"


@dataclass
class MaterializeResult:
    """apply_profile 返回结构。"""

    profile_id: str
    binding_id: str
    review_ids: list[str] = field(default_factory=list)
    item_type_counts: dict[str, int] = field(default_factory=dict)
    rag_index: dict[str, Any] = field(default_factory=dict)


class MaterializationService:
    """Profile → ReviewItem(prefix `review_style_ref_apply_`)→ binding 行编排。"""

    def __init__(self, session: Session) -> None:
        self.session = session
        self.repo = StyleReferenceRepository(session)

    def apply_profile(
        self,
        profile_id: str,
        *,
        scope: BindingScope | str,
        scope_ref_id: str | None,
        task_type: TaskType | str = TaskType.SCENE_GENERATION,
        strategy: InjectionStrategy | str | None = None,
        config_json: dict[str, Any] | None = None,
    ) -> MaterializeResult:
        """``config_json`` 落入 binding(intensity / sub_dimensions / include 开关),
        由 InjectionService._render 在注入时消费——前端强度滑块的端到端落点。"""
        # BindingScope 三种 scope(project/scene/character)都按 scope_ref_id 匹配
        # (_binding_rank),缺 ref 的绑定永远 rank=99,是解析不到的死绑定——拒绝落库
        if not (scope_ref_id and str(scope_ref_id).strip()):
            raise DomainError(
                "STYLE_REFERENCE_APPLY_PARAM_INVALID",
                f"scope={_enum_value(scope)} requires a non-empty scope_ref_id",
                status_code=400,
            )
        profile = self.repo.get_profile(profile_id)
        if profile is None:
            raise DomainError(
                "STYLE_REFERENCE_PROFILE_NOT_FOUND",
                f"profile {profile_id!r} not found",
                status_code=404,
            )
        coverage = profile.coverage_json or {}
        if coverage.get("stale"):
            raise DomainError(
                "STYLE_REFERENCE_PROFILE_STALE",
                "profile source findings changed after synthesis; synthesize a new profile before applying",
                status_code=409,
            )
        if profile.status == ProfileStatus.ARCHIVED.value:
            raise DomainError(
                "STYLE_REFERENCE_PROFILE_ARCHIVED",
                "archived profile cannot be applied",
                status_code=409,
            )

        if strategy is None:
            from novel_system.services.style_reference.injection import (
                default_injection_strategy,
            )

            strategy = default_injection_strategy(task_type)

        # 1. finding → ReviewItem(按 sub_dim layer 分发)
        review_ids: list[str] = []
        counts: dict[str, int] = {}
        finding_ids = profile.source_finding_ids_json or []
        for finding_id in finding_ids:
            finding = self.repo.get_finding(finding_id)
            if finding is None:
                logger.warning("finding %s not found, skipping", finding_id)
                continue
            item_type = _classify_finding_item_type(finding)
            review_id = _make_review_id(REVIEW_PREFIX, profile_id, finding_id)
            self._upsert_review_item(
                review_id=review_id,
                item_type=item_type,
                candidate_text=finding.statement,
                candidate_payload_json={
                    "source": PAYLOAD_SOURCE,
                    "scope": _enum_value(scope),
                    "scope_ref_id": scope_ref_id,
                    "profile_id": profile_id,
                    "finding_id": finding_id,
                    "sub_dimension": finding.sub_dimension,
                    "finding_kind": finding.finding_kind,
                },
            )
            review_ids.append(review_id)
            counts[item_type] = counts.get(item_type, 0) + 1

        # 2. calibration_guidance → ReviewItem(独立路径)
        calib_lines = (profile.profile_json or {}).get("calibration_guidance") or []
        for idx, line in enumerate(calib_lines):
            if not isinstance(line, str) or not line.strip():
                continue
            review_id = _make_calibration_review_id(profile_id, idx, line)
            self._upsert_review_item(
                review_id=review_id,
                item_type="calibration_candidate",
                candidate_text=line.strip(),
                candidate_payload_json={
                    "source": PAYLOAD_SOURCE,
                    "scope": _enum_value(scope),
                    "scope_ref_id": scope_ref_id,
                    "profile_id": profile_id,
                    "calibration_index": idx,
                },
            )
            review_ids.append(review_id)
            counts["calibration_candidate"] = counts.get("calibration_candidate", 0) + 1

        # 3. 写 binding 行
        binding_id = self._upsert_binding(
            profile_id=profile_id,
            scope=scope,
            scope_ref_id=scope_ref_id,
            task_type=task_type,
            strategy=strategy,
            config_json=config_json,
        )

        # 4. Q1 修复：激活 profile。此前 synthesize 产 DRAFT、apply 只建 active binding，
        #    却从不把 profile 本身置 active；而注入(InjectionService / scene_execution)
        #    硬要求 profile.status=="active"，导致真实流程(导入→抽取→合成→应用)后
        #    风格注入恒为空(no-op)——整个风格参考在生成期失效。apply 即"让该 profile
        #    在某 scope 生效"，随 active binding 一并激活 profile，使绑定与注入一致生效。
        profile.status = ProfileStatus.ACTIVE.value
        self.session.flush()

        # 5. v2 内容克制 RAG 索引就绪检查。新画像在 synthesize 时通常已建好；
        #    老画像或曾中断的部分索引在 apply/re-apply 时自动、幂等升级。向量后端
        #    属于增强能力，失败不得撤销已经合法完成的绑定与 ReviewItem 写入。
        try:
            from novel_system.services.style_reference.rag import ensure_rag_index

            rag_index = ensure_rag_index(
                self.session,
                profile,
                book_id=profile.book_id,
            )
        except Exception:  # noqa: BLE001
            logger.warning(
                "rag index ensure failed for profile %s",
                profile.profile_id,
                exc_info=True,
            )
            rag_index = {"skipped": "build_failed"}

        return MaterializeResult(
            profile_id=profile_id,
            binding_id=binding_id,
            review_ids=review_ids,
            item_type_counts=counts,
            rag_index=rag_index,
        )

    # ------------------------------------------------------------- internals

    def _upsert_review_item(
        self,
        *,
        review_id: str,
        item_type: str,
        candidate_text: str,
        candidate_payload_json: dict[str, Any],
    ) -> None:
        """已存在则 update payload + status reset to pending(幂等 apply)。"""
        existing = self.session.get(ReviewItem, review_id)
        if existing is None:
            review = ReviewItem(
                review_id=review_id,
                item_type=item_type,
                status="pending",
                candidate_text=candidate_text,
                candidate_payload_json=candidate_payload_json,
                active_on_approve=1,
            )
            self.session.add(review)
            self.session.flush()
            return
        existing.item_type = item_type
        existing.candidate_text = candidate_text
        existing.candidate_payload_json = candidate_payload_json
        # 不动 status / materialize_status,允许人工反复审核
        self.session.flush()

    def _upsert_binding(
        self,
        *,
        profile_id: str,
        scope: BindingScope | str,
        scope_ref_id: str | None,
        task_type: TaskType | str,
        strategy: InjectionStrategy | str,
        config_json: dict[str, Any] | None = None,
    ) -> str:
        scope_value = _enum_value(scope)
        task_type_value = _enum_value(task_type)
        strategy_value = _enum_value(strategy)
        # 同 (profile, scope, scope_ref_id, task_type) 已存在则复用,
        # 重复 apply 更新 strategy / config(滑块调整后重新应用即生效)
        existing = self.repo.list_bindings(
            profile_id=profile_id, task_type=task_type_value
        )
        for b in existing:
            if b.scope == scope_value and b.scope_ref_id == scope_ref_id:
                b.strategy = strategy_value
                if config_json is not None:
                    b.config_json = config_json
                self.session.flush()
                return b.binding_id
        binding = self.repo.create_binding(
            binding_id=f"sr_bind_{uuid.uuid4().hex[:12]}",
            profile_id=profile_id,
            scope=scope_value,
            scope_ref_id=scope_ref_id,
            task_type=task_type_value,
            strategy=strategy_value,
            config_json=config_json or {},
            status=BindingStatus.ACTIVE.value,
        )
        return binding.binding_id


# ---------------------------------------------------------------------------
# 辅助:finding → item_type 分发规则
# ---------------------------------------------------------------------------


def _classify_finding_item_type(finding) -> str:  # noqa: ANN001
    """按 sub_dim layer 与 finding_kind 决定 item_type。

    决策表(PR-4 用户拍板,plans §"PR-4 已敲定决策"):
      forbidden_pattern → banned_rule_cluster
      observation + sub_dim 以 "language." 开头 → style_rule_set
      observation + sub_dim 以 "narrative."/"scene."/"theme." 开头 → narrative_pattern
    """
    if finding.finding_kind == "forbidden_pattern":
        return "banned_rule_cluster"
    sub_dim = finding.sub_dimension or ""
    if sub_dim.startswith("language."):
        return "style_rule_set"
    # narrative / scene / theme 都归 narrative_pattern
    return "narrative_pattern"


def _make_review_id(prefix: str, profile_id: str, finding_id: str) -> str:
    p = profile_id[-12:] if len(profile_id) > 12 else profile_id
    f = finding_id[-12:] if len(finding_id) > 12 else finding_id
    return f"{prefix}{p}_{f}"


def _make_calibration_review_id(profile_id: str, idx: int, line: str) -> str:
    p = profile_id[-12:] if len(profile_id) > 12 else profile_id
    line_hash = hashlib.sha256(line.strip().encode("utf-8")).hexdigest()[:8]
    return f"{REVIEW_CALIB_PREFIX}{p}_{idx:02d}_{line_hash}"


def _enum_value(value: Any) -> str:
    if hasattr(value, "value"):
        return value.value
    return str(value)
