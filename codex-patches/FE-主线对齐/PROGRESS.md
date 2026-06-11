# PROGRESS — FE 主线对齐 · 进度账本

> Claude Code：每完成一项勾选并填提交号；「核对发现」一栏记录与简报假设不符的实际情况
> （简报基于 2026-06-11 的代码核对，以仓库实际为准）。换会话续工时**先读本文件**。

## 状态

- [x] Phase 0 · 基线与陷阱 — 提交：d661cd5（另：开工基线快照 c2044ae）
- [x] Phase 1 · 前端工程化 — 提交：00254f5
- [ ] Phase 2 · 作品域与聚合 — 提交：
- [ ] Phase 3 · 目录统一 — 提交：
- [ ] Phase 4 · 回收站 — 提交：
- [ ] Phase 5 · 待办收件箱 — 提交：
- [ ] Phase 6 · 资料库 — 提交：
- [ ] Phase 7 · 控制塔桥 — 提交：
- [ ] Phase 8 · 收尾退役 — 提交：

## 决策点确认（开工前人工填写；空白 = 按默认）

- D1 前端栈：默认（React → frontend-react/，Vue 并行保留）
- D2 统计服务端化：默认（服务端算，Asia/Shanghai）
- D3 回收站清理：默认（仅手动永久删除）
- D4 effect 后端执行：默认
- D5 派生半自动：默认
- D6 新端点走 v2：默认

## Phase 0 基线记录（2026-06-11）

- 分支：`fe-align`；基线提交 `c2044ae`（固化开工时工作树里既有的未提交改动：
  library/longform_tower 后端 + 迁移 0041–0046 + Vue 设计迁移 WIP + 本简报包。
  这批改动即简报「已核实」所基于的代码状态，不属于任何 Phase 的产出）。
- `alembic heads` = `20260611_0046`（单头），`alembic current` = head。
- Vue 端 `npm run test`：59 文件 / 536 测试全绿 + smoke ok。
- 后端 `python -m pytest -m "not chroma_integration"`（仓库根运行）：**808 passed, 12 deselected**（4m31s）。
  注意：须从仓库根运行（个别测试用仓库根相对路径读 golden 文件）；Windows 解释器为 Anaconda python。
- 基线截图：`baseline-shots/01-home.png … 15-trash.png`（1600×1000，两部种子作品各打开一遍后截取；
  生成脚本 `baseline-shots/capture.mjs`，静态服务 8077 端口）。
- 陷阱清单 T1–T13 逐条核对属实：T1 缓存串/T2 CSS 14 文件层叠顺序/T3 JSX 46 脚本顺序
  （终端入口 ws-app.jsx）/T4 createRoot 在 ws-app.jsx:459/T5 splash+CDN React 18.3.1/
  T6 EDITMODE 注释包 WS_DEFAULTS/T7 __activate_edit_mode 两处（ws-app.jsx:143,448）/
  T8 运行时探测 9 处 6 文件/T11 无前缀 localStorage 键。
  T12：design/ 下无 merge-plan-*、design-canvas、*-standalone 文件，index.html 引用即搬运清单。

## Phase 1 记录（2026-06-11）

- `frontend-react/`：Vite 6 + React 18.3.1。`src/` 由一次性 codemod
  `scripts/port-design.mjs` 从 `design/` 机械转换生成（import/export 化 + 入口装配，
  逻辑零改动；window.* 赋值过渡期保留）。后续 Phase 直接演进 src/，不再重跑 codemod。
- 人工处理两个文件：`tweaks-panel.jsx`（删宿主 postMessage 协议与 deck-stage 逻辑，
  useTweaks 持久化改 localStorage 键 `ws_tweaks_v1`，面板开关改听本地事件 `ws:tweaks-open`）；
  `ws-app.jsx`（两处 `__activate_edit_mode` postMessage → dispatch `ws:tweaks-open`，
  尾部 createRoot 移入 main.jsx，不包 StrictMode）。
- 验收：`npm run build` 过（86 模块，仅 chunk 体积提示）；15 视图 Playwright 截图
  （`scripts/shoot-views.mjs`）与 Phase 0 基线肉眼一致、零 console/page 错误；
  交互冒烟（`scripts/smoke-interact.mjs`）6 项全过：主题切换/舒适度面板/⌘K/
  新建作品/作品切换/删除→回收站恢复（均 localStorage）。
- `scripts/dev.ps1` + start/stop-dev.cmd 增加 React 前端（5174），与 Vue（5173）并行；
  `frontend-react/README.md` 注明双入口。

## Phase 2 记录（2026-06-11）

