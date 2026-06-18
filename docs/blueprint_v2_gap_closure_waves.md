# v2 蓝图差距闭合 · 两波实施记录

> 实施日期：2026-06-17
> 基线：`fe-align` 分支，全审计后确认 14/17 章节已有实质实现
> 方法：先全量审计（5 个并行代理覆盖后端/前端/三个同心圆），再按"影响 × 易度"排序分两波实施

本文档记录在「§17 验证出口」之前，针对审计发现的缺陷与提升点所做的两波闭合工作。每项均附蓝图条目、实现文件、测试覆盖。

---

## 审计结论速览

| 圈层 | 章节 | 闭合前 | 闭合后 |
|---|---|---|---|
| 第一圈·核心 | §2 事件溯源 | 90% | 95%（补卷级摘要层） |
| | §3 三轨检索 | 95% | 95% |
| | §4 规划结构 | 85% | 90%（补逆向骨架 LLM 精炼） |
| | §5 伏笔系统 | 95% | 95% |
| 第二圈·放大 | §6 分级选择 | 90% | 98%（分散度信号外显 + 二阶代价缓解） |
| | §7 抗趋均值采样 | 0% | 70%（API 层采样参数接入） |
| | §8 批判修订 | 95% | 95% |
| | §9 风格系统 | 80% | 95%（Lifetime 接线 + 漂移"展示"修正） |
| 第三圈·精修 | §10 节奏 | 100% | 100% |
| | §11 角色深度 | 100% | 100% |
| | §12 主题 | 100% | 100%（预算外显） |
| | §13 七步流水线 | 100% | 100% |
| | §14 人机协作 | 90% | 90% |
| | §15-16 校验诚实 | 70% | 90%（混合式一致性 + 约束强度滑块） |

---

## 第一波（6 缺陷 + 2 增强）

### Defect C · LifetimeExpressionRegistry 接入主路径（§9）
全书级禁用表达列表此前已实现但未接线。`bundle_builder._literary_freshness_budget` 现调用
`LifetimeExpressionRegistry.get_lifetime_avoidance_guidance()`，将全书已用比喻/开头/口癖注入
`budget["lifetime_banned_expressions"]`。解决 50+ 场景后窗口滑出导致的表达复用。

### Defect A · 抗趋均值采样参数接入（§7）
`LLMRequest` 新增 `frequency_penalty`/`presence_penalty`/`top_p`；OpenAI Responses + Chat
两条 adapter 路径注入（仅非 None）；`llm_task_runner._build_request` 从 task_config 读取；
`config/models.yaml` 的 `stylize` 默认 `frequency_penalty=0.3, presence_penalty=0.15`。
架构差异说明：蓝图假设本地模型（min-p/XTC/DRY），项目走 API；接入 API 原生支持的惩罚项是零成本补偿。

### Enhancement 2 · 过渡场景概率提升（§6.4）
`classify_scene` 新增 `consecutive_transition_count`；连续 3+ 过渡场景后下一个自动升为 standard
（N=3, critique=True）。`orchestrator._consecutive_transition_count` 查询前置场景计数。
缓解"关键场景人味高峰 + 过渡场景温吞平原"的新型 AI 味节奏。

### Defect F · 场景约束强度滑块（§16）
`SceneCard.constraint_intensity`（0.0 自由 / 1.0 全约束 / NULL 自动）。`classify_scene` 据此
覆盖临界度：≤0.2→transition，≥0.8→critical，中间→standard。把"呼吸缝隙"从隐性成本优化
升为一阶可调旋钮。

### Defect D · 分散度/临界度信号外显（§6）
`SceneRunState` 新增 `candidate_dispersion_score`/`criticality_level`/`criticality_reasons_json`；
`scene_generation` 写入分散度；`orchestrator` 写入临界度；`GET /style-candidates` 响应新增
`dispersion_score`/`dispersion_signal`/`criticality`。

