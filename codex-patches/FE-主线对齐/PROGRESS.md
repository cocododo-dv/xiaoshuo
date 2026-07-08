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
- [x] H2（源 D12）章级审计回执接真实产物 — commit 见 git log `FE-ALIGN H2`

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

### H2 明细

- 后端 `GET …/longform/chapters/{chapter_id}/audit-receipt`
  （LongformTowerService.audit_receipt，纯确定性无 LLM）：契约段（真）+
  产出段（场景卡 state/words + 各场 author-draft 正文剥 HTML，占位文档
  不算正文）+ 锚点在场扫描（pinned 设定锚点的 value 子串检索 → 命中摘
  **真实引用句** + 「场次 · 段 N」定位；未命中归 misses；promise 锚点
  payoff==本章序归 pending 到期承诺）。章序经 display_order 推导。
  测试 1 条（无正文 has_text=False / 命中带引用句 / 未检出 / 到期承诺）。
- FE `Lf7Bridge.auditReceipt(chNo)`：还原 LF3_AUDIT 形状——honored=命中
  （真实证据句），introduced=未检出+到期承诺（待人工核对语义），
  **drifted 恒空**（违约判定属 LLM 审计，D13）；无正文返回 null。
- **授权视图改动（记录在案）**：lf6 增 realAud 状态 + 拉取 effect
  （挂载/lf:bridge-changed/beginAudit 刷新，章号取 LF2_NEXT）；
  `aud` 与三处 audit 消费（页签/审计动画/归档动画）改为「真回执优先、
  无正文回落静态演示」。d1/d2/n1/n3 硬编码动作只随静态路径出现。
  DemoTag 收窄至「违约级判定 + 流程动画裁定语气」。
- 验证：pytest 全量 870 passed；smoke-h2.mjs 4/4（锚点命中真实引用句 /
  未检出 / 到期承诺 / 桥形状还原 + drifted 恒空）；run-smokes 六套 +
  smoke-acceptance 7/7 全过；build 绿。

## H 系列收口（D12 销账）

- H1/H2 完成；后端最终 870 passed / 12 skipped；全部冒烟绿。
- 控制塔最后的演示残余收敛为 **D13**：

### 新增遗留（DEFERRED，H 系列产生）

| # | 事项 | 原因 / 现状 |
|---|---|---|
| D13 | 章级审计的「违约判定」LLM 节点 + 流程动画的逐条裁定语气 + 静态路径的 d1/d2/n1/n3 演示动作 | 确定性扫描只能诚实声明「检出/未检出」；判定「草稿违反了契约第 N 条」需要 LLM 审计节点（性质同 styleref 提取/起草引擎：三件套 + 真实 LLM 环境）。回执管道（H2）与裁决产物化（P7 onceTask）都已就绪，接上节点即闭环 |

---

## 维护轮 · 重构后全链路猎虫（2026-06-12）

> 流程：基线回归（后端全量 + Vue 单测 + React build + 18 套冒烟）→ API 边界探针 /
> 空白书漫游 / 15 视图巡检 → Vue E2E（重构期间从未跑过的面）→ 修复 → 定点+全量复验。

### 修复 1 · v2 创建类端点幂等键被静默忽略（后端契约 bug）

- 探针发现：同一 X-Idempotency-Key 重放 `POST catalog/chapters` 建出**两个不同的章**。
  catalog.py 文件头声称「写端点全部要求幂等键（中间件统一拦截）」，实际不存在该中间件
  ——`IDEMPOTENCY_KEY_REQUIRED` 只在 `execute_with_idempotency` 里抛，而 catalog/library/
  longform_tower 的写端点根本没接它。前端 client.js 每次变更调用都带键，后端却不兑现。
- 修复：8 个「会创建新行」的端点接 `execute_with_idempotency`（必填 + 同键重放同响应）：
  catalog 建章/建场景、library 实体/关系/时间线/人物、longform 锚点/audit finding。
  PATCH/move/软删/恢复按天然幂等语义不强制（catalog.py 头注释已改为与实现一致）。
- 测试：3 条回归（重放同 id / 缺键 400 / 换载荷 409；catalog+library+tower 各覆盖）；
  test_library.py / test_longform_tower.py 两个旧文件的裸 POST 补 `_idem()` 头。
  冒烟脚本的裸 fetch 全部本就带键，零改动。

### 修复 2 · style_reference 路径导入空标题产出无名书

- Vue E2E reference-learning 揪出：标题留空时 `ingest_path` 原样落空串，
  书列表显示「—」。修复：ingest_path 空标题回退 `path.stem`，ingest_upload
  回退文件名 stem（无文件名时「未命名参考书」）。+1 回归测试。

### 修复 3 · Vue E2E 两个 spec 适配现实（重构期间无人跑过 test:e2e）

- chapter-batch：作者工作台章节列表已是 VirtualList（5/18 warm-paper 重构引入），
  视口外的行不进 DOM——spec 经 API 建的 CH910 排序在末尾，直接 click 挂死 120s。
  补 `scrollVirtualListTo` 滚动定位助手（与 author-trash 等已适配 spec 同思路）。
