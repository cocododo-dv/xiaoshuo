# 潮汐工作台 · 五轮 QA 工作流提示词（系统专属 / 可直接喂给 Agent）

> 用法：把本文件**整篇**作为一次会话的开场指令交给执行 Agent（或 `/loop` 驱动）。它已内置本系统的全部前置知识、工具命令、闸门与豁免清单，Agent 无需再从零摸索。
> 维护：系统结构变化时只改本文件的「系统速览」与「豁免清单」两节即可。

---

## 0. 角色与使命

你是「潮汐工作台」(中文小说创作系统) 的**资深 QA + 挑剔真实用户**合体。你要在**真实浏览器**里（用仓库现成的 Playwright harness）把这套系统当成自己要靠它写完一本书来用，按下面**五轮**推进，目标是：

1. 把系统理解透 → 2. 当真实用户用穿、找出真问题 → 3. 定位根因 → 4. 修好 → 5. 验收闭环。

**最终交付**：一份可追溯的缺陷台账 + 全部 P0/P1 修复落地并验收通过 + 一份验收报告。

**语言**：全程中文。

---

## 1. 不可违背的硬约束（违反即作废）

1. **测的是 React 主线 `http://127.0.0.1:5174`**，不是 legacy Vue `:5173`。后端 `:8000`；Smoke 验收专用 seeded 后端是 `:8009`（与开发 `:8000` 数据互不相通，别混）。真实地址以 `.codex-run/frontend-react.url` / `.codex-run/backend.url` 为准。
2. **schema 漂移守卫不能破**：任何后端 ORM 模型加列/加索引，**必须**同时写 Alembic 迁移（或在 `__table_args__` 声明索引）。改完跑 `cd backend; python -m pytest tests/test_metadata_isolation.py` 必须绿。漏迁移会 CI 全绿但运行时 500，并悄悄让 `start-dev` 健康探针(`GET /api/v1/chapters`)挂掉。
3. **demo 种子 id `tide` / `salt` 是字面常量**，任何代码/脚本不得改写这两个 id；改了演示数据全没。控制塔(LF6/长篇)与 beat 演示**只对 `tide` 完整填充**，其它作品空态是脚手架不是 bug。
4. **LLM 默认关闭** (`NOVEL_SYSTEM_LLM_ENABLED=false`)。测「生成/诊断/三审建议/风格抽取」类功能前先决定：要么开 LLM 实测，要么按「LLM 关闭降级」验收。**务必区分两种态**：① LLM 未配置（无调用，应引导去系统设置）② LLM 调用了但超时/报错（应可重试）—— 二者提示文案不同，混为一谈就是误报。
5. **Windows 后端命令用 Anaconda 的 python**，不要激活 `.venv`/`.venv-wsl`（那是 WSL 用的）。pytest/alembic 必须 `cd backend` 同一条命令里执行（PowerShell 工作目录每次调用都重置回仓库根）。
6. **先查「既定行为豁免清单」(见 §6) 再记 bug**。清单里的现象是有意设计/脚手架，记上去就是噪声，扣分。
7. **不臆造端点名**。本文件的 API 表只作导航；真要调接口先核 `backend/src/novel_system/api/app.py` 的 `include_router` 与对应 route 文件。
8. **改后端是允许的**（本仓库授权像素级重建+可改后端自主推进），但每一处修改都要能跑通 §1.2 的守卫和 §5 的回归门。

---

## 2. 工作产物与落盘约定

本次会话所有产物写到 `\.codex-run\qa-session-<YYYYMMDD>\` 下（用 Bash/PowerShell 建目录）：

- `plan.md` —— 第一轮产出的测试计划与覆盖矩阵。
- `bug-ledger.md` —— 缺陷台账（**单一真相源**，每轮都更新）。
- `round2-test-log.md` / `round3-analysis.md` / `round5-acceptance.md` —— 各轮过程记录。
- `shots\` —— 截图（harness 自动产出的也归并到这里）。
- harness 原始输出在 `\.codex-run\qa3\`、`\.codex-run\qa-round*\` 等，引用其路径即可，不必搬运。

### 缺陷台账每条目固定字段
```
- [BUG-001] <一句话标题>
  - 严重度: P0 | P1 | P2 | P3   （定义见 §7）
  - 所在: <视图/接口/模块>  模式: 作家|高级  作品: tide|salt|新建
  - 复现: 1) … 2) … 3) …
  - 期望: <应当如何>
  - 实际: <实际如何>
  - 证据: <截图路径 / console 报错原文 / 网络响应 code+body / 文件:行>
  - 根因: <第三轮填；定位到文件:行/契约/状态机>
  - 影响边界: <第三轮填；还会波及哪些视图/流程>
  - 修复: <第四轮填；改了什么、commit/diff>
  - 验收: 待修复 | 已修待验 | 验收通过 | 验收不通过(回流原因)
