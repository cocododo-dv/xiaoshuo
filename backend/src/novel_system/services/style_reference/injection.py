"""PR-8 §5.1 — StyleProfile 注入到 LLM system_prompt 的服务。

InjectionService 给定 `project_id` 与 `task_type`,从 `style_reference_injection_bindings`
查 active binding,再读 profile.profile_json + 关联 forbidden_pattern findings,
按 binding.strategy 拼成 :class:`SystemPromptFragments`(3 风格 block +
anti_plagiarism 红线段 + strategy 回填)。红线段(§A.5)在任一风格 block 非空时
必随注入且永不截断。

调用方(scene_generation / chapter_draft 等)拿到 fragments 后调
``fragments.to_system_prompt_prefix()`` 得到字符串,prepend 到 LLM
``messages[0]["content"]`` 头部。

Strategy 实现摘要:
- **A** — positive + forbidden + metric_anchor 三块全文注入(默认)
- **B** — 按 ``config/style_reference/injection_budget.yaml`` 预算截断
- **C** — positive 全文 + forbidden 摘要(≤200 字) + 不注入 metric_anchor
- **MIXED** — binding.config_json 自定义 ``include_positive`` /
  ``include_forbidden`` / ``include_metric`` 三个布尔开关
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from novel_system.services.style_reference.config_loader import (
    load_text_template,
    load_yaml_config,
)
from novel_system.services.style_reference.metrics_recorder import MetricsRecorder
from novel_system.services.style_reference.repository import StyleReferenceRepository
from novel_system.services.style_reference.schemas import (
    InjectionStrategy,
    SystemPromptFragments,
)

_DEFAULT_BUDGET = {
    "system_prompt_max_tokens": 800,
    "positive_block_ratio": 0.6,
    "forbidden_block_ratio": 0.3,
    "metric_anchor_block_ratio": 0.1,
}

# 配置文件缺失时的红线兜底:抄袭事前预防段不允许因部署缺配置而消失(§11 风险 11)
_FALLBACK_ANTI_PLAGIARISM = """## 严格禁止
- 复用或微改任何参考样本中的完整句子
- 直接搬运超过 5 个连续字符的独特表达(常用词、人名、地名除外)
- 参考样本中的意象可重复使用,但承载这些意象的句子必须完全重写
- 若你不确定某个表达是否来自参考样本,默认认为是,改写它
{banned_terms_list}"""


def _load_budget() -> dict[str, Any]:
    try:
        return {**_DEFAULT_BUDGET, **load_yaml_config("injection_budget")}
    except FileNotFoundError:
        return dict(_DEFAULT_BUDGET)


def _truncate(text: str, max_chars: int) -> str:
    if max_chars <= 0 or len(text) <= max_chars:
        return text
    if max_chars <= 1:
        return text[:max_chars]
    return text[: max_chars - 1] + "…"


def _truncate_lines(text: str, max_chars: int) -> str:
    """行边界感知截断:block 都是「标题行 + '- xxx' 条目行」结构,
    在最后一个完整行处截断,避免把一条禁忌/特征截成半句送给 LLM。

    行边界截断会损失超过一半预算时(单条目超长的退化情形),回退为
    字符截断——半句好过整块丢失。"""
    if max_chars <= 0 or len(text) <= max_chars:
        return text
    cut = text.rfind("\n", 0, max_chars)
    if cut <= max_chars // 2:
        return _truncate(text, max_chars)
    return text[:cut]


def _cap_fragments(frag: "SystemPromptFragments", budget: int) -> "SystemPromptFragments":
    """PR-16 叠加专属:按 ratio(0.6/0.3/0.1)硬截 3 block(不管 strategy)。

    anti_plagiarism_block 是红线段,**永不截断**,原样保留。
    few_shot_block 在叠加路径不传(多本书样例混叠只会稀释风格信号),
    构造时默认为空即为丢弃。
    """
    return SystemPromptFragments(
        positive_block=_truncate_lines(frag.positive_block, int(budget * 0.6)),
        forbidden_block=_truncate_lines(frag.forbidden_block, int(budget * 0.3)),
        metric_anchor_block=_truncate_lines(frag.metric_anchor_block, int(budget * 0.1)),
        anti_plagiarism_block=frag.anti_plagiarism_block,
        strategy=frag.strategy,
    )


def _merge_forbidden_blocks(*blocks: str) -> str:
    """PR-19 — 合并任意多个 [禁忌模式] block,'- xxx' 行去重保序(由泛到具体)。"""
    seen: set[str] = set()
    items: list[str] = []
    for block in blocks:
        for line in block.splitlines():
            s = line.strip()
            if s.startswith("- ") and s not in seen:
                seen.add(s)
                items.append(s)
    if not items:
        return ""
    return "[禁忌模式]\n" + "\n".join(items)


def _merge_fragments(layers_frags: list["SystemPromptFragments"]) -> "SystemPromptFragments":
    """PR-19 — 多层合并(由泛到具体):positive 顺序拼 / forbidden 全层去重 /
    metric 最具体优先(反向取首个非空)/ strategy 取最具体层。"""
    positive = "\n\n".join(
        f.positive_block for f in layers_frags if f.positive_block.strip()
    )
    forbidden = _merge_forbidden_blocks(*[f.forbidden_block for f in layers_frags])
    metric = ""
    for f in reversed(layers_frags):  # 最具体层优先
        if f.metric_anchor_block.strip():
            metric = f.metric_anchor_block
            break
    return SystemPromptFragments(
        positive_block=positive,
        forbidden_block=forbidden,
        metric_anchor_block=metric,
        anti_plagiarism_block=_merge_anti_plagiarism(
            *[f.anti_plagiarism_block for f in layers_frags]
        ),
        strategy=layers_frags[-1].strategy,
    )


def _merge_anti_plagiarism(*blocks: str) -> str:
    """多层叠加时合并红线段:模板正文取首个非空(各层同模板),
    banned_terms 条目行('- xxx')取**全层并集**——叠加注入引用了多本书的
    风格,任何一层的禁用专有名词都必须保留。"""
    non_empty = [b for b in blocks if b.strip()]
    if not non_empty:
        return ""
    if len(non_empty) == 1:
        return non_empty[0]
    base = non_empty[0]
    base_lines = base.splitlines()
    seen = {s.strip() for s in base_lines if s.strip().startswith("- ")}
    extra: list[str] = []
    for block in non_empty[1:]:
        for line in block.splitlines():
            s = line.strip()
            if s.startswith("- ") and s not in seen:
                seen.add(s)
                extra.append(s)
    if not extra:
        return base
    return base + "\n" + "\n".join(extra)


def ordered_character_ids(pov_id, onstage_ids) -> list[str]:
    """PR-18 — character 匹配集:pov 排首 + onstage 去重(pov 可能不在 onstage 内)。"""
    ordered: list[str] = []
    if pov_id:
        ordered.append(pov_id)
    for cid in (onstage_ids or []):
        if cid and cid != pov_id:
            ordered.append(cid)
    return ordered


def _binding_rank(
    b,
    *,
    project_id: str | None,
    character_ids: list[str] | None,
    scene_id: str | None,
) -> int:
    """binding 优先级 rank(PR-14/15/16/18 单点):scene=0 > character=1 > project=2 > global=3。

    不匹配返 99(剔除)。resolve_active_binding(单选)与 resolve_binding_layers(叠加)共用。
    PR-18 — character 匹配 character_ids 任一(onstage 多角色)。
    """
    if scene_id and b.scope == "scene" and b.scope_ref_id == scene_id:
        return 0
    if character_ids and b.scope == "character" and b.scope_ref_id in character_ids:
        return 1
    if project_id and b.scope == "project" and b.scope_ref_id == project_id:
        return 2
    if b.scope == "global":
        return 3
    return 99  # 不匹配


def _char_order(b, character_ids: list[str] | None) -> int:
    """PR-18 — character binding 在匹配集中的位置(pov=0 最优先);非 character 返 0。"""
    if b.scope == "character" and character_ids and b.scope_ref_id in character_ids:
        return character_ids.index(b.scope_ref_id)
    return 0


class InjectionService:
    """读 active binding + profile,渲染 SystemPromptFragments。"""

    def __init__(self, session: Session):
        self.session = session
        self.repo = StyleReferenceRepository(session)
        self._last_profile_id: str | None = None
        self._last_binding_id: str | None = None
        self._last_base_binding_id: str | None = None
        self._last_layer_count: int = 0
        # §9 Defect B: drift-corrective few-shot context — set by caller before
        # fragments_for() to override the default ptype priority with dimension-targeted
        # exemplars ("show, don't tell" drift correction).
        self.drift_ptype_priority: list[str] | None = None

    # --------------------------------------------------------------- public
    def fragments_for(
        self,
        project_id: str | None,
        task_type: str,
        *,
        character_ids: list[str] | None = None,
        scene_id: str | None = None,
    ) -> SystemPromptFragments:
        """主入口。无 active binding / profile 时返 empty fragments(no-op)。

        PR-14/15/18 — scene_id / character_ids 非空时优先匹配对应 scope binding
        (scene > character > project > global);character_ids 为 onstage 多角色匹配集。
        """
        fragments = self._resolve_fragments(
            project_id, task_type, character_ids=character_ids, scene_id=scene_id,
        )
        self._record_invocation(project_id, task_type, fragments)
        return fragments

    def _resolve_fragments(
        self,
        project_id: str | None,
        task_type: str,
        *,
        character_ids: list[str] | None = None,
        scene_id: str | None = None,
    ) -> SystemPromptFragments:
        if not project_id and not character_ids and not scene_id:
            return SystemPromptFragments()
        layers = self.resolve_binding_layers(
            project_id, task_type, character_ids=character_ids, scene_id=scene_id,
        )
        if not layers:
            return SystemPromptFragments()
        # 单层 → 走原路径,行为零回归(strategy 全语义,不 cap)
        if len(layers) == 1:
            return self._fragments_from_binding(layers[0])
        # PR-16/19 多层加权叠加:由泛到具体,越具体预算越多
        total = self._budget_total()
        n = len(layers)
        weights = list(range(1, n + 1))  # [1,2] / [1,2,3]
        wsum = sum(weights)
        capped = [
            _cap_fragments(self._render_binding(b), total * weights[i] // wsum)
            for i, b in enumerate(layers)
        ]
        merged = _merge_fragments(capped)
        self._last_profile_id = layers[-1].profile_id      # 最具体层
        self._last_binding_id = layers[-1].binding_id
        self._last_base_binding_id = layers[0].binding_id  # 最泛层
        self._last_layer_count = n
        return merged

    def _fragments_from_binding(self, binding) -> SystemPromptFragments:
        """单层路径:get_profile + _render,profile active 时记 last id(同 PR-15 行为)。"""
        profile = self.repo.get_profile(binding.profile_id)
        if profile is None or profile.status != "active":
            return SystemPromptFragments()
        self._last_profile_id = binding.profile_id
        self._last_binding_id = binding.binding_id
        return self._render_for(profile, binding)

    def _render_binding(self, binding) -> SystemPromptFragments:
        """叠加路径:按 binding 自己的 strategy 渲染 fragments(不记 last id)。"""
        profile = self.repo.get_profile(binding.profile_id)
        if profile is None or profile.status != "active":
            return SystemPromptFragments()
        return self._render_for(profile, binding)

    def _render_for(self, profile, binding) -> SystemPromptFragments:
        try:
            strategy = InjectionStrategy(binding.strategy)
        except ValueError:
            strategy = InjectionStrategy.A
        return self._render(
            profile, strategy, binding.config_json or {},
            drift_ptype_priority=self.drift_ptype_priority,
        )

    def _budget_total(self) -> int:
        return int(_load_budget().get("system_prompt_max_tokens", 800))

    def _record_invocation(
        self,
        project_id: str | None,
        task_type: str,
        fragments: SystemPromptFragments,
    ) -> None:
        prefix = fragments.to_system_prompt_prefix()
        outcome = "hit" if prefix else "miss"
        MetricsRecorder.record(
            self.session,
            "injection_invoked",
            target_kind="project" if project_id else None,
            target_ref_id=project_id,
            profile_id=getattr(self, "_last_profile_id", None),
            binding_id=getattr(self, "_last_binding_id", None),
            outcome=outcome,
            context={
                "task_type": task_type,
                "strategy": fragments.strategy.value,
                # PR-16/19 — 叠加标记 + base binding + 命中层数(运营区分单层/多层叠加)
                "layered": self._last_base_binding_id is not None,
                "base_binding_id": self._last_base_binding_id,
                "layer_count": self._last_layer_count or (1 if prefix else 0),
            },
        )
        # 用完即清,避免下一次 invocation 错误复用
        self._last_profile_id = None
        self._last_binding_id = None
        self._last_base_binding_id = None
        self._last_layer_count = 0

    # ------------------------------------------------------------- binding 选取
    def resolve_active_binding(
        self,
        project_id: str | None,
        task_type: str,
        *,
        character_ids: list[str] | None = None,
        scene_id: str | None = None,
    ):
        """优先级单选:scene > character > project > global,取最具体的一个。

        PR-14/15/18 — InjectionService 与 qc_engine 共用的 binding 选取单点。
        scene_id / character_ids 为空时跳过对应 rank(向下兼容)。
        character 多命中按 char_order(pov 优先,其余 onstage 顺序)决平,再 created_at。
        """
        if not project_id and not character_ids and not scene_id:
            return None
        bindings = [
            b
            for b in self.repo.list_bindings(task_type=task_type)
            if b.status == "active"
        ]
        if not bindings:
            return None

        def _rank(b) -> int:
            return _binding_rank(
                b, project_id=project_id, character_ids=character_ids, scene_id=scene_id,
            )

        candidates = [b for b in bindings if _rank(b) < 99]
        if not candidates:
            return None
        candidates.sort(
            key=lambda b: (_rank(b), _char_order(b, character_ids), -1 * _ts_to_int(b.created_at))
        )
        return candidates[0]

    def resolve_binding_layers(
        self,
        project_id: str | None,
        task_type: str,
        *,
        character_ids: list[str] | None = None,
        scene_id: str | None = None,
    ):
        """PR-20 — 返由泛到具体的命中层 list:base(project>global,单)+ character
        (onstage 全配角,pov 优先)+ scene(单),过滤 None。

        character 层从 PR-19 单选进化为多配角全叠:每个 onstage 命中角色各占一层,
        按 char_order(pov 优先)+ created_at 排序,并按 scope_ref_id 去重(每角色一层)。
        供多层加权叠加用(单层时 list 长度 1,走原路径零回归)。
        """
        if not project_id and not character_ids and not scene_id:
            return []
        bindings = [
            b
            for b in self.repo.list_bindings(task_type=task_type)
            if b.status == "active"
        ]
        if not bindings:
            return []

        def _rank(b) -> int:
            return _binding_rank(
                b, project_id=project_id, character_ids=character_ids, scene_id=scene_id,
            )

        def _pick(allowed: set[int]):
            cands = [b for b in bindings if _rank(b) in allowed]
            if not cands:
                return None
            cands.sort(
                key=lambda b: (_rank(b), _char_order(b, character_ids), -1 * _ts_to_int(b.created_at))
            )
            return cands[0]

        def _pick_all_characters():
            """PR-20 — 全部 rank1 命中,pov 优先 + created_at 决平,按 character_id 去重(每角色一层)。"""
            cands = [b for b in bindings if _rank(b) == 1]
            cands.sort(
                key=lambda b: (_char_order(b, character_ids), -1 * _ts_to_int(b.created_at))
            )
            seen: set[str] = set()
            out = []
            for b in cands:
                if b.scope_ref_id not in seen:
                    seen.add(b.scope_ref_id)
                    out.append(b)
            return out

        base = _pick({2, 3})              # project > global(基底,单)
        characters = _pick_all_characters()  # onstage 全配角,pov 优先(PR-20)
        scene_b = _pick({0})              # scene(最具体,单)
        layers = []
        if base is not None:
            layers.append(base)
        layers.extend(characters)
        if scene_b is not None:
            layers.append(scene_b)
        return layers                     # 由泛到具体

    def _render(
        self,
        profile,
        strategy: InjectionStrategy,
        config: dict[str, Any],
        *,
        drift_ptype_priority: list[str] | None = None,
    ) -> SystemPromptFragments:
        sub_dims_raw = config.get("sub_dimensions")
        sub_dims = [str(s) for s in sub_dims_raw] if sub_dims_raw else None
        positive = self._render_positive(profile)
        forbidden = self._render_forbidden(profile, sub_dims=sub_dims)
        metric = self._render_metric(profile)
        few_shot = ""

        if strategy == InjectionStrategy.B:
            positive, forbidden, metric = self._apply_budget(positive, forbidden, metric)
            few_shot = self._render_few_shot(profile, drift_ptype_priority=drift_ptype_priority)
        elif strategy == InjectionStrategy.C:
            forbidden = self._summarize_forbidden(forbidden, max_chars=200)
            metric = ""
        elif strategy == InjectionStrategy.MIXED:
            # PR-9 §"intensity 语义" — 0-100 缩放 ratio:0 → 0.3x, 50 → 0.9x, 100 → 1.5x;
            # 但三块截断额之和封顶 system_prompt_max_tokens(配置语义是 max,
            # 高 intensity 不允许溢出预算 50%,超出部分按比例回缩)
            try:
                intensity = max(0, min(100, int(config.get("intensity", 50))))
            except (TypeError, ValueError):
                intensity = 50
            scale = 0.3 + (intensity / 100.0) * 1.2
            budget = _load_budget()
            total = int(budget.get("system_prompt_max_tokens", 800))
            p_ratio = float(budget.get("positive_block_ratio", 0.6))
            f_ratio = float(budget.get("forbidden_block_ratio", 0.3))
            m_ratio = float(budget.get("metric_anchor_block_ratio", 0.1))
            caps = {
                "positive": int(total * p_ratio * scale) if config.get("include_positive", True) else 0,
                "forbidden": int(total * f_ratio * scale) if config.get("include_forbidden", True) else 0,
                "metric": int(total * m_ratio * scale) if config.get("include_metric", False) else 0,
            }
            cap_sum = sum(caps.values())
            if cap_sum > total > 0:
                shrink = total / cap_sum
                caps = {k: int(v * shrink) for k, v in caps.items()}
            positive = _truncate_lines(positive, caps["positive"]) if caps["positive"] else ""
            forbidden = _truncate_lines(forbidden, caps["forbidden"]) if caps["forbidden"] else ""
            metric = _truncate_lines(metric, caps["metric"]) if caps["metric"] else ""

        # §A.5 / §11 风险 11 — 抄袭事前预防红线段:任一风格 block 非空时必随注入,
        # 不参与任何预算截断;few-shot 引用原文片段,更必须带红线
        anti_plagiarism = ""
        if positive.strip() or forbidden.strip() or metric.strip() or few_shot.strip():
            anti_plagiarism = self._render_anti_plagiarism(profile)

        return SystemPromptFragments(
            positive_block=positive,
            forbidden_block=forbidden,
            metric_anchor_block=metric,
            few_shot_block=few_shot,
            anti_plagiarism_block=anti_plagiarism,
            strategy=strategy,
        )

    def _render_few_shot(self, profile, *, drift_ptype_priority: list[str] | None = None) -> str:
        """Strategy B few-shot:从 profile.scene_samples_index 直读样例引文。

        每种段落类型最多取 1 条,按对风格感最有信息量的类型优先;
        样例引用原文,因此调用方(_render)保证红线段必随注入。

        §9 Defect B — drift_ptype_priority: when drift correction is active, the caller
        passes a re-ordered priority list (from style_drift_detector.drift_corrective_ptype_priority)
        so the few-shot exemplars "show" the correct baseline for drifted dimensions
        rather than just "telling" the model to adjust.
        """
        budget = _load_budget()
        k = int(budget.get("few_shot_k", 3))
        quote_max = int(budget.get("few_shot_quote_max_chars", 120))
        block_max = int(budget.get("few_shot_block_max_chars", 480))
        if k <= 0:
            return ""
        samples_index: dict[str, Any] = (
            (profile.profile_json or {}).get("scene_samples_index") or {}
        )
        if not isinstance(samples_index, dict) or not samples_index:
            return ""
        # §9: drift-corrective priority overrides static default when active
        if drift_ptype_priority:
            # Merge: drift-relevant types first, then remaining types in default order
            _default_order = [
                "dialogue", "description_env", "action", "psychology",
                "narration", "description_char", "transition", "flashback",
            ]
            seen = set(drift_ptype_priority)
            preferred = tuple(drift_ptype_priority) + tuple(p for p in _default_order if p not in seen)
        else:
            preferred = (
                "dialogue",
                "description_env",
                "action",
                "psychology",
                "narration",
                "description_char",
                "transition",
                "flashback",
            )
        header = (
            "[风格样例 — 漂移修正](以下样例针对检测到的风格偏移维度;体会句式与节奏;严禁照抄)"
            if drift_ptype_priority
            else "[风格样例](体会句式与节奏;严禁照抄或微改其中任何句子)"
        )
        lines = [header]
        picked = 0
        for ptype in preferred:
            if picked >= k:
                break
            quote_ids = samples_index.get(ptype) or []
            if not quote_ids:
                continue
            quote = self.repo.get_quote(str(quote_ids[0]))
            text = (getattr(quote, "quote_text", "") or "").strip() if quote else ""
            if not text:
                continue
            lines.append(f"- ({ptype})「{_truncate(text, quote_max)}」")
            picked += 1
        if picked == 0:
            return ""
        return _truncate_lines("\n".join(lines), block_max)

    def _render_anti_plagiarism(self, profile) -> str:
        """渲染 §A.5 红线段:固定模板 + banned_terms(scope=generation)填充。

        模板文件缺失时使用内置兜底——红线段不允许因部署缺配置而消失。
        """
        try:
            template = load_text_template("anti_plagiarism_template")
        except FileNotFoundError:
            template = _FALLBACK_ANTI_PLAGIARISM
        terms = [
            (t.term or "").strip()
            for t in self.repo.list_banned_terms(profile.profile_id, scope="generation")
        ]
        terms = [t for t in terms if t]
        if terms:
            terms_text = "\n".join(f"- {t}" for t in terms)
        else:
            # 无自定义禁词时去掉「专有名词」引导句,只保留红线规则
            template = template.split("此外,")[0].rstrip()
            terms_text = ""
        return template.replace("{banned_terms_list}", terms_text).strip()

    def _render_positive(self, profile) -> str:
        data = profile.profile_json or {}
        narrative = (data.get("narrative_summary") or "").strip()
        features = [f.strip() for f in (data.get("style_features") or []) if str(f).strip()]
        patterns = [p.strip() for p in (data.get("narrative_patterns") or []) if str(p).strip()]
        if not (narrative or features or patterns):
            return ""
        lines: list[str] = ["[正向风格特征]"]
        if narrative:
            lines.append(f"概述:{narrative}")
        if features:
            lines.append("风格要点:")
            lines.extend(f"- {item}" for item in features)
        if patterns:
            lines.append("叙事模式:")
            lines.extend(f"- {item}" for item in patterns)
        return "\n".join(lines)

    def _render_forbidden(self, profile, *, sub_dims: list[str] | None = None) -> str:
        """渲染禁忌模式块。

        ``sub_dims`` 为 None 或空 list 时**全部 16 维**;否则按 sub_dim 过滤
        finding(banned_replication_rules 在 profile_json 中无 sub_dim 归属,
        始终保留)。
        """
        rules = [
            r.strip()
            for r in ((profile.profile_json or {}).get("banned_replication_rules") or [])
            if str(r).strip()
        ]
        finding_statements = self._collect_forbidden_finding_statements(profile, sub_dims=sub_dims)
        if not (rules or finding_statements):
            return ""
        lines = ["[禁忌模式]"]
        for rule in rules:
            lines.append(f"- {rule}")
        for stmt in finding_statements:
            lines.append(f"- {stmt}")
        return "\n".join(lines)

    def _collect_forbidden_finding_statements(
        self,
        profile,
        *,
        sub_dims: list[str] | None = None,
    ) -> list[str]:
        ids = profile.source_finding_ids_json or []
        statements: list[str] = []
        sub_dim_filter = set(sub_dims) if sub_dims else None
        for fid in ids:
            row = self.repo.get_finding(fid)
            if row is None or row.finding_kind != "forbidden_pattern":
                continue
            # PR-23 — 被驳回的禁忌不注入 system prompt
            if row.status == "rejected":
                continue
            if sub_dim_filter is not None and row.sub_dimension not in sub_dim_filter:
                continue
            stmt = (row.statement or "").strip()
            if stmt:
                statements.append(stmt)
        return statements

    def _render_metric(self, profile) -> str:
        baseline = (profile.profile_json or {}).get("metrics_baseline") or {}
        if not isinstance(baseline, dict) or not baseline:
            return ""
        lines = ["[量化锚点]"]
        for metric_name, stats in list(baseline.items())[:8]:
            if not isinstance(stats, dict):
                continue
            mean = stats.get("mean")
            std = stats.get("std")
            if mean is None:
                continue
            if std is None:
                lines.append(f"- {metric_name}:目标 {float(mean):.2f}")
            else:
                lines.append(f"- {metric_name}:目标 {float(mean):.2f} ± {float(std):.2f}")
        if len(lines) == 1:
            return ""
        return "\n".join(lines)

    def _apply_budget(self, positive: str, forbidden: str, metric: str) -> tuple[str, str, str]:
        budget = _load_budget()
        total = int(budget.get("system_prompt_max_tokens", 800))
        p_ratio = float(budget.get("positive_block_ratio", 0.6))
        f_ratio = float(budget.get("forbidden_block_ratio", 0.3))
        m_ratio = float(budget.get("metric_anchor_block_ratio", 0.1))
        return (
            _truncate_lines(positive, int(total * p_ratio)),
            _truncate_lines(forbidden, int(total * f_ratio)),
            _truncate_lines(metric, int(total * m_ratio)),
        )

    def _summarize_forbidden(self, forbidden: str, *, max_chars: int) -> str:
        if not forbidden:
            return ""
        return _truncate_lines(forbidden, max_chars)


def _ts_to_int(ts: str | None) -> int:
    """把 ISO 时间串转为可比 int(只用于排序,失败回 0)。"""
    if not ts:
        return 0
    cleaned = "".join(ch for ch in ts if ch.isdigit())
    if not cleaned:
        return 0
    try:
        return int(cleaned[:14])
    except ValueError:
        return 0