- reference-learning：抽取 run 自 PR-3 起强制要求 LLM（STYLE_REFERENCE_LLM_REQUIRED
  诚实降级），spec 还停留在「offline placeholder 产 8 findings」的旧设计。重构为双轨：
  无 LLM 环境断言「明确引导 + 零假 findings」（与 React smoke-f5 同语义）；
  完整链路轨 `test.skip(!LLM_LIVE)`，counts 按 PR-23 全 4 层 / 16 sub_dim 更新
  （该轨需真实 LLM 环境验证，记录在案）。

### 修复 4 · 冒烟泄漏测试书污染共享 dev 库（测试卫生）

- 视图截图巡检揪出 dev 库 16 本残留测试书（P2冒烟之书 ×4、验收之书 ×4、诊断 ×6 等）
  ＋探针对 tide 档案的不完整还原。smoke-phase2 / smoke-acceptance 补「软删 + 回收站
  彻底清除」清理段（沿用 f2/f3 模式）；api-probe 改为先取原值再完整还原；
  历史残留 15 本已清（「盛有式」来源不明，保留待人工确认）。

### 验证矩阵（全绿）

- 后端全量：**874 passed**（870 基线 + 3 幂等回归 + 1 ingest 回归）。
  alembic current == head（20260612_0052）。
- React 端：build 绿；run-smokes 六套 + f2–f6 + g1/g2/g4/g5 + h1/h2 + acceptance
  18 套全过（修复后 phase2/acceptance 复跑零残留）；15 视图截图零 console 错误；
  空白书 15 视图空态零错误 + 激活作品被外部软删后 UI 正常兜底。
- Vue 端：59 文件 / 536 单测 + smoke ok；Playwright E2E 20 passed + 1 skipped
  （完整 LLM 链路轨，需 LLM 环境）。
- API 边界探针 18 项全过（畸形载荷信封 / 跨项目越权拒绝 / 幂等重放 / 陈旧 revision
  409 / 双重软删 / 超长与 emoji 输入 / 派生卡 resolve 409）。

## AI 模型接入重建(2026-06-12,前后端)

> 决策:① 前后端一起做;② 主流厂商各写原生 adapter(if/elif → 注册表);
> ③ 节点路由呈现 = 简化分工槽位 + 高级矩阵入口。设计稿无此页,属授权新建
> (AISettings 原实现是 localStorage 假偏好,Haiku/Sonnet/Opus 写死三选一)。

### 后端

- **Adapter Registry 重构(零行为变化)**:`services/llm_providers/` 新包
  (base/registry/presets + 12 个 adapter)。llm_client.py 4 个 if/elif 分发点
  (_build_http_request/_build_headers/_extract_output_text/_extract_finish_reason
  + protocol_hint)改为委托 adapter;原 6 家 build/parse 逐字搬入,现有测试
  断言零改动作 golden 锁。SUPPORTED_PROVIDERS / DEFAULT_PROVIDER_BASE_URLS /
  _provider_catalog / base_url 补 /v1 集合 / api_mode 默认值全部改为注册表派生。
- **新原生 adapter ×6**(API 细节均经官方文档核验,2026-06):
  qwen_dashscope(百炼兼容模式;JSON 模式与思考互斥→json_object 时强制
  enable_thinking=false)、moonshot(thinking 只发 enabled 不发 disabled,
  k2.7-code 收 disabled 报错)、minimax(兼容端点无 response_format→省略靠
  解析兜底;max_completion_tokens)、doubao_ark(thinking enabled/disabled;
  无数据面 /models→预设回退)、xai(reasoning_effort none/low/medium/high;
  grok-4.3 现役)、ollama 原生(/api/chat + format json/schema + /api/tags
  列模型 + prompt_eval_count usage 钩子)。第三方中转(OpenRouter/SiliconFlow/
  OneAPI/自定义)走 openai_compatible 预设。
- **预设目录 + 新端点 ×3**:`GET /llm/provider-presets`(公开)、
  `GET /llm/providers/{id}/models`(实时拉取,失败回退预设,source 标记)、
  `POST /llm/role-routes`(分工槽位批量展开)。test_provider/_probe_completion
  改走 adapter 钩子,**顺带修复** anthropic(x-api-key+version)/gemini(?key=)
  探活一直用错 Bearer 的旧 bug。
- **角色分工槽位**:`llm_node_registry.py::ROLE_SLOTS`(写作主力=scene_generation
  +rewrite+snowflake 13 节点 / 审稿质检=quality+evaluation+writer_review+
  deep_review 22 / 提炼整理=reference+style_reference+project 19;恰好覆盖全部
  active 节点)。save_llm_role_routes 用 default_task_config_payload 展开保留
  节点级温度/预算;激活校验仅限触达节点(允许渐进配置);llm_overview 增
  role_slots(含从 node_routes 反推 current,槽内不一致 → mixed)。
- 测试:+35(test_llm_providers_registry 9 / test_llm_client_adapters 11 /
  test_llm_role_routes 11 + system_config 扩展)。**全量 909 passed**。

### 前端(React)

- client.js 增 `apiAdminGet/apiAdminPost`(X-Admin-Token;令牌 LS 键与 Vue
  共享);新 store `ws-ai-providers.jsx`(function-store + subscribe;管理面
  低频写 → 写后重拉,无乐观)。
