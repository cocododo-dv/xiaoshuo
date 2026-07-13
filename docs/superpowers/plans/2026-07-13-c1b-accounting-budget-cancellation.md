# C1B：统一 LLM 账本、硬预算与显式取消实施计划

> 日期：2026-07-13
>
> 执行分支：`codex/outcome-governance-closure`
>
> 前置完成：C0、C1A；C1A 证据见 `docs/superpowers/evidence/20260713-c1a-source-safety.json`
>
> 依据：`docs/superpowers/specs/2026-07-13-outcome-governance-closure-design.md` §4.3–§4.4、§9–§10

## 目标

关闭完成度评估 P0-4 和 P1-2 中与工程行为直接相关的缺口：

1. 所有生产 LLM 出口统一落 `LlmCall`，包括 `LLMClient.generate` 和系统配置页的最小 completion HTTP probe；`run` 与 `run_task` 不再有双重语义。
2. provider 缺 usage 或调用失败时使用本地估算结算，不能按 0 消失。
3. 场景调用在发起前原子预留，成功/失败/取消分别结算或释放；并发不能超卖。
4. 基线调用与可选调用都受场景生命周期 token 预算约束；自动流程不得重置 token 或次数账目。
5. 作者可显式取消异步场景任务；取消只阻止尚未开始的新节点，不回滚已完成调用、正文或账单。
6. 迁移、实际库、回归和证据状态可复算；offline 证据只关闭工程门。

## 非目标与诚实边界

- 本阶段不把估算价格冒充真实账单；`config/pricing.yaml` 的 `is_estimate=true` 保持不变。
- 本阶段不宣称跨 provider token 可直接比较。硬预算使用统一的本地预算单位和保守预留；报告继续分 provider 展示实际 usage。
- 不尝试中断已经发给 provider 的网络请求。取消在节点边界生效：当前调用允许完成并结算，下一节点不得开始。
- 不让同步 `/run/full` 冒充可取消任务；显式取消绑定 `/run/jobs` 创建的 `job_id`。UI 运行路径使用异步 job。
- 不推进真实模型、五章 UI、真人或发布门。

## 核心设计决策

### 1. LLM 调用是显式持久化边界

统一入口在 provider 调用前写入 `reserved` 账本并提交，在调用后写入 `settled`/`failed`/`released` 并提交。这样失败调用、预算预留和取消不会随外层业务事务回滚而消失。

SQLite 事务边界固定：使用 caller 传入的同一 Session 提交“上一节点产物/checkpoint + 本次 reservation”，提交后才进入 provider 网络期；网络期不得持有写事务。禁止在 caller 已 flush/持写锁时另开 Session 抢写 ledger，否则会自锁为 `database is locked`。provider 返回后仍由 caller Session 开新短事务完成结算和当前产物/checkpoint。

`accounting_status` 固定枚举为：`reserved`（已预留未返回）、`settled`（provider 成功并结算）、`failed`（provider 或后处理失败但已结算）、`released`（发送前取消并释放）、`rejected`（路由/预算/次数等发送前拒绝）、`usage_exceeds_reservation`（provider usage 破坏上界）。新调用必须有 `scope_type/scope_id`；场景、项目、style-reference book/profile、literary eval case 分别用对应 scope，无法归属业务对象的系统调用用 `system/<node_id>`，不得留成不可查询的空 scope。

这会把带 LLM 的长动作从“整请求单事务”改为“可恢复的检查点事务”。必须同步锁定幂等语义：`IdempotencyKey.status=started` 可以跨 LLM 检查点持久化，最终成功或失败仍由原 key 收口；重试从已持久化状态恢复，不重复删除已有有效稿。

### 2. 估算、预留、实际、计费分开

`LlmCall` 表示一个业务逻辑调用（供 SceneDraft/报告引用），`LlmCallAttempt` 表示一次真实 provider HTTP dispatch。`LLMClient` 的 transport retry、429/5xx 重试、response parse retry 和 missing-text reasoning/max-output 降级都必须触发 attempt hook；不能只从最终 `LLMResponse.attempt_count` 反推，因为它不覆盖外层 degrade hop。

每个 physical attempt 在 POST 前独立预留、标 dispatched，在返回/异常后独立结算；下一次 retry/degrade 重新过 token、provider-attempt 和 cancel 硬门。父 LlmCall 的 prompt/completion/total、charged、estimate flag 和最终 status 由子 attempt 求和/归并，成本聚合只计父聚合或只计子表之一，禁止双计。非 `LLMClient` 的 system completion probe 也生成一个 physical attempt。

- `estimated_tokens`：本地估算。输入使用 `context_budget.estimate_tokens`，输出成功时按响应文本/结构化文本估算；失败或 usage 缺失时采用保守估算。
- `reserved_tokens`：发起前硬上限。至少覆盖 UTF-8 输入字节上界、消息开销和路由 `max_output_tokens`，且不得小于 `estimated_tokens`。
- `total_tokens`：provider 提供时保存 provider actual；缺失时保存本地估算。
- `budget_charged_tokens`：场景预算实际扣减值；不得大于本次预留。
- `usage_is_estimate`：任一关键 usage 字段缺失或失败估算时为真。
- `billed_tokens`/真实费用仍不在本阶段伪造；现有成本服务继续标 `is_estimate=true`。

显式 `offline_deterministic` 响应若完整提供 input/output/total 均为 0，则这是有效的零消耗，不得被“usage 缺失”规则改写成收费估算；账本仍须落行并标明 offline provider。测试 fake 若要覆盖缺失 usage，必须使用非 offline provider，避免把离线行为和云调用缺口混淆。

若 provider 报告的 `total_tokens > reserved_tokens`，视为 provider/路由不变量破坏：结算完整记录该 actual，标记 `usage_exceeds_reservation`，耗尽本次预留并阻止后续自动调用，同时返回稳定错误，不能静默写成“仍在预算内”。正常路由的输入字节上界与 `max_output_tokens` 应使该分支不可达，但必须有可证伪测试。

场景次数使用两层：既有 `total_attempt_count/attempt_budget` 继续限制业务生成/重写循环；新增 `provider_attempts_used/provider_attempt_budget` 限制真实 HTTP dispatch。任一层或 token 预算耗尽都停止自动新调用。physical attempt 只有在 dispatch commit 时增加 used，发送前取消/reject 不计；扩容同样只能走作者 topup。

### 3. 原子预算账户

`SceneRunState` 新增 `scene_tokens_reserved`。当前运行时本来就是顺序管线，因此采用单 in-flight fence：调用前确认本次保守上界不大于余额，再用单条条件更新把**全部当前余额**置为本次 reservation。这样同一场景即使被两个 Session 并发触发，也只有一个 provider 调用能开始；另一个必须在前者结算释放后重试，不能同时超卖。

```text
reserved == 0
and used + request_upper_bound <= budget
then reserved = budget - used
```

更新影响行数为 0 时拒绝，provider client 的调用计数必须保持不变。结算增加 used，并把整笔 fence 释放为 0；调用只按 actual/本地估算扣费，未消费余额立即归还。状态不得出现负数，重复结算/释放通过 `LlmCall.accounting_status` 条件更新保持幂等。

预算为空只允许做一次初始化，不允许在调用后自动扩大。初始化基线使用 `max(现有 writer 估算, FALLBACK_INPUT + FALLBACK_OUTPUT)`，预算固定为 `5 × baseline` 并记录 basis；后续只有现有作者 topup 入口可扩容。

### 4. 取消以 job 为作用域

`ChapterRunJob.status` 使用 `queued | running | cancel_requested | cancelled | ...`。取消端点：

```text
POST /api/v1/run-jobs/{job_id}/cancel
```

- queued：直接进入 cancelled，不启动 worker。
- running：写 cancel_requested；当前节点完成后由 worker 收口为 cancelled。
- cancel_requested/cancelled：幂等返回当前状态。
- completed/failed/blocked：稳定 409 `RUN_JOB_NOT_CANCELLABLE`。

`run_job_id` 传播到 Orchestrator、LLM runner 和 LlmCall。worker 与 LLM 公共出口在每个新节点前检查持久化状态；数据库 CAS 是跨线程/跨进程的线性化真值，同进程注册表只缓存**已经成功提交**的 cancel 状态，不能抢在 DB 成功前单独停任务。取消请求和最终确认分别写 `scene_run_cancel_requested`、`scene_run_cancelled` OperationLog。