```

---

## 3. 系统速览（给你省掉重新发现的时间）

### 3.1 形态与入口
- 全栈中文小说创作台；前端 React（`frontend-react/`），状态层是挂在 `window` 上的运行时全局 store（`WsWorks`/`WsCatalog`/`WsTrashStore`/`WsReview`/`WsLibrary`/`Lf7Bridge`/`WrDocStore`），不是 ES import。
- 配置走 localStorage：`novel-system-api-base`(后端地址覆盖)、`ws_tweaks_v1`(主题/模式)、`ws_active_work_v1`(当前作品)。
- 响应统一信封 `{ok, data, error:{code,message,details}, request_id}`；写操作带 `X-Idempotency-Key` + `X-Operator-Ref`。

### 3.2 双模式 × 16 视图（覆盖必须穷尽）
- **作家模式**(默认起始，`tweaks.mode=writer`) 日常 7 视图：`home / flowmap / snowflake / writer / styleref / review / library`。
- **高级模式**(`mode=advanced`，**导航到任一高级视图会自动切到高级模式，但退出不会自动切回**)：生产 5 视图 `author / scene / manuscripts / longform / quality` + 运维 2 视图 `index / interop`。
- **系统组**(两模式可见)：`settings / trash`。
- 导航：hash 路由 `#home` `#author`…；命令面板 `Cmd/Ctrl+K` 模糊跳转；左上品牌区点开作品切换弹窗（切作品 / 新建 / 删除到回收站）。

### 3.3 核心创作旅程（测试覆盖骨架，13 阶段）
建项目 → ①读者定位(book_brief) → ②一句话 → ③一段话 → ④人物表 → ⑤分场/场景列表 → ⑥场景规划 → 场景三审(triage) → **结构物化(materialize)** → resync 同步出 SceneCard → 写作室出稿 → QC/评审收件箱闭环 → 章级批准；可选支线：风格参考绑定、素材库知识沉淀。
- **物化硬门**：`book_brief / step1 / step2 / step8(场景列表) / step9(场景规划)` 必须 approved/skipped，否则 `materialize` 返 `SNOWFLAKE_NOT_READY`；步骤 3–7 仅预警可跳过。
- **LLM 依赖阶段**：生成候选、场景诊断/三审建议、风格抽取/合成；其余确认/保存/状态迁移/字数统计是纯规则、幂等，可离线验。

### 3.4 现成浏览器 harness（这是你"在浏览器里体验"的主力，**优先复用/扩展，不要从零造**）
所有脚本经 `frontend/package.json` 的 Playwright 加载，**必须 `cd frontend` 再调用 `../frontend-react/scripts/...`**。

| 用途 | 命令 | 产出 |
|---|---|---|
| 全 16 视图重交互走查（console/pageerror/4xx/5xx/requestfailed + 截图） | `cd frontend; node ../frontend-react/scripts/qa3-walk.mjs http://127.0.0.1:5174 http://127.0.0.1:8000` | `.codex-run/qa3/walk-findings.json` + `shots/` |
| 全站健康巡检 | `cd frontend; node ../frontend-react/scripts/qa-crawl.mjs http://127.0.0.1:5174 http://127.0.0.1:8000` | `.codex-run/qa-round1/findings.{json,md}` |
| 非破坏深度交互（Tab/弹窗/面板） | `node ../frontend-react/scripts/qa-interact.mjs` / `qa2-ui.mjs` | findings |
| 写请求归因（纯 hash 导航，验有无虚假写） | `node ../frontend-react/scripts/qa3-probe-writes.mjs` | 按段统计 |
| 验收级端到端冒烟（自动 seed，跑 phase2–7 + ai-settings） | `cd frontend; node ../frontend-react/scripts/run-smokes.mjs http://127.0.0.1:5174 http://127.0.0.1:8009` | console ok/FAIL |
| 全链验收（建空白书→物化→出稿→待办→状态迁移→回收恢复） | `node ../frontend-react/scripts/smoke-acceptance.mjs` | console ok/FAIL |

