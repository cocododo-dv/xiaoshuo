"""生成《全系统 LLM 提示词优化交接文档》（给 Sonnet 5 直接投喂的自包含文档）。

用法（在 backend/ 下）：
    python -m novel_system.tools.export_prompt_handoff          # 写 docs/prompt-optimization-handoff.md
    python -m novel_system.tools.export_prompt_handoff --check  # 只跑完整性断言，不写文件

提取策略（保真优先）：
- prompts.yaml 模板：复用 prompt_builder.load_prompt_templates()（DB 快照优先、文件兜底），
  文档里记录本次的真实来源；
- 注册表/models.yaml：import / yaml.safe_load；
- Python 内联提示词与片段常量：AST 解析源文件取字面量（不 import 重依赖业务模块）；
  函数内联的两处（scene_quality / literary_eval）用注释模块里的逐字拷贝 + 源码锚点断言防漂移；
- 所有 file:line 引用都由「锚点子串 → 当前行号」在生成时解析，锚点消失即断言失败。

任何断言失败：打印全部失败项，退出码 1，不写文档。
"""
from __future__ import annotations

import argparse
import ast
import datetime as _dt
import json
import sys
from pathlib import Path
from typing import Any

import yaml

from novel_system.services.llm_node_registry import LLMNodeSpec, llm_node_specs
from novel_system.services.prompt_builder import (
    DRAFTING_TEMPLATE_NAMES,
    PromptTemplate,
    parse_prompt_templates,
)
from novel_system.tools import prompt_handoff_annotations as ann

REPO_ROOT = Path(__file__).resolve().parents[4]
DOC_PATH = REPO_ROOT / "docs" / "prompt-optimization-handoff.md"

# 审计结论的固定期望值（漂移时提醒重新盘点，而不是静默出错文档）
EXPECTED_TEMPLATE_COUNT = 54
EXPECTED_NODE_COUNT = 60
EXPECTED_ORPHAN_ACTIVE_NODES = {
    "reference_sample_ranker",
    "reference_style_structure_extract",
    "reference_profile_synthesize",
    "scene_quality_contract",
    "writer_reference_application_review",
    "writer_scene_diagnosis",
    "writer_chapter_diagnosis",
}

_ERRORS: list[str] = []


def _err(msg: str) -> None:
    _ERRORS.append(msg)


# ---------------------------------------------------------------------------
# 锚点 → 行号
# ---------------------------------------------------------------------------
_FILE_CACHE: dict[str, list[str]] = {}


def _file_lines(rel_path: str) -> list[str] | None:
    if rel_path not in _FILE_CACHE:
        fp = REPO_ROOT / rel_path
        if not fp.is_file():
            _err(f"锚点文件不存在: {rel_path}")
            _FILE_CACHE[rel_path] = []
        else:
            _FILE_CACHE[rel_path] = fp.read_text(encoding="utf-8").splitlines()
    return _FILE_CACHE[rel_path]


def resolve_anchor(rel_path: str, anchor: str, occurrence: int = 1) -> int | None:
    lines = _file_lines(rel_path)
    if not lines:
        return None
    seen = 0
    for idx, line in enumerate(lines, start=1):
        if anchor in line:
            seen += 1
            if seen == occurrence:
                return idx
    _err(f"锚点未命中: {rel_path} :: {anchor!r} (第 {occurrence} 次出现)")
    return None


def loc(rel_path: str, anchor: str, occurrence: int = 1) -> str:
    line = resolve_anchor(rel_path, anchor, occurrence)
    return f"`{rel_path}:{line}`" if line else f"`{rel_path}:?`"


# ---------------------------------------------------------------------------
# AST 字面量提取（避免 import 业务重模块）
# ---------------------------------------------------------------------------
_AST_CACHE: dict[str, dict[str, Any]] = {}


def _module_consts(dotted: str) -> dict[str, Any]:
    if dotted in _AST_CACHE:
        return _AST_CACHE[dotted]
    rel = "backend/src/" + dotted.replace(".", "/") + ".py"
    fp = REPO_ROOT / rel
    consts: dict[str, Any] = {}
    if not fp.is_file():
        _err(f"AST 源文件不存在: {rel}")
    else:
        tree = ast.parse(fp.read_text(encoding="utf-8"))
        for node in tree.body:
            targets: list[str] = []
            value = None
            if isinstance(node, ast.Assign):
                targets = [t.id for t in node.targets if isinstance(t, ast.Name)]
                value = node.value
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                targets = [node.target.id]
                value = node.value
            if not targets or value is None:
                continue
            try:
                literal = ast.literal_eval(value)
            except (ValueError, TypeError, SyntaxError):
                continue
            for name in targets:
                consts[name] = literal
    _AST_CACHE[dotted] = consts
    return consts


def ast_const(dotted: str, attr: str) -> Any:
    consts = _module_consts(dotted)
    if attr not in consts:
        _err(f"AST 常量未找到: {dotted}.{attr}")
        return None
    return consts[attr]


# ---------------------------------------------------------------------------
# Markdown 辅助
# ---------------------------------------------------------------------------


def fence(text: str, lang: str = "text") -> str:
    body = (text or "").rstrip("\n")
    mark = "````" if "```" in body else "```"
    return f"{mark}{lang}\n{body}\n{mark}"


