# Wave 4 实施计划：POV 减法投影

> 设计：`docs/superpowers/specs/2026-07-10-ai-novel-outcome-governance-design.md`（v1.1）§5.6 / §7.11 / §8 Wave 4 / §9.1
>
> 日期：2026-07-12
>
> 纪律：前一 Wave 完成门未过不得开始（Wave 0–3 已完成并验证，见 `docs/outcome-governance-progress.md`）；只改本 Wave 相关代码；测试先行；独立提交。

## 0. 前置门禁复核（开工前必须先跑）

Wave 3 完成门已在提交 `536f0c9` 验证（进度账本记录：定向 19 项 + 128 项回归 + vitest 79 + e2e PASS）。开工第一步在本机重跑关键回归确认基线仍绿：

```bash
cd backend && .venv/bin/python -m pytest tests/test_narrative_event_log.py \
  tests/test_consistency_validation_realistic.py tests/test_metadata_isolation.py \
  tests/test_orchestrator_flow.py -q
```

四个文件全绿 → 基线确认，开始 Wave 4。任一红灯先查是否环境漂移，不得在红基线上叠加改动。

## 1. 目标与完成门

**目标（设计 §8 Wave 4）**：模型从输入层就看不到 POV 不应知道的秘密。

**完成门**：
1. POV 提示词快照**不含秘密正文**（`secret_held_by` / `believes_false` 的内容不进入写作提示词，除非 POV 拥有或已获知）。
2. 硬 QC 仍能利用**全量事实**发现冲突（`check_consistency` 路径不受影响）。

**可复算自证**：
- golden 测试：含秘密的项目，POV 提示词快照断言不出现秘密正文子串；非 POV 场景断言秘密仍被硬 QC 全量读取并能检出矛盾。
- 退化等价测试：无任何显式秘密标注的项目，投影输出与现行 `format_state_for_prompt` / `information_asymmetry_digest` 逐字节等价（保证渐进迁移、不破坏存量）。

## 2. 关键设计决策

### D1：不新增 schema 迁移，用现有结构表示 6 个知识级别

设计 §8 Wave 4 主要文件**不含** `db/models.py` 与迁移，且 `NarrativeEvent` 已有 `payload_json`(JSON) 与 `confidence` 列。6 个知识级别（§5.6）用现有事件结构派生，不加列：

| 知识级别 | 现有结构表示 |
|---|---|
| `public` | 非信息不对称键的事实（`fact_key` ∉ `INFORMATION_ASYMMETRY_FACT_KEYS`），在场角色/实体可观察 |
| `secret_owner` | `secret_held_by` 事实——`entity_id`（持有者）知道，他人不知 |
| `known`（对 POV） | POV 自身事实 ∪ POV 的 `character_learns` 事实 ∪ POV 持有的 `secret_held_by` ∪ 已 `revealed_to` POV 的秘密 ∪ POV 在场场景断言的公共事实（回填启发式，见 D4） |
| `believed_false`（对 POV） | POV 的 `believes_false` 事实（POV 据此行动，需注入） |
| `suspected`（对 POV） | POV 的 `character_learns` 事实且 `payload_json["knowledge_status"] == "suspected"`（新约定，`log_event` 已透传 payload，写侧无需改签名） |
| `unknown` | 其余——不注入 |

漂移守卫因此不受影响（零列变更），但仍纳入回归。

### D2：投影为**逐事实过滤**，退化性是定理而非分支

现 `format_state_for_prompt` 用 `state.as_dict()` 注入**全部**事实键（含秘密）。POV 投影**只对信息不对称键**（`secret_held_by` / `believes_false` / `revealed_to` / `scene_revelation`）做 POV 过滤，其余公共事实（location/physical_state/alive/…）照旧注入。

推论：项目若无任何信息不对称事实 → 投影输出与今天逐字节相同（无秘密可减）。因此"无显式秘密→等价全量注入"（§5.6）是逐事实过滤的**自然性质**，不需要项目级 `has_secrets` 开关。这比全局开关更安全（不会误伤公共事实），也让退化等价测试直接可证。

### D3：新增 `PovKnowledgeProjection` 服务，两个 log 方法委派给它

