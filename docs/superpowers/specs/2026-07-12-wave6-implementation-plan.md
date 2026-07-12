# Wave 6 实施计划：成本、模型独立性和运维可见性

> 设计：`docs/superpowers/specs/2026-07-10-ai-novel-outcome-governance-design.md`（v1.1）§5.7 / §5.8 / §6.1 / §6.3 / §10
>
> 纪律：Wave 严格顺序（Wave 0–5 已完成，见 `docs/outcome-governance-progress.md`）；测试先行；只改本 Wave 边界文件；独立提交。

## 0. 目标与完成门

**目标**：知道每一分质量提升花了多少成本。

**完成门**（设计 §8 Wave 6）：任意场景可解释 **总成本、各阶段占比、是否超预算、评审是否独立**。

设计 §8 Wave 6 五项实施内容：
1. 建立 token/价格聚合服务和成本页。
2. 配置 writer、critic、judge 独立角色槽（§5.7）。
3. 对同模型自评显式标记 `correlated_judge=true`。
4. 增加运行取消、预算耗尽和失败恢复测试。
5. 在编排信号面板显示降级槽、成本、预算和裁判独立性。

## 1. 代码基线核实（实施前已逐条验证）

- `LlmCall`（`db/models.py:707`）已有 `provider/model/node_id/step/project_id/scene_id/chapter_id/prompt_tokens/completion_tokens/total_tokens/latency_ms/error_code`，索引 `(scene_id, created_at)`。**无价格字段**（符合 §5.8「不向每条调用写死价格」）。
- Wave 3 已落 `SceneRunState.scene_token_budget`（5×基线）/`scene_tokens_used`（累计实际 usage）；`services/scene_budget.py` 有 `can_spend/record_usage/ensure_budget/estimate_baseline_tokens`。预算耗尽停新调用已实装（Wave 3）。
- 路由解析：`LLMNodeRunner(session).task_config(node_id)` 返回带 `.provider`/`.model` 的配置对象（DB `node_routing` → config `task_routing` → 回退）。离线（`llm_enabled=False`）也能从 `config/models.yaml:task_routing` 解析五个目标节点。
- 默认路由分工：writer 主力 `style_draft`=gpt-5（温 0.8）；critic 独立 `soft_qc`=gpt-5-mini（`auto_critique_llm` 经 `_AD_HOC_ROUTE_ALIASES` 别名到 `soft_qc`）；judge `near_final_acceptance_review`；extractor `style_profile_extract`=gpt-5-mini。→ **默认 writer≠critic 模型，天然独立**。
- `run_task`（auto_critique/event-extract 咨询路径）**不落 LlmCall、不计 scene 预算**，且 `NOVEL_SYSTEM_LLM_AUTO_CRITIQUE_ENABLED` 默认关闭。故成本聚合覆盖经 `run()` 的调用，批判咨询 token 为**已知离账口径边界**（记入剩余风险，本 Wave 不改 `run_task`，守 §5.8「基于现有 LlmCall 建立聚合，不复制调用日志」+ 范围纪律）。
- 无运行取消子系统（`scene_run_jobs`/`scenes.py` 无 cancel 端点）。顺序管线中「取消尚未开始的新节点」= 预算闸 `can_spend` 阻止新调用（Wave 3 已实装）。本 Wave **不新建取消子系统**（超范围、非完成门项），改以测试锁定「预算耗尽/失败即等价取消未开始节点，且已完成调用与草稿不回滚」（§5.8 硬行为 + §7 不变量 1/2/5/9）。
- `GET /api/v1/scenes/{id}/orchestration-signals`（`scenes.py:608`）已有 dispersion/criticality/token_budget/degraded_slots/foreshadow/theme/style_drift。本 Wave 增 `cost` + `judge_independence` 两节。
- **零 ORM 改动**：价格走 `config/pricing.yaml`；成本/口径/独立性全部由 `LlmCall`+`SceneRunState`+路由**运行时计算**，无新列 → 无 Alembic 迁移。`test_metadata_isolation.py` 漂移守卫应保持不变通过（回归纳入）。

## 2. 设计决策

