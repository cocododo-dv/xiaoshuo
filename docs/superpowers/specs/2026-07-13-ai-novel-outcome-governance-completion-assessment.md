# AI 小说系统结果闭环治理：完成度深度评估与二次收敛清单（C2 最小闭环更新版）

> 评估日期：2026-07-14
>
> 评估基线：`codex/outcome-governance-closure` / `d01a338` 及本轮 C2 收尾修复
>
> 原设计：`docs/superpowers/specs/2026-07-10-ai-novel-outcome-governance-design.md`（v1.1）
>
> 实施账本：`docs/outcome-governance-progress.md`
>
> 当前结论：**C0、C1A、C1B 的离线工程门已闭合；C2 已取得一份“1 章 × 1 场”的真实 UI 最小闭环，覆盖空白项目、雪花物化、真实生成、候选终选、预算追加、断点恢复、页面归档和章节聚合。但自动 outcome gate 的该次运行先于修复失败，5 章 × 3 场、恢复哈希、真人盲评和 30 章耐久门仍未通过，因此 C2 只能记为部分完成，不能发布。**

---

## 0. 2026-07-14 C2 精简收尾补充

本轮按“只做最重要的”收缩范围，没有继续消耗真实模型执行三场或五章。已完成并验证的最小主链如下：

1. 从空白项目通过 React UI 创建 `PRJ_7F82A90111`，导入并批准雪花十步，物化 `CDBQA_20260714220922_01 / SC01`。
2. 真实场景任务进入匿名候选终选；作者在 UI 完成选择和显式预算追加。
3. 修复两类真实恢复阻断：作者可见 `soft_qc_patch_required` 不再遮蔽持久化 `soft_qc_ready`；新的幂等续跑执行可以继承上一 HTTP 续跑的无 `run_job_id` 产物，同时场景后台任务仍要求 `run_job_id == execution_id`。
4. 在原失败现场复验 `/resume-after-selection`：由 HTTP 409 变为 200，返回 `quality_warning`、`can_archive=true`，没有重复生成已完成产物。
5. 通过 UI 点击“采纳并归档”，后端生成非空 `FinalScene`，权威 `scene_status=archived`；再通过成稿中心点击“生成/刷新章节汇总”，生成 active final chapter memory。

新鲜结果：

| 项目 | 结果 |
|---|---|
| 真实规模 | 1 章 × 1 场；不是五章发布样本 |
| 场景终态 | `archived`，`final_scene_CDBQA_20260714220922_01_SC01_adopt_11804ed748`，SQLite 正文 381 字符，UI 计数 359 字 |
| 章节聚合 | `chapter_memory_final_CDBQA_20260714220922_01_v1`，381 字符，`active_flag=1`、`runtime_eligible=1` |
| 自动回归 | 前端 130 passed；后端关键链路 22 passed，新增新幂等续跑回归 1 passed；harness 契约 11 passed；Vite build passed |
| 原始 outcome gate | **FAIL，保留原判定**；运行在修复前于预算续跑 409 中止，不能改写为通过 |
| 人工续跑证据 | 两张真实 UI 截图和数据库终态证明最小链已完成；不等价于六阶段自动 gate 全绿 |

仍未完成且必须保持开放：

- 3 场单章、5 章 × 3 场、至少 3 次候选选择、15/15 归档、5/5 聚合均未执行。
- 没有清缓存后的全链重放及正文/选择/聚合哈希一致性证明。
- 本次原始 gate 的 `scene_execution/candidate_selection/archive/chapter_aggregation` 回执因中途失败仍为 missing；需要将人工续跑改造成可续接的机器回执后才能关闭自动验收缺口。
- 归档后 `run_execution_status=failed`、`run_checkpoint=soft_qc_ready` 仍保留，页面运行任务横幅也显示旧 `awaiting_candidate_selection`。作者终态不受影响，但会误导运维判断，属于后续应修的状态一致性债务。
- 未完成五章级 Q0/Q1、来源泄漏、真实计费、首次产稿率及 5× token 上限验证。

证据索引：`docs/superpowers/evidence/20260714-c2-minimal-ui-closure.md`。因此本轮只把 UI 北极星从“未接通”提升为“最小真实链已接通”，**不关闭 C2，不宣称五章发布门通过**。

---

## 1. 执行结论

本轮不能用“Wave 0–7 已完成”概括真实状态。更准确的表述是：

