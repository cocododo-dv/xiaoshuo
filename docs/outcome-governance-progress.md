# 结果闭环治理 · 实施进度账本

> 设计：`docs/superpowers/specs/2026-07-10-ai-novel-outcome-governance-design.md`（v1.1）
>
> 纪律：Wave 严格顺序推进；前一 Wave 完成门未过不得开始后一 Wave；每 Wave 独立提交。

## Wave 0：建立真实结果门禁 —— 已完成（2026-07-10）

实施计划：`docs/superpowers/specs/2026-07-10-wave0-implementation-plan.md`

### 交付内容

1. **结果门禁判定器**（单一权威实现，Python，pytest 全覆盖）：
   `scripts/playwright_audit_summary.py` 新增 `evaluate_outcome_gate()` + `--outcome-gate` CLI
   （`--expected-chapters` 默认 5、`--scenes-per-chapter` 默认 3、`--gate-output` 输出判定 markdown），
   退出码 0/1。六类失败：`LEGACY_REPORT_NO_OUTCOME` / `SCENE_COVERAGE_SHORTFALL` /
   `SCENE_WITHOUT_ARCHIVED_FINAL` / `OUTCOME_RECORD_INCOMPLETE` / `EMPTY_CHAPTER_FAKE_SCORE` /
   `NORTHSTAR_PHASE_NOT_UI`。既有产物摘要模式不变。
2. **测试先行**：`backend/tests/test_playwright_audit_summary.py` 新增 10 项门禁测试
   （先红后绿），含完成门测试 `test_outcome_gate_fails_legacy_no_draft_but_green_report`
   （按仓库真实旧"无稿但通过"样本形状构造，新门禁判失败）与可证伪性测试
   `test_outcome_gate_passes_complete_five_chapter_run`（完整五章样本必须能通过）。
3. **currentdb harness**（`scripts/run-currentdb-three-chapter-qa.cjs`）：
   - `buildChapters()` 扩为 **5 章 × 每章 3 场**（玻璃雨故事第 1–3 章拆为 3 场/章，
     第 4–5 章新增原创内容：钟影溯源/身份构陷/顾磬交易/零点源头/收束）；
   - `QA_CHAPTER_COUNT` / `QA_SCENES_PER_CHAPTER` 参数化（默认 5/3）；
   - `finalScenes` 按 scene_id 键控，逐场记录耗时/重试/token（可得时）/阻断原因/来源安全；
   - `evaluateChapterScores` 无稿守卫：无归档正文章节只输出 `no_draft: true`，
     不再产生"空章节 originality 9 / sourceLeakRisk 10"的伪评分；
   - 收尾调用 Python 门禁并透传退出码；报告头部为"结果门禁（唯一权威判定）"，
     步骤表降级为诊断证据。
4. **longzu harness**（`scripts/run-longzu-full-cloud-qa.cjs`）：同款机械改造
   （scenes 数组、逐场记录并继续而非首败即抛、outcome 节 + 门禁调用 + 退出码、
   报告头部门禁块）；计划保持 3 章 × 1 场（参考安全 lane），门禁期望取自自身计划。
5. **共享模块**：`scripts/lib/qa-outcome-gate.cjs`（outcome-gate-v1 结构组装 + 判定器调用，
   两 harness 共用，防结构发散）；`scripts/lib/longzu-literary-scoring.cjs` 的
   `buildChapterScores` 加无稿守卫并支持 scenes 数组。
6. **文档**：`docs/QA-五轮工作流-提示词.md` A4.2 更新（五章默认、门禁语义、预期红灯声明、
   新产物清单）；原"北极星硬缺口：硬编码三章"段落改写为已落地说明。

### 完成门验证（本机 CentOS 7）

```bash
cd backend && .venv/bin/python -m pytest tests/test_playwright_audit_summary.py -v   # 12 passed（10 新 + 2 旧）
node --check scripts/run-currentdb-three-chapter-qa.cjs                              # 语法通过
node --check scripts/run-longzu-full-cloud-qa.cjs                                    # 语法通过
```

完成门"旧的'无稿但通过'样本必须被新 harness 判为失败"由
`test_outcome_gate_fails_legacy_no_draft_but_green_report` 可复算证明：
旧报告形状（步骤全 ok、三场 `human_review_required`、finalRowId 全空、空章节仍拿 originality 9）
→ 门禁判 `LEGACY_REPORT_NO_OUTCOME` 失败，CLI 退出码 1。

### 阶段性红灯声明

候选终选 UI 到 Wave 3 才交付；五章基准在 Wave 1–3 完成前对真实运行**预期整体红灯**
（`NORTHSTAR_PHASE_NOT_UI` + 场景无归档正文），红灯即本 Wave 交付物。
该 lane 只进发布门（设计 §9.3），不进 PR CI。

### 剩余风险

- 两个 .cjs 无法在本机端到端实跑（node v16 无原生 fetch、无 Windows 服务栈、无真实 LLM）；
  harness 采集侧的运行期行为需在 Windows 开发机下一次实跑复核（R0 工装信任门）。
  判定侧逻辑已由 pytest 全覆盖。
- 每场 token 依赖 workbench 响应的 `generation_summary`/job `result_summary` 字段，
  取不到时记 `null`（门禁只校验键存在）；Wave 6 成本聚合落地后应改为从 `LlmCall` 聚合取数。
- 第 4–5 章 15 场原创规划数据是计划输入，其可执行性（bundle 预检、知识卡齐备度）
  由下一次真实运行检验；已为新角色顾磬补 voice 卡候选。