节点边界顺序固定为：**解析并持久化当前节点有效产物 → commit 当前节点 → 原子 claim 下一节点 → provider 调用**。claim 与取消都对同一 `ChapterRunJob.status` 做条件更新/存在性判断并在短事务中提交：取消先线性化则 claim 失败，claim 先线性化则该节点属于“已经开始”并允许完成。不能在 provider 已成功返回但正文/候选尚未提交时因 cancel 回滚该产物；也不能只做一次非原子 check 后再开始节点。registry 只能在 cancel CAS 提交成功后置位，DB 写失败时不得遗留仅内存生效的幽灵取消。

## Task 1：先红——schema、迁移和元数据守卫

**Files**

- Create: `backend/alembic/versions/20260713_0065_llm_accounting_budget_cancel.py`
- Modify: `config/models.yaml`
- Modify: `backend/src/novel_system/db/models.py`
- Modify: `backend/src/novel_system/tools/database_preflight.py`
- Create: `backend/tests/test_c1b_schema.py`
- Modify: `backend/tests/test_database_preflight.py`
- Modify: `backend/tests/test_generation_persistence.py`
- Modify: `backend/tests/test_metadata_isolation.py`
- Modify: `backend/tests/test_system_config.py`

- [x] 编写失败测试，要求 `SceneRunState` 存在：
  - `scene_tokens_reserved INTEGER NOT NULL DEFAULT 0`
  - `scene_budget_basis_json JSON NULL`
  - `provider_attempts_used INTEGER NOT NULL DEFAULT 0`、`provider_attempt_budget INTEGER NOT NULL DEFAULT 32`
  - `active_execution_id TEXT NULL`、`run_execution_status TEXT NULL`、`run_checkpoint TEXT NULL`、`run_checkpoint_json JSON NULL`
  - `active_run_job_id TEXT NULL`（同场景 active job 的 CAS 锁，不允许 query-then-insert）
- [x] 编写失败测试，要求 `LlmCall` 存在：
  - `scope_type TEXT NOT NULL`, `scope_id TEXT NOT NULL`, `run_job_id TEXT NULL`
  - `execution_id TEXT NULL`, `execution_step_key TEXT NULL`（同步 idempotency 与异步 job 共用的恢复关联键）
  - `estimated_tokens INTEGER NOT NULL DEFAULT 0`, `reserved_tokens INTEGER NOT NULL DEFAULT 0`, `budget_charged_tokens INTEGER NOT NULL DEFAULT 0`
  - `usage_is_estimate BOOLEAN NOT NULL DEFAULT true`, `accounting_status TEXT NOT NULL`, `request_dispatched_at TEXT NULL`, `settled_at TEXT NULL`
- [x] 为三类 token 与 `scene_tokens_reserved` 加非负 CheckConstraint，为 accounting status 加固定枚举约束；NULL/负数不能绕过预算聚合和条件更新。
- [x] `config/models.yaml retry_budget.provider_attempt_budget=32` 是独立安全上限，不冒充 LLMClient retry/degrade 的理论最大值；耗尽时允许提前停止内部重试。ORM default、0065 server_default/backfill 和 runtime fallback 都必须使用同一常量/配置测试，basis JSON 记录 config key/value，后续只能作者 topup。
- [x] 新增 `LlmCallAttempt`：`attempt_id` PK、`llm_call_id` FK→`llm_calls.llm_call_id`（审计行不级联删除）、父调用内 ordinal `provider_attempt_no`、`dispatch_kind`、request max output、provider request id、prompt/completion/total、estimated/reserved/charged、usage_is_estimate、accounting_status、request_dispatched_at/settled_at、latency/error；`(llm_call_id, provider_attempt_no)` 唯一，token 非负、status/dispatch kind 有枚举约束。
- [x] `ChapterRunJob` 新增 `scene_id TEXT NULL`，新 scene job 必填；0065 从旧 `payload_json/result_summary_json` 保守回填。加 `(scene_id, created_at)` 索引，使 latest terminal job 在 active lock 清除后仍可权威恢复。
- [x] 加索引：LlmCall 的 `(scope_type, scope_id, created_at)`、`run_job_id`、`(execution_id, execution_step_key)`、`accounting_status`；LlmCallAttempt 的 `llm_call_id/status`；ChapterRunJob 的 `(scene_id, created_at)`。
- [x] 迁移采用仓库已有 SQLite 存在性守卫；旧行不能伪造 provenance：统一回填 `usage_is_estimate=1`，`error_code IS NOT NULL` 回填 `accounting_status='failed'`，其余为 `settled`，`reserved=0`，token 字段只能从现有值保守复制，无法重建的历史失败维持 0 并在迁移/evidence 中声明不可追溯。旧 scope 依次从 scene/project/chapter 推导，均为空时回填 `system/<node_id-or-legacy>`。历史 logical call 不伪造 physical attempt 子行，audit 明确计为 legacy unreconstructable。downgrade 明确删除新增表/索引/列。
- [x] `database_preflight` 使用 revision-specific schema profile：`--expected-revision 0064` 仍按旧必需列验证迁移前 actual，0065 才要求 SceneRunState/LlmCall/LlmCallAttempt/ChapterRunJob 新列；generation persistence 同步 0065 head、attempt FK/orphan 盘点与旧行回填断言，不能只改 ORM/迁移。即使 actual `PRAGMA foreign_keys=0`，audit 也必须验证 attempt orphan=0。preflight CLI 增 `--output` 以无 BOM UTF-8 原子写 JSON，供证据直接哈希。
- [x] 迁移副本 `0064 -> 0065`，运行 metadata drift 和关键列检查。

Run:

```powershell
$env:PYTHONPATH='backend/src'
python -m pytest backend/tests/test_c1b_schema.py backend/tests/test_database_preflight.py backend/tests/test_generation_persistence.py backend/tests/test_metadata_isolation.py backend/tests/test_system_config.py -q
```

Commit:

```powershell
git add config/models.yaml backend/alembic/versions/20260713_0065_llm_accounting_budget_cancel.py backend/src/novel_system/db/models.py backend/src/novel_system/tools/database_preflight.py backend/tests/test_c1b_schema.py backend/tests/test_database_preflight.py backend/tests/test_generation_persistence.py backend/tests/test_metadata_isolation.py backend/tests/test_system_config.py
git commit -m "feat(accounting): add durable LLM budget fields"
```

## Task 2：先红——通用 usage 归一化与账本入口

**Files**

- Create: `backend/src/novel_system/services/llm_accounting.py`
- Modify: `backend/src/novel_system/services/llm_client.py`
- Create: `backend/tests/test_llm_accounting.py`
- Modify: `backend/tests/test_llm_client.py`