1. **C1B 工程闭环已经完成。** 8 个生产 application-level completion 出口全部进入统一账本；每个新 physical attempt、retry 和 degrade hop 都有父子账，usage 缺失或失败按保守估算结算。场景 token、业务 attempt、provider attempt 三类生命周期预算都只能由作者显式 top-up 扩容。
2. **显式取消已经完成。** queued cancel 保持 0 provider call；running cancel 允许当前节点结算并保留产物，下一节点由数据库 fence 阻断；CAS、lease、重启恢复、审计和前端权威状态均有回归。
3. **actual 迁移和 C1B 证据可复算。** canonical actual 已由 `20260712_0064` 升到 `20260713_0065`；严格 manifest 绑定 19 个产物、14 条成功命令和 13 个 required gates，并由 `--profile c1b --require-provenance offline` 外部复算通过。
4. **历史账不能被伪造为新账。** actual 中有 51 条迁移前 logical parent，全部回填为 estimated，physical attempt 子行仍为 0；这只能证明迁移后口径明确，不能反推历史真实 provider 尝试或账单。
5. **来源安全的两个 P0 工程缺口已关闭，真实门仍待验证。** 非本地策略要求显式声明与发送权，style-reference 全链使用统一不可信数据边界；C1A offline 证据不替代真实云模型和五章来源安全 lane。
6. **北极星 UI 和五章真实结果门仍未闭合。** 当前没有 5 章 × 3 场的 15/15 UI 归档、清缓存/重启恢复、Q0/Q1=0 与来源泄漏=0 的新鲜可复算产物。
7. **真人盲评和耐久门仍未执行。** 合成 30 对只能证明统计机制，不能证明 Best-of-N 值得默认成本；合成 30 章也不能证明真实恢复、p95、漂移、重复和成本斜率。
8. **旧 Wave 证据仍不可完整复算。** C0/C1A/C1B 已建立 tracked manifest，但更早 `.codex-run/wave*` 产物仍未形成同等级的保留策略。

因此，当前合理状态应定义为：

| 维度 | 状态 | 说明 |
|---|---|---|
| 核心工程能力 | **大部分已实现** | 正文/QC/候选/POV、来源安全、统一账本、硬预算、checkpoint 和取消主干已落地 |
| C1B 账本/预算/取消 | **离线工程门通过** | actual `0065`，13/13 gate 与严格 manifest 可复算；不代表真实账单或发布通过 |
| 自动测试可信度 | **较高但仍属 L2** | C1B 全量 2482 项后端收集、本轮 130 项前端与生产构建通过；不能替代真实模型、人评和浏览器全链 |
| UI 北极星闭环 | **部分完成** | 1×1 真实 UI 最小链已完成；该次自动 gate 先于修复中止，完整六阶段回执和五章规模未完成 |
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

- 从最新 `origin/main` 建立隔离分支，按 C0 → C1A → C1B 顺序收敛，不修改主工作区无关 `.idea` 变更。
- 逐节对照原设计 §2–§15、Wave 0–7 实施计划和进度账本。
- 对所有生产 completion 出口做对抗式 AST inventory，并核查 scope、logical parent、physical attempt、usage provenance 与失败结算。
- 对 checkpoint、预算、取消 CAS/lease/recovery、前端轮询和 race 做定向与全量回归。
- 在 canonical actual 的新校验备份上演练 `0064 -> 0065`，再升级 actual；迁移前后均做 preflight、只读 accounting audit 和备份校验。
- 生成 C1B strict manifest，并从 ignored artifact root 做外部语义复算。

### 2.3 本轮新鲜验证结果

本节只记录本次评估实际执行的结果，不复述历史账本中的通过数：

