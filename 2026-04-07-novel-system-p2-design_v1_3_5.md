# AI 小说写作系统 P2 级落地设计文档

> 版本：1.3.5（ops recovery / alias semantics / target_collection 收口）| 日期：2026-04-07  
> 基准文档：`novel_system_manual_v4_8_9_final.docx` + `novel_system_object_maps_v4_8_combined.pdf`  
> 文档状态：本版为**实施修订定稿（ops recovery + alias semantics + schema 收口）**。数据库字段、状态机、接口、向量 verify gate、P0/P1 bridge、lineage、关键 FK、single-writer 契约、作业崩溃恢复与回放规则均以本文为准。  
> 与 v1.3.4 相比：本版直接修复 3 类实施缺口：① 补 `idempotency_keys / reindex_jobs / verify_jobs` 的 `worker_id / attempt_no / heartbeat_at / lease_expires_at`，并定义 recovery sweep、lease reclaim 与 stale worker 失效语义；② `vector_alias_registry` 拆分 `active_embedding_version / candidate_embedding_version`，并要求 reindex/verify job 显式绑定 `target_embedding_version`，消除 snapshot rebuild / 回滚期的 embedding 语义歧义；③ `review_items.target_collection` 改为由 `item_type` 派生的受控 `STORED` 列，禁止自由文本漂移，同时保留列表筛选与 materialize 路由所需的显式投影。

---

## 1. 本版目标与用词

### 1.1 目标

把手册 v4.8.9 的 P2 半自动系统直接收口成一份**可实施规格**。本文不再停留在“模块名 + 概念解释”，而是明确：

1. 物理表长什么样；
2. 哪些字段是 source of truth，哪些是 runtime alias；
3. 哪些对象按 `row_id + lineage_key + version` 建模；
4. `active_flag ≠ runtime_eligible` 到底怎么落；
5. `source_bundle_id / bundle_snapshot_hash / source_version_refs` 怎样贯穿 bundle、draft、final、replay；
6. P0/P1 通过哪些 import / export / replay 能力接入，而不是一句“兼容”。

### 1.2 规范性用词

- **MUST / 必须**：实现不可偏离。
- **SHOULD / 应当**：默认按此实现；若偏离，必须在代码与配置中显式写明。
- **MAY / 可选**：不影响核心闭环。

### 1.3 非目标

本版仍然不解决：

- 多用户协作与权限系统；
- 分布式部署、分库分表、多实例竞争；
- 替作者拍板主线转折；
- 自动决定文学判断。

---

## 2. 基准对齐与不可改边界

### 2.1 与手册 / 图 1A / 1B / 1C 的直接映射

1. **图 1A（静态 ER）**：`scene_bundle` 是只读快照，不是 source of truth；source of truth 仍是 `chapter_goal / scene_card / 正式知识表 / tracker`。  
2. **图 1B（review_item 审核入库）**：`review_item -> materialize -> activate -> reindex/verify` 必须拆开；其中 structured 对象可在 materialize 同事务 activate，vector / `future_effective` 对象必须先形成 candidate，再由 verify 或 promotion 原子 flip，且 `active_flag ≠ runtime_eligible`。  
3. **图 1C（运行时写回链）**：`scene_bundle -> neutral_draft -> hard_qc -> style_draft -> soft_qc -> final_scene -> archive -> scene_memory -> chapter_memory`，异常流统一先 append `attempt_tracker` 再进入 `human_review_event`。  
4. **ADR-01 / ADR-02 / ADR-03**：`bundle_resolution_cache`、`staged_backfill`、`vector alias flip verify gate` 都必须有独立的物理落点和状态，不允许藏在“工具函数”里。

### 2.2 本实现固定写死的 10 条边界

1. `scene_bundle` **只读**；重组 bundle 只能新建 bundle，不能原地改旧 bundle。  
2. `chapter_goal / scene_card` 是作者层 source of truth，**不得**把运行态 gate 回写进作者卡。  
3. `scene_run_states` 是场景级 runtime 权威表；`scene_card.status` 这类写法只是 alias。  
4. `chapter_states` 是章节级 runtime 权威表；`mid_aggregate_enabled_effective` 和 `chapter_backfill_pending_count` 只能落这里。  
5. 版本化对象统一按 **物理行 `row_id` + 逻辑 `lineage_key` + `version`** 建模；`row_id` ≠ `lineage_key`。  
6. `active_flag` 只表示 canonical version；`runtime_eligible` 只表示当前读取通道可读；vector 与 `future_effective` candidate 在放行前必须保持 `active_flag = 0`、`runtime_eligible = 0`。  
7. `false / true`（inactive 但 runtime_eligible）是非法组合；DDL 与服务层都要防。  
8. `final aggregate` 的前置条件固定是 `chapter_backfill_pending_count = 0`；fallback 的目标是清零，不是绕过。  
9. draft / final scene / replay 全部依赖 `source_bundle_id`；P1/P2 额外依赖 `bundle_snapshot_hash`。  
10. `approved_knowledge` 是逻辑桶，不是物理大表；真正落库的是分表：`style_rules`、`banned_rule_clusters`、`style_observations`、`voice_cards`、`relation_cards`、`world_rules`、`calibration_lines`、`scene_memory`、`chapter_memory`、`final_scenes`。

---

## 3. 系统架构与 source-of-truth 分层

### 3.1 总体架构

采用**单体分层架构**：

- 后端：FastAPI
- 结构化 source of truth：SQLite（SQLAlchemy + Alembic）
- 向量副本：ChromaDB
- 前端：Vue 3 + Vite + Pinia
- 运行模式：单用户、本地单机

### 3.2 四层职责

| 层 | 物理落点 | 负责什么 | 不负责什么 |
|---|---|---|---|
| 作者输入层 | `chapter_goals`、`scene_cards` | 章节/场景意图、拍点、must_include | 运行状态、attempt 计数 |
| 正式知识层 | versioned knowledge tables | 已审批、可版本治理、可被 runtime 消费的知识对象 | 原始候选、临时 review 中间态 |
| 运行快照层 | `scene_bundles`、`scene_drafts`、`qc_reports`、`final_scenes`、memory tables | 一次执行的快照、草稿谱系、QC、归档输出 | 作者输入原始卡片 |
| 运行治理层 | `scene_run_states`、`chapter_states`、`attempt_tracker`、`human_review_events`、`version_registry`、`bundle_resolution_cache`、`vector_alias_registry`、`reindex_jobs`、`verify_jobs`、`idempotency_keys`、`operation_logs`、`reconcile_faults` | gate、重试、回流、版本切换、索引 verify、作业 lease / heartbeat / reclaim、幂等、故障审计、helper cache | 文学内容本体 |

### 3.3 P0 / P1 / P2 兼容边界

- **P0**：允许通过 `bundle worksheet` 导入/导出；`execution_mode = P0_manual` 时 `bundle_snapshot_hash` 可以留空，但 `source_bundle_id` 绝不能空。  
- **P1**：允许脚本把 Markdown / CSV / worksheet 同步进本模型；可不做完整 SPA，但必须遵守本模型的 lineage / runtime / verify 规则。  
- **P2**：SQLite + ChromaDB + SPA 全量落地；vector alias flip、review inbox、human review、replay 都按本文实现。  

“兼容”在本设计里等于：**一套 P2 原生模型 + 明确的 import/export/replay 契约**，不是三套物理 schema 并存。

---

## 4. 数据建模总则

### 4.1 ID 与命名规范

- `row_id`：物理行主键，使用 ULID/UUID 字符串；只在数据库内部做唯一标识。
- `*_id`：逻辑 lineage key 或业务 key；例如 `voice_id`、`relation_id`、`world_rule_id`、`bundle_id`。
- `version`：同一 lineage 的版本号，单调递增，从 1 开始。
- `source_bundle_id`：草稿/终稿/归档回放链的根指针。
- `bundle_snapshot_hash`：bundle 冻结快照指纹；只对 bundle 求值，不对 draft/final text 求值。
- `alias_scope`：向量 alias 作用域键，**必须**全局唯一并带 `object_type:` 前缀；推荐格式 `<object_type>:<scope>:<scope_ref_id|global>`。
- `collection_family`：向量 alias 族的稳定命名前缀或命名空间；它不是 runtime 查询指针，runtime 只看 `active_alias / candidate_alias`。
- `scene_id / chapter_id / scope / scope_ref_id`：凡 REST list/filter 合同要求支持服务端筛选的上下文字段，**MUST** 有显式投影列；不得只靠 JSON 扫描、解析 `alias_scope` 字符串或全文过滤冒充索引查询。

### 4.2 SQLite 类型约定

- 时间统一存 **UTC RFC3339 TEXT**，例如 `2026-04-07T12:34:56.789Z`
- 布尔统一用 `INTEGER CHECK IN (0,1)`
- JSON 统一用 `TEXT` 存 canonical JSON，服务层负责 schema 验证与 canonicalization
- 所有 `created_at / updated_at` 都是数据库默认写入；应用更新时同步刷新 `updated_at`

### 4.3 版本化对象统一规则

版本化对象必须满足：

1. 物理主键是 `row_id`
2. 逻辑主键是 `lineage_key + version`
3. 对同一 lineage，只允许 1 条 `active_flag = 1`
4. `runtime_eligible = 1` 时，该行一定也必须 `active_flag = 1`
5. immediate 的 direct-read 对象可以在同一事务里完成 `materialize -> active=1 -> runtime_eligible=1`
6. 所有 vector 对象与所有 `future_effective` 对象，candidate row 在放行前都必须保持 `active_flag = 0`、`runtime_eligible = 0`；旧 active 持续服务，直到 verify / promotion 收口事务完成
7. direct-read 对象和 vector 对象的 `runtime_eligible` 翻转时机不同，见第 6 章 activation matrix

### 4.4 `version_registry` 的定义

`version_registry` 是跨对象的统一事件账本，面向**已版本化且会进入 runtime / verify / promote 治理**的对象；`scene_draft` 不纳入 registry，草稿谱系由 `scene_drafts + scene_run_states + attempt_tracker` 审计。`version_registry` 记录：

- `approved_at`
- `materialized_at`
- `activated_at`
- `reindexed_at`
- `materialize_status`
- `reindex_status`
- `verify_status`
- `sample_query_success`

对象表本身保留 `active_flag / runtime_eligible / runtime_eligibility_basis / effective_at`；`vector_alias_registry` 保留 alias 级 `active_alias / candidate_alias / active_snapshot_version / candidate_snapshot_version / active_embedding_version / candidate_embedding_version / verify_status / sample_query_success`。`version_registry` 允许记录“已 materialize 但尚未 active”的 candidate、以及“已 verify 但等待 `effective_at`”的 future-effective 候选；但它**不直接**作为 runtime filter 的 source of truth。runtime 读取一律先看对象表与 `vector_alias_registry`；若它们与 `version_registry` 不一致，服务层必须写 `reconcile_faults` 并进入 reconcile。

### 4.5 运行态权威表

- `scene_run_states`：场景当前跑到哪一步、当前 bundle/draft/final 指针、attempt 计数、repeat issue 断路器。
- `chapter_states`：章节已通过场次、backfill pending、mid aggregate gate、当前 final/interim memory 指针。
- 这两张表**不**替代作者卡；它们只承接运行控制。

### 4.6 FK 优先与 soft-link 审计规则

- **必须直接做 FK 的关键指针**：`scene_run_states.current_*`、`chapter_states.last_*_memory_row_id`、`scene_bundles.supersedes_bundle_id`、`scene_drafts.parent_draft_row_id / supersedes_draft_row_id`、`final_scenes.parent_style_draft_row_id / supersedes_final_scene_row_id / qc_report_id`、`scene_memories.final_scene_row_id`、`chapter_memories.supersedes_memory_row_id`、`chapter_rolling_notes.source_scene_memory_row_id`、各对象表 `source_review_id`、`attempt_tracker.source_bundle_id`、`interop_artifacts.scene_id / chapter_id / source_bundle_id`。  
- **不能直接做 FK 的 soft-links**：`review_items.merge_target_row_id / approved_item_row_id / approved_item_id`、`version_registry.physical_row_id`、`human_review_events.context_refs_json`、`bundle_resolution_cache.source_version_refs_json`。这些字段仍是合法设计，但必须受服务层一致性审计约束。  
- 系统 **MUST** 提供 `reconcile_runtime_refs()`（启动/迁移后执行）与 `audit_soft_links()`（定期或发布前执行）两类检查。发现 orphan、跨表类型不匹配或 JSON 上下文引用失真时，不得静默继续；必须把相关对象置为 `manual_hold` / `human_review_required`，写 `reconcile_faults`，并为本次检查 append `operation_logs`；若发生在场景执行链内，还必须同步写 `attempt_tracker`（`step = 'reconcile'`）。  
- **删除策略（固定）**：本库按 append / audit 优先设计。凡已经被 `scene_bundles / scene_drafts / final_scenes / scene_memories / chapter_memories / review_items / version_registry / attempt_tracker / human_review_events` 任一链路引用过的行，**MUST NOT** 通过通用 API 做 hard delete；退役统一用 `status`、`supersedes_*`、`active_flag = 0`、`abandoned`、`rejected`、`cancelled`、`manual_hold` 表达。只有“从未形成下游引用的预热数据 / 测试数据”才允许物理删除，且删除前必须跑 FK preflight。

### 4.7 single-writer、提交顺序与幂等键

| 写入面 | 内容生产者 | 唯一状态提交者 | 负责字段 | 明确不得写 |
|---|---|---|---|---|
| 对象表（approved knowledge） | `VersionManager` | `VersionManager` | `active_flag`、`runtime_eligible`、`runtime_eligibility_basis`、`effective_at`、同对象族 supersede 指针 | 不得切 vector alias |
| 对象表（`final_scenes` / `scene_memories` / `chapter_memories`） | `Archiver` / `Aggregator` 生成内容行 | `VersionManager` | 内容行的 active / runtime / supersede 状态提交；`chapter_passed_scene_count` 与 rolling note upsert 结果也必须经同一提交路径收口 | `Archiver` / `Aggregator` 不得绕过 `VersionManager` 直接 flip active |
| `version_registry` | `VersionManager` | `VersionManager` | `approved_at / materialized_at / activated_at / reindexed_at`、`materialize_status / reindex_status / verify_status / sample_query_success` | 不得单独决定 runtime 放行 |
| `vector_alias_registry` | `ReindexWorker` 只生成 candidate；`VerifyGate` 负责放行 | `VerifyGate` | `active_alias / candidate_alias / active_snapshot_version / candidate_snapshot_version / active_embedding_version / candidate_embedding_version / verify_status / sample_query_success / active_since` | `reindex job` 不得直接 flip alias |
| `reindex_jobs` / `verify_jobs` | `JobDispatcher` 负责入队；`ReindexWorker` / `VerifyGate` 负责执行；`RecoveryService` 负责 reclaim | 运行中的持有 worker；reclaim 时由 `RecoveryService` CAS 接管 | `status / worker_id / attempt_no / heartbeat_at / lease_expires_at / started_at / finished_at` | 不得在拿不到 lease 时写 heartbeat、finish 或 flip 业务状态 |
| `scene_run_states` / `chapter_states` | `Orchestrator` / `Archiver` / `Aggregator` | 各自 runtime service | runtime 指针、计数器、gate | 不得回写作者卡 |
| `idempotency_keys` / `operation_logs` / `reconcile_faults` | 所有状态写路径 | `VersionManager` / `VerifyGate` / `PromotionService` / `ReindexWorker` / `ReconcileService` 各按职责 | 幂等占位、`worker_id / attempt_no / heartbeat_at / lease_expires_at`、操作审计、故障记录 | 不得退化成仅内存态或日志打印 |

- 所有状态变更 **MUST** 先 upsert `idempotency_keys`，再 append `operation_logs`；若发现对象表 / registry / alias / soft-link 不一致，必须写 `reconcile_faults`。  
- direct-read immediate 顺序固定为：**写对象行 -> 关闭旧 active -> 激活新 active / runtime_eligible -> 写 `version_registry` -> 标记 `idempotency_keys.status = succeeded` -> commit**。  
- direct-read `future_effective` 顺序固定为：**写 inactive candidate -> 写 `version_registry` pending -> 保留旧 active 服务 -> 到 `effective_at` 后再执行 close old active + activate / runtime_eligible + registry finalize**。  
- vector immediate 顺序固定为：**写 inactive candidate -> 写 `version_registry` pending -> reindex -> verify -> alias flip + close old active + activate / runtime_eligible -> `version_registry` finalize -> 标记幂等成功**。  
- vector `future_effective` 顺序固定为：**写 inactive candidate -> reindex -> verify -> 记录 `verify_status = succeeded` 但保持 `active = 0 / runtime_eligible = 0 / basis = future_effective` -> 到 `effective_at` 后再做 alias flip + activate / runtime 放行**。  
- `runtime_eligibility_basis` **不得**在所有表上共用“宽松枚举”。正向放行 basis 只允许与 primary read channel 对应：structured = `direct_read`；vector = `vector_ready`；是否支持 `future_effective` 由对象表逐表声明。  
- runtime 读取的 source of truth 固定为：**对象表 + `vector_alias_registry`**。若它们与 `version_registry` 不一致，运行时以对象表 / active alias 为准，同时进入 reconcile，不允许由 registry 反向覆盖对象表。

### 4.7.1 SQLite 单机写入 recipe（single-writer 的执行机制）

- 所有会同时涉及“关闭旧 active / 打开 candidate / 改 current pointers / finalize `idempotency_keys` / alias flip”的状态写路径，**MUST** 在 SQLite 内以 `BEGIN IMMEDIATE` 起事务；不允许先 `SELECT` 再在事务外拼接决定，最后用普通 autocommit 分步写回。  
- 应用层 **MUST** 再加一层语义锁：同一 `chapter_id`、`scene_id`、`object_type:lineage_key`、`alias_scope` 的写入必须串行。单次事务若同时涉及多把锁，获取顺序固定为 `chapter:{chapter_id}` -> `scene:{scene_id}` -> `lineage:{object_type}:{lineage_key}` -> `alias:{alias_scope}`；不得反向获取。  
- `VersionManager`、`VerifyGate`、`PromotionService`、`Archiver`、`Aggregator`、`Orchestrator` 必须复用同一个 `with_serialized_write(...)` 帮助函数；该函数负责：获取排序后的应用层 mutex、启动 `BEGIN IMMEDIATE`、执行状态变更、落 `operation_logs`、提交或回滚。  
- 对同一 `lineage_key` 或 `alias_scope` 的并发第二写者，服务层只能“等待短暂 backoff 后重试”或显式返回 `409 WRITE_SERIALIZATION_CONFLICT`；不得让两个写者分别读到同一个旧 active，再各自关闭 / 打开不同 candidate。  
- `close old active + activate candidate + current pointer update + idempotency finalize` 必须在**同一提交边界**内完成；任何一步失败都整体回滚。SQLite 的 `busy_timeout` 只解决数据库层等待，不代替上述语义锁。  
- `promotion_service` 与 `verify_gate` 也遵守同一 recipe：它们不得“先在事务外判定 ready，再进事务只做 flip”；ready 判定所依赖的 row / alias 读取与最终 flip 必须位于同一 `BEGIN IMMEDIATE` 写事务窗口内。

### 4.7.2 worker lease、heartbeat 与 stuck-job reclaim

