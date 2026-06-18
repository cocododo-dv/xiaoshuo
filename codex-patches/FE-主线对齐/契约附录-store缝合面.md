# 契约附录 · 前端 store 缝合面（视图层依赖的不可变接口）

> 改造的铁律：**视图文件零修改**。下面每个 store 的公开方法签名、返回形状、订阅语义、
> 触发的全局事件，改造后必须逐一保持。内部实现（localStorage → API）随便换。
> 本表抄自 `design/` 实际代码，开工时若发现遗漏以 `design/` 为准。

## 通用模式

- 订阅：每个 store 暴露 `subscribe(fn) → unsubscribe`，任何变更后同步调用全部订阅者。
- 全局事件（视图监听，不能丢）：`ws:work-changed`（detail=workId）、`ws:review-changed`、`lf:bridge-changed`。
- 命名空间：`wsKey(base) → base + "::" + activeWorkId`。接 API 后该函数保留（仍有 UI 偏好键在用），但**业务数据不再经过它**。
- 改造后每个写方法 = 乐观更新本地缓存 → 调 API（带幂等键）→ 失败回滚 + toast（沿用 `ApiRequestError` 的 message）。

## WsWorks（`design/ws-works.jsx`）

| 方法 | 语义 | 对接（Phase 2/4） |
|---|---|---|
| `list()` | 全部作品数组 | `GET /api/v1/projects`（+profile 扩展字段） |
| `active()` / `activeId()` | 当前作品 / id | 当前 id 仍存 localStorage（UI 状态） |
| `setActive(id)` | 切换并广播 `ws:work-changed` | 不变 |
| `create(data)` | `{title, genre, sub, wordsTarget, accent}` → 新作品并激活 | `POST /api/v1/projects` + profile |
| `update(id, patch)` | 局部字段更新 | `PATCH` profile；**字数/进度类字段改为只读派生，前端不再回写**（见 WsCatalog） |
| `remove(id)` | 整部进回收站 | P4 软删端点；删除「种子不可删」限制 |
| `restoreWork(w, keys)` | 从回收站整体恢复 | P4 restore 端点（`keys` 参数随 localStorage 时代消亡，签名保留、忽略） |
| `isSeed(id)` | 种子判定 | demo seed 项目由后端标记 `is_demo` |
| hooks | `useActiveWork()` / `useWorks()` | 不变 |

**作品对象形状**（视图直接读这些字段，响应适配层必须凑齐）：
`{id, title, genre, mark, accent(crimson|gold|sage|slate), sub, greet, wordsTotal, wordsTarget, chaptersWritten, chaptersTotal, wordsToday, wordsTargetDay, streak, home:{…}}`
（`home` 由 dashboard 端点供给，见 Phase 2；`greet` 前端按时段生成即可，不必入库。）

## WsCatalog（`design/ws-catalog.jsx`）

| 方法 | 语义 | 对接（Phase 3） |
|---|---|---|
| `get()` | 当前作品章节数组（同步！见下「同步性」） | 内存缓存，由 API 填充 |
| `isEmpty()` | 是否空目录 | 同上 |
| `set(next)` | 整树替换 + 持久化 + 汇总回写 + 通知 | 拆解为细粒度 PATCH（store 内部 diff 或改写各调用点所用的高层方法） |
| `reset()` | 回种子 | 仅 demo 项目保留；真实项目隐藏入口 |
| `sceneById(sid)` | `{chapter, scene, index}`，sid 形如 `ch08s3` | API 响应带 `slug` 字段映射 |
| `currentChapter()` / `writingScene()` | 当前在写章/场 | 派生自缓存 |
| `renameScene(chId, sid, title)` / `moveScene(chId, from, to)` / `addScene(chId, title)` / `removeScene(chId, sid)` / `restoreScene(chId, scene, index)` | 写作器结构操作 | 各对应 catalog 子端点；remove 走 P4 软删 |
| `addChapter(title)` | 建章并立为在写章 | `POST catalog/chapters` |
| `adoptOutline(list)` | 雪花第 7 步大纲 → 目录（去重、空目录首章立写）；`list=[{id,act,title,summary,spine}]` | **改为调用既有物化管线**（snowflake materialize / outline-plan approve），不在前端造章 |
| `recordSceneWords(sid, count, prev)` | 字数回写链 | **删除前端回写**：保存正文后由后端 rollup，store 刷新即可（方法保留为触发刷新的空壳） |
| `totals()` | `{words, written, planned, approved, today}` | 读 writing-stats + catalog 汇总 |
| hook | `useCatalogChapters()`（同时监听 `ws:work-changed`） | 不变 |

