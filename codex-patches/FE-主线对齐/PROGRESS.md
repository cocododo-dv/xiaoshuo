# PROGRESS — FE 主线对齐 · 进度账本

> Claude Code：每完成一项勾选并填提交号；「核对发现」一栏记录与简报假设不符的实际情况
> （简报基于 2026-06-11 的代码核对，以仓库实际为准）。换会话续工时**先读本文件**。

## 状态

- [x] Phase 0 · 基线与陷阱 — 提交：d661cd5（另：开工基线快照 c2044ae）
- [x] Phase 1 · 前端工程化 — 提交：00254f5
- [x] Phase 2 · 作品域与聚合 — 提交：e858b8b
- [x] Phase 3 · 目录统一 — 提交：de32d78
- [x] Phase 4 · 回收站 — 提交：64957cd
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

## Phase 3 记录（2026-06-11）

- 后端：迁移 `20260611_0048`（ChapterGoal += narrative_json/state/words_target/display_order；
  SceneCard += state/words_current；场景排序**复用 scene_seq**，不另建列）。
  `services/catalog.py` + `routes/catalog.py`（v2）：GET 全树（slug=chNN/chNNsM 计算、
  words rollup、display_order 惰性补号）、章/场景 PATCH、建章（空目录首章立 writing）、
  插场景(at)、move（复用 scene_seq 逻辑）、import（admin/loopback 保护，仅空目录，
  章级字数差额摊给零字数场景）。章标题权威字段=narrative_json["title"]（回退
  writer_brief_json.chapter_title→title→chapter_goal 首行）。
- `author_drafts.save`：scene.words_current 落库 + 响应带 words_rollup
  {scene_words, chapter_words, words_total}；project_overview 章节视图改走
  CatalogService（与目录 API 同源，fe_display 退役，pct=words rollup）。
- demo seed 升级：前端种子目录（ARR_CHAPTERS/CAT_SALT_CHAPTERS 全量戏剧卡/线索/张力）
  经 `scripts/export-demo-catalog.mjs` 导出为 `tools/fe_demo_catalog.json`，seed 走
  CatalogService.import_catalog（与迁移同一代码路径）；当前章的在写场景挂正文草稿。
- 前端：`ws-catalog.jsx` 接真 —— API 缓存 + 形状适配（C4：reactive 的 RDD 映射进
  goal/obstacle/turn 槽位 + kindFields=["反应","两难","决定"]）；**set() diff 引擎**
  （6 处整树写穿调用点不动视图：字段变化→PATCH、新增→POST、删除→既有 v1 trash、
  排序→既有 v1 scene-order）；本地 today/streak 计数器退役（catToday/catAddToday/
  catBumpStreak 删除，统计全走服务端）；一次性迁移 arr.chapters.v2 → POST import
  （仅后端目录为空时；打 ws_catalog_migrated_v1::<id> 标记）。
- `wr-doc-store.jsx`（新 store）：正文 = author-drafts 主路径（ensure + PATCH，
  revision 冲突以服务端为准重水合）；wr-doc 本地键退化为同步读缓存；保存响应的
  words_rollup 回流目录+统计。ws-writer.jsx 改动=3 个持久化触点 + 水合回填监听 +
  目录就绪后默认场景补选（冷启动直达 #writer 的修复）。
- 验收：catalog 7+2 后端测试绿；Playwright P3 冒烟 7 项全过（目录来自后端含戏剧卡/
  改章题落库/加删场景后端可见/正文保存→words rollup 全链路/跨会话水合）；15 视图
  截图零 console 错误，编排台与基线像素一致（数据已为后端目录）。

## Phase 4 记录（2026-06-11）

- 后端：迁移 `20260611_0049`（StoryProject += trashed_flag/at/by，沿用章/场景列名约定）。
  `services/trash.py` + `routes/trash.py`（v2）：作品软删 `DELETE /api/v2/projects/{id}` /
  恢复 `POST …/restore`；统一三级列表 `GET /api/v2/trash?project_id=…`（条目 id =
  `work:|chapter:|scene:` 前缀；全局作品桶 + 作品内章/场景桶；章被删时其场景
  restorable=false 引导先恢复章）；按条目恢复 `POST /api/v2/trash/{entry}/restore`；
  永久清除 `DELETE /api/v2/trash/{entry}`（D3 仅手动；作品 purge 级联 FE 域全表）。
  catalog 路由补章/场景级软删/恢复桥（校验归属后走既有 AuthorLifecycleService）。
  `ProjectService.list` 过滤软删作品。