- 凡生命周期会跨出单个 SQLite 提交边界的状态操作，**MUST** 有 lease tuple：`worker_id`、`attempt_no`、`heartbeat_at`、`lease_expires_at`。本版最小覆盖面固定为 `idempotency_keys(status = 'started')`、`reindex_jobs`、`verify_jobs`；实现者**不得**只在内存里记“哪个 worker 正在跑”。
- claim 规则固定为 compare-and-swap：`queued -> running`、或 `running / started` 且 `lease_expires_at <= now` 的过期行，必须在同一 `BEGIN IMMEDIATE` 事务内原子改成“由新 `worker_id` 持有的 attempt”。claim 成功后：`attempt_no += 1`（作业首次 claim 从 0 变 1；idempotency 首次开始执行为 1）、`heartbeat_at = now`、`lease_expires_at = now + lease_ttl`。
- heartbeat 规则固定为：持有 lease 的 worker 必须在 `heartbeat_interval < lease_ttl` 的节奏内刷新 `heartbeat_at / lease_expires_at`；任何 heartbeat / finish / fail / success 回写都必须附带 `(job_id 或 idempotency_key, worker_id, attempt_no, status='running'或'started')` 条件。若 0 行受影响，视为 lease 已丢失，旧 worker 必须停止后续写入，不得再提交 finish 或 flip。
- recovery sweep 固定由 `RecoveryService.recover_stuck_jobs(now)` 执行；触发点至少包括：进程启动后、worker poll 前、以及显式 `POST /api/v1/runtime/recovery/sweep`。它必须扫描 `reindex_jobs / verify_jobs WHERE status = 'running' AND lease_expires_at <= now` 与 `idempotency_keys WHERE status = 'started' AND lease_expires_at <= now`。
- reclaim 动作固定为两段式：① 若对应 job / request 仍可安全重跑，则在 sweep 事务内清旧 lease、递增 `attempt_no`、把作业改回 `queued`（或把同一语义 idempotency key 重新 claim 给新的 worker），并 append `operation_logs(event_type = 'lease_reclaim')`；② 若已超过 `job_runtime.max_reclaim_attempts`、下游状态已不可判定、或发现 partial side effect 与 registry / alias 不一致，则把 job / key 置 `failed`、清空 lease 字段、写 `reconcile_faults`，必要时创建 `human_review_event`。
- HTTP 层对 `X-Idempotency-Key` 的 stuck key 也遵守同一 reclaim 语义：`status = 'started'` 但 lease 已过期时，不得永久返回 `409`；服务端必须先尝试 reclaim，再决定继续执行或返回显式失败。**“started 永久占坑” 是非法实现。**

### 4.8 SQLite + Chroma 一致性边界（vector alias 单一逻辑源）

- `vector_alias_registry` 是**唯一逻辑 alias source of truth**；它必须同时保存 `object_type / scope / scope_ref_id / collection_family / active_alias / candidate_alias / active_snapshot_version / candidate_snapshot_version / active_embedding_version / candidate_embedding_version`。其中 `collection_family` 只是命名族；真正表示具体 collection 名的只有 `active_alias / candidate_alias`，不得再要求向量库维护第二套可变 alias 指针。
- runtime 向量查询路径固定为：**SQLite 读取 `alias_scope -> active_alias` -> 以该 collection 名查询 Chroma**。Chroma 只保存 candidate / active collection 本体；不得在 Chroma 内再维护一套能覆盖 SQLite 的“隐藏 alias 映射”。
- `embedding_version` **不再允许是单值语义**。当 active alias 仍在旧 embedding、candidate alias 已按新 embedding 重建时，必须分别记录 `active_embedding_version` 与 `candidate_embedding_version`；snapshot version 同理按 active/candidate 分栏保存，供 rebuild / rollback / blame 诊断使用。
- 因此本文所谓“alias flip”，定义为 **SQLite 内 `vector_alias_registry` 行的切换 + runtime 读缓存失效**。candidate collection 的创建 / 写入是 reindex side effect；collection 是否存在、内容是否可查，由 verify / reconcile 校验，但不再假定 SQLite 与 Chroma 存在真正的跨库同事务。
- `VerifyGate` 校验的对象固定是 `candidate_alias` 对应的具体 collection；成功后只在 SQLite 里切 `active_alias / candidate_alias` 与对象表状态。若 collection 缺失、top_k 泄漏旧 collection、或 registry 与实际 collection 集合不一致，必须写 `reconcile_faults(fault_scope = 'alias_mismatch')`。
- 运行时若使用 alias 读缓存，缓存必须是 read-through，且 **MUST** 以 `vector_alias_registry.updated_at` 失效；本地缓存 TTL 不得超过 5 秒。任何缓存命中都不得绕过 registry 校验。

---

## 5. SQLite 物理模型（可直接转 Alembic 初始迁移）

> **删除与退役说明**：本 DDL 故意把关键 current-pointer / lineage 引用做成 `RESTRICT`。结果是：`ON DELETE CASCADE` 只适用于“尚未形成运行产物”的局部清理；一旦 scene / chapter 已产生 bundle / draft / final / memory / review / attempt 等下游引用，物理删除就会被 FK 阻止。这是设计目标，不是实现 bug。API 层默认不提供通用 DELETE；退役统一走状态流与 supersede。

