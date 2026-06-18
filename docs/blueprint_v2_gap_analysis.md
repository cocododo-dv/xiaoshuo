# AI 长篇小说系统 · v2 蓝图 vs 当前项目 差距分析报告

> 分析日期：2026-06-16
> 对照文档：《AI 长篇小说生成系统 · v2 蓝图（冻结版）》
> 当前分支：`fe-align`（基于 `main` + 22 PR style-reference 加固 + FE 对齐系列）

---

## 一、总体定位对比

### 蓝图的核心立场

蓝图以一句话定调：**"LLM 只是算子，编排层才是算法。"** 它提出三层根因模型（架构层/训练目标层/扎根层），并用三个同心圆（正确性→能读→精修）划分 ROI 梯度。最终结论是：系统守住质量地板、放大人的判断，天花板归人。

### 当前项目的实际立场

当前项目走的是**工程先行、渐进式构建**路线：先把 Snowflake 规划管线跑通（10 步 + 物化），再搭 8 步场景生成流水线（bundle → blueprint → neutral → style → hard_qc → soft_qc → auto_rewrite → final），然后用 Style Reference 子系统做风格还原。整体倾向**先保证端到端可运行，再逐模块深化**。

### 关键分歧

| 维度 | 蓝图 | 当前项目 | 评价 |
|------|------|----------|------|
| 元哲学 | 先定义根因，再按 ROI 排序 | 先跑通链路，再补强 | 两者不矛盾，但蓝图更清醒地认识到"哪些问题不可解" |
| 第一优先级 | 正确性（事件溯源 + 连续性） | 功能完整性（端到端管线） | 当前项目有连续性检查但非架构级保证 |
| 人的位置 | 明确定义"不可外包"清单 | 隐式——Review gate 存在但设计目标未显式声明 | 蓝图更系统 |

---

## 二、逐模块深度对比

### §2 事件溯源（蓝图第一圈·核心）

**蓝图要求：** 只增不改的事件日志 → 任意时刻的角色/世界状态通过回放推导 → POV 过滤 → 信息不对称天然追踪。摘要塔仅作氛围辅助，绝不传递事实。

**当前项目：**
- `OperationLog`（`models.py:1600`）：追加式操作日志，但记录的是**系统操作**（API 调用），不是**叙事事件**（角色状态变化）。
- `AuthorDraftEvent`（`models.py:968`）：记录草稿编辑事件（created/edited/candidate_inserted），是**编辑历史**，不是**故事事件**。
- `AttemptTracker`（`models.py:1184`）：记录生成尝试的状态，是**流程跟踪**。
- `ForeshadowTracker`（`models.py:1463`）：有首级模型，但只记录 text + status，**没有因果前驱事件 ID、没有强化计划、没有回收时点**。
- `VoiceProfile` / `RelationProfile`：角色状态**快照**，不是通过事件回放推导的投影。

**差距评级：🔴 重大差距**

这是蓝图认为 ROI 最高的模块，当前项目完全没有。当前的连续性保证依赖 LLM 抽取器做 hard_qc（§15 蓝图指出这是"用不可靠验证不可靠"），没有确定性的事实真相源。

**具体缺失：**
1. 无叙事事件日志（角色状态变更、位置移动、信息获取、关系变化）
2. 无因果链追踪（事件 A 导致事件 B 的显式链接）
3. 无 POV 过滤（无法回答"第 N 场景时角色 A 知道什么"）
4. 无信息不对称追踪（角色间的认知差无法被系统利用来制造张力）
5. 角色/世界状态是快照式存储，不是事件回放式推导

### §3 检索策略：三轨并行

**蓝图要求：** 确定性实体查找（键值查找，不经语义检索）+ 伏笔主动轮询（从登记表主动检查到期伏笔）+ 语义检索（仅用于氛围/呼应）。三轨职责严格分离。

