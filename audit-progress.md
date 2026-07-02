# 系统审查进度记录

> 本文件是审查过程的进度账本（AUDIT_PROMPT.md 阶段 0 要求）。最终报告：`docs/system-audit-report.md`。
> 只读审查：全程不修改任何源代码文件。

## 状态总览

- [x] 阶段 0：系统地图
- [x] 阶段 1：宏观架构评估
- [x] 阶段 2：模块级评估（深审+轻扫分级，见报告 §9）
- [x] 阶段 3：系统流程评估（5 条端到端）
- [x] 阶段 4：报告已产出 `docs/system-audit-report.md`（测试基线已回填：1302 passed / 4 skipped / 0 failed，31m57s，退出码 0）

## 审查结束
全部阶段完成。交付物：`docs/system-audit-report.md`（20 项编号问题、5 条流程评估、行动路线图、6 项待确认）。审查阶段未修改任何源代码文件。

---

# 修复执行记录（2026-07-02，按报告 §7 路线图）

## 第一批（快速见效）
- [x] P-4 orchestrator.py `_load_style_baseline`：`binding.active` → `status == "active"`；单测 test_bundle_injection_efficacy::test_load_style_baseline_reads_active_binding。
- [x] P-5 bundle_builder `_character_arc_weights_prompt`：`select(func.count()).select_from(...)` 合法化 + 分母加 project/trashed 过滤；单测 ::test_character_arc_weights_query_does_not_degrade。
- [x] P-6 `_narrative_state_digest`：scene.project_id 优先、rsplit 仅兜底（与写侧对齐）；单测 ::test_narrative_state_digest_uses_scene_project_id。
- [x] P-7 `_index_scene_to_vector_store` + `_similar_scene_context`：改走 get_vector_store() 工厂；单测 ::test_scene_vector_indexing_persists_via_factory。
- [x] P-1 新建 services/chapter_state.py `ensure_chapter_state` 唯一入口；archiver/aggregator/chapter_runtime/catalog 全部接入；回归 tests/test_catalog_cold_start_runtime_state.py（4 用例，含"存量缺行章归档不崩"）。
- [x] P-16 admin token 改 hmac.compare_digest；P-18 物化场景 id 强制系统格式化（忽略 LLM 提供值）；P-20 injection.py 预算单位澄清注释；P-17 `_extract_scene_text` 错误消息去 stage 误导。
- [x] P-14 orchestrator/bundle_builder 入口补 scene/chapter 404 守卫。

## 第二批（契约对齐）
- [x] P-3 两端 client.js 幂等键改"操作意图"级（方法+路径+载荷签名持键：在途/可重试失败复用，成功/确定性失败释放；上限 200 条防涨）。React apiPost/apiAdminPost/apiDelete + Vue apiPost/apiPostForm/apiDelete。
- [x] P-8 幂等租约 TTL 改读 job_runtime.idempotency_claim_ttl_seconds（死配置激活），models.yaml 90→600s 并注释依据；代码注明"不做中途续租"的原因（SQLite 单写者 + 失败整体回滚的原子性冲突）。
- [x] P-11 降级可观测：orchestrator 5 处 debug→warning；bundle_builder 12 个注入槽统一 `_slot_degraded()`（WARNING + 快照 `degraded_slots` 字段，hash 后追加不影响 bundle_snapshot_hash）；orchestration-signals 端点暴露 degraded_slots；qc_engine 风格闸门降级 WARNING。