- C1B 专项：`364 passed`，覆盖 required selector、所有生产出口、usage missing、失败、retry/degrade、并发预留、重跑、checkpoint 与取消。
- 后端：`python -m pytest tests -q -m "not chroma_integration"` 新鲜通过，`2477 passed, 5 skipped, 17 deselected`；JUnit 为 `2482 tests / 0 failures / 0 errors / 5 skipped`，耗时 1722.57 秒。17 个 Chroma 集成用例按平台 marker 明确未选，没有隐去。
- 证据校验器：`159 passed, 1 skipped`；唯一 skip 是本机缺少创建 symlink/hardlink 的权限型白名单。WAL header、Windows URI、路径逃逸、硬链接、TOCTOU、hash/size、JUnit 重算和 offline 敏感声明均有回归。
- React：Vitest `14` 个测试文件、`122` 项全部通过；其中 scene-run/cancel 专项 `45` 项。
- 构建：Vite production build 通过；主 JS 1,246.35 kB、gzip 388.47 kB。gzip 仍低于 500 kB 目标，但单一大 chunk 和动态/静态混合导入警告仍在。
- Alembic/actual：代码 head 与 canonical actual 均为 `20260713_0065`；最终 preflight `ready=true`、`integrity=ok`、schema errors=0、attempt orphan=0。actual 为 6,516,736 bytes，SHA-256 `9f993a86451dc48289943600a9a643f559eaa9ff5a8bb4fb523e1289cf5fa123`。
- 迁移备份：`0064` 备份为 5,120,000 bytes，SHA-256 `2f4a69f7557671c46813fd249c7fb72d62e366a29545012de267316d8f9bdced`、page_count=1250、integrity=ok；副本演练和 actual 均到 `0065`。
- actual accounting：51 个迁移前 logical parents（50 settled、1 failed）全部为 estimated，0 unknown、0 physical attempt rows、0 negative/stuck/orphan/scope 缭乱。不得据此声称历史 physical attempts 已重建。
- outlet inventory：production application outlets `8`、unified `8`、unaccounted `0`。
- 当前 `PRAGMA foreign_keys=0`；FK 是否启用仍待正式结论。
- C1A 来源安全新鲜验证：实际库在备份、`0064` preflight、before/apply/after 权属盘点后保持 `0` 行、`0` 违规、`0` 降级；聚焦回归 `130 passed`，style-reference 选择集 `512 passed, 8 skipped`。可审查索引见 `docs/superpowers/evidence/20260713-c1a-source-safety.json`，provenance 为 `offline`。

说明：C1B 可审查索引见 `docs/superpowers/evidence/20260713-c1b-accounting-budget-cancel.json`；本机复核根为 `.codex-run/governance-c1b/20260713-c1b-20260714T080458Z-eba87a1`。必须使用 `validate --profile c1b --require-provenance offline`；generic validate 不能冒充 C1B 验收。C0 与 C1A manifest 继续保留各自边界。

**C1B 证据边界：** 本轮在 actual 迁移前保存了进程、监听端口和 WAL 快照，writer_matches=0、wal_size=0；备份、演练、actual 升级和终态只读审计均在同一 run 内。该事实仍依赖执行工作站和本地 artifact，不是加密证明。真实 provider、真实账单、真实模型效果和发布结果不在 offline provenance 的证明范围内。

**Validator threat model：** C1B profile 除存在/hash/size/命令时间外，还重算真实 SQLite 备份、preflight、账务 audit、outlet inventory、JUnit 聚合/selector/skip 白名单、Vite 完成标记和 13 个 gate 计数；同时拒绝路径逃逸、绝对路径、ADS、保留设备名、symlink/hardlink、TOCTOU 和 offline 证据中的 real/release/billing 冒充。它仍不是签名系统，不能阻止控制执行工作站的人同时伪造 manifest 与 artifact。

---

## 3. Wave 0–7 深度完成度

| Wave | 已做好 | 证据等级 | 没有闭环的关键点 | 本轮判定 |
|---|---|---:|---|---|
| Wave 0 结果门禁 | Outcome Gate 能识别空稿、缺场、假评分和非 UI lane | L2 | harness 没有随 Wave 1–3 反向接回真实 UI；候选终选仍写死 `missing` | **部分完成** |
| Wave 1 正文真值与归档 | `FinalScene` 权威态、`author_state`、latest-valid、adopt、后端成稿聚合已实现；actual schema 已到 `0065` | L2 | 没有真实浏览器清缓存/重启恢复门 | **工程主干完成，结果门未过** |
| Wave 2 QC 分级 | Q0–Q3、确定性复核、软问题不丢稿、reliable/strict 语义已有测试 | L2 | 没有“当前真实模型旧三章复跑”证据；真实波动和坏稿归档率未知 | **工程主干完成，真实门未过** |
| Wave 3 Best-of-N | 候选盲化、锁定、重开、durable resume、React CandidatePicker 和生命周期硬预算已存在 | L2 | harness 不走该 UI；真实多候选走查缺失；未有人评却已默认标准场 N=2、关键场 N=3 | **工程加强，默认策略证据不足** |
| Wave 4 POV 投影 | 两个主要状态注入槽和 finding 回灌脱敏已有实现与 golden 测试 | L2 | 无真实悬疑 LLM 对照；收益依赖显式知识标注质量；写侧事件提取默认关闭 | **工程完成度较高，效果未证** |
| Wave 5 质量实验室 | 实验表、路由、盲化、投票、统计报告和最小 UI 已实现 | L2（机制）/L0（真人结果） | 30 对和 21/30 产物是合成；真人 30 非平局未执行；没有把真实结论写回生产默认策略 | **基础设施完成，目标未完成** |
| Wave 6 成本与独立性 | 统一父子账本、三口径聚合、三类生命周期预算、显式取消、成本页和独立性信号已实现 | L2（offline） | pricing 全为 estimate；真实计费/cache 折扣和跨 provider token 可比性未证；指标体系缺失 | **工程门通过，真实成本门未过** |
| Wave 7 耐久/安全/收敛 | 备份/孤儿工具、来源权属门、不可信边界、取消恢复、严格 evidence profile、耐久判定器已实现 | L2 | 真实来源安全 lane、30 章、FK、大文件拆分和路由懒加载仍未完成 | **安全/恢复工程增强，Wave 7 仍不得标完成** |

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

