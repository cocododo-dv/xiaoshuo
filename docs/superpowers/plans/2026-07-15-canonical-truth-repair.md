# AI 小说系统权威真相链修复计划

> 状态：本轮功能与迁移已验收；全库发布预检受历史孤儿数据阻断
> 目标：修复跨章节叙事顺序、作者稿与权威正文分裂、章节聚合乱序，以及自动重写/归档检查对象错误；所有结论必须由可复算测试和数据库状态证明。

## 1. 本轮范围

本轮只处理会直接改变小说正文或长篇连续性的高优先级缺陷：

1. 项目级叙事事件必须按章节顺序与章节内场景顺序回放，不能再把章节内 `scene_seq` 当作全书时间轴。
2. 章节正文必须按 `SceneCard.scene_seq` 聚合，不能依赖内存行 ID 的字典序。
3. scene 级 `AuthorDraft` 必须有显式、可审计、可并发保护的“提升为权威正文”入口。
4. 来源安全、确定性连续性与文学质量检查必须绑定实际将被归档的文本；自动重写不得使用硬编码质量分。
5. 作者稿提升后，FinalScene、SceneMemory、ChapterMemory、叙事事件和终审正文哈希必须处于同一可解释版本链。

本轮不处理：多人鉴权、租户隔离、持久化 worker、移动端、Vue 下线、全站状态投影重构。这些保留为下一批，避免把正文正确性修复与平台化改造混在一起。

## 2. 不变量

实施和验收均以以下不变量为准：

- **正文唯一性**：`SceneRunState.current_final_scene_row_id` 指向当前权威场景正文；下游 SceneMemory、ChapterMemory 必须能追溯到该版本。
- **顺序唯一性**：叙事位置动态定义为 `(ChapterGoal.display_order NULLS LAST, ChapterGoal.chapter_id, SceneCard.scene_seq, SceneCard.scene_id)`；`NarrativeEvent.scene_seq` 只保留兼容和审计含义。
- **检查对象唯一性**：门禁记录的 `content_hash` 必须等于实际归档/提升文本的哈希。
- **作者意图显式**：保存草稿不等于定稿；只有显式 promote 才改变 FinalScene。
- **并发失败关闭**：草稿 revision 或当前 FinalScene 指针不匹配时返回 409，不允许覆盖较新正文。
- **叙事同步失败关闭**：作者修改可能改变事实但没有完成事件对账时，不得静默沿用旧事件。
- **历史不可覆盖**：提升创建新的不可变 FinalScene，旧正文保留并标记为 superseded；现有自动重写回滚只允许重新指向已存在的不可变 FinalScene，不得覆写历史正文。本轮不新增作者稿回滚 API。

## 3. 修复方案

### A. 跨章节叙事顺序

不持久化第二套易漂移的全局序号。新增内部 `NarrativeCursor`/位置解析器：

- 通过 scene_id 解析章节 `display_order`、场景 `scene_seq` 和稳定 scene_id。
- 项目级事件查询 join `ChapterGoal` 与 `SceneCard`，按复合位置排序。
- “当前场之前”使用严格小于当前复合位置；“截至当前场”使用小于等于。
- Bundle、POV 知识、关系矩阵、因果与伏笔查询改传 scene_id/游标；旧 `up_to_scene_seq` 只保留单章兼容入口，不再供生产内部调用。
- 事件查询通过 `NarrativeEvent -> SceneCard -> ChapterGoal` 重新解析当前目录位置；第一版不伪造事件版本或来源。

迁移只增加必要索引并修复可确定推导的历史位置字段，不新增会与目录重排漂移的 `narrative_order`。

### B. 章节聚合顺序

`Aggregator.run_final_aggregate` 使用 `SceneMemory -> SceneCard` join，并按：

1. `SceneCard.scene_seq ASC`
2. `SceneCard.scene_id ASC`

聚合。孤立 SceneMemory 不得悄悄混入正文，应返回可诊断状态或在预检中报告。

### C. 作者稿提升为权威正文