## 第三批（数据治理）
- [x] P-2 trash.purge_project 级联补全（scene/chapter/双列/draft/project 五个维度 30+ 张表，含 AuthorDraftRevision/Proposal、LlmCall、NarrativeEvent/ForeshadowTracker/VolumeSummary/ReviewItem、Longform 卡与 scope 指导；保留 OperationLog——对齐 style_reference 保留 MetricEvent 的取舍）；回归 tests/test_trash_purge_completeness.py（24 表残留断言）。
- [x] P-9(索引) 迁移 20260702_0060_hot_path_indexes（14 个命名索引）+ ORM __table_args__ 同步；drift guard 通过；tests/test_generation_persistence.py 两处硬编码 head 版本号随迁移更新。
- [⏸] P-9(PRAGMA foreign_keys) **有意不开启**：按报告自身警示需先做存量库孤儿盘点迁移，且部分既有测试/运行链路按松序建行；级联完整性已由 P-2 承担。留作后续项。
- [x] P-10 models.yaml 补 6 节点缺省路由（参数对齐 node registry 规格；stylize 别名保留）；验证 active-but-unrouted=NONE；tests/test_system_config.py 一处断言随新行为更新（missing_active_routes 应为空）。
- [x] P-15 llm_calls 审计载荷有界截断（AUDIT_TEXT_CAP=4000/段，messages+source_draft_content+structured_output；全文权威在 SceneDraft/FinalScene，prompt_hash 留痕）；llm_call_audit 聚合改只取标量列。

## 随行小项
- [x] P-12 wr-doc-store 冲突覆盖前本地稿备份到 `wr-doc:<sid>:conflict-<ts>` 并在 alert 告知。
- [x] P-19 wsMigrateLegacy 有失败不落已迁移标记（下次重试）；remove() 最后一部作品给 alert 提示。

## 验证
- 定向测试：orchestrator_flow/generation_persistence/scene_generation(24)、catalog 三件套(13)、efficacy 新测(4)、cold-start 新测(4)、purge 新测+trash_v2(6)、idempotency(4)、system_config(30+36)、metadata_isolation drift guard(4)、review_cards/release+run_guards+snowflake_workspace_v2(52) —— 全绿。
- 端到端：审查时崩溃的"目录冷启动→run"复现脚本重跑，ChapterState 正常建行（run 停在离线 QC 整改属预期）。
- 全量回归（-m "not chroma_integration"）：**1311 passed / 4 skipped / 0 failed**（32m25s，退出码 0）——修复前基线 1302 passed，新增 12 用例中 9 个计入本范围（3 个按用例聚合），零回归。
- 前端 vitest/build：本机 Node 16 无法运行（工程要求 22）——已按行为影响面人工核对 store 测试断言（wr-doc-store 冲突测试仅断言 alert 调用与 ensure 次数，兼容）；需 CI 验证。

## 未修项（报告中留作演进/待确认）
- P-13（get_settings 副作用/缓存）：测试隔离依赖 per-test env 重置，缓存有脏读风险，收益低——维持现状。
- 报告 §8 六项产品意图待确认（事件日志可靠性等级、审计载荷保留策略已按"有界截断+保留"落地、purge 保留 OperationLog 的取舍已按报告建议默认执行——如需连审计一并清除请指示）。
- 4.3/4.5 重复代码提炼、注入槽 provider 化：结构性重构，未在本轮范围。

## 阶段 0 记录

- 技术栈：后端 Python 3.12 + FastAPI + SQLAlchemy 2 + Alembic + ChromaDB（可选 memory 后端）；前端主线 React 18 + Vite（frontend-react/，window 全局 store）；遗留前端 Vue 3 + Pinia（frontend/）；配置 YAML（config/）。
- 规模：后端 src 208 个 py / 约 7.2 万行；services/ 约 4.9 万行；routes/ 31 个文件约 7000 行；models.py 2091 行；migrations 136 个；backend tests 153 个文件；frontend-react 64 个 js/jsx；frontend(Vue) 139 个文件。
- 环境：本机 Linux（CentOS 7 内核）、python3=3.12.7、backend/.venv 可用（缺 chromadb → chroma_integration 测试无法本地跑，按 CI 同款 `-m "not chroma_integration"` 跑基线）；Node v16.20.2（CI 要求 22 → 前端 build 可能不可跑，vitest 待验证）。
- 测试基线：pytest 收集 1306/1323（17 个 chroma 被 deselect）。完整运行结果 → scratchpad/pytest-baseline.txt（后台运行中）。
- 变更热点（git log 6 个月）：db/models.py(45)、frontend/lib/api.js(43)、api/app.py(26)、prompts.yaml(26)、routes/scenes.py(23)、models.yaml(21)、scene_generation.py(16)、qc_engine.py(16)、orchestrator.py(15)、bundle_builder.py(15)。
- 最近提交全是 QA 修复潮（pass2~pass5 红线 QA），说明系统刚经历密集 bug 修复期。

