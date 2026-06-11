# 任务：FE 主线对齐 — 以「潮汐工作台」原型为正式前端，改造 codex 后端

> 给 Claude Code 的**主简报（总览）**。按符号定位，不要依赖行号。
> 具体改动步骤拆在 `phases/00..08` 各自的简报里——**一个 Phase 一个会话、一次提交、单独跑测试**。
> 开工前先读完：本文件 → `契约附录-store缝合面.md` → `契约附录-B-后端端点清单.md` → `phases/00-基线与陷阱.md`（含对本表三处事实修正），再进入当前 Phase。
> 进度记账在 `PROGRESS.md`（每完成一步勾一项并写提交号）。
> 标 ⚖️ 的是需要人拍板的决策点，已给默认方案，不反对即按默认执行。

---

## 0. 背景：两套东西分别是什么

**设计真相源（`design/` 目录）**：高保真可交互原型「创作工作台 · 潮汐档案」，React 18 + Babel standalone，入口 `design/index.html`，所有状态在 localStorage。它**不是参考图，而是将被直接工程化的实现基础**（视觉与交互像素级保留）。

- **信息架构**（`design/ws-app.jsx` 的 `WS_NAV_GROUPS`）：
  - 日常写作：主页 / 流程 / 构思（雪花）/ 写作 / 风格 / 待办 / 资料
  - 高级模式追加：章节编排 / AI 起草台 / 成稿中心 / 长篇控制塔 / 发布索引 / 导入导出
  - 系统：设置 / 回收站；外加多作品切换器、⌘K 面板、作家/高级双模式、三主题
- **数据收敛层（= 移植缝合面，完整签名见《契约附录-store缝合面.md》）**：
  `WsWorks`（作品）· `WsCatalog`（章节/场景目录）· `WsTrashStore`（回收站）·
  待办 store（`rvPush` / `rvDerived` 等）· `Lf7Bridge`（控制塔联动桥）

**目标代码库（codex 仓库）**：FastAPI 后端（`backend/src/novel_system/`）+ 现存 Vue 3 前端（`frontend/`）。响应一律 `{ok, data, error, request_id}` 信封（`api/response.py`），幂等 `X-Idempotency-Key`，审计 `X-Operator-Ref`，迁移用 alembic，分页用 `services/pagination.py`。

**本任务**：以原型为产品形态的最终答案。后端缺的补齐，冲突的**向更好的方向**收敛（每处冲突下表已裁决）。

---

## ⚖️ 决策点汇总（不反对即按默认执行）

| # | 决策 | 默认方案 |
|---|---|---|
| D1 | 前端栈 | React 原型工程化为 `frontend-react/`；Vue 前端并行保留，稳定一个写作周期后再退役 |
| D2 | 今日字数 / streak | 服务端计算；时区默认 Asia/Shanghai |
| D3 | 回收站清理 | 仅手动永久删除；30 天自动清理留待后续 |
| D4 | 待办卡 effect | 后端事务执行（前端不再自己改数据） |
| D5 | 资料库派生 | 半自动：LLM 提取 → idea 卡进待办 → 人工确认入库 |
| D6 | 新端点版本号 | 一律 `/api/v2/projects/{id}/…` 风格（与 snowflake-workspace、library、longform 一致）；不动既有 v1 |

---

## 1. 总体原则（所有 Phase 共同遵守）

1. **后端是唯一真相源**。localStorage 只许存 UI 偏好（主题/动效/版式）。原型的 `wsKey()` per-work 命名空间 ≙ 后端**一切业务 API 按 `project_id` 隔离**。
2. **只动 store 层，不动视图层**。五个 store 对视图的方法签名/订阅语义保持不变（契约见附录），内部改为：乐观更新 + API + 失败回滚。视图文件原则上零修改。
3. 移植 Vue 端 `frontend/src/lib/api/client.js` 的信封/幂等/operator-ref/`novel-system-api-base` 逻辑为 `frontend-react/src/lib/client.js`，两端共享同一契约。
4. 后端改动走既有套路：路由进 `api/routes/`、服务进 `services/`、模型进 `db/models.py`、每个端点配单测（仿 `backend/tests/` 风格，conftest 隔离 DB）。
5. **先核对再动手**：每个 Phase 简报里的「后端现状」一节列了已核实的端点/符号；如与实际代码不符，以实际代码为准并把差异记进 PROGRESS.md。
6. 原型种子作品（潮汐档案/盐镇来信）迁为后端 demo seed（沿用 `.codex-run/skip-demo-seed` 开关）；接通真实 API 的视图删除其 `WsDemoTag` 标签，接不通的保留——**诚实标识不许提前摘**。

---

## 2. 概念对照表（前端概念 → 后端现状【已核实】→ 裁决）