新增：

`POST /api/v1/author-drafts/{draft_id}/promote-canonical`

请求必须包含：

- `base_revision_no`
- `expected_current_final_scene_row_id`（允许首次定稿为 null）
- `narrative_effect`：第一版仅接受 `facts_unchanged`；无法确认事实未变时返回明确 409，不能假装事件已同步
- `accepted_warning_codes`
- `X-Idempotency-Key`

第一版仅支持 `object_type=scene`；chapter/project 稿件返回明确 409。多场章节稿在没有可靠场景边界前不能直接写入权威正文。

事务顺序：

1. 只读校验草稿 current 状态、revision 基线和 FinalScene 指针基线，不写权威状态。
2. 服务端把富文本转换为安全的规范纯文本，拒绝空正文，并计算 content hash。
3. 对实际正文执行统一最终文本门禁。
4. 门禁通过后再执行草稿 revision CAS 与 FinalScene 指针 CAS，创建不可变的新 FinalScene，记录父版本、作者 draft/revision 和 content hash；旧当前版本标记 superseded。
5. 通过 Archiver 重建 active SceneMemory 与 rolling note。
6. 通过 Aggregator 重建 ChapterMemory；旧终审 read-confirmation 因正文 hash 改变而自然失效。
7. `narrative_effect=facts_unchanged` 时原样保留现有 NarrativeEvent，并写入针对新正文 hash 的作者确认；通过 SceneRunState 的 narrative sync 指针证明这些事实已被作者确认可沿用。不得复制事件破坏 causal predecessor 引用，也不得把旧事件伪造为从新正文重新提取。
8. 写入 OperationLog 审计记录并返回完整版本链；本轮不新增第二套作者事件表。

若未来支持 `requires_reconcile`，必须先实现事件差异确认与后续生成硬阻断；本轮不得用默认关闭且 advisory 的 prose extractor 冒充已同步。

### D. 统一最终文本门禁

新增只读 `FinalTextGateService`，输入 scene、实际 content 和 source bundle，统一返回：

- `content_hash`
- `source_safety`
- `continuity`
- `literary_quality`
- `archive_blockers` / `promotion_blockers`
- `warnings`

规则：

- 来源泄漏和确定性 Q0/Q1 连续性问题阻断归档。
- 文学 Q2/Q3 对普通作者定稿只警告，不得冒充 Q0/Q1 阻断；`accepted_warning_codes` 在本轮只作为审计备注，不能绕过任何硬门禁。
- auto-rewrite 属于机器自动提升，必须使用实际候选文本的真实信号分数达到阈值，不能由作者警告豁免。
- candidate 持久化后立即检查；promote 前再次检查并比对 content hash，防止 TOCTOU。
- Archiver 在写 memory/status 前执行最终兜底门，覆盖 orchestrator、adopt、auto-rewrite promote 和 rollback 路径。

自动重写分数从候选的实际 literary signals 计算：

- `ending_drive`：实际 `ending_drive.score`
- `choice_pressure`：实际 `choice_pressure.score`
- `character_scene_core`：结构维度的明确聚合值，并在响应中保留构成项

删除 `0.86/0.82/0.83` 硬编码通过分。

## 4. 数据迁移与兼容

新增两级 Alembic 迁移：

- `20260715_0068`：章节/场景/事件复合查询索引；回填可由现有所有权唯一推导的 `project_id`、空章节顺序和事件局部 `scene_seq` 兼容快照；事件身份冲突时明确阻断迁移。
- `20260715_0069`：`FinalScene` 的 content hash、父/后继版本和作者 draft/revision 来源；`AuthorDraft` 最近提升指针；`SceneRunState` 叙事同步状态与目标正文指针。
- 第一版不增加 `NarrativeEvent.active_flag/source_final_scene_row_id`：`facts_unchanged` 明确保留原事件，`requires_reconcile` 明确 409；真正的事件差异确认与版本化留到后续工作流，避免伪造来源。