- `ws-settings-ai.jsx` 重建「设置 → AI 模型」:接入状态条(readiness +
  管理令牌 Row)/ 模型服务卡片(测试连接/设默认/启停/编辑)/ 添加流程
  (预设分组选择 → 预填 base_url → 密钥 → 拉取模型 → 试连 → 保存 →
  缺失路由一键补齐)/ 模型分工三槽位(应用前 confirm 覆写提示)/
  高级路由折叠矩阵(分组+就绪红绿点+补齐按钮)/ AI 行为本地偏好保留。
  ws-settings.jsx 仅余 import 接缝;Section/Row/Toggle/Segmented/usePref 导出复用。
- 冒烟:`smoke-ai-settings.mjs` 入 run-smokes(渲染/预设/免密钥添加/分工
  生效断言 node_routes/补齐幂等/探活失败不崩)。**run-smokes 七套全过**;build 绿。

### 遗留(记录在案)

- 高级路由矩阵当前为只读展示+补齐;逐节点 provider/model 行内编辑与温度/
  预算微调仍在旧 Vue 高级界面(SystemConfigView),按需求再平移。
- 真实厂商 key 的手工验收(Phase 8 序列:presets → 保存真 key → models →
  probe check_completion → role-routes → 触发真实生成节点看 LlmCall 审计)
  待用户提供各家 key 后走查;adapter 形状已有 MockTransport golden 锁。
- minimax/doubao thinking 参数按 2026-06 官方文档实现;厂商如改版,改对应
  adapter 单文件即可。

### 模型接入 · 真实流量优化(2026-06-12,基于 gcli2api 审计数据)

- 依据 dev 库 LlmCall 审计(296 次真实调用)定位三处问题并修复:
  1. **重试零退避**:gcli2api 限流(No capacity)时三连击同一错误,单次调用
     被拖到 290-358s。llm_client 增 `retry_backoff_seconds` 指数退避
     (×0.8-1.2 抖动,封顶 30s,429 优先尊重 Retry-After;默认 0 保测试节奏),
     runner 生产侧默认 1.5s,可由 models 配置 `job_runtime.llm_retry_backoff_seconds` 调。
  2. **裸 KeyError 审计行**(writer_scene_story_diagnosis,16ms 即败):缺路由
     在 llm_enabled=False 分支会绕过引导错误。统一为 LLM_ROUTE_NOT_CONFIGURED
     (原始 KeyError 仍经 original_error 重抛,场景编排契约不变;
     test_scene_generation 两处审计断言随契约更新)。
  3. **根因——运行时配置读取吞 SQLAlchemyError**:sqlite 瞬时锁会让
     load_active_config_payload 返回 None → LLM 被误判未启用。三个 loader
     增 50/150ms 两次重试(持续失败仍安静兜底)。
- 测试:+5(退避×3 / 瞬时重试×1 / runner 退避配置×1)。**全量 914 passed**。
- 实机验证(dev 8000 + gcli2api):probe 连接 257ms + 48 模型 + 最小生成通过;
  GET providers/gcli2api/models 实时拉取 source=live 442ms。

### CI 回归保护加固(2026-06-24,项目状态审计后修复唯一 high)

审计发现唯一高危:**React 生产前端在自动 CI 中零回归保护**——`.github/workflows/ci.yml`
前端 job 仍指向 legacy Vue,`run-smokes.mjs` 契约 E2E 游离在所有 lane 之外,
单测仅 WsWorks 1 文件 2 用例。四条工作流闭合:

- **WS1 · GitHub CI 门禁**:ci.yml 三 job——Backend Tests / **Frontend Tests (React mainline)**
  (`frontend-react`:`npm ci`→vitest→build,authoritative gate)/ Legacy Vue Frontend Tests
  (覆盖不丢失,Vue 降级为独立 job)。
- **WS3 · store 单测扩面**:新增 `src/test-helpers.js`(按 URL 路由的 mock client 底座)+
  `ws-catalog.test.jsx`(WsCatalog 乐观写穿/PATCH 失败 catRecover 回滚 + WsTrashStore 恢复/失败刷新)/
  `ws-review.test.jsx`(rvPush/rvMarkResolved 乐观移除/resolve 失败告警)/
  `lf7-bridge.test.jsx`(ruleCanon 乐观锁定 + adjudicate 失败重拉回滚)。**用例 2→11,全绿**。
  **变异抽检**(有牙证明):临时打断 catRecover 告警/重拉 与 ruleCanon 乐观行,
  正好对应 3 个用例转红、其余 8 个不变,随后精确还原复绿。
  **稳定性加固**(对抗式复核发现初版在 CPU 负载下 flaky 后):失败回滚断言原本断
  "又拉了一次 apiGet",但 store 的 catFetch/lf7Fetch/trashFetch 带 in-flight 去重
  (并发时复用旧 promise、不再发请求),叠加默认 waitFor 1000ms 过紧 → 负载下间歇红。
  改为断「可观测结果」(标题被服务端原值覆盖 / isRuled 翻回 open / alert 触发,对去重免疫)
  + 加载阶段显式等 active 切到真实 id + 所有 waitFor 给足 5s。复测 **10 次顺序 + 4×2 并发抢 CPU
  共 18 次全绿、0 flake**;变异抽检在重写后断言上重做仍如期转红。