### P0-4 5× token 预算可漏记、可超限（工程门已关闭）

**当前状态**

- `engineering_status=passed`：8/8 生产 completion 出口统一走 `execute_accounted_call`；`run`、`run_task`、system probe、Snowflake、style-reference、library/longform 和 literary eval 均有明确 scope。
- 每次真实 dispatch（含 transport/parse retry 和 API/structured/missing-text degrade）均写 `LlmCallAttempt`；父 `LlmCall` 聚合子行，成本报表不双计。
- usage 缺失、部分、不一致、无效或 provider 失败都按非 0 保守估算结算，并显式记录 `usage_is_estimate`；不能再按 0 漏账。
- token、业务 attempt 和 provider attempt 三类生命周期账户在发送前原子预留/claim；实际高于 reservation 会进入会计完整性硬阻断，不能继续发送。
- 基线和可选节点使用同一硬门，自动重跑不清零；作者 top-up 是三类预算的唯一扩容入口。
- durable checkpoint 保存产品、hash、父子账和 execution owner；同 execution 恢复不重放已完成节点或重复扣费。
- C1B 专项 364 项、最终后端全量 2482 项、strict manifest 13/13 gate 均通过。

**诚实边界**

- actual 的 51 条迁移前 logical parents 只能标 estimated，0 physical attempt rows；历史 provider 行为无法追溯重建。
- `config/pricing.yaml` 仍全部为 estimate；provider actual、计费 token、prompt-cache 折扣和跨 tokenizer 可比性没有真实账单证据。
- 本门只从 P0 工程缺口降为“真实成本/发布门 pending”，不把 offline gate 写成关键场真实 5× 消耗已通过。

**完成条件核对**

- [x] 所有生产 LLM 出口统一写 logical parent；每个新 physical dispatch 单独记账。
- [x] usage 缺失和失败非 0 结算，预留/结算/释放具备并发不变量。
- [x] 基线与可选调用均受生命周期总预算约束，只有作者显式 top-up 可扩容。
- [x] provider 无 usage、actual>estimate、并发预留、重跑、retry/degrade 和 checkpoint 恢复均有可证伪回归。

### P0-5 未声明发送权时仍允许云端策略（工程门已关闭）

**当前状态**

- `engineering_status=passed`：非本地策略必须同时满足严格布尔 `declared=true` 与 `send_rights=true`；路径、上传和策略变化会重置前端确认，服务端再次复核持久化声明。
- 存量双层防线已落地：导入时拒绝，运行时在云调用前重新检查；审计工具支持 dry-run 与显式降级。
- 实际库 before/apply/after 均为 `violation_count=0`、`downgraded_count=0`，且 `style_reference_books` 实际为 0 行，因此没有伪称执行过存量降级。
- `real_gate_status=pending`、`release_gate_status=pending`：尚未用真实云 provider 和五章授权/公版 lane 验证。
- 证据：`docs/superpowers/evidence/20260713-c1a-source-safety.json`。

**原始缺口证据（修复前）**

- `style_reference/ingest.py:62-75` 对未声明权属返回 `declared=False`，不拒绝云端策略。
- `backend/tests/test_reference_ingest_rights.py:60-63` 明确测试“未声明 + allow_full_cloud 仍可导入”。

**原始问题（修复前）**

这曾与原设计 §11.9“不得对用户导入文本默认拥有云端发送权”直接冲突。选择 cloud policy 可以表示技术策略，不能自动替代版权/发送权声明。

**完成条件核对**