**当前项目：**
- `context_budget.py` 定义了 **21 个命名 section**，包括 `chapter_goal`、`scene_card`、`character_contract`、`foreshadow`、`style_rules` 等——这是一套**结构化检索**体系。
- `prompt_builder.py` 按 task_kind 策略组装上下文，有优先级丢弃。
- `vector_store.py` 支持语义检索（`similar_scene_context` section）。
- 没有伏笔"主动轮询"——伏笔只是作为 context section 被动注入，不会主动检查"有没有到期应回收的伏笔"。

**差距评级：🟡 中等差距**

当前项目的 21-section 结构化检索在工程上已相当成熟，但：
1. **第一轨不够确定性**——角色状态来自快照而非事件回放，"查找"的准确性依赖快照的时效性。
2. **第二轨缺失**——伏笔没有"到期主动轮询"机制，完全被动。
3. **三轨没有显式分离**——所有 section 在同一个 budget 池里竞争 token，没有"事实必须走确定性查找"的架构隔离。

### §4 规划与结构：无 Spec 不生成

**蓝图要求：** 铁律：没有上一层的绑定 spec，绝不生成散文。规划链：控制性理念 → 逆向因果骨架 → 多分辨率展开（雪花法）→ 场景 spec（五字段：因果前提/叙事目标/困境设计/代价要求/后续义务）。

**当前项目：**
- **Snowflake 管线（10 步）** 完整实现：`book_brief → one_sentence → one_paragraph → character_sheets → short_synopsis → character_synopses → long_synopsis → character_bibles → scene_list → scene_details`。有 5 个硬门（步骤 1/2/3/9/10 必须通过才能物化）。
- `SceneCard`（`models.py:444`）有 `scene_goal`、`beats_json`、`must_include_text`、`forbidden_text`、`exit_change`、`hook`、`target_length_band`——结构上是场景 spec，但**字段模型与蓝图不同**。
- `SceneExecutionContract`（`models.py:628`）有 `scene_mode`、`pov_character_id`、`scene_crucible`、`must_reveal`、`must_withhold`、`expected_reader_emotion`——这些更接近蓝图的 spec 理念。

**差距评级：🟢 小差距（已基本对齐）**

Snowflake 管线是当前项目最成熟的部分。主要差距：
1. **无"控制性理念"字段**——蓝图要求一句话主题判断作为全书锚，当前项目没有显式的 controlling idea 存储。
2. **无"逆向因果骨架"**——蓝图要求从终局反推因果链，当前是正向展开。
3. **场景 spec 缺"代价"字段**——蓝图特别强调"这个选择让角色失去了什么"，当前 `SceneCard` 没有显式 `cost` 字段。
4. **无因果前驱/后续义务**——场景间的因果链接不在 spec 中显式建模。

### §5 伏笔系统

**蓝图要求：** 完整生命周期（埋设→强化→回收），强制强化，反向伏笔生成，伏笔密度检查。

**当前项目：**
- `ForeshadowTracker`（`models.py:1463`）：有 `text`、`tracker_status`（open/resolved/closed）、`chapter_id`、`scene_id`。
- `DiagnosticCards` 中有 `foreshadow_debt` 类型，可检测未回收伏笔。
- `longform_control.py` 追踪 `promise_without_payoff`。

**差距评级：🟡 中等差距**

基础框架存在但功能浅：
1. **无"强化计划"**——蓝图要求在埋设和回收之间安排强化任务，当前只有 open/resolved/closed 三态。
2. **无"反向伏笔生成"**——不支持后期规划发现需要前文补充暗示。
3. **无密度检查**——不检查单场景伏笔数是否过多、连续场景是否无回收。
4. **不走确定性查找**——伏笔是通过 context section 被动注入，不是第二轨主动轮询。

### §6 分级选择（Best-of-N）

**蓝图要求：** 关键场景 N=5、过渡场景 N=3 → 对抗性指标初筛淘汰最差 → 人（关键场景）/指标（过渡场景）终选。分散度监控。