- **WS2 · E2E lane 接线**:新增 `scripts/verify_react_e2e.ps1`——隔离 e2e sqlite
  (`.codex-run/e2e/`,不碰 dev 库)+ alembic upgrade head + 起 :8009 seeded 后端 +
  :5174 React + 跑 run-smokes(七套逐套 reseed)+ 整树拆台,接进 `verify_release.ps1`
  默认门禁(消掉原 "follow-up" 注释)。**七套 smoke 全过**。
  额外发现并就地处理一个坑:**全新 `alembic upgrade head` 会被迁移 `20260523_0036`
  的 legacy-backup 门禁(`_assert_backup_present`)拦下**(dev 库当年带数据迁过、CI pytest 走
  create_all 都绕开了它);e2e lane 用该迁移自带的 `STYLE_REFERENCE_REPO_ROOT` 测试覆盖口
  指向占位 backup 满足之。
- **WS4 · 文档同步**:CLAUDE.md(CI/release lane 描述 + Contract-level E2E 接线 + 迁移门禁
  gotcha + store 单测约定)、release-checklist(三 job + React 契约 E2E 门禁)、本账本。
- 脚本编码注意:Windows PowerShell 5.1 按系统 ANSI 读无 BOM 的 .ps1,中文注释会撑坏解析
  ——`verify_react_e2e.ps1` 保持纯 ASCII 注释。

### 2026-06-25 健康审计当前态刷新

> 本小节为追加的「当前态快照」,不改写上方任何历史段落(各 Phase / F / G / H /
> AI 模型接入段里的 passed 数与 alembic head 均为**当时**快照,一律保留)。
> 换会话续工以本小节为最新真相基线。背景:此前账本最新的「当前态总规模」
> 只记到 2026-06-12(914 passed / head 20260612_0052)+ 2026-06-24 的 CI 加固段,
> 落后于实跑真相;本次健康审计实跑后补记。

- **后端全量**:`cd backend; python -m pytest -m "not chroma_integration" -q`
  实跑 **1260 passed / 0 failed / 3 skipped / 17 deselected**(372s,0 失败)。
  (3 skipped = Windows 自动跳过项;17 deselected = `chroma_integration` 标记。)
- **Schema 漂移守门**:`tests/test_metadata_isolation.py` 4 passed(含
  `test_migration_built_schema_matches_orm_models`);ORM `create_all` 与
  Alembic `upgrade head` 在表/列/命名索引层面**零漂移**。
- **Alembic**:单头 **20260618_0059**,`current == head`,无分叉
  (上一处当前态记录停在 0052;此后 finding-feedback 迁移链 0058/0059 已推进
  head,本小节补记)。
- **React 主线**:`frontend-react` vitest **8 文件 / 37 用例全绿**;
  `vite build` 成功(94 模块,gzip JS≈358KB)。
- **Git 在途**:分支 `feat/fe-react-quality-longform-fixes` 领先 `origin/main`
  **7**(main 在 origin/main 基础上 +4、本分支再 +3,即分支比 main 多 **3** 个提交),
  落后 0,工作树干净。核心工作(质量地板 / AI 设置 / 风格参考深层页 / CI 门禁)
  已落 main 但**未 push**——属单点丢失风险,待推送备份。

#### 修复轮(2026-06-25,本次健康审计后)

按「安全可验证优先」分阶段执行,各阶段独立提交、独立验收:
- **P1 账本刷新**(本段)—— 追加当前态小节,不改历史快照。✅
- **P2 D13 控制塔「违约裁定」接真** —— 按 `library_derive` 范式加
  `chapter_audit_adjudicate` 三件套 + 仿 `LibraryDeriveService` 的裁定服务 +
  幂等路由;前端 `lf7-bridge.drifted` 接后端 violations、`lf6-app`
  `fixDrift/archiveNew` 去 `d1/d2/n1/n3` 字面量。验收=LLM 关诚实降级(drifted
  留空 + author_action)+ mock LLM 落 `ChapterAuditFinding`/`ReviewItem` +
  store 单测 + `test_longform_tower` 全绿。
- **P3 非 tide 结构层确定性派生真化** —— 后端把 `ForeshadowTracker` /
  `SnowflakeScenePlan`(tension_target / onstage / causal_prerequisite)纯规则
  投影进 `LongformAnchor` / `ChapterAuditFinding`,接 materialize/archive 钩子;
  前端去 5 处 `!=="tide"` 清空门控改「后端有则显示、无则引导态」。
  验收=新建非 tide 作品 materialize 后控制塔真实投影 + 派生函数单测,**0 LLM**。
- **P4 推送备份** —— push `feat/fe-react-quality-longform-fixes`(含全部提交,
  不动 origin/main),消单点丢失高危。
- **P5 bundle 分包**(不做,仅记录)—— 勘察判定:48 个 window 注册模块靠
  main.jsx 有序加载 + ws-app 殿后维持加载序(T3 陷阱),激进 `manualChunks`
  破坏跨 chunk 求值序、投入产出比为负;client.js import 形态统一仅消警告无
  性能收益却要碰 ws-writer/ws-styleref 十余处。保持默认配置不动。