```sql
PRAGMA foreign_keys = ON;

CREATE TABLE chapter_goals (
  chapter_id TEXT PRIMARY KEY,
  planned_scene_count INTEGER,
  mid_aggregate_enabled INTEGER NOT NULL DEFAULT 0 CHECK(mid_aggregate_enabled IN (0,1)),
  chapter_goal TEXT NOT NULL,
  main_plot_push TEXT,
  emotional_target TEXT,
  ending_effect TEXT,
  must_not TEXT,
  notes TEXT,
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE TABLE scene_cards (
  scene_id TEXT PRIMARY KEY,
  chapter_id TEXT NOT NULL REFERENCES chapter_goals(chapter_id) ON DELETE CASCADE,
  scene_seq INTEGER NOT NULL,
  pov TEXT,
  pov_character_id TEXT,
  onstage_chars_json TEXT NOT NULL DEFAULT '[]',
  resolved_relation_id TEXT,
  location TEXT,
  scene_goal TEXT NOT NULL,
  surface_conflict TEXT,
  hidden_tension TEXT,
  beats_json TEXT NOT NULL,
  must_include_text TEXT,
  forbidden_text TEXT,
  exit_change TEXT,
  hook TEXT,
  target_length_band TEXT,
  scene_type TEXT CHECK(scene_type IN ('probe','reunion','bridge','mixed','action','climax_lite')),
  is_chapter_last INTEGER NOT NULL DEFAULT 0 CHECK(is_chapter_last IN (0,1)),
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  UNIQUE(chapter_id, scene_seq)
);

CREATE TABLE scene_run_states (
  scene_id TEXT PRIMARY KEY REFERENCES scene_cards(scene_id) ON DELETE CASCADE,
  scene_status TEXT NOT NULL DEFAULT 'ready' CHECK(scene_status IN (
    'ready','bundle_built','drafted','hard_checked','hard_passed',
    'hard_failed_minor','hard_failed_major','hard_failed_critical',
    'style_rewritten','soft_checked','approved','waived',
    'human_review_required','archived','abandoned'
  )),
  current_bundle_id TEXT REFERENCES scene_bundles(bundle_id) ON DELETE RESTRICT,
  current_bundle_hash TEXT,
  current_neutral_draft_row_id TEXT REFERENCES scene_drafts(row_id) ON DELETE RESTRICT,
  current_style_draft_row_id TEXT REFERENCES scene_drafts(row_id) ON DELETE RESTRICT,
  current_final_scene_row_id TEXT REFERENCES final_scenes(row_id) ON DELETE RESTRICT,
  current_qc_report_id TEXT REFERENCES qc_reports(report_id) ON DELETE RESTRICT,
  current_human_review_event_id TEXT REFERENCES human_review_events(event_id) ON DELETE RESTRICT,
  bundle_build_count INTEGER NOT NULL DEFAULT 0,
  hard_partial_rewrite_count INTEGER NOT NULL DEFAULT 0,
  hard_full_rewrite_count INTEGER NOT NULL DEFAULT 0,
  soft_patch_count INTEGER NOT NULL DEFAULT 0,
  total_attempt_count INTEGER NOT NULL DEFAULT 0,
  attempt_budget INTEGER NOT NULL DEFAULT 4,
  repeat_issue_key TEXT,
  repeat_issue_count INTEGER NOT NULL DEFAULT 0,
  last_resolution_code TEXT,
  last_error_code TEXT,
  updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE TABLE chapter_states (
  chapter_id TEXT PRIMARY KEY REFERENCES chapter_goals(chapter_id) ON DELETE CASCADE,
  chapter_passed_scene_count INTEGER NOT NULL DEFAULT 0,
  chapter_backfill_pending_count INTEGER NOT NULL DEFAULT 0 CHECK(chapter_backfill_pending_count >= 0),
  mid_aggregate_enabled_effective INTEGER NOT NULL DEFAULT 0 CHECK(mid_aggregate_enabled_effective IN (0,1)),
  aggregate_block_reason TEXT NOT NULL DEFAULT 'none' CHECK(aggregate_block_reason IN ('none','blocked_waiting_backfill','manual_hold')),
  last_interim_memory_row_id TEXT REFERENCES chapter_memories(row_id) ON DELETE RESTRICT,
  last_final_memory_row_id TEXT REFERENCES chapter_memories(row_id) ON DELETE RESTRICT,
  manual_hold_reason TEXT,
  updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE TABLE review_items (
  review_id TEXT PRIMARY KEY,
  item_type TEXT NOT NULL CHECK(item_type IN (
    'style_observation','style_rule_set','banned_rule_cluster',
    'voice_card_candidate','relation_card_candidate','world_rule',
    'calibration_candidate','foreshadow_open','foreshadow_touch','foreshadow_resolve',
    'scene_summary','chapter_summary'
  )),
  scene_id TEXT REFERENCES scene_cards(scene_id) ON DELETE RESTRICT,
  chapter_id TEXT REFERENCES chapter_goals(chapter_id) ON DELETE RESTRICT,
  candidate_text TEXT,
  candidate_payload_json TEXT NOT NULL DEFAULT '{}',
  evidence_refs_json TEXT NOT NULL DEFAULT '[]',
  evidence_count INTEGER,
  support_spread TEXT CHECK(support_spread IN ('single_chunk','multi_chunk','cross_chapter')),
  extractor_consensus TEXT CHECK(extractor_consensus IN ('low','medium','high')),
  self_confidence_band TEXT CHECK(self_confidence_band IN ('low','medium','high')),
  why TEXT,
  target_collection TEXT GENERATED ALWAYS AS (
    CASE item_type
      WHEN 'style_observation' THEN 'style_observations'
      WHEN 'style_rule_set' THEN 'style_rules'
      WHEN 'banned_rule_cluster' THEN 'banned_rule_clusters'
      WHEN 'voice_card_candidate' THEN 'voice_cards'
      WHEN 'relation_card_candidate' THEN 'relation_cards'
      WHEN 'world_rule' THEN 'world_rules'
      WHEN 'calibration_candidate' THEN 'calibration_lines'
      WHEN 'foreshadow_open' THEN 'foreshadow_tracker'
      WHEN 'foreshadow_touch' THEN 'foreshadow_tracker'
      WHEN 'foreshadow_resolve' THEN 'foreshadow_tracker'
      WHEN 'scene_summary' THEN 'scene_memories'
      WHEN 'chapter_summary' THEN 'chapter_memories'
    END
  ) STORED,
  materialize_action TEXT NOT NULL DEFAULT 'insert' CHECK(materialize_action IN ('insert','update_version','merge')),
  merge_target_row_id TEXT,
  approved_item_row_id TEXT,
  approved_item_id TEXT,
  approved_at TEXT,
  materialized_at TEXT,
  activated_at TEXT,
  reindexed_at TEXT,
  materialize_status TEXT NOT NULL DEFAULT 'pending' CHECK(materialize_status IN ('pending','succeeded','failed')),
  reindex_status TEXT NOT NULL DEFAULT 'none' CHECK(reindex_status IN ('none','queued','succeeded','failed','n_a')),
  retry_count INTEGER NOT NULL DEFAULT 0,
  max_retry INTEGER NOT NULL DEFAULT 2,
  last_retry_at TEXT,
  active_on_approve INTEGER NOT NULL DEFAULT 1 CHECK(active_on_approve IN (0,1)),
  revision_no INTEGER NOT NULL DEFAULT 0,
  status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','approved','rejected','revised')),
  reviewer_comment TEXT,
  materialize_error_text TEXT,
  reindex_error_text TEXT,
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  CHECK (scene_id IS NULL OR chapter_id IS NOT NULL)
);

CREATE TABLE style_rules (
  row_id TEXT PRIMARY KEY,
  style_rule_set_id TEXT NOT NULL,
  version INTEGER NOT NULL CHECK(version > 0),
  scope TEXT NOT NULL DEFAULT 'global' CHECK(scope IN ('global','chapter','scene')),
  scope_ref_id TEXT,
  rules_json TEXT NOT NULL,
  digest_text TEXT NOT NULL,
  notes TEXT,
  active_flag INTEGER NOT NULL DEFAULT 0 CHECK(active_flag IN (0,1)),
  runtime_eligible INTEGER NOT NULL DEFAULT 0 CHECK(runtime_eligible IN (0,1)),
  runtime_eligibility_basis TEXT NOT NULL DEFAULT 'stage_blocked' CHECK(runtime_eligibility_basis IN ('direct_read','stage_blocked','manual_hold','future_effective')),
  effective_at TEXT,
  source_review_id TEXT REFERENCES review_items(review_id) ON DELETE RESTRICT,
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  CHECK ((scope = 'global' AND scope_ref_id IS NULL) OR (scope IN ('chapter','scene') AND scope_ref_id IS NOT NULL)),
  CHECK (NOT (active_flag = 0 AND runtime_eligible = 1)),
  CHECK (runtime_eligible = 0 OR runtime_eligibility_basis = 'direct_read'),
  CHECK (runtime_eligibility_basis <> 'future_effective' OR effective_at IS NOT NULL),
  UNIQUE(style_rule_set_id, version)
);

CREATE TABLE banned_rule_clusters (
  row_id TEXT PRIMARY KEY,
  banned_cluster_id TEXT NOT NULL,
  version INTEGER NOT NULL CHECK(version > 0),
  scope TEXT NOT NULL DEFAULT 'global' CHECK(scope IN ('global','chapter','scene')),
  scope_ref_id TEXT,
  cluster_name TEXT NOT NULL,
  scene_types_json TEXT NOT NULL DEFAULT '[]',
  rules_json TEXT NOT NULL,
  digest_text TEXT NOT NULL,
  notes TEXT,
  active_flag INTEGER NOT NULL DEFAULT 0 CHECK(active_flag IN (0,1)),
  runtime_eligible INTEGER NOT NULL DEFAULT 0 CHECK(runtime_eligible IN (0,1)),
  runtime_eligibility_basis TEXT NOT NULL DEFAULT 'stage_blocked' CHECK(runtime_eligibility_basis IN ('direct_read','stage_blocked','manual_hold','future_effective')),
  effective_at TEXT,
  source_review_id TEXT REFERENCES review_items(review_id) ON DELETE RESTRICT,
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  CHECK ((scope = 'global' AND scope_ref_id IS NULL) OR (scope IN ('chapter','scene') AND scope_ref_id IS NOT NULL)),
  CHECK (NOT (active_flag = 0 AND runtime_eligible = 1)),
  CHECK (runtime_eligible = 0 OR runtime_eligibility_basis = 'direct_read'),
  CHECK (runtime_eligibility_basis <> 'future_effective' OR effective_at IS NOT NULL),
  UNIQUE(banned_cluster_id, version)
);

CREATE TABLE voice_cards (
  row_id TEXT PRIMARY KEY,
  voice_id TEXT NOT NULL,
  version INTEGER NOT NULL CHECK(version > 0),
  character_id TEXT NOT NULL,
  sentence_rhythm TEXT NOT NULL,
  dialogue_tone TEXT NOT NULL,
  pressure_shift TEXT NOT NULL,
  taboo_patterns_json TEXT NOT NULL DEFAULT '[]',
  full_card_text TEXT NOT NULL,
  digest_text TEXT NOT NULL,
  active_flag INTEGER NOT NULL DEFAULT 0 CHECK(active_flag IN (0,1)),
  runtime_eligible INTEGER NOT NULL DEFAULT 0 CHECK(runtime_eligible IN (0,1)),
  runtime_eligibility_basis TEXT NOT NULL DEFAULT 'stage_blocked' CHECK(runtime_eligibility_basis IN ('direct_read','stage_blocked','manual_hold','future_effective')),
  effective_at TEXT,
  source_review_id TEXT REFERENCES review_items(review_id) ON DELETE RESTRICT,
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  CHECK (NOT (active_flag = 0 AND runtime_eligible = 1)),
  CHECK (runtime_eligible = 0 OR runtime_eligibility_basis = 'direct_read'),
  CHECK (runtime_eligibility_basis <> 'future_effective' OR effective_at IS NOT NULL),
  UNIQUE(voice_id, version)
);

CREATE TABLE relation_cards (
  row_id TEXT PRIMARY KEY,
  relation_id TEXT NOT NULL,
  version INTEGER NOT NULL CHECK(version > 0),
  char_a TEXT NOT NULL,
  char_b TEXT NOT NULL,
  pair_key TEXT NOT NULL,
  surface_relation TEXT,
  hidden_tension TEXT NOT NULL,
  power_balance TEXT,
  trigger_cues TEXT,
  taboo_topics TEXT,
  current_phase TEXT NOT NULL,
  digest_text TEXT NOT NULL,
  notes_for_writer TEXT,
  active_flag INTEGER NOT NULL DEFAULT 0 CHECK(active_flag IN (0,1)),
  runtime_eligible INTEGER NOT NULL DEFAULT 0 CHECK(runtime_eligible IN (0,1)),
  runtime_eligibility_basis TEXT NOT NULL DEFAULT 'stage_blocked' CHECK(runtime_eligibility_basis IN ('direct_read','stage_blocked','manual_hold','future_effective')),
  effective_at TEXT,
  source_review_id TEXT REFERENCES review_items(review_id) ON DELETE RESTRICT,
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  CHECK (NOT (active_flag = 0 AND runtime_eligible = 1)),
  CHECK (runtime_eligible = 0 OR runtime_eligibility_basis = 'direct_read'),
  CHECK (runtime_eligibility_basis <> 'future_effective' OR effective_at IS NOT NULL),
  UNIQUE(relation_id, version)
);

CREATE TABLE world_rules (
  row_id TEXT PRIMARY KEY,
  world_rule_id TEXT NOT NULL,
  version INTEGER NOT NULL CHECK(version > 0),
  rule_text TEXT NOT NULL,
  digest_text TEXT NOT NULL,
  rule_tier TEXT NOT NULL CHECK(rule_tier IN ('hard_rule','soft_rule')),
  scope TEXT NOT NULL CHECK(scope IN ('global','chapter','scene')),
  scope_ref_id TEXT,
  domain TEXT NOT NULL CHECK(domain IN ('world','power','institution','taboo','cost')),
  allow_exception_mode TEXT NOT NULL DEFAULT 'none' CHECK(allow_exception_mode IN ('none','explicit_exception_only')),
  exception_to_rule_id TEXT,
  effective_mode TEXT NOT NULL DEFAULT 'immediate' CHECK(effective_mode IN ('immediate','future_effective')),
  effective_at TEXT,
  expires_at TEXT,
  active_flag INTEGER NOT NULL DEFAULT 0 CHECK(active_flag IN (0,1)),
  runtime_eligible INTEGER NOT NULL DEFAULT 0 CHECK(runtime_eligible IN (0,1)),
  runtime_eligibility_basis TEXT NOT NULL DEFAULT 'stage_blocked' CHECK(runtime_eligibility_basis IN ('direct_read','stage_blocked','manual_hold','future_effective')),
  source_review_id TEXT REFERENCES review_items(review_id) ON DELETE RESTRICT,
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  CHECK ((scope = 'global' AND scope_ref_id IS NULL) OR (scope IN ('chapter','scene') AND scope_ref_id IS NOT NULL)),
  CHECK (NOT (active_flag = 0 AND runtime_eligible = 1)),
  CHECK (runtime_eligible = 0 OR runtime_eligibility_basis = 'direct_read'),
  CHECK (runtime_eligibility_basis <> 'future_effective' OR effective_at IS NOT NULL),
  CHECK (effective_mode <> 'future_effective' OR effective_at IS NOT NULL),
  CHECK (expires_at IS NULL OR effective_at IS NULL OR expires_at >= effective_at),
  UNIQUE(world_rule_id, version)
);

CREATE TABLE style_observations (
  row_id TEXT PRIMARY KEY,
  style_observation_id TEXT NOT NULL,
  version INTEGER NOT NULL CHECK(version > 0),
  category TEXT NOT NULL CHECK(category IN ('rhythm','emotion','dialogue','ending','image','monologue')),
  candidate_text TEXT NOT NULL,
  evidence_excerpt TEXT,
  evidence_scope TEXT CHECK(evidence_scope IN ('single_chunk','multi_chunk')),
  scope TEXT NOT NULL DEFAULT 'global' CHECK(scope IN ('global','chapter','scene')),
  scope_ref_id TEXT,
  scene_types_json TEXT NOT NULL DEFAULT '[]',
  tags_json TEXT NOT NULL DEFAULT '[]',
  active_flag INTEGER NOT NULL DEFAULT 0 CHECK(active_flag IN (0,1)),
  runtime_eligible INTEGER NOT NULL DEFAULT 0 CHECK(runtime_eligible IN (0,1)),
  runtime_eligibility_basis TEXT NOT NULL DEFAULT 'stage_blocked' CHECK(runtime_eligibility_basis IN ('vector_ready','stage_blocked','manual_hold','future_effective')),
  effective_at TEXT,
  source_review_id TEXT REFERENCES review_items(review_id) ON DELETE RESTRICT,
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  CHECK ((scope = 'global' AND scope_ref_id IS NULL) OR (scope IN ('chapter','scene') AND scope_ref_id IS NOT NULL)),
  CHECK (NOT (active_flag = 0 AND runtime_eligible = 1)),
  CHECK (runtime_eligible = 0 OR runtime_eligibility_basis = 'vector_ready'),
  CHECK (runtime_eligibility_basis <> 'future_effective' OR effective_at IS NOT NULL),
  UNIQUE(style_observation_id, version)
);

CREATE TABLE calibration_lines (
  row_id TEXT PRIMARY KEY,
  calibration_line_id TEXT NOT NULL,
  version INTEGER NOT NULL CHECK(version > 0),
  line_text TEXT NOT NULL,
  tag TEXT NOT NULL CHECK(tag IN ('opening','ending','restraint','dialogue','image')),
  why_it_works TEXT,
  source_scene_id TEXT REFERENCES scene_cards(scene_id) ON DELETE RESTRICT,
  source_type TEXT NOT NULL CHECK(source_type IN ('self_written','approved_final_scene')),
  reject_if TEXT,
  scope TEXT NOT NULL DEFAULT 'global' CHECK(scope IN ('global','chapter','scene')),
  scope_ref_id TEXT,
  scene_types_json TEXT NOT NULL DEFAULT '[]',
  active_flag INTEGER NOT NULL DEFAULT 0 CHECK(active_flag IN (0,1)),
  runtime_eligible INTEGER NOT NULL DEFAULT 0 CHECK(runtime_eligible IN (0,1)),
  runtime_eligibility_basis TEXT NOT NULL DEFAULT 'stage_blocked' CHECK(runtime_eligibility_basis IN ('vector_ready','stage_blocked','manual_hold','future_effective')),
  effective_at TEXT,
  source_review_id TEXT REFERENCES review_items(review_id) ON DELETE RESTRICT,
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  CHECK ((scope = 'global' AND scope_ref_id IS NULL) OR (scope IN ('chapter','scene') AND scope_ref_id IS NOT NULL)),
  CHECK (NOT (active_flag = 0 AND runtime_eligible = 1)),
  CHECK (runtime_eligible = 0 OR runtime_eligibility_basis = 'vector_ready'),
  CHECK (runtime_eligibility_basis <> 'future_effective' OR effective_at IS NOT NULL),
  UNIQUE(calibration_line_id, version)
);

CREATE TABLE scene_bundles (
  bundle_id TEXT PRIMARY KEY,
  scene_id TEXT NOT NULL REFERENCES scene_cards(scene_id) ON DELETE CASCADE,
  execution_mode TEXT NOT NULL CHECK(execution_mode IN ('P0_manual','P1_scripted','P2_native')),
  supersedes_bundle_id TEXT REFERENCES scene_bundles(bundle_id) ON DELETE RESTRICT,
  bundle_snapshot_hash TEXT,
  hash_contract_version TEXT NOT NULL DEFAULT 'BSHASH_v1',
  hash_alg TEXT NOT NULL DEFAULT 'sha256',
  stage_allowlist_name TEXT NOT NULL,
  source_version_refs_json TEXT NOT NULL,
  resolved_ref_ids_json TEXT NOT NULL,
  ordered_injections_json TEXT NOT NULL,
  inline_digests_json TEXT NOT NULL,
  frozen_snapshot_json TEXT NOT NULL,
  budget_check_json TEXT NOT NULL DEFAULT '{}',
  created_by_action TEXT NOT NULL DEFAULT 'bundle_build' CHECK(created_by_action IN ('bundle_build','bundle_rebuild','manual_import')),
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  CHECK (
    bundle_snapshot_hash IS NULL OR (
      length(bundle_snapshot_hash) = 64 AND
      bundle_snapshot_hash = lower(bundle_snapshot_hash) AND
      bundle_snapshot_hash NOT GLOB '*[^0-9a-f]*'
    )
  ),
  CHECK (execution_mode = 'P0_manual' OR bundle_snapshot_hash IS NOT NULL),
  CHECK (hash_contract_version = 'BSHASH_v1'),
  CHECK (hash_alg = 'sha256')
);

CREATE TABLE scene_drafts (
  row_id TEXT PRIMARY KEY,
  draft_lineage_id TEXT NOT NULL,
  scene_id TEXT NOT NULL REFERENCES scene_cards(scene_id) ON DELETE CASCADE,
  stage TEXT NOT NULL CHECK(stage IN ('neutral_draft','style_draft')),
  version INTEGER NOT NULL CHECK(version > 0),
  execution_mode TEXT NOT NULL CHECK(execution_mode IN ('P0_manual','P1_scripted','P2_native')),
  source_bundle_id TEXT NOT NULL REFERENCES scene_bundles(bundle_id) ON DELETE RESTRICT,
  bundle_snapshot_hash TEXT,
  parent_draft_row_id TEXT REFERENCES scene_drafts(row_id) ON DELETE RESTRICT,
  supersedes_draft_row_id TEXT REFERENCES scene_drafts(row_id) ON DELETE RESTRICT,
  content TEXT NOT NULL,
  word_count INTEGER NOT NULL,
  style_length_lock TEXT CHECK(style_length_lock IN ('strict_5','default_8','action_10')),
  rewrite_note TEXT,
  status TEXT NOT NULL CHECK(status IN ('generated','rewritten','abandoned','superseded')),
  active_flag INTEGER NOT NULL DEFAULT 1 CHECK(active_flag IN (0,1)),
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  CHECK (
    bundle_snapshot_hash IS NULL OR (
      length(bundle_snapshot_hash) = 64 AND
      bundle_snapshot_hash = lower(bundle_snapshot_hash) AND
      bundle_snapshot_hash NOT GLOB '*[^0-9a-f]*'
    )
  ),
  CHECK (execution_mode = 'P0_manual' OR bundle_snapshot_hash IS NOT NULL),
  UNIQUE(draft_lineage_id, version)
);

CREATE TABLE qc_reports (
  report_id TEXT PRIMARY KEY,
  scene_id TEXT NOT NULL REFERENCES scene_cards(scene_id) ON DELETE CASCADE,
  draft_row_id TEXT NOT NULL REFERENCES scene_drafts(row_id) ON DELETE CASCADE,
  source_bundle_id TEXT NOT NULL REFERENCES scene_bundles(bundle_id) ON DELETE RESTRICT,
  qc_type TEXT NOT NULL CHECK(qc_type IN ('hard_qc','soft_qc')),
  resolution_code TEXT NOT NULL CHECK(resolution_code IN (
    'hard_pass','hard_fail_partial','hard_fail_full','hard_block_human',
    'soft_pass','soft_waive','soft_fail_partial','soft_block_human'
  )),
  pass_flag INTEGER NOT NULL CHECK(pass_flag IN (0,1)),
  severity TEXT CHECK(severity IN ('minor','major','critical')),
  issues_json TEXT NOT NULL DEFAULT '[]',
  next_action TEXT NOT NULL CHECK(next_action IN ('pass','partial_rewrite','full_rewrite','human_review_required','pass_with_notes')),
  rewrite_brief_json TEXT NOT NULL DEFAULT '[]',
  carry_forward_note INTEGER NOT NULL DEFAULT 0 CHECK(carry_forward_note IN (0,1)),
  note_scope TEXT CHECK(note_scope IN ('none','style_only','continuity')),
  carry_note_text TEXT,
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  CHECK (NOT (pass_flag = 1 AND next_action IN ('partial_rewrite','full_rewrite','human_review_required'))),
  CHECK (NOT (pass_flag = 0 AND next_action IN ('pass','pass_with_notes'))),
  CHECK (NOT (next_action = 'pass_with_notes' AND resolution_code <> 'soft_waive'))
);

CREATE TABLE final_scenes (
  row_id TEXT PRIMARY KEY,
  final_scene_id TEXT NOT NULL,
  scene_id TEXT NOT NULL REFERENCES scene_cards(scene_id) ON DELETE CASCADE,
  version INTEGER NOT NULL CHECK(version > 0),
  execution_mode TEXT NOT NULL CHECK(execution_mode IN ('P0_manual','P1_scripted','P2_native')),
  source_bundle_id TEXT NOT NULL REFERENCES scene_bundles(bundle_id) ON DELETE RESTRICT,
  bundle_snapshot_hash TEXT,
  parent_style_draft_row_id TEXT REFERENCES scene_drafts(row_id) ON DELETE RESTRICT,
  supersedes_final_scene_row_id TEXT REFERENCES final_scenes(row_id) ON DELETE RESTRICT,
  qc_report_id TEXT REFERENCES qc_reports(report_id) ON DELETE RESTRICT,
  content TEXT NOT NULL,
  word_count INTEGER NOT NULL,
  status TEXT NOT NULL CHECK(status IN ('approved','waived','abandoned')),
  active_flag INTEGER NOT NULL DEFAULT 0 CHECK(active_flag IN (0,1)),
  runtime_eligible INTEGER NOT NULL DEFAULT 0 CHECK(runtime_eligible IN (0,1)),
  runtime_eligibility_basis TEXT NOT NULL DEFAULT 'stage_blocked' CHECK(runtime_eligibility_basis IN ('vector_ready','stage_blocked','manual_hold')),
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  CHECK (
    bundle_snapshot_hash IS NULL OR (
      length(bundle_snapshot_hash) = 64 AND
      bundle_snapshot_hash = lower(bundle_snapshot_hash) AND
      bundle_snapshot_hash NOT GLOB '*[^0-9a-f]*'
    )
  ),
  CHECK (execution_mode = 'P0_manual' OR bundle_snapshot_hash IS NOT NULL),
  CHECK (NOT (active_flag = 0 AND runtime_eligible = 1)),
  CHECK (runtime_eligible = 0 OR runtime_eligibility_basis = 'vector_ready'),
  UNIQUE(final_scene_id, version)
);

CREATE TABLE scene_memories (
  row_id TEXT PRIMARY KEY,
  scene_id TEXT NOT NULL REFERENCES scene_cards(scene_id) ON DELETE CASCADE,
  version INTEGER NOT NULL CHECK(version > 0),
  final_scene_row_id TEXT NOT NULL REFERENCES final_scenes(row_id) ON DELETE RESTRICT,
  source_bundle_id TEXT NOT NULL REFERENCES scene_bundles(bundle_id) ON DELETE RESTRICT,
  summary TEXT NOT NULL,
  state_changes_json TEXT NOT NULL DEFAULT '[]',
  foreshadow_delta_json TEXT NOT NULL DEFAULT '{"opened":[],"touched":[],"resolved":[]}',
  carry_notes_json TEXT NOT NULL DEFAULT '[]',
  next_hook TEXT,
  active_flag INTEGER NOT NULL DEFAULT 0 CHECK(active_flag IN (0,1)),
  runtime_eligible INTEGER NOT NULL DEFAULT 0 CHECK(runtime_eligible IN (0,1)),
  runtime_eligibility_basis TEXT NOT NULL DEFAULT 'stage_blocked' CHECK(runtime_eligibility_basis IN ('direct_read','stage_blocked','manual_hold')),
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  CHECK (NOT (active_flag = 0 AND runtime_eligible = 1)),
  CHECK (runtime_eligible = 0 OR runtime_eligibility_basis = 'direct_read'),
  UNIQUE(scene_id, version)
);

CREATE TABLE chapter_memories (
  row_id TEXT PRIMARY KEY,
  chapter_id TEXT NOT NULL REFERENCES chapter_goals(chapter_id) ON DELETE CASCADE,
  aggregate_stage TEXT NOT NULL CHECK(aggregate_stage IN ('interim','final')),
  version INTEGER NOT NULL CHECK(version > 0),
  source_scene_ids_json TEXT NOT NULL DEFAULT '[]',
  chapter_result TEXT NOT NULL,
  core_shift TEXT NOT NULL,
  foreshadow_delta_text TEXT,
  next_chapter_hook TEXT,
  do_not_repeat TEXT,
  supersedes_memory_row_id TEXT REFERENCES chapter_memories(row_id) ON DELETE RESTRICT,
  active_flag INTEGER NOT NULL DEFAULT 0 CHECK(active_flag IN (0,1)),
  runtime_eligible INTEGER NOT NULL DEFAULT 0 CHECK(runtime_eligible IN (0,1)),
  runtime_eligibility_basis TEXT NOT NULL DEFAULT 'stage_blocked' CHECK(runtime_eligibility_basis IN ('direct_read','stage_blocked','manual_hold','future_effective')),
  effective_at TEXT,
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  CHECK (NOT (active_flag = 0 AND runtime_eligible = 1)),
  CHECK (runtime_eligible = 0 OR runtime_eligibility_basis = 'direct_read'),
  CHECK (runtime_eligibility_basis <> 'future_effective' OR effective_at IS NOT NULL),
  CHECK (aggregate_stage <> 'interim' OR active_flag = 0),
  CHECK (aggregate_stage <> 'interim' OR runtime_eligible = 0),
  UNIQUE(chapter_id, aggregate_stage, version)
);

CREATE TABLE chapter_rolling_notes (
  row_id TEXT PRIMARY KEY,
  chapter_id TEXT NOT NULL REFERENCES chapter_goals(chapter_id) ON DELETE CASCADE,
  scene_seq INTEGER NOT NULL,
  scene_id TEXT NOT NULL REFERENCES scene_cards(scene_id) ON DELETE CASCADE,
  source_scene_memory_row_id TEXT NOT NULL REFERENCES scene_memories(row_id) ON DELETE RESTRICT,
  result_text TEXT NOT NULL,
  state_change TEXT,
  foreshadow_action TEXT NOT NULL DEFAULT 'none' CHECK(foreshadow_action IN ('opened','touched','resolved','none')),
  next_hint TEXT,
  revision_no INTEGER NOT NULL DEFAULT 1 CHECK(revision_no > 0),
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  UNIQUE(chapter_id, scene_id)
);

CREATE TABLE foreshadow_tracker (
  foreshadow_id TEXT PRIMARY KEY,
  description TEXT NOT NULL,
  planted_at_scene_id TEXT,
  current_status TEXT NOT NULL CHECK(current_status IN ('open','touched','resolved','abandoned')),
  last_touched_at_scene_id TEXT,
  expected_payoff_window TEXT NOT NULL CHECK(expected_payoff_window IN ('near','mid','far','unknown')),
  related_chars_json TEXT NOT NULL DEFAULT '[]',
  trigger_line TEXT,
  notes_for_writer TEXT,
  backfilled_from_scene_id TEXT,
  defer_reason TEXT,
  reopen_trigger TEXT,
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
-- 设计说明：foreshadow_tracker 是**可变对象**，不走 row_id + lineage_key + version 版本化模型。
-- current_status / last_touched_at_scene_id 等字段直接原地更新。
-- 状态变更历史不存在 foreshadow_tracker 本身，审计路径固定为 operation_logs
--   (object_type = 'foreshadow_tracker', lineage_key = foreshadow_id, event_type = 'status_change')。
-- 实现者不得自行为 foreshadow_tracker 加版本化字段；若需要查历史状态，
-- 一律通过 operation_logs.payload_json 反查，不引入第二套 schema。

CREATE TABLE attempt_tracker (
  row_id TEXT PRIMARY KEY,
  scene_id TEXT NOT NULL REFERENCES scene_cards(scene_id) ON DELETE CASCADE,
  source_bundle_id TEXT REFERENCES scene_bundles(bundle_id) ON DELETE RESTRICT,
  bundle_snapshot_hash TEXT,
  version INTEGER,
  scene_status TEXT,
  step TEXT NOT NULL CHECK(step IN ('bundle_build','neutral_draft','hard_qc','style_draft','soft_qc','archive','human_review','reindex','reconcile')),
  attempt_no INTEGER NOT NULL CHECK(attempt_no > 0),
  resolution_code TEXT,
  issue_type TEXT,
  issue_key TEXT,
  next_action TEXT,
  human_action TEXT,
  human_note TEXT,
  token_estimate INTEGER,
  model TEXT,
  approved_at TEXT,
  materialized_at TEXT,
  activated_at TEXT,
  reindexed_at TEXT,
  passed INTEGER CHECK(passed IN (0,1)),
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  CHECK (
    bundle_snapshot_hash IS NULL OR (
      length(bundle_snapshot_hash) = 64 AND
      bundle_snapshot_hash = lower(bundle_snapshot_hash) AND
      bundle_snapshot_hash NOT GLOB '*[^0-9a-f]*'
    )
  ),
  CHECK (step IN ('bundle_build','human_review','reconcile') OR source_bundle_id IS NOT NULL)
);

CREATE TABLE human_review_events (
  event_id TEXT PRIMARY KEY,
  event_source TEXT NOT NULL CHECK(event_source IN ('review_queue','bundle','hard_qc','soft_qc','archive','reindex','backfill')),
  scene_id TEXT REFERENCES scene_cards(scene_id) ON DELETE RESTRICT,
  chapter_id TEXT REFERENCES chapter_goals(chapter_id) ON DELETE RESTRICT,
  trigger_reason TEXT NOT NULL,
  context_refs_json TEXT NOT NULL DEFAULT '{}',
  visible_panels_json TEXT NOT NULL DEFAULT '[]',
  allowed_actions_json TEXT NOT NULL,
  default_action TEXT,
  result_status_map_json TEXT NOT NULL DEFAULT '{}',
  priority TEXT NOT NULL DEFAULT 'medium' CHECK(priority IN ('low','medium','high')),
  owner TEXT NOT NULL DEFAULT 'author',
  status TEXT NOT NULL DEFAULT 'open' CHECK(status IN ('open','resolved','cancelled')),
  resolved_action TEXT,
  resolved_result_domain TEXT CHECK(resolved_result_domain IN ('scene_status','chapter_gate','index_job_status')),
  resolved_result_status TEXT,
  resolved_note TEXT,
  resolved_at TEXT,
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  CHECK (scene_id IS NULL OR chapter_id IS NOT NULL)
);

CREATE TABLE idempotency_keys (
  idempotency_key TEXT PRIMARY KEY,
  object_type TEXT NOT NULL,
  lineage_key TEXT NOT NULL,
  version INTEGER NOT NULL DEFAULT 0 CHECK(version >= 0),
  event_type TEXT NOT NULL,
  request_hash TEXT,
  worker_id TEXT,
  attempt_no INTEGER NOT NULL DEFAULT 1 CHECK(attempt_no > 0),
  heartbeat_at TEXT,
  lease_expires_at TEXT,
  status TEXT NOT NULL DEFAULT 'started' CHECK(status IN ('started','succeeded','failed','replayed')),
  result_ref_json TEXT NOT NULL DEFAULT '{}',
  first_seen_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  last_seen_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  notes TEXT,
  CHECK (
    (status = 'started' AND worker_id IS NOT NULL AND heartbeat_at IS NOT NULL AND lease_expires_at IS NOT NULL) OR
    (status IN ('succeeded','failed','replayed') AND worker_id IS NULL AND heartbeat_at IS NULL AND lease_expires_at IS NULL)
  )
);

CREATE TABLE operation_logs (
  op_id TEXT PRIMARY KEY,
  idempotency_key TEXT NOT NULL REFERENCES idempotency_keys(idempotency_key) ON DELETE RESTRICT,
  writer_service TEXT NOT NULL CHECK(writer_service IN ('version_manager','verify_gate','reindex_worker','promotion_service','archiver','aggregator','orchestrator','reconcile_service')),
  object_type TEXT NOT NULL,
  lineage_key TEXT,
  version INTEGER CHECK(version IS NULL OR version >= 0),
  event_type TEXT NOT NULL,
  target_table TEXT NOT NULL,
  target_row_id TEXT,
  status TEXT NOT NULL CHECK(status IN ('started','succeeded','failed')),
  payload_json TEXT NOT NULL DEFAULT '{}',
  error_text TEXT,
  started_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  finished_at TEXT,
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE TABLE reconcile_faults (
  fault_id TEXT PRIMARY KEY,
  fault_scope TEXT NOT NULL CHECK(fault_scope IN ('soft_link','registry_mismatch','alias_mismatch','runtime_ref','archive_idempotency','backfill_gate')),
  severity TEXT NOT NULL CHECK(severity IN ('warning','blocking')),
  object_type TEXT,
  lineage_key TEXT,
  version INTEGER CHECK(version IS NULL OR version >= 0),
  scene_id TEXT REFERENCES scene_cards(scene_id) ON DELETE RESTRICT,
  chapter_id TEXT REFERENCES chapter_goals(chapter_id) ON DELETE RESTRICT,
  ref_table TEXT,
  ref_id TEXT,
  expected_state_json TEXT NOT NULL DEFAULT '{}',
  observed_state_json TEXT NOT NULL DEFAULT '{}',
  status TEXT NOT NULL DEFAULT 'open' CHECK(status IN ('open','acknowledged','resolved')),
  requires_manual_hold INTEGER NOT NULL DEFAULT 0 CHECK(requires_manual_hold IN (0,1)),
  human_review_event_id TEXT REFERENCES human_review_events(event_id) ON DELETE SET NULL,
  detected_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  resolved_at TEXT,
  notes TEXT
);

CREATE TABLE version_registry (
  registry_id TEXT PRIMARY KEY,
  object_type TEXT NOT NULL CHECK(object_type IN (
    'style_rule','banned_rule_cluster','voice_card','relation_card','world_rule',
    'style_observation','calibration_line','final_scene',
    'scene_memory','chapter_memory'
  )),
  lineage_key TEXT NOT NULL,
  version INTEGER NOT NULL CHECK(version > 0),
  physical_row_id TEXT NOT NULL,
  active_flag INTEGER NOT NULL DEFAULT 0 CHECK(active_flag IN (0,1)),
  runtime_eligible INTEGER NOT NULL DEFAULT 0 CHECK(runtime_eligible IN (0,1)),
  runtime_eligibility_basis TEXT NOT NULL DEFAULT 'stage_blocked' CHECK(runtime_eligibility_basis IN ('direct_read','vector_ready','stage_blocked','manual_hold','future_effective')),
  read_channel TEXT NOT NULL CHECK(read_channel IN ('structured','vector')),
  scope TEXT NOT NULL CHECK(scope IN ('global','chapter','scene','runtime')),
  scope_ref_id TEXT,
  source_review_id TEXT REFERENCES review_items(review_id) ON DELETE RESTRICT,
  supersedes_registry_id TEXT REFERENCES version_registry(registry_id) ON DELETE RESTRICT,
  effective_at TEXT,
  approved_at TEXT,
  materialized_at TEXT,
  activated_at TEXT,
  reindexed_at TEXT,
  materialize_status TEXT NOT NULL DEFAULT 'pending' CHECK(materialize_status IN ('pending','succeeded','failed')),
  reindex_status TEXT NOT NULL DEFAULT 'none' CHECK(reindex_status IN ('none','queued','succeeded','failed','n_a')),
  reindex_action TEXT NOT NULL DEFAULT 'none' CHECK(reindex_action IN ('none','incremental','snapshot_rebuild','n_a')),
  sample_query_success TEXT NOT NULL DEFAULT 'n_a' CHECK(sample_query_success IN ('true','false','n_a')),
  verify_status TEXT NOT NULL DEFAULT 'pending' CHECK(verify_status IN ('pending','succeeded','failed','n_a')),
  verify_query_set_source TEXT NOT NULL DEFAULT 'deployment_smoke_queries' CHECK(verify_query_set_source IN ('deployment_smoke_queries','version_registry.verify_query_seed','n_a')),
  verify_query_seed_yaml TEXT,
  notes TEXT,
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  CHECK (NOT (active_flag = 0 AND runtime_eligible = 1)),
  CHECK (runtime_eligible = 0 OR runtime_eligibility_basis IN ('direct_read','vector_ready')),
  CHECK (NOT (runtime_eligible = 1 AND read_channel = 'structured' AND runtime_eligibility_basis <> 'direct_read')),
  CHECK (NOT (runtime_eligible = 1 AND read_channel = 'vector' AND runtime_eligibility_basis <> 'vector_ready')),
  CHECK (runtime_eligibility_basis <> 'future_effective' OR effective_at IS NOT NULL),
  UNIQUE(object_type, lineage_key, version)
);

CREATE TABLE bundle_resolution_cache (
  cache_key TEXT PRIMARY KEY,
  scene_id TEXT NOT NULL REFERENCES scene_cards(scene_id) ON DELETE CASCADE,
  resolver_type TEXT NOT NULL CHECK(resolver_type IN ('relation_id','voice_pick','rule_pick')),
  lookup_signature TEXT NOT NULL,
  resolved_ids_json TEXT NOT NULL DEFAULT '[]',
  source_version_refs_json TEXT NOT NULL DEFAULT '{}',
  cache_status TEXT NOT NULL DEFAULT 'fresh' CHECK(cache_status IN ('fresh','stale','invalidated')),
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  invalidated_at TEXT,
  notes TEXT,
  UNIQUE(scene_id, resolver_type, lookup_signature)
);

CREATE TABLE vector_alias_registry (
  alias_scope TEXT PRIMARY KEY,
  object_type TEXT NOT NULL CHECK(object_type IN ('style_observation','calibration_line','final_scene')),
  scope TEXT NOT NULL CHECK(scope IN ('global','chapter','scene','runtime')),
  scope_ref_id TEXT,
  collection_family TEXT NOT NULL,
  active_alias TEXT,
  candidate_alias TEXT,
  active_snapshot_version TEXT,
  candidate_snapshot_version TEXT,
  active_embedding_version TEXT,
  candidate_embedding_version TEXT,
  verify_status TEXT NOT NULL DEFAULT 'none' CHECK(verify_status IN ('none','pending','succeeded','failed')),
  sample_query_success TEXT NOT NULL DEFAULT 'n_a' CHECK(sample_query_success IN ('true','false','n_a')),
  verify_query_set_source TEXT NOT NULL DEFAULT 'deployment_smoke_queries' CHECK(verify_query_set_source IN ('deployment_smoke_queries','version_registry.verify_query_seed')),
  verify_query_seed_yaml TEXT,
  active_since TEXT,
  candidate_created_at TEXT,
  updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  CHECK ((scope IN ('global','runtime') AND scope_ref_id IS NULL) OR (scope IN ('chapter','scene') AND scope_ref_id IS NOT NULL)),
  CHECK (collection_family <> ''),
  CHECK (active_alias IS NOT NULL OR candidate_alias IS NOT NULL),
  CHECK (candidate_alias IS NULL OR active_alias IS NULL OR candidate_alias <> active_alias),
  CHECK (active_alias IS NOT NULL OR active_since IS NULL),
  CHECK (active_alias IS NULL OR active_snapshot_version IS NOT NULL),
  CHECK (active_alias IS NULL OR active_embedding_version IS NOT NULL),
  CHECK (active_alias IS NOT NULL OR (active_snapshot_version IS NULL AND active_embedding_version IS NULL)),
  CHECK (candidate_alias IS NULL OR candidate_snapshot_version IS NOT NULL),
  CHECK (candidate_alias IS NULL OR candidate_embedding_version IS NOT NULL),
  CHECK (candidate_alias IS NOT NULL OR (candidate_snapshot_version IS NULL AND candidate_embedding_version IS NULL)),
  CHECK (alias_scope = object_type || ':' || scope || ':' || COALESCE(scope_ref_id,'global')),
  CHECK (
    (object_type = 'style_observation' AND alias_scope LIKE 'style_observation:%') OR
    (object_type = 'calibration_line' AND alias_scope LIKE 'calibration_line:%') OR
    (object_type = 'final_scene' AND alias_scope LIKE 'final_scene:%')
  )
);

CREATE TABLE reindex_jobs (
  job_id TEXT PRIMARY KEY,
  job_type TEXT NOT NULL CHECK(job_type IN ('incremental','snapshot')),
  object_type TEXT NOT NULL CHECK(object_type IN ('style_observation','calibration_line','final_scene')),
  alias_scope TEXT REFERENCES vector_alias_registry(alias_scope) ON DELETE RESTRICT,
  target_snapshot_version TEXT,
  target_embedding_version TEXT,
  scope TEXT NOT NULL CHECK(scope IN ('global','chapter','scene','runtime')),
  scope_ref_id TEXT,
  requested_by TEXT NOT NULL DEFAULT 'system',
  worker_id TEXT,
  attempt_no INTEGER NOT NULL DEFAULT 0 CHECK(attempt_no >= 0),
  heartbeat_at TEXT,
  lease_expires_at TEXT,
  status TEXT NOT NULL DEFAULT 'queued' CHECK(status IN ('queued','running','succeeded','failed','cancelled')),
  reason TEXT,
  payload_json TEXT NOT NULL DEFAULT '{}',
  started_at TEXT,
  finished_at TEXT,
  error_text TEXT,
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  CHECK (status <> 'running' OR worker_id IS NOT NULL),
  CHECK (status <> 'running' OR attempt_no > 0),
  CHECK (status <> 'running' OR heartbeat_at IS NOT NULL),
  CHECK (status <> 'running' OR lease_expires_at IS NOT NULL)
);

CREATE TABLE verify_jobs (
  job_id TEXT PRIMARY KEY,
  alias_scope TEXT NOT NULL REFERENCES vector_alias_registry(alias_scope) ON DELETE RESTRICT,
  candidate_alias TEXT NOT NULL,
  target_snapshot_version TEXT,
  target_embedding_version TEXT,
  worker_id TEXT,
  attempt_no INTEGER NOT NULL DEFAULT 0 CHECK(attempt_no >= 0),
  heartbeat_at TEXT,
  lease_expires_at TEXT,
  status TEXT NOT NULL DEFAULT 'queued' CHECK(status IN ('queued','running','succeeded','failed','cancelled')),
  query_set_source TEXT NOT NULL CHECK(query_set_source IN ('deployment_smoke_queries','version_registry.verify_query_seed')),
  query_seed_yaml TEXT,
  results_json TEXT NOT NULL DEFAULT '{}',
  sample_query_success TEXT NOT NULL DEFAULT 'n_a' CHECK(sample_query_success IN ('true','false','n_a')),
  started_at TEXT,
  finished_at TEXT,
  error_text TEXT,
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  CHECK (status <> 'running' OR worker_id IS NOT NULL),
  CHECK (status <> 'running' OR attempt_no > 0),
  CHECK (status <> 'running' OR heartbeat_at IS NOT NULL),
  CHECK (status <> 'running' OR lease_expires_at IS NOT NULL)
);

CREATE TABLE interop_artifacts (
  artifact_id TEXT PRIMARY KEY,
  artifact_kind TEXT NOT NULL CHECK(artifact_kind IN (
    'bundle_worksheet_import','bundle_worksheet_export',
    'markdown_export','csv_export','scene_replay_export','import_manifest'
  )),
  scene_id TEXT REFERENCES scene_cards(scene_id) ON DELETE RESTRICT,
  chapter_id TEXT REFERENCES chapter_goals(chapter_id) ON DELETE RESTRICT,
  source_bundle_id TEXT REFERENCES scene_bundles(bundle_id) ON DELETE RESTRICT,
  file_path TEXT NOT NULL,
  file_format TEXT NOT NULL CHECK(file_format IN ('md','csv','yaml','json','txt','zip')),
  file_checksum TEXT,
  direction TEXT NOT NULL CHECK(direction IN ('import','export')),
  status TEXT NOT NULL DEFAULT 'completed' CHECK(status IN ('pending','completed','failed')),
  metadata_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE UNIQUE INDEX uq_style_rules_active ON style_rules(style_rule_set_id) WHERE active_flag = 1;
CREATE UNIQUE INDEX uq_banned_rule_clusters_active ON banned_rule_clusters(banned_cluster_id) WHERE active_flag = 1;
CREATE UNIQUE INDEX uq_voice_cards_active_lineage ON voice_cards(voice_id) WHERE active_flag = 1;
CREATE UNIQUE INDEX uq_voice_cards_active_character ON voice_cards(character_id) WHERE active_flag = 1;
CREATE UNIQUE INDEX uq_relation_cards_active_lineage ON relation_cards(relation_id) WHERE active_flag = 1;
CREATE UNIQUE INDEX uq_relation_cards_active_pair ON relation_cards(pair_key) WHERE active_flag = 1;
CREATE UNIQUE INDEX uq_world_rules_active ON world_rules(world_rule_id) WHERE active_flag = 1;
CREATE UNIQUE INDEX uq_style_observations_active ON style_observations(style_observation_id) WHERE active_flag = 1;
CREATE UNIQUE INDEX uq_calibration_lines_active ON calibration_lines(calibration_line_id) WHERE active_flag = 1;
CREATE UNIQUE INDEX uq_scene_drafts_active ON scene_drafts(draft_lineage_id) WHERE active_flag = 1;
CREATE UNIQUE INDEX uq_final_scenes_active_lineage ON final_scenes(final_scene_id) WHERE active_flag = 1;
CREATE UNIQUE INDEX uq_final_scenes_active_scene ON final_scenes(scene_id) WHERE active_flag = 1;
CREATE UNIQUE INDEX uq_scene_memories_active ON scene_memories(scene_id) WHERE active_flag = 1;
CREATE UNIQUE INDEX uq_chapter_memories_final_active ON chapter_memories(chapter_id) WHERE aggregate_stage = 'final' AND active_flag = 1;
CREATE UNIQUE INDEX uq_vector_alias_registry_scope ON vector_alias_registry(object_type, scope, IFNULL(scope_ref_id,'global'));

CREATE INDEX idx_scene_cards_chapter_seq ON scene_cards(chapter_id, scene_seq);
CREATE INDEX idx_scene_run_states_status ON scene_run_states(scene_status, updated_at);
CREATE INDEX idx_review_items_status ON review_items(status, chapter_id, scene_id, target_collection, item_type, created_at, review_id);
CREATE INDEX idx_style_rules_scope ON style_rules(scope, scope_ref_id, runtime_eligible);
CREATE INDEX idx_banned_clusters_scope ON banned_rule_clusters(scope, scope_ref_id, runtime_eligible);
CREATE INDEX idx_voice_cards_character_runtime ON voice_cards(character_id, runtime_eligible);
CREATE INDEX idx_relation_cards_pair_runtime ON relation_cards(pair_key, runtime_eligible);
CREATE INDEX idx_world_rules_scope_runtime ON world_rules(scope, scope_ref_id, runtime_eligible, rule_tier);
CREATE INDEX idx_style_observations_scope_runtime ON style_observations(scope, scope_ref_id, runtime_eligible);
CREATE INDEX idx_calibration_lines_scope_runtime ON calibration_lines(scope, scope_ref_id, runtime_eligible);
CREATE INDEX idx_scene_bundles_scene_created ON scene_bundles(scene_id, created_at);
CREATE INDEX idx_qc_reports_scene_type ON qc_reports(scene_id, qc_type, created_at);
CREATE INDEX idx_scene_memories_scene_created ON scene_memories(scene_id, created_at);
CREATE INDEX idx_chapter_memories_chapter_stage ON chapter_memories(chapter_id, aggregate_stage, created_at);
CREATE INDEX idx_chapter_rolling_notes_chapter_seq ON chapter_rolling_notes(chapter_id, scene_seq);
CREATE INDEX idx_foreshadow_tracker_status ON foreshadow_tracker(current_status, last_touched_at_scene_id);
CREATE INDEX idx_attempt_tracker_scene_attempt ON attempt_tracker(scene_id, attempt_no);
CREATE INDEX idx_human_review_events_status ON human_review_events(status, chapter_id, scene_id, priority, event_source, created_at, event_id);
CREATE INDEX idx_vector_alias_registry_scope ON vector_alias_registry(object_type, scope, scope_ref_id, updated_at);
CREATE INDEX idx_idempotency_keys_lookup ON idempotency_keys(object_type, lineage_key, version, event_type, status);
CREATE INDEX idx_idempotency_keys_recovery ON idempotency_keys(status, lease_expires_at, worker_id);
CREATE INDEX idx_operation_logs_writer_status ON operation_logs(writer_service, status, started_at);
CREATE INDEX idx_reconcile_faults_status ON reconcile_faults(status, severity, fault_scope, detected_at);
CREATE INDEX idx_version_registry_lookup ON version_registry(object_type, lineage_key, active_flag, runtime_eligible);
CREATE INDEX idx_version_registry_reindex ON version_registry(reindex_status, verify_status, read_channel);
CREATE INDEX idx_bundle_resolution_cache_scene ON bundle_resolution_cache(scene_id, resolver_type, cache_status);
CREATE INDEX idx_reindex_jobs_status ON reindex_jobs(status, lease_expires_at, object_type, job_type);
CREATE INDEX idx_verify_jobs_status ON verify_jobs(status, lease_expires_at, alias_scope);
CREATE INDEX idx_interop_artifacts_lookup ON interop_artifacts(artifact_kind, scene_id, chapter_id, source_bundle_id);
```

