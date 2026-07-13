# AI 小说系统结果闭环治理：完成度深度评估与二次收敛清单

> 评估日期：2026-07-13
>
> 评估基线：`main` / `ab1550f`
>
> 原设计：`docs/superpowers/specs/2026-07-10-ai-novel-outcome-governance-design.md`（v1.1）
>
> 实施账本：`docs/outcome-governance-progress.md`
>
> 当前结论：**工程底座已大幅补齐，但原设计的结果级闭环尚未完成；当前不可宣告整体完成，不满足五章发布门，也不满足 30 章耐久门。**

---

## 1. 执行结论

本轮不能用“Wave 0–6 已完成、Wave 7 接近完成”概括真实状态。更准确的表述是：

1. **代码和自动测试层进展显著。** 唯一正文真值、作者状态、Q0–Q3 分级、候选终选、POV 投影、实验数据模型、成本聚合、备份与孤儿盘点等基础能力已存在，并有较强的单元/集成测试覆盖。
2. **北极星 UI 闭环没有合上。** 当前五章 harness 仍把雪花规划、物化、场景执行、归档和章节聚合记录为 API lane，把候选终选写死为 `missing`；判定器要求六阶段全部为 `ui`，所以现有 harness 在结构上必然触发 `NORTHSTAR_PHASE_NOT_UI`。
3. **五章真实结果门没有通过。** 仓库中没有本轮 5 章 × 3 场、15/15 服务端归档、清缓存与重启恢复、Q0/Q1=0、来源泄漏=0 的新鲜可复算产物。
4. **Wave 5 只完成实验基础设施，没有完成“30 组人类盲评”。** 进度账本引用的是合成 30 对、合成投票；它能证明统计代码工作，不能证明读者偏好，更不能证明 Best-of-N 值得默认 3–5 倍候选成本。
5. **5× token 预算不是硬上限。** 当前只对部分可选调用做 `can_spend` 前置检查；辅助 `run_task` 不落 `LlmCall`，provider usage 缺失按 0 记，且没有真实预留/结算账户，因此存在漏记和实际调用后超限。
6. **来源安全仍有两处直接违约。** 未声明发送权却选择云端策略仍被测试明确放行；不可信文本封装只接入最终 few-shot/RAG 注入，风格抽取、补证和预览仍把原文/引文直接 JSON 序列化进 LLM user prompt。
7. **Wave 7 不是完成态。** 真实 30 章运行、重启恢复、p95、FK 实际启用、大文件拆分和路由级懒加载均未闭环；现有耐久通过产物是合成数据。
8. **证据链不可完整复算。** 进度账本引用的 `.codex-run/wave*` 产物被 `.gitignore` 排除，当前拉取后的工作区没有这些文件，审查者只能相信文字摘要，不能从仓库复算历史完成门。

因此，当前合理状态应定义为：

| 维度 | 状态 | 说明 |
|---|---|---|
| 核心工程能力 | **大部分已实现** | Wave 1–4 的主干代码较完整，Wave 5–7 的基础设施已铺设 |
| 自动测试可信度 | **较高但偏结构验证** | 大量测试证明函数、路由和离线管线；不能替代真实模型、人类选择和浏览器全链 |
| UI 北极星闭环 | **未完成** | harness 本身仍记录 API/missing lane |
| 五章发布门 | **未通过/无新鲜证据** | 没有 15/15 真实归档与恢复产物 |
| 30 组人类盲评 | **未执行** | 只有合成报告 |
| 30 章耐久门 | **未执行** | 只有判定器和合成样本 |
| 生产默认策略证据 | **未完成** | 未以真实人评结论驱动 Best-of-N 默认开关 |
| 整体设计状态 | **未闭环，不可发布** | 不能把“基础设施完成”写成“结果完成” |

---

## 2. 评估口径

### 2.1 五级证据模型

本评估不再用单一“完成/未完成”描述复杂 Wave，而采用以下证据等级：

| 等级 | 定义 |
|---|---|
| L0 | 未实现，只有设计或待办 |
| L1 | 代码/接口/工具存在，但缺少充分验证 |
| L2 | 自动单元或隔离集成测试通过 |
| L3 | 真实浏览器、真实服务、真实持久化的端到端门禁通过 |
| L4 | 真实模型/真人数据证明结果，并已按结果设置生产默认策略 |