##### 修复轮收口(2026-06-25)

- **P1** ✅ `830c8f1` 账本刷新(本节)。
- **P2** ✅ `ac8ce55` D13 控制塔违约裁定接真 + 诚实降级(三件套 chapter_audit_adjudicate
  + LongformTowerService.adjudicate_draft + 幂等路由 audit/adjudicate-draft + 前端
  Lf7Bridge.adjudicateDraft 桥 / lf6 beginAudit 接缝 + fixDrift 真 finding_id / DemoTag)。
- **P3** ✅ 非 tide 结构层确定性派生:`LongformTowerService.derive_structure`
  (雪花 SnowflakeScenePlan → thread 角色出场区段[连续章号合并 segs] / promise 显式
  伏笔·下游义务,确定性幂等、0 LLM)+ 幂等路由 derive-structure + 前端 lf2DeriveStructure
  桥(lf6 挂载对非 tide 自动派生再水合,tide 保持 seed)。**范围克制**:只投影高置信映射;
  断链(causal_break)/空降(unplanted_reveal)/张力曲线/人物弧线等推断性或更重的派生**未做**,
  记为后续(需真实数据校准,避免无数据时产假阳性,守项目诚实纪律)。
- **P4** ✅ 推送备份:`feat/fe-react-quality-longform-fixes` 已 push origin(含全部提交,
  不动 origin/main)。
- **P5** ❌ bundle 分包不做(仅记录,见上)。
- **验收**:后端全量 `pytest -m "not chroma_integration"` = **1264 passed** / 0 failed /
  3 skipped / 17 deselected;React vitest 8 文件 / **39 用例** + `vite build` 绿;
  schema 漂移守门 4 passed + alembic 单头 20260618_0059 不变。
- **后续(本轮明确不做)**:① D13 / 派生的真实 LLM 端到端验收(本环境 LLM 不可用);
  ② P3 低置信派生(断链 / 空降 / 张力 / 弧线)接真 + 真实数据校准;③ 非 tide 作品的
  审计层(lf3 `LF3_AUDIT.drifted`)与结构提示层(`LF2_RISKS`)的进一步真化。

##### 雪花 AI 融合轮（2026-07-06,AI 融合 F1）

- **痛点**:构思视图的 AI 只有 fe-candidates 一个口——上下文是前端折叠的
  180 字/步有损文本,产物是纯文本候选,采纳只写自由草稿(`setDraft`),8/10 步的
  后端规范字段全靠脚手架派生 → AI 产物对完备性闸门/health/物化零贡献;后端
  真·结构化生成 `steps/{key}/generate`(每步专用模板+权威上游+压力诊断)与
  assistant / scene-triage-suggest 全未接线,「AI 生成不贴合雪花系统、生硬、孤立」。
- **B1 候选缺口导向** ✅ `fe_step_candidates` 服务端自组上下文:`approved_steps`
  (已批上游规范草稿)+ `current_canonical_draft` + `pressure_rubric` +
  `current_pressure_diagnosis` 入提示;前端折叠文本降级 `fe_local_context` 补充。
  模板 `snowflake_step_candidates` 升 2026-07-06.v3(至少一条候选修最弱缺口)。
- **B2 提示净化** ✅ `_sanitize_canonical_draft`:generate/candidates/assistant/triage
  的提示上下文剥 `fe_*` 写穿键(脚手架 JSON/状态/历史账本不再吃 token 预算),
  作者自由草稿以 `author_free_draft` 显式保留。
- **B3 采纳方向通道** ✅ `generate_step` 接 `direction_text`(采纳候选正文 →
  prompt `adopted_direction` + how_to_use 蓝本指令)与 `require_llm`(LLM 未启用
  409 SNOWFLAKE_LLM_REQUIRED,绝不静默落启发式版本)。
- **F1 采纳并结构化** ✅ ws-snow 候选双动作:AI 候选主按钮「采纳并结构化」走
  generate → 回包经 `SnowSync.applyServerStep` 反推脚手架(`feFromCanon`)+
  权威 health 即时刷新 + 留底可回滚;次按钮「仅作草稿」保留旧行为。编辑区死按钮
  (让 AI 续写/再生 3 条/让句子更短/挑明动机)收敛为一个真按钮「让 AI 生成候选」。
- **F2 规范字段保真合并** ✅ ws-snow-sync 新增 canon 镜像(hydrate/PATCH 回包/
  applyServerStep 刷新)+ `mergeCanon` 深合并:上行 PATCH 在服务端规范草稿之上
  合并脚手架派生字段——对象缺席键幸存(角色圣经四维等富字段不再被剪)、数组按
  character_id/row_uid 对位继承、FE 标量作者主权。附带修复 backstory synopsis
  前缀行往返拆解;audience 补「期待读者情绪」表单(此前 BE 必填字段前端无框可填)。