迁移必须幂等、SQLite 可执行、支持 downgrade。旧数据库升级后不改变任何当前正文指针，不伪造无法可靠回填的事件 provenance。

兼容约束：

- 现有 `adopt-current` 继续工作，但所有归档最终经过同一门禁。
- 现有旧事件 API 响应保留 `scene_seq`；新运行时边界改用 `scene_id`，旧单章 `scene_seq` 调用仍兼容，多章歧义调用明确拒绝。
- 未显式 promote 的 AuthorDraft 继续只是可编辑稿，不自动改变 FinalScene。

## 5. 验收矩阵

### 自动化验收

1. **跨章回放**：第一章事实在第二章第一场之前可见；第二章事件不会倒灌到第一章。
2. **同序号隔离**：不同章节的 `scene_seq=1` 不再互相覆盖或被视为同一场。
3. **目录重排**：改变 chapter display_order 后，动态回放顺序随目录变化，无第二套序号漂移。
4. **聚合顺序**：故意使用逆字典序/UUID scene_id，结果仍严格按 scene_seq。
5. **作者提升成功**：新 FinalScene、SceneMemory、ChapterMemory 内容和 hash 一致，旧 FinalScene 保留且 superseded。
6. **并发保护**：过期 revision、过期 FinalScene 指针、重复幂等键均得到确定结果。
7. **稿件类型保护**：chapter/project promote 明确拒绝，不产生半成品正文。
8. **事件沿用边界**：`facts_unchanged` 提升后事件行数、事件 ID 与 causal predecessor 引用不变，sync 指针指向新正文；`requires_reconcile` 不产生任何正文或记忆副作用。
9. **安全阻断**：作者稿和 auto-rewrite 候选含受保护文本时均不能归档。
10. **候选实际评分**：弱候选不能靠硬编码分通过；响应中的分数可由候选文本独立复算。
11. **TOCTOU**：candidate gate 后篡改 SceneDraft，promote 必须重扫并拒绝。
12. **归档兜底**：直接调用 Archiver 也无法绕过 Q0/Q1。

### 回归验收

- 后端：叙事事件、POV、关系矩阵、聚合、author-draft、scene adopt、auto-rewrite、archive/checkpoint 定向套件全部通过。
- 前端：WrDocs/写作房间定向测试、React 全量测试、生产 build 通过。
- 迁移：空库 `upgrade head`、现有库 `0066/0067 -> 0069`、`0069` downgrade/re-upgrade、schema drift guard、database preflight 通过。
- 数据：升级前后当前 FinalScene 指针不变；无新增 orphan；active SceneMemory 每场最多一条。

## 6. 验收证据

最终报告至少记录：

- 执行命令、退出码、测试数与耗时。
- Alembic current/head。
- 迁移前后表结构与关键行数。
- 每个验收用例对应的测试名。
- 未完成项、明确阻断原因和不允许宣称的结论。

验收状态按“本轮修复是否正确”和“整个历史数据库是否满足发布门槛”分别记录；任何未完成或被阻断的门槛都必须显式保留，不能用定向测试通过替代全量结论。

## 7. 本次验收结果（2026-07-15）

### 7.1 结论

- **本轮功能修复：通过。** 跨章节叙事位置、章节聚合、作者稿权威提升和最终文本门禁均已落地，定向高风险套件通过。
- **本轮数据库迁移：通过。** 迁移副本演练、降级/再升级和线上库 `0066 -> 0069` 均成功，核心正文指针、行数与内容哈希未发生非预期改变。
- **全库发布预检：阻断。** 历史库已有 `209` 条 `llm_call_attempts` 缺失父级 `llm_calls`；全库 `PRAGMA foreign_key_check` 还发现 `297` 条 `snowflake_revision_links` 历史孤儿。它们不是本轮迁移产生，但在完成取证、导出和处置前，不能宣称数据库达到全局发布就绪。
- **后端全量回归：未完成。** 共收集 `2567` 个测试，运行约 `904` 秒后因验收时间窗超限终止；终止前没有失败输出，但这不等于全量通过。

