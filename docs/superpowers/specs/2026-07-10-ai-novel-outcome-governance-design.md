# AI 小说系统结果闭环与质量证据治理设计

> 日期：2026-07-10
>
> 状态：可交付实施规划
>
> 产品目标：单作者本地创作工具为主，文学质量实验平台为证据体系
>
> 总体路线：渐进治理、结果闭环优先，不推倒现有架构
>
> 第一阶段北极星：从空白项目稳定完成五章真实成稿

## 1. 执行摘要

当前系统已经具备成熟的规划、场景生成、上下文组装、连续性、伏笔、风格参考、质量检查、评审和长篇治理模块。问题不在于模块少，而在于以下能力尚未形成同一条可证伪的产品闭环：

1. 前端完成态、浏览器缓存、后端最终稿和章节聚合存在多套真值。
2. 软性审美问题可能与硬事实问题一样阻断成稿，导致系统“认真检查但交不出正文”。
3. Best-of-N 已有后端候选接口，但关键场景的作者终选没有进入 React 主线。
4. POV 上下文是“注入全部事实后再补充角色已知信息”，不能真正隔离秘密。
5. 自动指标证明了质量下限，却没有证明读者偏好上限；真实人类盲测、模块消融和过约束标定尚未完成。
6. 系统记录 token，却缺少场景、章节和全书级成本预算与收益判断。
7. 当前最深自动验收固定在三章，且仓库最新真实模型三章 QA 中三场均未形成最终稿，验收步骤仍被标记为通过。

本设计要求暂停新增外围模块，把现有能力收敛为两条隔离通道：

- **创作生产通道**：优先交付可编辑、可恢复、可归档正文。
- **质量实验通道**：负责盲测、消融、模型对照和成本收益测量，不阻塞日常创作。

唯一成功标准不是接口全绿，而是五章真实正文全部进入后端权威归档，清空浏览器缓存并重启后仍可恢复，同时通过来源安全、硬事实连续性、成本上限和 30 组人类盲评。

## 2. 当前证据与问题基线

### 2.1 必须保留的现有优势

- 路由、服务、模型分层清楚，错误包络、幂等执行和 LLM 审计入口较统一。
- Bundle 快照、版本引用和哈希能够追溯一次生成实际消费的上下文。
- 场景管线已覆盖中性稿、风格稿、Best-of-N、批判修订、硬/软 QC、近终稿和归档。
- 事件日志、伏笔、张力、人物弧线、关系、主题、自我重复和上下文预算已有实现。
- 风格参考子系统具备导入、证据抽取、画像、绑定、RAG/few-shot、反抄袭和云端策略。
- 2026-07-02 审计修复已处理归档状态缺口、注入静默失效、向量工厂绕过、幂等错位、永久删除残留、审计膨胀和降级不可观测等问题。
- 当前定向验证为后端 134 项通过，React 63 项通过且构建成功。

### 2.2 当前不足与系统盲区

| 编号 | 问题 | 当前证据 | 影响 | 本设计处置 |
|---|---|---|---|---|
| G-01 | 验收成功语义错误 | 最新三章 QA 的“场景运行并归档”步骤为通过，但三场均无最终行且为 `human_review_required` | 测试绿灯不能代表作者拿到稿 | 建立 Outcome Gate；无正文即整次验收失败 |
| G-02 | 多套正文真值 | UI `done`、`wr-doc`、`FinalScene`、`archived`、章节审批并存 | 清缓存或跨页面后可能状态分裂、稿件不可恢复 | 后端 `FinalScene` 成为唯一权威；前端状态只派生 |
| G-03 | QC 过度阻断 | 真实模型三场均被硬/近终稿检查拦截 | 系统守住下限却无法交付 | 四级质量分类；只允许数据安全和硬事实阻断 |
| G-04 | 人类终选未接主线 | 后端有 style-candidates 读取/选择接口，React 无消费者 | Best-of-N 上界仍由机器决定 | 关键场景在后续 QC 前进入匿名候选终选 |
| G-05 | POV 信息泄漏 | `format_state_for_prompt` 先注入全部角色状态，再追加 POV 已知集 | 悬疑、多视角和信息差叙事可能被模型暗中污染 | 建立 POV 减法投影 |
| G-06 | 指标 Goodhart 化 | 同一批结构/AI 腔信号参与提示、排序、QC 和重写 | 文本可能结构正确但趋同、失去生命力 | 生产与实验隔离；人评和异源裁判决定默认策略 |
| G-07 | 评审模型不独立 | 默认/实际路由可让写作、批评、裁判落到同一模型族 | 相关性错误、自我认同闭环 | 关键评审使用异源角色槽；LLM 裁决不单独硬阻断 |
| G-08 | 长篇能力未证实 | 自动 harness 固定三章；五章北极星尚未落地 | 第 4–5 章后的漂移、重复、伏笔和成本未知 | 第一阶段强制 5 章 15 场；之后做 30 章耐久测试 |
| G-09 | 成本缺少经营视角 | `LlmCall` 有 token/延迟，系统审计不聚合总 token/价格/收益 | Best-of-N 与重试可能无上限烧调用 | 场景级 5× 上限、章节/书级预算、成本看板 |
| G-10 | 风格参考安全仍有边界 | 连续文本和专名检查强，但权属、结构性衍生相似和恶意文本指令未完整覆盖 | 版权、隐私和提示词注入风险 | 增加权属声明、来源隔离、结构相似人工门 |
| G-11 | 数据完整性依赖人工 | SQLite 未启用 foreign keys，删除依靠手工级联 | 新表和新路径可能重新产生孤儿 | 存量孤儿盘点后分阶段启用 FK；补备份恢复演练 |
| G-12 | 前端和服务体积过大 | 多个 1000–4000 行文件，单 JS chunk 约 1.22MB | 修改风险、上下文负担和启动成本增长 | 只沿本设计改动边界拆分，不做无关重写 |
| G-13 | 演示与真实功能混杂 | `ct-*` 仍以 tide 演示数据为完整真值 | 用户误把演示能力当真实能力 | 演示功能显式隔离；未接真页面不进入主验收 |