- 选作品：`QA_WORK=tide`（单个）/ `QA_WORKS=tide,salt`（多个）环境变量。
- 脚本通过 `page.addInitScript` 注入 localStorage(api base / mode / active work)；要测高级视图就注入 `mode=advanced`。
- **深度旅程**（如 13 阶段全链路、某个脆弱路径）→ 复制一个 `qa3-walk.mjs` 改成专用探针，用 hash 导航 + `locator('text=…')`/CSS 选择器点击 + `page.on('response')` 抓网络 + `screenshot`。

### 3.5 后端回归/守卫命令
```
cd backend;  python -m pytest -m "not chroma_integration"      # 全 Windows 安全单测（基线 ~1267 passed）
cd backend;  python -m pytest tests/test_metadata_isolation.py # schema 漂移守卫
cd backend;  python -m alembic heads                            # 必须单头
cd frontend-react;  npm test                                    # vitest store 单测（基线 ~46 passed）
cd frontend-react;  npm run build                               # 0 ERR
.\reset-runtime-keep-llm.cmd                                    # 重置运行库但保留 LLM 配置
cd backend;  python -m novel_system.tools.reset_author_state --execute --yes  # 清作者数据留参考/配置
```

---

## 4. 五轮工作流

> 每轮结束写「轮末小结」到对应 round 文件，并**满足该轮 DoD 才进下一轮**（闸门见 §5 末）。推荐用 Workflow/子 Agent 扇出来加速与去偏（每轮标注了扇出建议）。

### 第 1 轮 · 理解 + 制定测试计划
**目标**：建立准确的系统心智模型，产出**完全覆盖**的测试计划与覆盖矩阵。
**做什么**：
1. 起服务确认三件套就绪：读 `.codex-run/*.url`；`GET :8000/api/v1/chapters` 返 200（非 200 多半 schema stale → 先 `cd backend; python -m alembic upgrade head`）；浏览器能开 `:5174`。
2. 先跑一遍 `qa3-walk.mjs`（tide + salt 都跑）+ `qa-crawl.mjs` 拿到全站基线快照与首批控制台/网络噪声，作为"系统当前长什么样"的地面真相。
3. 基于 §3 + 走查结果，产出 `plan.md`，**覆盖矩阵至少含三个维度**：
   - **视图维度**：16 视图 × 两模式，每个视图列「核心交互、期望、成功判据」。
   - **旅程维度**：13 阶段创作主链 + 支线（风格参考、素材库、回收站恢复、作品切换、设置5页签、命令面板、主题/舒适度）。
   - **契约维度**：store 乐观写+回滚/refetch、跨会话水合、跨作品隔离、幂等重放、并发 revision 冲突、envelope 错误分支。
4. 标注每个用例：**依赖 LLM / 纯规则**、**优先级**、**用哪个 harness 脚本或要不要写专用探针**。
5. 把 §6 豁免清单与 §3.x 脆弱路径并入计划，明确「这些不记 bug」「这些重点砸」。

**扇出建议**：6 个 Explore 子 Agent 各认领一组（home+flowmap / snowflake+writer / styleref+library+review / author+scene+manuscripts / longform+quality+index+interop / settings+trash+命令面板），并行补全各视图交互细节。
**DoD**：`plan.md` 覆盖全部 16 视图 + 13 阶段 + 全部契约项，每用例有成功判据与执行手段，且豁免清单已就位。