### 2.1 价格快照（§5.8）
- 新增 `config/pricing.yaml`：`snapshots` 列表，每条含 `provider/model/effective_at/input_per_1k/output_per_1k/currency/is_estimate`；顶层 `default_estimate` 兜底。
- **占位价格全部标 `is_estimate: true`**：这是脚手架价格而非权威计费，诚实标注估算；运维可后续替换真实单价。→ 任何成本天然带 `is_estimate` 标记（符合 §5.8「无法获取时标记为估算值」精神）。
- 新增 `services/pricing.py`：`load_price_book()`（缓存 + 文件缺失硬回退）/`resolve_price(provider, model, at=None)`（取 `effective_at ≤ at` 的最新快照，未命中回 `default_estimate`）/`compute_cost(provider, model, prompt_tokens, completion_tokens)` → `{cost, currency, is_estimate, input_cost, output_cost, unit}`。

### 2.2 模型独立性（§5.7）
- 新增 `services/model_independence.py`。§5.7 五槽 → 代表节点：
  - `writer_primary` → `style_draft`
  - `writer_explorer` → `neutral_draft`
  - `critic_independent` → `soft_qc`（`auto_critique_llm` 实际路由目标）
  - `judge_advisory` → `near_final_acceptance_review`
  - `extractor_fast` → `style_profile_extract`
- 与既有 `ROLE_SLOTS`（drafting/review/extraction，供设置 UI）**是不同抽象，不改动它**。
- `resolve_slot(session, slot_id)` → 经 `task_config` 解析 `(provider, model)`；失败降级到 `get_llm_node_spec` 注册表默认；再失败 `degraded=True, provider/model=None`。绝不 500（读路径）。
- `judge_independence(session)`：解析 writer_primary + critic_independent（+ judge_advisory），`correlated_judge = (writer.provider==critic.provider and writer.model==critic.model)`；`independent = not correlated_judge`；生产默认要求 independent。返回 `{correlated_judge, independent, writer, critic, judge, reason, weight_hint}`（同源 → `weight_hint="downweight"` 降权提示，§5.7）。
- `observed_correlated_judge(session, scene_id)`：从该场景**已记录** LlmCall 行（writer 阶段 vs review 阶段实际 model/provider）判定 —— 对已跑场景比 config 更真实。
- **`correlated_judge=true` 的显式标记**（Wave 6 项 3）落在 `judge_independence`/`scene_cost.judge_independence` 结构中，随信号面板与成本摘要暴露、可查询。不改 QC issue 逐条发射（守范围；逐条 advisory issue 打标为后续）。

### 2.3 成本聚合（§5.8/§10）
- 新增 `services/cost_aggregation.py`。阶段分类 `classify_phase(node_id, step)` → `candidate_generation | quality_check | revision | review | other`（按 node_id/step 子串/精确映射；见实现表）。
- `scene_cost(session, scene_id)` 返回：
  - `total_cost` / `currency`（跨 provider 汇总以**费用**为准，§5.8）、`is_estimate`（任一价格估算即 true）。
  - `tokens_by_provider`：per-provider token（**不跨 provider 相加**，§5.8「分词器不同」）；顶层 `total_tokens` 仅在同 provider 语境下有意义，附 `cross_provider` 标记。
  - `phase_breakdown`：每阶段 `{tokens, cost, share, call_count}`（占比之和≈1）。
  - `budget`：`{budget, used, remaining, over_budget, usage_ratio, baseline, multiplier_used, run_policy}`（源自 `SceneRunState`，5× 上限使用率）。
  - `calibers`：三口径 `estimate/actual/billed`。`actual`=∑`total_tokens`（provider usage）；`billed`=actual 且 `is_estimate=true`（prompt-cache 折扣未接入，诚实标注等同实际）；`estimate`=`scene_tokens_used`（预算账目口径）。当前三口径多重合 → 记剩余风险（cache/预留落库后分化）。
  - `extra_cost`：`{failed_call_cost（error_code≠null 的调用）, low_dispersion_topup_cost（候选阶段超出 criticality 初始 N 的补候选）, repeat_qc_cost（QC 阶段第 2 次起）, total, retry_cost_ratio}`（§5.8「因低分散、失败重试和重复 QC 产生的额外成本」；启发式，已注释口径）。
  - `judge_independence`：观测口径（该场景实际 writer vs review 模型）+ config 口径回退。
- `chapter_cost(session, chapter_id)`：LlmCall 按 chapter_id 聚合 + 归档场景数（`FinalScene.status=='archived'` distinct scene）；`tokens_per_archived_scene`、`cost_per_archived_chapter`。
- `project_cost(session, project_id)`：项目内所有 scene（`SceneCard.project_id`）→ LlmCall（`project_id` 命中或 `scene_id ∈ 项目场景`）；章节 rollup + 书级 §10 指标 + `judge_independence`（config 口径）。