原设计的“完成门”和“发布门”多数要求 L3 或 L4。仅达到 L1/L2 时，不得写成结果闭环完成。

### 2.2 本轮实际核查范围

- 拉取 `origin/main`，从 `39e0544` 快进到 `ab1550f`，工作区拉取前后均无冲突。
- 逐节对照原设计 §2–§15、Wave 0–7 实施计划和进度账本。
- 静态核查新增后端、前端、迁移、harness、实验、成本、安全和运维路径。
- 新鲜运行后端非 Chroma 全量测试、React Vitest 和生产构建。
- 核查 Alembic head、本机默认数据库版本、FK pragma、必需新列和实验表。
- 核查进度账本所引用证据是否能在当前仓库复算。

### 2.3 本轮新鲜验证结果

本节只记录本次评估实际执行的结果，不复述历史账本中的通过数：

- 后端：`python -m pytest -q -m "not chroma_integration"` 新鲜通过，`1590 passed, 4 skipped, 17 deselected`，耗时 563.09 秒。
- React：`npm test` 新鲜通过，`14` 个测试文件、`89` 项测试全部通过。
- 构建：`npm run build` 新鲜通过；当前主 JS 为 1,237.29 kB，Vite 报告 gzip 385.35 kB。虽然已低于设计中“主 chunk <500KB gzip”的体积目标，但仍是单一主 chunk，Vite 同时给出 chunk 大于 500 kB 的拆分警告，路由级懒加载没有落地。
- Alembic：代码 head 为 `20260712_0064`；实际默认库已在 C0 闭环中从 `20260618_0059` 升级到 `20260712_0064`，新鲜 preflight 报告 `ready=true`、`integrity=ok`，必需新列和实验表均已存在。
- C0 迁移前的已验证备份仍保留 `20260618_0059` 历史状态，SHA-256 为 `804fc4e01237d77eacf83b7671f90ab50fdd5db985a2356ba74666240dec31b3`；副本演练与 actual 复核均到达 `0064`。
- 当前默认库孤儿盘点为 0；`PRAGMA foreign_keys=0`，FK 是否启用仍待正式结论。

说明：默认库版本落后的可运行态阻断已关闭。可审查索引见 `docs/superpowers/evidence/20260713-c0-manifest.json`；其中 provenance 为 `offline`，复核二进制 artifact 时必须以本机 `.codex-run/governance-c0/20260713-c0` 作为 `artifact_root`，并使用 `validate --profile c0`。只有 C0 profile 才强制八个 required gates 全部存在；generic validate 保留给未来 manifest 兼容，不能作为 C0 验收通过依据。该证据只关闭工程运行门，不推进真实模型门或发布门。

**历史证据边界：** actual 迁移执行前的进程安全检查没有持久化进程快照，因此不能由当前 manifest 追溯证明迁移当时没有服务占用。`RUNTIME_PROCESS_CLEAR.details.report.scope="verification_time_only"` 只证明本轮证据复核时未发现命令行同时含 `uvicorn` 与 `novel_system` 的进程。C0 运行真值由可复核的三组事实构成：已验证的迁移前 `0059` 备份、当前 actual `0064` 且 `ready=true` / `integrity=ok`、actual 孤儿数 0。

**Validator threat model：** validator 面向单用户本地工具的信任边界，验证 artifact 存在及 hash、本地 command 时间与 expected exit、以及已出现的已知 C0 gate details 的结构和值，用于发现误标、缺失或意外损坏；只有启用 `--profile c0` 才进一步证明八个 required gates 完整。Generic mode 保留未来兼容，不能作为 C0 验收。Validator 不是加密签名或防篡改证明，不能阻止有意伪造 manifest、命令记录或配套 artifact；审查者仍须信任执行工作站、Git 历史及用于复核的本地 artifact 来源。CLI validate 是 manifest 之外的外部验收动作，不写回 commands 或 gates。

---

## 3. Wave 0–7 深度完成度