## 模块清单与审查优先级（P0 最高）

### 后端 services/（按业务关键度×复杂度×改动频率）
| 优先级 | 模块 | 行数 | 状态 |
|---|---|---|---|
| P0 | snowflake_workspace.py + snowflake_steps.py + snowflake_planner.py | 2146+1368+983 | 待审 |
| P0 | orchestrator.py + scene_execution.py + bundle_builder.py | 992+711+954 | 待审 |
| P0 | scene_generation.py + qc_engine.py + scene_quality.py | 1362+1884+783 | 待审 |
| P0 | llm_client.py + llm_task_runner.py + llm_providers/ | 777+504+1609 | 待审 |
| P0 | db/models.py + db/session.py | 2091+? | 待审 |
| P0 | api/app.py + api/response.py + 中间件 | ~? | 待审 |
| P1 | projects.py + author_lifecycle.py + chapter_runner.py | 1439+583+572 | 待审 |
| P1 | style_reference/（16 文件 7736 行） | 7736 | 待审 |
| P1 | system_config.py（含加密快照） | 1885 | 待审 |
| P1 | idempotency.py + hash_engine.py | 543+? | 待审 |
| P1 | versioning/（1272 行） | 1272 | 待审 |
| P1 | literary_quality.py + self_repetition.py + auto_critique.py + best_of_n_blind_eval.py | 2323+779+380+340 | 待审 |
| P1 | author_drafts.py | 2381 | 待审 |
| P2 | narrative_event_log.py + prose_event_extractor.py + causal_chain_validator.py + foreshadow_lifecycle.py | ~2500 | 待审 |
| P2 | writer_review.py + writer_deep_review.py + near_final.py | 1595+1481+1166 | 待审 |
| P2 | knowledge_catalog.py + library.py + catalog.py + trash | ~2400 | 待审 |
| P2 | longform_tower.py + longform_control.py + longform_editor.py | 867+808+542 | 待审 |
| P2 | vector_store.py + indexing + source_safety.py + reference_safety.py | ? | 待审 |
| P3 | 其余小服务（theme_anchor、character_*、tension_curve、voice_fingerprint 等） | ~ | 轻量扫描 |

### API routes/（31 文件）
- 待审：与对应 service 一起看。重点 scenes.py、snowflake_workspace.py、system_config.py、review.py、style_reference.py。

### 前端
| 优先级 | 模块 | 状态 |
|---|---|---|
| P0 | frontend-react/src 全局 store（ws-works/ws-catalog/ws-review/lf7-bridge/wr-doc-store）+ lib/client.js | 待审 |
| P1 | frontend-react 视图层（ws-app.jsx 等） | 待审 |
| P2 | frontend/（Vue 遗留，仅轻量扫描——理由：已标记 legacy、默认不启动） | 待审 |

