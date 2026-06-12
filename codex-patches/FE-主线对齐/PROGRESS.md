# PROGRESS — FE 主线对齐 · 进度账本

> Claude Code：每完成一项勾选并填提交号；「核对发现」一栏记录与简报假设不符的实际情况
> （简报基于 2026-06-11 的代码核对，以仓库实际为准）。换会话续工时**先读本文件**。

## 状态

- [x] Phase 0 · 基线与陷阱 — 提交：d661cd5（另：开工基线快照 c2044ae）
- [x] Phase 1 · 前端工程化 — 提交：00254f5
- [x] Phase 2 · 作品域与聚合 — 提交：e858b8b
- [x] Phase 3 · 目录统一 — 提交：de32d78
- [x] Phase 4 · 回收站 — 提交：64957cd
- [x] Phase 5 · 待办收件箱 — 提交：f6785bb
- [x] Phase 6 · 资料库 — 提交：4f57fb2
- [x] Phase 7 · 控制塔桥 — 提交：b05021e
- [x] Phase 8 · 收尾退役 — 提交：185c39c

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

## Phase 6 记录（2026-06-11）

- 后端：迁移 `20260611_0051`（新表 timeline_events）。LibraryService 扩展：
  时间线 CRUD（GET/POST/PATCH/DELETE …/library/timeline）、图投影
  `GET …/library/graph`（人物+实体 → nodes，关系 → edges，纯投影）、
  人物资料卡 `POST/PATCH …/library/characters`（改名经 character_id 引用不断；
  fe_details 自由字段组挂 summary_json）、overview 聚合并入 timeline。
- 半自动派生（D5）：`services/library_derive.py` + `POST …/library/derive`
  —— LLM 未配置静默跳过（带 author_action 提示）；启用时走 call_llm_node
  （新节点 library_derive：llm_node_registry + config/models.yaml task_routing +
  config/prompts.yaml 模板）；候选**不直接入库**，产 idea 卡
  （dedupe=derive:{chapter}:{name}，actions=确认入库/忽略）。
  effect 注册表补 create_entity / add_timeline_event。归档自动触发挂 P7 写回链。
- demo seed：ws-library-data 种子（people/world/events 20 条）导出
  fe_demo_library.json —— 人物→StoryCharacter、世界→LibraryEntity、
  大事记→TimelineEvent、links→LibraryRelation（指向事件的链接进事件 entity_refs）。
  作品 purge 级联补 StoryCharacter/TimelineEvent。
- 前端：ws-library-data 接真 —— LIB_ENTRIES 退化为可变缓存数组（保持引用，
  视图随访问重挂载读取），API 聚合适配为原型条目形状（人物/世界/大事记；
  refs/profiles/knowledge 三类 P8 接风格/知识子系统前留空）；静态种子改名
  LIB_SEED_ENTRIES 仅作导出脚本数据源。ws-library-edit：LIB_persist 改为
  per-条目 diff → PATCH（人物/实体/时间线分流）+ links diff → relations
  POST/DELETE；LIB_persistAdds → POST（people→characters / events→timeline /
  其余→entities）；LIB_seedOn 恒 true（per-work 隔离由 API 保证）；旧本地
  覆盖层键一次性上行。**视图接缝（与 P3/P5 同类）**：WsReview 增一个
  ws:review-changed 同步 effect（store 异步化后缓存更新需进视图列表）+
  store 在进入 #review 时刷新。
- 验收：6 后端测试绿（时间线 CRUD 排序/图投影/人物改名 id 不断/derive 静默跳过/
  effect 入库进图/seed 幂等）；P6 冒烟 5 项全过 + P5 冒烟回归 6 项全过；
  15 视图零错误；全量 pytest **844 passed**。
- 核对发现：实体「差集」实际不需要新列——aliases/status 已有，first_seen/
  fields(facts/blurb/arc/appears) 走 details_json 键约定；新增 library_derive
  LLM 节点必须同时进 llm_node_registry（缺了会让 system-config sync-missing 422）。

## Phase 7 记录（2026-06-11）

- 链路①（裁决同源）：`create_finding` 同事务产 decision/risk 卡
  （dedupe=canon:{finding_id}，drift/block→risk+P1；FE 展示元数据 subject/value/
  source/drift 以 JSON 存 evidence——不加列）；effect 注册表补 `rule_canon`
  （调 adjudicate 同一服务函数）；adjudicate 反向同事务把卡置 resolved。
  create_finding 接受可选 finding_id（幂等，demo seed / 桥迁移用）。