def schema_fence(schema: Any) -> str:
    return fence(json.dumps(schema, ensure_ascii=False, indent=2), "json")


# ---------------------------------------------------------------------------
# 数据装载
# ---------------------------------------------------------------------------


def load_templates() -> tuple[dict[str, PromptTemplate], str]:
    """DB 快照优先（与运行时一致），失败/缺席回落 config/prompts.yaml。"""
    try:
        from novel_system.services.system_config import load_active_config_payload

        payload = load_active_config_payload("prompts")
        if payload is not None:
            return parse_prompt_templates(payload), "DB 系统配置快照（category=prompts，当前生效——注意与 config/prompts.yaml 可能不一致）"
    except Exception as exc:  # noqa: BLE001 — DB 不可达时按文件出文档并明示
        source_note = f"config/prompts.yaml（读取 DB 快照失败已回落: {type(exc).__name__}）"
        raw = yaml.safe_load((REPO_ROOT / "config" / "prompts.yaml").read_text(encoding="utf-8"))
        return parse_prompt_templates(raw), source_note
    raw = yaml.safe_load((REPO_ROOT / "config" / "prompts.yaml").read_text(encoding="utf-8"))
    return parse_prompt_templates(raw), "config/prompts.yaml（无生效的 DB prompts 快照）"


def load_models() -> dict[str, Any]:
    return yaml.safe_load((REPO_ROOT / "config" / "models.yaml").read_text(encoding="utf-8"))


def load_eval_cases() -> list[dict[str, Any]]:
    fp = REPO_ROOT / "config" / "evals" / "literary_small.yaml"
    if not fp.is_file():
        _err("config/evals/literary_small.yaml 不存在")
        return []
    payload = yaml.safe_load(fp.read_text(encoding="utf-8")) or {}
    cases = payload.get("cases")
    if not isinstance(cases, list):
        cases = (payload.get("suite") or {}).get("cases") if isinstance(payload.get("suite"), dict) else None
    out: list[dict[str, Any]] = []
    for item in cases or []:
        if isinstance(item, dict) and item.get("prompt"):
            out.append(item)
    if not out:
        _err("literary_small.yaml 未解析出任何带 prompt 的评测用例")
    return out


def routing_line(task_routing: dict[str, Any], node_id: str) -> str:
    cfg = task_routing.get(node_id)
    if not isinstance(cfg, dict):
        return "（models.yaml 无此路由）"
    parts = [f"model=`{cfg.get('model')}`"]
    if cfg.get("model_profile"):
        parts.append(f"profile=`{cfg['model_profile']}`")
    parts.append(f"temperature={cfg.get('temperature')}")
    parts.append(f"max_output_tokens={cfg.get('max_output_tokens')}")
    parts.append(f"response_format=`{cfg.get('response_format')}`")
    for key in ("frequency_penalty", "presence_penalty", "top_p", "timeout_seconds", "refresh_every_chars"):
        if cfg.get(key) is not None:
            parts.append(f"{key}={cfg[key]}")
    return "，".join(parts)


# ---------------------------------------------------------------------------
# 校验
# ---------------------------------------------------------------------------