- 前端：`WsTrashStore` 接真（缓存 + work-changed/trash-changed 刷新；push 退化为
  刷新壳；restore 乐观返回 true、失败 store 自提示）；`WsWorks.remove` 实装软删
  （乐观下架+回滚），`restoreWork` 实装恢复端点；**isSeed 恒 false**（摘「种子不可删」，
  demo 可删可恢复；演示身份仍在 work.isDemo）。
- 验收：5 个后端测试绿（往返/三级列表/正文随恢复回来/purge 无残影/章删级联下场景
  恢复阻止）；P4 冒烟 4 项全过（删整部→切换器消失→回收站恢复→数据无损含统计；
  删场景→恢复正文保留；永久清除无残影）；全量 pytest **832 passed**；build 过。

## Phase 5 记录（2026-06-11）

- 后端：迁移 `20260611_0050`（ReviewItem += project_id/kind/priority/provenance_json/
  card_json/actions_json/state/snooze_until/resolved_action_index/dedupe_key +
  (project_id,dedupe_key) 唯一索引；新表 review_derived_snoozes）。**扩展原表**：
  卡片行 item_type="fe_card"、status 恒 pending（legacy CheckConstraint 兼容），
  生命周期走 state；legacy 行响应映射 pending→open、approved/rejected→resolved。
- `services/review_cards.py`：create（dedupe 静默去重=onceTask）/list（持久卡∪派生卡，
  全局卡 project_id=NULL 任一作品可见）/resolve（**同一事务执行 actions_json[i].effect**，
  D4）/unresolve（不回滚 effect）/snooze（派生按指纹存表）/badge。
  `services/review_effects.py` 注册表：insert_scene、rename_chapter（走 CatalogService）、
  bind_style_profile（走 style_reference MaterializationService.apply_profile，
  scope=project=当前作品）；rule_canon P7 注册、create_entity/add_timeline_event P6 注册。
- `services/review_derived.py`：三类派生（雪花空缺/已起草未确认、目录异常·空章+
  成稿无字、产出待办·审阅中待批准/全场成稿可送审）；三语义后端保证（live 卡 resolve
  409 / GET 现算修好即消 / id 带指纹 snooze 按指纹存）。
- 端点：GET review-items?state=&project_id=（卡片模式）、POST（kind 载荷走卡片创建）、
  resolve/unresolve/snooze/unsnooze、badge（声明在 {review_id} 之前防吞）。
- 生产者：风格画像 synthesize 完成 → 全局 decision 卡（dedupe=style-profile:{id}，
  effect=bind_style_profile，resolve 时以当前作品为 scope 绑定）。demo seed 给 tide
  补 5 张原型 RV_SEED 卡（rename/insert effect 指向真实章节 id）。
- 前端：ws-review store 段接真（适配层卡片↔视图形状；rvPush→POST；resolve/snooze/
  unresolve→端点；badge=缓存派生；done_today 留 localStorage UI 计数；旧 ws_review_v1
  custom 项一次性上行）。**视图唯一接缝**：act() 增一行 `window.rvResolveAction(item, a)`
  ——effect 后端化后 store 必须知道点了哪个动作（action_index），视图本地 runEffect 对
  后端 effect 占位类型自然 no-op，needsChoice 守卫保留。
- 验收：6 后端测试绿（建/列/收/撤、dedupe、effect 事务含未知类型 400、派生三语义、
  badge、全局卡）；P5 冒烟 6 项全过（QC 卡插场景落库/决策卡 rename 落库/badge/
  派生不可划掉+修好消失/dedupe）；15 视图零错误；全量 pytest **838 passed**。

## 核对发现（实际代码 vs 简报假设）

