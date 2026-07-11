# Wave 3 实施计划：Best-of-N 人类终选与 5× 预算

> 设计依据：`docs/superpowers/specs/2026-07-10-ai-novel-outcome-governance-design.md` v1.1 §4.4/§4.6/§5.5/§6.1/§6.3 + Wave 3 条目
>
> 纪律：测试先行；动模型必须「模型 + Alembic 迁移 + 漂移守卫」三件套；
> Wave 2 完成门已过（提交 84762b4，全量 1457 passed + e2e PASS）。
>
> 完成门：**关键场景未选择前不可归档；选择后可安全续跑；总 token 不超过基线 5×。**

## 1. 现状事实表（2026-07-11 逐项核实）

| # | 事实 | 位置 |
|---|---|---|
| F1 | GET style-candidates 按 `adversarial_score` 降序返回并携带分数与 `selected` 标记——直接复用违反 §5.5 盲化要求（v1.1 §2.3 已预警） | `routes/scenes.py:492-545` |
| F2 | select 端点已走幂等，但**无终选锁定**：重复提交不同 row_id 直接覆盖 `current_style_draft_row_id`；无 HumanReviewEvent 记录、无 blinded_order/耗时 | `routes/scenes.py:648-688` |
| F3 | 关键场景不暂停：orchestrator 生成候选后自动选 adversarial #1 继续归档，仅在 near-final 之后建 `critical_scene_human_gate` 事件（时点不符 §5.5 顺序：终选应在批判修订/硬检查**之前**） | `orchestrator.py:156-172,317-346` |
| F4 | 低分散补救是一次性爆发：温度加宽整批重试（+N）+ 多策略发散（+3），单场可产出 ~9-11 个候选、无预算约束——违反 Wave 3 项 5「渐进补候选」 | `scene_generation.py:399-547` |
| F5 | `SceneCriticality.best_of_n` 是一步到位的 5/3/1，无「先 N=3 补到 5 / 先 N=2 补到 3」的初始/上限区分 | `scene_criticality.py:116-149` |
| F6 | `SceneRunState` 无 `run_policy`/`scene_token_budget`/`scene_tokens_used` 列（Wave 2 的 run_policy 是请求级）；`attempt_budget`（次数）已存在，双轨并存不动 | `db/models.py:528-556` |
| F7 | `LlmCall` 已记 prompt/completion/total_tokens（`_persist_call`，成功与失败行都写）；`task_config.max_output_tokens` 可得；prompt `token_budget.estimated_input_tokens` 可得——预算记账的原料齐备，无聚合 | `llm_task_runner.py:435-470,348` |
| F8 | `_prepare_state_for_run` 每次 run 重置计数器——新增预算字段**不得**进入该重置（§7.12 预算不可被自动流程重置） | `orchestrator.py:_prepare_state_for_run` |
| F9 | 恢复 bundle 所需数据在 `SceneBundle`（frozen_snapshot_json + bundle_snapshot_hash）——resume 可重建 `{bundle_id, bundle_snapshot_hash, snapshot}` | `db/models.py:596-606` |
| F10 | FE `lib/client.js` 自动附 X-Idempotency-Key；`ws-signals.jsx` 已读 orchestration-signals 渲染分散/关键度面板（预算展示的挂点）；`author_state=awaiting_author_choice` 映射已存在（critical_scene_human_gate） | `client.js:86-100`、`ws-signals.jsx`、`author_state.py` |
| F11 | 离线（llm 未启用）`_best_of_n_count` 恒 1——关键场景在离线下是单候选终选（§5.3 允许「至少一份候选」）；测试需以可控 fake usage 驱动预算断言 | `orchestrator.py:_best_of_n_count` |

## 2. 架构决策

- **D1 · 三件套落列**：`SceneRunState` 增 `run_policy: str|None`、`scene_token_budget: int|None`、`scene_tokens_used: int default 0`。迁移带存在性守卫（沿 20260711_0061 模式）；漂移守卫保持通过。`_prepare_state_for_run` 不重置这三列；run_scene 写入本次 effective run_policy。
- **D2 · 预算服务**（新 `services/scene_budget.py`）：
  - 单发基线（§4.6）：`estimate_baseline_tokens(session, snapshot)` = PromptBuilder 按 `style_draft` 构建的 `token_budget.estimated_input_tokens` + 该节点 `task_config.max_output_tokens`（任一不可得回退常量 4000/2400）。确定性检查计 0。
  - `ensure_budget(state, baseline)`：`scene_token_budget` 为空时置 `5 × baseline`，从不收缩；`record_usage` 由 `llm_task_runner._persist_call` 钩子完成——凡带 scene_id 且存在运行态行的调用（成功/失败）累计 `scene_tokens_used += total_tokens`（usage 缺失记 0，§5.8 估算口径记入剩余风险）。
  - `can_spend(state, estimated)`：顺序管线内「先预留后发起」退化为逐次前置检查（无并发生成，竞态超支不适用——记边界）。可选支出（补候选/批判/补丁/near-final 重写）过闸；基线必经调用不拦但照常计数（§5.8 预算耗尽停止**新**调用）。
  - 显式追加：`POST /api/v1/scenes/{id}/budget/topup`（作者动作，OperationLog 审计；自动流程无任何加预算路径——§7.12）。