### Defect B · 漂移修正"告诉"→"展示"（§9）
蓝图核心洞察"给模型看比告诉模型有用"。`style_drift_detector` 新增 `_DIMENSION_PREFERRED_PTYPES`
（18 维→段落类型映射）+ `drift_corrective_ptype_priority()` + `format_drift_dimensions_for_bundle()`；
`injection._render_few_shot` 接受 `drift_ptype_priority` 优先选取漂移维度相关样例；经
`orchestrator`（存 `recommendation_json`）→ `bundle_builder`（提取）→ `scene_generation`（设入
`InjectionService.drift_ptype_priority`）端到端打通。

---

## 第二波（2 增强 + 2 提升 + 信号端点）

### E5 · 卷级摘要层（§2 摘要塔补全）
长篇（50+ 场景）需要章级之上的远景氛围层。`VolumeSummary` 模型 + `Aggregator.aggregate_volume_summary()`
+ `maybe_aggregate_volume()`（每 `VOLUME_CHAPTER_SPAN=5` 章在边界滚动）。`orchestrator` 章节归档时触发。
`bundle_builder._latest_volume_summary` 注入，**显式标注"仅供语气延续，严禁当作事实来源"**——
严守蓝图"事实从日志查，氛围从摘要读"。

### E4 · ChapterMemory 事实/氛围标注
`ChapterMemory.memory_kind`（mixed/factual/atmosphere，默认 mixed 向后兼容）。为摘要塔的
事实/氛围分离奠定字段基础。

### E1 · 混合式一致性校验（§15 诚实边界）
蓝图明确警告"用不可靠验证不可靠"的循环依赖。实现刻意保守：
- 关键词层（`check_consistency`）保持权威**阻断**层。
- `check_consistency_llm` 至多 1 次 LLM 调用，仅在已投影硬事实上，结果标 `source="llm_flag"`
  → 建议性（人工抽检），**绝不自动阻断**。无 runner 时退化为纯关键词。
- `ConsistencyViolation.source` + `ConsistencyReport.blocking_violations` 区分阻断/建议。
- `qc_engine` 据 source 分级（keyword→high 阻断，llm_flag→medium 建议）。
捕获"双手握剑"（断臂时）这类关键词漏判，又不让幻觉抽取器误杀生成。

### E3 · 逆向因果骨架 LLM 精炼（§4）
`reverse_causal_skeleton.refine_skeleton_with_llm`（opt-in）：问"要让这步可信，之前必须发生什么"，
返回**建议性** `CausalGap` 列表 + `format_causal_gaps_for_prompt`。**不修改骨架**——
幻觉精炼器永远无法静默改写因果主干。

### 编排信号聚合端点（§0 "把决策浮出来"）
`GET /api/v1/scenes/{id}/orchestration-signals` 一次聚合：分散度+临界度（§6）、伏笔欠债（§5）、
主题表达预算（§12）、活跃风格漂移修正（§9）。各子项 best-effort，单项失败不拖垮整个面板。
前端 `ws-signals.jsx`（`OrchestrationSignals` 组件）防御式消费——无数据/无场景/取数失败时不渲染，
不影响原型视图与 smoke 测试。挂载于写作视图场景卡下方。

---

## 测试覆盖

- `tests/test_blueprint_v2_wave2.py`：22 用例覆盖卷级摘要、概率提升、约束强度、混合一致性、
  骨架精炼、信号端点。
- 第一波改动由既有 `tests/test_blueprint_v2_modules.py` + `test_consistency_validation.py` +
  `test_scene_generation.py` 等覆盖回归。
- 全量后端套件 + React 生产构建均绿。

## 设计原则一致性

所有"LLM 增强"层（混合一致性、骨架精炼、漂移语义评判）统一采用 **opt-in + 无 runner 即退化 +
失败不抛 + 建议不阻断** 的保守模式，与既有 `llm_auto_critique` 一致，严守 §15「校验的诚实边界」。