def run_assertions(
    templates: dict[str, PromptTemplate],
    specs: tuple[LLMNodeSpec, ...],
    models_cfg: dict[str, Any],
) -> dict[str, Any]:
    yaml_keys = set(templates)
    unit_template_keys = {u["template_key"] for u in ann.UNITS if u["template_key"]}
    if len(yaml_keys) != EXPECTED_TEMPLATE_COUNT:
        _err(f"模板数漂移: 期望 {EXPECTED_TEMPLATE_COUNT}，实际 {len(yaml_keys)}（重新盘点后更新期望值）")
    missing_in_units = sorted(yaml_keys - unit_template_keys)
    extra_in_units = sorted(unit_template_keys - yaml_keys)
    if missing_in_units:
        _err(f"yaml 模板未被任何单元覆盖: {missing_in_units}")
    if extra_in_units:
        _err(f"单元引用了不存在的 yaml 模板: {extra_in_units}")

    registry_ids = {s.node_id for s in specs}
    if len(specs) != EXPECTED_NODE_COUNT:
        _err(f"注册节点数漂移: 期望 {EXPECTED_NODE_COUNT}，实际 {len(specs)}")
    covered_nodes: set[str] = set()
    for unit in ann.UNITS:
        covered_nodes.update(unit["node_ids"])
    unknown_nodes = sorted(covered_nodes - registry_ids)
    if unknown_nodes:
        _err(f"单元引用了注册表之外的节点: {unknown_nodes}")
    uncovered = sorted(registry_ids - covered_nodes - set(ann.NO_PROMPT_NODES))
    if uncovered:
        _err(f"注册节点未被单元或 NO_PROMPT_NODES 覆盖: {uncovered}")

    task_routing = models_cfg.get("task_routing") or {}
    stray_routes = sorted(set(task_routing) - registry_ids - set(ann.EXTRA_ROUTING_KEYS))
    if stray_routes:
        _err(f"models.yaml task_routing 存在未盘点的键: {stray_routes}")

    if len(ann.CALL_SITES) != ann.EXPECTED_CALL_SITE_COUNT:
        _err(f"调用点数漂移: 注释里 {len(ann.CALL_SITES)}，期望 {ann.EXPECTED_CALL_SITE_COUNT}")
    for site in ann.CALL_SITES:
        resolve_anchor(site["file"], site["anchor"], site["occurrence"])

    site_nodes: set[str] = set()
    for site in ann.CALL_SITES:
        site_nodes.update(site["nodes"])
    orphan_active = {
        s.node_id
        for s in specs
        if s.status == "active" and s.requires_llm and s.node_id not in site_nodes
    }
    if orphan_active != EXPECTED_ORPHAN_ACTIVE_NODES:
        _err(
            "活跃孤儿节点集合漂移: "
            f"新增 {sorted(orphan_active - EXPECTED_ORPHAN_ACTIVE_NODES)}，"
            f"消失 {sorted(EXPECTED_ORPHAN_ACTIVE_NODES - orphan_active)}"
        )

    for unit in ann.UNITS:
        for field in ("purpose", "inputs", "output_contract", "failure", "opt_notes", "status", "trigger"):
            if not str(unit.get(field) or "").strip():
                _err(f"单元 {unit['unit_id']} 缺少字段 {field}")
        is_wired = not any(tag in unit["status"] for tag in ("孤儿", "保留", "本地", "休眠")) or unit["adhoc_task"] in (
            "consistency_extract",
            "causal_skeleton_refine",
        )
        if not unit["call_chain"] and "孤儿" not in unit["status"] and "保留" not in unit["status"] and "本地" not in unit["status"]:
            _err(f"活跃单元 {unit['unit_id']} 没有调用链锚点")
        _ = is_wired
        for file, anchor, occurrence, _note in unit["call_chain"]:
            resolve_anchor(file, anchor, occurrence)
        for file, anchor, occurrence in unit["parser_refs"]:
            resolve_anchor(file, anchor, occurrence)
        if unit["template_key"] is None and unit["inline_key"] is None and "孤儿" not in unit["status"]:
            _err(f"单元 {unit['unit_id']} 既无模板也无内联提示词")
        if unit["inline_key"] and unit["inline_key"] not in ann.INLINE_PROMPTS:
            _err(f"单元 {unit['unit_id']} 的 inline_key 不存在: {unit['inline_key']}")

    for key, spec in ann.INLINE_PROMPTS.items():
        for _label, _text, anchors in spec["verbatim_blocks"]:
            for anchor in anchors:
                resolve_anchor(spec["file"], anchor)
        for module, attr, _label in spec["import_attrs"]:
            ast_const(module, attr)
    for frag in ann.FRAGMENTS:
        for module, attr, _label in frag.get("import_attrs", []):
            ast_const(module, attr)
        for _label, _text, anchors in frag.get("verbatim_blocks", []):
            for anchor in anchors:
                resolve_anchor(frag["file"], anchor)
        if frag.get("read_file") and not (REPO_ROOT / frag["read_file"]).is_file():
            _err(f"片段引用的文件不存在: {frag['read_file']}")

    stale_drafting = sorted(DRAFTING_TEMPLATE_NAMES - yaml_keys)
    return {
        "orphan_active": sorted(orphan_active),
        "stale_drafting": stale_drafting,
        "task_routing_count": len(task_routing),
    }


# ---------------------------------------------------------------------------
# 文档渲染
# ---------------------------------------------------------------------------