**当前项目：**
- **完全没有 Best-of-N 机制。** 场景生成走单路径（neutral → style → QC → rewrite），不生成多个候选。
- `RevisionCandidate`、`PassagePatchCandidate` 等支持"候选"状态，但这些是**修订候选**，不是**初始生成候选**。
- QC 是单次判断（pass/fail/rewrite），不是 N 候选中选最优。

**差距评级：🔴 重大差距**

蓝图在 §6 做了 v1→v2 最大改动，将 Best-of-N 从"全自动万能药"修正为"分级方案"。当前项目连基础的多候选生成都没有。这意味着：
1. 每次生成的输出就是分布的**众数**（最可能但最平庸的版本）。
2. 无法通过采样探索分布尾巴——"好但不那么可能"的版本永远到不了用户面前。
3. 无分散度监控——不知道当前采样是否打开了搜索空间。

**前置条件提醒：** 蓝图 §6.5 指出，在上 Best-of-N 之前要先审计指标是"对抗性"还是"顺从性"。当前项目的 `literary_quality.py` 有 18 个维度，其中约 7 个是对抗性的（`model_voice`、`image_homogeneity`、`template_action_reuse`、`syntax_monotony`、`false_clarity`、`dialogue_as_report`、`over_explained_motive`）。**这个前置条件部分满足**，可以考虑开始引入。

### §7 抗趋均值采样（解码端）

**蓝图要求：** min-p / typical sampling / DRY + no-repeat 惩罚 / XTC（排除最高概率 token）。

**当前项目：**
- `llm_client.py` 支持 `temperature` 参数，但**没有 min-p、typical sampling、DRY、XTC**。
- `config/models.yaml` 为不同任务配置了不同 temperature（drafting 0.6、stylize 0.8、QC 0.2），但这是粗粒度控制。
- 当前使用 API 模式调用（OpenAI/Anthropic/Gemini），**大部分高级采样参数不可用**——这些是本地模型（KoboldCpp/SillyTavern）的专属杠杆。

**差距评级：⚪ 不适用（架构约束）**

蓝图在 §7 明确说"本地模型的解码端是几乎免费的杠杆，纯 prompt/检索层方案完全碰不到它"。当前项目走的是 API 调用路线（gpt-5、Claude、Gemini 等），这些提供商的 API **不暴露 min-p/DRY/XTC**。这不是差距，是**架构路线选择不同**——API 路线换来的是模型能力更强但解码控制更少。

**注意：** 如果未来引入本地模型（如 config 中预留的 Ollama provider），这些采样策略才有意义。

### §8 批判-修订回路

**蓝图要求：** 独立角色的"编辑"pass，检查 AI 味清单（直接命名情绪、感知过滤词、冲突化解太干净、感官泛化、段落套路）。

**当前项目：**
- `soft_qc` 阶段本质上就是这个"编辑 pass"——检查风格合规性，可触发 patch/waive/human_review。
- `literary_quality.py` 的 18 个维度中有多个直接对应蓝图清单：
  - `model_voice`（0.09 权重）→ 检测 LLM 陈词滥调
  - `false_clarity`（0.02）→ "她知道/终于明白了"式虚假确定性
  - `dialogue_as_report`（0.07）→ 对话当报告
  - `over_explained_motive`（0.04）→ 过度解释动机
  - `template_action_reuse`（0.06）→ 模板化动作
  - `syntax_monotony`（0.03）→ 句法单调
  - `image_homogeneity`（0.05）→ 意象同质化
- `scene_quality.py` 区分了**结构失败**（触发全场景重写）和**语言失败**（触发局部修补）。
- Auto-rewrite 循环存在（`auto_rewrite_max_attempts`）。

**差距评级：🟢 基本对齐**

当前项目的批判-修订回路在工程实现上甚至比蓝图描述更精细（18 维度 vs 蓝图的 5 条清单）。主要差距：
1. **不是独立模型调用**——蓝图暗示用不同模型/角色做批判，当前用同一 LLM 做 QC。
2. **缺感知过滤词显式清单**——蓝图列出"她觉得/他看到/她意识到"，当前 `MODEL_VOICE_TERMS` 有部分覆盖但可能不够细。
3. **缺"段落起承转合套路"检测**——18 维度中 `syntax_monotony` 部分覆盖，但不够段落结构级。