### 7.2 自动化证据

| 验收面 | 命令/范围 | 结果 |
|---|---|---|
| 跨章叙事链 | `test_narrative_order_cross_chapter`、event log、POV、reconciliation、bundle、causal recall、prose extraction | `79 passed`，`16.39s` |
| 目录动态重排 | `test_narrative_order_cross_chapter.py` | `8 passed`；包含重排目录但不改写事件的断言 |
| 作者稿权威提升 | canonical manuscripts、author drafts/revisions、chapter manuscripts、adopt/archive | `63 passed`，`32.51s` |
| 最终文本门禁 | auto-rewrite、adopt/archive、QC、source safety、literary quality、orchestrator | `197 passed`，`98.26s` |
| 迁移预检代码 | database preflight、metadata isolation、Alembic env | `37 passed`，`15.43s` |
| 前端回归 | `npm test -- --run` | `139 passed`，16 个测试文件，`5.77s` |
| 前端生产构建 | `npm run build` | 退出码 `0`，98 modules，`3.72s`；保留既有动态导入和大 chunk 警告 |
| 静态核对 | `python -m compileall -q src`、`git diff --check` | 退出码 `0`；仅有既有换行符提示 |
| 后端全量 | `python -m pytest -q` | 收集 `2567` 项；约 `904s` 超时终止，未形成通过/失败结论 |

上述套件存在覆盖交集，测试数量不能简单相加作为“总通过数”。

### 7.3 迁移与数据证据

- 线上库迁移前只读备份：`.codex-run/live-before-0069-20260715.db`。
- 备份 SHA-256：`5862b6f73a1bc2f807a4508729d38d78a829f99e3676062c3929d66eff4218fd`；`page_count=6210`；完整性检查与复核哈希均通过。
- 迁移副本成功执行 `0066 -> 0069`，并成功执行 `0069 -> 0068 -> 0069`；线上库随后成功升级，`alembic current` 与 `alembic heads` 均为单一 `20260715_0069` head。
- 升级前后核心行数一致：`final_scenes=2`、`scene_run_states=36`、`author_drafts=27`、`narrative_events=0`、`scene_memories=3`、`chapter_memories=3`。
- 两个已有场景的 `current_final_scene_row_id` 升级前后完全一致；迁移后正文哈希空值 `0`、哈希不匹配 `0`、active SceneMemory 重复 `0`、active SceneMemory 孤儿 `0`、叙事身份不匹配 `0`，四个叙事位置索引均存在。
- OpenAPI 已暴露 `POST /api/v1/author-drafts/{draft_id}/promote-canonical`；线上只读 API smoke 返回 `200`，并能正确报告草稿 revision、`canonical_dirty` 与当前 FinalScene 指针。

### 7.4 发布阻断与后续边界

1. 严格 database preflight 的 schema、revision、表列与本轮约束检查均通过，但因 `llm_call_attempt_orphans=209` 返回 `ready=false`。这些历史行中状态分布为 `200 settled / 8 failed / 1 reserved`，阶段分布为 `206 initial / 3 response_parse_retry`。
2. 全库外键检查共返回 `506` 条历史孤儿：上述 `209` 条 LLM attempt，加 `297` 条 snowflake revision link。父级请求元数据已经缺失，本轮没有擅自删除或伪造父记录。
3. 后续应另立“历史孤儿数据取证与隔离”任务：先导出不可逆证据，再由保留策略决定补建、隔离或删除；完成后重新运行严格预检。
4. 全量后端测试必须在不受当前时间窗限制的环境完成，才能补充“全量回归通过”结论。
5. `foreshadow_lifecycle` 的项目健康统计和 `scene_execution` 的逆向因果骨架仍有使用章节内 `scene_seq` 作为跨章边界的风险，未包含在本轮权威正文链修复内，应进入下一批连续性治理。

因此，本轮修复可以判定为**功能与迁移验收通过**；整个系统目前只能判定为**有条件可用、尚未达到全库发布就绪**。