def render_briefing(counts: dict[str, Any]) -> list[str]:
    batch_rows = "\n".join(
        f"| {b['id']} | {b['title'].split('·', 1)[1].strip()} | "
        f"{sum(1 for u in ann.UNITS if u['batch'] == b['id'])} 个单元 |"
        for b in ann.BATCHES
    )
    return [
        "## §0 给 Sonnet 5 的任务简报",
        "",
        "你是一位提示词工程与小说创作双料专家。本文档是一个**中文网文创作系统**（雪花法构思 → 场景生成 → "
        "质量门 → 风格模仿 → 作家评审全管线）的**全量 LLM 提示词交接书**：系统里每一处 LLM 调用、"
        "每一份提示词原文、路由参数、输入组装方式、输出契约与失败降级都在这里，你**不需要也无法访问代码仓库**。",
        "",
        "### 你的任务",
        "按批次优化本文档 §3–§8 中的提示词（system_prompt / task_prompt / structured_schema 描述部分），并按"
        "「回写格式」输出可直接落盘的替换块。**一次会话只处理一个批次**：先给该批的《诊断与改写策略》（每个模板"
        "≤5 行：现有问题 → 改法），经确认后再输出回写块。",
        "",
        "| 批次 | 主题 | 规模 |",
        "|---|---|---|",
        batch_rows,
        "",
        "### 优化目标（按优先级）",
        "1. **去AI味 / 文学质量**：本系统自带 21 维文学质量规则打分（感知过滤缺失、冲突太干净、总结式收尾、"
        "解释性对白、意象复用、句式单调、自我重复等都是扣分维度）与「蓝图 v2 反AI味」机制。生成类模板"
        "（雪花各步、场景蓝图、中性稿、风格化、续写、改写）要把这些维度转译成**可执行的写作指令与禁令**，"
        "而不是「写得更生动」式空话。评审/QC 类模板则要求发现项**证据化、可定位、可执行**。",
        "2. **弱模型鲁棒性**：真实执行模型是用户在系统设置里配置的**中档中转模型**（当前典型为 oneapi 中转的 "
        "deepseek-v4-flash 一类，而非模板路由里名义上的 gpt-5）。已知病症：**结构化输出不稳**（字段自造、"
        "枚举越界、JSON 夹杂散文）与**产出薄**（抽取类返回 0 条或每条只写一半字段）。对策：指令显式分步、"
        "字段逐个说明用途并给填写范例、给**产出下限**（最少条数/字数）、把「找不到就返回空」与「必须凑满」"
        "的边界讲清楚。注意系统已有降级链路（见 §1），schema 可能被整段内联进 system prompt——schema 本身"
        "也是提示词，要精简自描述。",
        "",
        "### 硬约束（违反即返工）",
        "1. **structured_schema 的字段名、required 列表、枚举值一律冻结**——下游解析器按名取值（每个单元标注了"
        "解析器位置）。确有必要改 schema 时，放进单独的《schema 变更提案》区并说明需要同步改哪处代码，"
        "**不得**混进回写块。hard_qc / soft_qc 的 resolution_code / next_action 枚举更是被运行时代码强制合并"
        "（§9「qc_schema_alignment」），改了也会被覆盖。",
        "2. **运行时自动追加的内容不要写进模板**：语言锁、角色连续性指令、「Return only valid JSON…」收尾、"
        "枚举列举、上下文分节、[STYLE_REFERENCE] 注入块与反抄袭红线、发散化前缀——这些全部由代码追加"
        "（清单见 §9）。模板里复写 = 双份指令互相打架。",
        "3. **占位符原样保留**：`{paragraphs}`、`{scene_context_block}`、`{text}`、`{facts_block}`、"
        "`{controlling_idea}`、`{ending_state}`、`{chain_block}`、`{banned_terms_list}` 等花括号槽位是代码 "
        "format 的接缝，一个都不能丢或改名。",
        "4. **输出语言契约不变**：多数模板是英文指令 + 要求中文产出（scene_text 为中文散文、评审意见跟随草稿语言）。"
        "你可以判断某模板改成中文指令对弱模型更稳——允许，但必须在该模板的策略段里说明理由，且语言锁语义不得削弱。",
        "5. **input_token_budget 是输入预算**（不是输出）：task_prompt 加长要克制，上下文大头是自动注入的分节。",
        "6. **version 字段必须 bump**（建议 `2026-07-04.v2` 风格）；`prompt_hash` 会随内容自动变化，无缓存冲突。",
        "7. **反抄袭 / 版权红线语义只增不减**：所有涉参考书的模板（批次 D、风格化）中「抽象风格、禁抄招牌意象、"
        "禁复制原文」的约束是法务级要求。",
        "8. **孤儿/休眠/保留单元（标 P2）默认跳过**，除非用户点名。评测集提示词（§10）**勿动**。",
        "",
        "### 回写格式（每批次的最终输出）",
        "- **yaml 模板**：每个改动模板输出一个完整可替换块——",
        "  ````",
        "  ### 回写 · <template_key>",
        "  ```yaml",
        "  <template_key>:",
        "    version: \"<bumped>\"",
        "    input_token_budget: <n>",
        "    system_prompt: |",
        "      ...",
        "    task_prompt: |",
        "      ...",
        "    structured_schema:",
        "      ...（原样保留，除非走《schema 变更提案》）",
        "  ```",
        "  ````",
        "  用户会用它整段替换 `config/prompts.yaml` 里的同名键（顶格两空格缩进，与原文件一致）。",
        "- **Python 内联提示词**：输出「文件路径 + 旧字符串（逐字）→ 新字符串（逐字）」对，供精确替换；"
        "占位符与外围引号拼接方式保持原状。",
        "- **不改的模板**：显式列出「跳过：<key>（理由一句话）」。",
        "- **《schema 变更提案》**（如有）：单独一节，含动机、影响的解析器位置、建议的代码改动点。",
        "",
        "### 你没有的信息（防幻觉声明）",
        "你看到的是模板与机制，**看不到运行时的真实上下文实例**（bundle 分节内容、参考书 findings 等）。"
        "涉及输入实态的判断请以「假设：…」标注；不要虚构本文档未记载的字段名、路由或代码行为。",
        "",
        f"> 本文档由 `python -m novel_system.tools.export_prompt_handoff` 生成；数字对账见 §12"
        f"（模板 {counts['templates']}、注册节点 {counts['nodes']}、调用点 {counts['call_sites']}）。",
        "",
    ]