- **验收**:后端新增 3 用例(权威上下文入提示+fe_*不泄漏 / adopted_direction 入
  提示 / require_llm 409)全绿,雪花+prompt 相关 8 文件 95 passed;React vitest
  新增 ws-snow-sync.test.jsx 4 用例,全套 **10 文件 58 用例** + `vite build` 绿;
  隔离后端(:8010 + mock LLM :8111)真实链路冒烟:候选 3 条缺口导向、结构化采纳
  落 summary + health 88、提示含 approved_steps/诊断/adopted_direction、无 fe_* 泄漏。
- **后续(本轮明确不做)**:① assistant(驻场教练)与 scene-triage/suggest 的
  React 接线(后端能力已在,继续候补);② steps history/restore、accept-stale、
  resync 的前端面;③ backstory 散文型 synopsis 的字段级拆分(现整段进「信念」框)。

##### 雪花 AI 融合轮·二(2026-07-06,结构化残缺根治)

- **根因**:7-04 提示词优化批把 6 个生成模板的键名写脱离了后端契约——模板教模型
  输出 `entry_point/wound/value_conflict/core_line/result_or_change` 等游离键,而
  `_sanitize_character_items`/`_sanitize_scene_list_items` 只保留编辑器模板键 →
  清洗后只剩人名/类型,「采纳并结构化」落库即残缺。scene_details 部分错位
  (未点名 title/exit_change/hook),long_synopsis 让模型回散文段落而前端大纲表
  按「NN 章名：摘要」行解析 → 章表切碎。
- **修复三件套**:
  ① 6 模板重写升 2026-07-06.v3(sheets/synopses/bibles/scene_list/scene_details/
  long_synopsis):键名逐一对齐编辑器模板并显式警告「契约外键会被服务端丢弃」,
  保留 7-04 批编辑学指导(把 wound/contradiction/visible_behavior 等映射进
  worst_memory/self_image↔public_image/appearance-style 等规范字段);synopses 的
  synopsis 规定为 信念/旧伤/欲望/恐惧/关系 五前缀行(前端解析器上一轮已备);
  long_synopsis 改三幕段落×「NN 章名：因果一句（灾N）」章行格式,12-20 章。
  ② `generate_step` 空字段定向重试(1 次):`_collect_generation_gaps` 按编辑器
  模板对集合项逐字段下钻(嵌套档案维度整块全空计缺),非空则带 `completeness_repair`
  (空字段清单+「契约外键会被丢弃」提醒)重试,仅当更完整才采用,失败保留首版。
  ③ 契约守卫测试:从编辑器模板派生键名清单断言各模板 task_prompt 全部提及
  (服务端指派键豁免),并显式禁止 8 个历史游离键回流;另有 gaps 下钻单测与
  重试行为测试(缺→补齐、首轮完整只调一次)。
- **验收**:test_snowflake_fe_candidates 10 passed;雪花+prompt 全家 84 passed;
  export_prompt_handoff 对账通过(fe-candidates/generate 注释同步更新)。隔离后端
  (:8010+mock :8111)复演:synopses 五前缀行落满、scene_list 内容键全非空+服务端
  指派 scene_id、bibles 首轮故意回放游离键→触发 completeness_repair 重试→四维度
  全部救回(LLM 调用 2 次,重试提示点名空维度)。
- **后续**:① bibles 部分残缺(维度内个别子字段空)不触发重试——按「整块全空」
  阈值设计,若实际使用仍见零星空洞可降阈值;② 弱模型若两轮都残缺则保留更完整的
  一版,前端健康分/缺字段清单会如实亮红,作者可再点重新生成。

##### 雪花 AI 融合轮·三(2026-07-06,9/10 步场景 AI 工具面)

- **痛点**:场景列表(09)/场景规划(10)是全流程手工量最大的两步——候选(3 条短文本)
  对表格步几乎无用,后端专为它们准备的场景分诊(scene-triage/suggest+repair_patch)
  一直没接前端,逐场 GCS/RDD 只能手填。
- **B1 单场定向生成** ✅ generate(scene_details) 接 `focus_scene_refs`(row_uid/
  scene_id 皆可指):焦点场注入 prompt `focus_scenes`+只输出焦点场指令,清洗器按
  scene_id 合并;**关键修复**——焦点模式合并底稿改用「当前最新草稿(剥 fe_*)」,
  默认底稿是 scene_list 重播种骨架,会把焦点外场景的既有深化整体盖掉
  (`_normalize_full_step_output` 增 `base_override`);修复重试的缺口过滤到焦点场;
  指错场景 409 SNOWFLAKE_FOCUS_SCENE_NOT_FOUND。分诊条目补 `row_uid`(FE 规划以
  row_uid 为键,此前只有 scene_id 对不上位)。
- **F1 前端工具面** ✅ ws-snow:adoptStructured 泛化为 `structuredGenerate`
  (direction/focus/focusRow 单场时只回写焦点场规划,防未上行编辑被盖);
  09 统计栏「AI 生成整表」(非空表 confirm+留底);10 工具栏「AI 分诊」
  (draft_override=SnowSync.canonDraft 免自动保存竞态;byRow 按 row_uid 索引)+
  「AI 补全所有场景」;逐场:导航格分诊色条(tri-pass/maybe/rewrite)+选中场分诊卡
  (状态/评分/诊断/修复步骤+「应用修复补丁」——GCS/RDD 进 10 的 plans,坩埚/摘要/
  地点回写 09 场景行,均留底可回滚)+「AI 补全这一场」。