- 后端：`StoryProject` 增 mark/accent/synopsis_line/words_target_daily/is_demo（迁移
  `20260611_0047`，单头）；新表 `project_writing_stats`；`services/writing_stats.py`
  （today/streak 规则照抄原型 catAddToday/catBumpStreak/catEffectiveStreak，
  Asia/Shanghai；字数口径=剥 HTML 去空白字符数）；埋点挂在
  `AuthorDraftService.save`（PATCH author-drafts 主路径，D2）。
- 新端点（routes/project_overview.py，全部 v2）：`PATCH …/profile`、
  `GET …/writing-stats`、`GET …/dashboard`（resume/brief/snowflake/chapters_recent/stats）、
  `GET …/flow-status`。v2 项目列表每项附 `stats` + `chapters_written`。
- 章节展示态（state/pct）在 P3 目录统一前暂存 `ChapterGoal.writer_brief_json["fe_display"]`
  （demo seed 写入），P3 落正式列。
- demo seed：`tools/seed_fe_demo_works.py`（挂入 seed_demo，幂等）；**project_id 沿用
  原型字面 id `tide`/`salt`**——前端目录种子按该 id 命名空间回退，换 id 会让 demo 目录消失。
- CORS 默认白名单补 5174/5175（React dev/preview）。
- 前端：`lib/client.js`（自 Vue 端移植）；`ws-works.jsx` 全面接真（列表/创建/档案
  PATCH/一次性迁移 ws_works_created_v1→POST；缓存影子保 list() 同步语义；
  乐观更新+失败回滚；WS_WORKS_SEED 硬编码删除）；派生字段只读化——
  `WsWorks.update` 不再接受 wordsTotal/wordsToday/streak/chaptersWritten，
  `catPushTotals` 改读 writing-stats 经内部接缝 `__applyDerived` 注入（带变化守卫防
  ws:work-changed 自激循环）。`remove`/`restoreWork` 在 P4 接软删端点前为提示性空壳。
- 验收：12 个新后端测试绿；前端 build 过；Playwright 冒烟 5 项全过
  （书架来自后端/统计数字/新建落库换会话仍在/主页渲染/PATCH profile 落库）。

## 核对发现（实际代码 vs 简报假设）

| Phase | 简报假设 | 实际情况 | 处理 |
|---|---|---|---|
| 1 | 文件头 `/* global */` 注释 = 完整依赖清单 | 有遗漏（如 ws-app.jsx 用了 ws-snow 的 `WsConstruct` 未声明） | codemod 加全注册表词边界扫描兜底；只允许 import 加载序更早的文件防环 |
| 1 | T12 提到 design/ 可能混入 merge-plan-*/design-canvas/*-standalone | 实际不存在这些文件；index.html 引用清单即全部 46 个 jsx + 14 个 css | 按 index.html 清单搬运 |
| 2 | 主页读 `work.home`（dashboard 供给） | ws-home 实际**优先读本地 WsCatalog/s2StepSummary/rvOpenItems**，home 仅兜底 | dashboard→home 适配照做（新建作品/兜底路径用）；目录真相 P3 切换 |
| 2 | 雪花第 10 步 step_key | 是 `scene_details` 不是「场景规划 scene_planning」 | seed/映射按 scene_details |
| 2 | `POST /api/v2/projects` 载荷 | `outline_text` 必填（ProjectService.create 校验） | 适配层以 sub/title 兜底填充 |
| 2 | ChapterGoal 有标题概念 | **无 title/序号列**；标题只能放 writer_brief_json | P2 用 brief.title + fe_display；P3 建正式列 |
| 2 | 正文保存写路径 | ✅ 已核实：`ensure` + `PATCH author-drafts/{draft_id}` | 埋点加在 PATCH 服务层 |
| 4 | 章/场景 trash 的实现机制（软删标记 or 移表）；两套是否同一服务 | （待核对 services 层） | |
| 5 | ReviewItem 状态机可扩展为统一 state | （待核对） | |
| 6 | library 实体模型字段差集 | （待核对） | |
| 7 | adjudicate 幂等性 | （待核对） | |

## 遗留 / 例外

- P2→P3 间隔期：写作器正文仍存 localStorage（wr-doc 键），本地写作不产生服务端
  words_delta —— 切换器「今日字数/总字数」在此期间只反映后端统计（demo 种子值），
  P3 接通 author-drafts 保存链路后恢复实时。
- `WsWorks.remove/restoreWork` 为提示性空壳（P4 接软删/恢复端点）；作品删除入口
  按钮仍可见但点击只弹说明（视图零修改约束下的最小方案）。
- 旧 localStorage 键（ws_works_created_v1 等）迁移后保留不删（P8 统一清理）。
- demo 作品的本地目录种子（ws-catalog/ws-snow 等）在 P3 前继续生效——主页/构思
  视图对 demo 作品显示的是本地种子数据 + 服务端统计的混合（诚实标识 WsDemoTag 未摘）。