### §9 风格系统

**蓝图要求：** 三角色配比（Few-shot 范例 + Voice Card + 结构化 Metrics）+ 反重复引擎 + 动态漂移检测（每章 16 维打偏离分）。

**当前项目：**
- **Style Reference 子系统**（22 PR，954 测试）是当前项目最重工程化的部分：
  - 4 层 × 16 sub-dim 提取（language/narrative/scene/theme）
  - `MetricsEngine`：25+ 硬指标（纯函数，无 LLM）
  - 注入三策略（A=System Prompt / B=Few-shot / C=RAG 预留）
  - 三路验证（quantitative + semantic + plagiarism）
  - `forbidden_pattern`（反样本机制）
  - 自适应容差（`tolerance = max(std × 1.25, 绝对下限)`）
  - 多层叠加注入（base + character + scene，加权预算）
  - 抄袭双层防护（事前红线段 + 事后 8-gram Rabin-Karp）
  - 长文本防漂移（`refresh_every_chars` 续写循环）

- **Style Profile**（旧系统，7 features）：rhythm/syntax/imagery/narrative_distance/emotion_curve/paragraph_density/dialogue_ratio，提取后产出 guidance + calibration_lines + banned_moves。

- **反重复**：`BannedRuleCluster` 存储禁用规则，`banned_adjectives.yaml` 拦截空泛形容词，但**没有"与自身前文比较"的反重复引擎**。

**差距评级：🟢 小差距（部分超越蓝图）**

Style Reference 子系统在多个维度上**超越了蓝图的设计**：
- 蓝图只提到"三角色配比"，当前项目做到了 4×16 分层提取 + 25 硬指标 + 三路验证。
- 蓝图的"Voice Card"对应当前的 `SystemPromptFragments`（5 块强类型化）。
- 蓝图的"动态漂移检测"对应当前的 `quantitative` 验证路径（每次生成都做偏离分）。

仍缺：
1. **自身前文反重复引擎**——蓝图要求用 n-gram/Rabin-Karp 检查与自身前文的重复（已用过的比喻、场景开头方式、动作口癖），当前 plagiarism 只查参考书引文重复。
2. **每章偏离分报告**——当前验证是逐场景的，没有累积到章级/全书级的偏离趋势分析。

### §10 节奏：张力曲线 + 场景功能标签

**蓝图要求：** 全书目标张力曲线（0-10）→ 张力值映射写作参数（低→长段描写日常对话/高→短句快速切换）→ 功能标签（推进/深化/揭示/呼吸/铺垫/转折）→ 相邻不得连续两个以上同标签。网文：章末钩子类型不重复。

**当前项目：**
- `ChapterGoal` 有 `emotional_target`、`ending_effect`，但**没有数值化张力目标**。
- `SceneCard` 有 `scene_type`、`scene_crucible`，但不是蓝图的功能标签体系。
- `literary_quality.py` 有 `choice_pressure`（0.08）和 `ending_drive`（0.08）维度，但这是**事后评分**，不是**事前规划**。
- 无张力曲线可视化，无相邻标签约束检查。

**差距评级：🔴 重大差距**

节奏控制是蓝图第三圈的核心模块之一，当前项目只有碎片化的处理：
1. **无全书张力曲线**——没有规划阶段的目标张力序列。
2. **无张力→参数映射**——不能根据张力值自动调整句长、对话比例等写作参数。
3. **无功能标签体系**——场景缺少显式的叙事功能分类和相邻约束。
4. **有的是事后评分，不是事前约束**——`choice_pressure` 和 `ending_drive` 只能在生成后告诉你"这个场景张力不够"，不能在生成前指导"这个场景应该是张力 7，用短句为主"。

### §11 角色深度：心理模型 + 声音指纹 + 关系矩阵