| # | 原型概念 | 后端现状（核实过的符号） | 裁决 | Phase |
|---|---|---|---|---|
| C1 | 作品 Work（title/genre/mark/accent/sub/wordsTarget/今日目标/streak） | **`GET/POST /api/v2/projects` 已存在**（`snowflake_workspace.py`）；`StoryProject`；profile 字段不全 | 在 v2 上补字段 | P2 |
| C2 | 主页聚合（续写卡/GOS/雪花进度/近章） | **`GET /api/v1/projects/{id}/dashboard` 已存在** | 对比载荷，缺什么扩什么，不要另起炉灶 | P2 |
| C3 | 目录 WsCatalog（章→场景树：GMC、戏剧卡、tension、threads、字数、entry/exit/promise） | `ChapterGoal`+`SceneCard`（`writer_brief_json` 已有 GCS/RDD）；`GET /api/v1/chapters`、`POST /api/v1/chapters/{id}/scene-order` | 后端为骨架、原型为血肉：扩 JSON 字段 + 目录读写 API | P3 |
| C4 | 场景三元组 goal/obstacle/turn（主动反应同一组） | 主动=Goal/Conflict/Setback；反应=Reaction/Dilemma/Decision | **以后端为准**（忠实 Ingermanson）；store 层做映射 | P3 |
| C5 | 回收站（场景/章节/整部作品，可整体恢复） | **章级与场景级都已存在**：`chapters/trash|restore|purge`、`scenes/trash|restore|purge`、`GET author-trash` | 实际缺口＝作品级软删 + 三级统一列表 | P4 |
| C6 | 待办收件箱（5 类卡、priority、provenance、actions 带 effect、snooze、**实时派生项**） | `GET/POST /api/v1/review-items` + `approve/release/reject`；`backtrack-items/{id}/resolve` 是「后端执行 effect」的现成先例 | 升级 ReviewItem 为卡片模型；新增派生项语义 | P5 |
| C7 | 雪花十步 + 大纲采用（`adoptOutline`） | `snowflake_workspace.py`（v2）齐全：步骤/助手/物化；`outline-plan` + `approve` | 已有对接；`adoptOutline` ≙ 物化主路径 | P3 |
| C8 | 写作房间（自动保存、字数回写、今日字数、streak） | 保存主路径**已确认** = `author-drafts/{type}/{id}/ensure` + `PATCH author-drafts/{draft_id}`；`writer-room` 端点为装载读 | 统计埋点加在 PATCH 服务层 | P2/P3 |
| C9 | 深改面板（issues/采纳/忽略/重扫/撤销） | **已核实**：`scenes|chapters/{id}/deep-review`（扫描）+ `passages/patch-candidates` + `{patch_id}/accept|reject`；undo 端点缺 | 对接；补 undo（仅一步逆操作） | P8 |
| C10 | 风格（学画像→预览→「应用到本项目」决策卡） | `style_reference/` 子系统齐全（`/api/v2/style-reference`） | 对接；「应用」走 P5 决策卡 | P5/P8 |
| C11 | 资料库（实体/关系/时间线/派生） | **实体+关系已存在**：`/api/v2/projects/{id}/library`（GET）、`entities`（POST/PATCH）、`relations`（POST/DELETE） | 补 时间线 + 图投影 + 派生管线 | P6 |
| C12 | 控制塔 + lf7 桥（设定裁决统一/onceTask/归档写回） | `longform_tower.py`：anchors、chapter contract、audit、**`audit/{finding_id}/adjudicate`** | 裁决=adjudicate 与待办卡同源；onceTask=dedupe_key | P7 |
| C13 | 编排/起草台/成稿中心 | `author_desk` `author_drafts` `scenes` `chapter_manuscripts` `chapters/{id}/run/full` `run-status` | 对接 | P8 |
| C14 | 发布索引 / 导入导出 / 设置 | `indexing.py` / `interop.py` / `system_config.py` + LLM 节点注册表 | 对接；UI 偏好留 localStorage | P8 |
| C15 | 流程 flowmap 总览 | 无聚合端点（Vue router 有 workflowGroups 概念） | 新增 `flow-status` 纯聚合 | P2 |
| C16 | ⌘K 面板 | 无需后端：目录 + 雪花步骤 + 动作表客户端模糊匹配 | 不做搜索端点 | P8 |

---

## 3. Phase 一览（详见 `phases/` 各简报）

| Phase | 名称 | 产出 | 依赖 |
|---|---|---|---|
| 0 | 基线与陷阱 | 分支 + 基线截图 + 陷阱清单核对 | — |
| 1 | React 前端工程化 | `frontend-react/` 可 build、全视图可走通（仍 localStorage） | P0 |
| 2 | 作品域 + 聚合 | 作品 CRUD 接真、dashboard/flow-status/writing-stats | P1 |
| 3 | 目录统一 | catalog API 成为章/场景唯一真相源 | P2 |
| 4 | 回收站 | 场景/章节/作品三级软删 + 整体恢复 | P3 |
| 5 | 待办收件箱 | 卡片模型 + 后端 effect + 派生项 + badge | P3 |
| 6 | 资料库 | 时间线 + 图 + 半自动派生 | P3, P5 |
| 7 | 控制塔桥 | 裁决同源 + dedupe 投递 + 归档写回 | P5 |
| 8 | 收尾退役 | 其余视图接真、摘 DemoTag、回归全绿 | 全部 |

**每 Phase 通用流程**：`alembic upgrade head` → 基线 `python -m pytest` 绿 → 按该 Phase 简报实施 → 新端点必配单测 → 跑全量测试 → 更新 PROGRESS.md → 提交 `FE-ALIGN Phase N: <名称>`。
**前端数据迁移通则**：store 接 API 后，保留旧 localStorage 的**一次性上行迁移**（首启检测旧键 → POST 给后端 → 打迁移标记），不许直接丢用户数据。

---

## 4. 全局验收（全部 Phase 完成后）

- 断网刷新 React 前端：除 UI 偏好外无业务数据来自 localStorage。
- 新建空白书 → 雪花十步 → 物化 → 编排 → 起草 → 写作 → 深改 → 归档 → 成稿，全链路真实数据；期间每张待办卡可处理且 effect 真实生效（插场景/改章题/绑画像/裁决均落库）。
- 删除整部书 → 回收站整体恢复，数据无损。
- 待办派生项：人为制造一个雪花空缺 → 待办自动浮现 → 去补全 → 自动消失。
- `python -m pytest` / `verify_windows.ps1` / 前端 build / Playwright 全绿；alembic 头线性。