## 5.2 `review_items.candidate_payload_json` 契约

`review_items` 不能只靠 `candidate_text` materialize。所有需要结构化入库的候选，必须在 `candidate_payload_json` 里携带完整 payload；服务层按 `item_type` 校验。

### 5.2.1 payload 示例（下列 JSON 均为 `candidate_payload_json` 字段值本体）

```json
{
  "style_rule_set_id": "STYLE_GLOBAL_MAIN",
  "scope": "global",
  "scope_ref_id": null,
  "rules": [
    {
      "rule_key": "emotion_restraint",
      "rule_text": "避免直接命名情绪，优先让动作、停顿与物象承担情绪。",
      "priority": 10,
      "tags": ["emotion", "dialogue"]
    }
  ],
  "digest_text": "情绪以动作和停顿呈现，避免直白命名；对白收束要留余波。"
}
```

```json
{
  "banned_cluster_id": "BAN_REUNION_V1",
  "scope": "global",
  "scope_ref_id": null,
  "cluster_name": "reunion_scene_bans",
  "scene_types": ["reunion", "probe"],
  "rules": [
    {
      "ban_key": "no_full_exposition",
      "ban_text": "重逢场不可一次说透旧事。",
      "severity": "hard"
    }
  ],
  "digest_text": "重逢/试探场禁止一次性说透旧事、禁止抢答真相。"
}
```