| Wave | 已做好 | 证据等级 | 没有闭环的关键点 | 本轮判定 |
|---|---|---:|---|---|
| Wave 0 结果门禁 | Outcome Gate 能识别空稿、缺场、假评分和非 UI lane | L2 | harness 没有随 Wave 1–3 反向接回真实 UI；候选终选仍写死 `missing` | **部分完成** |
| Wave 1 正文真值与归档 | `FinalScene` 权威态、`author_state`、latest-valid、adopt、后端成稿聚合已实现；默认库 schema 已到 `0064` | L2 | 没有真实浏览器清缓存/重启恢复门 | **工程主干完成，结果门未过** |
| Wave 2 QC 分级 | Q0–Q3、确定性复核、软问题不丢稿、reliable/strict 语义已有测试 | L2 | 没有“当前真实模型旧三章复跑”证据；真实波动和坏稿归档率未知 | **工程主干完成，真实门未过** |
| Wave 3 Best-of-N | 候选盲化、锁定、重开、resume、React CandidatePicker 和预算字段已存在 | L2 | harness 不走该 UI；预算非硬上限；真实多候选走查缺失；未有人评却已默认标准场 N=2、关键场 N=3 且关键场强制终选 | **部分完成，默认策略证据不足** |
| Wave 4 POV 投影 | 两个主要状态注入槽和 finding 回灌脱敏已有实现与 golden 测试 | L2 | 无真实悬疑 LLM 对照；收益依赖显式知识标注质量；写侧事件提取默认关闭 | **工程完成度较高，效果未证** |
| Wave 5 质量实验室 | 实验表、路由、盲化、投票、统计报告和最小 UI 已实现 | L2（机制）/L0（真人结果） | 30 对和 21/30 产物是合成；真人 30 非平局未执行；没有把真实结论写回生产默认策略 | **基础设施完成，目标未完成** |
| Wave 6 成本与独立性 | 价格配置、成本聚合、成本页、独立性信号已实现 | L1–L2 | 辅助调用漏账、价格全估算、计费口径近似实际、无真实取消、跨 provider 预算仍全局累计、指标体系缺失 | **部分完成** |
| Wave 7 耐久/安全/收敛 | 备份工具、孤儿工具、部分不可信封装、耐久判定器、演示标记已实现 | L1–L2 | 30 章未跑；FK 未开；大文件未拆；路由懒加载未做；来源安全仍有直接缺口 | **进行中，不得标完成** |

### 3.1 值得保留的成果

以下能力已经形成可继续收敛的工程基础，不应推倒重来：

- `author_state` 与 latest-valid 使“跑完无稿”“有稿警告”“硬阻断仍保稿”可以被统一表示。
- `quality_classifier.py` 将 LLM 提案与确定性复核分开，修复了软审美问题断头的核心缺陷。
- 候选终选 API 已具备盲化顺序、整稿、幂等、选择锁定和显式重开语义。
- POV 投影覆盖了原审计发现的两个主要秘密泄漏槽，并处理了 QC finding 回灌旁路。
- 实验通道与生产 `FinalScene` 隔离，统计逻辑能处理平局、唯一快照和精确二项检验。
- 成本服务已建立场/章/书聚合骨架，模型独立性也能输出 configured/observed 两种信号。
- 数据库在线备份、校验、恢复和孤儿盘点工具具备较好的可测性。

这些成果证明方向正确，但它们是“闭环所需零件”，不是“闭环已经通过”的替代证据。

---

## 4. P0：必须先修的结果与安全缺口

### P0-1 北极星 harness 与现有 UI 脱节

**证据**

- `scripts/playwright_audit_summary.py:307-320` 要求六阶段全部为 `ui`。
- `scripts/run-currentdb-three-chapter-qa.cjs:1157-1169` 仍把 `scene_execution` 记为 `api`、`candidate_selection` 记为 `missing`、`archive` 记为 `api`。
- `scripts/run-currentdb-three-chapter-qa.cjs:1251-1254` 把章节聚合记为 `api`。
- 同一仓库的 `frontend-react/src/ws-scene.jsx:879` 已有 CandidatePicker，说明缺口不是“没有 UI”，而是“验收工装没有使用 UI”。

**影响**

当前无法证明作者能从空白项目经 UI 拿到可恢复正文；API 深链可能绕过前端映射、状态同步、选择交互和缓存恢复缺陷。

**完成条件**

- 六阶段全部由浏览器交互触发并记录为 `ui`。
- API 仅用于断言服务端真值，不用于替代点击、填写、终选、归档和成稿查看。
- 删除 harness 中“候选终选到 Wave 3 才交付”的过期硬编码说明。