**蓝图要求：** 三层心理模型（表层行为→中层动力→深层潜意识）+ 决策权重随弧光迁移 + 声音指纹（句法/词汇/语用/特殊标记）+ 关系矩阵含信息不对称标记。

**当前项目：**
- `VoiceProfile`（`models.py:477`）：有 `content`（完整声音描述）+ 版本控制 + 激活时间窗。
- `RelationProfile`（`models.py:495`）：成对关系声音/立场。
- `character_continuity.py`：构建 character_contract_digest（id/name/pronouns/role/aliases/relationship_stance）。
- `SnowflakeCharacterPlan`（`models.py:174`）：Snowflake 第 4/6/8 步产出角色数据。
- `detect_character_pronoun_drift()`：检测代词漂移。

**差距评级：🟡 中等差距**

角色系统有良好基础但缺深度模型：
1. **无三层心理模型**——当前 VoiceProfile 是扁平的文本描述，没有"核心需求/核心恐惧/应对机制"的结构化建模。
2. **无决策权重**——蓝图的核心创新"面对威胁时：70% 战斗 / 20% 独自承受 / 10% 求助"不存在。
3. **无权重迁移**——没有"开篇→终局"的决策权重变化，无法量化角色弧光。
4. **声音指纹不够结构化**——VoiceProfile.content 是自由文本，不是蓝图要求的句法层/词汇层/语用层/特殊标记分层结构。
5. **关系矩阵缺信息不对称**——RelationProfile 记录关系，但不追踪"谁知道什么"的信息差。

### §12 主题管理

**蓝图要求：** 控制性理念（全书锚）+ 表达光谱（从最显到最隐）+ 对位叙事法（不同角色回应同一主题）+ 主题校验 pass。

**当前项目：**
- Style Reference 的 `theme` 层提取主题特征（`emotional_tone`/`values`/`motifs`/`narrative_philosophy`），但这是**从参考书提取**，不是当前项目自身的主题管理。
- `DiagnosticCard` 有 `theme_pressure_light` 类型——检测主题强化不足。
- `WorkProfile`（`models.py:896`）可能含主题信息，但 profile_json 结构不明确。
- `LongformStructureGuidance` 可以编码主题指导。

**差距评级：🟡 中等差距**

1. **无显式"控制性理念"存储**——蓝图要求一句话主题判断作为全书锚，当前没有。
2. **无表达光谱约束**——不控制主题表达频率（"直接议论全书最多 1-2 次"）。
3. **无对位叙事支持**——不追踪不同角色对同一主题的回应角度。
4. **有主题压力检测但弱**——`theme_pressure_light` 存在但不是完整的主题校验 pass。

### §13 每场景流水线

**蓝图要求：** 七步（规划确认→上下文组装→多路径生成→评判选择→批判修订→校验提交→人工闸门）。

**当前项目：** 八步（bundle → blueprint → neutral → style → hard_qc → soft_qc → auto_rewrite → final）。

**对比：**

| 蓝图步骤 | 当前对应 | 覆盖度 |
|----------|----------|--------|
| Step 1 规划确认 | bundle_builder（SnapshotBundle）| ✅ 基本对齐 |
| Step 2 上下文组装 | prompt_builder + context_budget（21 sections）| ✅ 对齐且更精细 |
| Step 3 多路径生成 | neutral → style（单路径）| ❌ 无多路径 |
| Step 4 评判选择 | 无 | ❌ 无候选选择 |
| Step 5 批判修订 | soft_qc + auto_rewrite | ✅ 对齐 |
| Step 6 校验提交 | hard_qc（连续性检查）| 🟡 部分——无事件日志追加 |
| Step 7 人工闸门 | Review gate（human_review_required）| ✅ 对齐 |

**差距评级：🟡 中等差距（管线结构对齐，多路径和事件追加缺失）**

### §14 人机协作边界

**蓝图要求：** 明确定义不可外包：控制性理念、角色核心创伤/矛盾、主题论证、关键转折创意决策、品味判断。