- 链路②（onceTask）：`Lf7Bridge.onceTask` 退化为 rvPush+dedupeKey 薄封装
  （后端唯一索引静默去重；返回值恒 true——重复与否由后端裁决，记录为已知差异）。
- 链路③（归档写回）：契约 transition→archived 时推进 ChapterGoal.state→draft +
  触发 P6 资料派生（LLM 关静默跳过）；开放 findings 未裁决时 409（force 可越过，
  既有规则）。新端点 `GET …/longform/audit`（项目级清单，桥缓存数据源）。
- flow-status 的 open_review_count 改统一收件箱口径（fe_card 行 status 恒
  pending，旧计数失真）。
- demo seed：LF2_CANON 三条 conflict（c1/c2/c3）→ ChapterAuditFinding（经
  create_finding 同源产卡）。
- 前端：lf7-bridge 接真——findings 项目级缓存；ruleCanon→adjudicate（乐观+刷新）；
  addCanonConflict→POST audit；extraCanon/pendingCanon 从缓存还原 canon 形状
  （evidence JSON）；isArchived 改读目录章状态（draft/review/approved）；
  markArchived 退化为刷新；resetLoop9 不移植（弹说明，等价=reset_author_state）；
  旧 lf7_bridge_v1 一次性上行（extraCanon→findings、canonRuled→adjudicate，
  tasked/archived 丢弃）。handoff9 流程标记仍留本地（纯 UI 流程态）。
- 验收：6 后端测试绿（同事务成卡/双向裁决消失/finding 幂等+卡 dedupe/归档写回/
  开放 finding 阻断）；P7 冒烟 5 项全过；15 视图零错误；全量 pytest **850 passed**。
- 核对发现（简报「adjudicate 幂等性」）：可重复调用，幂等覆盖 decision/note，
  不报错；卡片置 resolved 也幂等。

## Phase 8 记录（2026-06-12）

- 接真状态核对（store 真相源）：home/works/catalog/writer/review/library/trash/
  flowmap = 全后端；manuscripts/author/ops/palette = 派生自目录与正文缓存（真数据）；
  settings/tweaks = UI 偏好（本约定允许本地）。
- 起草台采纳正文改写穿 WrDocs（原直写 localStorage 绕过后端的数据洞）。
- **修复跨作品正文污染 bug**（全局验收冒烟揪出）：WrDocs 的 docMeta 按裸 sid
  缓存，同名 slug（ch01s1）在切换作品后会把 PATCH 打到上一部作品的 draft；
  meta 键改为「作品id::sid」。
- start-dev 默认打开 React（5174，Vue 降为 legacy 备用）；CLAUDE.md 增补
  React 前端章节（架构规则/E2E/账本指针）。
- E2E 平移：scripts/run-smokes.mjs 跑批 smoke-phase2..7（套间 reseed 保独立，
  全部通过）+ scripts/smoke-acceptance.mjs（新建空白书全链路 7 项）。
- ws-styleref 补 WsDemoTag（原缺诚实标注）。
- wsKey 业务键审计：wr-doc:*（后端正文的写穿缓存 ✓）/ ws-lib-graph-pos、
  wr-notes、tweaks（UI 偏好 ✓）/ ws_snow_state_v2（构思暂存，见遗留）/
  scn-run、scn-queue（起草台运行态，见遗留）/ lf7 handoff9（UI 流程标记 ✓）。

### 全局验收（主简报 5 条）

1. **新建空白书全链路** ✓ smoke-acceptance 7/7：新建→编排建章→写正文（author-drafts）
   →统计上涨→待办卡 effect 改目录→契约归档推章状态→回收站往返。
   （雪花构思在本地暂存、其物化边界走 API —— 见遗留 5。）
2. **跨会话** ✓ 清 localStorage 重载后目录/正文/统计/章题全部从后端水合。
3. **demo 两部种子作品** ✓ smoke-phase2..7 六套批跑全过（目录/统计/待办/资料/塔桥）。
4. **Vue 前端不回归** ✓ 59 文件 / 536 测试 + smoke ok。
5. **后端全量** ✓ 850 passed（chroma_integration 12 deselected，Windows 惯例）。

### 遗留 / 例外（DEFERRED）