- [x] 测试本地输入/输出估算、UTF-8 预留上界、message overhead 和 `max_output_tokens`。
- [x] 测试 provider usage 完整时保存 actual 且 `usage_is_estimate=false`。
- [x] 测试显式 offline provider 的完整 0 usage 保持 0 且照常落父 LlmCall，不生成“真实 HTTP”子 attempt、不增加 provider_attempts_used，也不被 audit 误报为 legacy unreconstructable/missing usage。
- [x] 测试 usage 缺失、只有 input/output、total 不一致、非数字和负数；全部规范化且不能按 0 漏账。
- [x] `LLMResponse`/解析层保留 usage provenance/completeness（带安全默认值，兼容现有 fake）。不能只读已被 `_normalize_usage` 补成 0 的字典；用真实 `LLMClient` provider 解析路径构造“raw response 无 usage”集成红测，确认到账本后 `usage_is_estimate=true` 且非 0。
- [x] 测试 provider 失败：账本行持久化、`error_code` 保留、按保守估算结算、`accounting_status=failed`。
- [x] `LLMClient.generate` 接收内部 accounting attempt hook（对公共 caller 保持兼容）：每次 `_generate_once` POST、transport retry、parse retry、missing-text degrade 都调用 before-dispatch/after-response/after-error；外层逻辑调用返回稳定内部 `llm_call_id` 和可选 provider request id。
- [x] 红测首次 timeout 或 200 missing text、随后成功：父 LlmCall 下有 2 个 physical attempts，第一次按 unknown/actual 结算、第二次按 actual 结算，父 total/charged 为两者和；余额不足或 provider-attempt 只剩 1 时第二次 POST count=0。
- [x] 红测 degrade 把 max_output 扩大后的第二 attempt 使用新 request 上界重新预留，不能复用第一次较小 reservation。
- [x] 测试账本前置提交与外层业务失败：`LlmCall` 仍存在，已完成业务正文不被账本清理。
- [x] 用真实 file-backed SQLite 测 caller Session 已 flush 业务写的路径：账本入口用同 Session 提交前置状态后进入阻塞 provider，网络等待期间第二 Session 能提交状态写；provider 返回后结算成功，全程无 `database is locked`、无丢账。
- [x] dispatch 使用第二个短事务：reservation commit 后、真正调用 provider 前写 `request_dispatched_at` 并提交。crash 恢复遇 reserved+未 dispatched 可安全 release/retry；reserved+已 dispatched 或状态未知必须按保守估算 settle failed，并返回 `RUN_CHECKPOINT_OUTPUT_MISSING`，不得自动重发。
- [x] file-backed crash 红测分别中止在 reservation commit 后、dispatch commit 后：前者释放且同 step 可继续，后者记 estimate/failed、预算不免费、同 execution 不重发。
- [x] 实现唯一生产 provider 出口 `execute_accounted_call(...)`；接收 typed `LLMCallContext`，统一生成 call id、摘要、计时、成功/失败行。
- [x] 实现 `mark_postprocess_failure(...)`，供 provider 成功但结构化解析失败的 caller 更新同一账本行，不新增重复 call。

Run:

```powershell
python -m pytest backend/tests/test_llm_accounting.py backend/tests/test_llm_client.py -q
```

Commit:

```powershell
git add backend/src/novel_system/services/llm_accounting.py backend/src/novel_system/services/llm_client.py backend/tests/test_llm_accounting.py backend/tests/test_llm_client.py
git commit -m "feat(accounting): centralize provider call ledger"
```

## Task 3：先红——durable node checkpoint 与同执行恢复

**Files**

- Create: `backend/src/novel_system/services/scene_run_checkpoint.py`
- Modify: `backend/src/novel_system/services/orchestrator.py`
- Modify: `backend/src/novel_system/services/scene_generation.py`
- Modify: `backend/src/novel_system/services/idempotency.py`
- Modify: `backend/src/novel_system/services/scene_run_jobs.py`
- Modify: `backend/src/novel_system/services/chapter_runner.py`
- Modify: `backend/src/novel_system/api/routes/scenes.py`
- Create: `backend/tests/test_scene_run_checkpoint_resume.py`
- Modify: `backend/tests/test_idempotency_contract.py`
- Modify: `backend/tests/test_generation_persistence.py`

- [x] 为每次作者动作建立稳定 `execution_id`：同步 run 使用 `idempotency:<X-Idempotency-Key>`，scene job 使用 `job_id`，chapter runner 使用 `chapter_job_id:scene_id`；禁止随机重试 id 冒充同一执行。
- [x] `active_execution_id` 用 CAS 获取：同 id 的 active/failed execution 可恢复；不同 id 只能在旧 execution 已 failed/completed/cancelled 后原子 supersede。两个不同同步 key、scene job、chapter job 并发只允许一个获胜；旧 id 被取代后再重试稳定返回 `RUN_EXECUTION_SUPERSEDED`，不得覆盖新游标。
- [x] 同一 execution 也必须有唯一 owner lease：同步路径用 IdempotencyKey 的唯一 `worker_id/attempt_no/lease_expires_at`，job 路径用 ChapterRunJob owner/lease。started reclaim 必须做包含旧 owner、attempt、expiry 的条件 UPDATE；活 lease 一律 `IN_PROGRESS`，只有过期 lease 的 CAS 单赢家能恢复。
- [x] 每个 durable checkpoint 续租；provider 调用前按 `request.timeout_seconds + grace` 延长 lease，覆盖长网络节点，调用后再次续租。禁止继续沿用“固定 TTL 且中途不续租”的旧注释/实现。
- [x] checkpoint 固定宏阶段并按顺序推进：`budget_ready -> planning_ready -> bundle_ready -> neutral_ready -> hard_qc_ready -> style_ready -> selection_wait|soft_qc_ready -> near_final_ready -> archived`，另有 `cancelled`。checkpoint JSON 同时保存 `node_key + sub_index`（候选序号、continuation 分段、QC/patch/rewrite 迭代）以及恢复所需 bundle/draft/report/candidate/final row id、hash、策略和分支结果；每个子调用产物提交后推进，不能等整批完成才记录。
- [x] 当前节点的有效业务产物与 checkpoint 在同一事务提交；同 `execution_id` 重试先校验 checkpoint 所指行与 bundle hash，再从下一节点继续，不调用已完成 provider、不重复扣 token、不重复插确定性 PK。
- [x] 新 `execution_id` 才允许初始化新的运行游标；即使新执行也不得重置生命周期 token、reserved、attempt count/budget 或 latest-valid。
- [x] 每条 scene LlmCall 写 `execution_id + execution_step_key`；同步/异步都按该键与 checkpoint 对账，不能只靠 nullable `run_job_id` 或 scene 历史猜测。checkpoint 引用缺行/hash 不符时稳定失败 `RUN_CHECKPOINT_CORRUPT`，不得静默重跑已计费节点。若本 execution/step 账本已 settled 但产物尚未形成 checkpoint（进程在极窄窗口崩溃），返回 `RUN_CHECKPOINT_OUTPUT_MISSING` 并要求作者显式新执行，不能自动二次收费。
- [x] checkpoint 恢复复用 Task2 dispatch 状态：未 dispatch 的遗留 reservation 可释放后重做当前 step；已 dispatch/未知或已 settled 但无产物一律保守结算并阻断同 execution 自动重发。
- [x] `_prepare_state_for_run` 只在新的 execution 上清理可清理的 current 指针，不再对同 execution retry 清空；`from_step/resume` 要么接到 checkpoint 服务，要么删除无效参数，禁止保留“看似可恢复、实际未使用”的接口。
- [x] 集成红测：neutral 和 style 已 commit，下一节点失败；同 key 重试后 neutral/style provider call_count 与 used 不增、无重复 SceneDraft PK、latest-valid 保留、从失败节点继续。另测 Best-of-N 候选 1 已提交、候选 2 失败：重试只从候选 2 开始。
- [x] `generate_long_form_continuation` 当前无生产 caller；本 Task 只交付 service 级稳定 segment row/step、累计描述和 resume 验证。未来任何生产接入必须同时传 `segment_checkpoint` 与 `step_reconciler`：caller 在每个首缺 segment 的 provider 调用前按稳定 `long_form_continuation:<index>` 对账，已 dispatched/settled 但 segment 缺失时阻断为 `RUN_CHECKPOINT_OUTPUT_MISSING`、不得重发；成功后把 segment SceneDraft + AttemptTracker + cumulative descriptor + sub_index 在同一事务 commit。禁止依赖 service 内 commit；无 callback 仅保留测试/工具的旧单事务兼容语义。
- [x] Task 3F 边界审计：`run_scene` 与 `resume_after_selection` 在 `_finalize_after_style` 汇合。soft 之后至 `archived` 的剩余 provider 出口只有可选 auto critique 的 `auto_critique.llm_auto_critique -> run_task`、可选正文事件抽取的 `prose_event_extractor.extract_events_from_prose -> run_task`，以及章末 `NearFinalAcceptanceService.evaluate_chapter -> run`；全仓 `rg` 与 AST 函数归属盘点未发现该可达区间的其他 provider 出口。前两项必须随 Task 4 的 `run_task/execute_accounted_call` 迁移收口，章末评价也必须在 Task 4 的归档子游标收口；因此 Task 3 不宣称这三个延后出口已具备 exactly-once。归档器、规则事件写入、向量索引、章/卷聚合与风格漂移虽不是 provider 出口，也处在同一归档故障窗口，统一延后到 Task 4 的单调 archive subcursor 验收，禁止继续依赖最后一个整体 `archived` checkpoint。
- [x] Task 3F 的实现边界仅覆盖 scene-scoped durable `LLMNodeRunner.run`；无 runtime 的在线 `run`、全部 `run_task`（含 auto critique 与 prose extraction）以及 archive 子游标均明确留在 Task 4，Task 3F 不对这些路径宣称已闭环。
- [x] 集成红测：同 key 在 `IdempotencyKey.status=started/failed` 后重入复用同 execution；不同 payload 仍 409，不并发二次执行。
- [x] 两 Session/两个 owner barrier 红测：活 lease 下同 key 第二请求只能 IN_PROGRESS；过期 lease 并发 reclaim 只有一个 CAS 成功，provider 与 budget 只执行一次。
- [x] barrier 红测：两个不同 execution 同时 acquire 只允许一个；失败 execution 被新 execution supersede 后，旧 key 重试不改变 checkpoint、budget 或 active execution。