## 3. 目标、非目标与约束

### 3.1 目标

1. 从空白项目经真实 UI 和真实 LLM 完成五章、十五场正文。
2. 默认模式优先可靠成稿；关键场景允许严格模式。
3. 任何失败路径都保留最近有效正文，不允许“检查失败连稿一起消失”。
4. 后端最终稿是唯一事实来源，浏览器缓存只做临时留底。
5. 关键场景的 Best-of-N 总消耗不超过单发基线 5 倍。
6. 建立 30 组匿名 A/B 人类偏好评测，验证质量模块的实际收益。
7. 每个高成本质量模块都具备可关闭、可消融、可测边际收益的开关。

### 3.2 非目标

- 本阶段不建设多租户、团队协作、云同步、订阅计费或公共 SaaS。
- 本阶段不以一次运行写完 60 万字为验收目标。
- 本阶段不重写整个后端、数据库或 React 主线。
- 本阶段不新增新的文学理论模块；现有模块先证明价值。
- 本阶段不把 AI 评分包装成客观文学质量分。

### 3.3 已确认约束

- 产品目标：单作者本地工具 + 文学质量实验平台。
- 总体路线：渐进治理。
- 生产策略：默认可靠成稿，关键场景严格。
- 第一阶段：真实五章闭环。
- 人评方式：用户本人完成 30 组匿名 A/B 选择。
- 成本边界：关键场景端到端最多 5× 单发 token。

## 4. 核心设计原则

### 4.1 结果先于流程

任何测试、任务或页面不得在缺少非空正文时宣称“创作完成”。流程跑完只能叫“执行结束”，不能叫“成稿成功”。

### 4.2 硬事实与软质量分离

系统只对可证明的硬错误实施阻断。审美、节奏和结构建议默认不得阻断正文交付。

### 4.3 永远保留最近有效正文

每次场景运行、自动补丁、候选选择和人工编辑都必须维护 `SceneRunState.latest_valid_draft_row_id`。任何后续失败都回退到该版本。

### 4.4 机器守下限，人决定上限

机器只能淘汰空文本、结构化响应不可解析、来源安全 Q0 或确定性硬事实 Q1 的无效候选；关键候选的最终选择归作者。AI 腔或结构评分低不得单独删除候选。

### 4.5 生产与实验隔离

实验只能读取生产快照并生成独立实验产物，不能原地覆盖权威正文。只有经过人评和统计门槛的策略才能改变生产默认值。

### 4.6 成本是质量设计的一部分

所有候选、重试、批判、补丁和 QC 都计入同一个场景预算。不得通过把调用移到另一个节点绕过上限。

“单发基线”统一定义为：对同一冻结 Bundle、同一 writer 路由执行一次 N=1 正文生成，再执行一次确定性 Q0/Q1 与来源安全检查；不含软 QC、LLM 批判、补丁和重试。生产预算按生成调用的估算输入上限与配置输出上限，加上本地检查的实际 token（正常为 0）计算；实验报告同时记录实际 token。关键场景的 5× 上限以该基线为分母。