| # | 事项 | 原因 / 现状 |
|---|---|---|
| D1 | ws-scene 起草引擎 scnRun → 后端 scenes run/full 管线 | 原型用 window.claude.complete（宿主 API，本构建不存在，UI 会明确报「AI 接口不可用」）；run/full 异步任务管线大改造。采纳/字数/状态写回已接真。视图带精确 DemoTag |
| D2 | ws-styleref 视图 → style_reference v2 API | 后端子系统完整；提取/合成需启用 LLM。卡片桥已通（synthesize→全局决策卡→bind_style_profile effect）。视图带 DemoTag |
| D3 | lf6 控制塔视图数据（lf2/lf3 静态） | 桥三链路（裁决/任务/归档）已后端同源；塔的悬念债/弧线等可视化数据待接锚点/审计 API。视图带 DemoTag |
| D4 | ws-manuscripts 版本对比区 | author_drafts 无历史版本查询端点；目录态/批准流已真。区域带 DemoTag |
| D5 | ws-snow 雪花构思 state 本地（ws_snow_state_v2） | 简报 P8 改动清单未列雪花；构思为暂存、其「物化→目录」边界已 API 化（P3 adoptOutline）。后续可对接 snowflake-workspace v2 |
| D6 | window.* 兼容赋值与 9 处运行时探测清理 | 纯机械大改、回归风险 > 收益（不影响「业务数据进后端」验收）；建议独立 PR 处理 |
| D7 | 负载敏感 flaky（created_at 时间戳并列排序断言） | 预存在（P0 基线即有），单跑/整文件全绿，仅并发负载下偶发 |

WsDemoTag 现存 4 处 = D1–D4，全部为上表记录在案的例外。

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

---

## 后续 F 系列（DEFERRED D1–D7 收尾）

> 简报：`后续任务简报-DEFERRED.md`。规则沿用主简报；P8 加的 WsDemoTag
> 在对应管线接真后移除；极小视图接缝沿用 P3/P5/P6 先例并在此记账。

- [x] F1（源 D7）utcnow 严格单调根治负载敏感 flaky — commit 见 git log `FE-ALIGN F1`
- [x] F2（源 D4）author-draft 修订历史 + 成稿对比接真 — commit 见 git log `FE-ALIGN F2`
- [x] F3（源 D5）ws-snow 接 snowflake-workspace v2 — commit 见 git log `FE-ALIGN F3`
- [x] F4（源 D3）lf6 控制塔可视化接锚点/审计 API — commit 见 git log `FE-ALIGN F4`
- [x] F5（源 D2）ws-styleref 接 style_reference v2 — commit 见 git log `FE-ALIGN F5`
- [x] F6（源 D1）ws-scene 起草引擎接 scenes run 管线 — commit 见 git log `FE-ALIGN F6`
- [x] F7（源 D6）window.* 兼容赋值清理 — commit 见 git log `FE-ALIGN F7`

### F1 明细

- `db/models.py:utcnow()` 改进程内严格单调（threading.Lock + 同 tick 微秒 +1），
  所有 `default=utcnow` 列一次性根治；`services/versioning/shared.py:now_iso`
  统一委托同一实现。`services/idempotency.py:utcnow`（返回 datetime，TTL 语义）不动。
- 新增 `tests/test_utcnow_monotonic.py`：万次快速调用严格递增 + 字典序一致、
  8 线程 4000 次无重复、now_iso 委托验证。
- 验证：全量 853 passed（原 850 + 新 3）/ 12 skipped；原 flaky 两文件
  与全量套件并发对跑 20 轮（人为制造高负载）无翻车。

### F2 明细

- 后端：新表 `author_draft_revisions`（draft_revision_id PK / draft_id /
  revision_no / content / words / origin / created_by / created_at，
  (draft_id, revision_no) 唯一）+ 迁移 `20260612_0052`（单头续链，inspector 守卫）。
- `AuthorDraftService` 六个 revision 推进点统一走 `_snapshot_revision`
  （created / edited / derived / proposal_applied ×2 / candidate_inserted），
  幂等（同 draft+revision 已存在则跳过）；冲突 409 不产快照。
- 端点：`GET /api/v1/author-drafts/{draft_id}/revisions`（倒序、列表不带正文）、
  `GET …/revisions/{revision_no}`（含 content；缺失 404
  AUTHOR_DRAFT_REVISION_NOT_FOUND）。测试 `test_author_draft_revisions.py` 4 条。
- 前端 store：`wr-doc-store.jsx` 新增 `WrDocVersions`（list/paras/diff；
  draftId 复用 WrDocs ensure 链路；句级 LCS diff，按新版段落分版式）。