def render_architecture(models_cfg: dict[str, Any], template_source: str) -> list[str]:
    retry = models_cfg.get("retry_budget") or {}
    lines = [
        "## §1 系统与调用架构速览",
        "",
        "**管线图景**：雪花十步构思 →（分诊+物化）→ ChapterGoal/SceneCard → 场景运行管线"
        "（bundle 上下文 → 场景蓝图 → 中性稿 → 风格化 Best-of-N（规则盲评选优）→ 可选 LLM 编辑评审 → "
        "硬/软 QC → 近终稿评审）→ 归档/资料库派生。旁路子系统：风格参考（参考书 → 分类 → 四层抽取 → "
        "Profile → 注入/验证）、作家评审（四镜头诊断+修订+深评）、文学评测。",
        "",
        "**LLM 补全出口只有两类，且都统一记账**：",
        f"1. `execute_accounted_call`（{loc('backend/src/novel_system/services/llm_accounting.py', 'def execute_accounted_call(')}）——"
        "全部业务补全先落父调用，再由 attempt hook 包围每次物理请求；",
        f"2. 系统设置补全探针（{loc('backend/src/novel_system/services/llm_accounting.py', 'response = httpx.post(')}）——"
        "同样落 `system/provider_probe` 父子账本。模型列表 GET 不产生 token，不建 LLM 调用。",
        "全仓无任何 openai/anthropic SDK 直连、无 embedding API（向量为本地确定性哈希）。",
        "",
        "**四条调用路径**（每个单元标注了自己走哪条）：",
        "1. `LLMNodeRunner.run(node_id=…)`——审计路径：`PromptBuilder` 组装、落 `LlmCall` 审计行、"
        "上下文预算超限抛连续性错误；",
        "2. `LLMNodeRunner.run_task(task_name=…)`——顾问路径：内联提示词、不落草稿、失败快速降级；"
        "别名表 `auto_critique_llm→soft_qc`、`narrative_event_extract→extraction`（借道路由，不占独立节点）；",
        "3. `style_reference/_llm_helper.call_llm_node(node_id, UntrustedPayload, client, session, context)`——调用方传 typed "
        "payload；Mapping/list/tuple 内字符串叶值递归中和并转义伪边界，user_prompt 将 task 留在唯一显式 "
        "UNTRUSTED_REFERENCE_DATA JSON 区块外；system 追加“数据非指令、禁止 role/tool/schema 变更”约束，"
        "response_schema 仍是 request 独立字段；超时保底 120s；",
        "4. 专用请求组装器：雪花工作台（模板 + JSON payload）、文学评测（内联提示词）和段落分类器；"
        "三者都调用 `execute_accounted_call`，其中段落分类器还复用路径 3 的 typed `UntrustedPayload`、"
        "递归中和与 system 数据约束，可信 task 位于唯一显式 JSON boundary 外。",
        "",
        "**PromptBuilder 组装契约**（路径 1 的所有模板）：`system_prompt` **原样发送、无变量替换**；"
        "`user_prompt` = task_prompt + 运行时指令（语言锁/角色连续性，仅特定模板）+ schema 收尾指令 + "
        "带英文标签的上下文分节（bundle 快照按 token 预算与 allowlist 裁剪；标签清单见 §9）。"
        "所以模板正文里**不出现**花括号变量——数据全部以分节/JSON 形式进 user_prompt。",
        "",
        "**路由双层**：`config/models.yaml` 的 task_routing 只是静态兜底；系统设置「模型与接入」写入 DB "
        "node_routing（provider/model/api_mode 按「写作主力/审稿质检/提炼整理」三个角色槽批量路由），"
        "**DB 优先**。本文档标注的模型/温度是 yaml 默认值——真实执行以用户 DB 配置为准（当前典型：中转 "
        "deepseek-v4-flash 类中档模型）。",
        "",
        "**降级阶梯**（`LLMClient.generate` 内建，对提示词设计有直接影响）：`/responses` 404 → 换 chat；"
        "wire `json_schema` 被拒 → 退 `json_object` → 再退无 response_format，**同时把 schema 以中文提示内联进 "
        "system prompt**（原文见 §9「schema_inline_hint」）；空正文（思考烧光预算）→ 关 reasoning + 预算×2 重试。"
        "结论按 (provider, model) 进程内缓存。含义：**schema 本身会成为提示词的一部分**，字段名要自解释。",
        "",
        f"**重试预算**（models.yaml）：hard_partial_max={retry.get('hard_partial_max')}，"
        f"hard_full_max={retry.get('hard_full_max')}，soft_patch_max={retry.get('soft_patch_max')}，"
        f"total_attempt_budget={retry.get('total_attempt_budget')}。",
        "",
        "**提示词的运行时真源**：yaml 模板可被 DB 系统配置快照（category=prompts）**整体覆盖**"
        "（`POST /api/v1/system-config/drafts` + activate；导出现行版本用 "
        "`GET /api/v1/system-config/export/prompts`）。6 处 Python 内联提示词**不受**快照覆盖。"
        f"**本文档模板取自：{template_source}**。优化回写后：若曾激活过 prompts 快照，改文件不生效，"
        "需重新走 drafts+activate（或清掉快照）。",
        "",
    ]
    return lines