## 5. 目标架构

### 5.1 两条隔离通道

#### 创作生产通道

```text
雪花规划
  -> 场景执行契约
  -> 生成至少一份可编辑正文
  -> 硬事实与来源安全检查
  -> 软质量诊断
  -> 作者选择或编辑
  -> 后端原子归档
  -> 章节聚合
```

普通场景在生成一份有效正文后即可继续。标准场景可以自动生成最多三份，机器仅移除空文本、不可解析响应和 Q0/Q1 无效候选。关键场景暂停在作者终选；作者选择后先执行确定性 Q0/Q1 与来源安全检查，剩余预算允许时最多执行一次 LLM 批判和一次补丁。

#### 质量实验通道

```text
冻结的场景输入快照
  -> treatment/control 策略生成
  -> 匿名随机化
  -> 人类 A/B 选择
  -> 异源 AI 辅助分析
  -> 偏好率、显著性、token 与耗时报告
```

实验通道不写 `FinalScene`，只写实验产物。实验失败不影响生产状态。

### 5.2 唯一正文真值

正文生命周期统一为：

```text
SceneDraft(不可变版本)
  -> SceneRunState.current_* 指针
  -> 作者明确采纳
  -> FinalScene
  -> archive_final_scene 原子事务
  -> ChapterManuscript 聚合
```

约束：

- `SceneDraft` 版本不可原地覆盖。
- `FinalScene` 只由服务端归档事务创建或提升。
- `ChapterManuscript` 只聚合服务端已归档 `FinalScene`。
- React 的 `done` 只由服务端 `archived` 响应映射。
- `wr-doc` 缓存不得作为章节聚合来源。
- 归档失败时保留草稿、候选选择和失败原因，允许使用同一幂等键重试。

### 5.3 作者可见状态模型

现有内部状态暂不一次性迁移；API 新增稳定的 `author_state` 投影，React 只消费该字段。

| author_state | 含义 | 是否有稿 | 是否可编辑 | 是否可归档 |
|---|---|---:|---:|---:|
| `draft_ready` | 已有有效正文 | 是 | 是 | 是 |
| `quality_warning` | 有软质量问题 | 是 | 是 | 是 |
| `awaiting_author_choice` | 关键场景等待候选终选 | 是，至少两份 | 是 | 否 |
| `hard_blocked` | 有数据、安全或硬事实问题 | 是，保留最近有效稿 | 是 | 否 |
| `archived` | 后端权威归档完成 | 是 | 通过新修订版本编辑 | 已完成 |

API 必须同时返回：

- `latest_valid_draft_row_id`
- `current_final_scene_row_id`
- `blocking_findings`
- `quality_warnings`
- `recommended_actions`
- `can_edit`
- `can_archive`
- `recovery_action`

### 5.4 四级质量分类

| 级别 | 范围 | 行为 |
|---|---|---|
| Q0 | 数据持久化、来源泄漏、血缘缺失、安全错误 | 阻断归档，保留正文 |
| Q1 | 有确定证据的硬事实冲突 | 阻断自动归档，交作者确认或修订 |
| Q2 | 结构、节奏、钩子、代价、关系转折不足 | 正文照常交付，醒目警告 |
| Q3 | AI 口癖、比喻、句式、风格与实验指标 | 只进入诊断，不改变状态 |

分类纪律：

- 单个 LLM 判断不能直接生成 Q0/Q1。
- Q1 必须包含权威事实、冲突正文、证据定位和置信度。
- 无法给出确定证据时自动降为 Q2。
- 同一问题最多自动修订两次；仍失败时停止消耗，交付当前最好稿。
- QC 超时、模型不可用或补丁失败时，不撤销已有正文。

### 5.5 Best-of-N 作者终选

关键场景执行顺序改为：

```text
候选生成
  -> 确定性坏稿淘汰
  -> 全文匿名展示
  -> 作者终选
  -> 对选中稿做确定性硬检查，并在预算内最多做一次批判修订
  -> 硬检查
  -> 归档
```

候选 UI 要求：

- 展示完整正文，不只展示预览。
- 默认隐藏模型、顺序和机器分数。
- 支持并排、单篇沉浸阅读和句段差异定位。
- 支持整稿选择；局部拼接作为后续增强，不阻塞第一阶段。
- 记录选择、放弃、无明显差异和选择耗时。
- 机器分数只用于排序和标注，不删除仅因分数低而被判为有效的候选。

成本分配：