```json
{
  "voice_id": "VC_CHAR_LIN",
  "character_id": "CHAR_LIN",
  "sentence_rhythm": "短句为主，停顿多，关键句后置。",
  "dialogue_tone": "表面客气，潜台词偏冷。",
  "pressure_shift": "受压时句子更短，回答更硬。",
  "taboo_patterns": ["不长篇抒情", "不主动讲大道理"],
  "full_card_text": "……",
  "digest_text": "短句、停顿、表客内冷；受压时更硬，不作长篇抒情。"
}
```

```json
{
  "relation_id": "REL_CHAR_A_CHAR_B",
  "char_a": "CHAR_A",
  "char_b": "CHAR_B",
  "pair_key": "CHAR_A|CHAR_B",
  "surface_relation": "旧识",
  "hidden_tension": "都在试探对方知情范围。",
  "power_balance": "表面平衡，实际 B 更占上风。",
  "trigger_cues": "那年冬天",
  "taboo_topics": "旧信寄件人",
  "current_phase": "重逢初期",
  "digest_text": "重逢初期、互探知情范围；B 略占上风，提到“那年冬天”会抬高张力。"
}
```

```json
{
  "world_rule_id": "WR_GLOBAL_014",
  "rule_text": "禁术在城内不得公开施放。",
  "digest_text": "城内禁术公开施放属于硬禁令。",
  "rule_tier": "hard_rule",
  "scope": "global",
  "scope_ref_id": null,
  "domain": "taboo",
  "allow_exception_mode": "explicit_exception_only",
  "exception_to_rule_id": null,
  "effective_mode": "immediate",
  "effective_at": null,
  "expires_at": null
}
```

```json
{
  "style_observation_id": "STY_003",
  "category": "ending",
  "candidate_text": "结尾偏向余波式收束，不急于解释。",
  "evidence_excerpt": "她没有回头。",
  "evidence_scope": "multi_chunk",
  "scope": "global",
  "scope_ref_id": null,
  "scene_types": ["probe", "reunion"],
  "tags": ["ending", "restraint"]
}
```

```json
{
  "calibration_line_id": "CAL_002",
  "line_text": "门在她背后轻轻合上，像一句没说完的话。",
  "tag": "ending",
  "why_it_works": "用动作收尾，回响感强，不直接总结情绪。",
  "source_scene_id": "CH001_SC03",
  "source_type": "approved_final_scene",
  "reject_if": "若必须依赖前文专有名词才成立则拒绝。"
}
```

```json
{
  "scene_id": "CH001_SC03",
  "summary": "旧城重逢成立，主角由迟疑转为警觉。",
  "state_changes": ["主角警觉性上升"],
  "foreshadow_delta": {"opened": ["F014"], "touched": [], "resolved": []},
  "carry_notes": [],
  "next_hook": "下一场进入更明确的试探。"
}
```

```json
{
  "chapter_id": "CH001",
  "aggregate_stage": "final",
  "source_scene_ids": ["CH001_SC01", "CH001_SC02", "CH001_SC03"],
  "chapter_result": "重逢与试探成立，章目标达成。",
  "core_shift": "主角从回避转向主动追查旧信。",
  "foreshadow_delta": "旧信寄件人线索被正式打开。",
  "next_chapter_hook": "下一章从追查寄件人展开。",
  "do_not_repeat": "不再重复解释旧城与旧识背景。"
}
```

### 5.2.2 服务层校验要求

- `pair_key` 必须在 materialize 前规范化成排序后的 `CHAR_A|CHAR_B`
- `style_rules.rules[*].rule_key`、`banned_rule_clusters.rules[*].ban_key` 必须在各自集合内唯一
- `scene_summary` / `chapter_summary` 只能写入 runtime memory 表，不能误写到知识分表
- `calibration_candidate.source_type = approved_final_scene` 时，`source_scene_id` 必须可追溯到 `final_scenes.status in {approved, waived}`

### 5.2.3 `target_collection` 派生规则（固定，不接受自由文本）

- `review_items.target_collection` 是**受控派生列**，由 `item_type` 通过数据库 `GENERATED ALWAYS AS ... STORED` 计算；写入端不得把它当作自由输入字段。
- materialize routing 的唯一合法映射固定为：`style_observation -> style_observations`、`style_rule_set -> style_rules`、`banned_rule_cluster -> banned_rule_clusters`、`voice_card_candidate -> voice_cards`、`relation_card_candidate -> relation_cards`、`world_rule -> world_rules`、`calibration_candidate -> calibration_lines`、`foreshadow_open/touch/resolve -> foreshadow_tracker`、`scene_summary -> scene_memories`、`chapter_summary -> chapter_memories`。
- API / worker / extractor 若显式提交 `target_collection`，服务层必须把它视为**只读镜像字段**：值与派生结果不一致时，拒绝写入并返回 `REVIEW_TARGET_COLLECTION_DERIVATION_MISMATCH`；一致时也不得以其取代 `item_type` 路由。
- Review Inbox 与 list/filter 仍然可以按 `target_collection` 过滤，但这是基于显式生成列与索引，不是自由文本命名。

### 5.2.4 字段语义澄清

- 上面的 payload 示例都只表示 `candidate_payload_json` 字段值本体；完整 `review_items` API body 由外层资源对象包裹，不得把“整条 review_item JSON”原样再嵌进 payload。
- `target_collection` 是 read-only 派生列，不属于 candidate payload / create body 的自由输入面；任何 materialize / merge / list filter 都必须把 `item_type` 视为 canonical 路由键。
- `active_on_approve` 只是**审批意图 hint**，不是 `activate` 的同义词。`1` 表示“当对象类型与时机允许时，审批后可继续走默认 materialize / activate 流”；它**不能**越过第 6 章 activation matrix。vector 与 `future_effective` 对象即使 `active_on_approve = 1`，也必须先落 candidate，再等 verify / promotion。
- `active_on_approve = 0` 的固定语义是：approval 只负责 materialize candidate 或 inactive row，不自动进入 runtime；后续必须经显式 promotion / manual release 才可放行。HTTP 层固定提供 `POST /api/v1/review-items/{review_id}/release` 与 `POST /api/v1/runtime/promotions/run-due` 两条收口路径，前者面向人工 release，后者面向 future-effective 到点 promotion。  
- `attempt_tracker.version` 是**审计辅助字段**，记录“本次 attempt 主要触达的对象版本号”。`neutral_draft / style_draft` 记录 draft version；`archive` 记录 `final_scene` 或 `scene_memory` 的 version；review / reindex 可记录知识对象 version；不适用时允许 `NULL`。它不是 scene 全局修订号，也不是 join 主键，不得脱离 `step` 与对象上下文单独解释。

### 5.2.5 Review / Human Review 的上下文投影列规则

- `review_items.scene_id / chapter_id` 与 `human_review_events.scene_id / chapter_id` 是**列表筛选与工作台联动的投影列**；它们不替代 `candidate_payload_json` / `context_refs_json` 的 canonical 语义。  
- scene-scoped item / event 必须回填 `scene_id`，并从 `scene_cards.chapter_id` 同步投影 `chapter_id`；chapter-scoped item / event 至少回填 `chapter_id`；global item / event 允许二者都为 `NULL`。  
- `GET /api/v1/review-items` 与 `GET /api/v1/human-review-events` 的 `scene_id / chapter_id` 过滤 **不得**依赖 JSON 扫描；服务端必须直接命中这两列与对应索引。  
- 若 `candidate_payload_json` / `context_refs_json` 的上下文与投影列不一致，写入层必须拒绝入库并返回 `SCOPED_CONTEXT_PROJECTION_MISMATCH`。

## 5.3 正式 Schema Contract（仓库必须存在）

仓库 **MUST** 同时提供 Pydantic 模型与导出的 JSON Schema；数据库只存 canonical JSON，不承担结构校验。最低落点如下：

- `app/schemas/review_payloads.py` + `schemas/generated/review_payloads.json`
- `app/schemas/qc_outputs.py` + `schemas/generated/qc_outputs.json`
- `app/schemas/human_review_event.py` + `schemas/generated/human_review_event.json`
- `app/schemas/bundle_snapshot.py` + `schemas/generated/bundle_snapshot.json`

### 5.3.1 `review_items.candidate_payload_json`

- 使用 `item_type` 作为 discriminated union；未声明 `item_type`、缺少必填字段或出现额外未知字段时拒绝入库
- `target_collection` 不属于输入 schema；它只能由 `item_type` 派生，schema / service / worker 不得接受自由文本 collection 名称
- `candidate_payload_json` 在 API、service、worker 三处复用同一模型；禁止各层各写一套 dict 校验

### 5.3.2 QC 输出

- `HardQCOutput` 与 `SoftQCOutput` 必须是独立模型；`issues[*].issue_key`、`resolution_code`、`next_action`、`pass_flag` 必填
- `issues_json`、`rewrite_brief_json` 入库前必须由 schema parse 后 canonicalize，禁止接受额外字段
- `validate_qc_report()` 是唯一入口；前端、API、worker 都调用同一模型

### 5.3.3 `human_review_events.allowed_actions_json / result_status_map_json`

- `allowed_actions_json` 必须是受控 enum 数组
- `result_status_map_json` 只允许映射已在 `allowed_actions_json` 中声明的动作
- `result_status_map_json[action]` 的值必须是对象：`{"target_domain": ..., "target_status": ...}`；**不允许**再用 bare string 状态名
- `target_domain` 只允许三类：`scene_status`、`chapter_gate`、`index_job_status`
- `scene_status` 只允许映射到 `scene_run_states.scene_status` 的受控值；本版显式使用 `bundle_built`，不再使用 `bundle_ready` 这类别名
- `chapter_gate` 只允许：`none`、`blocked_waiting_backfill`、`manual_hold`
- `index_job_status` 只允许：`queued`、`running`、`succeeded`、`failed`、`cancelled`；本版用 `queued` 代替 `reindex_queued` 这类混域写法
- `default_action` 若非空，必须属于 `allowed_actions_json`
- `resolved_result_domain` / `resolved_result_status` 必须回写本次执行动作最终命中的 domain/status，前端不得自行拼接第二套状态常量

### 5.3.4 `scene_bundles.frozen_snapshot_json` / worksheet 分层 schema contract

- `scene_bundles.frozen_snapshot_json` 固定只存 **`BundleSnapshotCoreV1`**；它是 bundle core 的 canonical JSON。worksheet 导入 / 导出与 `GET /api/v1/replay/*` 则固定使用 **`BundleWorksheetEnvelopeV1`**；envelope 负责携带 `bundle_id / bundle_snapshot_hash / hash_contract_version / hash_alg / execution_mode / created_by_action`，并把真正的快照 core 放进 `snapshot` 字段。  
- `BundleSnapshotCoreV1` 的最低字段固定为：

```json
{
  "contract_version": "BSHASH_v1",
  "stage_allowlist_name": "bundle_build_allowlist_v1",
  "source_version_refs": {},
  "resolved_ref_ids": {},
  "ordered_injections": [],
  "inline_digests": {},
  "budget_check": {}
}
```

- `BundleWorksheetEnvelopeV1` 的最低字段固定为：

```json
{
  "bundle_id": "BND_CH001_SC03_b01",
  "bundle_snapshot_hash": "38ba1eb7dd787d7b158655e59f86a093b8563fd9c2b0a8696b4a611acf12a32d",
  "hash_contract_version": "BSHASH_v1",
  "hash_alg": "sha256",
  "execution_mode": "P2_native",
  "created_by_action": "bundle_build",
  "snapshot": {
    "contract_version": "BSHASH_v1",
    "stage_allowlist_name": "bundle_build_allowlist_v1",
    "source_version_refs": {},
    "resolved_ref_ids": {},
    "ordered_injections": [],
    "inline_digests": {},
    "budget_check": {}
  }
}
```

- `scene_bundles.source_version_refs_json / resolved_ref_ids_json / ordered_injections_json / inline_digests_json / budget_check_json` 是从 `BundleSnapshotCoreV1` 解析后投影出的结构化列；写入层 **MUST** 校验这些列与 `frozen_snapshot_json` 对应字段逐项一致，不一致时拒绝入库。  
- `source_version_refs`、`resolved_ref_ids`、`ordered_injections[*]`、`inline_digests` 均禁止额外未知字段；需要演进时一律 bump `contract_version` 并更新 schema，不允许靠“宽松 dict”偷加字段。  
- hash 投影固定为 `BundleSnapshotHashProjectionV1 = {contract_version, stage_allowlist_name, source_version_refs, resolved_ref_ids, ordered_injections, inline_digests}`；`budget_check`、`created_by_action`、调试注释与导入来源元数据**不参与** `bundle_snapshot_hash` 计算。  
- API、service、interop worker 在落 `scene_bundles.frozen_snapshot_json` 前都必须先通过同一 `BundleSnapshotCoreV1` parse + canonicalize；worksheet / replay 在返回 envelope 前，必须再按 `BundleWorksheetEnvelopeV1` 复包，不允许手拼 dict。

### 5.3.5 `vector_alias_registry` 投影 contract

- `alias_scope` 是 `object_type / scope / scope_ref_id` 的**字符串投影**，固定公式为 `object_type + ':' + scope + ':' + (scope_ref_id or 'global')`；`GET /api/v1/index/alias-scopes` 的筛选必须命中显式列 `object_type / scope / scope_ref_id`，不得在 SQL 中现拆 `alias_scope`。  
- `collection_family` 是 candidate / active collection 的稳定命名族，例如 `<object_type>__<scope>__<scope_ref_id|global>`；它**不是** runtime 查询指针。runtime 读路径只看 `active_alias`，构建 candidate 时只写 `candidate_alias`。  
- `active_alias / active_snapshot_version / active_embedding_version` 必须描述当前正在服务的 active collection；`candidate_alias / candidate_snapshot_version / candidate_embedding_version` 必须描述待切换 candidate collection。candidate 可以为空，但只要 candidate_alias 非空，对应 snapshot / embedding version 就必须同时非空。
- `active_alias` / `candidate_alias` 若非空，必须都代表具体 collection 名；不得把 `collection_family`、embedding 版本号或其他命名片段误当 alias 本体。  
- active 与 candidate 的 embedding version **允许不同**；snapshot rebuild / rollback / verify 必须显式比较两边，而不是再从 alias 名字字符串里反推 embedding。

### 5.3.6 job lease / recovery contract

- `reindex_jobs` 与 `verify_jobs` 的 lease tuple 固定为 `worker_id / attempt_no / heartbeat_at / lease_expires_at`。`attempt_no` 是**执行尝试计数**：入队时为 0，首次 claim 成功后为 1；每次 reclaim / retry 再 +1。
- running job 的 heartbeat、finish、fail、retry、cancel 都必须携带 `(job_id, worker_id, attempt_no, status='running')` 作为 compare-and-swap 条件；命中 0 行视为 lease 已丢失，旧 worker 只能停止，不得再写结果。
- `target_snapshot_version / target_embedding_version` 是作业捕获时的目标元数据，不得在 job 运行中被“顺手改成最新值”；否则必须新建 job 而不是重写旧 job。
- recovery sweep 对 `status='running' AND lease_expires_at <= now` 的 job 只能做两种收口：回到 `queued` 并保留同一 `job_id` / 递增 `attempt_no`，或终态 `failed` 并写 `error_text + operation_logs + reconcile_faults`。不得留在永久 `running`。

---

## 6. activation matrix、lineage 与 supersede 规则

### 6.1 activation matrix（实现必须照表执行）

| object_type | lineage_key | primary read channel | materialize 后 | candidate ready 后 | activate / runtime 放行时 | `future_effective` | 备注 |
|---|---|---|---|---|---|---|---|
| `style_rule` | `style_rule_set_id` | structured | 新行写入 | n/a | immediate 时 `active=1`、`runtime_eligible=1` | 先保持 `active=0`、`runtime_eligible=0`，到 `effective_at` 再 flip | 直接读，不依赖向量 |
| `banned_rule_cluster` | `banned_cluster_id` | structured | 新行写入 | n/a | immediate 时 `active=1`、`runtime_eligible=1` | 先保持 `active=0`、`runtime_eligible=0`，到 `effective_at` 再 flip | soft_qc / stylizer 直接读 |
| `voice_card` | `voice_id` | structured | 新行写入 | n/a | immediate 时 `active=1`、`runtime_eligible=1` | 先保持 `active=0`、`runtime_eligible=0`，到 `effective_at` 再 flip | bundle deterministic select |
| `relation_card` | `relation_id` | structured | 新行写入 | n/a | immediate 时 `active=1`、`runtime_eligible=1` | 先保持 `active=0`、`runtime_eligible=0`，到 `effective_at` 再 flip | 依赖 `pair_key` 唯一 active |
| `world_rule` | `world_rule_id` | structured | 新行写入 | n/a | immediate 时 `active=1`、`runtime_eligible=1` | 先保持 `active=0`、`runtime_eligible=0`，到 `effective_at` 再 flip | 冲突裁决按 tier + authority |
| `style_observation` | `style_observation_id` | vector | 新行写入，`active=0`、`runtime_eligible=0` | `reindex + verify` 成功后仍 `active=0` | immediate 时由 `VerifyGate` 同事务 `alias flip + close old active + active=1 + runtime_eligible=1` | verify 可提前完成；未到 `effective_at` 前保持 candidate，不切 alias | basis 只允许 `vector_ready / stage_blocked / manual_hold / future_effective` |
| `calibration_line` | `calibration_line_id` | vector | 新行写入，`active=0`、`runtime_eligible=0` | `reindex + verify` 成功后仍 `active=0` | immediate 时由 `VerifyGate` 同事务 `alias flip + close old active + active=1 + runtime_eligible=1` | verify 可提前完成；未到 `effective_at` 前保持 candidate，不切 alias | basis 只允许 `vector_ready / stage_blocked / manual_hold / future_effective` |
| `final_scene` | `final_scene_id` | vector（仅 `similar_scenes`） | 行写入，`active=0` | `archive` 成功且 `similar_scenes` verify 成功后仍 `active=0` | `VersionManager + VerifyGate` 收口时置 `active=1`；`runtime_eligible=1` 仅服务相似检索 | **不支持** | UI 直接按 `row_id` 读；`runtime_eligible` 不参与正文归档读取 |
| `scene_memory` | `scene_id` | structured | 归档生成 | n/a | 同事务 `active=1`、`runtime_eligible=1` | **不支持** | 下一场 deterministic read；basis 只允许 `direct_read / stage_blocked / manual_hold` |
| `chapter_memory(final)` | `chapter_id|final` | structured | final aggregate 生成 | n/a | immediate 时 `active=1`、`runtime_eligible=1` | 先保持 `active=0`、`runtime_eligible=0`，到 `effective_at` 再 flip | 下一章开头只读 final |
| `chapter_memory(interim)` | `chapter_id|interim` | structured | interim aggregate 生成 | n/a | 固定 `active=0`、`runtime_eligible=0` | 不适用 | 只服务压缩 / 人工复查，不进 runtime |
| `scene_draft` | `draft_lineage_id` | n/a | 生成草稿行 | n/a | `active=1` 仅表示该 lineage 当前版本 | 不适用 | 不进 runtime 检索，也不进入 `version_registry` |
| 作者输入表 / tracker | 业务主键 | explicit read | 直接写入 | 不适用 | 不适用 | 不适用 | `chapter_goals`、`scene_cards`、`foreshadow_tracker` 不靠 `runtime_eligible` |

### 6.2 `runtime_eligible` 的固定解释