def render_inventory(
    specs: tuple[LLMNodeSpec, ...],
    task_routing: dict[str, Any],
    audit: dict[str, Any],
) -> list[str]:
    node_units: dict[str, dict[str, Any]] = {}
    for unit in ann.UNITS:
        for node_id in unit["node_ids"]:
            node_units.setdefault(node_id, unit)
    node_sites: dict[str, list[str]] = {}
    for site in ann.CALL_SITES:
        ref = loc(site["file"], site["anchor"], site["occurrence"])
        for node_id in site["nodes"]:
            node_sites.setdefault(node_id, []).append(ref)

    lines = [
        "## §2 全量 LLM 调用清单（零遗漏）",
        "",
        "注册表 60 节点 + 2 个未注册的休眠 ad-hoc 任务 + 连通性探针。状态口径：**活跃**=有真实调用点；"
        "**孤儿**=active 且 requires_llm 但无调用点；**模板载体**=仅为镜头节点提供模板名；"
        "**保留/本地**=设计上不调 LLM；**休眠**=代码在但无路由无注册，生产不可达。",
        "",
        "| # | 节点 / 任务 | 组 | 状态 | 提示词来源 | 调用点 |",
        "|---|---|---|---|---|---|",
    ]
    orphan_set = set(audit["orphan_active"])
    for idx, spec in enumerate(specs, start=1):
        if spec.node_id in ann.NO_PROMPT_NODES:
            status = "本地保留" if spec.group == "local" else "孤儿·无模板"
            source = "无"
        elif spec.node_id in orphan_set:
            if spec.node_id in {"writer_scene_diagnosis", "writer_chapter_diagnosis"}:
                status = "模板载体（镜头节点共用，不直接调用）"
            else:
                status = "孤儿"
            unit = node_units.get(spec.node_id)
            source = f"yaml:`{unit['template_key']}`" if unit and unit["template_key"] else "无"
        elif spec.status != "active" or not spec.requires_llm:
            status = "保留"
            unit = node_units.get(spec.node_id)
            source = f"yaml:`{unit['template_key']}`" if unit and unit["template_key"] else "无"
        else:
            status = "活跃"
            unit = node_units.get(spec.node_id)
            if unit and unit["template_key"]:
                source = f"yaml:`{unit['template_key']}`"
            elif unit and unit["inline_key"]:
                source = f"内联:`{ann.INLINE_PROMPTS[unit['inline_key']]['file'].rsplit('/', 1)[-1]}`"
            else:
                source = "？"
        sites = "；".join(node_sites.get(spec.node_id, [])) or "—"
        lines.append(f"| {idx} | `{spec.node_id}` | {spec.group} | {status} | {source} | {sites} |")

    adhoc_rows = [
        ("auto_critique_llm", "顾问·活跃（别名→soft_qc）", "内联:`auto_critique.py`"),
        ("narrative_event_extract", "顾问·活跃（别名→extraction）", "内联:`prose_event_extractor.py`"),
        ("consistency_extract", "顾问·休眠（无路由无注册）", "内联:`narrative_event_log.py`"),
        ("causal_skeleton_refine", "顾问·休眠（无路由无注册）", "内联:`reverse_causal_skeleton.py`"),
    ]
    site_by_label = {s["anchor"]: s for s in ann.CALL_SITES}
    _ = site_by_label
    adhoc_anchor = {
        "auto_critique_llm": (f"{ann.SVC}/auto_critique.py", 'task_name="auto_critique_llm"'),
        "narrative_event_extract": (f"{ann.SVC}/prose_event_extractor.py", "task_name=EXTRACT_TASK_NAME"),
        "consistency_extract": (f"{ann.SVC}/narrative_event_log.py", 'task_name="consistency_extract"'),
        "causal_skeleton_refine": (f"{ann.SVC}/reverse_causal_skeleton.py", 'task_name="causal_skeleton_refine"'),
    }
    for name, status, source in adhoc_rows:
        file, anchor = adhoc_anchor[name]
        lines.append(f"| — | `{name}`（run_task 任务名） | — | {status} | {source} | {loc(file, anchor)} |")
    lines.append(
        f"| — | `stylize`（task_routing 键） | — | 别名/兜底路由 | {ann.EXTRA_ROUTING_KEYS['stylize'][:38]}… | — |"
    )
    lines.append(
        f"| — | 连通性探针 / 模型列表 | — | 管理路径（无业务提示词） | 无 | "
        f"{loc(f'{ann.SVC}/llm_accounting.py', 'response = httpx.post(')}；"
        f"{loc(f'{ann.SVC}/system_config.py', 'httpx.get(list_request.url, headers=list_request.headers')}；"
        f"{loc(f'{ann.SVC}/system_config.py', 'response = httpx.get(', 2)} |"
    )
    lines += [
        "",
        f"**调用点合计 {len(ann.CALL_SITES)} 处**：21× `LLMNodeRunner.run` + 4× `run_task`（2 休眠）+ "
        "7× `call_llm_node` + 3× 专用 accounted 调用 + 1× accounted 探针 POST + 2× 无 token 的管理 GET。",
        "",
        "### 查证过不存在的调用形态（负面证据）",
        "",
    ]
    lines += [f"- {item}" for item in ann.NEGATIVE_EVIDENCE]
    lines.append("")
    return lines