- 普通场景：N=1。
- 标准场景：先 N=2，低分散时最多补到 N=3。
- 关键场景：先 N=3，低分散时最多补到 N=5。
- 候选、修订、硬检查和失败重试合计不得超过 5× 单发 token。
- 预算接近上限时，优先保留候选生成和硬检查，取消重复软评审。

### 5.6 POV 减法投影

新增 `PovKnowledgeProjection` 服务，生成时只返回以下信息：

1. POV 角色亲历、被告知或已在事件日志中明确标记为 `suspected` 的事实；不得在投影时临时推理新的秘密。
2. 当前场景所有角色都可观察到的公开事实。
3. 世界公共规则和当前地点可感知状态。
4. 不泄漏的写作约束，例如“某角色在隐瞒信息”，但不得暴露被隐瞒内容。

禁止直接把全角色权威状态注入 POV 写作提示词。全量权威状态仅供硬 QC 使用。

投影需要支持：

- `known`
- `believed_false`
- `suspected`
- `unknown`
- `public`
- `secret_owner`

对历史事件缺少知识归属时，采用保守策略：只注入公共事实和 POV 直接参与事件，不把缺少归属的秘密默认为已知。

### 5.7 模型独立性

LLM 角色槽至少区分：

- `writer_primary`
- `writer_explorer`
- `critic_independent`
- `judge_advisory`
- `extractor_fast`

生产默认要求 `critic_independent` 与 `writer_primary` 至少在模型或提供商之一不同。若无法满足，评审结果只能是 Q2/Q3 建议。

确定性规则和来源安全是唯一可以不依赖异源模型的硬门。

### 5.8 成本治理

基于现有 `LlmCall.prompt_tokens/completion_tokens/total_tokens/latency_ms` 建立聚合，不复制调用日志。

新增可配置价格快照，至少包含：

- provider/model
- 生效时间
- 输入单价
- 输出单价
- 币种
- 是否为估算

必须展示：

- 单次运行总 token、费用和耗时。
- 单场、单章、单书累计。
- 候选生成、QC、修订、评审各阶段占比。
- 5× 上限使用率。
- 因低分散、失败重试和重复 QC 产生的额外成本。

硬行为：

- 预算耗尽后停止新调用，返回已有最佳稿。
- 允许取消尚未开始的新节点。
- 已完成调用和草稿不可因取消而回滚。
- 无法获取 provider usage 时使用本地 token 估算，并标记为估算值。

### 5.9 来源安全与不可信文本

保留现有连续片段、专名、动态来源画像和 `local_only` 策略，并增加：

- 导入时记录用户对文本拥有分析和发送权限的声明。
- 所有参考文本进入 LLM 前使用明确的“非指令数据”边界封装。
- 过滤参考文本中的系统提示词、工具调用、忽略前文等指令模式；原文仍可本地保存，但不作为可执行指令发送。
- 关键成稿增加“桥段组合相似风险”人工检查卡，不自动作法律结论。
- 来源安全检测器与写作模型分离，失败时不得把未检查正文标为安全。

## 6. 数据与接口设计

### 6.1 第一阶段最小数据改动

优先复用现有表，避免无必要迁移。

#### SceneRunState

新增字段：

- `latest_valid_draft_row_id: str | null`
- `author_state: str | null`，迁移期可先由 API 计算，稳定后再持久化
- `run_policy: reliable | strict | auto`
- `scene_token_budget: int | null`
- `scene_tokens_used: int`

#### QcReport.issues_json

每条 issue 统一结构：

```json
{
  "issue_key": "string",
  "quality_level": "Q0|Q1|Q2|Q3",
  "blocking": true,
  "authority_ref": "event/fact/rule/source ref",
  "evidence_spans": [],
  "confidence": 1.0,
  "recommended_action": "string",
  "source": "deterministic|llm_advisory|human"
}
```

#### HumanReviewEvent

候选终选复用该表，`details_json` 统一包含：

- `gate_type=style_candidate_selection`
- `candidate_row_ids`
- `selected_row_id`
- `decision_status`
- `blinded_order`
- `tokens_used`

#### LlmCall

继续使用现有 token 与延迟字段。增加聚合服务和价格快照，不向每条调用写死价格。

### 6.2 第二阶段实验数据

质量实验通道新增以下三张表：

#### EvaluationExperiment

- `experiment_id`
- `name`
- `hypothesis`
- `treatment_policy_json`
- `control_policy_json`
- `status`
- `created_at`

#### EvaluationPair