**当前项目：**
- Review gate 存在（`human_review_required` 出口），让人可以介入。
- Snowflake 步骤支持 `SnowflakeAssistantTurn` 迭代优化。
- `AuthorDraftProposal` 支持人工修改候选。
- `author_actions.py` 模式引导用户到正确操作点。

**差距评级：🟢 小差距**

人机协作的基础设施到位，但缺少**显式的"不可外包"声明**——这更多是设计文档层面的问题，而非代码层面。

### §15 校验的诚实边界

**蓝图要求：** 只校验硬事实（角色生死、核心设定），放弃软事实自动校验。

**当前项目：**
- `hard_qc` 做连续性和结构检查，`soft_qc` 做风格和语言检查——这是两级分离。
- `literary_quality.py` 明确区分了"blocking"和"revision"和"taste"级别的问题。
- 但当前 **hard_qc 本身是 LLM 驱动的**（gpt-5, temp 0.2），仍然是"用不可靠验证不可靠"。

**差距评级：🟡 中等差距**

蓝图的诚实在于承认"不可能完美校验"并放弃软事实自动校验。当前项目的 hard_qc 仍然依赖 LLM 抽取，如果有事件溯源，硬事实校验可以变成确定性查找（键值查找，不经 LLM），精确率和召回率都会显著提升。

---

## 三、当前项目的优势（蓝图未覆盖或不如的地方）

### 优势 1：工程成熟度远超蓝图

蓝图是冻结的设计文档（零代码）。当前项目是**已运行的系统**：
- 后端 ~343 测试 / 前端 524 测试 + smoke，全绿。
- 完整的 Alembic migration 链（53+ revisions）。
- 10 个 LLM provider 支持（OpenAI/Anthropic/Gemini/DeepSeek/Zhipu/Ollama 等）。
- idempotency + 审计日志 + 操作引导（author_action）+ 双栈分页。
- Docker-ready 开发环境（start-dev.cmd 一键启动）。

蓝图还停留在"§17 离开蓝图的出口"。

### 优势 2：Style Reference 子系统超越蓝图设计

22 PR、954 测试、三轮加固。蓝图 §9 的"三角色配比"只占了不到一页，当前项目的 Style Reference 是完整的工程子系统：
- 4×16 分层提取（蓝图没有提到 16 sub-dim 这个粒度）
- 25+ 硬指标引擎（蓝图提到了 MetricsEngine 但没有设计细节）
- 多层叠加注入 base+character+scene（蓝图没有）
- 抄袭双层防护 + 全书段落语料匹配（蓝图只提到了"n-gram 反抄袭"）
- 自适应容差（蓝图只提了公式，当前有完整实现 + 校准观察文档）
- cloud_policy 强制执行（蓝图没有提到）
- Few-shot 直读（scene_samples_index O(1)）
- forbidden_pattern（反样本）是当前项目的创新，蓝图也提到了但细节更少

### 优势 3：Snowflake 管线 + Scene 管线的端到端闭环

10 步 Snowflake + 8 步 Scene 管线 + 物化门 + 审阅流 + 版本提升 + 向量别名——这是一个**完整的内容生产链**。蓝图的"七步流水线"是理论设计，当前项目是跑通的实现，且步骤更多（加了 blueprint 和双阶 QC）。

### 优势 4：QC 分级比蓝图更精细

蓝图的 QC 设计集中在"AI 味清单"（5 条），当前 `literary_quality.py` 有 **18 个维度**，每个有明确权重。加上 `writer_rubrics.yaml` 的两套评分表（9 维度戏剧效能 + 10 维度文学修订），维度覆盖远超蓝图。

### 优势 5：上下文预算管理

`context_budget.py` 的 21-section 分级丢弃策略是蓝图没有提到的工程细节。在 token 预算受限时按任务类型策略决定丢什么留什么——这对实际生产至关重要。蓝图的"上下文组装"只说了"三轨检索 + 风格三件套"，没有讨论当 token 不够时怎么办。