- `structured` immediate 对象：正向放行 basis 只有 `direct_read`；默认在 **activate 同事务** 里把 `runtime_eligible` 置为 1。  
- `structured future_effective`：candidate row 必须先以 `active=0 / runtime_eligible=0 / basis=future_effective` 落库；旧 active 持续服务，直到 `promotion_service` 到点后再做 close old active + activate + runtime 放行。  
- `vector` 对象：candidate row 在 materialize 时一律 `active=0 / runtime_eligible=0`；`reindex + verify` 只让 candidate 进入“可切换”状态，本身**不会**改 active / runtime。  
- `vector future_effective`：verify 可以提前完成，但 alias flip、关闭旧 active、以及 `runtime_eligible = 1` 都必须等 `effective_at` 到达后一次性完成。  
- `final_scene` 不接受 `future_effective`；`scene_memory` 不接受 `future_effective` 与 `vector_ready`；`chapter_memory(interim)` 固定 `active_flag = 0` 且 `runtime_eligible = 0`。  
- `future_effective` 的核心原则不是“先切 canonical 再等待放行”，而是“旧 active 持续服务，直到 replacement 已准备好且到点后再原子切换”。

### 6.3 lineage / supersede 规则（必须写死）

| 用户动作 | `source_bundle_id` | `bundle_snapshot_hash` | draft/final lineage | supersede 行为 |
|---|---|---|---|---|
| `partial_rewrite`（neutral） | 保持不变 | 保持不变 | 同 `draft_lineage_id`，`version + 1` | 旧 draft `active=0` |
| `full_rewrite`（scene_card 未改） | 保持不变 | 保持不变 | 同 neutral lineage，`version + 1` | 旧 draft `active=0` |
| `local_patch`（style） | 保持不变 | 保持不变 | 同 style lineage，`version + 1` | 旧 style draft `active=0` |
| `re_run_stylizer` | 保持不变 | 保持不变 | 同 style lineage，`version + 1` | 旧 style draft `active=0` |
| `approve_with_notes` / `soft_waive` | 保持不变 | 保持不变 | 同 `final_scene_id` lineage，`version + 1` 或首版建 v1 | 旧 active final 只在 `archive + verify` 收口事务中置 `active=0`，不在新 final 行插入时关闭 |
| `edit_scene_card` | **新 bundle** | **新 hash** | **新 neutral/style/final lineage** | 旧 lineage 保留历史 |
| `pin_item / exclude_item / bundle_rebuild` | **新 bundle** | **新 hash** | **新 neutral/style/final lineage** | 旧 lineage 保留，可 replay |
| allowlist / ordered_injections / source_version_refs 变化 | **新 bundle** | **新 hash** | **新 lineage** | 原 bundle 绝不覆盖 |

---

## 7. 配置文件契约（仓库中必须存在）

### 7.1 `config/allowlists.yaml`

```yaml
bundle_build_allowlist_v1:
  include:
    - chapter_goal
    - scene_card
    - voice_card
    - relation_card
    - world_rule
    - scene_memory
    - chapter_memory_final
    - foreshadow_tracker_open
    - style_rule
    - style_observation
    - calibration_line
    - banned_rule_cluster
    - final_scene_similar
  exclude:
    - review_queue
    - raw_books
    - scene_draft_neutral
    - scene_draft_style
    - chapter_memory_interim

soft_qc_allowlist_v1:
  include:
    - style_draft
    - style_rule
    - banned_rule_cluster
    - calibration_line
    - pov_voice_digest
    - relation_digest_optional
    - scene_card_minimal
    - style_length_lock_metadata
  exclude:
    - review_queue
    - raw_books
    - world_lore_long_text
    - full_foreshadow_tracker
    - chapter_memory
    - final_scene_similar
```

### 7.2 `config/models.yaml`

```yaml
task_routing:
  extraction: cheap
  neutral_draft: medium
  hard_qc: medium
  stylize: strong
  soft_qc: medium
  archive: cheap
  chapter_aggregate: medium

retry_budget:
  hard_partial_max: 2
  hard_full_max: 1
  soft_patch_max: 2
  total_attempt_budget: 4

job_runtime:
  idempotency_claim_ttl_seconds: 90
  reindex_lease_ttl_seconds: 180
  verify_lease_ttl_seconds: 180
  heartbeat_interval_seconds: 45
  max_reclaim_attempts:
    idempotency: 3
    reindex: 3
    verify: 3
```

### 7.3 `config/hash_contract.yaml`

```yaml
contract_version: BSHASH_v1
hash_alg: sha256
text_normalization:
  unicode: NFC
  line_ending: LF
  trim_trailing_spaces: true
  trim_outer_whitespace: true
json_canonicalization:
  pretty: false
  fixed_key_order: true
empty_values:
  scalar: null
  list: []
  map: {}
ordered_arrays:
  preserve:
    - ordered_injections
    - style_observations
    - calibration_lines
    - banned_rules
    - similar_scenes
unordered_arrays:
  sort_ascending:
    - resolved_ref_ids.relation_ids
    - resolved_ref_ids.world_rule_ids
    - resolved_ref_ids.open_foreshadow_ids
```

---

## 8. Core Engine 实现合同

### 8.1 Orchestrator

```python
run_scene(scene_id: str, from_step: str = "bundle", resume: bool = False) -> SceneRunResult
```

#### 8.1.1 执行顺序

1. 读取 `scene_cards`、`chapter_goals`、`scene_run_states`、`chapter_states`
2. 执行 `recovery_service.recover_stuck_jobs(now)`（至少在进程启动后 / worker poll 前 / 显式 recovery sweep 时触发；单机模式下 `run_scene()` 可机会性调用）
3. 执行 `promotion_service.promote_due_objects(now)`
4. `bundle_builder.build(scene_id, execution_mode)`
5. 生成 neutral draft
6. 跑 `hard_qc`
7. 根据 hard_qc resolution 做 rewrite / block / continue
8. 生成 style draft
9. 跑 `soft_qc`
10. 根据 soft_qc resolution 做 patch / waive / block / continue
11. 生成 final scene
12. `archiver.archive_final_scene(...)`
13. 若命中聚合条件，触发 `aggregator.run_interim_or_final(...)`

#### 8.1.2 `scene_run_states` 更新规则

- `current_bundle_id/hash`：bundle 写入成功后更新
- `current_neutral_draft_row_id`：neutral 草稿成功后更新
- `current_style_draft_row_id`：style 草稿成功后更新
- `current_final_scene_row_id`：final scene 成功后更新
- `attempt_tracker.source_bundle_id`：除 `bundle_build` 与 pre-bundle 的 `human_review / reconcile` 外，其他 step 一律必须非空；`neutral_draft / hard_qc / style_draft / soft_qc / archive / reindex` 不允许丢 bundle 指针
- `total_attempt_count`：每次重写 / human review / rerun 前递增
- `repeat_issue_key` / `repeat_issue_count`：按最新 `qc_reports.issues[*].issue_key` 比对连续重复
- 任何人工动作都必须先 append `attempt_tracker`，再改变 `scene_run_states`

#### 8.1.3 断路器

- `hard_partial_rewrite_count > 2` -> `human_review_required`
- `hard_full_rewrite_count > 1` -> `human_review_required`
- `soft_patch_count > 2` -> `human_review_required`
- 同一 `issue_key` 连续 2 次 -> `human_review_required`
- `total_attempt_count >= attempt_budget` -> `human_review_required`

### 8.2 BundleBuilder

```python
build(scene_id: str, execution_mode: str, force_rebuild: bool = False) -> BundleBuildResult
```

#### 8.2.1 六步算法

1. `hard_filter`
2. `deterministic_select`
3. `semantic_rank`
4. `conflict_resolve`
5. `budget_trim`
6. `freeze_and_persist`

#### 8.2.2 `deterministic_select` 的固定规则

- `chapter_goal`：按 `chapter_id` 直接取
- `scene_card`：按 `scene_id` 直接取
- `pov voice`：只允许按 `scene_cards.pov_character_id` 唯一 active `voice_cards` 命中
- `relation`：
  1. 若 `scene_cards.resolved_relation_id` 已存在且对应 active row 仍有效，则直接用
  2. 若不存在，只在以下情况下自动解析：  
     - `onstage_chars_json` 去重后正好 2 人；或  
     - `pov_character_id + 1 个非 POV 在场角色` 能组成唯一 pair  
  3. 命中唯一 active `pair_key` 时，允许幂等回填 `scene_cards.resolved_relation_id`
  4. `>1` 命中或无法唯一推断时，不得强行选，进入 optional unresolved 或 human review
- `previous scene_memory`：按同章上一个 `scene_seq` 的 active memory 直接取
- `chapter_memory(final)`：只有跨章或明确需要章记忆时才取 final，不得取 interim
- `open foreshadow_tracker`：只取 `current_status in ('open','touched')` 且与本场角色/章上下文相关的项

#### 8.2.3 `semantic_rank` 的排序键

固定排序键：

1. 实体 / 角色重合
2. `scene_type` / tag 匹配
3. 手工 pin / priority
4. recency（`activated_at`、`last_touched_at`）
5. scope proximity（scene > chapter > global，只用于相关性排序）
6. `stable_object_key`（同类型 canonical 主键字典序）

#### 8.2.4 `conflict_resolve`

覆盖权固定为：

1. `explicit_pin / manual_override`
2. `hard_rule`
3. `soft_rule`
4. `observation`

同 tier 再看 authority：`global > chapter > scene`

只有以下情况允许低 scope 覆盖高 scope：

- 高层 `allow_exception_mode = explicit_exception_only`
- 低层规则显式填写 `exception_to_rule_id = 上层 rule_id`

否则直接打回 `human_review_required`。

#### 8.2.5 `budget_trim`

固定裁剪顺序：

1. 删 `similar_scenes`
2. `style_observations` 从 5 压到 3
3. `calibration_lines` 从 2 压到 1
4. 压缩 `relation/world/memory` digest
5. 仍超限则停止自动写作，要求拆场而不是继续压 `scene_card`

### 8.3 HashEngine

```python
compute_bundle_hash(
    stage_allowlist_name: str,
    source_version_refs: dict,
    resolved_ref_ids: dict,
    ordered_injections: list,
    inline_digests: dict
) -> str
```

#### 8.3.1 MUST 规则

- 只对 canonical bundle snapshot 求 hash
- `compute_bundle_hash()` 的输入 **MUST** 来自 schema-validated `BundleSnapshotHashProjection`；禁止 API / worker / interop 各自手拼 hash dict
- 不把 neutral/style/final text 算进去
- `budget_check_json`、导入来源元数据、调试注释不参与 hash
- `ordered_injections` 是 build 时冻结顺序，冻结后不得 post-hoc 重排
- 不同 contract_version、allowlist、source_version_refs、ordered_injections、inline_digests 任何一项变化，都必须得到新 hash

### 8.4 Resolver 与 `bundle_resolution_cache`

```python
resolve_relation_id(scene_id: str, lookup_signature: str) -> ResolverResult
resolve_voice_id(scene_id: str, character_id: str) -> ResolverResult
```

#### 8.4.1 cache 读写权限

- canonical writer：`bundle_builder` 的 resolver pass
- lazy prepass：只能 best-effort 写回 fresh cache，且必须是唯一 deterministic hit
- ambiguous / multi-hit / no-hit：**不得**写 fresh cache

#### 8.4.2 stale 条件

以下任一变化，都必须把 cache 置 stale：

- `scene_card` 的角色组合变化
- 参与解析的 source version 升版
- `stage_allowlist_name` 变化
- `hash_contract_version` 变化
- `future_effective` promotion 改变可读集合

### 8.5 QC Validator

```python
validate_qc_report(qc_type: str, payload: dict) -> ValidatedQCReport
```

#### 8.5.1 hard_qc 合法组合

| resolution_code | pass_flag | next_action |
|---|---:|---|
| `hard_pass` | 1 | `pass` |
| `hard_fail_partial` | 0 | `partial_rewrite` |
| `hard_fail_full` | 0 | `full_rewrite` |
| `hard_block_human` | 0 | `human_review_required` |

#### 8.5.2 soft_qc 合法组合

| resolution_code | pass_flag | next_action |
|---|---:|---|
| `soft_pass` | 1 | `pass` |
| `soft_waive` | 1 | `pass_with_notes` |
| `soft_fail_partial` | 0 | `partial_rewrite` |
| `soft_block_human` | 0 | `human_review_required` |

#### 8.5.3 强校验

- 缺字段 -> block human
- `pass_flag=true` 但 `next_action` 是 rewrite / human -> block human
- `pass_flag=false` 但 `next_action` 是 pass / pass_with_notes -> block human
- `soft_waive` 必须显式带 `carry_forward_note`、`note_scope`、`carry_note_text`
- `note_scope = continuity` 才允许进入 `scene_memory.carry_notes`

#### 8.5.4 schema 绑定

- `validate_qc_report()` **MUST** 先按 `HardQCOutput` / `SoftQCOutput` schema parse，再做合法组合校验。
- parse 失败、额外字段、枚举越界与合法组合冲突，一律返回 `QC_ILLEGAL_COMBO` 并转 `human_review_required`。
- `issues_json` / `rewrite_brief_json` 写库前必须 canonicalize；前端、API、worker 使用同一份 schema 导出，不允许双写规则表。

### 8.6 Archiver

```python
archive_final_scene(scene_id: str, final_scene_row_id: str, qc_report_id: str) -> ArchiveResult
```

#### 8.6.1 原子写入范围

单次 archive 事务内必须完成：

1. 插入新 `scene_memories` 行
2. 关闭旧 active `scene_memories`
3. 对 `chapter_rolling_notes` 执行 **upsert**：首次归档插入；同一 `scene_id` 重归档时覆盖当前台账、更新 `source_scene_memory_row_id`、`revision_no + 1`
4. 仅在“首次为该 scene 建立 rolling note / active scene_memory”时，更新 `chapter_states.chapter_passed_scene_count += 1`
5. 更新 `scene_run_states.scene_status = 'archived'`

#### 8.6.2 archive 幂等与重归档规则

- `archive_final_scene()` 的幂等键固定为 `final_scene:{final_scene_id}:{version}:archive`。
- `chapter_rolling_notes` 是**当前章内台账**，不是 append-only 历史表；历史留在 `scene_memories`、`final_scenes`、`operation_logs`。
- 若同一 scene 因 supersede / waive / rerun 发生重归档，系统必须 upsert 旧 rolling note，而不是再插一条重复 scene 行。
- `chapter_passed_scene_count` 表示“已通过并进入归档链的 distinct scene 数”，不是“归档执行次数”；重归档不得重复加 1。

#### 8.6.3 carry notes 规则

- `soft_waive + note_scope = continuity` -> 写入 `scene_memories.carry_notes_json`
- `style_only` -> 只保留在 `qc_reports` 和 `attempt_tracker`
- human review 若覆盖了 note_scope / carry_note_text，以 **最终回流值** 为准

#### 8.6.4 calibration candidate

- 每场最多提 1 条 `calibration_candidate`
- 只有来源 `final_scenes.status in ('approved','waived')` 时才允许进入 `review_items`
- archive 阶段只负责提名，不直接入 `calibration_lines`

### 8.7 Aggregator

```python
run_interim_aggregate(chapter_id: str) -> AggregateResult
run_final_aggregate(chapter_id: str) -> AggregateResult
```

#### 8.7.1 interim 触发条件

必须同时满足：

- `chapter_goals.planned_scene_count > 5`
- `chapter_states.chapter_passed_scene_count % 3 == 0`
- 当前场景不是章末
- `chapter_states.mid_aggregate_enabled_effective = 1`

输出固定为：

- `aggregate_stage = 'interim'`
- `active_flag = 0`
- `runtime_eligible = 0`

#### 8.7.2 final 触发条件

必须同时满足：

- 当前场景 `is_chapter_last = 1`
- 本场 `scene_memory` 已生成
- `chapter_states.chapter_backfill_pending_count = 0`
- `chapter_states.aggregate_block_reason = 'none'`

输出固定为：

- `aggregate_stage = 'final'`
- 关闭旧 final active
- 新 final `active_flag = 1`
- immediate 情况下 `runtime_eligible = 1`

### 8.8 Backfill（ADR-02）

```python
run_staged_backfill(chapter_id: str, strategy: str) -> BackfillResult
```

允许的 `strategy` 只有：

- `create_tracker_now`
- `mark_staged_abandoned`
- `explicit_defer_with_tracker`
- `run_backfill_again`

#### 8.8.1 固定步骤

1. 先创建 / upsert 正式 `foreshadow_tracker`
2. 再移除 `scene_cards.must_include_text` 中的 staged marker
3. 再修正 archive / memory / review context 中的自由文本引用
4. 最后更新 `chapter_states.chapter_backfill_pending_count`
5. pending 清零后，才允许 `aggregate_block_reason` 从 `blocked_waiting_backfill` 释放

#### 8.8.2 fallback 规则

- 若 `blocked_waiting_backfill` 连续超过 2 次 retry，或跨过 1 个作者 review 周期仍未解锁，则置 `aggregate_block_reason = 'manual_hold'`
- `manual_hold` 不是放行 aggregate，而是暂停等待明确 backfill 动作

### 8.9 VersionManager / PromotionService / RecoveryService / Vector Verify Gate

```python
materialize_review(review_id: str) -> MaterializeResult
release_review(review_id: str) -> PromoteResult
promote_due_objects(now: datetime) -> PromoteResult
recover_stuck_jobs(now: datetime) -> RecoverySweepResult
run_incremental_reindex(object_type: str, lineage_keys: list[str]) -> ReindexResult
run_snapshot_rebuild(alias_scope: str) -> ReindexResult
run_verify(job_id: str) -> VerifyResult
```

#### 8.9.1 materialize 规则

- structured immediate 对象：`materialize + activate + runtime_eligible` 可以在同一事务完成。
- structured `future_effective` 对象：materialize 时只能写 **inactive candidate**（`active=0 / runtime_eligible=0 / basis=future_effective`）；旧 active 保持服务到 promotion 时刻。
- vector immediate 对象：materialize 时只能写 **inactive candidate**；`reindex + verify` 成功之前不得关闭旧 active，也不得 flip alias。
- vector `future_effective` 对象：candidate 可以提前 `reindex + verify`，但在 `effective_at` 到达前必须保持 `active=0 / runtime_eligible=0`，active alias 不得变化。
- materialize routing **只能**从 `review_items.item_type`（以及由其派生的只读 `target_collection`）决定；不得信任客户端 / extractor 提供的自由文本 collection 名称。
- `review_items.status = approved` 后 materialize 失败，不回滚到 `pending`。
- retry 权威落点是 `review_items.retry_count / max_retry`。

#### 8.9.2 future-effective promotion

promotion 候选条件固定为：

- `runtime_eligibility_basis = 'future_effective'`
- `effective_at <= now`
- target row `materialize_status = succeeded`
- structured 对象已存在 candidate row；vector 对象还必须满足 `verify_status = succeeded` 与 `reindexed_at != null`

**`world_rules.expires_at` 到期处理**：`promote_due_objects(now)` 在处理 `future_effective` 放行的同一轮次内，还必须扫描 `world_rules WHERE expires_at <= now AND active_flag = 1`，对命中行执行 `active_flag = 0, runtime_eligible = 0, runtime_eligibility_basis = 'stage_blocked'`，并追加 `operation_logs(event_type = 'expire')`。到期 deactivation 不需要 candidate，直接在同一 `BEGIN IMMEDIATE` 事务内关闭 active row 即可；`version_registry` 对应行同步更新 `activated_at` 不变、追加 `notes = 'expired'`。若 `expires_at` 到期时对应行 `active_flag` 已为 0，视为幂等，只记 `operation_logs` 不写 `reconcile_faults`。

promotion 动作：

- structured 对象：**close old active -> activate candidate -> `runtime_eligible = 1` -> basis 改成 `direct_read`**。
- vector 对象：只有当 candidate index 已 verify 成功，才可执行 **alias flip + close old active + activate candidate + `runtime_eligible = 1` -> basis 改成 `vector_ready`**；否则只能排队 reindex / verify，不能偷跑。
- `final_scene` 与 `scene_memory` 若收到 `future_effective` 配置，视为 schema violation，直接拒绝写库。
- promotion service **不得**先关闭旧 active 再等待 candidate 补齐；旧 active 必须一直服务到 replacement 准备完毕。

#### 8.9.2.1 manual release