- **授权视图改动（记录在案）**：`ws-manuscripts.jsx` `ManuDiff` 由静态演示组件
  重写为消费 WrDocVersions 的真实对比（视觉契约不变：`.select` 选择器、
  `d-same/d-del/d-add` 句级样式、±句统计）；「对比」标签可见条件由
  `isTide && M_BODY[id]` 放开为「章有场景即可」；调用点补传 `catCh`。
  原 DemoTag（版本对比为演示数据）随接真移除。
- 验证：后端全量 857 passed / 12 skipped；`smoke-f2.mjs` 4/4
  （两次保存→版本列表≥3→旧版内容取回→UI 真 diff 渲染）；run-smokes 六套全过；
  `npm run build` 绿。

### F3 明细

- 新增 store `ws-snow-sync.jsx`（main.jsx 入口追加导入，注释标注非原型清单）：
  `ws_snow_state_v2::<work>` 退化为后端真相的写穿缓存。
  - 上行：监听 `ws:snow-saved`（detail=存储键）→ 按步 diff →
    `PATCH …/snowflake-workspace/steps/{key}`（force=true）。draft 同时带
    **规范字段**（FE 形状映射：audience→book_brief、logline→one_sentence_summary、
    paragraph→one_paragraph_summary（五句脊）、characters→character_sheets、
    synopsis→short_synopsis、backstory→character_synopses、outline→long_synopsis、
    profile→character_bibles、scenes→scene_list、planning→scene_details
    （list+plans 合并成 GCS/RDD 行））与 **fe_* 键**（fe_text/fe_scaffold/
    fe_checks/fe_state/fe_t，merge_step_draft 保留未知键 → 无损往返）；
    revs/confirmRevs 经 book_brief 的 fe_meta 随存。
  - fe_state 变 done 时顺手 POST approve（前序闸门不满足则静默跳过）。
  - 水合：启动 / `#snowflake`/`#home` hashchange / `ws:work-changed` →
    GET workspace；fe_* 优先，无 fe_* 时从规范字段反推原型形状（兼容
    seed/真管线项目）；本地 `_t` 不旧于服务端则本地为准；非雪花项目
    （PROJECT_NOT_SNOWFLAKE 409）静默退出。
- `WsCatalog.adoptOutline` 升级（D5/简报核对发现的正解落地）：
  `ready_to_materialize` 时走 **materialize 主路径**（POST materialize →
  目录 reset 重拉），否则沿用目录批量建章兜底（原逻辑改名 `__adoptByDiff`）。
- **授权视图改动（记录在案）**：ws-snow.jsx 两处保存事件补 `detail: myKey`
  （同步器需知道写的是哪个作品的键）+ 一个 `ws:snow-hydrated` 监听 effect
  （水合落盘后重读缓存刷新组件状态）。视图契约（方法/形状/事件语义）未变。
- 遗留（账本口径）：history（步骤快照日志）不上行——体积大（每条含全量
  drafts+scaffolds 快照）、跨会话价值低；revs/confirmRevs 已随存。
- 验证：smoke-f3.mjs 4/4（上行 PATCH+规范字段 → approve → 清缓存跨会话
  水合 → 构思视图展示水合内容）；run-smokes 六套全过（一次批跑失败定位为
  此前冒烟残留的回收站作品污染 phase4 用例，purge 后复跑全绿；f2/f3 冒烟
  清理步骤已改为软删+回收站彻底清除）；后端全量 857 passed（F3 零后端改动）；
  build 绿。

### F4 明细

- 后端：`ANCHOR_KINDS` 扩 `promise`/`thread`/`arc`（悬念债/故事线/人物弧线），
  FE 形状以 JSON 存 `LongformAnchor.note`（`{"fe": {...}}`），text 存人读摘要；
  无新表无迁移。测试：test_tower_bridge 新增 kind 往返+400 校验。
- seed：`_seed_tide_anchors`（19 条 = 6 设定 + 6 悬念债 + 4 故事线 + 3 弧线，
  与原 LF2_* 演示数据等值；幂等 delete+rebuild；cleanup 级联补 LongformAnchor）；
  test_seed_demo 断言 19。
- 前端 lf2-data：演示层 LF2_LOOPS/CANON/THREADS/ARCS/RISKS 由 const 转 let
  （ESM live binding），新增 `lf2SyncFromTower()`（启动/`ws:work-changed`/
  `#longform` hashchange 水合；有锚点的作品以后端为准，无锚点的非 tide 清空
  演示层）+ `lf2LoopOp`/`lf2CanonOp`（钉入/排期/回收/锁定 → PATCH note 写回）
  + `lf2HasTowerData`。