- [x] `cloud_policy != local_only` 时，必须同时存在 `declared=true`、`send_rights=true`。
- [x] 未声明只能导入为 local-only，或阻止导入并要求用户确认；不得静默沿用云端策略。
- [x] 对存量 `declared=false + 非 local_only` 记录建立盘点和显式降级工具；实际库本轮为 0 违规、0 降级。

### P0-6 不可信文本封装没有覆盖全部 LLM 入口（工程门已关闭）

**当前状态**

- `engineering_status=passed`：公共 helper 只接受 typed `UntrustedPayload`，递归中和字符串叶子，并把 JSON 放入唯一 `UNTRUSTED_REFERENCE_DATA` 边界；system prompt 同时追加数据非指令约束。
- 抽取、补证、画像合成、预览、语义校验、forbidden 校验、library derive、longform audit 和分段直连出口均已接线；静态盘点为 typed caller `7/7`、实际 style-reference `generate` 出口 `2/2`。
- 恶意角色标记、工具标记、全角/空白/零宽/Markdown 变体和伪造边界已有回归；聚焦 `130 passed`，完整选择集 `512 passed, 8 skipped`。
- `real_gate_status=pending`、`release_gate_status=pending`：尚未用真实模型证明模型行为不受恶意参考文本影响，也未完成五章来源安全 lane。
- 证据：`docs/superpowers/evidence/20260713-c1a-source-safety.json`。

**原始缺口证据（修复前）**

- `secure_reference_block` 的生产调用点只在 `style_reference/injection.py:628-633`，覆盖最终 few-shot/RAG。
- `style_reference/_llm_helper.py:56` 把任意 payload 直接 JSON 序列化到 user prompt。
- `style_reference/extractors/base.py` 的抽取与补证 payload 含原始 `paragraphs[].text`。
- `style_reference/preview.py:103-114` 把原始 `seed_quote` 直接送入预览模型。

**原始影响（修复前）**

恶意参考文本曾可在抽取、补证和预览阶段影响模型角色或输出；只保护最终写作注入不能称为完整来源安全闭环。

**完成条件核对**

- [x] 在 style-reference LLM 公共出口建立 typed untrusted fields，统一中和并边界封装原文、quote 和 evidence。
- [x] system prompt 明确不可信区块只作为数据；结构化 schema 和任务指令位于区块外。
- [x] 抽取、补证、画像合成、预览、语义/forbidden、分段、RAG/few-shot 最终注入逐入口回归。

---

## 5. P1：发布前必须补齐的工程缺口

### P1-1 FK 仍未启用

- 当前 Alembic head 与默认库均为 `0065`，preflight 为 `ready=true`、`integrity=ok`、attempt orphan=0；默认库版本落后阻断已关闭。
- 默认库孤儿盘点为 0，但 FK pragma 仍为 0；Wave 7 的“盘点后再评估启用”尚未完成最后一步。
- 依据 tracked manifest 和全量存量盘点、metadata drift、主要 API smoke 结果，形成是否启用 FK 的正式结论；启用前仍须保留校验备份与回滚路径。

### P1-2 成本数据仍不是真实账单

- `config/pricing.yaml` 全部 `is_estimate:true`。
- 工程上已分开 estimate、provider actual、budget charged，retry/degrade 也可见；但 prompt cache 折扣、计费 token 与实际 token 仍没有真实 provider 数据支撑。
- 跨 provider 预算仍按全局 token 相加，而不同 tokenizer 的 token 不可直接比较。
- actual 的 51 条历史父调用没有 physical attempt 子行，不能从迁移后标签反推真实账单；新调用具备完整账本不等于旧账可恢复。
- 作者取消端点、worker 状态机和前端控制已经关闭工程缺口，不再列为本 P1 的未完成项。

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
3. **测试偏向离线结构和确定性失败路径。** provider usage 缺失、未声明云发送权、恶意抽取文本、迁移落后、预算并发和取消竞态已补；仍缺真实浏览器五章全链、真实 provider/账单和真实进程重启下的发布验证。
4. **演示隔离依赖人工盘点。** `ws-flowmap` 只做最小标记且无组件测试；至少应有导航级断言，保证真实项目不会显示 tide 演示叠加。
5. **默认策略与实验结论脱钩。** 实验服务只返回建议，不具备受审计的“应用策略”动作；生产配置因此可能长期与证据不一致。
6. **启动路径仍缺 schema preflight。** 当前 actual 已迁移到 `0065`，但 README 仍要求手动升级，Windows 启动脚本也不保证未来迁移；应在启动前做 schema preflight，明确失败而不是运行期 500。

---

## 7. 原设计十项最终交付物复核

