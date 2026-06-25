# 系统健康审计 + 修复轮留档（2026-06-25）

> 实施日期：2026-06-25
> 分支：`feat/fe-react-quality-longform-fixes` → 已 fast-forward 合入 `main`（顶端 `08f1326`），特性分支已删除，仓库回到单一主分支。
> 方法：6 路并行调研 + 真体检（实跑 `pytest` / `vitest` / `build`）+ 对每条发现做**对抗式核验**（独立 agent 打开代码/重跑命令确认真伪与严重度）。
> 性质：把"账本自陈状态"用真实运行结果交叉验证，区分【真实问题 / 被夸大降级 / 已修复误报】，并落地可在本环境验收的修复。本环境 LLM 不可用，凡需真实大模型端到端的验收均不在本轮范围。

---

## 0. 一句话结论

工程健康度高、全门禁绿；近期"长篇控制塔"的后端能力已真化。**真正的问题集中在前端 demo 层尚未接后端真值**（尤其构思控制塔 `ct-*` 与长篇交接链的 tide 硬编码），外加蓝图正确性地基的少数已知缺口。**核验后没有一条达到 high 级（会在生产破坏 / 数据损坏）**。

本轮修复了唯一一处真实正确性 bug（控制塔章号定位），并补齐了三处"诚实标注 / 可证伪测试 / CI 兜底"的空缺；高风险或需外部凭证（LLM key / 文学人评）的项**诚实延期**，不在无法验收的环境里硬塞。

---

## 1. 审计方法

一个确定性编排的多 agent 工作流（fan-out → 体检 → 对抗式核验）：

| 阶段 | 内容 |
|---|---|
| 调研与体检（6 路并行） | ① 进度账本提炼 ② 后端体检（alembic/漂移守卫/全量 pytest）③ 前端体检（vitest+build）④ 长篇控制塔近期特性审阅 ⑤ 代码债扫描 ⑥ 架构契约一致性 |
| 核验（对抗式） | 对调研报出的每条问题派独立 agent 打开代码/重跑命令，给出 `is_real` / 修正后 severity / 证据 / note（夸大或已修复则说明） |

关键纪律：**绿灯不等于被验证**——审计本身就建立在"对抗式重跑"上，避免把账本自陈当真相（历史上 §17 动作 B 的"假绿"教训，见 `blueprint_v2_validation_results.md`）。

---

## 2. 健康基线（实测）

| 维度 | 结果 |
|---|---|
| 后端 `pytest -m "not chroma_integration"` | **1264 → 1267 passed**（本轮 +3 守卫）/ 0 failed / 3 skipped / 17 deselected（约 8 分钟） |
| Schema 漂移守卫 `test_metadata_isolation.py` | **4 passed**；ORM `create_all` 与 Alembic `upgrade head` 零漂移；单头 `20260618_0059` |
| 前端 `frontend-react` vitest | **39 → 46 passed**（本轮 +7）/ vite build 绿 |
| legacy `frontend`（Vue） | build 绿 |
| 架构契约 | 31 个路由全部挂载；前端 store 端点全部命中后端；config `model_profile` 无悬空引用 |

诚实纪律在生效：后端 LLM 链路普遍"离线确定性降级"（LLM 关闭时返回 `offline_fallback` / 空结果 + 引导动作，不伪造产物）；账本主动登记自身延期项。

---

## 3. 核验后的问题账本

> 原始 severity = 调研阶段判定；核验 severity = 对抗式核验修正后。`is_real=false` = 已修复或不成立。★ = 本轮已处理。