- **授权视图改动（记录在案）**：lf6-app 六个操作函数各加一行 store 写回调用
  （pinLoop/ensurePinLoop/schedule/resolveLoop/resolveCanon/pinCanon）；
  `WsLongform6` 点亮闸门由「仅 tide」放宽为「tide 或有锚点数据的作品」；
  页级 DemoTag 文案收窄（悬念债/锚点/线/弧已真，「生成/草稿审计」仍为演示——
  接真归 F6 起草引擎管线；LF3_ORPHANS/CAUSAL/CLUES/RETRIEVE 仍为 tide 演示层，
  属同一生成流模拟，记录保留）。
- 验证：smoke-f4.mjs 5/5（seed 19 条 → 水合 → 塔渲染 → POST 新锚点刷新可见 →
  排期写回 PATCH 落库）；run-smokes 六套全过；后端全量 858 passed；build 绿。
  期间教训：8009 验证后端是旧进程时新 kind 会 400——改后端后必须重启验证服务。

### F5 明细

- ws-styleref.jsx 数据层接 style_reference v2（零后端改动）：
  - `srSyncBooks()`：GET books → SR_BOOKS（后端有真实书则以后端为准，
    否则保留演示书做流水线展示）；启动/`#styleref` hashchange 水合。
  - `srImportBook()`：文件选择 → POST import-upload（multipart + 幂等键
    + X-Operator-Ref）；`srBookAction()`：重跑抽取/重新分类——LLM 未启用
    （STYLE_REFERENCE_LLM_REQUIRED）弹「去设置启用」引导，LLM 启用但任务
    路由未配置则透传真实错误（两类都是诚实降级，无假进度）；
    `srDeleteBook()`：DELETE（删除键带时间熵，见下）。
- **踩坑记录（重要）**：style_reference 的 `book_id` 由内容 checksum 决定
  （同文重导 = 同 id）。删除请求的幂等键若只含 book_id，跨轮次会撞键——
  幂等层直接**重放上一次的成功响应而不执行删除**。删除键必须带熵；
  冒烟样本文本也要掺入唯一串避免跨轮 checksum 冲突。
- **授权视图改动（记录在案）**：WsStyleRef 加 `sr:books-changed` 重渲染
  订阅；两处导入入口（+ 按钮 / 导入卡）补 onClick；`runHeaderAction` 真实书
  分流到 `srBookAction`（演示书保留原模拟节奏）；页级 DemoTag 收窄
  （书库/导入/删除/抽取启动已真；矩阵/画像/回测/注入为 LLM 抽取产物，
  启用前保留演示——记录在案的剩余演示区）。
- 验证：smoke-f5.mjs 4/4 连跑两轮（multipart 导入 → 视图渲染真实书且演示书
  退场 → LLM 不可用启动抽取得明确引导 → 删除回落）；run-smokes 六套全过；
  后端全量 858 passed；build 绿。

### F6 明细

- `scnRun` 重写（ws-scene-run.jsx）：window.claude.complete（宿主 API，不存在）
  → 后端 scenes run 管线。`POST /api/v1/scenes/{id}/run/jobs` 投递 →
  轮询 `GET /api/v1/run-jobs/{id}`（终态 completed/blocked/failed/cancelled，
  5 分钟超时）→ `GET …/workbench` 取产出（final → style → neutral 回退）→
  本地确定性复检（scnQC 保留，戏剧拍 beat 后端不标，按「未标注」如实呈现）。
  需人工审阅的 blocked 终态若已有草稿照实取回呈现并注明闸门状态。
- 诚实降级（scnFriendly）：执行契约缺字段 → 引导「补全场景卡 / 走构思物化
  主路径」（带 missing_fields）；LLM 不可用 → 引导去系统设置；其余透传真实
  错误。预检 blocked 的 job 直接报前置检查未通过。无任何假进度/假输出。
- 后端守卫（小修）：`Orchestrator.run_scene` 与 workbench 路由对 FE 目录
  直接建的场景（无 SceneRunState 行）按 scenes POST 约定补建运行态行，
  保证 409 结构化引导而不是 AttributeError 500。
  测试 `test_fe_scene_run_guards.py` 3 条（workbench 200 / run-full 409
  SCENE_EXECUTION_CONTRACT_BLOCKED 带 missing_fields / run-jobs 建任务不 500）。