- 新文件 `services/pov_knowledge_projection.py`，`class PovKnowledgeProjection`。
- `NarrativeEventLog.format_state_for_prompt` 与 `information_asymmetry_digest`（**全仓仅 bundle_builder 写作提示词消费**，已核实）改为委派给投影服务的 POV 过滤实现。bundle_builder 的两个槽位因此自动切换，改动面最小。
- 硬 QC 用的 `project_character_state` / `all_facts_at_scene` / `check_consistency` **保持全量、零改动**；在 log 方法 docstring 中显式标注"写作提示词走投影、硬 QC 走全量"的边界，防未来回归。

### D4：存量归属回填走**投影时派生**，不做破坏性数据迁移

设计 §5.6 要求"POV 在场场景的事件 → `known`"以免饿死上下文。实现为**投影时**从 `SceneCard.onstage_chars_json` 派生：POV 在场场景中断言的公共事实计入 POV `known`，无需向 append-only 日志插入合成事件（插入合成 `character_learns` 会污染"单一真相源"、影响重放，风险更高且不可逆）。

- 完成门（POV 快照无秘密 / 硬 QC 全量）不要求持久化回填，投影时派生即满足。
- **不落地持久化写入工具**：设计 §13 风险表与 §5.6 均警告向 append-only 日志插入合成
  `character_learns` 事件会污染"单一真相源"、影响其他场景的 `known_facts` 与信息不对称
  重放。因此回填**只做投影时派生**（`PovKnowledgeProjection._onstage_public_values`），
  同时满足 §5.6 的"不饿死上下文"与"无秘密→等价"两项要求，且不可逆风险为零。此为对
  §8 Wave 4 项 6"回填迁移"的等价、更安全实现，列入剩余风险说明。

### D5：finding 证据脱敏堵 QC 回灌旁路（§7.11 / 不变量 11）

- 现状核实：秘密键（`secret_held_by`/`believes_false`）不在 `_CHECKABLE_FACT_KEYS`，故 consistency 违规**结构上不会**携带秘密内容；且 Wave 2 后确定性 Q1 违规走作者确认、不进自动补丁。旁路当前结构上已闭合。
- 本 Wave 补**显式防御 + 可证伪测试**：`PovKnowledgeProjection.desensitize_findings(findings, pov, project, scene_seq)`——凡 finding 的 `authority_ref`/`expected`/`actual`/`evidence`/`evidence_spans` 命中"非 POV 已知的秘密事实值"即从**自动补丁 brief 中剔除**并改标 `author_confirmation_only`。挂载点：orchestrator 自动补丁 brief 构造处（soft QC `_rewrite_brief_from_report` 与 critique `format_critique_brief` 两条回灌路径）。
- 硬 QC 自身不脱敏（不变量 11 明确"硬 QC 始终读全量权威状态"）。

## 3. 盘点结果（Wave 4 第一步已完成）

已核实 Bundle 内**仅两个**注入槽位读事件日志权威状态：

| 槽位 | 文件:行 | 调用 | 泄漏 |
|---|---|---|---|
| `narrative_state` | `bundle_builder.py:622` `_narrative_state_digest` | `format_state_for_prompt` | `as_dict()` 注入 `secret_held_by`/`believes_false` 值 |
| `information_asymmetry` | `bundle_builder.py:985` `_information_asymmetry_digest` | `information_asymmetry_digest` | 直接打印 "Secrets held by X" / "False beliefs of X" |

其余提示词槽位（character_psychology / relationship_matrix / voice_fingerprint / theme 等）不读事件日志权威状态（核实 grep 无 `NarrativeEventLog`/`project_*_state`/`secret` 命中）。两个 log 方法全仓仅被 bundle_builder 消费。

## 4. 分步实施（测试先行）

### Step A — `PovKnowledgeProjection` 服务（新文件）