### P0-2 五章真实发布门完全没有新鲜通过证据

**缺失证据**

- 原创 5 章 × 3 场的 15/15 非空服务端正文。
- 15/15 后端权威 `archived`。
- 5/5 章节聚合与场景拼接一致。
- 至少 3 个关键场真实进入作者终选。
- 清 localStorage、重启后端和刷新浏览器后的恢复。
- Q0/Q1 未解决项为 0、来源泄漏为 0。
- 15 场中至少 14 场首次任务产出可编辑正文。
- 每个关键场实际 token 不超过 5×。

**完成条件**

原创 lane 与授权/公版参考文本 lane 都必须产出带正文、快照哈希、路由、token、耗时、状态、来源安全和恢复证据的归档包；任一红线失败即整轮失败。

### P0-3 30 组真人盲评未执行，默认高成本策略却已启用

**证据**

- `docs/outcome-governance-progress.md:464-469` 明确承认使用合成 pair/投票。
- `scene_criticality.py` 对标准场默认 `initial_best_of_n=2`，关键场默认 `initial_best_of_n=3` 且 `human_gate=True`。
- 仓库没有基于真实报告的 Best-of-N 生产开关，也没有从 `keep_optional/upgrade_to_default` 决策更新默认策略的路径。

**问题**

统计设施通过与文学增益成立是两件事。合成 21/30 只能验证阈值计算，不能证明真实作者偏好。当前实际行为相当于在未获得人评证据前就让标准/关键场承担多候选成本，与原设计“未通过人评的高成本模块默认可选”不一致。

**完成条件**

- 30 个不同冻结快照、30 个非平局真人选择、可复算报告。
- 报告中明确 provenance 为真人，禁止合成票进入生产决策。
- `upgrade_to_default` 才允许关键场默认 Best-of-N；`keep_optional` 时默认单发，并由作者显式开启。
- 消融升级默认必须另用一批新的 30 个非平局快照复验。

### P0-4 5× token 预算可漏记、可超限

**证据**

- `scene_budget.py` 只把补候选、批判、补丁和 near-final 重写定义为受 `can_spend` 约束的“可选支出”，基线生成不拦。
- `llm_task_runner.py:278-309` 的 `run_task` 直接调用 client 并返回，不写 `LlmCall`，auto critique 和事件抽取因此不进成本账。
- `llm_task_runner.py:480-487` 在 usage 缺失时按 0 累计。
- `can_spend` 只是读取 `scene_tokens_used + estimated`，没有原子预留余额；调用结束后的实际 usage 可以把总量推到预算之上。
- 现有测试甚至专门接受 `over_budget=True` 后“仍可解释”，这证明当前语义是“事后报告超支”，不是“硬保证不超支”。

**完成条件**

- 所有 LLM 出口统一写 `LlmCall`，包含辅助调用、失败调用和 usage 缺失时的本地估算。
- 发起前原子预留，完成后以实际 usage 冲正；失败也结算已消费 token。
- 基线调用与可选调用均受生命周期总预算约束，只有作者显式 topup 可扩容。
- 加入“provider 无 usage”“实际高于估算”“并发候选”“重跑”四类不会越过预算的测试。

### P0-5 未声明发送权时仍允许云端策略

**证据**

- `style_reference/ingest.py:62-75` 对未声明权属返回 `declared=False`，不拒绝云端策略。
- `backend/tests/test_reference_ingest_rights.py:60-63` 明确测试“未声明 + allow_full_cloud 仍可导入”。

**问题**

这与原设计 §11.9“不得对用户导入文本默认拥有云端发送权”直接冲突。选择 cloud policy 可以表示技术策略，不能自动替代版权/发送权声明。

**完成条件**

- `cloud_policy != local_only` 时，必须同时存在 `declared=true`、`send_rights=true`。
- 未声明只能导入为 local-only，或阻止导入并要求用户确认；不得静默沿用云端策略。
- 对存量 `declared=false + 非 local_only` 记录建立盘点和降级迁移。

### P0-6 不可信文本封装没有覆盖全部 LLM 入口

**证据**