- 已知差距（记录在案）：作者自由改写指令（note）与上一版草稿暂不进入后端
  管线（管线提示词由 config/prompts.yaml 组装）；起草日志中明确提示改用
  写作台·深改姿态。scnBuildPrompt 保留作提示词参考。
- DemoTag 更新：起草台标注改为「目录场景走 scenes run 真管线，LLM 未就绪
  给明确引导」。
- 验证：smoke-f6.mjs 3/3（最小场景卡投递真管线 → 结构化引导；UI 点「开始
  起草」得到明确报错而非假进度；若环境 LLM 可用则断言真实正文 ≥100 字）；
  pytest 全量 861 passed；run-smokes 六套全过；build 绿。

### F7 明细

- codemod `scripts/codemod-window.mjs`（一次性，留档可复跑）：window.* 跨模块
  **读访问** → 显式 ESM import，共 414 处 / 28 文件。安全规则：只处理
  main.jsx 装配清单内模块（+ ws-app 殿后）；只转换「定义模块加载序更早 +
  已 ESM 导出」的符号（防环）；`window.X =` 注册面、浏览器原生、`__` 运行时
  信箱一律保留。
- 按规则保留的 36 处（划入「确属运行时注入」的探测面）：load-order 29
  （如 ct-* 引用 ws-snow 的 s2 系、ws-writer 引用 LIB_*、ws-catalog 引用
  SnowSync——皆为后载模块，window 探测是正确形态）+ no-export 7
  （lf2LoopOp/lf2CanonOp 等授权接缝，本就设计为 `window.X && window.X()`
  可选探测）。`Object.assign(window, …)` 注册保留——冒烟脚本与接缝依赖它。
- window.claude 活探测仅剩 2 处（ws-snow 候选生成→失败回退静态候选集 /
  ws-writer 内联改写），属 LLM 耦合点 → 记 DEFERRED D8；ws-scene-run 头注释
  同步改为「后端 scenes run 管线」。
- 验证：build 绿 + run-smokes 六套 + smoke-f2..f6 + **smoke-acceptance 7/7**
  全过；后端全量 861 passed（F7 零后端改动）。

## F 系列收口

- 全部七阶段完成；每阶段独立提交；后端最终 861 passed / 12 skipped；
  React build 绿；run-smokes + f2–f6 + acceptance 全绿。
- WsDemoTag 现存 4 处 = 起草台（演示队列场标注，真实场已走真管线）/
  风格参考（LLM 产物 stage）/ 控制塔（生成/草稿审计模拟）/ 成稿中心已移除
  （F2 接真）——逐处与下表对应。

### 新增遗留（DEFERRED，F 系列产生）

| # | 事项 | 原因 / 现状 |
|---|---|---|
| D8 | window.claude 活探测 2 处（ws-snow 步骤候选生成 / ws-writer 内联改写） | 宿主 API 不存在时优雅回退（静态候选 / 报错）；接真需为两者建后端 LLM 节点（registry+models.yaml+prompts.yaml 三件套），独立小阶段可完成 |
| D9 | 起草 note（作者自由改写指令）不进后端管线 | scenes run 提示词由 config/prompts.yaml 组装；起草日志已明示改用写作台·深改姿态 |
| D10 | LF3 演示层（ORPHANS/CAUSAL/CLUES/RETRIEVE/AUDIT 流程模拟） | 与「生成/草稿审计」同属起草管线可视化，待管线在真实 LLM 环境跑通后再投影 |
| D11 | 雪花 history（步骤快照日志）不跨会话 | 体积大（每条含全量快照），revs/confirmRevs 已随存 fe_meta |

---

## 后续 G 系列（DEFERRED D8–D11 收尾）

> 简报：`后续任务简报-DEFERRED-2.md`。规则沿用 F 系列；LLM 阶段验收口径 =
> 管线接真 + 诚实降级（本环境 LLM 不可用，端到端产文不在验收内）。

- [x] G1（源 D10）LF3 空降/断链/线索不公平接审计 findings — commit 见 git log `FE-ALIGN G1`
- [x] G2（源 D11）雪花 history 轻量跨会话 — commit 见 git log `FE-ALIGN G2`
- [x] G3（源 D9）起草 note 进 scenes run 管线 — commit 见 git log `FE-ALIGN G3`
- [x] G4（源 D8）写作台内联改写接 passages/patch-candidates — commit 见 git log `FE-ALIGN G4`
- [x] G5（源 D8）雪花候选生成接后端 LLM 节点 — commit 见 git log `FE-ALIGN G5`