- `pair_id`
- `experiment_id`
- `scene_snapshot_hash`
- `left_artifact_ref`
- `right_artifact_ref`
- `blind_mapping_encrypted_or_hidden`
- `token_cost_json`

#### EvaluationVote

- `vote_id`
- `pair_id`
- `choice=left|right|tie`
- `reviewer_ref`
- `duration_ms`
- `created_at`

映射在投票前不得通过 API 返回给前端。

### 6.3 核心接口

保留现有接口并补齐稳定契约：

- `GET /api/v1/scenes/{scene_id}/author-state`
- `POST /api/v1/scenes/{scene_id}/run`，接受 `run_policy`
- `GET /api/v1/scenes/{scene_id}/style-candidates`
- `POST /api/v1/scenes/{scene_id}/style-candidates/{row_id}/select`
- `POST /api/v1/scenes/{scene_id}/resume-after-selection`
- `POST /api/v1/scenes/{scene_id}/archive`
- `GET /api/v2/projects/{project_id}/cost-summary`
- `POST /api/v1/evaluation-experiments`
- `GET /api/v1/evaluation-experiments/{id}/next-pair`
- `POST /api/v1/evaluation-pairs/{id}/vote`
- `GET /api/v1/evaluation-experiments/{id}/report`

所有写接口必须使用操作意图级幂等键。候选选择和归档必须可安全重放。

## 7. 错误处理与恢复不变量

以下不变量任何实现不得破坏：

1. 已经持久化的有效正文不会因后续 QC、评审、索引或聚合失败而被删除。
2. `hard_blocked` 仍必须返回可查看、可导出的最近有效正文。
3. 候选生成部分成功时，已有候选可进入作者选择，不要求全部成功。
4. 作者完成选择后，重复提交相同选择返回相同结果。
5. 归档事务要么完整成功，要么保持未归档草稿状态，不能出现前端完成、后端缺稿。
6. 章节聚合失败不回滚已经归档的场景。
7. 事件抽取、向量索引、主题、张力和漂移等辅助模块失败只产生可观察降级，不撤销成稿。
8. 来源安全未完成时可以保存草稿，但不能标记为已安全归档。
9. 预算耗尽时返回当前最佳版本与明确原因，不再继续自动调用。
10. 清除浏览器缓存后，所有已归档正文和作者决策都能从后端恢复。

## 8. 分阶段实施方案

### Wave 0：建立真实结果门禁

目标：先让测试能够正确失败。

实施内容：

1. 将三章 harness 参数化为章节数，第一阶段固定运行 5 章、每章 3 场。
2. 新增结果级断言：五章、十五场均有非空 `FinalScene` 且为后端 `archived`。
3. 删除“步骤完成即通过”的判断；若任何场景无最终稿，进程退出码非零。
4. 空章节不得生成正常文学分数或“暂无明显风险”。
5. 测试必须从空白项目走真实雪花 UI、物化、场景执行、候选选择、归档、章节聚合。
6. 保留 API 深链作为诊断 lane，但不能替代 UI 北极星。
7. 输出每场 token、耗时、重试、阻断、最终稿和来源安全结果。

主要文件：

- `scripts/run-currentdb-three-chapter-qa.cjs`
- `scripts/run-longzu-full-cloud-qa.cjs`
- `docs/QA-五轮工作流-提示词.md`
- `scripts/playwright_audit_summary.py`
- `backend/tests/test_playwright_audit_summary.py`

完成门：旧的“无稿但通过”样本必须被新 harness 判为失败。

### Wave 1：统一正文真值和归档

目标：消除前端/缓存/后端多套完成态。

实施内容：

1. 建立 `author_state` 投影服务。
2. 在每次成功生成或人工保存后维护最近有效正文指针。
3. 归档改为单一服务入口，前端不再先本地置 `done`。
4. `ws-scene-run` 归档后必须重新拉服务端状态。
5. `wr-doc-store` 启动时服务端优先；本地较新时创建冲突副本并让作者选择。
6. `ws-manuscripts` 只读取后端章节聚合。
7. 增加清 localStorage、重启服务、重新加载后的恢复 E2E。

主要文件：

- `backend/src/novel_system/services/orchestrator.py`
- `backend/src/novel_system/services/archiver.py`
- `backend/src/novel_system/services/chapter_manuscripts.py`
- `backend/src/novel_system/services/chapter_state.py`
- `backend/src/novel_system/api/routes/scenes.py`
- `backend/src/novel_system/api/routes/chapter_manuscripts.py`
- `frontend-react/src/ws-scene-run.jsx`
- `frontend-react/src/wr-doc-store.jsx`
- `frontend-react/src/ws-manuscripts.jsx`