- **D3 · 渐进补候选**（F4/F5）：`SceneCriticality` 拆 `initial_best_of_n`/`max_best_of_n`（critical 3/5、standard 2/3、transition 1/1）。`generate_style_draft_candidates` 的低分散补救改为**逐个**补候选：`while dispersion<0.15 and n<max and can_spend(baseline)`，每次 1 个（温度加宽与发散前缀轮换作为逐个候选的变体来源，不再整批爆发）；补到 max 即停（关键场补满 5 = 本场放弃批判与补丁，§5.5 预算优先级固定）。不删除低分候选（§4.4）。
- **D4 · 关键场景暂停（时点前移）**：关键场景（`criticality.human_gate`）候选生成后：确定性坏稿淘汰（空文本 + 来源安全 Q0 扫描；不按分数删）→ 建终选 gate 事件（`HumanReviewEvent`，details=`{gate_type:"style_candidate_selection", candidate_row_ids, blinded_order(随机置换), decision_status:"awaiting", tokens_used}`）→ `scene_status="awaiting_candidate_selection"`（新词值，投影 `awaiting_author_choice`、can_archive=False）→ 早退（携投影契约）。原 near-final 后的 `critical_scene_human_gate` 块被本 gate 取代（终选后不再二次人工门，§5.5 顺序）。标准场景保留机器下限自动选择不暂停。
- **D5 · run_scene 尾部抽取 + resume**：把「批判修订 → 软 QC → near-final → 严格停点 → 归档」抽为 `_finalize_after_style(...)`；`run_scene` 与新 `resume_after_selection(scene_id)` 共用。resume 前置校验：状态=awaiting + 终选事件 decision_status="selected"，否则 409 `SELECTION_REQUIRED`；bundle 从 `SceneBundle` 行重建（F9）；批判/补丁在剩余预算内按 §5.5 优先级执行（补满 5 候选后跳过）。选中稿即软 QC/批判的输入（§4.3 select 已维护 latest_valid）。
- **D6 · 盲化视图**（F1）：GET style-candidates 默认盲化——存在终选 gate 时按 `blinded_order` 输出全文，剥离 `adversarial_score`/`selected`/模型元数据；`?include_scores=true`（作者主动展开）附分数**不改顺序**；无 gate（标准场/历史）保留旧诊断形状并标 `blinded:false`。
- **D7 · 终选锁定与重开**（F2）：select 端点绑定 gate 事件——已 selected 且同 row_id → 幂等返回；不同 row_id → 409 `SELECTION_LOCKED`；`POST /style-candidates/reopen` 显式重开（decision_status="reopened" + details 追加审计历史）后方可改选。select 记录 `selected_row_id/decided_at/duration_ms?/no_clear_difference?`（FE 可传）。无 gate 的旧路径（标准场直接 select）首次 select 时补建已决 gate（锁定语义对所有场生效，§6.3）。
- **D8 · adopt 守卫**：`author_state=awaiting_author_choice` → adopt-current 409 `SELECTION_REQUIRED`（完成门「未选择前不可归档」双入口封死：管线暂停 + adopt 拒绝）。
- **D9 · FE 终选视图**：`ws-scene-run.jsx` 增 `scnCandidates/scnSelectCandidate/scnResumeAfterSelection`（盲化列表 → 整稿选择 → 续跑 → 重拉状态）；`ws-scene.jsx` 在 gate.authorState=awaiting_author_choice 时渲染候选终选面板（全文逐稿阅读 + 「选这稿」+「无明显差异」快捷）；`ws-signals.jsx` 面板加 token 预算行（orchestration-signals 端点补 `token_budget` 节）。并排/句段差异定位为后续增强（§5.5 允许，不阻塞第一阶段）。

## 3. 改动清单