### G1 明细

- seed：`_seed_tide_lf3_findings`（9 条 = 2 空降 unplanted_reveal + 3 因果
  causal_break + 4 认知态 unfair_clue；FE 形状 JSON 存 evidence）。
  **ORM 直插而非 create_finding**——服务会同事务产 decision 卡，这批是
  可视化数据层，不该涌进收件箱（ReviewItem 计数断言不变）。
  AUDIT_KINDS 本就含这三类，后端零代码改动。test_seed_demo 断言 12 条
  findings 按 kind 分布。
- lf3-data：LF3_ORPHANS/CAUSAL/CLUES 转 let + `lf3SyncFromAudit()`
  （GET longform/audit → 按 kind 分桶投影；启动/work-changed/#longform
  水合；无数据的非 tide 清空）。LF3_RETRIEVE / LF3_AUDIT 留演示（起草管线
  运行产物，候 D12）。
- **顺手修掉的真问题**：`Lf7Bridge.extraCanon()` 原来只按「不在 LF2_CANON
  静态 id 里」过滤——G1 的 9 条 LF3 findings 会被误还原成 canon 冲突涌进
  锚点页。补 `kind === "drift"` 过滤（canon 冲突的登记 kind，
  addCanonConflict 也只发 drift）。
- lf6 DemoTag 收窄：空降/断链/认知态已真；「生成/草稿审计」流程模拟与
  记忆预算池仍为演示。
- 验证：smoke-g1.mjs 4/4（seed 12 条 → LF3_* 投影 → 塔渲染空降且 canon 页
  无污染 → POST 新空降刷新可见）；run-smokes 六套全过；后端 861 passed；
  build 绿。

### G2 明细

- ws-snow-sync：fe_meta（book_brief 随行）增 `history`——去掉 snap 内容快照、
  cap 20 条的 journal（t/who/action/note/key）；水合时还原进缓存。
- 视图零新增接缝：时间线的回滚按钮本就只对带 snap 的条目渲染
  （`h.snap && onRestore`），还原条目天然只读；既有水合接缝补一行
  `setHistory`。本地新操作仍带 snap、可回滚。
- 验证：smoke-g2.mjs 3/3（journal 上行 fe_meta 且 snap 剥离 → 清缓存重载
  还原 → 视图无误渲染且无可回滚按钮）；smoke-f3 回归 4/4；后端全量
  861 passed（零后端改动）；build 绿。

### G3 明细

- 链路：`POST run/jobs` / `POST run/full` 接受可选 `author_note`（≤500 字）→
  job payload_json 随行（serialize_job 曝光）→ worker →
  `Orchestrator.run_scene(author_note=…)` → `generate_style_draft` 的
  extra_instruction 追加 `author_note_instruction()` 段（管线本就有该注入
  通道，模板零改动；空 note 完全无变化）。run/full 的幂等载荷含 note
  （不同指令=不同请求哈希）。
- FE：scnRun 上行 author_note；起草日志由「指令不进管线」改为
  「改写指令已随任务下发（注入风格生成阶段）」。D9 销账。
- 测试 3 条：author_note_instruction 格式/截断；run/jobs 载荷往返；
  run/full 经 stub Orchestrator 断言转发。全量 864 passed。
- 验证：smoke-f6 回归 3/3（G3 后端重启 8009 后）；build 绿。

### G4 明细

- `wrRewriteMulti` 弃 window.claude → `POST /api/v1/passages/patch-candidates`
  （现成 writer_passage_patch 节点；指令+语气滑杆并入 issue_dimension 自由
  文本；场景定位 = 当前在写 sid → 后端 scene_id）。
- 候选裁决闭环：替换 → accept（带 selected_option_id）；关闭未采纳 →
  reject——这是作者偏好画像（AuthorPreferenceProfile）的学习入口；
  幂等（裁决一次即清，close 的 reject 对已裁决 no-op）。
- 诚实降级：离线确定性占位（rationale 标记 offline deterministic）按
  「模型不可用」处理不冒充真实改写；错误文案升级为「去系统设置启用 LLM」。
- **授权视图改动（记录在案）**：WriterRoom 增 1 行 activeScene → 模块级
  WR_ACTIVE_SID 镜像 effect；doReplace/close 各 1 行裁决回传；
  wrRewriteMulti/wrPatchDecide 进 window 注册表（冒烟驱动面）。