完成门：前端显示完成的场景必须存在可回放的后端归档稿；缓存清除不丢稿。

### Wave 2：QC 分级和可靠成稿模式

目标：软质量问题不再让作者无稿可用。

实施内容：

1. 增加统一 issue 分类器，把现有 issue_key 映射到 Q0–Q3。
2. 确定性证据不足的 LLM issue 自动降为 Q2。
3. 统一硬/软 QC、near-final、style gate 和来源安全的阻断策略。
4. 自动修订最多两次，达到上限后返回最佳稿和作者行动建议。
5. 所有早退结果都携带 `latest_valid_draft_row_id` 和 `author_state`。
6. React 将“无法继续”和“已有稿但建议修改”分开展示。
7. 默认可靠模式允许带 Q2/Q3 归档；严格模式可要求作者显式接受 Q2。

主要文件：

- `backend/src/novel_system/services/qc_engine.py`
- `backend/src/novel_system/services/near_final.py`
- `backend/src/novel_system/services/scene_generation.py`
- `backend/src/novel_system/services/narrative_event_log.py`
- `backend/src/novel_system/services/source_safety.py`
- `frontend-react/src/ws-scene-run.jsx`
- `frontend-react/src/ws-review.jsx`
- `frontend-react/src/ws-quality.jsx`

完成门：使用当前真实模型重复旧三章场景时，至少能交付三份可编辑正文；只有真实 Q0/Q1 能阻断归档。

### Wave 3：Best-of-N 人类终选与 5× 预算

目标：把质量上界真正交给作者。

实施内容：

1. 关键场景生成候选后暂停编排，不提前自动选择并继续归档。
2. 复用后端 style-candidates 接口，返回完整正文和盲化元数据。
3. React 新增候选终选视图。
4. 作者选择后通过 `resume-after-selection` 从批判修订/硬检查继续。
5. 将低分散补救改为渐进补候选，不能一次生成后再无上限重试。
6. 所有调用计入场景总预算；达到 5× 立即停止。
7. 标准场景保留机器下限选择，关键场景强制作者终选。

主要文件：

- `backend/src/novel_system/services/orchestrator.py`
- `backend/src/novel_system/services/scene_generation.py`
- `backend/src/novel_system/services/scene_criticality.py`
- `backend/src/novel_system/api/routes/scenes.py`
- `frontend-react/src/ws-scene-run.jsx`
- `frontend-react/src/ws-signals.jsx`

完成门：关键场景未选择前不可归档；选择后可安全续跑；总 token 不超过基线 5×。

### Wave 4：POV 减法投影

目标：模型从输入层就看不到 POV 不应知道的秘密。

实施内容：

1. 扩展事件知识归属和公开级别。
2. 实现 POV 投影服务，替换写作提示中的全量状态注入。
3. 硬 QC 仍读取全量权威状态。
4. 加入秘密、错误信念、怀疑和公共事实 golden 用例。
5. 使用悬疑样本做真实 LLM 对照，检查角色是否提前行动或暗示秘密。

主要文件：

- `backend/src/novel_system/services/narrative_event_log.py`
- `backend/src/novel_system/services/prose_event_extractor.py`
- `backend/src/novel_system/services/bundle_builder.py`
- `backend/tests/test_narrative_event_log.py`
- `backend/tests/test_consistency_validation_realistic.py`

完成门：POV 提示词快照不含秘密正文；硬 QC 仍能利用全量事实发现冲突。

### Wave 5：质量实验室与人类盲评

目标：证明哪些模块真的提升偏好。

实施内容：

1. 复用现有 `best_of_n_blind_eval` 逻辑，增加数据库实验实体和简单 React 投票页。
2. 首轮建立 30 个有效对比对：Best-of-N 终选策略 vs 单发基线。
3. 匿名随机左右位置；投票前不返回映射。
4. 报告偏好率、平局率、无对比率、精确二项检验、token 倍率和耗时倍率。
5. treatment 至少赢 21/30 个有效对比，且双侧精确检验 `p < 0.05`，才允许作为默认严格模式。
6. 依次消融自动批判、风格 few-shot/RAG、漂移修正和结构约束强度。
7. 任何未通过人评的高成本模块默认改为可选。

主要文件：

- `backend/src/novel_system/services/best_of_n_blind_eval.py`
- `backend/src/novel_system/tools/best_of_n_blind_eval.py`
- `backend/src/novel_system/api/routes/literary_eval.py`
- 新增实验服务、路由与最小投票页面

