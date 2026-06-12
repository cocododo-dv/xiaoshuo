# FE-ALIGN 后续任务简报（三）— DEFERRED D12 收尾（H 系列）

> 前置：F 系列（D1–D7）与 G 系列（D8–D11）已全部交付（PROGRESS.md，
> G 收口提交 `0bcc976`）。本简报把 D12（控制塔最后一块演示区）拆为 H1–H2。

## 现场核对（已验证，以代码为准）

塔闭环「规划 → 交接 → 生成 → 审计 → 归档」中：
- **交接/下发已真**：`generate()` 经 `lf7Dispatch9()` 封契约 + 拆场入列
  起草台（F6 起即真管线）；`Lf6Generating` 只是 1.9s 过场动画，文案诚实
  （「封进契约下发起草台」），不伪造产文。
- **归档已真**（P7 写回链）。
- **真正剩下的伪造层只有两处**：
  1. `LF3_AUDIT` 静态回执——honored 条目带**虚构的正文证据句**（来自一份
     不存在的第 9 章草稿），audit 页签/审计动画/归档动画都吃它；
     d1/d2/n1/n3 修复-归档动作硬编码绑在静态条目上。
  2. `LF3_RETRIEVE` 记忆池——Lf3Memory/Lf4Brief 的「可检索池」静态五条
     （三处消费者均 ESM live import，lf3-data 重赋值即生效）。
- 锚点模型的 `status: pinned/faded` 语义（在场/淡出可重钉）正好映射
  记忆池的 enforce/retrieve 两态——H1 零建模成本。

## 执行规则

沿用 F/G 系列（红线/完成定义/卡死规则/单提交）。审计回执的诚实口径：
**确定性扫描只声明「检出（带真实引用句）/未检出（待人工核对）」，
绝不机器判定「违约」**——违约判定是 LLM 审计的活（残余记 D13）。

## 阶段

### H1（D12-记忆池）— LF3_RETRIEVE 接锚点库

- seed：rv1–rv5 五条入 tide 锚点（kind 按语义 fact/setting，
  `status="faded"`（淡出=可检索池），fe JSON 存 {id,text,ch,tone,reason,
  pool:"retrieve"}）；seed 计数断言 19→24。
- lf2SyncFromTower 分流：fe.pool==="retrieve"（或 status faded）的锚点
  不进 LF2_CANON，归集为检索池 → lf3-data 在 `lf2:tower-synced` 上把它
  投影进 LF3_RETRIEVE（const→let；消费者 live import 自动生效）；
  无数据非 tide 清空。
- 钉入升格（pinnedFacts promote）写回：anchor status faded→pinned
  的一行接缝（按现 UI 交互定，能一行就一行，记账）。

**验收**：冒烟：seed 24 锚点 → LF3_RETRIEVE 投影 5 条 → POST 一条
faded 锚点刷新可见；记忆面板渲染真实池。

### H2（D12-审计回执）— 章级审计回执接真实产物

- 后端 `GET /api/v2/projects/{pid}/longform/chapters/{chapter_id}/audit-receipt`
  （longform_tower 服务，纯确定性，无 LLM）：
  1. 契约段：get_or_create 的 status + constraints（真）。
  2. 产出段：本章场景卡 state/words + 各场 author-draft 正文（剥 HTML），
     汇总章正文与总字数（真）。
  3. 锚点在场扫描：pinned 设定锚点（fact/trait/setting/timeline）的
     value 子串在章正文中检索——命中 → 摘出**真实引用句** + 位置
     （场次标题+段号）；未命中 → pending（待人工核对）。promise 锚点
     payoff==本章号 → 列入 pending（到期承诺待人工核对）。
- FE：lf7-bridge 加 `auditReceipt(chapterNo)` 适配器（fetch + 还原
  LF3_AUDIT 形状：honored=命中（真实证据句）、drifted=[]、introduced=[]、
  pending 列表附注）；lf6 的 `aud`/审计动画/归档动画在**本章有真实正文**时
  吃真回执，无正文时回落静态演示（demo 体验保留）。最小接缝记账。
- d1/d2/n1/n3 硬编码修复-归档动作只在静态路径出现（随静态保留）。
- DemoTag 收窄：「草稿审计 = 确定性回执（契约/产出/锚点在场扫描）已真；
  违约级判定 + 流程动画的逐条裁定语气仍属演示，待 LLM 审计节点」。

**验收**：pytest：契约+产出+扫描三段断言（造场景草稿含/不含锚点值 →
hit/pending）；冒烟：写正文（含某锚点值）→ 回执 API 命中且引用句正确 →
塔上审计页签展示真实回执。

## 完成标准

1. H1–H2 各一次提交，账本「后续 H 系列」勾选 + 明细。
2. pytest 全绿；build 绿；run-smokes + acceptance 全过。
3. 残余演示面（流程动画的裁定语气、违约判定、d1/d2 静态动作）记 D13
   （需 LLM 审计节点，性质同 styleref 提取）。
4. 输出总结：提交号 + D13 定义。