def render_unit(
    unit: dict[str, Any],
    templates: dict[str, PromptTemplate],
    task_routing: dict[str, Any],
    seq: str,
) -> list[str]:
    lines = [f"### [{seq}] {unit['title']}", ""]
    meta = [
        f"- **状态**：{unit['status']}",
        f"- **优先级**：{unit['priority']}",
    ]
    if unit["node_ids"]:
        meta.append("- **节点**：" + "、".join(f"`{n}`" for n in unit["node_ids"]))
    if unit["adhoc_task"]:
        meta.append(f"- **run_task 任务名**：`{unit['adhoc_task']}`")
    if unit["template_key"]:
        tpl = templates[unit["template_key"]]
        meta.append(
            f"- **模板**：`config/prompts.yaml` → `{unit['template_key']}`（version `{tpl.version}`，"
            f"input_token_budget {tpl.input_token_budget}）"
        )
    if unit["inline_key"]:
        meta.append(f"- **内联提示词**：`{ann.INLINE_PROMPTS[unit['inline_key']]['file']}`（不受 DB 快照覆盖）")
    route_nodes = unit["node_ids"] or ([unit["adhoc_task"]] if unit["adhoc_task"] else [])
    seen_route: set[str] = set()
    for node_id in route_nodes:
        line = routing_line(task_routing, node_id)
        if line in seen_route and len(route_nodes) > 2:
            continue
        seen_route.add(line)
        label = node_id if len(route_nodes) > 1 else "默认路由"
        meta.append(f"- **路由（yaml 兜底，DB 优先）** `{label}`：{line}")
    lines += meta
    lines.append(f"- **用途**：{unit['purpose']}")
    lines.append(f"- **触发**：{unit['trigger']}")
    if unit["call_chain"]:
        chain = "；".join(
            f"{loc(f, a, o)}（{note}）" for f, a, o, note in unit["call_chain"]
        )
        lines.append(f"- **调用链**：{chain}")
    lines.append(f"- **输入组装**：{unit['inputs']}")
    contract = unit["output_contract"]
    if unit["parser_refs"]:
        refs = "、".join(loc(f, a, o) for f, a, o in unit["parser_refs"])
        contract += f"（解析/校验：{refs}）"
    lines.append(f"- **输出契约**：{contract}")
    lines.append(f"- **失败与降级**：{unit['failure']}")
    lines.append(f"- **优化注意**：{unit['opt_notes']}")
    lines.append("")

    if unit["template_key"]:
        tpl = templates[unit["template_key"]]
        lines += [
            "**system_prompt（原样发送）**",
            "",
            fence(tpl.system_prompt),
            "",
            "**task_prompt（运行时在其后追加指令与上下文）**",
            "",
            fence(tpl.task_prompt),
            "",
            "**structured_schema（wire 层 + 降级时内联；字段名冻结）**",
            "",
            schema_fence(tpl.structured_schema),
            "",
        ]
    if unit["inline_key"]:
        spec = ann.INLINE_PROMPTS[unit["inline_key"]]
        for module, attr, label in spec["import_attrs"]:
            value = ast_const(module, attr)
            if value is None:
                continue
            lines += [f"**{label}**（`{module.rsplit('.', 1)[-1]}.{attr}`）", "", fence(str(value)), ""]
        for label, text, _anchors in spec["verbatim_blocks"]:
            lines += [f"**{label}**", "", fence(text), ""]
        if spec.get("extra_schema"):
            lines += ["**structured_schema（代码内联；字段名冻结）**", "", schema_fence(spec["extra_schema"]), ""]
        if spec.get("note"):
            lines += [f"> {spec['note']}", ""]
    return lines


def render_fragments() -> list[str]:
    lines = [
        "## §9 运行时拼接片段附录",
        "",
        "以下内容由代码**自动追加**到模板之外——优化模板时**不要**把它们复写进 system_prompt/task_prompt；"
        "若要改这些片段本身，需改对应源码。",
        "",
    ]
    for frag in ann.FRAGMENTS:
        lines.append(f"### {frag['title']}")
        lines.append("")
        lines.append(f"- 位置：`{frag['file']}`")
        lines.append(f"- 机制：{frag['how']}")
        lines.append("")
        for module, attr, label in frag.get("import_attrs", []):
            value = ast_const(module, attr)
            if value is None:
                continue
            if attr == "SECTION_SPECS":
                lines.append(f"**{label}**（共 {len(value)} 个分节，按注入顺序）")
                lines.append("")
                lines += [f"- `{name}` → “{label_}”" for name, label_, _keys in value]
                lines.append("")
            elif isinstance(value, (list, tuple)):
                lines.append(f"**{label}**")
                lines.append("")
                for i, item in enumerate(value, start=1):
                    lines += [f"（第 {i} 条）", "", fence(str(item)), ""]
            else:
                lines += [f"**{label}**", "", fence(str(value)), ""]
        for label, text, _anchors in frag.get("verbatim_blocks", []):
            lines += [f"**{label}**", "", fence(text), ""]
        if frag.get("read_file"):
            content = (REPO_ROOT / frag["read_file"]).read_text(encoding="utf-8")
            lines += [f"**`{frag['read_file']}` 原文**", "", fence(content), ""]
    return lines


def render_evals(cases: list[dict[str, Any]]) -> list[str]:
    lines = [
        "## §10 评测集提示词附录（勿动）",
        "",
        f"`config/evals/literary_small.yaml` 共 {len(cases)} 个用例——`literary_eval_live` 通道会把用例的 "
        "`prompt` 嵌入 user_prompt 生成候选场景，再由**规则引擎**打分。改这些 prompt 会破坏历史评测可比性，"
        "**列出仅为完整性**。",
        "",
    ]
    for case in cases:
        cid = case.get("case_id") or case.get("id") or "?"
        title = case.get("title") or ""
        lines += [f"### 用例 `{cid}` {title}", "", fence(str(case.get("prompt", ""))), ""]
    return lines