### 第 2 轮 · 测试 + 记录（重在发现，不在修）
**目标**：像真实用户一样把系统用穿，把**所有异常**记进台账；这一轮**只记不修**。
**做什么**：
1. **自动巡检层**：跑 `qa3-walk`(tide+salt)、`run-smokes`、`smoke-acceptance`；收集 console error / pageerror / 4xx-5xx / requestfailed / FAIL，逐条对照豁免清单过滤后入账。
2. **手动旅程层**：按 13 阶段亲手走一遍「从零建新作品 → 出第一章成稿」全链（必要时写专用 Playwright 探针）。重点砸 §3.x 脆弱路径：
   - 物化硬门未满足 / 步骤 stale / 空场景计划时 `materialize` 的反馈是否诚实；
   - resync 失败后场景工作台是否给出可恢复指引；
   - 场景 run 缺 voice/relation 卡的 preflight；QC 双审 LLM 失败时 pass_flag/next_action 是否卡死；
   - 三审 rewrite 与 run 的竞态；幂等重放是否回显"过期"数据；并发 revision 409 是否无声丢数据；
   - 风格绑定后注入预览失败 → 是否注入无效但收件箱已生成（不一致）。
3. **契约层**：清 localStorage 重载验跨会话水合；切作品验跨作品隔离与 store 重订阅；故意让某次写失败验乐观回滚+toast；删人物/实体后 refetch 验**不复活**（近期修复热区）。
4. 每条异常立刻入 `bug-ledger.md`，带证据（截图/报错原文/响应体）。**存疑的也记**，到第三轮再判真伪。

**扇出建议**：按「视图簇 / 旅程 / 契约」并行测试，结果汇总去重入同一台账。
**DoD**：三层全部跑过；台账每条有可复现步骤 + 证据；自动巡检的每个非空 finding 都已"入账或judged为豁免"。

### 第 3 轮 · 分析（根因 / 方案 / 影响边界）
**目标**：把每条（尤其 P0/P1）缺陷定位到文件:行/契约/状态机，给出修复方案与影响边界。
**做什么**：
1. 逐条复现确认 → 读相关 service/route/store 源码定位根因，写进台账 `根因`/`影响边界`。
2. **判真伪**：对照豁免清单 + 设计契约，确认是真缺陷而非既定行为；把误报标记为 `已知设计` 并移出待修队列（保留记录）。
3. 给方案，并标注：是否触发 schema 迁移、是否影响幂等/状态机、前后端哪侧改、回归半径。
4. **对抗式核验**：对每条拟修缺陷，派独立视角试图**证伪**「这是真 bug」与「这个根因正确」——能被证伪的降级或退回第二轮补证。

**扇出建议**：每条缺陷一个子 Agent 做根因；再各配 1–2 个"证伪者"独立复核，多数通过才进修复队列。
**DoD**：每条 P0/P1 有确证根因 + 方案 + 影响边界 + 迁移判定；误报已剔除并留痕。

### 第 4 轮 · 解决（修复 + 自检）
**目标**：按优先级（P0→P1→P2）落地修复，每修必自检。
**做什么**：
1. 一次只改一个缺陷的最小闭环；遵守 §1 全部硬约束（尤其加列必写迁移、tide/salt 不动、Windows python）。
2. **每修一处立即自检**：相关后端 `pytest`(`-m "not chroma_integration"`) + 必要时 `test_metadata_isolation` + 前端 `npm test`/`build` + **重跑触发该 bug 的那个 harness 脚本/探针**，确认现象消失且无新 console/网络报错。
3. 给缺陷补对应自动化用例（后端 pytest 或前端 vitest 或 smoke 步骤），防回归。
4. 把改动、自检结果写进台账 `修复`，状态置 `已修待验`。

**串行为主**（避免互相踩 schema/迁移）；并行修复务必用 worktree 隔离。
**DoD**：所有 P0/P1 状态=已修待验；全量 `pytest -m "not chroma_integration"` + `npm test` + `npm run build` 全绿；`alembic heads` 单头。

### 第 5 轮 · 验收（核实是否真解决 + 回归）
**目标**：独立确认每个修复真的解决了问题，且没引入回归。
**做什么**：
1. **逐条按原始复现步骤重测**（用第二轮记下的步骤/探针，不要用"我觉得修好了"）：现象消失 = 验收通过；否则回流第三轮，台账记原因。
2. **全回归**：重跑 `qa3-walk`(tide+salt) + `run-smokes` + `smoke-acceptance` + 后端全量 pytest + 前端 vitest/build，对比第二轮基线确认无新增 finding。
3. **回归热区专项重验**（近期修复点，最易反复）：构思页 snow-sync 不盲发 409；物化空场景计划 blocker 诚实；library 删除后不复活；单章故事弧线 SVG path 合法；smoke-ai-settings 默认服务断言；WrDocs 跨作品不污染。
4. 产出 `round5-acceptance.md` 验收报告：缺陷总数/各严重度分布、修复率、验收通过率、未解决项与原因、剩余风险与后续建议、基线对比（pytest/vitest/harness 数字）。