**章节对象形状**：`{id, act, n, title, state(planned|todo|writing|draft|review|approved), tension(0..1), pov, time, place, current?, words:{cur,target}, entry, exit, align, promise, drama:{promise,spine,arc,problem,aftertaste,ending,forbidden,notes}, threads:[{name,role}], scenes:[…]}`
**场景对象形状**：`{sid, title, kind(主动|反应), state(todo|writing|done), words?, goal, obstacle, turn}`
→ C4 裁决：API 按 kind 返回 GCS 或 RDD；适配层把 RDD 映射到 `goal/obstacle/turn` 槽位并带 `kindFields` 标签，视图后续微调标签文案（这是唯一允许的视图改动）。

**同步性陷阱**：`get()` 是同步的，视图在 render 里直接调。改造 = 模块加载时拉一次 API 进缓存、写后失效重拉；`get()` 永远即时返回缓存（可能短暂为空数组 + `catReady` 状态）。

## WsTrashStore（`design/ws-catalog.jsx` 后半）

| 方法 | 语义 | 对接（Phase 4） |
|---|---|---|
| `list()` | 全局桶（整部作品）+ 当前作品桶合并，按删除时间倒序 | `GET /api/v2/trash?project_id=…` + 全局段 |
| `push(item)` | `{kind, title, payload}` 入箱 | 由各软删端点自动产生，`push` 退化为兼容壳 |
| `restore(id)` / `purge(id)` / `clear()` | 恢复 / 永久删 / 清空 | 对应端点 |

条目形状：`{id, kind("作品"|"场景"|…), title, removedAt, payload}`。

## 待办 store（`design/ws-review.jsx`）

| 方法 | 语义 | 对接（Phase 5） |
|---|---|---|
| `rvPush(item)` | 各模块投递待办卡 | `POST /api/v1/review-items`（升级后的卡片模型 + `dedupe_key`） |
| `rvOpenItems()` | 未处理项（priority 1 置顶） | `GET /api/v1/review-items?state=open` |
| `rvSnoozedList()` / `rvMarkSnoozed(id)` / `rvUnsnooze(id)` | 稍后队列 | snooze 端点 |
| `rvMarkResolved(ids)` / `rvUnresolve(ids)` / `rvIsResolved(id)` | 处理/撤销（含「今日已处理 N 件」计数） | resolve 端点（**effect 后端事务执行**）；unresolve = 撤销最近 resolve |
| `rvBadge()` / `useReviewBadge()` | 徽标 = priority 1 的未处理数 | badge 端点或 open 列表派生 |
| `rvDerived()` | ⚠️ **实时派生项**：直接从工作台真相（雪花空缺/起草队列/目录异常）算出；`live:true` 不可无动作划掉，修好自动消失；id 带内容指纹，状况变化后即使曾 snooze 也重新浮现 | 后端在 GET 时同步计算（纯读），或定时物化——**语义三条必须保留：不可划掉 / 自动消失 / 指纹复浮** |

卡片形状（视图渲染依赖）：`{id, kind(decision|risk|qc|idea|note), priority(1|2|3), title, where, source, time, detail, preview?:{before,after}, checklist?:[], options?:[], live?, actions:[{label, intent(primary|ghost|quiet), op(resolve|nav|snooze), to?, step?, effect?}]}`。