def render_legacy(audit: dict[str, Any], task_routing_count: int) -> list[str]:
    legacy_txt = REPO_ROOT / "config" / "style_reference" / "prompts" / "style_ref_paragraph_classify.txt"
    lines = [
        "## §11 遗留与待清理（供系统作者决策；Sonnet 5 默认跳过）",
        "",
        f"1. **活跃孤儿节点（7 个）**：{'、'.join(f'`{n}`' for n in audit['orphan_active'])} —— 有模板/路由/注册但无调用点"
        "（其中两个 diagnosis 基节点是镜头模板载体属正常设计；三个 reference_* 是被 style_reference 子系统取代的遗留；"
        "`scene_quality_contract` 无模板、服务实际走 scene_auto_rewrite；`writer_reference_application_review` 是未接线的预留功能）。",
        "2. **休眠 ad-hoc 任务（2 个）**：`consistency_extract`、`causal_skeleton_refine` —— 提示词写好、无路由无注册，"
        "生产不可达；接线需在 models.yaml/节点注册或别名表补路由。",
        "3. **`DRAFTING_TEMPLATE_NAMES` 里的陈旧名（无对应模板，仅分类集合残留）**："
        + "、".join(f"`{n}`" for n in audit["stale_drafting"])
        + "。",
        "4. **疑似废弃文件**：`config/style_reference/prompts/style_ref_paragraph_classify.txt` —— 无任何代码加载"
        "（现行分类器用 yaml 的 anchor/bulk 双模板）。原文附下，供比对后删除或归档：",
        "",
        fence(legacy_txt.read_text(encoding="utf-8") if legacy_txt.is_file() else "（文件不存在）"),
        "",
        "5. **DB prompts 快照对账**：若系统曾激活 prompts 快照，`config/prompts.yaml` 与运行时真源会分叉——"
        "回写优化结果前先 `GET /api/v1/system-config/export/prompts` 对账（本文档 §1 已注明本次生成用的来源）。",
        "",
    ]
    return lines


def render_audit_section(counts: dict[str, Any], template_source: str) -> list[str]:
    return [
        "## §12 完整性自审计",
        "",
        f"- 生成命令：`cd backend && python -m novel_system.tools.export_prompt_handoff`（{_dt.date.today().isoformat()}）",
        f"- 模板来源：{template_source}",
        f"- prompts 模板：**{counts['templates']}** 个，全部出现在 §3–§8（脚本断言双向覆盖）",
        f"- 注册节点：**{counts['nodes']}** 个，全部出现在 §2 总表；未进单元的仅 "
        + "、".join(f"`{n}`" for n in ann.NO_PROMPT_NODES)
        + "（无提示词，§11 说明）",
        f"- models.yaml task_routing：**{counts['task_routing']}** 键，全部为注册节点或已说明的别名（`stylize`）",
        f"- 调用点：**{counts['call_sites']}** 处，锚点全部在当前源码命中（行号为生成时解析）",
        f"- Python 内联提示词：**{len(ann.INLINE_PROMPTS)}** 组（AST 字面量提取 + 函数内联逐字拷贝经源码包含性断言）",
        f"- 运行时片段：**{len(ann.FRAGMENTS)}** 组；评测用例：**{counts['eval_cases']}** 个",
        "- 负面证据（无 SDK 直连 / 无 embedding API / 前端无提示词 / RAG 注入无 LLM 等）见 §2 末尾",
        "",
        "以上任一数字与源码漂移时，生成脚本会以非零退出并列出差异——重新盘点后更新 "
        "`novel_system/tools/prompt_handoff_annotations.py` 再生成。",
        "",
    ]


def build_document() -> str:
    templates, template_source = load_templates()
    models_cfg = load_models()
    specs = llm_node_specs()
    task_routing = models_cfg.get("task_routing") or {}
    eval_cases = load_eval_cases()

    audit = run_assertions(templates, specs, models_cfg)

    counts = {
        "templates": len(templates),
        "nodes": len(specs),
        "call_sites": len(ann.CALL_SITES),
        "task_routing": audit["task_routing_count"],
        "eval_cases": len(eval_cases),
    }

    lines: list[str] = [
        "# 全系统 LLM 提示词优化交接文档",
        "",
        f"> 面向 Claude Sonnet 5 的自包含提示词优化工作底稿 · 生成于 {_dt.date.today().isoformat()} · "
        "机器提取 + 人工审计注释，勿手改本文件（改注释/源码后重新生成）。",
        "",
    ]
    lines += render_briefing(counts)
    lines += render_architecture(models_cfg, template_source)
    lines += render_inventory(specs, task_routing, audit)

    section_no = 3
    for batch in ann.BATCHES:
        units = [u for u in ann.UNITS if u["batch"] == batch["id"]]
        lines += [f"## §{section_no} {batch['title']}", "", batch["intro"], ""]
        for i, unit in enumerate(units, start=1):
            lines += render_unit(unit, templates, task_routing, f"{batch['id']}-{i:02d}")
        section_no += 1

    lines += render_fragments()
    lines += render_evals(eval_cases)
    lines += render_legacy(audit, audit["task_routing_count"])
    lines += render_audit_section(counts, template_source)
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="只跑断言，不写文档")
    parser.add_argument("--out", default=str(DOC_PATH), help="输出路径（默认 docs/prompt-optimization-handoff.md）")
    args = parser.parse_args()

    document = build_document()

    if _ERRORS:
        print(f"完整性断言失败（{len(_ERRORS)} 项）：", file=sys.stderr)
        for item in _ERRORS:
            print(f"  - {item}", file=sys.stderr)
        return 1

    if args.check:
        print("完整性断言全部通过（--check 模式，未写文件）。")
        return 0

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(document, encoding="utf-8")
    line_count = document.count("\n")
    print(f"已生成 {out_path}（{line_count} 行）。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