验收记录：五轮独立规范/质量复审最终均为 `APPROVED`；文件型 SQLite 崩溃窗口、父子账本篡改、owner lease、终态 claim、continuity 本地降级与 checkpoint 完整性均有聚焦回归覆盖。Task 4 延后边界保持在第 205–206 行，不在本任务冒充完成。

Run:

```powershell
python -m pytest backend/tests/test_scene_run_checkpoint_resume.py backend/tests/test_idempotency_contract.py backend/tests/test_generation_persistence.py -q
```

Commit:

```powershell
git add backend/src/novel_system/services/scene_run_checkpoint.py backend/src/novel_system/services/orchestrator.py backend/src/novel_system/services/scene_generation.py backend/src/novel_system/services/idempotency.py backend/src/novel_system/services/scene_run_jobs.py backend/src/novel_system/services/chapter_runner.py backend/src/novel_system/api/routes/scenes.py backend/tests/test_scene_run_checkpoint_resume.py backend/tests/test_idempotency_contract.py backend/tests/test_generation_persistence.py
git commit -m "feat(scene-run): resume durable node checkpoints"
```

## Task 4：先红——原子预留、结算、释放与 runner 统一

**Files**

- Modify: `backend/alembic/versions/20260713_0065_llm_accounting_budget_cancel.py`
- Modify: `backend/src/novel_system/db/models.py`
- Modify: `backend/src/novel_system/services/scene_budget.py`
- Modify: `backend/src/novel_system/services/llm_accounting.py`
- Modify: `backend/src/novel_system/services/llm_client.py`
- Modify: `backend/src/novel_system/services/llm_task_runner.py`
- Modify: `backend/src/novel_system/services/auto_critique.py`
- Modify: `backend/src/novel_system/services/prose_event_extractor.py`
- Modify: `backend/src/novel_system/services/narrative_event_log.py`
- Modify: `backend/src/novel_system/services/reverse_causal_skeleton.py`
- Modify: `backend/src/novel_system/services/author_drafts.py`
- Modify: `backend/src/novel_system/services/near_final.py`
- Modify: `backend/src/novel_system/services/projects.py`
- Modify: `backend/src/novel_system/services/qc_engine.py`
- Modify: `backend/src/novel_system/services/scene_blueprint.py`
- Modify: `backend/src/novel_system/services/scene_generation.py`
- Modify: `backend/src/novel_system/services/scene_quality.py`
- Modify: `backend/src/novel_system/services/style_profile.py`
- Modify: `backend/src/novel_system/services/writer_review.py`
- Modify: `backend/src/novel_system/services/writer_deep_review.py`
- Modify: `backend/src/novel_system/services/archiver.py`
- Modify: `backend/src/novel_system/services/aggregator.py`
- Modify: `backend/src/novel_system/services/orchestrator.py`
- Modify: `backend/src/novel_system/services/scene_run_checkpoint.py`
- Modify: `backend/src/novel_system/services/scene_run_jobs.py`
- Modify: `backend/src/novel_system/services/chapter_runner.py`
- Modify: `backend/src/novel_system/api/routes/scenes.py`
- Create: `backend/tests/test_scene_budget_reservations.py`
- Modify: `backend/tests/test_generation_persistence.py`
- Modify: `backend/tests/test_llm_accounting.py`
- Modify: `backend/tests/test_llm_task_runner.py`
- Modify: `backend/tests/test_scene_token_budget.py`
- Modify: `backend/tests/test_llm_critique_integration.py`
- Modify: `backend/tests/test_prose_event_extraction.py`
- Modify: `backend/tests/test_narrative_event_log.py`
- Modify: `backend/tests/test_blueprint_v2_modules.py`
- Modify: `backend/tests/test_scene_blueprint.py`
- Modify: `backend/tests/test_scene_quality_auto_rewrite.py`
- Modify: `backend/tests/test_scene_adopt_archive.py`
- Modify: `backend/tests/test_scene_run_checkpoint_resume.py`
- Modify: `backend/tests/test_near_final_engine.py`
- Modify: `backend/tests/test_scene_run_jobs.py`
- Modify: `backend/tests/test_chapter_runner.py`
- Modify: `backend/tests/test_orchestrator_flow.py`
- Modify: `backend/tests/test_author_drafts.py`
- Modify: `backend/tests/test_projects.py`
- Modify: `backend/tests/test_style_profile.py`
- Modify: `backend/tests/test_writer_review.py`
- Modify: `backend/tests/test_writer_review_lenses.py`
- Modify: `backend/tests/test_writer_deep_review.py`

执行拆分固定为四段，逐段先红并独立复审：4A 预算初始化、真实 request reservation 与三重发送前硬门；4B `run/run_task`、offline capability 与全部生产 caller 统一；4C auto critique/prose extraction 产品 envelope 和 checkpoint 血缘；4D 共享单调 archive subcursor。21 个 `run` 与 4 个 `run_task` 是静态清单基线；章末评价必须使用真实 chapter scope，任何 synthetic `scene_id` 都不得冒充 scene。归档全局入口若不能在本任务统一，完成声明必须降级为 scene-run archive，不得冒充全局归档闭环。

阶段验收记录（4A/4B）：公共 canonical budget 初始化、审计式 topup 重放、request reservation、token/业务/physical attempt 三重门禁、SQLite/PostgreSQL execution-step 唯一 claim、`run/run_task` 统一父子账本、21+4 caller typed context、scene/chapter job ownership、offline/no-call 语义和重复 callback/release 幂等均已实现。受影响范围回归 338 passed，补充 context/topup 边界回归 140 passed；独立规格与质量复审最终均为 `APPROVED`。本记录不勾选 Task 4 总体验收项；4C 产品 envelope、4D archive subcursor 及 Task 3D/3F 的 legacy 兼容移除仍未完成。

阶段验收记录（4C）：auto critique 与 prose extraction 已统一显式产品 envelope；called `run_task` 固定 online，offline 保存 `not_invoked/offline_unsupported`；成功、解析失败、provider 失败、发送前拒绝及规则/no-call 均绑定 typed owner、父调用、严格 physical-attempt 账本和稳定产品语义。`soft_qc_ready/sub_index=0` 同事务保存 critique/patch-failure 产品、产品 hash、独立 parsed-LLM anchor、generation provider-mode 历史快照及父账本锚点；创建期和恢复期使用同一 schema/owner/ledger/semantic 校验，released/rejected 崩溃窗口、配置 online/offline 切换、产品/owner/attempt/mode/hash 篡改均有定向阻断测试，已完成分支不重发且不重复扣账。最终验证包括 checkpoint 全量 135 passed、accounting/critique/prose/runner 166 passed、额外受影响模块 127 passed；最后一个 released-online→current-offline 组合修复后相关聚焦 66 passed。独立规格与质量复审最终均为 `APPROVED`，`compileall` 与 `git diff --check` 通过，实际数据库仍保持 revision `20260712_0064` 与原 SHA-256。本记录仍不勾选 Task 4 总体验收项；4D archive subcursor 尚未完成。