**先写测试** `tests/test_pov_knowledge_projection.py`（先红）：
- `test_projection_suppresses_non_pov_secret_content`：X 持 `secret_held_by="X 杀了市长"`，POV=Y 在场 → 投影的 narrative digest 不含该秘密正文。
- `test_projection_keeps_pov_owned_secret`：POV 自己持有秘密 → 注入（POV 据此行动）。
- `test_projection_keeps_revealed_secret`：秘密 `revealed_to` POV（或 POV 的 `character_learns` 记录）→ 注入。
- `test_projection_keeps_public_facts`：location/physical_state/alive 等公共事实照旧注入。
- `test_projection_pov_false_belief_injected_others_suppressed`：POV 的 `believes_false` 注入；他人的 `believes_false` 内容抑制。
- `test_projection_suspected_marked`：POV 的 `character_learns`+`knowledge_status=suspected` → 以"怀疑"措辞注入，不表述为既定事实。
- `test_projection_onstage_derivation_feeds_pov_known`：POV 在场场景断言的公共事实计入 POV known（不饿死上下文）。
- `test_projection_no_secrets_is_byte_identical_to_full`：无任何信息不对称事实 → `PovKnowledgeProjection.format_state_for_prompt` 与旧全量实现逐字节相等（退化等价）。

**再实现** `services/pov_knowledge_projection.py`：
- `class PovKnowledgeProjection.__init__(self, session)`。
- `project(project_id, scene_seq, pov_character_id, onstage_character_ids) -> PovProjection`（dataclass：`known_secrets` / `public_facts_by_char` / `pov_false_beliefs` / `pov_suspicions` / `suppressed_secret_owners`）。
- `format_state_for_prompt(...)`：复刻旧输出骨架（`## Authoritative Character State` / 位置 / 物品段），但对信息不对称键做 POV 过滤；非 POV 秘密以 §5.6.4 内容无关约束替代（"角色 X 似乎在隐瞒信息（内容对 {POV} 不可见）"）或直接省略。
- `information_asymmetry_digest(...)`：POV 视角——只展示"POV 知道而他人不知"的内容；他人独有知识只给内容无关提示（条数/存在性），绝不打印 "Secrets held by X" 的正文。
- `desensitize_findings(...)`：见 Step D。
- 复用 `narrative_event_log.INFORMATION_ASYMMETRY_FACT_KEYS`。

### Step B — 两个 log 方法委派 + bundle 槽位自动切换

**先写测试**（在 `tests/test_narrative_event_log.py` 追加，先红）：
- `test_format_state_for_prompt_pov_hides_other_secret`：含秘密时 `NarrativeEventLog.format_state_for_prompt(pov=Y)` 不含 X 的秘密正文。
- `test_information_asymmetry_digest_pov_hides_secrets`：不再出现 "Secrets held by X" 正文。
- 保留 `test_format_state_for_prompt`（无秘密，继续绿）证明退化不破坏。

**再实现**：`NarrativeEventLog.format_state_for_prompt` / `information_asymmetry_digest` 内部委派给 `PovKnowledgeProjection`；docstring 标注"写作提示词走投影 / 硬 QC 走 project_character_state 全量"边界。bundle_builder 两槽位无需改逻辑（自动切换），仅补注释指向本 Wave。

### Step C — 硬 QC 全量不回归

**测试**（追加到 `tests/test_consistency_validation_realistic.py`，先红后绿）：
- `test_hard_qc_still_sees_full_state_with_secrets`：项目含秘密时，`check_consistency` 仍读全量 `project_character_state`，对与秘密相关的硬事实矛盾（如物理状态）能检出——证明"投影只减写作提示词，不减硬 QC"。

（此步无生产代码改动，仅加守卫测试锁定分离不变量。）

### Step D — finding 证据脱敏（QC 回灌旁路）

**先写测试** `tests/test_pov_finding_desensitization.py`（先红）：
- `test_finding_referencing_non_pov_secret_excluded_from_auto_patch`：构造引用非 POV 秘密值的 Q1 finding → `desensitize_findings` 将其剔出自动补丁 brief，标 `author_confirmation_only`。
- `test_finding_on_public_fact_passes_through`：引用公共事实的 finding 正常进入 brief。
- `test_pov_owned_secret_finding_passes_through`：POV 自己已知的秘密相关 finding 可进入 brief。

**再实现**：
- `PovKnowledgeProjection.desensitize_findings(...)`。
- orchestrator 自动补丁 brief 构造处（`_rewrite_brief_from_report` 结果与 `format_critique_brief` 结果）在传入 `generate_style_patch` 前过一遍脱敏，POV/project/scene_seq 从当前 scene 取。硬 QC/人工确认路径不脱敏。