| # | 问题 | 域 | 原始 | 核验 | 状态 |
|---|---|---|---|---|---|
| 1 | 真实 LLM 端到端产文从未在本环境验收 | 账本 | high | **low** | 透明披露的延期；管线接真+诚实降级（无 key，非缺陷） |
| 2 | §2 事件溯源是"叠加"非"POV 减法投影" | 后端 | high | **medium** | 真实，正确性地基渐进缺口；确定性 `check_consistency` 已作 blocking 地板兜底。**延期** |
| 3 | §7 解码端 XTC/min-p/typical/DRY 缺失 | 后端 | medium | **low** | 走 API 的设计取舍，账本已诚实标注（接了 API 原生 freq/presence penalty） |
| 4 | 控制塔/非 tide 推断性派生未做的演示残余 | 账本 | medium | **low** | 有意延期；非 tide 真实作品已清空 demo 残余（`LF2_RISKS=[]`/`drifted` 恒空） |
| 5 | §4 代价"轴位移"无自动校验 + §9 few-shot 非默认 | 后端 | medium | **low** | 相对蓝图的功能增强缺口，非运行期 bug；few-shot 能力在、为 opt-in（Strategy B） |
| 6 | 重构期 v2 创建端点幂等键契约 bug | 账本 | medium | **false** | 2026-06-12 已修 + 回归测试 `test_create_chapter_idempotency_contract` 通过 |
| 7 | WrDocs 按裸 sid 缓存的跨作品污染 | 账本 | low | **false** | 已修 `work::sid` 双层隔离 + 可证伪回归测试通过 |
| 8 | 主 JS chunk > 500kB（1.15MB / gzip 359KB） | 前端 | low | **low** | 真实，Vite 构建期最佳实践告警（非错误），build 成功 |
| 9 | `client.js` 动态+静态混合导入 | 前端 | low | **low** | 真实，打包优化告警；核心小模块本不该单独拆 chunk |
| 10 | 后端交接契约端点（CRUD/transition/归档写回）前端零消费者 | 控制塔 | high | **medium** | 真实 wiring gap；后端已测，UI 归档只改内存态。**延期** |
| 11 | "交接下发→归档"主链 tide 专属静态硬编码 | 控制塔 | high | **medium** | 真实；但审计原语对任意作品已真化，tide-only 的是下发/归档演示动画。DEMO 脚手架（PROGRESS D13 DEFERRED）。**延期** |
| 12 | `LF2_NEXT` 章号锚死 tide 常量"第 9 章" | 控制塔 | medium | **medium** | **唯一真实正确性缺陷**（短书 no-op、长书审错章）★ **本轮已修** |
| 13 | `resetLoop9` 降级为 alert 提示 | 控制塔 | low | **low** | 诚实降级（等价能力=后端 `reset_author_state`） |
| 14 | P3 派生覆盖面有意收窄（断链/空降/张力/弧线未做） | 控制塔 | low | **low** | 有意收窄守诚实纪律；已做部分（thread/promise）有单测 |
| 15 | 前端 audit-receipt / derive-structure 无 FE 单测 | 控制塔 | low | **low** | ★ **本轮已补** auditReceipt + deriveStructure 单测 |
| 16 | `ct-*` 构思控制塔跑硬编码 demo + 缺 `WsDemoTag` 徽标 | 代码债 | high | **medium** | 真实；唯一缺诚实徽标的视图。★ **本轮已挂徽标**（接真为更大工程，仍延期） |
| 17 | lf7 第 9 章交接 promise/threads/scenes tide 硬编码 | 代码债 | medium | **medium** | DEMO 脚手架；接上 LLM 审计节点即收口。**延期** |
| 18 | `ct-edit` 占位章节（灾二/灾三）字面值 | 代码债 | low | **low** | demo 种子；占位↔已落位状态其实可派生翻转 |
| 19 | 风格参考拟人/比喻子维度用词表近似 | 代码债 | low | **low** | 确定性下界，自陈非可靠度量，需 LLM（§14 增强项） |
| 20 | 资料库 refs/profiles/knowledge 三 tab 运行时空 | 代码债 | low | **low** | P8 接真前留空，前后端均无数据源 |
| 21 | LLM 节点 `template_name` 与 `prompts.yaml` 无守卫测试 | 契约 | medium | **low** | 真实但当前无害（悬空项均走内联/别名/run_task）。★ **本轮已补窄约束守卫** |
| 22 | `models.yaml`/`prompts.yaml` 任务名差集无一致性 tripwire | 契约 | low | **low** | 松耦合设计；miss 会运行期 KeyError（非静默）；★ template 对齐部分由本轮守卫覆盖 |

一条未完成核验：#（"假绿测试"历史项）核验 agent 结构化输出失败未拿到独立结论；从原始证据看（commit `60bb715`「消除 6 处假绿断言」）大概率为已收紧的历史项。

---

## 4. 本轮修复（已合入 main）

提交：`2fd4e95`（前端）、`08f1326`（后端）。

| 批 | 修复 | 对应 # | 验收 |
|---|---|---|---|
| B2 | `lf2SyncFromCatalog` 章号定位改为对**所有作品**取目录真相（`now`/`LF2_NEXT`），仅 beat/理想张力演示结构层保留给 tide | 12 | 新测 `lf2-chapter-pos.test.jsx`（5，可证伪）：非 tide 第 3/15 章→next 4/16；tide 仍=9；全计划章兜底=2 |
| B1 | `ct-app.jsx` 页头补挂 `WsDemoTag`——如实标注结构强度/连续性/脊柱/质量矩阵为示例+工作台推演、未接后端真值 | 16 | build + vitest 绿 |
| B1 | `lf7-bridge.test.jsx` 补 `auditReceipt` 确定性回执映射覆盖（命中/未检出/到期承诺 + drifted 恒空 + 无正文降级 null） | 15 | +2 例 |
| B1 | 新建 `test_llm_node_registry.py`：节点 `template_name` ↔ `prompts.yaml` 对齐守卫（文档化豁免集 + 自清理配对 + prompts well-formed） | 21/22 | 3 passed |