### 优势 6：前端已有可交互原型

Vue SPA + React 高保真原型双轨并行。蓝图完全没有讨论前端，当前项目有完整的作家工作台（SnowflakeWorkbench、WriterRoom、ReferenceLearning、ReviewInbox、SystemConfig 等视图）。

### 优势 7：多提供商 LLM 路由

`llm_client.py` 支持 10 个 provider，`llm_node_registry.py` 定义了节点级路由。蓝图只提到了"本地模型"和"API"，没有讨论多提供商调度。

### 优势 8：可观测性

`MetricsRecorder` / `MetricsAggregator`（PR-10），metric events 上报、趋势图（PR-22），清理策略——蓝图完全没有提到运行时可观测性。

---

## 四、当前项目的劣势（蓝图指出但未实现的关键能力）

### 劣势 1：🔴 无事件溯源——正确性地基缺失

**影响等级：最高（蓝图第一圈·核心地基）**

蓝图将事件溯源定为 ROI 最高的单一模块。没有它：
- 连续性 bug 只能靠 LLM 抽取器检测（精确率和召回率都有上限）
- POV 过滤无法实现（不知道角色 A 在第 N 场景知道什么）
- 信息不对称无法被系统利用（叙事张力的核心燃料缺失）
- 角色状态只有快照，不能追溯"怎么变成这样的"

**蓝图 §17 动作 B 验证**：拿一段已知有连续性 bug 的旧稿跑，量召回率和精确率。如果召回率低 → "整个系统的连续性承诺都是空的，停下来修这一层，不要往上加 Best-of-N"。

### 劣势 2：🔴 无多候选生成——质量上界被锁死

**影响等级：高（蓝图第二圈·质量放大）**

单路径生成只能给你分布的众数。蓝图论证得很清楚：对抗性指标只管下界，上界需要在多候选中挑选。当前系统的质量天花板被"一次生成就定了"锁死。

### 劣势 3：🔴 无张力曲线——节奏失控

**影响等级：中高（蓝图第三圈，但对可读性影响大）**

没有全书张力曲线意味着：
- 不能事前约束场景的节奏参数
- 不能检测"连续 5 个场景都是中等张力"的均匀化问题
- 不能做功能标签的相邻约束

### 劣势 4：🟡 角色建模浅——弧光不可量化

**影响等级：中**

缺决策权重迁移意味着角色弧光只能通过自然语言描述传达给 LLM，无法量化追踪"角色在这个维度上移动了多少"。蓝图的决策权重是角色弧光的**可测代理**。

### 劣势 5：🟡 伏笔管理弱——强化和回收靠运气

**影响等级：中**

`ForeshadowTracker` 只有三态（open/resolved/closed），没有强化计划和到期轮询。长篇小说中伏笔遗忘是读者最容易感知到的"AI 味"之一（大量铺垫无回收 = 废笔感）。

### 劣势 6：🟡 前文自我反重复缺失

**影响等级：中**

当前 plagiarism 只检查参考书引文重复，不检查生成文本与自身前文的重复。蓝图指出"已用过的比喻、场景开头方式、角色动作口癖进'禁用表达列表'"——这是比 logit penalty 更精准的语义级反重复。

---

## 五、优先级排序建议（按 ROI 递减）

