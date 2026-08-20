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
- **A** — positive + forbidden + metric_anchor 三块全文注入
- **B** — 按 ``config/style_reference/injection_budget.yaml`` 预算截断
- **C** — positive 全文 + forbidden 摘要(≤200 字) + 不注入 metric_anchor
- **MIXED** — 场景生成默认；binding.config_json 自定义 ``include_positive`` /
  ``include_forbidden`` / ``include_metric`` 三个布尔开关
"""

from __future__ import annotations

import hashlib
import logging
import math
from types import SimpleNamespace
from typing import Any

from sqlalchemy.orm import Session

from novel_system.services.context_budget import estimate_tokens
from novel_system.services.style_reference.config_loader import (
    load_text_template,
    load_yaml_config,
)
from novel_system.services.style_reference.metrics_recorder import MetricsRecorder
from novel_system.services.style_reference.repository import StyleReferenceRepository
from novel_system.services.style_reference.runtime_contract import (
    StyleGenerationContext,
    validate_style_runtime_contract,
)
from novel_system.services.style_reference.schemas import (
    InjectionStrategy,
    SystemPromptFragments,
    TaskType,
)

logger = logging.getLogger(__name__)

# §5.1 TaskType → 默认注入策略表(设计手册规划的 strategy.py 落点)。绑定创建时
# 未显式选 strategy 的推荐默认;前端「注入应用」任务卡片以此为数据源。
DEFAULT_STRATEGY_BY_TASK: dict[TaskType, InjectionStrategy] = {
    TaskType.PROJECT_INIT: InjectionStrategy.A,
    TaskType.SCENE_GENERATION: InjectionStrategy.MIXED,
    TaskType.FINE_TUNING: InjectionStrategy.B,
    TaskType.LONG_FORM_CONTINUATION: InjectionStrategy.MIXED,
    TaskType.KEY_CHAPTER: InjectionStrategy.C,
}


def default_injection_strategy(
    task_type: TaskType | str,
) -> InjectionStrategy:
    """返回任务的唯一推荐默认，供 API、物化服务与评测共同消费。"""
    task = (
        task_type
        if isinstance(task_type, TaskType)
        else TaskType(str(task_type))
    )
    return DEFAULT_STRATEGY_BY_TASK.get(task, InjectionStrategy.A)


def injection_task_defaults() -> list[dict[str, Any]]:
    """TaskType → 默认策略 + 运行时刷新周期(只读,前端任务卡片数据源)。

    refresh_every_chars 的唯一运行时真源是 llm_node_registry 的
    long_form_continuation 节点(scene_generation 按它分段重注入防漂移);
    其余任务是一次性注入(0)。
    """
    from novel_system.services.llm_node_registry import get_llm_node_spec

    spec = get_llm_node_spec("long_form_continuation")
    refresh = int(getattr(spec, "refresh_every_chars", 0) or 0) if spec else 0
    return [
        {
            "task_type": task.value,
            "default_strategy": strategy.value,
            "refresh_every_chars": (
                refresh if task is TaskType.LONG_FORM_CONTINUATION else 0
            ),
        }
        for task, strategy in DEFAULT_STRATEGY_BY_TASK.items()
    ]


# 预算单位是**字符数**（配置注释：汉字 ~1 字 = 1 token 的粗估），
# 截断走 _truncate_lines(text, max_chars)——键名沿用 *_max_tokens 仅为配置兼容（审计 P-20）。
_DEFAULT_BUDGET = {
    "system_prompt_max_tokens": 800,
    "positive_block_ratio": 0.5,
    "forbidden_block_ratio": 0.2,
    "metric_anchor_block_ratio": 0.3,
}

# 配置文件缺失时的红线兜底:抄袭事前预防段不允许因部署缺配置而消失(§11 风险 11)
_FALLBACK_ANTI_PLAGIARISM = """## 严格禁止
- 复用或微改任何参考样本中的完整句子
- 直接搬运超过 5 个连续字符的独特表达(常用词、人名、地名除外)
- 参考样本中的意象可重复使用,但承载这些意象的句子必须完全重写
- 若你不确定某个表达是否来自参考样本,默认认为是,改写它
{banned_terms_list}"""

_METRIC_GROUPS: tuple[tuple[str, tuple[str, ...], int, tuple[str, ...]], ...] = (
    (
        "paragraph_shape",
        (
            "paragraph_mean_chars",
            "paragraph_length_std_chars",
            "paragraphs_per_1k",
            "single_sentence_paragraph_ratio",
            "quote_led_paragraph_ratio",
        ),
        3,
        ("paragraph_mean_chars", "paragraphs_per_1k"),
    ),
    (
        "sentence_shape",
        (
            "avg_sentence_length",
            "sentence_length_std",
            "short_sentence_ratio",
            "long_sentence_ratio",
        ),
        2,
        ("avg_sentence_length",),
    ),
    (
        "punctuation_rhythm",
        (
            "punctuation_density_per_1k",
            "dash_em_density_per_1k",
            "ellipsis_density_per_1k",
            "semicolon_density_per_1k",
            "question_density_per_1k",
        ),
        3,
        ("punctuation_density_per_1k", "semicolon_density_per_1k"),
    ),
    (
        "register",
        ("classical_word_ratio", "colloquial_marker_ratio"),
        2,
        ("classical_word_ratio", "colloquial_marker_ratio"),
    ),
    (
        "figurative_proxy",
        ("metaphor_density_per_1k", "personification_density_per_1k"),
        1,
        (),
    ),
)
_METRIC_LABELS = {
    "paragraph_mean_chars": "段均字数",
    "paragraph_length_std_chars": "段长起伏",
    "paragraphs_per_1k": "千字换段数",
    "single_sentence_paragraph_ratio": "单句段占比",
    "quote_led_paragraph_ratio": "对话起段占比",
    "avg_sentence_length": "句均字数",
    "sentence_length_std": "句长起伏",
    "short_sentence_ratio": "短句占比",
    "long_sentence_ratio": "长句占比",
    "punctuation_density_per_1k": "标点/千字",
    "dash_em_density_per_1k": "破折号/千字",
    "ellipsis_density_per_1k": "省略号/千字",
    "semicolon_density_per_1k": "分号/千字",
    "question_density_per_1k": "问号/千字",
    "classical_word_ratio": "文言虚词比例",
    "colloquial_marker_ratio": "口语语气词比例",
    "metaphor_density_per_1k": "比喻标记密度",
    "personification_density_per_1k": "拟人标记密度",
    "sensory_visual_per_1k": "视觉词密度",
    "sensory_auditory_per_1k": "听觉词密度",
    "sensory_olfactory_per_1k": "嗅觉词密度",
    "sensory_tactile_per_1k": "触觉词密度",
    "sensory_gustatory_per_1k": "味觉词密度",
}
_METRIC_REQUIRED_ORDER: tuple[str, ...] = (
    # 先放最稳定、最能跨题材区分文体的结构信号；预算截尾时仍保证这些在前。
    "paragraph_mean_chars",
    "paragraphs_per_1k",
    "semicolon_density_per_1k",
    "avg_sentence_length",
    "punctuation_density_per_1k",
    "classical_word_ratio",
    "colloquial_marker_ratio",
)
_RATIO_METRICS = frozenset(
    {
        "short_sentence_ratio",
        "long_sentence_ratio",
        "classical_word_ratio",
        "colloquial_marker_ratio",
        "single_sentence_paragraph_ratio",
        "quote_led_paragraph_ratio",
    }
)

# 已有/旧版 Profile 可能同时携带冻结数字和由 LLM 概括的表层频率判断。
# 对可直接量化的域只保留数字真源；叙事视角、信息释放、动作组织等不能由
# 这些指标覆盖的机制仍照常注入。按域检查可避免用一个笼统关键词过滤掉
# 与指标无关的有效叙事建议。
_METRIC_GUIDANCE_DOMAINS: tuple[
    tuple[frozenset[str], tuple[str, ...]], ...
] = (
    (
        frozenset(
            {
                "avg_sentence_length",
                "sentence_length_std",
                "short_sentence_ratio",
                "long_sentence_ratio",
            }
        ),
        ("短句", "长句", "句长", "断句", "句式长度", "单句"),
    ),
    (
        frozenset(
            {
                "paragraph_mean_chars",
                "paragraph_length_std_chars",
                "paragraphs_per_1k",
                "single_sentence_paragraph_ratio",
                "quote_led_paragraph_ratio",
            }
        ),
        ("段落", "段均", "段长", "段数", "段密度", "换段", "分段", "孤立成句"),
    ),
    (
        frozenset(
            {
                "punctuation_density_per_1k",
                "dash_em_density_per_1k",
                "ellipsis_density_per_1k",
                "semicolon_density_per_1k",
                "question_density_per_1k",
            }
        ),
        (
            "句号",
            "分号",
            "逗号",
            "问号",
            "问句",
            "发问",
            "设问",
            "反问",
            "省略号",
            "破折号",
            "标点",
        ),
    ),
    (
        frozenset({"classical_word_ratio", "colloquial_marker_ratio"}),
        ("口语", "语气词", "文言", "书面语", "四字格"),
    ),
    (
        frozenset(
            {"metaphor_density_per_1k", "personification_density_per_1k"}
        ),
        ("明喻", "比喻", "拟人", "仿佛", "似的", "好像", "如同", "犹如"),
    ),
)


def _is_metric_domain_guidance(text: str, baseline: dict[str, Any]) -> bool:
    normalized = str(text or "").strip()
    if not normalized:
        return False
    return any(
        any(metric in baseline for metric in metrics)
        and any(marker in normalized for marker in markers)
        for metrics, markers in _METRIC_GUIDANCE_DOMAINS
    )


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
    kept = text[:cut].rstrip().splitlines()
    # 预算刚好截在小节标题后时，不把“叙事模式:”之类的空标题交给模型。
    # 空标题会暗示该维度存在、实际却没有任何指令，也掩盖了预算分配失衡。
    while len(kept) > 1 and kept[-1].strip().endswith((":", "：")):
        kept.pop()
    return "\n".join(kept)


def _cap_fragments(
    frag: "SystemPromptFragments", budget: int
) -> "SystemPromptFragments":
    """PR-16 叠加专属:按配置 ratio 硬截 3 block(不管 strategy)。

    anti_plagiarism_block 是红线段,**永不截断**,原样保留。
    few_shot_block 与 rag_block(立项 C)在叠加路径**均不传**:二者都引用某一
    profile/book 的原文样例,多层(可能跨书/跨 profile)混叠只会稀释风格信号——
    RAG 检索是 per-profile 的,叠加时与 few_shot 同样丢弃,构造默认空即为丢弃。
    (单层路径才走 strategy 全语义,RAG 在那里正常注入。)
    """
    configured = _load_budget()
    p_ratio = float(configured.get("positive_block_ratio", 0.5))
    f_ratio = float(configured.get("forbidden_block_ratio", 0.2))
    m_ratio = float(configured.get("metric_anchor_block_ratio", 0.3))
    return SystemPromptFragments(
        positive_block=_truncate_lines(frag.positive_block, int(budget * p_ratio)),
        forbidden_block=_truncate_lines(frag.forbidden_block, int(budget * f_ratio)),
        metric_anchor_block=_truncate_lines(
            frag.metric_anchor_block, int(budget * m_ratio)
        ),
        anti_plagiarism_block=frag.anti_plagiarism_block,
        strategy=frag.strategy,
    )


def fit_fragments_to_input_budget(
    fragments: SystemPromptFragments,
    *,
    base_system_prompt: str,
    user_prompt: str,
    target_input_tokens: int,
) -> tuple[SystemPromptFragments, dict[str, Any]]:
    """在最终正文已知后，把风格注入压进真实输入预算。

    ``PromptBuilder`` 只能预算 bundle sections；style pass 随后还会追加完整
    中性稿与 Style Reference system prefix。此前最终执行器虽能 fail-closed，
    却无法对后追加的风格块做确定性压缩，导致只超几十 token 也整场失败。

    压缩严格走完整行边界：先从最低优先级的量化锚点尾部缩减，再在必要时
    权衡正向机制与禁忌条目。few-shot / RAG 要么完整保留（含不可信数据边界），
    要么整块移除；反抄袭红线只要仍有任一风格负载就原样保留，绝不截断。
    返回的 audit 只含规模与策略，不含提示词正文。
    """
    target = max(0, int(target_input_tokens or 0))
    full_prefix = fragments.to_system_prompt_prefix()
    base_tokens = estimate_tokens(base_system_prompt) + estimate_tokens(user_prompt)
    full_tokens = estimate_tokens(full_prefix + base_system_prompt) + estimate_tokens(
        user_prompt
    )

    def _audit(final: SystemPromptFragments, *, policy: str) -> dict[str, Any]:
        final_prefix = final.to_system_prompt_prefix()
        final_tokens = estimate_tokens(
            final_prefix + base_system_prompt
        ) + estimate_tokens(user_prompt)
        block_names = (
            "positive_block",
            "forbidden_block",
            "metric_anchor_block",
            "few_shot_block",
            "rag_block",
        )
        trimmed = [
            name
            for name in block_names
            if len(getattr(final, name)) < len(getattr(fragments, name))
        ]
        omitted = [
            name
            for name in block_names
            if getattr(fragments, name).strip() and not getattr(final, name).strip()
        ]
        return {
            "compacted": final_prefix != full_prefix,
            "policy": policy,
            "target_input_tokens": target,
            "base_estimated_input_tokens": base_tokens,
            "full_estimated_input_tokens": full_tokens,
            "final_estimated_input_tokens": final_tokens,
            "prefix_chars_before": len(full_prefix),
            "prefix_chars_after": len(final_prefix),
            "trimmed_blocks": trimmed,
            "omitted_blocks": omitted,
            "style_payload_omitted": bool(full_prefix and not final_prefix),
            "anti_plagiarism_preserved": bool(
                not final_prefix
                or not fragments.anti_plagiarism_block.strip()
                or final.anti_plagiarism_block
                == fragments.anti_plagiarism_block
            ),
        }

    if not full_prefix or target <= 0 or full_tokens <= target:
        return fragments, _audit(fragments, policy="no_compaction_needed")

    def _fits(candidate: SystemPromptFragments) -> bool:
        prefix = candidate.to_system_prompt_prefix()
        return (
            estimate_tokens(prefix + base_system_prompt) + estimate_tokens(user_prompt)
            <= target
        )

    def _line_variants(block: str) -> list[str]:
        """从全文到空串，仅产生完整行前缀；孤立标题不作为有效块。"""
        lines = block.splitlines()
        variants = [block]
        for count in range(len(lines) - 1, 0, -1):
            candidate = "\n".join(lines[:count]).strip()
            if count == 1 and lines[0].lstrip().startswith("["):
                candidate = ""
            if candidate not in variants:
                variants.append(candidate)
        if "" not in variants:
            variants.append("")
        return variants

    # 大多数临界超限只需少带一两个量化指标。正向特征、禁忌与原文样例
    # 在这一阶段完全不动，最大限度保住风格辨识信号。
    for metric in _line_variants(fragments.metric_anchor_block):
        candidate = fragments.model_copy(
            update={"metric_anchor_block": metric}
        )
        if _fits(candidate):
            return candidate, _audit(
                candidate,
                policy="trim_metric_tail_preserve_style_and_safety_v1",
            )

    def _best_abstract_candidate(
        *, keep_reference_examples: bool
    ) -> SystemPromptFragments | None:
        positive_variants = _line_variants(fragments.positive_block)
        forbidden_variants = _line_variants(fragments.forbidden_block)
        best: tuple[tuple[int, int, int], SystemPromptFragments] | None = None
        for positive in positive_variants:
            for forbidden in forbidden_variants:
                candidate = fragments.model_copy(
                    update={
                        "positive_block": positive,
                        "forbidden_block": forbidden,
                        "metric_anchor_block": "",
                        "few_shot_block": (
                            fragments.few_shot_block
                            if keep_reference_examples
                            else ""
                        ),
                        "rag_block": (
                            fragments.rag_block if keep_reference_examples else ""
                        ),
                    }
                )
                if not _fits(candidate):
                    continue
                # 正向机制优先，禁忌次之；同分时保留更多完整字符。
                score = (
                    3 * len(positive.splitlines())
                    + 2 * len(forbidden.splitlines()),
                    int(bool(positive)) + int(bool(forbidden)),
                    len(candidate.to_system_prompt_prefix()),
                )
                if best is None or score > best[0]:
                    best = (score, candidate)
        return best[1] if best is not None else None

    for keep_examples in (True, False):
        candidate = _best_abstract_candidate(
            keep_reference_examples=keep_examples
        )
        if candidate is not None and candidate.to_system_prompt_prefix():
            return candidate, _audit(
                candidate,
                policy=(
                    "trim_abstract_lines_preserve_reference_blocks_v1"
                    if keep_examples
                    else "trim_abstract_lines_drop_reference_blocks_v1"
                ),
            )

    # 连完整的一条风格机制 + 原样红线都容不下时，宁可显式审计为风格降级，
    # 也不截断安全红线或发送半条指令。若基础 prompt 自身仍超限，最终执行器
    # 会继续以 CONTINUITY_BUDGET_EXCEEDED fail-closed。
    empty = SystemPromptFragments(strategy=fragments.strategy)
    return empty, _audit(empty, policy="omit_style_payload_preserve_base_prompt_v1")


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


def _merge_fragments(
    layers_frags: list["SystemPromptFragments"],
) -> "SystemPromptFragments":
    """PR-19 — 多层合并(由泛到具体):positive 顺序拼 / forbidden 全层去重 /
    metric 最具体优先(反向取首个非空)/ strategy 取最具体层。

    few_shot_block 与 rag_block(立项 C)不在此合并:它们已在上游 `_cap_fragments`
    阶段丢弃(per-profile 原文样例多层混叠稀释风格信号,详见该函数注释),故合并产物
    不含二者。RAG 仅在单层路径注入。

    positive 拼接时 `[正向风格特征]` 标题只保留首层——每层各带一遍标题会让
    system prompt 出现多个同名块头,干扰 LLM 对块结构的解析(2026-07 观感修正)。"""
    positive_parts: list[str] = []
    for f in layers_frags:
        block = f.positive_block.strip()
        if not block:
            continue
        if positive_parts and block.startswith("[正向风格特征]"):
            block = block[len("[正向风格特征]") :].lstrip("\n")
            if not block:
                continue
        positive_parts.append(block)
    positive = "\n\n".join(positive_parts)
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
    for cid in onstage_ids or []:
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
        self._last_runtime_contract_hash: str | None = None
        self._last_runtime_profile_ids: list[str] = []
        self._last_runtime_binding_ids: list[str] = []
        self._last_context_audit: dict[str, Any] | None = None
        self.last_runtime_audit: dict[str, Any] | None = None
        # §9 Defect B: drift-corrective few-shot context — set by caller before
        # fragments_for() to override the default ptype priority with dimension-targeted
        # exemplars ("show, don't tell" drift correction).
        self.drift_ptype_priority: list[str] | None = None
        # 立项 C — Strategy C(RAG)的检索 query 来源:续写最新上下文。
        # 由调用方(scene_generation._inject_style_reference)在 fragments_for() 前设置,
        # 续写循环按 refresh_every_chars 周期性刷新此值 → RAG 召回随上下文变化(§12 防漂移)。
        self.context_text: str | None = None

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
            project_id,
            task_type,
            character_ids=character_ids,
            scene_id=scene_id,
        )
        self._record_invocation(project_id, task_type, fragments)
        return fragments

    def fragments_for_contract(
        self,
        contract: dict[str, Any],
        *,
        project_id: str | None,
        context: StyleGenerationContext | None = None,
        drift_ptype_priority: list[str] | None = None,
    ) -> SystemPromptFragments:
        """Render the exact frozen bundle lineage instead of re-resolving live bindings."""
        frozen = validate_style_runtime_contract(contract)
        task_type = str(frozen["task_type"])
        layers = list(frozen["layers"])
        rendered = [
            self._render_contract_layer(
                layer,
                context_text=context.query_text if context is not None else None,
                drift_ptype_priority=drift_ptype_priority,
            )
            for layer in layers
        ]
        if len(rendered) == 1:
            fragments = rendered[0]
        else:
            total = self._budget_total()
            weights = list(range(1, len(rendered) + 1))
            weight_sum = sum(weights)
            fragments = _merge_fragments(
                [
                    _cap_fragments(
                        fragment,
                        total * weights[index] // weight_sum,
                    )
                    for index, fragment in enumerate(rendered)
                ]
            )

        self._last_profile_id = str(layers[-1]["profile"]["profile_id"])
        self._last_binding_id = str(layers[-1]["binding"]["binding_id"])
        self._last_base_binding_id = (
            str(layers[0]["binding"]["binding_id"]) if len(layers) > 1 else None
        )
        self._last_layer_count = len(layers)
        self._last_runtime_contract_hash = str(frozen["contract_hash"])
        self._last_runtime_profile_ids = list(frozen["profile_ids"])
        self._last_runtime_binding_ids = list(frozen["binding_ids"])
        self._last_context_audit = context.audit_dict() if context is not None else None
        self._record_invocation(project_id, task_type, fragments)
        return fragments

    def _render_contract_layer(
        self,
        layer: dict[str, Any],
        *,
        context_text: str | None,
        drift_ptype_priority: list[str] | None,
    ) -> SystemPromptFragments:
        profile = SimpleNamespace(**dict(layer["profile"]))
        binding = dict(layer["binding"])
        try:
            strategy = InjectionStrategy(str(binding["strategy"]))
        except ValueError:
            strategy = InjectionStrategy.A
        return self._render(
            profile,
            strategy,
            dict(binding.get("config_json") or {}),
            drift_ptype_priority=drift_ptype_priority,
            context_text=context_text,
            frozen_layer=layer,
        )

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
            project_id,
            task_type,
            character_ids=character_ids,
            scene_id=scene_id,
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
        self._last_profile_id = layers[-1].profile_id  # 最具体层
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
            profile,
            strategy,
            binding.config_json or {},
            drift_ptype_priority=self.drift_ptype_priority,
            context_text=self.context_text,
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
        runtime_profile_ids = list(self._last_runtime_profile_ids)
        if not runtime_profile_ids and self._last_profile_id:
            runtime_profile_ids = [self._last_profile_id]
        runtime_binding_ids = list(self._last_runtime_binding_ids)
        if not runtime_binding_ids and self._last_binding_id:
            runtime_binding_ids = [self._last_binding_id]
        runtime_audit = {
            "outcome": outcome,
            "task_type": task_type,
            "strategy": fragments.strategy.value,
            "contract_hash": self._last_runtime_contract_hash,
            "profile_ids": runtime_profile_ids,
            "binding_ids": runtime_binding_ids,
            "layer_count": self._last_layer_count or (1 if prefix else 0),
            "context": self._last_context_audit,
            "prefix_chars": len(prefix),
            "prefix_sha256": hashlib.sha256(prefix.encode("utf-8")).hexdigest(),
        }
        self.last_runtime_audit = runtime_audit
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
                "runtime_contract_hash": self._last_runtime_contract_hash,
                "runtime_profile_ids": runtime_profile_ids,
                "context": self._last_context_audit,
            },
        )
        # 用完即清,避免下一次 invocation 错误复用
        self._last_profile_id = None
        self._last_binding_id = None
        self._last_base_binding_id = None
        self._last_layer_count = 0
        self._last_runtime_contract_hash = None
        self._last_runtime_profile_ids = []
        self._last_runtime_binding_ids = []
        self._last_context_audit = None

    # ------------------------------------------------------------- binding 选取
    def _active_bindings(self, task_type: str) -> list:
        """binding.status=active **且其 profile.status=active** 的候选集。

        2026-07 勘误:此前只查 binding 状态——draft/archived profile 的 binding
        仍会被 resolve 选中:注入侧渲染为空(no-op),但 qc_engine 的风格校验门
        照样以该 profile 做回测裁决,出现「从未注入却被风格门拦下」的矛盾;
        多层叠加时空层还白占预算权重。在选取单点统一过滤,注入 / qc gate 一致。
        """
        profile_status: dict[str, str | None] = {}

        def _profile_active(profile_id: str) -> bool:
            if profile_id not in profile_status:
                profile = self.repo.get_profile(profile_id)
                profile_status[profile_id] = getattr(profile, "status", None)
            return profile_status[profile_id] == "active"

        return [
            b
            for b in self.repo.list_bindings(task_type=task_type)
            if b.status == "active" and _profile_active(b.profile_id)
        ]

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
        bindings = self._active_bindings(task_type)
        if not bindings:
            return None

        def _rank(b) -> int:
            return _binding_rank(
                b,
                project_id=project_id,
                character_ids=character_ids,
                scene_id=scene_id,
            )

        candidates = [b for b in bindings if _rank(b) < 99]
        if not candidates:
            return None
        candidates.sort(
            key=lambda b: (
                _rank(b),
                _char_order(b, character_ids),
                -1 * _ts_to_int(b.created_at),
            )
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
        bindings = self._active_bindings(task_type)
        if not bindings:
            return []

        def _rank(b) -> int:
            return _binding_rank(
                b,
                project_id=project_id,
                character_ids=character_ids,
                scene_id=scene_id,
            )

        def _pick(allowed: set[int]):
            cands = [b for b in bindings if _rank(b) in allowed]
            if not cands:
                return None
            cands.sort(
                key=lambda b: (
                    _rank(b),
                    _char_order(b, character_ids),
                    -1 * _ts_to_int(b.created_at),
                )
            )
            return cands[0]

        def _pick_all_characters():
            """PR-20 — 全部 rank1 命中,pov 优先 + created_at 决平,按 character_id 去重(每角色一层)。"""
            cands = [b for b in bindings if _rank(b) == 1]
            cands.sort(
                key=lambda b: (
                    _char_order(b, character_ids),
                    -1 * _ts_to_int(b.created_at),
                )
            )
            seen: set[str] = set()
            out = []
            for b in cands:
                if b.scope_ref_id not in seen:
                    seen.add(b.scope_ref_id)
                    out.append(b)
            return out

        base = _pick({2, 3})  # project > global(基底,单)
        characters = _pick_all_characters()  # onstage 全配角,pov 优先(PR-20)
        scene_b = _pick({0})  # scene(最具体,单)
        layers = []
        if base is not None:
            layers.append(base)
        layers.extend(characters)
        if scene_b is not None:
            layers.append(scene_b)
        return layers  # 由泛到具体

    def describe_binding_layers(
        self,
        project_id: str | None,
        task_type: str,
        *,
        character_ids: list[str] | None = None,
        scene_id: str | None = None,
    ) -> dict[str, Any]:
        """只读叠层预览(注入应用页「叠加注入层」数据源)。

        复算 `_resolve_fragments` 的权重/预算分配并附各层截断后 block 规模与
        合并结果概要;不写 metric 事件、不记 last id(纯读,可随 UI 反复调用)。
        """
        total = self._budget_total()
        layers = self.resolve_binding_layers(
            project_id,
            task_type,
            character_ids=character_ids,
            scene_id=scene_id,
        )
        if not layers:
            return {"layers": [], "merged": None, "budget_total": total}
        n = len(layers)
        weights = list(range(1, n + 1))
        wsum = sum(weights)
        rendered = [self._render_binding(b) for b in layers]
        if n == 1:
            # 单层与 _resolve_fragments 一致:strategy 全语义,不 cap
            budgets = [total]
            capped = rendered
            merged = rendered[0]
        else:
            budgets = [total * weights[i] // wsum for i in range(n)]
            capped = [_cap_fragments(rendered[i], budgets[i]) for i in range(n)]
            merged = _merge_fragments(capped)
        rank_by_scope = {"scene": 0, "character": 1, "project": 2, "global": 3}
        out_layers: list[dict[str, Any]] = []
        for i, binding in enumerate(layers):
            frag = capped[i]
            block_chars = {
                "positive_block": len(frag.positive_block),
                "forbidden_block": len(frag.forbidden_block),
                "metric_anchor_block": len(frag.metric_anchor_block),
            }
            profile = self.repo.get_profile(binding.profile_id)
            out_layers.append(
                {
                    "rank": rank_by_scope.get(binding.scope, 9),
                    "scope": binding.scope,
                    "scope_ref_id": binding.scope_ref_id,
                    "binding_id": binding.binding_id,
                    "profile_id": binding.profile_id,
                    "profile_title": getattr(profile, "title", None),
                    "strategy": binding.strategy,
                    "weight": weights[i],
                    "budget_chars": budgets[i],
                    "block_chars": block_chars,
                    "fragment_count": sum(1 for v in block_chars.values() if v),
                }
            )
        prefix = merged.to_system_prompt_prefix()
        strategy_val = (
            merged.strategy.value
            if hasattr(merged.strategy, "value")
            else str(merged.strategy)
        )
        return {
            "layers": out_layers,
            "budget_total": total,
            "merged": {
                "layer_count": n,
                "strategy": strategy_val,
                "prefix_chars": len(prefix),
            },
        }

    def _render(
        self,
        profile,
        strategy: InjectionStrategy,
        config: dict[str, Any],
        *,
        drift_ptype_priority: list[str] | None = None,
        context_text: str | None = None,
        frozen_layer: dict[str, Any] | None = None,
    ) -> SystemPromptFragments:
        sub_dims_raw = config.get("sub_dimensions")
        sub_dims = [str(s) for s in sub_dims_raw] if sub_dims_raw else None
        positive = self._render_positive(profile)
        forbidden = self._render_forbidden(
            profile,
            sub_dims=sub_dims,
            frozen_findings=(
                list(frozen_layer.get("forbidden_findings") or [])
                if frozen_layer is not None
                else None
            ),
        )
        metric = self._render_metric(profile, context_text=context_text)
        few_shot = ""
        rag_block = ""

        if strategy == InjectionStrategy.B:
            positive, forbidden, metric = self._apply_budget(
                positive, forbidden, metric
            )
            few_shot = self._render_few_shot(
                profile,
                drift_ptype_priority=drift_ptype_priority,
                frozen_layer=frozen_layer,
            )
        elif strategy == InjectionStrategy.C:
            # 立项 C — 真召回:positive 全文 + forbidden 摘要 + RAG 检索片段(metric 不注)。
            # 空召回(无索引/无 query)时 rag_block="",C 优雅退化到 positive + forbidden 摘要。
            forbidden = self._summarize_forbidden(forbidden, max_chars=200)
            metric = ""
            rag_block = self._render_rag(
                profile,
                context_text=context_text,
                frozen_layer=frozen_layer,
            )
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
                "positive": (
                    int(total * p_ratio * scale)
                    if config.get("include_positive", True)
                    else 0
                ),
                "forbidden": (
                    int(total * f_ratio * scale)
                    if config.get("include_forbidden", True)
                    else 0
                ),
                "metric": (
                    int(total * m_ratio * scale)
                    if config.get("include_metric", True)
                    else 0
                ),
            }
            cap_sum = sum(caps.values())
            if cap_sum > total > 0:
                shrink = total / cap_sum
                caps = {k: int(v * shrink) for k, v in caps.items()}
            positive = (
                _truncate_lines(positive, caps["positive"]) if caps["positive"] else ""
            )
            forbidden = (
                _truncate_lines(forbidden, caps["forbidden"])
                if caps["forbidden"]
                else ""
            )
            metric = _truncate_lines(metric, caps["metric"]) if caps["metric"] else ""
            # mixed = A + B:few-shot 样例块也随混合策略注入(自带 few_shot_block_max_chars
            # 预算截断,不参与上面三块的比例分配)
            few_shot = self._render_few_shot(
                profile,
                drift_ptype_priority=drift_ptype_priority,
                frozen_layer=frozen_layer,
            )

        # Wave 7 §5.9 — few-shot 例句与 RAG 召回片段是参考书**原文派生物**,进 LLM 前
        # 必须先中和指令模式再用「非指令数据」边界封装(主防线),堵不可信文本提示词注入。
        # positive/forbidden/metric 是抽象特征(非原文),不封装;anti_plagiarism 是我方红线。
        from novel_system.services.style_reference.untrusted_data import (
            secure_reference_block,
        )

        if few_shot.strip():
            few_shot = secure_reference_block(few_shot, kind="few_shot")
        if rag_block.strip():
            rag_block = secure_reference_block(rag_block, kind="rag")

        # §A.5 / §11 风险 11 — 抄袭事前预防红线段:任一风格 block 非空时必随注入,
        # 不参与任何预算截断;few-shot 引用原文片段,更必须带红线
        anti_plagiarism = ""
        if (
            positive.strip()
            or forbidden.strip()
            or metric.strip()
            or few_shot.strip()
            or rag_block.strip()
        ):
            anti_plagiarism = self._render_anti_plagiarism(
                profile,
                frozen_terms=(
                    list(frozen_layer.get("banned_terms") or [])
                    if frozen_layer is not None
                    else None
                ),
            )

        return SystemPromptFragments(
            positive_block=positive,
            forbidden_block=forbidden,
            metric_anchor_block=metric,
            few_shot_block=few_shot,
            rag_block=rag_block,
            anti_plagiarism_block=anti_plagiarism,
            strategy=strategy,
        )

    def _render_rag(
        self,
        profile,
        *,
        context_text: str | None,
        frozen_layer: dict[str, Any] | None = None,
    ) -> str:
        """Strategy C — 按 context_text 从三粒度索引检索参考风格片段,渲染 rag_block。

        query 来源:续写最新上下文(context_text);为空时回退用 profile 叙事概述
        (narrative_summary),保证非续写场景(项目初始化)也能召回。无索引/空召回 →
        空串(C 优雅退化)。全程无 LLM(§11 风险 6:inject < 50ms,库内拼装)。

        反抄袭/隐私(附录 B):RAG 注入的是参考书**原文片段**(段/句/景),最终随用户
        生成 prompt 送往云端 LLM。与 Strategy B(few-shot)共用 ``cloud_llm_allowed``
        守卫：仅精确合法的云策略和严格发送权声明可检索/注入；其余情况直接跳过
        RAG(positive/forbidden 抽象特征仍由其它 block 注入,不受影响)。
        """
        from novel_system.services.style_reference.rag import (
            RagRetriever,
            load_rag_config,
            render_rag_block,
        )
        from novel_system.services.style_reference.policy import cloud_llm_allowed

        frozen_book = (frozen_layer.get("book") or {}) if frozen_layer else None
        if frozen_book is not None and not bool(
            frozen_book.get("cloud_llm_allowed_at_freeze")
        ):
            return ""
        book = self.repo.get_book(getattr(profile, "book_id", None))
        if frozen_layer is not None and (book is None or not cloud_llm_allowed(book)):
            return ""
        if frozen_book is not None and str(
            getattr(book, "text_checksum", "") or ""
        ) != str(frozen_book.get("text_checksum") or ""):
            logger.warning(
                "frozen style book checksum changed; skipping RAG for %s",
                getattr(profile, "profile_id", None),
            )
            return ""
        if frozen_layer is None and book is not None and not cloud_llm_allowed(book):
            return ""

        cfg = load_rag_config()
        query = (context_text or "").strip()
        if not query:
            query = (
                (profile.profile_json or {}).get("narrative_summary") or ""
            ).strip()
        if not query:
            return ""
        max_q = int(cfg.get("rag_context_query_max_chars", 2000))
        query = query[-max_q:]
        try:
            snippets = RagRetriever(self.session).retrieve(profile.profile_id, query)
        except Exception:  # noqa: BLE001 — 召回失败不阻断生成
            logger.warning(
                "rag retrieve failed for profile %s", profile.profile_id, exc_info=True
            )
            return ""
        return render_rag_block(snippets, config=cfg)

    def _render_few_shot(
        self,
        profile,
        *,
        drift_ptype_priority: list[str] | None = None,
        frozen_layer: dict[str, Any] | None = None,
    ) -> str:
        """Strategy B few-shot:优先注入 quote 所在的代表性完整段落。

        证据 quote 往往只有数个到数十个字，无法展示换段、句群和标点节奏；因此
        在运行契约冻结 paragraph 哈希且权限允许时，按 Profile 的目标段均字数选择
        最接近的完整父段落。无父段落的旧数据仍退化为 quote。每种段型最多一条，
        样例引用原文，因此调用方(_render)保证红线段必随注入。

        §9 Defect B — drift_ptype_priority: when drift correction is active, the caller
        passes a re-ordered priority list (from style_drift_detector.drift_corrective_ptype_priority)
        so the few-shot exemplars "show" the correct baseline for drifted dimensions
        rather than just "telling" the model to adjust.

        反抄袭/隐私(附录 B):few-shot 注入的是参考书**原文引文**,最终随用户生成 prompt
        送往云端 LLM。``cloud_policy=local_only`` 的书禁止把原文送云端,故此处直接跳过
        few-shot(与 Strategy C RAG 守卫一致;positive/forbidden 抽象特征仍由其它 block 注入)。
        """
        from novel_system.services.style_reference.policy import cloud_llm_allowed

        frozen_book = (frozen_layer.get("book") or {}) if frozen_layer else None
        if frozen_book is not None and not bool(
            frozen_book.get("cloud_llm_allowed_at_freeze")
        ):
            return ""
        book = self.repo.get_book(getattr(profile, "book_id", None))
        if frozen_layer is not None and (book is None or not cloud_llm_allowed(book)):
            return ""
        if frozen_layer is None and book is not None and not cloud_llm_allowed(book):
            return ""
        budget = _load_budget()
        k = int(budget.get("few_shot_k", 3))
        quote_max = int(budget.get("few_shot_quote_max_chars", 120))
        paragraph_min = int(budget.get("few_shot_paragraph_min_chars", 40))
        paragraph_max = int(budget.get("few_shot_paragraph_max_chars", 360))
        scan_per_type = int(budget.get("few_shot_candidate_scan_per_type", 12))
        block_max = int(budget.get("few_shot_block_max_chars", 900))
        if k <= 0:
            return ""
        samples_index: dict[str, Any] = (profile.profile_json or {}).get(
            "scene_samples_index"
        ) or {}
        if not isinstance(samples_index, dict) or not samples_index:
            return ""
        header = (
            "[风格样例 — 漂移修正](代表性完整段落优先；只学习句群、换段与标点节奏；样例长度不是输出长度；严禁照抄)"
            if drift_ptype_priority
            else "[风格样例](代表性完整段落优先；只学习句群、换段与标点节奏；样例长度不是输出长度；严禁照抄或微改)"
        )
        lines = [header]
        frozen_quote_refs: dict[str, dict[str, str]] | None = None
        frozen_paragraph_hashes: dict[str, str] | None = None
        if frozen_layer is not None:
            frozen_quote_refs = {
                str(item.get("quote_id")): {
                    "quote_sha256": str(item.get("quote_sha256") or ""),
                    "paragraph_id": str(item.get("paragraph_id") or ""),
                }
                for item in (frozen_layer.get("sample_quote_refs") or [])
                if isinstance(item, dict)
                and item.get("quote_id")
                and item.get("quote_sha256")
            }
            frozen_paragraph_hashes = {
                str(item.get("paragraph_id")): str(item.get("paragraph_sha256") or "")
                for item in (frozen_layer.get("sample_paragraph_refs") or [])
                if isinstance(item, dict)
                and item.get("paragraph_id")
                and item.get("paragraph_sha256")
            }

        baseline = (profile.profile_json or {}).get("metrics_baseline") or {}
        paragraph_target = _finite_number(
            (baseline.get("paragraph_mean_chars") or {}).get("mean")
            if isinstance(baseline.get("paragraph_mean_chars"), dict)
            else None
        ) or 120.0
        drift_order = {
            str(ptype): index
            for index, ptype in enumerate(drift_ptype_priority or [])
        }
        candidates: list[dict[str, Any]] = []
        seen_sources: set[str] = set()
        for ptype, raw_quote_ids in samples_index.items():
            quote_ids = raw_quote_ids if isinstance(raw_quote_ids, list) else []
            for source_order, raw_quote_id in enumerate(
                quote_ids[: max(1, scan_per_type)]
            ):
                quote_id = str(raw_quote_id or "")
                if not quote_id or (
                    frozen_quote_refs is not None
                    and quote_id not in frozen_quote_refs
                ):
                    continue
                quote = self.repo.get_quote(quote_id)
                quote_text = (
                    (getattr(quote, "quote_text", "") or "").strip()
                    if quote
                    else ""
                )
                if not quote_text:
                    continue
                frozen_quote_ref = (
                    frozen_quote_refs.get(quote_id)
                    if frozen_quote_refs is not None
                    else None
                )
                if frozen_quote_ref is not None and (
                    hashlib.sha256(quote_text.encode("utf-8")).hexdigest()
                    != frozen_quote_ref["quote_sha256"]
                ):
                    logger.warning("frozen style quote changed; skipping %s", quote_id)
                    continue

                text = _truncate(quote_text, quote_max)
                source_kind = "证据短引文"
                source_id = f"quote:{quote_id}"
                paragraph_id = str(getattr(quote, "paragraph_id", "") or "")
                expected_paragraph_id = (
                    frozen_quote_ref.get("paragraph_id", "")
                    if frozen_quote_ref is not None
                    else paragraph_id
                )
                paragraph = (
                    self.repo.get_paragraph(paragraph_id) if paragraph_id else None
                )
                paragraph_text = (
                    (getattr(paragraph, "text", "") or "").strip()
                    if paragraph
                    else ""
                )
                paragraph_chars = sum(
                    1 for char in paragraph_text if not char.isspace()
                )
                frozen_paragraph_ok = frozen_layer is None or bool(
                    paragraph_id
                    and paragraph_id == expected_paragraph_id
                    and frozen_paragraph_hashes is not None
                    and hashlib.sha256(paragraph_text.encode("utf-8")).hexdigest()
                    == frozen_paragraph_hashes.get(paragraph_id)
                )
                if (
                    paragraph_text
                    and quote_text in paragraph_text
                    and paragraph_min <= paragraph_chars <= paragraph_max
                    and frozen_paragraph_ok
                ):
                    text = paragraph_text
                    source_kind = "完整参考段落"
                    source_id = f"paragraph:{paragraph_id}"
                if source_id in seen_sources:
                    continue
                seen_sources.add(source_id)
                sample_chars = sum(1 for char in text if not char.isspace())
                distance = abs(math.log(max(sample_chars, 1) / paragraph_target))
                style_distance = _reference_sample_style_distance(text, baseline)
                candidates.append(
                    {
                        "ptype": str(ptype),
                        "text": text,
                        "source_kind": source_kind,
                        "source_id": source_id,
                        "chars": sample_chars,
                        "style_distance": style_distance,
                        "rank": (
                            drift_order.get(str(ptype), len(drift_order))
                            if drift_order
                            else 0,
                            # 完整父段落比证据短引文更能展示句群与换段；同类
                            # 候选再按整套可观测风格指标选最接近画像基线者，
                            # 避免仅因段长接近而挑中问号/感叹号等修辞离群段。
                            0 if source_kind == "完整参考段落" else 1,
                            style_distance,
                            distance,
                            source_order,
                            quote_id,
                        ),
                    }
                )

        candidates.sort(key=lambda item: item["rank"])
        picked_types: set[str] = set()
        picked = 0
        for candidate in candidates:
            if picked >= k:
                break
            ptype = candidate["ptype"]
            if ptype in picked_types:
                continue
            picked_types.add(ptype)
            lines.append(
                f"- ({ptype}；{candidate['source_kind']}；{candidate['chars']}字)"
                f"「{candidate['text']}」"
            )
            picked += 1
        if not picked:
            return ""
        return _truncate_lines("\n".join(lines), block_max)

    def _render_anti_plagiarism(
        self,
        profile,
        *,
        frozen_terms: list[str] | None = None,
    ) -> str:
        """渲染 §A.5 红线段:固定模板 + banned_terms(scope=generation)填充。

        模板文件缺失时使用内置兜底——红线段不允许因部署缺配置而消失。
        """
        try:
            template = load_text_template("anti_plagiarism_template")
        except FileNotFoundError:
            template = _FALLBACK_ANTI_PLAGIARISM
        terms = (
            [str(term or "").strip() for term in frozen_terms]
            if frozen_terms is not None
            else [
                (t.term or "").strip()
                for t in self.repo.list_banned_terms(
                    profile.profile_id, scope="generation"
                )
            ]
        )
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
        baseline = data.get("metrics_baseline") or {}
        has_baseline = isinstance(baseline, dict) and bool(baseline)
        if (
            has_baseline
            and narrative
            and not narrative.startswith("量化基线（")
            and _is_metric_domain_guidance(narrative, baseline)
        ):
            # 兼容旧画像：早期 narrative_summary 由 LLM 直接生成，可能写出
            # “短句密集/高频设问”等与冻结数字相反的结论。整句混合时无法
            # 安全拆分，宁可省略旧概述，让量化锚点和非量化机制成为真源。
            narrative = ""
        features = [
            f.strip()
            for f in (data.get("style_features") or [])
            if str(f).strip()
            and not (
                has_baseline and _is_metric_domain_guidance(str(f), baseline)
            )
        ]
        patterns = [
            p.strip()
            for p in (data.get("narrative_patterns") or [])
            if str(p).strip()
            and not (
                has_baseline and _is_metric_domain_guidance(str(p), baseline)
            )
        ]
        calibration = [
            str(item).strip()
            for item in (data.get("calibration_guidance") or [])
            if str(item).strip()
            and not (
                has_baseline and _is_metric_domain_guidance(str(item), baseline)
            )
        ]
        if not (narrative or features or patterns or calibration):
            return ""
        lines: list[str] = ["[正向风格特征]"]
        if narrative:
            lines.append(f"概述:{narrative}")
        # MIXED/B 会在较小预算内截断该块。旧顺序是“全部 feature → 全部
        # pattern”，真实画像常在最后留下一个空的“叙事模式:”标题，模型完全
        # 看不到叙事机制。按轮次交织三类可执行信息，让任意完整行前缀都保持
        # 表达、叙事和偏离校准的基本覆盖；Strategy A 仍会拿到全部条目。
        for index in range(max(len(features), len(patterns), len(calibration))):
            if index < len(features):
                lines.append(f"- [表达机制] {features[index]}")
            if index < len(patterns):
                lines.append(f"- [叙事机制] {patterns[index]}")
            if index < len(calibration):
                lines.append(f"- [偏离校准] {calibration[index]}")
        return "\n".join(lines)

    def _render_forbidden(
        self,
        profile,
        *,
        sub_dims: list[str] | None = None,
        frozen_findings: list[dict[str, Any]] | None = None,
    ) -> str:
        """渲染禁忌模式块。

        ``sub_dims`` 为 None 或空 list 时**全部 16 维**;否则按 sub_dim 过滤
        finding(banned_replication_rules 在 profile_json 中无 sub_dim 归属,
        始终保留)。
        """
        rules = [
            r.strip()
            for r in (
                (profile.profile_json or {}).get("banned_replication_rules") or []
            )
            if str(r).strip()
        ]
        finding_statements = self._collect_forbidden_finding_statements(
            profile,
            sub_dims=sub_dims,
            frozen_findings=frozen_findings,
        )
        if not (rules or finding_statements):
            return ""
        lines = ["[禁忌模式]"]
        # 同一禁忌可能在多个 sub_dim 下重复抽出(statement 完全一致),行级去重
        seen: set[str] = set()
        for entry in [*rules, *finding_statements]:
            if entry in seen:
                continue
            seen.add(entry)
            lines.append(f"- {entry}")
        return "\n".join(lines)

    def _collect_forbidden_finding_statements(
        self,
        profile,
        *,
        sub_dims: list[str] | None = None,
        frozen_findings: list[dict[str, Any]] | None = None,
    ) -> list[str]:
        if frozen_findings is not None:
            sub_dim_filter = set(sub_dims) if sub_dims else None
            return [
                str(item.get("statement") or "").strip()
                for item in frozen_findings
                if item.get("status") != "rejected"
                and (
                    sub_dim_filter is None
                    or item.get("sub_dimension") in sub_dim_filter
                )
                and str(item.get("statement") or "").strip()
            ]
        safe_findings = (profile.profile_json or {}).get(
            "generation_safe_forbidden_findings"
        )
        if isinstance(safe_findings, list):
            sub_dim_filter = set(sub_dims) if sub_dims else None
            return [
                str(item.get("statement") or "").strip()
                for item in safe_findings
                if isinstance(item, dict)
                and item.get("status") != "rejected"
                and (
                    sub_dim_filter is None
                    or item.get("sub_dimension") in sub_dim_filter
                )
                and str(item.get("statement") or "").strip()
            ]
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

    def _render_metric(self, profile, *, context_text: str | None = None) -> str:
        baseline = (profile.profile_json or {}).get("metrics_baseline") or {}
        if not isinstance(baseline, dict) or not baseline:
            return ""
        from novel_system.services.style_reference.validation.quantitative import (
            TYPE_RATIO_METRICS,
            compute_generated_metrics,
        )
        from novel_system.services.style_reference.metrics import (
            compute_prose_shape_from_text,
        )

        current_metrics: dict[str, float] = {}
        context_chars: int | None = None
        if context_text and len(context_text.strip()) >= 40:
            try:
                context_chars = sum(
                    1 for char in context_text if not char.isspace()
                )
                current_metrics = compute_generated_metrics(context_text)
                current_metrics.update(
                    compute_prose_shape_from_text(context_text)
                )
            except Exception:  # pragma: no cover - optional local metric degradation
                logger.warning("style metric delta computation degraded", exc_info=True)

        selected = _select_actionable_metrics(
            baseline,
            current_metrics=current_metrics,
            excluded=TYPE_RATIO_METRICS,
        )
        lines = [
            "[量化硬锚点｜与抽象描述冲突时以此为准；先完成句段与标点目标，勿机械凑数]"
        ]
        paragraph_pair = {
            "paragraph_mean_chars",
            "paragraphs_per_1k",
        }
        if paragraph_pair.issubset(selected):
            paragraph_line = _render_paragraph_shape_anchor(
                baseline,
                current_metrics=current_metrics,
                context_chars=context_chars,
            )
            if paragraph_line:
                lines.append(paragraph_line)
        for metric_name in selected:
            if metric_name in paragraph_pair and paragraph_pair.issubset(selected):
                continue
            stats = baseline[metric_name]
            mean = _finite_number(stats.get("mean"))
            if mean is None:
                continue
            std = _finite_number(stats.get("std"))
            current = _finite_number(current_metrics.get(metric_name))
            label = _METRIC_LABELS.get(metric_name, metric_name)
            # 已知指标用紧凑中文名，避免 240 字预算被内部英文键名吃掉；未知扩展
            # 指标仍原样显示，确保未来字段不会静默消失。
            display_name = label
            target_text = _format_metric_value(metric_name, mean)
            if current is None:
                spread = (
                    f"，自然波动约±{_format_metric_value(metric_name, std)}"
                    if std is not None and std > 0
                    else ""
                )
                lines.append(
                    f"- {display_name}：目标约{target_text}{spread}。"
                )
                continue
            current_text = _format_metric_value(metric_name, current)
            direction = _metric_direction(
                metric_name,
                current=current,
                target=mean,
                std=std,
                context_chars=context_chars,
            )
            lines.append(
                f"- {display_name}：当前约{current_text}，目标约{target_text}；{direction}。"
            )
        if len(lines) == 1:
            return ""
        return "\n".join(lines)

    def _apply_budget(
        self, positive: str, forbidden: str, metric: str
    ) -> tuple[str, str, str]:
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


def _reference_sample_style_distance(
    text: str,
    baseline: dict[str, Any],
) -> float:
    """用画像自身的可观测统计挑代表段，不用题材词或作者身份。

    旧选择器只比较候选段长度，问号密集或语域异常的离群段只要长度接近
    平均值就会成为 few-shot。这里复用验证侧指标与自适应容差，先在每个
    指标组内平均，再跨组平均，避免某一组字段多就压过其余组。
    """

    if not text.strip() or not isinstance(baseline, dict) or not baseline:
        return 4.0
    try:
        from novel_system.services.style_reference.metrics import (
            compute_prose_shape_from_text,
        )
        from novel_system.services.style_reference.validation.quantitative import (
            DEFAULT_FLOOR,
            compute_generated_metrics,
        )

        actual = compute_generated_metrics(text)
        actual.update(compute_prose_shape_from_text(text))
        try:
            floors = load_yaml_config("tolerance_floors")
        except FileNotFoundError:
            floors = {}
        group_distances: list[float] = []
        for _group, names, _quota, _required in _METRIC_GROUPS:
            distances: list[float] = []
            for name in names:
                stats = baseline.get(name)
                observed = _finite_number(actual.get(name))
                if not isinstance(stats, dict) or observed is None:
                    continue
                target = _finite_number(stats.get("mean"))
                if target is None:
                    continue
                std = _finite_number(stats.get("std")) or 0.0
                floor = _finite_number(floors.get(name)) or DEFAULT_FLOOR
                tolerance = max(std * 1.25, floor, 1e-9)
                distances.append(min(4.0, abs(observed - target) / tolerance))
            if distances:
                group_distances.append(sum(distances) / len(distances))
        if group_distances:
            return sum(group_distances) / len(group_distances)
    except Exception:  # pragma: no cover - 本地指标退化不得阻断风格注入
        logger.warning("reference sample style scoring degraded", exc_info=True)
    return 4.0


def _finite_number(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _render_paragraph_shape_anchor(
    baseline: dict[str, Any],
    *,
    current_metrics: dict[str, float],
    context_chars: int | None,
) -> str:
    mean_stats = baseline.get("paragraph_mean_chars")
    rate_stats = baseline.get("paragraphs_per_1k")
    if not isinstance(mean_stats, dict) or not isinstance(rate_stats, dict):
        return ""
    target_mean = _finite_number(mean_stats.get("mean"))
    target_rate = _finite_number(rate_stats.get("mean"))
    if target_mean is None or target_rate is None:
        return ""
    current_mean = _finite_number(current_metrics.get("paragraph_mean_chars"))
    current_rate = _finite_number(current_metrics.get("paragraphs_per_1k"))
    target_text = f"{target_mean:.1f}字/{target_rate:.1f}段"
    if current_mean is None or current_rate is None:
        return f"- 段均字数/千字换段数：目标约{target_text}。"

    count_hint = _count_range_hint(
        context_chars=context_chars,
        target_count=(context_chars / max(target_mean, 1.0) if context_chars else None),
    )
    if current_mean + max(target_mean * 0.05, 1.0) < target_mean:
        action = "合并同一叙事单元，禁逐句分段"
    elif current_mean - max(target_mean * 0.05, 1.0) > target_mean:
        action = "只在叙事单元边界拆分"
    else:
        action = "保持当前段落幅度"
    count_suffix = f"；{count_hint}" if count_hint else ""
    return (
        "- 段均字数/千字换段数："
        f"当前约{current_mean:.1f}字/{current_rate:.1f}段，"
        f"目标约{target_text}{count_suffix}；{action}。"
    )


def _select_actionable_metrics(
    baseline: dict[str, Any],
    *,
    current_metrics: dict[str, float],
    excluded: frozenset[str],
    limit: int = 11,
) -> list[str]:
    """按可观测组均衡选锚点；有源稿时优先每组偏差最大的指标。"""
    valid = {
        name
        for name, stats in baseline.items()
        if name not in excluded
        and isinstance(stats, dict)
        and _finite_number(stats.get("mean")) is not None
    }
    selected: list[str] = [name for name in _METRIC_REQUIRED_ORDER if name in valid]

    def priority(name: str) -> tuple[float, int]:
        stats = baseline[name]
        target = _finite_number(stats.get("mean")) or 0.0
        current = _finite_number(current_metrics.get(name))
        if current is None:
            deviation = -1.0
        else:
            # 这里只用于同组内选“最需要动作”的指标。std 代表作者自然波动，
            # 不应把一个高辨识度但波动也高的标点习惯排除在提示外。
            scale = max(abs(target), 0.05)
            deviation = abs(current - target) / scale
        order = next(
            (
                index
                for _group, names, _quota, _required in _METRIC_GROUPS
                for index, candidate in enumerate(names)
                if candidate == name
            ),
            999,
        )
        return -deviation, order

    for _group, names, quota, _required in _METRIC_GROUPS:
        candidates = [name for name in names if name in valid]
        selected_here = [name for name in candidates if name in selected]
        optional = [name for name in candidates if name not in selected]
        optional.sort(key=priority)
        selected.extend(optional[: max(0, quota - len(selected_here))])

    # 自定义扩展指标仍可显示，避免 Profile 新增指标后静默消失；段型比例仍硬排除。
    remaining = [name for name in valid if name not in selected]
    remaining.sort(key=priority)
    selected.extend(remaining[: max(0, limit - len(selected))])
    return selected[:limit]


def _format_metric_value(metric_name: str, value: float) -> str:
    if metric_name in _RATIO_METRICS:
        return f"{value * 100:.1f}%"
    return f"{value:.1f}"


def _metric_direction(
    metric_name: str,
    *,
    current: float,
    target: float,
    std: float | None,
    context_chars: int | None = None,
) -> str:
    tolerance = max(abs(target) * 0.05, (std or 0.0) * 0.5, 0.01)
    increase = current < target
    if metric_name == "paragraph_mean_chars":
        target_chars = max(1, round(target))
        count_hint = _count_range_hint(
            context_chars=context_chars,
            target_count=(context_chars / target_chars if context_chars else None),
        )
        suffix = f"；{count_hint}" if count_hint else ""
        return (
            f"合并同一叙事单元，约每{target_chars}字换段{suffix}，禁逐句分段"
            if increase
            else f"在叙事单元边界拆段，约每{target_chars}字换段{suffix}"
        )
    if metric_name == "paragraphs_per_1k":
        target_breaks = max(1, round(target))
        count_hint = _count_range_hint(
            context_chars=context_chars,
            target_count=(
                context_chars * target / 1000.0 if context_chars else None
            ),
        )
        suffix = f"；{count_hint}" if count_hint else ""
        return (
            f"每千字约保留{target_breaks}个功能段{suffix}"
            if increase
            else f"合并同一叙事单元，每千字约{target_breaks}段{suffix}，禁逐句分段"
        )
    if metric_name == "semicolon_density_per_1k" and context_chars:
        expected = max(0, round(context_chars * target / 1000.0))
        natural_delta = round(context_chars * max(std or 0.0, 0.0) / 1000.0)
        radius = max(1, min(2, natural_delta))
        lower = max(0, expected - radius)
        upper = expected + radius
        return (
            f"全文约{expected}个，控制在{lower}–{upper}个，分散使用勿堆叠"
        )
    if abs(current - target) <= tolerance:
        return "保持当前幅度"
    verbs = {
        "paragraph_length_std_chars": (
            "增加长短段落层次",
            "收敛过大的段落长度落差",
        ),
        "single_sentence_paragraph_ratio": (
            "增加少量承担转折的单句段",
            "减少连续单句碎段",
        ),
        "quote_led_paragraph_ratio": (
            "增加少量直接对话段",
            "减少引号直接起段，让对话嵌入动作或叙述",
        ),
        "avg_sentence_length": ("适度拉长部分句子", "适度拆短复句"),
        "sentence_length_std": ("增加长短句落差", "收敛过大的句长跳动"),
        "short_sentence_ratio": ("增加短句断点", "减少碎片化短句"),
        "long_sentence_ratio": ("增加少量承接长句", "减少拖长句"),
        "punctuation_density_per_1k": ("增加必要停顿", "减少过密标点"),
        "dash_em_density_per_1k": ("适量增加破折号停顿", "减少破折号"),
        "ellipsis_density_per_1k": ("适量增加省略停顿", "明显减少省略号"),
        "semicolon_density_per_1k": ("适量增加分号并列", "减少分号并列"),
        "question_density_per_1k": ("增加必要问句", "减少问句"),
        "classical_word_ratio": ("增加少量文言虚词", "减少文言虚词"),
        "colloquial_marker_ratio": ("增加自然口语语气", "收敛口语语气词"),
        "metaphor_density_per_1k": ("增加少量有效比喻", "减少比喻标记"),
        "personification_density_per_1k": ("增加少量拟人动作", "减少拟人标记"),
    }
    if metric_name.startswith("sensory_"):
        return "增加该感官的具体落点" if increase else "减少该感官词的重复堆叠"
    pair = verbs.get(metric_name, ("适度提高", "适度降低"))
    return pair[0] if increase else pair[1]


def _count_range_hint(
    *, context_chars: int | None, target_count: float | None
) -> str:
    if not context_chars or target_count is None:
        return ""
    expected = max(1, round(target_count))
    lower = max(1, expected - 1)
    upper = expected + 1
    return f"按当前约{context_chars}字，全文约{expected}段（{lower}–{upper}段）"


def _ts_to_int(ts: str | None) -> int:
    """把 ISO 时间串转为可比 int(只用于排序,失败回 0)。

    取前 20 位数字(YYYYMMDDHHMMSS + 微秒 6 位):models.utcnow() 是进程内严格
    单调的微秒级时间戳,截到秒([:14])会让同秒创建的多条 binding 排序退化为
    非确定的插入序;补齐微秒后「最新优先」决平确定。
    """
    if not ts:
        return 0
    cleaned = "".join(ch for ch in ts if ch.isdigit())
    if not cleaned:
        return 0
    try:
        return int(cleaned[:20].ljust(20, "0"))
    except ValueError:
        return 0