| Phase | 简报假设 | 实际情况 | 处理 |
|---|---|---|---|
| 1 | 文件头 `/* global */` 注释 = 完整依赖清单 | 有遗漏（如 ws-app.jsx 用了 ws-snow 的 `WsConstruct` 未声明） | codemod 加全注册表词边界扫描兜底；只允许 import 加载序更早的文件防环 |
| 1 | T12 提到 design/ 可能混入 merge-plan-*/design-canvas/*-standalone | 实际不存在这些文件；index.html 引用清单即全部 46 个 jsx + 14 个 css | 按 index.html 清单搬运 |
| 2 | 主页读 `work.home`（dashboard 供给） | ws-home 实际**优先读本地 WsCatalog/s2StepSummary/rvOpenItems**，home 仅兜底 | dashboard→home 适配照做（新建作品/兜底路径用）；目录真相 P3 切换 |
| 2 | 雪花第 10 步 step_key | 是 `scene_details` 不是「场景规划 scene_planning」 | seed/映射按 scene_details |
| 2 | `POST /api/v2/projects` 载荷 | `outline_text` 必填（ProjectService.create 校验） | 适配层以 sub/title 兜底填充 |
| 2 | ChapterGoal 有标题概念 | **无 title/序号列**；标题只能放 writer_brief_json | P2 用 brief.title + fe_display；P3 建正式列 |
| 3 | 简报：SceneCard 增 display_order | scene_seq 已是排序字段（v1 scene-order 端点写它） | 复用 scene_seq，不建新列（简报改动2也要求二选一） |
| 3 | adoptOutline ≙ 物化主路径（materialize/approve） | ws-snow 在 P3 仍是本地数据，后端无 scene plans，materialize 必 409 | adoptOutline 经 set() diff → catalog API 后端建章；materialize 主路径待 ws-snow 接 v2 工作台（P8）|
| 3 | 章级与场景级 trash 机制 | 已核对：同一服务 AuthorLifecycleService，软删标记 trashed_flag（章 trash 级联场景）；purge 物理删除 | P4 沿用同一机制扩作品级 |
| 3 | 「wr-notes:<sid> 同步迁移」 | 写作器代码中无该键的实际使用者（仅回收站 purge 清理它） | 无需迁移；P4 处理回收站时一并核对 |
| 2 | 正文保存写路径 | ✅ 已核实：`ensure` + `PATCH author-drafts/{draft_id}` | 埋点加在 PATCH 服务层 |
| 4 | 章/场景 trash 的实现机制（软删标记 or 移表）；两套是否同一服务 | 同一服务 AuthorLifecycleService；trashed_flag 软删；章 trash 级联场景；「场景已删时章删被 409 阻止」「场景 restore 追加到章尾（scene_seq 重排）」 | 作品级沿用同列名约定；统一列表对被级联场景标 restorable=false |
| 5 | ReviewItem 状态机可扩展为统一 state | status 有 CheckConstraint(pending/approved/rejected)，不能直接改枚举 | 新增独立 state 列；卡片行 status 恒 pending；legacy 行响应映射 |
| 6 | library 实体模型字段差集 | （待核对） | |
| 7 | adjudicate 幂等性 | （待核对） | |

## 遗留 / 例外

- P2→P3 间隔期：写作器正文仍存 localStorage（wr-doc 键），本地写作不产生服务端
  words_delta —— 切换器「今日字数/总字数」在此期间只反映后端统计（demo 种子值），
  P3 接通 author-drafts 保存链路后恢复实时。
- `WsWorks.remove/restoreWork` 为提示性空壳（P4 接软删/恢复端点）；作品删除入口
  按钮仍可见但点击只弹说明（视图零修改约束下的最小方案）。
- 旧 localStorage 键（ws_works_created_v1 等）迁移后保留不删（P8 统一清理）。
- ~~demo 作品的本地目录种子在 P3 前继续生效~~（P3 已解决：目录种子后端化，
  目录/正文/字数全链路后端；ws-snow 构思视图仍本地，P8 接 v2 工作台）。
- P3：`WsCatalog.reset()` 改为「丢缓存重拉服务端」——demo 作品不再能从前端一键回种子
  （等价能力=重跑 seed_demo / dev 重启自动 reseed）。
- P3：ws-manuscripts 经 set() 写的 `approvedAt` 是视图糖字段，不入库（refetch 后丢失，
  显示退化为状态徽标）；P8 接成稿中心时按需落库。
- ~~P3：restoreScene 重新建行~~（P4 已切后端 restore：恢复原行，但**追加到章尾**——
  既有 lifecycle 语义 scene_seq 重排，与原型「恢复回原位置」略有出入，记为已知差异）。
- P4：旧 localStorage 回收站条目（ws_trash_v1/ws_trash_works_v1）不迁移——其中场景
  在后端真相里已不存在或已另行处理，恢复无意义；旧键 P8 统一清理。
- P4：场景 purge 不再清理本地 wr-doc 缓存键（scene_id↔slug 映射已断）；残留缓存键
  无害，P8 统一清理。
- 题外（DEFERRED，不属本任务范围）：既有测试存在**负载敏感的偶发失败**——
  `test_scene_generation.py::test_run_scene_records_style_routing_failure`、
  `test_qc_engine.py` 两例等按 `created_at` 排序断言的测试，在机器高负载下多行
  落入同一时钟 tick，排序回退到随机 id 而翻车（Windows 时钟粒度）。无并发负载时
  全量 827 passed 全绿；与 FE-ALIGN 改动无关（P2 提交点同样可复现机制）。
  建议后续给 LlmCall 排序断言加序列号或冻结时钟，本任务不动。
