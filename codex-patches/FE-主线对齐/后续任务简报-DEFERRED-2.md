# FE-ALIGN 后续任务简报（二）— DEFERRED D8–D11 收尾（G 系列）

> 前置：F 系列（D1–D7 → F1–F7）已全部交付（`后续任务简报-DEFERRED.md` +
> PROGRESS.md「后续 F 系列」，收口提交 `a282734`）。本简报把 F 系列新产生的
> DEFERRED D8–D11 整理为 G1–G5，按「无 LLM 依赖优先、小→大」排序。

## 执行规则（沿用 F 系列）

- 红线、完成定义（自检 + pytest 全绿 + build/冒烟 + 单提交 + 账本）、
  卡死规则（3 修法失败 → DEFERRED 续编号）全部沿用。
- LLM 相关阶段（G3–G5）的验收口径：**管线接真 + 诚实降级**——本环境
  LLM 不可用，端到端产文不在验收内；以「后端单测断言提示词/节点装配 +
  FE 冒烟断言降级引导」为准。
- 提交信息 `FE-ALIGN G<N>: <主题>`。

## 核对事实（已验证）

- `AUDIT_KINDS` 已含 `unplanted_reveal`（空降）/ `causal_break`（断链）/
  `unfair_clue`（线索不公平）——G1 后端零改动。
- `POST /api/v1/passages/patch-candidates` + LLM 节点 `writer_passage_patch`
  现成（多 option 产出 + accept/reject 学习偏好闭环）——G4 主要是 FE 接线。
- run job 的 `payload_json` 是现成的随行载荷通道——G3 的 note 从这里进。
- 雪花候选生成（s2GenerateCands）与内联改写（wrRewriteMulti）的 FE 提示词
  逻辑完整，迁移后端时以 config/prompts.yaml 模板为正源重写。

## 阶段

### G1（源 D10）— LF3 空降/断链/线索不公平接审计 findings

复刻 F4 的打法：`_seed_tide_audit` 扩展三类 kind 的 findings（fe 形状存
meta/evidence JSON），lf3-data 增加 `lf3SyncFromAudit()`（复用 Lf7Bridge 的
项目级 audit 缓存或直接 GET），LF3_ORPHANS/LF3_CAUSAL/LF3_CLUES 退化为
后端投影；无数据的非 tide 作品清空。LF3_RETRIEVE（记忆预算池）与
LF3_AUDIT（草稿审计流程模拟）保留演示、记账（属起草管线可视化，待真实
LLM 环境）。塔 DemoTag 文案随之收窄。

**验收**：冒烟断言 seed findings → LF3_* 投影 → 塔上空降/断链可见；
POST 一条 unplanted_reveal → 刷新可见。

### G2（源 D11）— 雪花 history 轻量跨会话

`ws-snow-sync` 的 fe_meta 增加 `history`：去掉 snap 快照、cap 20 条的
journal（t/who/action/note/key）。水合时还原（snap=null）。视图 rollback
依赖 h.snap——加一行守卫接缝（无 snap 的条目隐藏/禁用回滚按钮，标注
「历史会话 · 不可回滚」语义按现行 UI 形态最小化处理），记账。

**验收**：冒烟：构思操作产生 history → 清缓存重载 → journal 还原可见、
无 snap 条目不可回滚、本地新操作仍可回滚。

### G3（源 D9）— 起草 note 进 scenes run 管线

- 后端：`POST /scenes/{id}/run/jobs` 接受可选 `author_note`（≤500 字）→
  payload_json 随行 → worker 调 `Orchestrator.run_scene(..., author_note)` →
  风格生成提示词注入（prompts.yaml 对应模板加可选输入段，缺省为空不影响
  现有快照测试；同步 run/full 同样支持）。单测断言 LLM 请求提示词含 note。
- FE：scnRun 把 note 上行；起草日志撤掉「指令不进管线」提示，改为
  「改写指令已随任务下发」。
- 注意：模板改动若引发 hash_contract / prompt 快照类测试失败，按测试语义
  更新（记核对发现）。

**验收**：后端单测（mock LLM runner 捕获 prompt 断言含 note）；冒烟断言
job payload 带 note（API 查 run-jobs 序列化）。

### G4（源 D8-写作台）— 内联改写接 passages/patch-candidates

- FE `wrRewriteMulti` 改走 `POST /api/v1/passages/patch-candidates`
  （object_type=scene + 当前场景后端 id + source_excerpt=选区 +
  issue_dimension/instr 映射；tone 滑杆并入指令文本）→
  `replacement_options_json` → 3 版本列表（形状适配现有结果面板）。
- 采纳/弃用回传 accept/reject（学习偏好闭环）；`no-model` 错误路径保留，
  文案升级为「去系统设置启用 LLM」。
- 核对 `_run_passage_patch` 的 instr 注入口（issue_dimension 自由文本？
  note 字段？以代码为准），必要时后端补一个可选 `author_instruction` 输入。

**验收**：后端单测（mock runner：3 option 返回 → FE 形状）；冒烟断言
LLM 不可用时 UI 弹明确引导（现 error phase 文案）。

### G5（源 D8-雪花）— 雪花步骤候选生成接后端节点

- 后端：新 LLM 节点 `snowflake_step_candidates`（三件套铁律：
  llm_node_registry + config/models.yaml task_routing + config/prompts.yaml
  模板，structured_schema 输出 [{label,tag,text,notes}]）+ 端点
  `POST /api/v2/projects/{id}/snowflake-workspace/steps/{step_key}/fe-candidates`
  （上下文从步骤 fe_*/规范字段折叠，FE 不再自带提示词）。
- FE `s2GenerateCands` 改走端点；LLM 不可用/失败回退静态 `s2GenericCands`
  （现行为不变，候选卡标注来源）。
- 记得 system-config sync-missing 校验（F 系列教训：缺 registry 422）。

**验收**：后端单测（mock runner 断言模板装配 + 解析）；冒烟断言降级回退
静态候选且 UI 不报错。

## 完成标准（整个 G 系列）

1. G1–G5 各一次提交，PROGRESS.md「后续 G 系列」小节全勾选。
2. 后端全量 pytest 绿；build 绿；run-smokes + f2–f6 + acceptance 全过。
3. window.claude 引用归零（grep 验证）；WsDemoTag 仅余「起草管线流程模拟」
   类目（LF3_AUDIT/RETRIEVE、styleref LLM 产物 stage、起草台演示队列）。
4. 输出总结：各阶段提交号 + 新增 DEFERRED（D12…）清单。