- longzu lane 的五章扩展与"授权/公版参考文本"替换遗留至 §9.3 发布门 2 重整。

## Wave 1：统一正文真值和归档 —— 已完成（2026-07-11）

实施计划：`docs/superpowers/specs/2026-07-11-wave1-implementation-plan.md`

### 交付内容

1. **author_state 投影服务**（§5.3，测试先行）：`services/author_state.py` 新增
   `compute_author_state()`——判定先分「有稿性」，无稿走空稿三态
   （`not_started` / `generating` / `generation_failed`+`recovery_action`），
   有稿走 `draft_ready` / `quality_warning` / `awaiting_author_choice` /
   `hard_blocked` / `archived`；返回 §5.3 全部契约字段（can_edit / can_archive /
   latest_valid_draft_row_id / blocking_findings / …）。挂载到
   `GET /scenes/{id}/status`、`GET /scenes/{id}/workbench`、`GET /scene-run-states`。
   G-01 核心回归：`human_review_required` 且库里无稿 → `generation_failed`，
   不得再伪装成「有稿待审」。
2. **最近有效正文指针**（§4.3）：`SceneRunState.latest_valid_draft_row_id` 新列
   （迁移 `20260711_0061`，带存在性守卫；漂移守卫通过）。维护点：
   `scene_generation.py` 全部 5 个草稿写点 + 候选 select + adopt 归档；
   失败/重写路径**不清空**（区别于 current_*），仅项目级运行时失效重置。
3. **归档单入口 + 状态词表统一**（§5.2）：`Archiver.archive_final_scene` 事务内
   统一置 `FinalScene.status="archived"`；4 处消费方
   （bundle_builder ×3、style_drift_detector）词表同步扩展；迁移把历史
   被 archived 运行态指向的行映射为 `archived`。新端点
   `POST /api/v1/scenes/{scene_id}/adopt-current`（幂等）：作者采纳归档，
   内容源 = 未归档 FinalScene > 管线草稿 > author-draft 人工稿兜底；
   无稿 409 `NO_VALID_DRAFT`；来源安全命中 409 `SOURCE_SAFETY_BLOCKED`
   （草稿保留，红线 8）。
4. **React 归档先后端**：`ws-scene-run.jsx` `scnAdoptToDoc` 改 async——先 POST
   adopt-current 成功才写缓存/置 done/重拉服务端状态；后端拒绝时不动本地任何
   状态。`ws-scene.jsx` 调用点同步改 await。
5. **成稿中心换源**：新 store `ws-manuscripts-store.jsx`（`WsManuStore`，
   API-backed 同步缓存），`ws-manuscripts.jsx` 的正文/结构/导出全部改从后端
   章节聚合取（detail 的 `scenes[].final_scene` 新带 `content` 全文），
   localStorage `wr-doc:*` 不再作为成稿正文来源；tide 演示种子回落保留。
6. **wr-doc 跨会话冲突**（设计项 5）：保存失败写持久化 `wr-doc-pending:{sid}`
   标记；重启后水合发现标记且本地≠服务端 → 本地稿备份冲突副本 + alert 让作者
   选择（不再静默覆盖）；保存成功/409 路径消费标记。

### 完成门验证（本机 CentOS 7）

```bash
cd backend && .venv/bin/python -m pytest tests/test_author_state_projection.py tests/test_scene_adopt_archive.py -q   # 26 passed（16+10，先红后绿）
cd backend && .venv/bin/python -m pytest tests/test_metadata_isolation.py -q    # 4 passed（漂移守卫）
cd backend && .venv/bin/python -m pytest -q -m "not chroma_integration"         # 全量回归
cd frontend-react && NODE_OPTIONS="--require ./crypto-polyfill.cjs" npx vitest run   # 73 passed（12 文件）
cd frontend-react && NODE_OPTIONS="--require ./crypto-polyfill.cjs" npm run build    # 构建通过
# 迁移验证（隔离库）：alembic upgrade head → latest_valid_draft_row_id 列存在
```

完成门「前端显示完成的场景必须存在可回放的后端归档稿」由
`test_adopt_promotes_style_draft_to_archived_final`（归档后 workbench /
chapter-manuscripts 可回放全文）+ vitest「done 只由 adopt 成功响应映射、
后端拒绝不置 done」可复算证明；「缓存清除不丢稿」由 vitest
「清空 localStorage 后正文仍完整来自 API」+「重启会话 pending 冲突副本」证明。

### 剩余风险

- Playwright 级「清缓存重启恢复」E2E 本机无法实跑（node16 无 fetch /
  无 Windows 服务栈），vitest 模拟为本 Wave 可复算证明；smoke 级验证与
  Wave 0 采集侧复核同批（Windows lane）。
- `ws-manuscripts.jsx` 换源后的视觉回归（阅读器/结构/导出）需 Windows lane
  实跑复核；store/取数层已有 vitest 覆盖。
- author-draft 人工编辑不维护 `latest_valid_draft_row_id`（两个 id 体系，
  计划 D5 边界）；人工稿归档经 adopt 的 author-draft 兜底路径覆盖。
- adopt 端点 Wave 1 只做确定性来源安全 Q0 守卫；Q0–Q3 分级阻断策略归 Wave 2。

## Wave 2：QC 分级和可靠成稿模式 —— 未开始（待 Wave 1 完成门确认）

## Wave 3–7 —— 未开始