- **验收**:后端新增 2 用例(focus 只改焦点场+焦外保留+提示含指令+缺口不误触重试+
  指错 409;分诊条目带 row_uid)→ test_snowflake_fe_candidates **12 passed**;雪花
  回归 57 passed;React build+vitest 54 passed;隔离后端冒烟:全量深化两场齐全 →
  分诊(pass/maybe+row_uid+补丁)→ 单场定向只改 S2 的两难、S1 原样保留、health 随
  回包刷新。export_prompt_handoff 对账通过(generate 单元注释补 focus/repair 键)。
- **后续**:① 分诊结果尚未落 SnowflakeSceneTriageItem(FE 本地应用补丁→autosave
  写穿,物化闸门的 triage_items 走的是后端 suggest 时的即时诊断;若要「重写场硬闸」
  需接 save_scene_triage);② assistant 驻场教练(带 focus_scene_id 单场辅导)仍候补;
  ③ 09 的整表生成是整体替换语义,「只补空行」的增量模式未做。

##### 雪花 AI 融合轮·四(2026-07-06,驻场教练 + 分诊闸门落库)

- **F1 教练 tab** ✅ ws-snow 新增第 5 个 tab「教练」:接后端
  `snowflake_workspace_assistant`(回合 SnowflakeAssistantTurn 持久化,workspace
  回包带 assistant_history → 进页懒加载,跨会话可见)。发送带 draft_override
  (SnowSync.canonDraft 免自动保存竞态);第 10 步自动以当前选中场聚焦
  (`_focus_scene_payload` 兼容 row_uid/scene_id);带 candidate_patch 的回合
  (含历史回合)可一键「应用补丁」。快捷提问 3 条,LLM 未启用退规则建议并明示。
- **F2 咨询式补丁合并** ✅ ws-snow-sync 新增 `applyCanonPatch`(+SnowSync 暴露):
  与 mergeCanon 的「FE 主权」语义相反——补丁是建议:空值不清空既有内容、数组按
  character_id/row_uid 对位合并、不删补丁未提到的成员(新成员追加);底稿取
  「canon 镜像 ⊕ 当前脚手架」。应用前留底可回滚,仅当回合 step_key=当前步。
- **F3 分诊落库** ✅ runTriage 在 suggest 后自动 `save_scene_triage` 存推荐态
  (不写 manual_status,作者主权保留);会话内记 triage_id 复用防堆行(后端 save
  无 id 会新建行,_triage_items 按 scene_plan_id 取最新);存档后 SnowSync.refetch
  刷新 ready 标志。**闸门语义**:rewrite 场存档后 materialize 主路径 409
  SNOWFLAKE_TRIAGE_BLOCKED;FE adoptOutline 在 ready=false 时本就走目录批量建章
  兜底(既有设计),真物化管线则被真实拦住。
- **验收**:后端 +3 用例(_focus_scene_payload row_uid / assistant 回复+历史持久化
  +workspace 带历史 / save 带 triage_id 复诊不堆行且无 manual 态)→
  test_snowflake_fe_candidates **15 passed**,雪花回归 52 passed;FE +1 用例
  (applyCanonPatch 三条语义)→ vitest **55 passed** + build 绿;隔离后端冒烟:
  教练回复+建议+expected_reader_emotion 补丁+历史 1 条 → 分诊存档 pass/rewrite
  带 triage_id → materialize 409 SNOWFLAKE_TRIAGE_BLOCKED。handoff 对账通过
  (assistant 单元注释补 React 接线)。
- **后续**:① 教练补丁对 scene_details 的 focus 场景可以更细(现按整步补丁对位);
  ② 分诊人工裁定(manual_status 覆盖推荐态)的 UI 未做——作者想强行放行 rewrite
  场时需要;③ 09 整表「只补空行」增量模式仍未做(单场补全已覆盖大半场景)。

##### 贯通轮(2026-07-07,雪花产物 ↔ 写作台/AI 起草台的四条缝)

背景:用户反馈「雪花生成的章节/场景孤立,写作台、AI 起草、场景工作台各自为战」。
核对结论:主链路(物化→目录→写作/起草)本通,断点在回流、降级通道、动线、起草台本地态四处。

- **G1 resync 回流补接(React 主线此前完全没接)** ✅ ws-snow-sync:hydrate 捕获
  workspace 回包 `resync_status`(新 `ws:snow-resync` 事件),SnowSync 暴露
  `resyncStatus()/resync()`(POST /resync 空 body 全量;回包自带 workspace 就地刷新
  + WsCatalog.__refresh 重拉目录);9/10 步 PATCH 上行后若目录非空**强制重拉工作台**,
  横幅数字实时跟上(hydrate 的 _t 比较保证本地新草稿不被覆盖)。ws-snow 构思页
  strip 下新增回流横幅(「构思已更新·N 场待同步」+一键「同步到目录」)。
  **后端假阳性根修**:物化与 resync 对 writer_brief_json 的出处/富化键写法天生不同
  (source=snowflake_method+outline_plan_id vs snowflake_resync+scene_plan_id+
  primary_form+chapter_goal),_scene_card_diff 整体 != 导致**刚物化完就报全场待同步**;
  改 `_writer_brief_comparable` 只比 7 个戏剧内容键(crucible+GCS+RDD,空串=缺席)。
  注意:scene_goal 列=plan.summary 优先,只改 plan.goal 时 diff 落在 brief 而非列。