- `release_review(review_id)` 是 `active_on_approve = 0`、`runtime_eligibility_basis = manual_hold`、或“人工确认现在可以放行”的显式入口。它先根据 `review_items.approved_item_row_id / approved_item_id` 与 `version_registry` 解析目标 candidate，再复用与 `promote_due_objects()` 相同的 activate / alias flip 规则。  
- preconditions 固定为：`review_items.status = approved`、`materialize_status = succeeded`、目标 candidate 存在；structured 对象在 `manual_release` 时必须已 materialize；vector 对象额外要求 `verify_status = succeeded` 且 `reindexed_at != null`。不满足时返回 `409 RELEASE_PRECONDITION_FAILED`。  
- `release_review` 的幂等键固定为 `review_item:{review_id}:release`；同一 review 的重复 release 不得造成二次 flip。  
- HTTP 对应入口固定为 `POST /api/v1/review-items/{review_id}/release`；它只做人工 release，不替代 `POST /api/v1/runtime/promotions/run-due` 的到点 promotion job。

#### 8.9.3 vector alias flip

- `alias_scope` 命名固定为 `<object_type>:<scope>:<scope_ref_id|global>`；DDL 同时显式存 `scope / scope_ref_id`，并要求它们与 `alias_scope` 投影一致。
- `vector_alias_registry` 是唯一逻辑 alias source of truth；它还必须保存 `collection_family` 作为命名族。`active_alias / candidate_alias` 都是**具体 collection 名**；`collection_family` 只服务命名与运维，不参与 runtime lookup。runtime 查询路径固定为：`alias_scope -> active_alias -> query same-named Chroma collection`；不得在 Chroma 内再维护第二套可变 alias 指针。
- `embedding_version` 语义固定拆分为 `active_embedding_version / candidate_embedding_version`；snapshot 版本同理拆成 `active_snapshot_version / candidate_snapshot_version`。snapshot rebuild、verify、rollback、故障排查都必须直接比较这四个字段，不得从 alias 字符串反推。
- bootstrap 允许 `vector_alias_registry.active_alias = null`；首次 candidate 构建时只写 `candidate_alias + candidate_snapshot_version + candidate_embedding_version`，verify 通过后再提升为首个 `active_alias`。
- verify 失败时，若 `active_alias` 已存在（非首次），保留 `active_alias` 不变；`candidate_alias` 保持原值以待 retry，不得清空（清空会导致 CHECK `active_alias IS NOT NULL OR candidate_alias IS NOT NULL` 失败）。若确需废弃当前 candidate（例如 candidate collection 已损坏无法修复），必须先写新 `candidate_alias`（指向新 candidate collection），再在同一事务内清空旧 `candidate_alias`，保证约束始终满足。
- **首次 bootstrap verify 失败的特殊边界**：`active_alias = null` 且 verify 失败时，系统不得清空 `candidate_alias`（否则两者同时为 null，触发 CHECK violation）。此场景下服务层必须：① 保留 `candidate_alias` 原值；② 写 `verify_status = failed`；③ 写 `reconcile_faults(fault_scope = 'alias_mismatch', severity = 'blocking')`；④ 将 `alias_scope` 对应的所有 runtime 消费请求返回降级响应（空结果而非报错），直至首次 verify 成功。
- reindex job **没有权限**切 active alias；它只负责把 candidate collection 写满并回写 `reindexed_at`。
- verify job 是唯一能放行 alias flip 的步骤，且它校验的目标固定是 `candidate_alias` 对应的 collection，而不是“某个隐含当前别名”。
- 成功条件：
  - `reindexed_at != null`
  - candidate collection 真实存在且可查询
  - 所有 sample queries 成功
  - 返回非空
  - top_k 全部来自 candidate collection
- 成功后的动作：
  - immediate：在**同一 SQLite 收口事务**中把 `candidate_alias / candidate_snapshot_version / candidate_embedding_version` 原子迁移到 `active_*` 三元组、清空 `candidate_*` 三元组、关闭旧 active row、打开新 active row 的 `runtime_eligible`。由于 runtime 总是先查 registry，再按 collection 名访问 Chroma，因此这里不再假定有跨库同事务 alias mutation。
  - `future_effective`：若 `effective_at > now`，只记 `verify_status = succeeded`，candidate 维持待切换；到点后再做真正 alias flip。
- 失败动作：
  - 保留旧 active alias（若仍不存在旧 active alias，则保持 `active_alias = null`）
  - `vector_alias_registry.verify_status = failed`
  - candidate `alias / snapshot_version / embedding_version` 三元组一并留在待修复状态，允许 retry
  - 若发现 registry 与实际 collection 集合不一致、candidate collection 缺失或存在 orphan collection，必须写 `reconcile_faults(fault_scope = 'alias_mismatch')`
- 任何 runtime alias 本地缓存都必须以 `vector_alias_registry.updated_at` 失效；缓存命中不得绕过 registry 读取。

#### 8.9.4 job lease / recovery sweep

- `recover_stuck_jobs(now)` 是唯一允许 reclaim `reindex_jobs / verify_jobs / idempotency_keys(status='started')` 的入口；它必须使用与 4.7.1 相同的 `BEGIN IMMEDIATE + ordered mutex` recipe，不得在事务外先判定“这行卡住了”再进事务改状态。
- `run_incremental_reindex` / `run_snapshot_rebuild` / `run_verify` 的 claim 步骤必须先把 job 从 `queued` 原子改成 `running`，同时写 `worker_id / attempt_no / heartbeat_at / lease_expires_at / started_at`。完成、失败、取消与 retry 都必须校验同一 `(job_id, worker_id, attempt_no)`；stale worker 命中 0 行时只能退出，不得补写结果。
- recovery sweep 对 `status='running' AND lease_expires_at <= now` 的 job，若 `attempt_no < job_runtime.max_reclaim_attempts[*]`，则必须把 job 改回 `queued`、清空 `worker_id / heartbeat_at / lease_expires_at`、保留同一 `job_id` 并等待下次 claim；若已达上限，则改 `failed`，写 `error_text = 'lease_expired_reclaimed'`，并视影响面决定是否创建 `human_review_event`。
- 对 `idempotency_keys(status='started')` 的 reclaim 规则固定为：要么把同一语义 key 重新 claim 给新 worker 继续执行，要么改 `failed` 并清 lease 字段；**不得**把过期 started key 永久留在表里阻塞后续重试。
- `reindex_jobs` 与 `verify_jobs` 的 `target_snapshot_version / target_embedding_version` 必须与 claim 当刻的 `vector_alias_registry.candidate_*` 一致；若 claim 前 candidate 已被新一轮 rebuild 覆盖，则旧 job 只能取消或失败，不得再把旧结果写回新 candidate。
- sweep 与 reclaim 都必须 append `operation_logs(event_type = 'lease_reclaim' | 'lease_expired_fail')`；若 job / alias / registry 之间已出现分叉，还必须同步写 `reconcile_faults`。

#### 8.9.5 single-writer、提交顺序与幂等键

- `VersionManager` 是对象表 + `version_registry` 的唯一**状态提交者**；`Archiver` / `Aggregator` 只负责各自对象族的内容生成，状态提交必须经同一条写路径收口。所有下述收口事务都必须遵守 **4.7.1** 的 `BEGIN IMMEDIATE + ordered mutex` recipe。
- `VerifyGate` 是 `vector_alias_registry` 的唯一状态提交者；`run_incremental_reindex` / `run_snapshot_rebuild` 不得改 `active_alias`，也不得直接把 vector 对象 `runtime_eligible` 置 1。
- 幂等键固定为 `object_type:lineage_key:version:event_type`；所有状态写路径必须先 upsert `idempotency_keys`，再写 `operation_logs`。
- direct-read immediate 顺序：materialize target row -> close old active -> activate / runtime_eligible -> write registry timestamps/status -> mark idempotency succeeded -> commit。
- direct-read `future_effective` 顺序：materialize inactive candidate -> write registry pending -> keep old active serving -> promotion 时 close old active -> activate / runtime -> registry finalize。
- vector immediate 顺序：materialize inactive candidate -> write registry pending -> reindex -> verify -> alias flip + close old active + object/runtime 放行 + registry finalize（同一收口事务）。
- vector `future_effective` 顺序：materialize inactive candidate -> reindex -> verify -> registry `verify_status = succeeded` 但 object/alias 维持 candidate -> promotion 时再做 alias/object flip。
- 若对象表与 registry 不一致，runtime 读取以对象表 + active alias 为准，同时写 `reconcile_faults`，不得直接用 registry 覆盖对象表。

---

## 9. REST API 合同

### 9.1 统一返回格式

```json
{
  "ok": true,
  "data": {},
  "error": null,
  "request_id": "req_..."
}
```

错误格式：

```json
{
  "ok": false,
  "data": null,
  "error": {
    "code": "RELATION_AMBIGUOUS",
    "message": "scene CH001_SC02 无法唯一解析 relation_id",
    "details": {}
  },
  "request_id": "req_..."
}
```

### 9.1.1 变更接口的幂等契约（HTTP）

- 所有 `POST` / `PUT` 变更接口 **MUST** 接受 `X-Idempotency-Key`；`GET` 不需要。
- 服务端按“方法 + 路径模板 + schema-canonicalized request body”计算 `request_hash`，并写 `idempotency_keys.request_hash`。`request_id` 只用于追踪，不代替 idempotency key。
- 同一 key + 同一 hash + 已成功结果：返回首次成功的响应体，并附 `X-Idempotency-Status: replayed`。
- 同一 key + 不同 hash：返回 `409 IDEMPOTENCY_KEY_REUSED_WITH_DIFFERENT_PAYLOAD`。
- 同一 key 当前仍处于 `started` 且 `lease_expires_at > now`：返回 `409 IDEMPOTENCY_REQUEST_IN_PROGRESS`。
- 同一 key 当前处于 `started` 但 `lease_expires_at <= now`：服务端**必须**先尝试 reclaim stale row（`attempt_no += 1`、刷新 `worker_id / heartbeat_at / lease_expires_at`、append `operation_logs(event_type = 'lease_reclaim')`），成功后继续执行；不得永久占坑。成功收口时可附 `X-Idempotency-Status: reclaimed`。
- 同一 key + 同一 hash + 既往 `failed`：服务端允许把同一语义 key 重新转回 `started` 并重试，但必须保留旧失败记录在 `operation_logs`；不得要求调用方仅为了绕过 stale key 人工更换 idempotency key。
- 变更接口缺少 header：返回 `400 IDEMPOTENCY_KEY_REQUIRED`。
- worker / scheduled jobs 不走 HTTP header，但仍必须沿用 `object_type:lineage_key:version:event_type` 写 `idempotency_keys`；retry 不得更换语义 key。

### 9.1.2 HTTP 删除与退役契约

- 本版核心 API 合同**默认不定义通用 DELETE**。
- `chapter_goal`、`scene_card`、`scene_bundle`、版本化知识对象、runtime 产物的退役，一律通过 `PUT/POST` 更新、`supersedes_*`、`status`、`active_flag = 0` 或 `manual_hold` 表达。
- 若后续实现额外加入仅用于“未形成下游引用的预热数据 / 测试数据”的 cleanup DELETE，必须先做 FK preflight；一旦存在下游引用，服务端只能返回 `409 DELETE_NOT_ALLOWED_ON_REFERENCED_OBJECT`。

### 9.2 核心接口

| Method | Path | 作用 |
|---|---|---|
| `POST` | `/api/v1/chapters` | 新建 `chapter_goal` |
| `PUT` | `/api/v1/chapters/{chapter_id}` | 更新 `chapter_goal` |
| `GET` | `/api/v1/chapters/{chapter_id}/status` | 读取 `chapter_states`、aggregate gate 与 backfill 计数 |
| `POST` | `/api/v1/scenes` | 新建 `scene_card` |
| `PUT` | `/api/v1/scenes/{scene_id}` | 更新 `scene_card` |
| `GET` | `/api/v1/scenes/{scene_id}/workbench` | 返回 workbench 聚合视图 |
| `GET` | `/api/v1/scenes/{scene_id}/status` | 读取 `scene_run_states` 与 current pointers |
| `GET` | `/api/v1/scenes/{scene_id}/attempts` | 分页返回 `attempt_tracker` 时间线 |
| `POST` | `/api/v1/scenes/{scene_id}/bundle/build` | 构建 bundle |
| `POST` | `/api/v1/scenes/{scene_id}/run/full` | 从 bundle 跑完整链路 |
| `POST` | `/api/v1/scenes/{scene_id}/resume` | 从 `scene_run_states` 当前步恢复 |
| `GET` | `/api/v1/review-items` | Review Inbox 列表 / 筛选 / 分页 |
| `GET` | `/api/v1/review-items/{review_id}` | review item 详情 |
| `POST` | `/api/v1/review-items/{review_id}/approve` | 审批并 materialize |
| `POST` | `/api/v1/review-items/{review_id}/release` | 显式 release 已审批 candidate |
| `POST` | `/api/v1/review-items/{review_id}/reject` | 驳回 |
| `POST` | `/api/v1/review-items/{review_id}/edit-and-approve` | 改写后审批 |
| `GET` | `/api/v1/human-review-events` | Human Review 列表 / 筛选 / 分页 |
| `GET` | `/api/v1/human-review-events/{event_id}` | human review 详情 |
| `POST` | `/api/v1/human-review-events/{event_id}/resolve` | 执行动作并回流 |
| `GET` | `/api/v1/index/alias-scopes` | Index Console alias 列表 / 筛选 |
| `GET` | `/api/v1/index/alias-scopes/{alias_scope}` | alias 详情（含 active / candidate / verify） |
| `GET` | `/api/v1/index/jobs` | `reindex_jobs` / `verify_jobs` 列表 / 筛选 / 分页 |
| `GET` | `/api/v1/index/jobs/{job_id}` | index job 详情 |
| `POST` | `/api/v1/index/reindex/incremental` | 增量重建 |
| `POST` | `/api/v1/index/reindex/snapshot` | snapshot rebuild |
| `POST` | `/api/v1/index/verify/{job_id}/retry` | 重新 verify |
| `POST` | `/api/v1/runtime/promotions/run-due` | 执行到点 promotion / release 收口 |
| `POST` | `/api/v1/runtime/recovery/sweep` | 执行 stuck-job / stale-key recovery sweep |
| `POST` | `/api/v1/interop/import/bundle-worksheet` | 导入 P0 / P1 worksheet |
| `GET` | `/api/v1/interop/export/bundle-worksheet/{bundle_id}` | 导出 A5 worksheet |
| `GET` | `/api/v1/replay/final-scene/{row_id}` | 回放 final scene 的 source bundle |
| `GET` | `/api/v1/replay/draft/{row_id}` | 回放 draft 的 source bundle |

### 9.2.1 list / filter 契约

- `/api/v1/review-items` 最低必须支持：`status`、`item_type`、`target_collection`、`scene_id`、`chapter_id`、`page`、`page_size`。`target_collection` 过滤命中的是数据库派生列，而不是自由文本。
- `/api/v1/human-review-events` 最低必须支持：`status`、`event_source`、`priority`、`owner`、`scene_id`、`chapter_id`、`page`、`page_size`。
- `/api/v1/index/alias-scopes` 最低必须支持：`object_type`、`scope`、`scope_ref_id`。
- `/api/v1/index/jobs` 最低必须支持：`status`、`job_type`、`object_type`、`alias_scope`、`worker_id`、`stuck_only`、`page`、`page_size`。
- `scene_id / chapter_id` 过滤必须直接命中 `review_items`、`human_review_events` 的显式投影列；`scope / scope_ref_id` 过滤必须直接命中 `vector_alias_registry.scope / scope_ref_id`，不得靠解析 `candidate_payload_json`、`context_refs_json` 或 `alias_scope` 字符串代替。  
- 所有列表接口都必须返回稳定排序键与分页游标 / 页码元数据；默认排序建议为 `created_at DESC, review_id DESC`、`created_at DESC, event_id DESC`、`object_type ASC, scope ASC, COALESCE(scope_ref_id,'') ASC, alias_scope ASC`。前端不得靠“读完整表再本地 filter”凑 Review Inbox / Human Review / Index Console。

### 9.2.2 status 读取契约

- `/api/v1/scenes/{scene_id}/status` 至少返回：`scene_status`、`current_bundle_id`、`current_bundle_hash`、`current_*_row_id`、attempt counters、`repeat_issue_key / repeat_issue_count`。
- `/api/v1/chapters/{chapter_id}/status` 至少返回：`chapter_passed_scene_count`、`chapter_backfill_pending_count`、`mid_aggregate_enabled_effective`、`aggregate_block_reason`、`last_*_memory_row_id`。
- `/api/v1/index/alias-scopes/{alias_scope}` 至少返回：`object_type`、`scope`、`scope_ref_id`、`collection_family`、`active_alias`、`candidate_alias`、`active_snapshot_version`、`candidate_snapshot_version`、`active_embedding_version`、`candidate_embedding_version`、`verify_status`、`sample_query_success`、`updated_at`。
- `/api/v1/index/jobs/{job_id}` 至少返回：`status`、`job_type`、`object_type`、`alias_scope`、`target_snapshot_version`、`target_embedding_version`、`worker_id`、`attempt_no`、`heartbeat_at`、`lease_expires_at`、`started_at`、`finished_at`。
- `/api/v1/runtime/recovery/sweep` 的响应至少返回：`reclaimed_jobs`、`failed_jobs`、`reclaimed_idempotency_keys`、`failed_idempotency_keys`、`created_human_review_events`。

### 9.3 必须实现的错误码（最少 14 个）

| code | 含义 |
|---|---|
| `POV_VOICE_MISSING` | POV voice 未命中 |
| `RELATION_AMBIGUOUS` | relation_id 无法唯一解析 |
| `BUNDLE_BUDGET_EXCEEDED` | 裁剪后仍超预算 |
| `QC_ILLEGAL_COMBO` | QC 输出字段组合非法 |
| `BACKFILL_PENDING_BLOCKS_FINAL_AGGREGATE` | final aggregate 前置条件不满足 |
| `VECTOR_VERIFY_FAILED` | candidate alias verify 未通过 |
| `RELEASE_PRECONDITION_FAILED` | manual release / promotion 的前置条件不满足 |
| `WRITE_SERIALIZATION_CONFLICT` | 同一 `lineage_key` / `alias_scope` 写入竞争，需要重试 |
| `SCOPED_CONTEXT_PROJECTION_MISMATCH` | `scene_id / chapter_id / scope / scope_ref_id` 投影列与 canonical payload/context 不一致 |
| `REVIEW_TARGET_COLLECTION_DERIVATION_MISMATCH` | 客户端 / worker 传入的 `target_collection` 与 `item_type` 派生结果不一致 |
| `IDEMPOTENCY_KEY_REQUIRED` | 变更请求缺少 `X-Idempotency-Key` |
| `IDEMPOTENCY_KEY_REUSED_WITH_DIFFERENT_PAYLOAD` | 相同 idempotency key 对应了不同 canonical request body |
| `IDEMPOTENCY_REQUEST_IN_PROGRESS` | 相同 idempotency key 当前仍在执行中 |
| `DELETE_NOT_ALLOWED_ON_REFERENCED_OBJECT` | 已形成下游引用的对象不允许 hard delete |
| `BUNDLE_SNAPSHOT_SCHEMA_INVALID` | `frozen_snapshot_json` / worksheet envelope 不符合 `BundleSnapshotCoreV1` / `BundleWorksheetEnvelopeV1` schema |

---

## 10. 前端页面合同

### 10.1 Scene Workbench 必须同时显示