- [ ] 测试 `reserve -> settle`、`reserve -> release`、重复 settle/release 幂等、reserved 永不为负。
- [ ] 用两个独立 Session 和 barrier 测试并发预留：单 in-flight fence 只允许一个成功，失败线程不调用 provider；前者结算释放后后者可重新预留。
- [ ] 测试 provider usage 缺失、失败、actual 高于本地 estimate 但低于 reserved；`used + reserved <= budget` 始终成立。
- [ ] 测试 actual 高于 reserved 的不变量破坏分支：稳定错误、账本标异常、后续调用被阻止。
- [ ] 测试预算已耗尽时 neutral/style/QC 等基线调用也不发起，不再只拦“可选支出”。有 latest-valid 时返回该稿；无稿时进入明确 blocked 状态。
- [ ] scene-scoped 公共预留入口在 state/budget 为空时只做一次保守初始化并记录 basis；Orchestrator、独立 scene blueprint、scene quality/auto-rewrite 等入口都不得在初始化前调用 provider，也不要求每个 caller 自己记得 ensure。
- [ ] `total_attempt_count >= attempt_budget` 与 token 不足使用同一个发送前硬门：neutral/style/QC/run_task 辅助调用全部 provider count=0，并返回区别于 token exhausted 的稳定原因。
- [ ] physical attempt hook 在每次 dispatch 前原子检查/increment `provider_attempts_used < provider_attempt_budget`；首次失败后若只剩 0 次，LLMClient 内部 retry/degrade 的第二个 POST 必须为 0。发送前 cancel/reject 不增加 used。
- [ ] 把 `run` 和 `run_task` 都接到 `execute_accounted_call`；`run_task` 强制接收 typed context，不提供可漏 scope 的默认值，成功和失败均落账。
- [ ] 逐一修改 4 个生产 `run_task` caller：auto critique、prose event extractor、narrative consistency、reverse causal refine。前两条由 Orchestrator 显式传 scene/chapter/project/run_job，因此进入同一生命周期预算；无场景对象的 causal refine 也必须传明确 project/system scope。
- [ ] AST 守卫所有生产 `run_task(...)` 调用都存在 `context=`，并用集成测试证明 auto critique/event extraction 会增加同一 scene 的 LlmCall 与 budget charged，预算不足时 caller 降级且 provider count=0。
- [ ] auto critique 的返回产品必须携带稳定父 `llm_call_id` 与 `execution_step_key`（同一 execution 固定 step，不得由重试随机生成）；`soft_qc_ready/sub_index=0` 同事务保存 critique 产品快照、产品 hash、父 call id、step 和 execution owner。恢复先逐项验证产品/hash/call/owner，再从 soft sub1 继续；产品缺行、父/子账不完整或任一字段被篡改时稳定 `RUN_CHECKPOINT_CORRUPT`，provider call count 与 budget charged 均不得增加。规则模式/预算拒绝/降级也必须保存明确的无调用 outcome，不能把“没有 call”与“call 引用丢失”混为一谈。
- [ ] 在 `near_final_ready/sub_index=3` 与最终 `archived` 之间建立单调 archive subcursor，并让首次运行与 `_archive_near_final_checkpoint` 走同一实现。至少逐项保存、散列并恢复验证：Archiver 的 `FinalScene(status=archived)`、`SceneMemory`、`ChapterRollingNote`、archive AttemptTracker；规则生成的 NarrativeEvent 行；可选 prose extraction 的父 call/step/owner、抽取结果及对应 NarrativeEvent 行（含显式 skipped/degraded outcome）；向量索引的幂等结果/失败 outcome；章末 `ChapterMemory` 聚合、卷聚合结果或 no-op/degraded outcome；章末 `WriterEvaluation` 及其父 call/step/owner；风格漂移 guidance 或 no-op/degraded outcome。任一步产品与本级 subcursor 同事务提交，任一步失败后同 execution 只从下一未完成步骤继续；已完成分支不得重复写副作用、调用 provider 或扣预算，缺行/错绑/hash 篡改必须阻断恢复。只有全部适用步骤验证通过后才能写最终 `archived` checkpoint。
- [ ] 删除 `_persist_call` 中 usage 缺失记 0 的旧逻辑和 `record_usage` 旁路；所有场景扣账只走 reservation settlement。
- [ ] 父 LlmCall 聚合所有 physical attempts；SceneDraft 等业务引用仍指向父 `llm_call_id`，不能指向某次 retry 子行。成本测试证明父/子不双计。
- [ ] `LLMNodeRunner.run` 与 `run_task` 的 attempt 子账是强制不变量：每个真实 dispatched provider attempt（含 transport/parse retry 与 degrade hop）都必须存在 `LlmCallAttempt`，父 `LlmCall` 必须由子行聚合状态与 token；offline/no-dispatch 只能使用明确可验证的零 attempt 语义，不允许以 legacy 父行或 AttemptTracker 冒充 physical attempt。
- [ ] Task 3D/3F 延后到本任务收紧：当 `LLMNodeRunner.run/run_task` 全部迁到 `execute_accounted_call` 后，style/de-template、auto critique、prose extraction 与章末 evaluate_chapter 的恢复校验必须移除“仅 legacy parent + AttemptTracker”兼容分支，强制校验连续 ordinal、dispatch/status、父子 token 聚合、attempt PK/FK 以及 checkpoint 的 call/step/execution owner；缺行或篡改必须 `RUN_CHECKPOINT_CORRUPT`，且 provider/budget 不增。
- [ ] 保留外层有效稿；账本提交不得清空 `latest_valid_draft_row_id`。

Run:

```powershell
python -m pytest backend/tests/test_scene_budget_reservations.py backend/tests/test_scene_token_budget.py backend/tests/test_llm_critique_integration.py backend/tests/test_prose_event_extraction.py backend/tests/test_narrative_event_log.py backend/tests/test_blueprint_v2_modules.py backend/tests/test_scene_blueprint.py backend/tests/test_scene_quality_auto_rewrite.py backend/tests/test_scene_run_checkpoint_resume.py backend/tests/test_near_final_engine.py -q
```

Commit:

```powershell
git add backend/src/novel_system/services/scene_budget.py backend/src/novel_system/services/llm_task_runner.py backend/src/novel_system/services/auto_critique.py backend/src/novel_system/services/prose_event_extractor.py backend/src/novel_system/services/narrative_event_log.py backend/src/novel_system/services/reverse_causal_skeleton.py backend/src/novel_system/services/near_final.py backend/src/novel_system/services/archiver.py backend/src/novel_system/services/aggregator.py backend/src/novel_system/services/orchestrator.py backend/tests/test_scene_budget_reservations.py backend/tests/test_scene_token_budget.py backend/tests/test_llm_critique_integration.py backend/tests/test_prose_event_extraction.py backend/tests/test_narrative_event_log.py backend/tests/test_blueprint_v2_modules.py backend/tests/test_scene_blueprint.py backend/tests/test_scene_quality_auto_rewrite.py backend/tests/test_scene_run_checkpoint_resume.py backend/tests/test_near_final_engine.py
git commit -m "feat(budget): reserve scene tokens before every call"
```

## Task 5：先红——收口全部生产 LLM 出口

**Files**

- Modify: `backend/src/novel_system/services/snowflake_workspace_llm.py`
- Modify: `backend/src/novel_system/services/system_config.py`
- Modify: `backend/src/novel_system/services/style_reference/_llm_helper.py`
- Modify: `backend/src/novel_system/services/style_reference/ingest.py`
- Modify: `backend/src/novel_system/services/style_reference/segmentation/__init__.py`
- Modify: `backend/src/novel_system/services/style_reference/segmentation/llm.py`
- Modify: `backend/src/novel_system/services/style_reference/extractors/base.py`
- Modify: `backend/src/novel_system/services/style_reference/profile_synthesizer.py`
- Modify: `backend/src/novel_system/services/style_reference/preview.py`
- Modify: `backend/src/novel_system/services/style_reference/validation/semantic.py`
- Modify: `backend/src/novel_system/services/style_reference/validation/forbidden_semantic.py`
- Modify: `backend/src/novel_system/services/style_reference/validation/runner.py`
- Modify: `backend/src/novel_system/services/library_derive.py`
- Modify: `backend/src/novel_system/services/longform_tower.py`
- Modify: `backend/src/novel_system/services/literary_eval.py`
- Modify: `backend/src/novel_system/api/routes/literary_eval.py`
- Modify: `backend/src/novel_system/tools/literary_eval.py`
- Create: `backend/src/novel_system/tools/llm_outlet_inventory.py`
- Create: `backend/src/novel_system/tools/llm_accounting_audit.py`
- Modify: `backend/src/novel_system/tools/prompt_handoff_annotations.py`
- Modify: `docs/prompt-optimization-handoff.md`
- Create: `backend/tests/test_llm_accounting_outlets.py`
- Create: `backend/tests/test_llm_accounting_tools.py`
- Modify: `backend/tests/test_system_config.py`
- Modify: affected service/route tests