完成门：产出可复算的 30 组投票报告，并给每个被测模块明确保留、降级或关闭结论。

### Wave 6：成本、模型独立性和运维可见性

目标：知道每一分质量提升花了多少成本。

实施内容：

1. 建立 token/价格聚合服务和成本页。
2. 配置 writer、critic、judge 独立角色槽。
3. 对同模型自评显式标记 `correlated_judge=true`。
4. 增加运行取消、预算耗尽和失败恢复测试。
5. 在编排信号面板显示降级槽、成本、预算和裁判独立性。

完成门：任意场景可解释总成本、各阶段占比、是否超预算以及评审是否独立。

### Wave 7：长篇耐久、安全和结构收敛

目标：五章通过后再验证规模和降低维护风险。

实施内容：

1. 将五章 harness 扩展为 30 章耐久测试，允许使用成本较低模型，但必须走真实持久化和重启。
2. 每五章记录连续性、声音漂移、跨章重复、伏笔债、数据库大小、查询延迟和平均成本。
3. 对参考文本增加不可信内容封装和导入权属记录。
4. 盘点存量孤儿，增加修复迁移，再评估启用 SQLite foreign keys。
5. 增加数据库备份、WAL 一致性备份和恢复演练脚本。
6. 沿本轮改动边界拆分 `orchestrator`、`ws-scene-run`、`ws-snow` 等大文件。
7. 对 React 做路由级懒加载，目标主 chunk 小于 500KB gzip 前体积告警阈值。
8. 未接真实数据的演示页面从普通作者导航移除或显式标注实验性。

完成门：30 章全部后端归档；在第 5、10、20、30 章后执行清缓存和重启均能恢复；Q0/Q1 与来源泄漏均为 0；第 21–30 章平均 `tokens_per_archived_scene` 不超过第 1–10 章的 1.5 倍；目录、场景状态和章节成稿三个核心读取接口的 p95 响应均低于 2 秒；不存在未处理的高严重度声音漂移或跨章自我重复。

## 9. 验证体系

### 9.1 单元测试

- Q0–Q3 分类极性和证据要求。
- `author_state` 映射。
- 最近有效正文回退。
- 候选预算计算和渐进补候选。
- POV 知识投影。
- 价格与 token 聚合。
- 盲化映射不泄漏和投票统计。

### 9.2 集成测试

- 生成成功、QC 失败后正文仍存在。
- 候选部分失败仍可终选。
- 选择接口幂等。
- 归档接口幂等且原子。
- 章节聚合失败不回滚场景归档。
- 来源检查失败时草稿可保存但不可安全归档。
- 清缓存和重启后的服务端水合。
- writer 与 critic 同模型时，所有由 LLM 产生的阻断建议自动降为 Q2；确定性 Q0/Q1 不受影响。

### 9.3 真实模型门禁

真实 LLM 门禁不进入普通 PR CI，但必须作为发布前门：

1. 固定原创五章基准，不使用参考书，验证纯主链。
2. 固定一套有授权或公版参考文本，验证风格参考与来源安全。
3. 每次路由、提示词、QC 或 Bundle 结构重大变更后重跑。
4. 报告必须保存正文、快照哈希、调用路由、token、耗时、状态和阻断证据。
5. 无正文、空章节、未归档或丢稿均为失败，不能用评分补偿。

### 9.4 五章发布门

五章基准固定为：

- 5 章。
- 每章 3 场，共 15 场。
- 每章 2000–4000 个中文字符。
- 总正文 10000–20000 个中文字符。
- 至少 3 个关键场景进入作者候选终选。

必须同时满足：

- 15/15 场有非空服务端正文。
- 15/15 场为后端权威归档态。
- 5/5 章聚合正文与场景拼接一致。
- 清 localStorage 并重启后内容与作者决策均恢复。
- Q0/Q1 未解决项为 0。
- 来源安全泄漏为 0。
- 任一关键场景不超过单发 token 的 5×。
- 普通场景至少 90% 在第一次任务中产生可编辑正文；本次 15 场基准按至少 14/15 场计算。
- 30 组有效盲评达到 21 胜且双侧精确检验 `p < 0.05`，否则高成本策略不升级为默认。
- 第 4–5 章硬事实 Q0/Q1 为 0；不得存在未被作者接受的高严重度声音漂移；跨章自我重复服务不得报告高严重度命中。

“通过”不使用模糊的综合分抵消红线：以上任一项失败，五章发布门失败并输出具体章节、场景和证据。

## 10. 可观测性与产品指标

必须新增以下指标：