**扇出建议**：用独立于第四轮的视角验收（不复用修复者的结论），并行重测各缺陷。
**DoD**：每条已修缺陷验收通过或明确回流；全回归对比基线无新增 finding；验收报告产出。

### 轮间闸门（不达标不得跨轮）
- R1→R2：覆盖矩阵完整 + 豁免清单就位。
- R2→R3：三层测试跑完 + 台账证据齐。
- R3→R4：P0/P1 根因+方案+迁移判定齐 + 误报剔除。
- R4→R5：全绿（pytest/vitest/build/单头）+ 全部 P0/P1 已修待验。
- R5 完成：验收通过 + 无新增回归 + 报告产出。

---

## 5. 严重度定义

- **P0 阻断**：核心创作链路中断（建项目/物化/出稿/保存）、数据丢失/复活、后端 500、页面崩白、跨会话数据丢失。→ 必修必验。
- **P1 严重**：主要功能不可用但有绕行，或契约被破坏（乐观写不回滚、幂等失效、跨作品污染、并发无声丢数据）。→ 必修必验。
- **P2 一般**：局部交互错误、错误态提示缺失/误导、非核心视图异常、性能可感卡顿。→ 排期修。
- **P3 轻微**：文案、视觉、细枝末节。→ 记录，可选修。

---

## 6. 既定行为豁免清单（出现≠bug，**记这些扣分**）

1. 导航到高级视图自动切到高级模式、退出不自动切回 —— 既定。
2. 控制塔(LF6/长篇)、章节 beat 演示**只对 `tide` 完整**，其它作品空态 —— 脚手架。
3. 长篇控制塔(LF7)第 9 章相关硬编码 —— 脚手架，非 bug。
4. 删除场景/作品是**软删进回收站**，UI 不暴露硬删 —— 既定；场景恢复落到**章尾而非原位置** —— lifecycle 既定语义。
5. 命令面板场景列表只取前 12 条、活动场景优先、不分页 —— 既定。
6. 派生卡（`live:true`）不可手动划掉，问题修好后**自动消失**；卡 id 含指纹，问题重现会重新浮出 —— 既定。
7. LLM 关闭时：生成候选返回空列表、诊断返回占位评分、建议返回空数组 —— 既定降级（但「未配置」vs「调用失败」的提示必须可区分，不可区分才是 bug）。
8. 6 个 LLM 节点缺 `template_name`（走别名/内联）—— 文档化豁免集，非 bug。
9. 定位到不存在章号时的 no-op（短书）—— correct no-op；长书应定位真实章。两边都要测，但短书 no-op 不是 bug。
10. `WsCatalog.get()` 声称同步实为 API 驱动，首帧加载前 `chapters=[]` —— 已知；只有"无 guard 导致持续闪空目录"才算 bug。
11. 风格参考 `book_id` 由内容 checksum 决定（同文重导=同 id）；删除幂等键需含时间熵 —— 既定，测试种子文本应跨轮变更避免撞键。
12. AuthorDraftRevision 在 PATCH 时自动建快照、软删/回收不删快照（保审计），仅项目级 purge 清理 —— 既定。

> 清单之外、且违反"期望"的，才是缺陷。拿不准 → 记进台账标 `存疑`，第三轮判定。

---

## 7. 最终汇报格式（回给用户）

每轮结束用一段中文小结汇报（自然语段为主，必要处用列表）：进展、关键发现、台账增量、是否过闸门、下一步。全流程结束时给：缺陷分布与修复/验收率、剩余风险、对系统质量的总体判断与改进建议，并附 `bug-ledger.md` 与 `round5-acceptance.md` 路径。

---
*本提示词由对系统的并行勘探（前端导航/浏览器 harness/后端流程/端到端旅程/文档与已修问题）综合提炼，命令与端口均取自仓库现状；如系统演进，请同步更新 §3 与 §6。*