- [ ] AST 失败测试枚举生产 `.generate(...)` 调用表达式和 completion probe 的 `httpx.post`；除 `llm_accounting.py` 外不得存在真实 completion 出口。模型列表/健康检查 GET 不计 token，离线 fake 的 `def generate` 不算出口。
- [ ] `SystemConfigService._probe_completion` 通过账本化 probe helper 发出最小生成请求，scope 为 `system/provider_probe`；成功、HTTP 错误和 transport failure 均落账，不能因为它不是 `LLMClient.generate` 就漏记。
- [ ] snowflake 迁移到通用入口，保留 project/step scope、prompt hash、parse failure 更新和现有错误码。
- [ ] style-reference 公共 helper 增 session/scope context，7 个 typed caller 全量传递；`ingest -> segmentation.__init__ -> segmentation.llm` 和 `validation.runner -> semantic/forbidden` 全链传递 session/scope，分段直连也走通用入口，不回退 C1A 不可信边界。
- [ ] library derive、longform audit 落 project/chapter scope。
- [ ] literary eval API 与 CLI 为每个 case 落 eval run/case scope；`execute_accounted_call` 返回并传播内部稳定 `llm_call_id`，报告直接保存该 id 对账，provider request id 只作为可空外部字段，不能充当主关联键。
- [ ] 所有直接出口的成功、usage 缺失和失败测试至少各覆盖一条；禁止因“非场景调用无预算”而跳过账本。
- [ ] 提供只读 JSON 工具：outlet inventory 输出 application-level completion 出口及是否统一；accounting audit 输出 schema、scope 空值、负 token、stuck reserved、LlmCallAttempt orphan、status/usage provenance 和 legacy unreconstructable counts，供 actual/drill 证据复算。
- [ ] 更新 handoff 权威源并用生成器 `--check` 验证文档逐字一致。

Run:

```powershell
python -m pytest backend/tests/test_llm_accounting_outlets.py backend/tests/test_llm_accounting_tools.py backend/tests/test_system_config.py backend/tests/test_snowflake_workspace_v2.py backend/tests/test_style_reference_llm_routing.py backend/tests/test_style_reference_segmentation.py backend/tests/test_literary_eval.py -q
python -m novel_system.tools.export_prompt_handoff --check
```

Commit:

```powershell
git add backend/src/novel_system/services backend/src/novel_system/api/routes/literary_eval.py backend/src/novel_system/tools/literary_eval.py backend/src/novel_system/tools/prompt_handoff_annotations.py backend/tests docs/prompt-optimization-handoff.md
git commit -m "feat(accounting): cover every production LLM outlet"
```

## Task 6：先红——生命周期预算初始化、重跑和成本口径

**Files**

- Modify: `backend/src/novel_system/services/orchestrator.py`
- Modify: `backend/src/novel_system/services/scene_generation.py`
- Modify: `backend/src/novel_system/services/cost_aggregation.py`
- Modify: `backend/src/novel_system/api/routes/scenes.py`
- Modify: `backend/tests/test_scene_token_budget.py`
- Modify: `backend/tests/test_cost_aggregation.py`
- Modify: `backend/tests/test_scene_cost_cancellation_recovery.py`

- [ ] 验证公共预留层的一次性预算初始化在 Orchestrator 与独立 blueprint/quality 入口一致，basis 不因后续 bundle 或重跑自动扩大。
- [ ] 删除 `_prepare_state_for_run` 对 `total_attempt_count` 的自动重置；token budget、used、reserved、attempt count/budget 都不得由自动重跑清零。
- [ ] 重跑测试：历史 used/attempt 保留，余额不足时 provider call count 不增加；只有 topup 可扩大预算。
- [ ] topup 支持显式 `extra_tokens`、`extra_attempts` 和/或 `extra_provider_attempts`（至少一项为正），返回并审计 token budget、业务 attempt budget、physical provider-attempt budget、used、reserved；这是三类生命周期上限的唯一扩容入口，禁止隐式清除任何 used/reserved/count。
- [ ] 成本聚合三口径改为读取新字段：estimate、provider actual、budget charged；父 LlmCall 聚合 attempt，报表只计一层，usage estimate/异常/retry/degrade 数量可见。
- [ ] 移除“over budget 仍正常”作为可接受主语义的旧测试，改为兼容只读历史脏数据但新调用不能制造 over-budget。

Run:

```powershell
python -m pytest backend/tests/test_scene_token_budget.py backend/tests/test_cost_aggregation.py backend/tests/test_scene_cost_cancellation_recovery.py -q
```

Commit:

```powershell
git add backend/src/novel_system/services/orchestrator.py backend/src/novel_system/services/scene_generation.py backend/src/novel_system/services/cost_aggregation.py backend/src/novel_system/api/routes/scenes.py backend/tests/test_scene_token_budget.py backend/tests/test_cost_aggregation.py backend/tests/test_scene_cost_cancellation_recovery.py
git commit -m "fix(budget): enforce lifecycle limits across reruns"
```

## Task 7：先红——取消 API、worker 状态机与审计

**Files**

- Modify: `backend/src/novel_system/services/scene_run_jobs.py`
- Modify: `backend/src/novel_system/services/orchestrator.py`
- Modify: `backend/src/novel_system/services/llm_accounting.py`
- Modify: `backend/src/novel_system/services/scene_budget.py`
- Modify: `backend/src/novel_system/services/author_state.py`
- Modify: `backend/src/novel_system/services/versioning/runtime_recovery.py`
- Modify: `backend/src/novel_system/api/routes/scenes.py`
- Create: `backend/tests/test_scene_run_cancellation.py`
- Modify: `backend/tests/test_fe_scene_run_guards.py`
- Modify: `backend/tests/test_author_state_projection.py`
- Modify: `backend/tests/test_indexing_contracts.py`

- [ ] 队列态取消：worker 未开始，0 provider calls，job=cancelled，OperationLog 两阶段或直接确认完整。
- [ ] 运行态取消：用阻塞 fake 模拟正在执行的 provider；取消时当前调用完成并结算，下一调用 count 保持 0，已有 draft/账单不回滚。
- [ ] 预算拒绝、普通 provider 失败、作者取消分别得到不同 job status/error/audit，不复用同一个 `failed`。
- [ ] 重复 cancel 幂等；completed/failed/blocked 返回 409；错误码和 details 稳定。
- [ ] queued→running 与 queued→cancelled、running→cancel_requested 全部使用条件 UPDATE/CAS 并检查 rowcount；用真实 barrier race 证明只有一个转换胜出，失败方按最终状态重读，不能用普通属性赋值覆盖。
- [ ] worker claim 写唯一 `worker_id` 与 `lease_expires_at`；每个节点边界续租，provider 前按 request timeout+grace 延长 lease。另一进程的 cancel endpoint 只能 running→cancel_requested，不能因本地 registry 没有该 worker 就判死亡或释放 reservation。
- [ ] 下一节点 claim 与 scene budget reservation 在同一短事务中要求 job 仍为 running；用 barrier 测 claim-vs-cancel：cancel 先提交则 provider count=0，claim 先提交则只允许当前节点完成，下一 claim 必败。
- [ ] 创建 job 通过 `SceneRunState.active_run_job_id` CAS 原子占位；两个 Session 并发创建同场景 job 只能一个成功。terminal/cancelled 清理也用 `WHERE active_run_job_id=:job_id`，不能清掉更新 job 的锁。
- [ ] registry 只在 DB cancel CAS 成功后置位；注入 DB busy/commit failure 时 endpoint 返回失败且 registry 不得残留取消信号。
- [ ] worker 启动、每个编排阶段、预留前和预留后使用上述 claim；`run_job_id`、`execution_id`、step/sub-index 落每条相关 LlmCall。
- [ ] 测试并实现“产物 commit 后再观察 cancel”的节点边界顺序；provider 已返回的有效 draft/candidate 必须保留，取消只阻止下一个节点。
- [ ] 新增 `GET /api/v1/scenes/{scene_id}/run/jobs/latest`（或 scene-run-states 等价权威字段），返回 latest job id/status/current_step；`author_state` active job 集合纳入 cancel_requested，刷新后不依赖内存变量恢复。
- [ ] 进程重启后以数据库 `cancel_requested` 为真值：只有 DB lease 已过期且 recovery 通过 owner+lease CAS 取得回收权，才能按 dispatch 状态结算/释放遗留 reservation、标 cancelled、清 active job；有效 lease 即使不在本进程 registry 也不得提前收口。
- [ ] 两 service/进程语义红测：A 持有效 lease 和阻塞 provider，B cancel 只写 cancel_requested、不释放当前 call；lease 过期后 sweep 单赢家收口，任务不会永久卡非终态。