- 验证：pytest 7 条 guards（含 G4 离线全链 + accept）；全量 865 passed；
  smoke-g4 3/3（真实端点 + no-model 降级 + 视图可达）；run-smokes 六套
  全过；build 绿。window.claude 活探测仅剩雪花候选 1 处（G5 销）。

### G5 明细

- 新 LLM 节点 `snowflake_step_candidates` 三件套齐备（registry +
  config/models.yaml task_routing + config/prompts.yaml 模板，
  structured_schema=[{label,tag,text,notes}]，temp 0.7）。
- 端点 `POST …/snowflake-workspace/steps/{step_key}/fe-candidates`：
  上下文/草稿折叠文本由 FE 随请求带入（**与简报「后端折叠」的差异，
  以代码为准记录**：原型脚手架形状只在前端存在，后端持有提示词模板与
  路由——同 passages/patch 的分工），复用 `_run_structured_task`
  （LLM 关 → source=fallback 空候选；路由缺失 → sync_missing 引导）。
- FE：`s2GenerateCands` 弃 window.claude 改走端点；fallback/空 → 抛
  「去系统设置启用 LLM」引导（默认展示的本地启发式候选 s2GenericCands
  不受影响，不冒充生成成功）；FE→BE 步骤键映射正源迁至 ws-snow 的
  `S2_BE_STEPS`，ws-snow-sync 改引用（消除双份漂移）。
- **window.claude 引用归零**（代码 + 注释，grep 验证）——D8 销账。
- 验证：pytest 4 条（fallback 语义/非法步骤/normalize 裁剪/三件套铁律）
  全量 869 passed；smoke-g5 3/3；run-smokes + f2/f3/f4/f5/f6/g1 +
  **smoke-acceptance 7/7** 全过；build 绿。

## G 系列收口

- G1–G5 全部完成，每阶段独立提交；后端最终 869 passed / 12 skipped；
  build 绿；全部冒烟（六套批跑 + f2–f6 + g1/g2/g4/g5 + acceptance）绿。
- D8（window.claude ×2）、D9（note 进管线）、D10（LF3 三层投影）、
  D11（journal 跨会话）全部销账。
- 仍为演示的区域（每处有 DemoTag + 账本记录）：起草台演示队列场、
  风格参考 LLM 产物 stage、控制塔「生成/草稿审计」流程模拟与记忆预算池
  （D12，见下）。

### 新增遗留（DEFERRED，G 系列产生）

| # | 事项 | 原因 / 现状 |
|---|---|---|
| D12 | 控制塔「生成/草稿审计」流程模拟 + LF3_RETRIEVE 记忆预算池 | 展示的是起草管线在真实 LLM 环境下的运行产物（交接回执/逐条审计/预算分配）；管线已可真跑（F6/G3），待 LLM 环境就绪后把真实 run 产物投影进塔（替换 LF3_AUDIT 静态） |

---

## 后续 H 系列（DEFERRED D12 收尾）

> 简报：`后续任务简报-DEFERRED-3.md`。审计回执诚实口径：确定性扫描只声明
> 「检出（真实引用句）/未检出（待人工核对）」，违约判定留给 LLM 审计（D13）。

- [x] H1（源 D12）LF3_RETRIEVE 记忆池接锚点库 — commit 见 git log `FE-ALIGN H1`
- [ ] H2（源 D12）章级审计回执接真实产物 — commit `______`

### H1 明细

- seed：rv1–rv5 五条入锚点库（kind 按语义 fact/setting/trait/timeline，
  `status="faded"` = 淡出可检索，fe JSON 带 pool:"retrieve"）；tide 锚点
  19→24，seed 断言 + smoke-f4 断言随更新。
- lf2SyncFromTower 分流：pool/faded 锚点不进 LF2_CANON，归集
  `LF2_RETRIEVE_POOL`（ESM live export）；lf3-data 在 `lf2:tower-synced`
  上投影进 LF3_RETRIEVE（const→let；Lf3Memory/Lf4Brief 等消费者
  live import 自动生效）；无数据非 tide 清空。
- 钉入升格（pinnedFacts promote）不做持久写回——以代码为准的裁决：
  promote 是「本章简报」级 UI 状态，其持久面就是下发契约本身（P7 已真），
  全局改写 anchor status 反而语义错位。记账。
- 验证：smoke-h1.mjs 4/4（seed 24/5 faded → 投影 5 条且 canon 不被污染 →
  塔记忆面板渲染 → POST+PATCH faded 新条目刷新可见）；smoke-f4 回归过；
  run-smokes 六套全过；后端全量 869 passed；build 绿。
