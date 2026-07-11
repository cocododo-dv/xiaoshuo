# Wave 0 实施计划：建立真实结果门禁

> 日期：2026-07-10
>
> 所属设计：`2026-07-10-ai-novel-outcome-governance-design.md`（v1.1）§8 Wave 0
>
> 完成门：旧的"无稿但通过"样本必须被新 harness 判为失败
>
> 纪律：测试先行；不修改与本 Wave 无关的代码；不新增文学模块；独立提交

## 1. 现状事实（实施前逐行核实）

| 事实 | 位置 | 含义 |
|---|---|---|
| `human_review_required` 被列入终态集合，场景阻塞不抛错 | `run-currentdb-three-chapter-qa.cjs:34`（terminalJobStatuses）、`exerciseSceneWorkbench`（阻塞仅 push blocker 后 break） | fatal 步骤永不因"无稿"而失败 |
| 退出码只在 fatal 步骤抛错时非零 | `main().catch` → `process.exitCode = 1`（行 1886） | 三场全阻塞时退出码仍为 0 —— G-01 的机制根源 |
| 空正文得到正常评分 | `evaluateChapterScores`：`scoreByTokens("")` 保底 4 分；空文本扫不出保护词 → `originality: 9`、`sourceLeakRisk: 10` | 空章节拿"满分安全"，正是实施项 4 要禁止的 |
| 报告以步骤表为判定门面 | `buildReport` 行 1562：`item.ok ? "通过" : "阻塞"` | "步骤完成即通过"的呈现层 |
| 章节/场景为 3×1 硬编码 | `buildChapters` 返回 3 章、每章单 `scene` 对象；`planned_scene_count: 1` 硬编码于 `createOriginalWorkspace` | 参数化改造面：`.scene` 消费点约 10 处 |
| 每场结果数据已可采集 | `collectSceneOutput`（workbench API）：sceneStatus/finalRowId/finalText/hardQc/attempts/source_safety_scan/generationSummary | 实施项 7 的数据来源基本齐备 |
| `run-longzu-full-cloud-qa.cjs` 同骨架同缺陷 | 3×1 硬编码（CHOR01..03）、同款 `evaluateChapterScores`、同款退出语义 | 需同步机械改造 |
| 本机 node 为 v16.20.2，harness 用原生 fetch（需 ≥18） | `node --version` | 两个 .cjs 只能在 Windows 开发机实跑；本机可验证面 = Python 门禁 pytest + `node --check` 语法 |
| `playwright_audit_summary.py` 是纯产物摘要器，已有 pytest 挂点 | `scripts/playwright_audit_summary.py` + `backend/tests/test_playwright_audit_summary.py`（2 项通过） | 结果门禁的宿主：Python 单一权威实现，本机可测 |

## 2. 架构决策

**单一权威判定器**：结果门禁逻辑只实现一份，放在 `scripts/playwright_audit_summary.py`（纯函数 + CLI），由 pytest 完整覆盖。两个 .cjs harness 只负责**采集**每场结果数据并在收尾时**调用**该判定器、传播退出码。判定器不可执行时按失败处理（门禁未执行不得视为通过，对应设计 §11 禁止性规则 2）。

**北极星六阶段以门禁准则形式落地**（实施项 5/6）：harness 为 `snowflake_planning / materialization / scene_execution / candidate_selection / archive / chapter_aggregation` 六阶段如实记录通道（`ui` / `api` / `missing`）。门禁要求全部为 `ui` 才算北极星通过；当前诚实值为 api/missing → 正确红灯。API 深链保留为诊断通道，报告中显式标注，不冒充 UI 北极星。这样实施项 5 在 Wave 0 就"作为会正确失败的验收准则"存在，Wave 1–3 落地后逐项翻绿，不需要在 Wave 0 伪造尚不存在的 UI 流程。

**判定输入契约** `outcome-gate-v1`（写入 `qa-live-results.json` 的 `outcome` 节 + 独立 `outcome-gate.json`）：

```json
{
  "schema": "outcome-gate-v1",
  "expected": {"chapters": 5, "scenes_per_chapter": 3},
  "planned_scenes": [{"chapter_id": "...", "scene_id": "..."}],
  "scenes": {"<scene_id>": {
    "chapter_id": "...", "final_row_id": "str|null", "final_chars": 0,
    "archived": false, "scene_status": "...", "tokens": "int|null",
    "duration_ms": 0, "attempts": 1, "block_reason": "str|null",
    "source_safety": "object|null"
  }},
  "northstar_phases": [{"phase": "...", "lane": "ui|api|missing", "evidence": "..."}]
}
```

**判定规则**（任一命中即整体失败，退出码 1）：