| 优先级 | 模块 | 投入预估 | ROI 理由 |
|--------|------|----------|----------|
| **P0** | 事件溯源 MVP | 2-3 周 | ✅ 内核已实现（`NarrativeEvent` 表 + `NarrativeEventLog` 服务 + `project_character_state` 回放 + `check_consistency` 增量校验 + `format_state_for_prompt` 注入 + migration 0054）。待做：接入 orchestrator 自动记录事件 + 接入 prompt builder 注入权威状态。 |
| **P1** | 指标审计 | 半天 | ✅ 已完成（`docs/metrics_audit_adversarial_vs_conformity.md`）。12/18 对抗性，0 顺从性。 |
| **P2** | Best-of-N 原型 | 1-2 周 | ✅ 已完成（`generate_style_draft_candidates` + `adversarial_rank_score` + `candidate_dispersion` + temperature spread）。 |
| **P3** | 伏笔生命周期 | 1 周 | ✅ 已实现（`ForeshadowLifecycleService` + 主动到期轮询 + 强化/回收指令 + 密度检查 + prompt 注入）。 |
| **P4** | 前文反重复引擎 | 1 周 | ✅ 已完成（`SelfRepetitionDetector` + `self_repetition` 维度 + `external_signals` 钩子 + context_budget section）。 |
| **P5** | 张力曲线 + 功能标签 | 1-2 周 | ✅ 基础已实现（`TensionCurveService` + 6 功能标签 + 相邻约束检测 + 张力单调性检测 + 写作参数映射 + prompt 注入）。利用 `writer_brief_json` 存储，无需 migration。 |
| **P6** | 角色决策权重 | 1 周 | SnowflakeCharacterPlan 加决策权重矩阵 + 进度迁移曲线；注入当前场景对应权重。 |
| **P7** | 控制性理念 + 主题校验 | 0.5 周 | StoryProject 加 controlling_idea 字段；每场景 QC 加主题相关性检查。 |

---

## 六、总结

### 一句话评价

> **当前项目是一个工程上完整、风格系统精深、但叙事结构层（事件溯源/因果链/多候选/节奏控制）明显薄弱的系统。蓝图在"正确性地基"上的洞察（事件溯源是 ROI 最高的单一投入）对当前项目最有指导价值。**

### 量化对比

| 蓝图模块（17 节） | 当前覆盖度 |
|-------------------|-----------|
| §0 元原则 | 🟡 隐式存在但未显式声明 |
| §1 优先级同心圆 | 🟡 有优先级但非按 ROI 排序 |
| §2 事件溯源 | 🟢 MVP 已实现（NarrativeEvent + 回放 + 一致性校验 + prompt 注入） |
| §3 三轨检索 | 🟡 21-section 结构化检索存在，但三轨未分离 |
| §4 无 Spec 不生成 | 🟢 Snowflake + SceneCard 基本对齐 |
| §5 伏笔系统 | 🟡 基础存在，生命周期管理弱 |
| §6 分级选择 | 🟢 已实现（Best-of-N + adversarial_rank_score + orchestrator 自动路由） |
| §7 抗趋均值采样 | ⚪ 不适用（API 路线） |
| §8 批判-修订回路 | 🟢 基本对齐（18 维度 QC） |
| §9 风格系统 | 🟢 **超越蓝图**（Style Reference 22 PR） |
| §10 张力曲线 | 🟢 基础已实现（TensionCurveService + 功能标签 + 相邻约束 + prompt 注入） |
| §11 角色深度 | 🟢 已实现（CharacterArcService + 决策权重 + 弧光迁移检测 + prompt 注入） |
| §12 主题管理 | 🟢 已实现（ThemeAnchorService + 控制性理念 + 场景相关性校验 + 表达光谱 + prompt 注入） |
| §13 七步流水线 | 🟢 八步流水线已实现 |
| §14 人机边界 | 🟢 Review gate + author action |
| §15 校验诚实边界 | 🟡 两级 QC 存在，但硬事实校验仍依赖 LLM |
| §16 诚实的代价 | — 设计文档层面，非代码 |
| §17 验证路径 | 🟡 待执行（指标审计 + 事件溯源 MVP） |

**覆盖率统计（实施后）：** 🟢 对齐/超越 11 个 | 🟡 部分覆盖 5 个 | 🔴 缺失 0 个 | ⚪ 不适用 1 个

### 最核心的一条建议

**立即执行蓝图 §17 动作 A（指标审计）**——这是半天工作量、零新代码、能产出数字的动作。审计结果会告诉你 Best-of-N 是否可行、现有 QC 是否在正确方向上。然后再决定是先投入事件溯源（长期 ROI 最高）还是先投入 Best-of-N（短期质量提升最明显）。