- `secure_reference_block` 的生产调用点只在 `style_reference/injection.py:628-633`，覆盖最终 few-shot/RAG。
- `style_reference/_llm_helper.py:56` 把任意 payload 直接 JSON 序列化到 user prompt。
- `style_reference/extractors/base.py` 的抽取与补证 payload 含原始 `paragraphs[].text`。
- `style_reference/preview.py:103-114` 把原始 `seed_quote` 直接送入预览模型。

**影响**

恶意参考文本仍可在抽取、补证和预览阶段影响模型角色或输出；只保护最终写作注入不能称为完整来源安全闭环。

**完成条件**

- 在 style-reference LLM 公共出口建立 typed untrusted fields，统一中和并边界封装原文、quote 和 evidence。
- system prompt 明确不可信区块只作为数据；结构化 schema 和任务指令位于区块外。
- 抽取、补证、画像合成、预览、RAG rerank、few-shot/RAG 最终注入逐入口回归。

---

## 5. P1：发布前必须补齐的工程缺口

### P1-1 FK 仍未启用

- 当前 Alembic head 与默认库均为 `0064`，preflight 为 `ready=true`、`integrity=ok`；默认库版本落后阻断已关闭。
- 默认库孤儿盘点为 0，但 FK pragma 仍为 0；Wave 7 的“盘点后再评估启用”尚未完成最后一步。
- 依据 tracked manifest 和全量存量盘点、metadata drift、主要 API smoke 结果，形成是否启用 FK 的正式结论；启用前仍须保留校验备份与回滚路径。

### P1-2 成本数据仍不是真实账单

- `config/pricing.yaml` 全部 `is_estimate:true`。
- prompt cache 折扣、计费 token 与实际 token 没有真实 provider 数据支撑。
- 跨 provider 预算仍按全局 token 相加，而不同 tokenizer 的 token 不可直接比较。
- 没有作者取消端点，当前以“预算闸阻止后续节点”替代取消，语义不等价。

### P1-3 可观测性指标体系大部分未落地

原设计要求 15 个指标加一个北极星指标。全仓精确检索只能找到少量成本/分散度字段；以下核心名称和统一聚合未实现：

- `draft_delivery_rate`
- `archive_success_rate`
- `draft_recovery_success_rate`
- `hard_block_rate`
- `soft_warning_rate`
- `human_takeover_rate`
- `candidate_preference_rate`
- `degraded_slot_rate`
- `pov_leak_findings`
- `source_safety_block_rate`
- `cross_chapter_continuity_error_rate`
- `archived_publishable_chapters_per_100k_tokens`

没有这些指标，系统仍难以回答“交付率是否提高、软警告是否只是被忽略、质量收益是否值得成本”。

### P1-4 真实恢复、30 章耐久和延迟门未执行

- 备份/恢复工具通过不等于真实应用状态恢复通过。
- 需要在第 5/10/20/30 章清缓存并重启，验证目录、场景状态、作者选择和章节成稿一致恢复。
- 当前 30 章指标产物为合成数据，不能证明数据库增长、模型漂移、跨章重复、成本斜率或 p95。

### P1-5 证据产物没有可审查的保留策略

- 进度账本引用 `.codex-run/wave2-e2e`、`wave3-e2e`、`wave5-blind-eval-report` 等路径。
- `.codex-run/` 被整体忽略，当前拉取后不存在这些产物。

应保留脱敏后的 manifest、哈希、命令、退出码、汇总 JSON 和必要正文摘要；敏感正文可放外部受控存储，但仓库必须保留可核对的证据索引和校验和。

### P1-6 结构收敛未完成

- `orchestrator.py` 约 1316 行、`ws-snow.jsx` 约 3961 行、`models.py` 约 2172 行、`qc_engine.py` 约 1829 行。
- `ws-app.jsx` 仍静态导入主要页面，没有 React 路由级 lazy load。
- 当前主 JS gzip 约 379KB，已达到体积目标，但单 chunk 与静态导入仍增加启动、变更和回归风险。

---

## 6. P2：文档、测试和产品语义缺点