| 代码 | 条件 | 对应实施项 |
|---|---|---|
| `LEGACY_REPORT_NO_OUTCOME` | 报告缺少 `outcome` 节（旧版报告形状） | 完成门（旧样本必判失败） |
| `SCENE_COVERAGE_SHORTFALL` | 计划场景数 < 期望章数×每章场数，列出缺口 | 1 |
| `SCENE_WITHOUT_ARCHIVED_FINAL` | 任一计划场景 final_row_id 为空 / final_chars=0 / archived≠true，逐场列出 | 2、3 |
| `OUTCOME_RECORD_INCOMPLETE` | 任一场景记录缺必备键（tokens/duration_ms/attempts/block_reason/source_safety/…） | 7 |
| `EMPTY_CHAPTER_FAKE_SCORE` | chapterScores 对无归档正文的章节给出数值文学分或"安全"结论 | 4 |
| `NORTHSTAR_PHASE_NOT_UI` | 六阶段任一缺失或通道非 `ui` | 5、6 |

**红灯即交付物**：候选终选 UI 到 Wave 3 才存在，五章基准在 Wave 1–3 完成前预期整体红灯。本 lane 只进发布门（设计 §9.3），不进 PR CI。

## 3. 改动清单（仅限本 Wave 文件）

1. `scripts/playwright_audit_summary.py`：新增 `evaluate_outcome_gate()` 纯函数族 + `--outcome-gate` CLI 模式（`--expected-chapters`、`--scenes-per-chapter`、`--gate-output`），退出码 0/1；既有产物摘要模式完全不变。
2. `backend/tests/test_playwright_audit_summary.py`：先行新增 9 个门禁测试（含"旧无稿绿灯样本必判失败"的完成门测试、"完整五章样本必须能通过"的可证伪性测试）；既有 2 项保持通过。
3. `scripts/run-currentdb-three-chapter-qa.cjs`：
   - `buildChapters` 重写为 5 章 × 每章 3 场（第 1–3 章沿用玻璃雨故事拆分为 3 场，第 4–5 章新增原创内容：第二枚钟影溯源、零点广播源头收束）；`chapter.scene` → `chapter.scenes[]`，场景级 writer brief 移入各场景；
   - `QA_CHAPTER_COUNT`（默认 5）/ `QA_SCENES_PER_CHAPTER`（默认 3）参数化，诊断用途可裁剪；
   - `finalScenes` 改按 scene_id 键控；`exerciseSceneWorkbench` 按章×场迭代，记录每场耗时/重试/阻断/тoken（generationSummary 可得时）；
   - `evaluateChapterScores` 加无稿守卫：章内任一场无归档非空正文 → 该章 `no_draft: true`，不产生文学分与安全结论；
   - 新增 `outcome` 节构建 + 六阶段通道记录 + 收尾调用 Python 门禁并传播退出码；
   - 报告头部改为"结果门禁（权威判定）"块，步骤表降级为诊断证据。
4. `scripts/run-longzu-full-cloud-qa.cjs`：同款机械改造（scenes 数组结构、无稿守卫、outcome 节、门禁调用）；其计划保持既有 3 章内容（该 lane 是参考安全通道，五章内容扩展与 §9.3 门 2 的"授权/公版参考文本"重整一并另行处理，记入进度账本）。门禁期望值取自其自身计划。
5. `docs/QA-五轮工作流-提示词.md`：A4.2 harness 说明更新（五章默认、结果门禁为权威判定、预期红灯声明、退出码语义、新增产物 outcome-gate.json / outcome-gate-verdict.md）。
6. `docs/outcome-governance-progress.md`：新建进度账本，记录 Wave 0 证据与遗留项。

## 4. 测试先行顺序

1. 写 9 个门禁测试 → 运行 → **必须红**（函数不存在）。
2. 实现 `evaluate_outcome_gate` + CLI → 运行 → **必须绿**，且既有 2 项不回归。
3. 改造两个 .cjs → `node --check` 语法验证（本机 node 16 无法实跑 fetch）。
4. 文档与账本 → 全文件 pytest 复跑。

## 5. 本机验证命令

```bash
cd backend && .venv/bin/python -m pytest tests/test_playwright_audit_summary.py -v
node --check scripts/run-currentdb-three-chapter-qa.cjs
node --check scripts/run-longzu-full-cloud-qa.cjs
```

## 6. 完成门自证方式

pytest 用例 `test_outcome_gate_fails_legacy_no_draft_but_green_report` 按仓库真实旧样本形状构造报告（步骤全 ok、三场 `human_review_required`、finalRowId 全空、空章节 originality 9），断言门禁判失败——这正是设计完成门"旧的'无稿但通过'样本必须被新 harness 判为失败"的可复算证据。同时 `test_outcome_gate_passes_complete_five_chapter_run` 证明门禁可通过（可证伪性，防止造一个永远失败的假门）。

## 7. 已知边界与剩余风险（提交时复述）

- 两个 .cjs 无法在本机端到端实跑（node 16 无 fetch、无 Windows 服务栈、无真实 LLM）；harness 采集侧的运行期验证依赖 Windows 开发机下一次实跑。判定侧逻辑已由 pytest 全覆盖。
- 五章基准在 Wave 1–3 完成前预期红灯（设计如此），不得为转绿而放宽判定。
- 第 4–5 章新增的 15 场原创规划内容是"计划数据"，其文学质量由后续真实运行检验，不属于本 Wave 验收面。
- longzu lane 的五章扩展与"授权/公版参考文本"替换遗留至 §9.3 门 2 重整。