- `draft_delivery_rate`
- `archive_success_rate`
- `draft_recovery_success_rate`
- `hard_block_rate`
- `soft_warning_rate`
- `human_takeover_rate`
- `candidate_dispersion`
- `candidate_preference_rate`
- `tokens_per_archived_scene`
- `cost_per_archived_chapter`
- `retry_cost_ratio`
- `degraded_slot_rate`
- `pov_leak_findings`
- `source_safety_block_rate`
- `cross_chapter_continuity_error_rate`

北极星指标为 `archived_publishable_chapters_per_100k_tokens`，同时看结果、质量和成本，避免单独优化调用成功率或内部质量分。

## 11. 禁止性规则

实施 AI 必须遵守：

1. 不得新增文学模块来绕开五章闭环失败。
2. 不得让空正文、空章节或未归档状态进入成功报告。
3. 不得把 LLM 单独判断升级为硬阻断。
4. 不得以删除旧稿的方式解决候选或冲突。
5. 不得继续让 localStorage 成为权威成稿源。
6. 不得通过增加重试次数解决低分散或质量不足。
7. 不得在没有人评证据时宣称某模块提升文学质量。
8. 不得在一个提交中同时做主链行为修改和无关大规模重构。
9. 不得对用户导入文本默认拥有云端发送权。
10. 不得在未盘点存量孤儿前直接启用 SQLite foreign keys。

## 12. AI 执行方式

执行顺序必须严格按 Wave 0 → 7。每个 Wave 使用独立实施计划、独立测试和独立提交，不允许跨 Wave 提前实现。

每个 Wave 的执行模板：

1. 读取本设计和涉及文件。
2. 写出当前行为的失败测试。
3. 实现最小改动。
4. 运行定向测试。
5. 运行相关回归测试。
6. 对涉及 UI 的改动执行 React 测试、构建和真实浏览器走查。
7. 更新五章验收工装或进度账本。
8. 检查工作树，只提交本 Wave 文件。
9. 输出证据：命令、通过数、失败数、真实产物路径和剩余风险。

在 Wave 0–3 完成前，禁止把工作重点转移到样式美化、控制塔演示或新文学指标。

## 13. 风险与缓解

| 风险 | 缓解 |
|---|---|
| QC 放宽后明显坏稿被归档 | 只放宽 Q2/Q3；Q0/Q1 仍阻断；作者可启用严格模式 |
| 后端真值切换导致旧 localStorage 稿丢失 | 首次水合做双向比对，所有冲突先留副本，再由作者选择 |
| 候选终选增加作者负担 | 只对关键场景强制；普通/标准场景自动继续 |
| 5× 上限降低关键场景质量 | 先测候选收益；预算优先用于探索而非重复评审 |
| POV 减法导致上下文过少 | 公共事实、直接参与事件和合理推断分别建 golden 测试 |
| 异源裁判提高成本 | 只用于关键场景和实验；不能独立硬阻断 |
| 五章真实模型测试波动 | 冻结输入、记录路由与快照、运行多次并分离模型失败与系统失败 |
| 启用 FK 暴露存量孤儿 | 先盘点、修复、验证，再分阶段开启 |
| 设计范围过大 | 每个 Wave 独立门禁；前一 Wave 未完成不得开始后一 Wave |

## 14. 最终交付物

完成本设计后仓库应具备：

1. 可正确失败的五章结果验收脚本。
2. 服务端权威成稿和统一作者状态。
3. 不会因软质量问题丢稿的可靠成稿模式。
4. 关键场景匿名候选终选界面。
5. POV 减法知识投影。
6. 30 组人类盲评实验和统计报告。
7. 场景、章节、全书级 token 与成本看板。
8. 五章完整成稿、来源安全报告、连续性报告和恢复证据。
9. 30 章耐久测试与数据库增长报告。
10. 每个高成本模块明确的保留、可选、降级或移除结论。

## 15. 最终决策标准

系统是否进入下一阶段，不看代码量、接口数或测试总数，只看以下问题：

1. 作者能否从空白项目稳定拿到五章可发表候选稿？
2. 任何失败后正文是否仍然存在并可接管？
3. 后端是否拥有唯一、可恢复的权威正文？
4. Best-of-N 是否在人类盲评中值得最多 5× 成本？
5. 第 4–5 章是否满足 Q0/Q1 为 0、无未接受的高严重度声音漂移、无高严重度跨章重复？
6. 每一个高成本模块是否能说清楚自己的边际贡献？

任何一个问题回答为否，就继续修结果闭环，不新增外围能力。