- **G2 物化降级不再丢场** ✅ WsCatalog.adoptOutline:ready=false 时优先
  window.s2Materialize.preview/apply(章+场按脊柱锚点直建、带 GCS/RDD 三拍),
  仅预览不 ok(09 无场)才落 __adoptByDiff 空壳章;07 采用按钮 confirm 明示
  「主路径落库 / 降级直建」哪条通道。
- **G3 动线补齐** ✅ 07 并入成功后新增「去 AI 起草」(已规划 todo 场批量入列,
  __scnEnqueue 支持 {sids:[…]},ws-scene init 数组消化);写作台 WrCtxScene 的
  GMC 区块下新增「交给 AI 起草整场」(单场入列惯用法同 ws-author forkAI,
  目录场存在才显示)。
- **G4 起草台后端水合** ✅ ws-scene-run 新增 `scnHydrateFromBackend(sid)`:
  GET /scenes/{id}/workbench 的 final/style/neutral 产出 → 本地复检(scnQC)
  → ready(目录场 done → archived)运行对象;挂载时对无本地 scn-run 记录的
  队列项异步水合,enqueueSid 同样兜底;setRuns 有记录不覆盖。
- **验收**:FE vitest 60 passed(+5 新用例:resync 契约 2 + adoptOutline 降级 3)
  + build 绿;后端新守卫 `test_snowflake_resync_fe_flow.py`(FE 调用序列端到端:
  PATCH 步骤→pending=1→空 body resync→清零+brief 换新,含「刚物化完 pending=0」
  假阳性回归)+ test_snowflake_workspace_v2 31 passed + fe_candidates 19 passed。
- **后续**:① 起草台队列 membership 仍是 localStorage(运行态已可恢复,队列本身
  换浏览器会空);② 控制塔「下游交付」仍走本地引擎,ready 时未切 materialize 主路径;
  ③ 09 步「采用到当前章」的堆一章语义未动(07 已是主入口);④ blocked 稿与待办
  收件箱的互通未做。

##### 贯通轮二(2026-07-08,收掉上轮遗留 ①②④)

背景:上轮「后续」四项中用户指示推进三项(①队列成员 localStorage、②控制塔
下游交付未切主路径、④blocked 稿与收件箱不互通;③09 堆一章语义维持现状)。

- **H1 起草台队列成员后端化(遗留①)** ✅ 后端新端点
  `GET /api/v1/scene-run-states?project_id=`(routes/scenes.py):项目内
  SceneRunState ⋈ 非回收 SceneCard,只返回离开过 ready 的场(=进过管线),
  按 updated_at 倒序。FE `scnBackendQueueSids()`(ws-scene-run):run-states
  → 目录 backendId→sid 对位(目录空则先 __refresh);ws-scene 挂载新 effect
  把派生 sid 并入队列(本地在前、恢复在后,scnQueueSave 落缓存),新并入场
  经 scnHydrateFromBackend 恢复运行态。localStorage 队列自此退化为管线
  真相的读缓存——换浏览器队列成员+运行态都能恢复。
- **H2 控制塔下游交付接物化主路径(遗留②)** ✅ ct-panels CTDownstream:
  `SnowSync.readyToMaterialize()` 时 writeIn 走 `SnowSync.materialize()`
  (与 adoptOutline 同语义,confirm 明示主路径),按钮/横幅文案跟随;未就绪
  降级本地 s2Materialize 时 confirm 注明「降级为目录直建」。门槛区新增
  主路径就绪 pill;本地预览不可用但后端闸门已过时(换浏览器冷启动)另有
  主路径直达面板。监听 ws:snow-hydrated 让就绪标志随水合刷新。
- **H3 管线 blocked 稿 ↔ 待办收件箱(遗留④)** ✅ review_derived 新增
  `_pipeline_blocked`:SceneRunState 处于 7 个「等人拍板」态(human_review_
  required/critical_scene_human_gate/near_final_revision_required/hard_qc_
  partial|full_rewrite_required/soft_qc_patch_required/needs_replan)且目录场
  未 done(作者主权)→ live decision 卡(priority 1,指纹=scene_status,状态
  变化即复浮);动作 nav_to="scene"+nav_scene=slug。ws-review act() 新增起草台
  深链:__scnEnqueue={sid}+ws:scene-enqueue 事件(与 forkAI 同源惯用法;
  go("scene") 自动切高级模式)。
- **验收**:后端 test_scene_run_jobs(+run-states 列表用例)+test_review_cards
  (+blocked 卡生命周期:出卡/换指纹复浮/done 或 archived 消失)13 passed;
  FE vitest 63 passed(+3:ws-scene-run.test.jsx 派生对位/空目录补拉/失败兜底)
  + build 绿;后端全量(not chroma)见当轮记录。
- **未动**:③09 步「采用到当前章」堆一章语义(07 已是主入口,维持);
  run-states 端点未纳入 openapi 契约测试(项目无此惯例)。