## Lf7Bridge（`design/lf7-bridge.jsx`）

| 方法 | 语义 | 对接（Phase 7） |
|---|---|---|
| `ruleCanon(id, value)` / `isRuled(id)` / `ruled()` | 设定裁决（塔与待办同源，任一侧裁决另一侧消失） | `POST longform/audit/{finding_id}/adjudicate`；待办卡 resolve 的 effect=`rule_canon` 调同一服务 |
| `addCanonConflict(entry)` / `extraCanon()` | 归档时发现的新冲突登记 | audit 创建端点 |
| `onceTask(key, payload)` | 同一事项只投递一次待办 | ReviewItem `dedupe_key` 唯一索引 |
| `isArchived(ch)` / `markArchived(ch)` | 归档登记 | 归档端点完成时写目录状态（写回链后端化） |
| `resetLoop9()` | 演示循环复位 | **不移植**；等价能力 = `reset_author_state` 工具 |

## WsDemoTag（`design/ws-catalog.jsx` 末尾）

视图接通真实 API 后删除该视图里的 `<WsDemoTag />`；未接通的必须保留。全部摘除是 Phase 8 验收项之一。

## WsAiProviders（`frontend-react/src/ws-ai-providers.jsx`，模型接入重建新增）

> 注:AISettings 原型实现是 localStorage 假偏好,经授权整体重建为真实接入面;
> 视图层 = `ws-settings-ai.jsx`(设置 → AI 模型),`ws-settings.jsx` 仅余一行 import 接缝。

| 方法 | 语义 | 对接 |
|---|---|---|
| `subscribe(fn)` / `state()` / `useAiProviders()` | 订阅 + 状态快照(loading/overview/presets/busy/probes/adminConfigured) | — |
| `refresh()` | 拉 overview(providers/node_routes/role_slots/readiness/missing_active_routes) | `GET /api/v1/system-config/llm` + `GET /api/v1/system-config`(runtime.admin_configured) |
| `loadPresets()` | 厂商预设目录(国内/国际/中转/本地/自定义 分组) | `GET /api/v1/system-config/llm/provider-presets`(新增,公开) |
| `saveProvider(payload)` | 新增/编辑模型服务(upsert;写后重拉,无乐观) | `POST /api/v1/system-config/llm/providers`(admin) |
| `setDefault(id)` / `probe(id, extra)` | 默认服务 / 连接测试(结果留 probes[id]) | `…/providers/{id}/default`、`…/providers/{id}/probe`(admin) |
| `fetchModels(id)` | 实时拉模型列表,失败回退预设(`source: live\|preset`) | `GET /api/v1/system-config/llm/providers/{id}/models`(新增,admin) |
| `testDraft(payload)` | 保存前草稿试连/拉模型(添加流程) | `POST /api/v1/system-config/test-provider`(admin) |
| `saveRoleRoutes(assignments, activate)` | 分工槽位(写作主力/审稿质检/提炼整理)按组批量展开节点路由;激活校验仅限触达节点(渐进配置) | `POST /api/v1/system-config/llm/role-routes`(新增,admin) |
| `saveNodeRoutes(payload)` / `syncMissing(payload)` | 高级路由整表 / 一键补齐缺失 | `…/llm/node-routes`、`…/llm/node-routes/sync-missing`(admin) |
| `setAdminToken(v)` / `adminToken()` | 管理令牌(与 Vue 高级界面共享 LS 键 `novel-system-admin-token`) | 经 client.js 新增 `apiAdminGet/apiAdminPost` 注入 `X-Admin-Token` |

后端适配层:`services/llm_providers/`(adapter registry,12 种 provider_type:
原 6 家 + qwen_dashscope / moonshot / minimax / doubao_ark / xai / ollama 原生);
角色槽位定义在 `llm_node_registry.py::ROLE_SLOTS`(drafting/review/extraction,
覆盖全部 54 个 active 节点)。冒烟:`scripts/smoke-ai-settings.mjs`(入 run-smokes)。