### 其他
- config/*.yaml（models/prompts/allowlists/hash_contract/style_reference/）：与消费方一起审。
- alembic migrations：抽样审 + 与 schema-drift guard 对照。
- scripts/（dev.ps1 等）：轻量扫描。
- docs/：作为意图参照。

## 阶段 1-3 发现暂存区

### 已审模块（深审）
app.py/session.py/settings.py/response.py ✅、models.py ✅、orchestrator.py ✅、scene_generation.py ✅、llm_task_runner.py ✅、llm_client.py ✅、bundle_builder.py ✅、qc_engine.py(HardQc 部分) ✅、snowflake_workspace.py(materialize/resync/结构) ✅、system_config.py(鉴权/加密/审计) ✅、idempotency.py ✅、style_reference/injection.py+cleanup.py ✅、projects.py(物化部分) ✅、routes/scenes.py(部分) ✅

### 发现列表（编号 F-x，严重程度草标）
- F-1【高】orchestrator.py:872 `StyleReferenceInjectionBinding.active == 1` — 模型无 `active` 列（只有 status），AttributeError 被 L883 裸 except 吞掉 → `_load_style_baseline` 恒 None，风格漂移基线永远取不到绑定 profile。
- F-2【高】bundle_builder.py:884-886 `sa_func.count(...).where(...)` — Function 无 .where()，恒 AttributeError 被吞 → §11 角色弧线权重注入永久静默失效（已用 venv 复现确认）。同函数 L880-882 `execute(count)` 无 project 过滤（跨项目算进度，修复后仍是 bug）。
- F-3【高】bundle_builder.py:600 `_narrative_state_digest` 只用 `chapter_id.rsplit("_",1)[0]` 推导 project_id、不先用 scene.project_id；catalog.py:212/365 造的章 id 为 `{project}_CH_{hex}` → rsplit 得 `{project}_CH` → 事件日志权威状态注入查错 project → 静默缺失。写侧 `_record_narrative_events`（orchestrator.py:558-559）用 scene.project_id 优先——读写不对称。
- F-4【中】session.py 未开 `PRAGMA foreign_keys` → 所有 FK 仅文档性（模型注释也承认）；孤儿风险靠手工级联（cleanup.py 做了，其他删除路径未必）。
- F-5【中】幂等租约：settings.idempotency_ttl_seconds 硬编码 90s（无 env）、models.yaml job_runtime.idempotency_claim_ttl_seconds/heartbeat_interval_seconds 无消费方；action 执行期间不续心跳 → >90s 的场景 run 重试会并发二次执行。
- F-6【中】高频表缺索引：scene_drafts(scene_id)、final_scenes(scene_id/chapter_id)、qc_reports(scene_id)、llm_calls(scene_id/created_at)、attempt_tracker(scene_id)、scene_bundles(scene_id)、human_review_events(scene_id/status)、review_items(scene_id/chapter_id/status)…（SQLite 不自动给 FK 建索引，多数还没 FK）。
- F-7【中】llm_calls.request_payload_summary 存完整 messages+source_draft_content 全文；response 存完整 structured_output → 全量审计无裁剪无清理策略，长篇跑几百场景后 DB 膨胀+慢查询。
- F-8【低】orchestrator 等 78 处 `except Exception`，约 20 处直接吞（多为"永不阻断"设计意图，但日志级别 DEBUG，运维不可见；auto_critique 里连补丁生成失败也吞成 debug）。
- F-9【低】require_admin_token 用 `==` 比较（非常数时间）；无 token 时回退 loopback 判定 `request.client.host`（反向代理后失效）。仅本地单机可接受。
- F-10【低】orchestrator._index_scene_to_vector_store / bundle_builder._similar_scene_context 硬编码 InMemoryVectorStore（无视 NOVEL_SYSTEM_VECTOR_BACKEND；需确认 InMemoryVectorStore 是否文件持久化 → 待查 vector_store.py）。
- F-11【低】scene_generation._extract_scene_text 报错信息硬编码 "neutral_draft response missing scene_text"（风格/补丁路径也用它，误导排障）。
- F-12【低】settings.get_settings 每次调用 vector_store_dir.mkdir（getter 带副作用）+ include_runtime_config=True 时每次查 DB（多层 get_settings 调用叠加）。
- F-13【低】llm_client 每次 generate 新建 httpx.Client（无连接复用）；retry time.sleep 阻塞线程池 worker（单机可接受）。
- F-14【中】system_config.llm_call_audit 一次加载 ≤5000 行 LlmCall 全 JSON 载荷只为聚合计数（配合 F-7 会非常慢）。
- F-15【低】settings.py CORS 默认 cors_allow_credentials=True + 固定本地 origin 列表（可接受，但 * 配置时禁 credentials 的保护是对的）。

### 待确认问题暂存区
- Q-1 blueprint §2 声称事件日志是"single source of truth"，但 orchestrator._record_narrative_events 失败仅 debug 日志吞掉——"事件日志可缺失"是否可接受设计？
- Q-2 llm_calls 全量提示词落库是审计需求还是临时调试？（决定 F-7 的处置）
- Q-3 ChapterGoal.chapter_id 全局主键依赖 id 前缀约定防碰撞（{project_id}_CH…），是否存在导入/interop 路径可注入任意 chapter_id？
- Q-4 idempotency 租约 90s 与前端重试策略的契约（FE 是否保证 409 时不换 key 重发？）

### 追加发现（已验证）
- F-16【高】frontend-react/src/lib/client.js:80-82 与 frontend/src/lib/api/client.js:89-91 `buildIdempotencyKey` 每次调用生成 `path+Date.now()+random` 新键 → 后端幂等去重/重放/在途 409 机制被前端整体绕过（双击/重试=两个不同键=两次执行）。
- F-17【严重】archiver.py:32+68（连带 aggregator.py:121-122）对 `session.get(ChapterState,…)` 结果无 None 守卫；catalog.create_chapter（目录冷启动链路）不建 ChapterState → 场景 run 通过全部 QC 后在归档步 AttributeError→500→整跑回滚（已用文件库+离线模式复现：`'NoneType' object has no attribute 'chapter_passed_scene_count'`）。与 orchestrator 补 SceneRunState 的修复是同族缺口。
- F-18【高】trash.py purge_project"永久清除"漏删：SceneDraft/FinalScene/SceneMemory/ChapterMemory/ChapterRollingNote/SceneBundle/SceneBlueprint/Scene*Contract/QcReport/WriterEvaluation/AttemptTracker/LlmCall/HumanReviewEvent/AuthorDraftRevision（有 draft_id 却只删了 Event+Draft）/NarrativeEvent/ForeshadowTracker/VolumeSummary/ReviewItem（后四者甚至有 project_id 列）→ 正文全文残留 + 永久孤儿。
- F-19【高】orchestrator.py:757-765 `_index_scene_to_vector_store` new 裸 InMemoryVectorStore（纯实例字典，函数返回即丢）→ §3 Track3 场景索引完全 no-op；正确工厂 get_vector_store() 存在但被绕过（bundle_builder.py:785 同样绕过，但因每次重建+同实例查询而"恰好可用"，且从不用 Chroma；相似度=字符集交集，非语义）。
- F-20【中】llm_enabled=true 时 6 个活跃节点无文件路由（style_draft/style_patch/project_outline_plan/writer_deep_review/style_profile_extract/literary_eval_live）——task_config 故意不回退 stylize 别名 → 首次启用 LLM 必须先去系统配置 sync-missing，否则核心风格化节点全部 LLM_ROUTE_NOT_CONFIGURED（有 recommended_action 引导，属首跑陷阱）。
- F-21【中】wr-doc-store.jsx:122-128 AUTHOR_DRAFT_CONFLICT 处理：直接放弃本地未保存修改、以服务端为准重水合（仅 alert 告知）→ 本地新内容丢失，未留副本。
- 【低】ws-works.jsx:192 wsMigrateLegacy 部分失败也标记已迁移（失败作品永不重试）。
- 【低】wr-doc-store htmlToParas/innerHTML 注入面（单机自有内容，低危）。
- 【正面样例】idempotency.py 失败先回滚再落标记；style_reference/cleanup.py 级联+RAG 索引清理；qc_engine 确定性闸门叠加 LLM 裁决+熔断；hash_engine/BundleSnapshotHashProjection 快照哈希契约；conftest per-test 隔离库+schema drift guard；client.js 信封+错误归一化。

### 覆盖情况
- 深审：见"已审模块"+ vector_store、archiver、aggregator、trash(purge)、versioning/promotion(release_review 头部)、literary_quality(权重解析)、wr-doc-store、ws-works、client.js×2。
- 轻扫（结构+关键函数抽查）：writer_review/writer_deep_review/near_final、knowledge_catalog、longform_tower/control/editor、narrative 服务群（causal/tension/foreshadow/character_*）、library/catalog(建章路径深看)、interop、indexing、author_drafts(冲突契约确认)、Vue 前端(router/client 对照)、migrations(60 个，heads=0059 单头)。
- 测试基线：后台运行中（>10 CPU 分钟），完成后回填。
- 配置一致性：node registry 55 活跃节点 vs models.yaml 53 路由（差 6 见 F-20）；prompts.yaml 54 模板（异名映射正常）。

### 待办
- [x] 前端 / 轻扫 / 配置一致性 / 迁移抽查
- [ ] 测试基线结果回填
- [ ] 报告撰写 → docs/system-audit-report.md