后端（`backend/`）：
1. `db/models.py` + `alembic/versions/<new>_wave3_run_policy_budget.py` — D1 三件套
2. `services/scene_budget.py`（新） — D2
3. `services/llm_task_runner.py` — `_persist_call` 累计钩子
4. `services/scene_criticality.py` — initial/max 拆分
5. `services/scene_generation.py` — 渐进补候选（预算闸）
6. `services/orchestrator.py` — D4 暂停 / D5 尾部抽取 + resume / 预算初始化与批判补丁闸
7. `services/author_state.py` — `awaiting_candidate_selection` 映射
8. `api/routes/scenes.py` — D6 盲化 / D7 锁定+重开 / resume-after-selection / adopt 守卫 / budget topup / orchestration-signals 预算节
9. `tests/test_candidate_selection_gate.py`（新）+ `tests/test_scene_token_budget.py`（新）+ 受影响既有断言更新

前端（`frontend-react/src/`）：
10. `ws-scene-run.jsx` — 三个 API 函数 + gate 透出候选待选态
11. `ws-scene.jsx` — 候选终选面板
12. `ws-signals.jsx` — 预算行
13. `ws-scene-run.test.jsx` 扩展（盲化取数/选择锁定/续跑，先红后绿）

文档：14. 本计划；15. `docs/outcome-governance-progress.md` Wave 3 段。

## 4. 测试先行顺序

1. `tests/test_candidate_selection_gate.py`（先红）：关键场（constraint_intensity=0.9）run → `awaiting_candidate_selection` + 无 FinalScene + gate 事件带 blinded_order/candidate_row_ids；adopt 409 SELECTION_REQUIRED；盲化 GET（无分数、按 blinded_order、全文）与 `include_scores` 不重排；select 锁定（同选幂等/异选 409）+ reopen 后可改选留审计；resume 前置校验 409；select→resume→archived 且终稿=选中稿；标准场不暂停仍自动归档。
2. `tests/test_scene_token_budget.py`（先红）：run 后 `scene_token_budget=5×baseline`、fake usage 累计入 `scene_tokens_used`；重跑不重置（累计）；`can_spend` 拒绝时不再补候选/批判/补丁（构造小预算断言无新增调用）；补满 max 候选后跳过批判与补丁；topup 端点扩容+审计，自动路径无扩容。
3. 后端实现 → 定向绿 → 漂移守卫 + 既有断言更新 → 全量回归。
4. FE vitest 先红：盲化列表渲染序、select 提交与锁定 409 呈现、resume 后重拉。
5. FE 实现 → vitest 绿 → 构建。
6. 完成门自证（隔离后端 e2e：关键场暂停 → adopt 409 → select → resume → archived；预算字段可见）。

## 5. 本机验证命令

```bash
cd backend && .venv/bin/python -m pytest tests/test_candidate_selection_gate.py tests/test_scene_token_budget.py tests/test_metadata_isolation.py -q
cd backend && .venv/bin/python -m pytest -q -m "not chroma_integration"
cd frontend-react && NODE_OPTIONS="--require ./crypto-polyfill.cjs" npx vitest run
cd frontend-react && NODE_OPTIONS="--require ./crypto-polyfill.cjs" npm run build
# 迁移验证（隔离库）+ e2e：alembic upgrade head → 关键场 run/select/resume 全链路
```

## 6. 完成门自证

- 「关键场景未选择前不可归档」：pytest（管线暂停无 FinalScene + adopt 409）+ 隔离后端 e2e 实跑同断言。
- 「选择后可安全续跑」：select→resume→archived，终稿内容=作者选中候选（非机器 #1）；resume 幂等安全（重复调用不重复归档）。
- 「总 token 不超过基线 5×」：可控 fake usage 下全管线跑完断言 `scene_tokens_used ≤ scene_token_budget`；预算闸拒绝时优先级顺序（候选>硬检查>批判>补丁）由「小预算场景跳过批判/补丁但保留候选」测试证明。

## 7. 边界与剩余风险

- token 三口径（估算/实际/计费）本 Wave 只落「实际」累计与估算判定的最小闭环；prompt-cache 计费折扣与跨 provider 分槽累计归 Wave 6 成本聚合。
- 并发候选生成不存在（顺序管线），预留-结算的竞态语义未实装——若 Wave 6+ 引入并行生成需回补。
- 离线模式关键场为单候选终选（F11）；多候选盲化的真实模型走查归 Windows lane。
- 并排对比/句段差异定位 UI 为后续增强（§5.5 明示不阻塞）；本 Wave 交付逐稿全文阅读 + 整稿选择。
- 旧 `critical_scene_human_gate`（near-final 后）被终选 gate 取代——存量停在该状态的场按既有 human-review resolve 通道收尾，不迁移。