### Step E — golden 用例 + 悬疑 LLM 对照 lane（§8 Wave 4 项 4/5）

- golden 用例并入 Step A/B 测试（秘密/错误信念/怀疑/公共事实四类，已覆盖）。
- 悬疑真实 LLM 对照属 §9.3 发布门 lane：加一个 `@pytest.mark.skipif`（无 `NOVEL_SYSTEM_LLM_ENABLED`）的对照测试骨架 `test_suspense_pov_no_early_action`（离线跳过、发布门实跑），检查 POV 视角生成不提前泄漏/据未知秘密行动。本机 node16/无额度不实跑，逻辑门由 golden 覆盖。

### Step F — 更新进度账本

`docs/outcome-governance-progress.md` 追加 Wave 4 节（交付内容 / 完成门验证命令与通过数 / 剩余风险）。

## 5. 测试矩阵

| 层 | 文件 | 断言 |
|---|---|---|
| 单元 | `test_pov_knowledge_projection.py`（新）| 6 级知识投影极性 + 退化等价 + 在场派生 |
| 单元 | `test_narrative_event_log.py`（追加）| 委派后 POV 隐藏他人秘密；无秘密退化 |
| 单元 | `test_pov_finding_desensitization.py`（新）| 回灌脱敏剔除非 POV 秘密 finding |
| 集成 | `test_consistency_validation_realistic.py`（追加）| 硬 QC 全量不回归 |
| 发布门骨架 | `test_consistency_validation_realistic.py`（追加 skipif）| 悬疑 LLM 对照（离线跳过）|

## 6. 回归与验证命令

```bash
cd backend && .venv/bin/python -m pytest \
  tests/test_pov_knowledge_projection.py tests/test_pov_finding_desensitization.py \
  tests/test_narrative_event_log.py tests/test_consistency_validation_realistic.py -q   # 定向（先红后绿）
cd backend && .venv/bin/python -m pytest tests/test_metadata_isolation.py -q            # 漂移守卫（零列变更应仍绿）
cd backend && .venv/bin/python -m pytest tests/test_orchestrator_flow.py \
  tests/test_bundle_builder.py tests/test_qc_engine.py -q                                # 回灌/注入相关回归
cd backend && .venv/bin/python -m pytest -q -m "not chroma_integration"                 # 全量回归
```

前端无改动（Wave 4 纯后端输入层），不跑 vitest/build。

## 7. 预期剩余风险

- 悬疑真实 LLM 对照本机不可实跑（node16/无额度）——归 §9.3 发布门；离线 golden 覆盖逻辑门。
- 持久化归属回填仅提供可选离线工具，默认走投影时派生；若未来引入并发事件抽取需复核派生一致性。
- `revealed_to`/`character_learns` 记录秘密获知的写侧覆盖度依赖规划/抽取数据质量；投影对"不确定"一律保守抑制（宁可漏注入不可泄密），可能对标注稀疏项目略减 POV 可见秘密——符合 §5.6 保守策略。

## 8. 提交边界（只提交本 Wave 文件）

- `backend/src/novel_system/services/pov_knowledge_projection.py`（新）
- `backend/src/novel_system/services/narrative_event_log.py`（两方法委派 + docstring 边界）
- `backend/src/novel_system/services/bundle_builder.py`（仅注释指向，如无逻辑改动可不动）
- `backend/src/novel_system/services/orchestrator.py`（自动补丁 brief 脱敏挂载）
- `backend/tests/test_pov_knowledge_projection.py`（新）
- `backend/tests/test_pov_finding_desensitization.py`（新）
- `backend/tests/test_narrative_event_log.py`（追加）
- `backend/tests/test_consistency_validation_realistic.py`（追加）
- `docs/outcome-governance-progress.md`（Wave 4 节）
- `docs/superpowers/specs/2026-07-12-wave4-implementation-plan.md`（本文件）

不触碰 prose_event_extractor 的 LLM 抽取逻辑（除非需给 `character_learns` 加 `knowledge_status` 透传——`log_event` 已支持 payload，写侧零改动）。