| # | 原交付物 | 当前状态 | 结论 |
|---:|---|---|---|
| 1 | 可正确失败的五章结果验收脚本 | 判定器存在，但 harness 未跟上现有 UI | **部分完成** |
| 2 | 服务端权威成稿和统一作者状态 | 主干已实现，默认库 schema 已到 `0065`；真实浏览器恢复门仍缺 | **工程基本完成** |
| 3 | 软质量问题不丢稿的可靠模式 | 有分类器和测试，真实模型未复跑 | **工程基本完成** |
| 4 | 关键场景匿名候选终选界面 | UI/API 存在，北极星不使用 | **工程完成、E2E 未验** |
| 5 | POV 减法知识投影 | 代码/golden 存在，真实悬疑对照缺失 | **工程完成、效果未验** |
| 6 | 30 组人类盲评与统计报告 | 只有合成 30 组 | **未完成** |
| 7 | 场景/章节/全书 token 与成本看板 | 新调用统一账本与三口径聚合已完成；价格、cache 折扣和跨 provider 可比性仍为估算 | **工程基本完成、真实成本未证** |
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

1. [x] 未声明发送权的参考文本强制 local-only 或拒绝云端策略；C1A offline 工程证据已归档。
2. [x] 把不可信封装下沉到 style-reference 公共 LLM 出口，覆盖抽取、补证、合成、预览和最终注入；typed caller 与实际出口盘点均通过。
3. [x] 统一 `run`/`run_task` 与全部生产 completion 出口，补 physical attempt、保守 token 估算、原子预算预留/冲正和只读 audit。
4. [x] 加入显式取消 API、CAS/lease/recovery、审计事件、latest 权威读和 React 取消控制。

**完成门：已通过（offline engineering）。** 无权属云发送、提示词注入旁路、usage 缺失漏账、预算超限、重放扣费和取消竞态均可证伪并通过。真实 provider、真实账单和发布结果继续由后续门负责。

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

- [x] Alembic current 与 head 均为 `20260713_0065`；C1B 证据见 `docs/superpowers/evidence/20260713-c1b-accounting-budget-cancel.json`。
- [x] 后端全量非 Chroma（2477 passed / 5 skipped / 17 deselected）、React 122 项和生产构建新鲜通过。
- [ ] 五章 harness 六阶段全部为 UI lane。
- [ ] 原创 15/15 场有非空服务端归档正文，5/5 聚合一致。
- [ ] 授权/公版参考文本 lane 通过，未声明发送权不进入云端。
- [ ] 清缓存与后端重启后，正文、作者选择和章节聚合完全恢复。
- [ ] Q0/Q1 未解决项为 0，来源泄漏为 0。
- [x] 所有新生产 completion 出口可记账，生命周期硬预算/重跑/top-up/取消的 offline engineering gate 通过；真实关键场实际消耗仍由五章门验证。
- [x] queued/running 取消、CAS/lease/restart recovery、审计与前端权威恢复的 engineering gate 通过。
- [ ] 30 个不同快照完成真人非平局盲评并产出可复算报告。
- [ ] Best-of-N 生产默认与真人报告结论一致。
- [ ] 30 章真实耐久门通过，含恢复、p95、成本斜率、连续性、漂移和重复证据。
- [ ] FK 是否启用已有基于全量存量盘点和回归的正式结论。
- [ ] §10 指标与北极星指标可由权威数据复算。
- [ ] 所有发布门证据有 manifest、hash、provenance，合成产物不会冒充真人/真实模型结果。

---

## 10. 最终判断

这一轮已经关闭三类最危险的工程真值缺口：来源权属/不可信文本、LLM 账本/生命周期硬预算、显式取消/恢复；同时把 actual 升到 `0065` 并建立可语义复算的 strict evidence profile。它也保留并加强了“无稿不绿灯、软问题不丢稿、前端缓存不冒充真值、候选选择有锁、POV 不明文泄密”的既有成果。

但它也没有完成原设计最重要的证明责任：**作者是否真的能从 UI 稳定拿到五章、Best-of-N 是否真的值得成本、系统是否能在 30 章和重启后维持结果、所有来源和成本是否真的可解释。**

下一轮不应继续增加文学模块或外围页面。工程真值阶段已经完成，剩余顺序应收紧为“UI 五章闭环 → 真人盲评并应用默认策略 → 真实 30 章耐久/FK 结论 → 结构与指标”。只有当真实结果证据替代合成/offline 证据后，原治理设计才算真正闭环。