1. `chapter_goal` / `scene_card`
2. `current_bundle_id`、`bundle_snapshot_hash`
3. neutral/style/final 当前 active 版本
4. `qc_reports` 问题高亮定位
5. `attempt_tracker` 时间线（每条 attempt row 旁须提供"回放此 bundle"入口，点击后调用 `GET /api/v1/replay/final-scene/{row_id}` 或 `GET /api/v1/replay/draft/{row_id}`，并将返回的 `BundleWorksheetEnvelopeV1` 展示在 bundle detail 面板；replay 入口仅在 `attempt_tracker.source_bundle_id IS NOT NULL` 时显示）
6. 当前 `human_review_event`
7. `scene_run_states` 当前 scene status
8. 当前 `chapter_states` gate（`chapter_backfill_pending_count`、`aggregate_block_reason`、`mid_aggregate_enabled_effective`）

### 10.2 Review Inbox 必须显示

- `candidate_text`
- `candidate_payload_json` 结构化预览（由 schema 驱动）
- evidence preview
- `target_collection`（只读 badge；来源 = `item_type` 派生列，而非自由文本）
- 可能冲突的 active 版本对照
- 审批按钮：`approve / reject / edit_and-approve / merge / defer`；当 `active_on_approve = 0`、`materialize_status = succeeded` 且对象仍未进入 runtime 时，必须额外显示 `release`
- 列表筛选：`status / item_type / target_collection / scene_id / chapter_id`
- 数据源固定为 `GET /api/v1/review-items` + `GET /api/v1/review-items/{review_id}`，前端不得绕过 API 直拼多表

### 10.3 Human Review Drawer 必须遵守

- 只展示 `allowed_actions_json` 中的动作
- 任何动作先写 `attempt_tracker`
- 动作完成后按 `result_status_map_json[action].target_domain / target_status` 回流
- 动作枚举与路由映射必须来自 `human_review_event` schema，不允许前端维护第二套 action/status 常量
- `scene_status`、`chapter_gate`、`index_job_status` 三个域必须在 UI 上显式区分，禁止把它们混成同一状态下拉框
- 不允许用户手工输入自由状态字符串
- 数据源固定为 `GET /api/v1/human-review-events` + `GET /api/v1/human-review-events/{event_id}`，前端不得自己重建事件状态机

### 10.4 Index Console 必须显示

- `vector_alias_registry` 当前 `object_type / scope / scope_ref_id / collection_family`
- 当前 active / candidate alias
- active / candidate 的 `snapshot_version` 与 `embedding_version`
- `reindex_jobs`
- `verify_jobs`
- `worker_id / attempt_no / heartbeat_at / lease_expires_at`
- `sample_query_success`
- 最近一次 alias flip 结果
- recovery sweep 入口与最近一次 reclaim 摘要
- `updated_at` 与最近一次 `reconcile_faults(fault_scope = 'alias_mismatch')` 摘要
- 数据源固定为 `GET /api/v1/index/alias-scopes` / `GET /api/v1/index/alias-scopes/{alias_scope}` + `GET /api/v1/index/jobs` / `GET /api/v1/index/jobs/{job_id}` + `POST /api/v1/runtime/recovery/sweep`

---

## 11. P0 / P1 Bridge、Import / Export / Replay

### 11.1 bundle worksheet import

- 输入：A5 兼容 YAML / Markdown
- 输出：`scene_bundles` 一条或多条记录 + `interop_artifacts`
- `execution_mode` 固定写 `P0_manual` 或 `P1_scripted`
- 导入前必须先按 `BundleWorksheetEnvelopeV1` schema parse，并对其中的 `snapshot` 再按 `BundleSnapshotCoreV1` parse；缺少必填字段、order-sensitive 数组结构不合法或出现未知字段时，返回 `BUNDLE_SNAPSHOT_SCHEMA_INVALID`
- 若 worksheet 自带 hash：
  - 必须按 `snapshot` 的 `BundleSnapshotHashProjectionV1` 用 BSHASH_v1 复算并验证
- 若 worksheet 无 hash：
  - 允许导入，但只能用于 P0/P1 replay，不能冒充 P2 canonical hash

### 11.2 bundle worksheet export

导出必须返回 `BundleWorksheetEnvelopeV1`，至少包含：

- `bundle_id`
- `bundle_snapshot_hash`
- `hash_contract_version`
- `hash_alg`
- `execution_mode`
- `created_by_action`
- `snapshot`（其类型固定为 `BundleSnapshotCoreV1`）
- 导出结构必须与 `BundleWorksheetEnvelopeV1` 同构；再导入时不得丢 envelope 字段，也不得重排 `snapshot.ordered_injections` 这类 order-sensitive 数组

### 11.3 replay

给定 `final_scenes.row_id` 或 `scene_drafts.row_id`，系统必须能：

1. 取到 `source_bundle_id`
2. 还原该 bundle 的 `BundleSnapshotCoreV1`
3. 组装并返回 `BundleWorksheetEnvelopeV1`
4. 显示 source version refs
5. 对比当前 active 版本与当时 bundle 的差异

### 11.4 Markdown / CSV export

至少支持导出：

- `chapter_goals`
- `scene_cards`
- `chapter_rolling_notes`
- `foreshadow_tracker`
- `review_items`
- `attempt_tracker`

---

## 12. 测试、回归与验收

### 12.1 必跑 golden tests

1. **DDL migration test**：空库可完整执行第 5 章 DDL；所有 partial unique index、关键 FK、`alias_scope` CHECK、`review_items.scene_id / chapter_id / target_collection(GENERATED)`、`human_review_events.scene_id / chapter_id`、`vector_alias_registry.scope / scope_ref_id / collection_family / active_embedding_version / candidate_embedding_version`、`idempotency_keys / reindex_jobs / verify_jobs` 的 lease 字段、以及 `operation_logs / reconcile_faults` 三张治理表均存在  
2. **BSHASH_v1 golden vector**：本版 `BundleSnapshotHashProjectionV1` fixture 的期望 hash 必须精确等于 `311c57097d809b81a6ece39943041c3b412e3ab67ab3efd2d5619498d4ef96a4`。用于复现该 hash 的输入固定如下（测试框架直接使用此 JSON，不得手拼）：

```json
{
  "contract_version": "BSHASH_v1",
  "stage_allowlist_name": "bundle_build_allowlist_v1",
  "source_version_refs": {
    "chapter_goal": "CH001",
    "scene_card": "CH001_SC03",
    "voice_id": "VC_CHAR_LIN",
    "relation_id": "REL_CHAR_A_CHAR_B",
    "scene_memory_prev": "CH001_SC02",
    "open_foreshadow_ids": ["F014"],
    "style_rule_set_id": "STYLE_GLOBAL_MAIN",
    "banned_cluster_id": "BAN_REUNION_V1",
    "style_observation_ids": ["STY_003"],
    "calibration_line_ids": ["CAL_002"]
  },
  "resolved_ref_ids": {
    "relation_ids": ["REL_CHAR_A_CHAR_B"],
    "world_rule_ids": ["WR_GLOBAL_014"],
    "open_foreshadow_ids": ["F014"]
  },
  "ordered_injections": [
    {"slot": "chapter_goal", "ref_id": "CH001", "digest_key": "chapter_goal"},
    {"slot": "scene_card", "ref_id": "CH001_SC03", "digest_key": "scene_card"},
    {"slot": "pov_voice", "ref_id": "VC_CHAR_LIN", "digest_key": "voice_card"},
    {"slot": "relation", "ref_id": "REL_CHAR_A_CHAR_B", "digest_key": "relation_card"},
    {"slot": "prev_scene_memory", "ref_id": "CH001_SC02", "digest_key": "scene_memory"},
    {"slot": "style_rule", "ref_id": "STYLE_GLOBAL_MAIN", "digest_key": "style_rule"},
    {"slot": "banned_cluster", "ref_id": "BAN_REUNION_V1", "digest_key": "banned_rule"},
    {"slot": "style_obs_0", "ref_id": "STY_003", "digest_key": "style_observation"},
    {"slot": "calibration_0", "ref_id": "CAL_002", "digest_key": "calibration_line"},
    {"slot": "world_rule_0", "ref_id": "WR_GLOBAL_014", "digest_key": "world_rule"},
    {"slot": "foreshadow_0", "ref_id": "F014", "digest_key": "foreshadow"}
  ],
  "inline_digests": {
    "chapter_goal": "重逢与试探成立，章目标达成。",
    "scene_card": "旧城重逢，主角由迟疑转为警觉。",
    "voice_card": "短句、停顿、表客内冷；受压时更硬，不作长篇抒情。",
    "relation_card": "重逢初期、互探知情范围；B 略占上风，提到\"那年冬天\"会抬高张力。",
    "scene_memory": "旧城重逢成立，主角由迟疑转为警觉。",
    "style_rule": "情绪以动作和停顿呈现，避免直白命名；对白收束要留余波。",
    "banned_rule": "重逢/试探场禁止一次性说透旧事、禁止抢答真相。",
    "style_observation": "结尾偏向余波式收束，不急于解释。",
    "calibration_line": "门在她背后轻轻合上，像一句没说完的话。",
    "world_rule": "城内禁术公开施放属于硬禁令。",
    "foreshadow": "旧信寄件人线索被正式打开。"
  }
}
```

hash 计算规则：按 `config/hash_contract.yaml` 对上述 JSON 做 NFC + LF 规范化后 canonical JSON 序列化，再 SHA-256。`budget_check`、`created_by_action` 不参与输入。
3. **activation matrix test**：structured immediate、structured future-effective candidate、vector candidate materialize inactive、vector verify success、vector future-effective promotion、illegal false/true、`final_scene.future_effective` 被拒、`scene_memory.vector_ready` 被拒 八类路径全部覆盖  
4. **resolver cache test**：fresh / stale / invalidated / ambiguous 四类结果  
5. **review payload schema test**：`candidate_payload_json` discriminated union 全覆盖，额外字段与缺字段被拒  
6. **QC schema + combo test**：`HardQCOutput` / `SoftQCOutput` parse、额外字段拒绝、合法组合矩阵全覆盖  
7. **human review route schema test**：`allowed_actions_json`、`result_status_map_json[*].target_domain / target_status`、`default_action`、`resolved_result_domain` 的一致性校验  
8. **archive idempotency test**：同一 `scene_id` 重归档时 `chapter_rolling_notes` 必须 upsert、`revision_no` 递增、`chapter_passed_scene_count` 不得重复计数  
9. **idempotency + reconcile test**：重复事件键不得双提交；`status='started'` 的 stale key 必须可 reclaim 或显式 fail，不得永久阻塞；对象表 / registry / alias mismatch 必须写 `reconcile_faults`，场景链内同时写 `attempt_tracker(step='reconcile')`  
10. **backfill gate + soft-link reconcile test**：pending 未清零时 final aggregate 必须被阻断；soft-link orphan 被降级到 `manual_hold` / `human_review_required`  
11. **vector verify gate test**：verify 失败时旧 alias 必须继续服务；bootstrap 场景允许 `active_alias = null`；active / candidate embedding version 可不同且不会混淆；且只有 `VerifyGate` 能 flip alias  
12. **interop roundtrip test**：bundle worksheet 导出后再导入，`ordered_injections` 与 hash 保持一致  
13. **bundle snapshot core/envelope schema test**：`scene_bundles.frozen_snapshot_json` 固定存 `BundleSnapshotCoreV1`；worksheet import / export / replay 固定走 `BundleWorksheetEnvelopeV1`；projection columns 与 core 一致；未知字段被拒；`budget_check` 不影响 hash  
14. **list projection filter test**：`GET /api/v1/review-items`、`GET /api/v1/human-review-events`、`GET /api/v1/index/alias-scopes` 的 `scene_id / chapter_id / scope / scope_ref_id` 过滤必须命中显式列，不得扫描 JSON / 解析字符串  
15. **HTTP idempotency contract test**：缺少 `X-Idempotency-Key` 被拒；相同 key + 相同 payload 返回 replayed；相同 key + 不同 payload 返回 `409`；`started` 且 lease 未过期返回 `409`；`started` 且 lease 过期时必须 reclaim 或显式失败，不得永久卡死  
16. **SQLite writer serialization test**：同一 `lineage_key` / `alias_scope` 的并发写入必须由 `BEGIN IMMEDIATE + ordered mutex` 串行；不能出现双 active、双 flip 或半提交 current pointer  
17. **vector logical alias source test**：runtime 查询必须先从 `vector_alias_registry` 解析 `active_alias`；Chroma 不得存在第二套可变 alias source；missing / orphan collection 必须写 `reconcile_faults(alias_mismatch)`  
18. **delete / retire policy test**：已形成下游引用的 chapter / scene / bundle / runtime rows 不允许 hard delete；未引用测试数据经过 FK preflight 才允许 cleanup  
19. **job lease / heartbeat / recovery sweep test**：`reindex_jobs` / `verify_jobs` claim 时写 `worker_id / attempt_no / heartbeat_at / lease_expires_at`；lease 过期后 recovery sweep 能 requeue 或 fail；旧 worker 在 lease 丢失后不得再 heartbeat / finish 成功  
20. **vector dual embedding version test**：snapshot rebuild 时 `active_embedding_version` 与 `candidate_embedding_version` 可以不同；verify / flip / rollback 全程保留可审计的 active/candidate 三元组  
21. **review target_collection derivation test**：`target_collection` 只能由 `item_type` 派生；显式错误输入被拒；列表筛选命中派生列索引而非 JSON 扫描  

### 12.2 一次性验收口径

只有同时满足以下 20 条，本版才算“完成”：

1. 首章 3 场能从 `scene_card` 跑到 `scene_memory`
2. `source_bundle_id`、`bundle_snapshot_hash`、`source_version_refs` 在 draft/final/replay 上全链可追
3. `scene_run_states` 能断点恢复
4. `active_flag != runtime_eligible` 在 direct-read / vector / future-effective 三条路径都正确，且旧 active 在 replacement 就绪前持续服务
5. `chapter_backfill_pending_count` 能真实阻断 final aggregate
6. `chapter_rolling_notes` 重归档时会 upsert 当前台账，且 `chapter_passed_scene_count` 不重复计数
7. `human_review_event` 的 allowed actions 能先写 attempt，再按 domain/status 正确回流
8. `vector_alias_registry` 能在 verify 失败时保留旧 alias，bootstrap 时允许无旧 alias，且 alias flip 只能经 `VerifyGate`
9. `idempotency_keys`、`operation_logs`、`reconcile_faults` 能真实阻断重复提交与错误继续传播
10. P0 worksheet 能导入、导出、回放，不需要另写第二套 schema
11. `scene_bundles.frozen_snapshot_json` 固定存 `BundleSnapshotCoreV1`，worksheet / replay 固定返回 `BundleWorksheetEnvelopeV1`，且 `budget_check` 不影响 hash
12. `review_items` / `human_review_events` / `vector_alias_registry` 的 `scene_id / chapter_id / scope / scope_ref_id` 过滤都可由显式投影列驱动，不需要 JSON scan 或字符串解析
13. 所有变更接口都执行 `X-Idempotency-Key` 契约；same key + same payload 可重放，same key + different payload 被拒
14. `active_on_approve = 0` 的对象可以经 `POST /api/v1/review-items/{review_id}/release` 显式放行；future-effective 对象可以经 `POST /api/v1/runtime/promotions/run-due` 到点 promotion
15. 同一 `lineage_key` / `alias_scope` 的并发写入能被 `BEGIN IMMEDIATE + ordered mutex` 正确串行，且不会产生双 active / 半提交 current pointer
16. Review Inbox / Human Review / Index Console 能完全由本文定义的 GET/list/read 接口驱动，不需要前端直拼底表
17. `vector_alias_registry` 是唯一逻辑 alias source，runtime 查询固定为“registry -> collection”；已形成下游引用的对象默认禁止 hard delete，只允许状态退役 / supersede
18. `reindex_jobs` / `verify_jobs` / `idempotency_keys(status='started')` 在进程崩溃后不会永久卡死；lease 过期可被 recovery sweep reclaim 或显式 fail，stale worker 不能再写回旧 attempt
19. `vector_alias_registry` 能同时清晰表达 active / candidate 的 `snapshot_version` 与 `embedding_version`；snapshot rebuild、verify 失败与回滚判断不依赖 alias 字符串猜测
20. `review_items.target_collection` 是由 `item_type` 派生的受控列，可用于 Review Inbox 筛选与 materialize 路由，但不接受客户端自由文本漂移

---

## 13. 实施顺序（规格不变，交付分 L1 / L2 / L3 三个里程碑）

### 13.1 L1：运行闭环

1. **先上第 5 章 DDL（含关键 FK）与 CRUD**
2. 打通 `scene_run_states` / `chapter_states` + orchestrator + bundle builder
3. 接 QC、archiver、scene/chapter memory、最小 replay
4. 本阶段**不**接 review materialize / version registry / vector alias

L1 gate：首章 3 场能从 `scene_card` 跑到 `scene_memory`；`source_bundle_id` 回放链打通；backfill gate 生效。

### 13.2 L2：版本治理与人工回流

1. 接 `review_items` materialize、`version_registry`
2. 接 `human_review_events`、schema contracts、`validate_qc_report()`、soft-link audit / reconcile
3. 打通 P0/P1 bridge 的 import / export / replay

L2 gate：`active_flag ≠ runtime_eligible` 路径稳定；human review 能先写 attempt 再回流；schema contract 能阻断非法 JSON；`review_items.target_collection` 已从自由文本收口为派生列。

### 13.3 L3：向量闭环与互操作

1. 接 `vector_alias_registry`、`reindex_jobs`、`verify_jobs`
2. 接 vector verify gate、`similar_scenes`、snapshot rebuild / alias flip
3. 完成 interop center、增量 / snapshot reindex、verify retry

L3 gate：verify 失败时旧 alias 继续服务；`VerifyGate` 成为唯一 alias flip 放行点；lease / heartbeat / recovery sweep 稳定回收 stuck jobs；active/candidate embedding version 可被清晰观察；P0/P1/P2 互操作不引入第二套 schema。

本节只限定**交付顺序**，不改变上面的实现规格；代码可以分阶段落地，但最终行为必须回到本文定义。

---

## 14. 本版收口结论

到本版为止，P2 文档不再只是“概念正确”：

- 数据层已经从“字段清单”细化到**可执行 DDL**，并把 vector / `future_effective` 统一收成 candidate-first，再由 verify / promotion 原子 flip
- review / memory / vector / bridge 都有明确物理落点，同时补齐了关键 FK、soft-link audit、`idempotency_keys / operation_logs / reconcile_faults` 三类治理表
- `style_rules`、`banned_rule_clusters`、`scene_run_states`、`vector_alias_registry` 不再缺席，`single-writer` 也不再靠口头约定，而是拆成“内容生产者 + 状态提交者”双层契约
- `vector_alias_registry` 已被固定为唯一逻辑 alias source；runtime 查询路径改成“registry -> collection”，不再把 SQLite 与 Chroma 误写成双源同事务 alias 系统；active / candidate 的 snapshot 与 embedding version 也已拆开，snapshot rebuild / rollback 不再靠猜
- `chapter_rolling_notes` 已明确为当前章内台账：重归档 upsert，不重复累计 `chapter_passed_scene_count`
- `candidate_payload_json`、QC 输出、`result_status_map_json`、`scene_bundles.frozen_snapshot_json` 已提升为正式 schema contract；bundle snapshot 现在明确拆为 `BundleSnapshotCoreV1` + `BundleWorksheetEnvelopeV1`，`human_review_event` 改为 domain/status 路由；`review_items.target_collection` 也已经从自由文本收口为派生列
- HTTP 层现在有显式 `X-Idempotency-Key` 契约、完整 GET / list / status 接口与“默认禁止 hard delete”规则；Review Inbox / Human Review / Index Console 的筛选列已显式落到物理模型，single-writer 也补到了 SQLite 级 recipe；长作业再额外具备 lease / heartbeat / recovery sweep，不会把 stale key 和 stuck job 永久留在运行面
- `row_id + lineage_key + version`、`active_flag ≠ runtime_eligible`、`source_bundle_id / bundle_snapshot_hash / source_version_refs` 三条主轴继续保持闭环

后续实现时，代码、迁移、接口、前端只允许在本文约束内展开，不再另起一套隐含模型。