### 2.4 接口与前端
- 新增路由 `api/routes/cost.py`：`GET /api/v2/projects/{project_id}/cost-summary`（可选 `?scene_id=`/`?chapter_id=` 下钻）；`app.py` 挂载（单行）。
- 扩 `orchestration-signals`（`scenes.py`）：加 `cost`（scene_cost 摘要：total_cost/currency/phase shares/over_budget/is_estimate）+ `judge_independence`。各自 try/except 防面板整体失败（与既有信号一致）。
- 前端新 `frontend-react/src/ws-cost.jsx`（`WsCost` store + 成本页视图），接入 `ws-app` 高级/生产组导航（仿 `ws-eval`）。
- 扩 `ws-signals.jsx`：加成本 chip + 裁判独立性 chip（同源亮 `correlated_judge` 警示）。

## 3. 测试清单（先红后绿）

**后端**
- `tests/test_pricing.py`：resolve 取最新生效快照；未知模型 → default_estimate `is_estimate=true`；compute_cost 数学；currency 透传；文件缺失硬回退。
- `tests/test_model_independence.py`：五槽解析；默认 writer≠critic → `correlated_judge=false, independent=true`；构造同模型 DB 路由 → `correlated_judge=true, weight_hint=downweight`；task_config 失败降级到注册表默认；observed 口径从 LlmCall 判定。
- `tests/test_cost_aggregation.py`：phase_breakdown 占比、per-provider token 不相加、budget over/under（超预算标记）、calibers 三口径存在、extra_cost（失败重试/重复 QC/补候选归因）、chapter/project rollup 与归档指标。
- `tests/test_cost_summary_route.py`：端点返回信封；project/chapter/scene 三级下钻；空项目不 500。
- `tests/test_orchestration_signals_cost.py`：signals 含 `cost` + `judge_independence`；无 run state 时 `available:false` 不破。
- `tests/test_scene_cost_cancellation_recovery.py`（Wave 6 项 4）：预算耗尽停新调用但 `latest_valid_draft_row_id`+`FinalScene` 保留（等价取消未开始节点，不回滚）；mid-run LLM 失败保留最近有效稿；已完成调用/草稿不因后续失败回滚（§7 不变量 1/2/5/9）。

**前端**
- `src/ws-cost.test.jsx`：store 读取 cost-summary 成形；空/失败降级不抛；只读不写。
- 回归：`test_metadata_isolation.py`（漂移守卫，零列变更应不变通过）+ 相关既有套件。

## 4. 阶段分类映射（实现参考）

| phase | node_id/step 关键词 |
|---|---|
| candidate_generation | `neutral_draft` `style_draft` `long_form_continuation` `de_template` `*_blueprint` `chapter_story_architecture` `*_running` |
| quality_check | `hard_qc` `soft_qc` `near_final*` `chapter_near_final*` `scene_quality_contract` `style_ref_validate*` |
| revision | `style_patch` `soft_patch` `scene_auto_rewrite` `scene_literary_rewrite` `writer_*_revision` `writer_passage_patch` `auto_rewrite*` |
| review | `writer_deep_review` `writer_*_diagnosis` `chapter_audit_adjudicate` `literary_eval_live` `auto_critique*` |
| other | 其余（extraction/planning/snowflake/outline 等） |

## 5. 交付与证据
- 定向测试全绿（先红后绿证据）+ 全量回归 `-m "not chroma_integration"` 0 failed。
- vitest + build 通过。
- 真实产物：`.codex-run/wave6-cost-summary.json`（脱运行时可复算的成本摘要样本）。
- 更新 `docs/outcome-governance-progress.md`。
- 只提交本 Wave 文件的独立 Git 提交；输出命令/通过数/失败数/产物路径/剩余风险。

## 6. 剩余风险（预登记）
- auto_critique/event-extract 咨询 token 离 LlmCall 账（`run_task` 不落库，默认关闭）→ 成本聚合不含；本 Wave 不改 `run_task`。
- 三口径当前多重合（无 per-call 预留落库、无 prompt-cache 折扣数据）；结构已就位，精度待 cache/预留口径落库。
- 占位价格为估算（`is_estimate:true`），真实计费需运维替换单价。
- extra_cost 归因为启发式（补候选/重复 QC/失败重试按阶段计数近似）。
- 无真实取消端点：取消语义以预算闸等价覆盖；显式作者取消 UI 归后续。
- 前端成本页/信号 chip 浏览器走查归 Windows lane；store/取数逻辑 vitest 覆盖。