1. **进度状态过度乐观（历史问题，已纠正）。** Wave 0–6 的标题曾写“已完成”，但正文承认真实模型、浏览器、人评和发布门未跑；该问题已在 2026-07-13 状态矩阵中纠正为 `engineering_status`、`real_gate_status`、`release_gate_status` 三层状态。后续更新仍须维持三层状态，避免再次产生管理误读。
2. **合成数据命名容易误导。** `wave5-blind-eval-report` 和 `wave7-endurance-metrics` 应在文件名、schema 和报告首页写 `synthetic_fixture=true`，禁止被当作真实结果。
3. **测试偏向结构和 happy path。** 需要补充真实浏览器全链、provider usage 缺失、未声明云发送权、恶意抽取文本、迁移落后启动和真实取消等失败路径。
4. **演示隔离依赖人工盘点。** `ws-flowmap` 只做最小标记且无组件测试；至少应有导航级断言，保证真实项目不会显示 tide 演示叠加。
5. **默认策略与实验结论脱钩。** 实验服务只返回建议，不具备受审计的“应用策略”动作；生产配置因此可能长期与证据不一致。
6. **启动路径仍缺 schema preflight。** 当前 actual 已迁移到 `0064`，但 README 仍要求手动升级，Windows 启动脚本也不保证未来迁移；应在启动前做 schema preflight，明确失败而不是运行期 500。

---

## 7. 原设计十项最终交付物复核

| # | 原交付物 | 当前状态 | 结论 |
|---:|---|---|---|
| 1 | 可正确失败的五章结果验收脚本 | 判定器存在，但 harness 未跟上现有 UI | **部分完成** |
| 2 | 服务端权威成稿和统一作者状态 | 主干已实现，默认库 schema 已到 `0064`；真实浏览器恢复门仍缺 | **工程基本完成** |
| 3 | 软质量问题不丢稿的可靠模式 | 有分类器和测试，真实模型未复跑 | **工程基本完成** |
| 4 | 关键场景匿名候选终选界面 | UI/API 存在，北极星不使用 | **工程完成、E2E 未验** |
| 5 | POV 减法知识投影 | 代码/golden 存在，真实悬疑对照缺失 | **工程完成、效果未验** |
| 6 | 30 组人类盲评与统计报告 | 只有合成 30 组 | **未完成** |
| 7 | 场景/章节/全书 token 与成本看板 | 骨架存在，漏账且价格估算 | **部分完成** |
| 8 | 五章完整成稿、安全、连续性、恢复证据 | 无新鲜完整产物 | **未完成** |
| 9 | 30 章耐久与数据库增长报告 | 只有判定器和合成样本 | **未完成** |
| 10 | 每个高成本模块的保留/可选/降级/移除结论 | 只有机制/合成建议，未驱动生产默认 | **未完成** |

最终交付物层面，不能以“7/8 个 Wave 有提交”替代“10 项结果交付物完成”。

---

## 8. 二次收敛执行顺序

### 收敛 0：恢复可运行真值与证据纪律

1. [x] 已对默认库执行校验备份并验证备份可恢复；备份保留迁移前 `0059` 历史状态。
2. [x] 已在副本上从 `0059` 升级到 `0064` 完成演练，并将 actual 升级到 `0064`；preflight `ready=true`、`integrity=ok`、孤儿数 0。
3. [x] 已建立固定 evidence manifest：tracked 索引为 `docs/superpowers/evidence/20260713-c0-manifest.json`，本地二进制复核使用 `.codex-run/governance-c0/20260713-c0` 作为 `artifact_root`。
4. [x] 已把进度账本状态改为“工程实现”“真实门”“发布门”三列，不再使用单一“已完成”。
5. evidence manifest 使用 `outcome-evidence-v1` schema，并分别记录 `engineering_status`、`real_gate_status`、`release_gate_status`；工程实现、真实门与发布门只能由各自对应层的有效证据推进。
6. synthetic/offline 证据只能支持 `engineering_status`；被忽略的 artifact 或缺失 artifact 不得推进真实门，`real_gate_status` 必须保持 `pending`（需要人类终验时保持 `pending_human`），也不得据此推进 `release_gate_status`。

**完成门：** 当前默认运行库与代码 head 一致；任一审查者能按 manifest 复算门禁结论。

### 收敛 1：先修 P0 安全与成本真值

1. 未声明发送权的参考文本强制 local-only 或拒绝云端策略。
2. 把不可信封装下沉到 style-reference 公共 LLM 出口，覆盖抽取、补证、合成、预览和最终注入。
3. 统一 `run`/`run_task` 成本记录，补本地 token 估算和原子预算预留/冲正。
4. 加入真实取消 API 与审计事件。