Run:

```powershell
python -m pytest backend/tests/test_scene_run_cancellation.py backend/tests/test_fe_scene_run_guards.py backend/tests/test_author_state_projection.py backend/tests/test_indexing_contracts.py -q
```

Commit:

```powershell
git add backend/src/novel_system/services/scene_run_jobs.py backend/src/novel_system/services/orchestrator.py backend/src/novel_system/services/llm_accounting.py backend/src/novel_system/services/scene_budget.py backend/src/novel_system/services/author_state.py backend/src/novel_system/services/versioning/runtime_recovery.py backend/src/novel_system/api/routes/scenes.py backend/tests/test_scene_run_cancellation.py backend/tests/test_fe_scene_run_guards.py backend/tests/test_author_state_projection.py backend/tests/test_indexing_contracts.py
git commit -m "feat(scene-run): add explicit cancellable jobs"
```

## Task 8：先红——作者取消 UI

**Files**

- Modify: `frontend-react/src/lib/client.js`
- Modify: `frontend-react/src/ws-scene-run.jsx`
- Modify: `frontend-react/src/ws-scene-run.test.jsx`

- [ ] API client 增 `cancelRunJob(jobId)` 与 `getLatestSceneRunJob(sceneId)`，复用幂等 key 规则。
- [ ] running/queued/cancel_requested 显示可访问的状态与取消按钮；点击后禁用重复提交并继续轮询到 terminal cancelled。
- [ ] completed/failed/blocked 不显示可执行取消按钮；409 显示明确不可取消原因。
- [ ] React 测试覆盖请求、状态切换、重复点击；刷新/重新进入时从 latest-job 权威 API 恢复 cancel_requested/cancelled job，不依赖函数局部 `job_id` 或 localStorage。

Run:

```powershell
npm --prefix frontend-react test -- --run
npm --prefix frontend-react run build
```

Commit:

```powershell
git add frontend-react/src/lib/client.js frontend-react/src/ws-scene-run.jsx frontend-react/src/ws-scene-run.test.jsx
git commit -m "feat(scene-run): expose author cancellation control"
```

## Task 9：迁移 actual、全量回归与 C1B 证据

**Files**

- Create: `docs/superpowers/evidence/20260713-c1b-accounting-budget-cancel.json`
- Modify: `docs/superpowers/specs/2026-07-13-ai-novel-outcome-governance-completion-assessment.md`
- Modify: `docs/superpowers/plans/2026-07-13-c1b-accounting-budget-cancellation.md`
- Modify: `backend/src/novel_system/services/outcome_evidence.py`
- Modify: `backend/src/novel_system/tools/outcome_evidence.py`
- Modify: `backend/tests/test_outcome_evidence.py`

- [ ] canonical actual 固定为 `E:\codex\xiaoshuo\codex\backend\novel_system.db`，禁止使用 worktree 相对路径 `backend/novel_system.db`（当前仅 4096 bytes）。执行前 `Resolve-Path` 必须等于 canonical path、文件必须大于 1 MiB、preflight 必须为 0064；显式设置 `NOVEL_SYSTEM_DATABASE_URL=sqlite:///E:/codex/xiaoshuo/codex/backend/novel_system.db`。
- [ ] 保存进程/监听端口/WAL 快照，确认没有明确 backend/uvicorn/数据库 writer；无法确认则停止，不迁移。
- [ ] 对 canonical actual 做新校验备份；verify 失败则停止。
- [ ] 在备份副本演练 `0064 -> 0065`，通过 preflight、metadata drift、关键表列和 ledger smoke 后再升级 actual。
- [ ] actual 升到 `0065`，再次 preflight/backup verify；记录旧 LlmCall 回填数和 reserved=0 盘点。
- [ ] 运行后端非 Chroma 全量、React 全量、生产构建；Chroma 按平台规则单独记录 skipped，不隐去。
- [ ] 运行 C1B gate：所有生产出口落账、usage missing、失败、actual>estimate、并发预留、重跑、排队取消、运行中取消、取消不回滚。
- [ ] 扩展 `outcome_evidence validate --profile c1b`：强制 C1B required gate 完整、database revision=0065、offline provenance、命令时间/退出码、artifact 存在/hash 和关键 gate details；generic validate 不能冒充 C1B 通过。
- [ ] 生成 `outcome-evidence-v1` offline manifest，至少包含 git commit、0065 revision、备份 hash、进程/WAL 快照、drill/actual audit、静态出口盘点、后端/前端 JUnit 与 build log/hash，以及以下 gates：
  - `ALL_PRODUCTION_LLM_OUTLETS_ACCOUNTED`
  - `ALL_PHYSICAL_PROVIDER_ATTEMPTS_ACCOUNTED`
  - `MISSING_USAGE_ESTIMATED`
  - `FAILED_CALLS_CHARGED`
  - `RETRY_AND_DEGRADE_BUDGETED`
  - `ATOMIC_RESERVATION_NO_OVERSPEND`
  - `BASELINE_CALLS_BUDGETED`
  - `LIFECYCLE_BUDGET_NOT_RESET`
  - `CHECKPOINT_RESUME_NO_REPLAY`
  - `QUEUED_CANCEL_NO_CALL`
  - `RUNNING_CANCEL_STOPS_NEXT_NODE`
  - `CANCEL_CAS_LINEARIZABLE`
  - `CANCEL_PRESERVES_DRAFT_AND_LEDGER`
- [ ] assessment 只把 P0-4 和“显式取消缺失”的 engineering gate 改为 passed；真实账单、跨 provider 可比性、real/release 继续 pending。
- [ ] 使用 `--profile c1b --require-provenance offline` 对 ignored artifact root 做外部复算；独立规格审查、质量审查和 manifest 复算全部通过后提交。

Run:

```powershell
$ErrorActionPreference = 'Stop'
$actual = 'E:\codex\xiaoshuo\codex\backend\novel_system.db'
$resolved = (Resolve-Path $actual).Path
if ($resolved -ne $actual -or (Get-Item $actual).Length -le 1MB) { throw 'canonical actual database check failed' }
$global:LASTEXITCODE = 0
$shortSha = (git rev-parse --short HEAD).Trim()
if ($LASTEXITCODE -ne 0 -or -not $shortSha) { throw 'cannot resolve evidence git commit' }
$runId = '20260713-c1b-' + (Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssZ') + '-' + $shortSha
$run = Join-Path 'E:\codex\xiaoshuo\codex\.worktrees\outcome-governance-closure\.codex-run\governance-c1b' $runId
if (Test-Path $run) { throw "evidence run directory already exists: $run" }
New-Item -ItemType Directory $run | Out-Null

$utf8NoBom = New-Object System.Text.UTF8Encoding($false)
$script:commandLog = @()
function Save-CommandLog {
  $payload = [ordered]@{ schema='c1b-command-log-v1'; commands=$script:commandLog } | ConvertTo-Json -Depth 8
  [System.IO.File]::WriteAllText("$run\commands.json", $payload, $utf8NoBom)
}
function Invoke-Checked([string]$id, [scriptblock]$command) {
  $started = (Get-Date).ToUniversalTime().ToString('o')
  $global:LASTEXITCODE = 0
  try {
    & $command
    $code = [int]$global:LASTEXITCODE
  } catch {
    $code = if ($global:LASTEXITCODE) { [int]$global:LASTEXITCODE } else { 1 }
    $script:commandLog += [ordered]@{ id=$id; command=$command.ToString().Trim(); started_at_utc=$started; ended_at_utc=(Get-Date).ToUniversalTime().ToString('o'); expected_exit=@(0); actual_exit=$code }
    Save-CommandLog
    throw
  }
  $script:commandLog += [ordered]@{ id=$id; command=$command.ToString().Trim(); started_at_utc=$started; ended_at_utc=(Get-Date).ToUniversalTime().ToString('o'); expected_exit=@(0); actual_exit=$code }
  Save-CommandLog
  if ($code -ne 0) { throw "$id failed with exit $code" }
}

$listeners = @(Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue)
$writers = @(Get-CimInstance Win32_Process | Where-Object {
  $_.ProcessId -ne $PID -and $_.CommandLine -match '(uvicorn|novel_system|python[^\r\n]*backend)'
})
$processScan = [ordered]@{
  captured_at_utc = (Get-Date).ToUniversalTime().ToString('o')
  actual_database = $actual
  wal_size_bytes = if (Test-Path "$actual-wal") { (Get-Item "$actual-wal").Length } else { 0 }
  writer_matches = @($writers | ForEach-Object { [ordered]@{ process_id=$_.ProcessId; name=$_.Name; command_line=$_.CommandLine } })
  listening_connections = @($listeners | ForEach-Object { [ordered]@{ process_id=$_.OwningProcess; local_address=$_.LocalAddress; local_port=$_.LocalPort } })
}
[System.IO.File]::WriteAllText("$run\process-scan.json", ($processScan | ConvertTo-Json -Depth 6), $utf8NoBom)
if ($writers.Count -gt 0) { throw 'possible actual database writer detected' }

Push-Location backend
$env:PYTHONPATH='src'
$env:NOVEL_SYSTEM_DATABASE_URL='sqlite:///E:/codex/xiaoshuo/codex/backend/novel_system.db'
Invoke-Checked 'actual-preflight-before' { python -m novel_system.tools.database_preflight $actual --expected-revision 20260712_0064 --output "$run\actual-preflight-before.json" }
Invoke-Checked 'actual-backup' { python -m novel_system.tools.db_backup --backup $actual "$run\database-before-0065.db" }
Invoke-Checked 'backup-verify-before' { python -m novel_system.tools.db_backup --verify "$run\database-before-0065.db" }
Invoke-Checked 'drill-restore' { python -m novel_system.tools.db_backup --restore "$run\database-before-0065.db" "$run\migration-drill.db" }

$drillUrlPath = (Join-Path $run 'migration-drill.db').Replace('\', '/')
$env:NOVEL_SYSTEM_DATABASE_URL="sqlite:///$drillUrlPath"
Invoke-Checked 'drill-upgrade' { python -m alembic upgrade head *> "$run\drill-alembic.log" }
Invoke-Checked 'drill-preflight' { python -m novel_system.tools.database_preflight "$run\migration-drill.db" --expected-revision 20260713_0065 --output "$run\drill-preflight.json" }
Invoke-Checked 'drill-accounting-audit' { python -m novel_system.tools.llm_accounting_audit --database "$run\migration-drill.db" --json --output "$run\migration-drill-accounting.json" }
Invoke-Checked 'drill-metadata-regression' { python -m pytest tests/test_metadata_isolation.py tests/test_generation_persistence.py tests/test_database_preflight.py -q --junitxml="$run\migration-focused.junit.xml" }

$env:NOVEL_SYSTEM_DATABASE_URL='sqlite:///E:/codex/xiaoshuo/codex/backend/novel_system.db'
try {
  Invoke-Checked 'actual-upgrade' { python -m alembic upgrade head *> "$run\actual-alembic.log" }
  Invoke-Checked 'actual-preflight-after' { python -m novel_system.tools.database_preflight $actual --expected-revision 20260713_0065 --output "$run\actual-preflight-after.json" }
  Invoke-Checked 'actual-accounting-audit' { python -m novel_system.tools.llm_accounting_audit --database $actual --json --output "$run\actual-accounting.json" }
} catch {
  Invoke-Checked 'actual-restore-after-migration-failure' { python -m novel_system.tools.db_backup --restore "$run\database-before-0065.db" $actual }
  Invoke-Checked 'actual-restore-verify' { python -m novel_system.tools.db_backup --verify $actual }
  Invoke-Checked 'actual-restore-preflight' { python -m novel_system.tools.database_preflight $actual --expected-revision 20260712_0064 --output "$run\actual-restore-preflight.json" }
  throw
}
Invoke-Checked 'backup-verify-after' { python -m novel_system.tools.db_backup --verify "$run\database-before-0065.db" }
Invoke-Checked 'llm-outlet-inventory' { python -m novel_system.tools.llm_outlet_inventory --json --output "$run\llm-outlet-inventory.json" }
Invoke-Checked 'c1b-gates' { python -m pytest tests/test_llm_accounting.py tests/test_llm_client.py tests/test_scene_budget_reservations.py tests/test_scene_run_checkpoint_resume.py tests/test_scene_run_cancellation.py tests/test_llm_accounting_outlets.py -q --junitxml="$run\c1b-gates.junit.xml" }
Invoke-Checked 'backend-full' { python -m pytest tests -q -m "not chroma_integration" --junitxml="$run\backend-full.junit.xml" }
Pop-Location

Invoke-Checked 'frontend-tests' { npm --prefix frontend-react test -- --reporter=junit --outputFile="$run\frontend.junit.xml" }
Invoke-Checked 'frontend-build' { npm --prefix frontend-react run build *> "$run\frontend-build.log" }

$artifactRows = @(Get-ChildItem -File $run | Where-Object Name -ne 'artifacts.json' | Sort-Object Name | ForEach-Object {
  [ordered]@{ path=$_.Name; size_bytes=$_.Length; sha256=(Get-FileHash -Algorithm SHA256 $_.FullName).Hash.ToLowerInvariant() }
})
$artifactIndex = [ordered]@{ schema='c1b-artifact-index-v1'; generated_at_utc=(Get-Date).ToUniversalTime().ToString('o'); artifacts=$artifactRows }
[System.IO.File]::WriteAllText("$run\artifacts.json", ($artifactIndex | ConvertTo-Json -Depth 8), $utf8NoBom)

# 用 apply_patch 把本次唯一 $runId/$run 写入 tracked manifest 后，以下是外部复算，不写回 manifest/command log。
python -m json.tool docs/superpowers/evidence/20260713-c1b-accounting-budget-cancel.json > $null
if ($LASTEXITCODE -ne 0) { throw "manifest json validation failed: $LASTEXITCODE" }
Push-Location backend
$env:PYTHONPATH='src'
python -m novel_system.tools.outcome_evidence validate ..\docs\superpowers\evidence\20260713-c1b-accounting-budget-cancel.json --artifact-root "$run" --profile c1b --require-provenance offline
if ($LASTEXITCODE -ne 0) { throw "C1B evidence profile validation failed: $LASTEXITCODE" }
Pop-Location
git diff --check
if ($LASTEXITCODE -ne 0) { throw "git diff --check failed: $LASTEXITCODE" }
```

Commit:

```powershell
git add backend/src/novel_system/services/outcome_evidence.py backend/src/novel_system/tools/outcome_evidence.py backend/tests/test_outcome_evidence.py docs/superpowers/evidence/20260713-c1b-accounting-budget-cancel.json docs/superpowers/specs/2026-07-13-ai-novel-outcome-governance-completion-assessment.md docs/superpowers/plans/2026-07-13-c1b-accounting-budget-cancellation.md
git commit -m "docs(governance): close C1B accounting and cancellation"
```

## C1B 完成门

- [ ] 生产代码只有统一的 application-level completion 入口；system probe 和每个真实 provider physical attempt 都可按 scope/logical call/attempt 查询。
- [ ] provider usage 缺失和失败调用均非 0 结算且显式标 estimate。
- [ ] 任何预算预留失败都不发起 provider 请求。
- [ ] 新调用永远满足 `scene_tokens_used + scene_tokens_reserved <= scene_token_budget`。
- [ ] 同 execution checkpoint 恢复不重放已完成节点/候选；provider retry/degrade 每次单独记账并重新过硬门。
- [ ] 自动重跑不重置 token、业务 attempt 或 physical provider-attempt 账目，topup 是唯一扩容入口。
- [ ] queued cancel 为 0 调用；running cancel 完成当前节点后不再开始下一节点。
- [ ] 取消、预算耗尽、普通失败状态与审计可区分；已有正文和账单不回滚。
- [ ] actual 库到 `0065`，备份、迁移、回归和 offline manifest 可复算。
- [ ] 真实账单、跨 provider token 可比性、真实模型和发布门没有被 offline 工程证据冒充。