**修复设计要点**：

- **B2 章号定位**：根因是 `lf2SyncFromCatalog` 对非 tide 作品整体早退，`LF2_NEXT` 永远停在 tide 常量 `LF2_BOOK.now+1=9`。修复抽出纯函数 `lf2ChapterPosFromCatalog(cat)`（`now`=最后已写/在写章，`next=now+1`），对所有作品生效；`lf7ChapterIdByNo` 按 `c.n` 定位，短书定位到不存在的章→正确 no-op，长书定位到真实当前章而非错误第 9 章。tide 演示结构层（beat/张力）逻辑不变。
- **B1 template_name 守卫**：窄约束关键——6 个"缺失" template（`stylize`/`scene_auto_rewrite`/`scene_quality_contract`/`extraction`/`snowflake_step_generate`/`literary_eval_live`）全部走别名/内联/run_task，**不经 PromptBuilder.build()**，naive 守卫会误报。故用"文档化豁免集 + 自清理配对"（豁免集成员一旦进 prompts.yaml 即报错逼迫移除），既不误报、又能拦未来新节点的 template_name 拼写漂移。

**总验收门（全绿）**：后端 1267 passed / 0 failed；schema 漂移守卫 4 passed；前端 vitest 46 passed + build 绿。

---

## 5. 诚实延期（backlog）

按纪律不在"无法验收 / 会危及已绿套件"时硬塞。

### 本轮明确延期（核验 medium）

1. **前端归档接后端 `contract/transition`**（#10）——本质是给非 tide 作品补一条真实归档交互（新功能，非外科修复），且无 FE 测试底座可证伪验收；"尽力而为"旁路 POST 语义含糊（归档闸门遇 open findings 会拦）。后端端点已测。
2. **§2 事件溯源 POV 减法投影**（#2）——改 `format_state_for_prompt` 会改提示词内容、可能动摇 golden 套件；"限定 POV 已知集"的正确性需文学化人评/真实 LLM（无 key 不可得）；确定性 `check_consistency` 已作 blocking 地板兜底。属需独立验证的质量重构。
3. **lf7 第 9 章交接 tide 硬编码**（#11/#17）——与归档接线同族，项目自身已登记的 DEMO 脚手架，接上 LLM 审计节点即收口。

### 继承的既有延期（环境/设计/数据所限）

- 真实 LLM 端到端产文走查（待用户提供各家 provider key）。
- §7 为草稿步加本地模型通道以启用 XTC/min-p/DRY（走 API 即拿不到这把"对抗趋均值最锋利的刀"）。
- §4 代价"轴位移"自动追踪；§9 确认写作默认策略真注入 few-shot。
- P3 低置信结构派生（断链/空降/张力曲线/人物弧线）接真 + 真实数据校准（无数据时硬投影会产假阳性）。
- 风格参考拟人/比喻语义抽取（需 LLM）、真实 embedding 的语义 hit@5、LLM rerank 接非实时路径。
- 资料库 refs/profiles/knowledge 三类 P8 接真。
- §17 仍未跑的可证伪判据：Best-of-N 上界偏好率盲测、关键增强层消融、§16 过约束体检（滑块有旋钮无标定）——均差人评。

---

## 6. 后续建议

1. **优先级最高且最接近可做**：给非 tide 作品补真实归档交互并接 `contract/transition`（#10），让后端归档推章状态 + library derive 在真实 UI 下触发——需接受更深的回归验证 + 补 FE 测试底座。
2. **正确性地基**：把 §2 POV 做成减法投影（#2），作为独立立项，配套 golden 套件管理 + 待 LLM 可用后的文学人评。
3. **契约卫生**：在本轮 template_name 守卫基础上，可补 `models.yaml`/`prompts.yaml` 跨文件一致性的静态 tripwire（#22），把冷门节点的拼写漂移从运行期前移到 CI。
4. 待用户提供 LLM key 后，统一跑一轮真实端到端走查（D13 裁定 / styleref 抽取 / 雪花候选 / 起草引擎），关闭一大批"管线接真但未端到端验收"的延期。

---

*本文件为一次性审计快照；持续进度账本仍以 `codex-patches/FE-主线对齐/PROGRESS.md` 与 `docs/style-reference-progress.md` 为准。*