**完成门：** 无权属云发送、提示词注入旁路、usage 缺失漏账和预算超限测试全部可证伪并通过。

### 收敛 2：让北极星真正走 UI

1. 更新 currentdb harness，删除 Wave 3 前的过期 `missing` 记录。
2. 用 UI 完成雪花规划、物化、15 场执行、至少 3 场候选终选、归档和章节成稿查看。
3. API 只负责验证后端最终状态和内容哈希。
4. 在运行中执行清缓存、服务重启和页面重载恢复。

**完成门：** `NORTHSTAR_PHASE_NOT_UI` 为 0，15/15 归档，5/5 聚合一致，恢复后内容/选择哈希不变。

### 收敛 3：执行真人盲评并驱动默认策略

1. 从 30 个不同冻结快照生成 treatment/control。
2. 用户本人完成至少 30 个非平局选择；平局继续采样，不凑数。
3. 生成带原始匿名票、映射 reveal、统计过程和成本倍率的可复算报告。
4. 通过受审计配置动作应用 `upgrade_to_default` 或 `keep_optional`。

**完成门：** 生产默认与真实报告结论一致；没有报告时默认单发/可选。

### 收敛 4：执行真实 30 章耐久门

1. 使用真实持久化、真实重启和分层模型基线运行 30 章。
2. 在第 5/10/20/30 章执行恢复检查。
3. 采集数据库大小、三核心读取 p95、每五章连续性/漂移/重复、按模型分层 token/成本。
4. 若孤儿盘点持续为 0，在完整回归后启用 SQLite FK。

**完成门：** 原设计 Wave 7 的 30 章硬断言全部通过，且产物不是 synthetic fixture。

### 收敛 5：最后做结构和指标收敛

1. 沿已修改边界拆分 orchestrator、ws-snow、qc_engine 和 models，不做功能混杂重写。
2. 增加路由级 lazy load，保持主 chunk gzip <500KB。
3. 补齐 §10 全部指标和北极星指标，统一由后端权威数据聚合。

**完成门：** 结构调整后全量回归、北极星五章和关键失败路径不退化；指标可以从同一证据包复算。

---

## 9. 最终关闭清单

以下全部满足之前，本文状态保持“未闭环”：

- [x] Alembic current 与 head 均为 `20260712_0064`；证据见 `docs/superpowers/evidence/20260713-c0-manifest.json`，本地 artifact 复核须指定 `.codex-run/governance-c0/20260713-c0`。
- [ ] 后端全量非 Chroma 测试、React 测试和生产构建新鲜通过。
- [ ] 五章 harness 六阶段全部为 UI lane。
- [ ] 原创 15/15 场有非空服务端归档正文，5/5 聚合一致。
- [ ] 授权/公版参考文本 lane 通过，未声明发送权不进入云端。
- [ ] 清缓存与后端重启后，正文、作者选择和章节聚合完全恢复。
- [ ] Q0/Q1 未解决项为 0，来源泄漏为 0。
- [ ] 所有 LLM 调用可记账，关键场生命周期实际消耗不超过有效预算。
- [ ] 30 个不同快照完成真人非平局盲评并产出可复算报告。
- [ ] Best-of-N 生产默认与真人报告结论一致。
- [ ] 30 章真实耐久门通过，含恢复、p95、成本斜率、连续性、漂移和重复证据。
- [ ] FK 是否启用已有基于全量存量盘点和回归的正式结论。
- [ ] §10 指标与北极星指标可由权威数据复算。
- [ ] 所有发布门证据有 manifest、hash、provenance，合成产物不会冒充真人/真实模型结果。

---

## 10. 最终判断

这一轮实施不是失败：它已经把最危险的“无稿却绿灯、软质量断头、前端缓存冒充真值、候选选择无锁、POV 明文泄密”等问题推进到更可靠的工程形态。

但它也没有完成原设计最重要的证明责任：**作者是否真的能从 UI 稳定拿到五章、Best-of-N 是否真的值得成本、系统是否能在 30 章和重启后维持结果、所有来源和成本是否真的可解释。**

下一轮不应继续增加文学模块或外围页面。应严格按“安全与成本真值 → UI 五章闭环 → 真人盲评 → 30 章耐久 → 结构与指标”的顺序收口。只有当真实结果证据替代合成证据后，原治理设计才算真正闭环。
