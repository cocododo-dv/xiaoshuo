# 全系统 LLM 提示词优化交接文档

> 面向 Claude Sonnet 5 的自包含提示词优化工作底稿 · 生成于 2026-07-04 · 机器提取 + 人工审计注释，勿手改本文件（改注释/源码后重新生成）。

## §0 给 Sonnet 5 的任务简报

你是一位提示词工程与小说创作双料专家。本文档是一个**中文网文创作系统**（雪花法构思 → 场景生成 → 质量门 → 风格模仿 → 作家评审全管线）的**全量 LLM 提示词交接书**：系统里每一处 LLM 调用、每一份提示词原文、路由参数、输入组装方式、输出契约与失败降级都在这里，你**不需要也无法访问代码仓库**。

### 你的任务
按批次优化本文档 §3–§8 中的提示词（system_prompt / task_prompt / structured_schema 描述部分），并按「回写格式」输出可直接落盘的替换块。**一次会话只处理一个批次**：先给该批的《诊断与改写策略》（每个模板≤5 行：现有问题 → 改法），经确认后再输出回写块。

| 批次 | 主题 | 规模 |
|---|---|---|
| A | 雪花构思管线（14 个模板） | 14 个单元 |
| B | 场景生成与改写（9 个单元，去AI味主战场） | 9 个单元 |
| C | 质量门与裁定（6 个单元） | 6 个单元 |
| D | 风格参考子系统（12 个模板，弱模型鲁棒性主战场） | 12 个单元 |
| E | 作家评审（7 个单元） | 7 个单元 |
| F | 项目与杂项（12 个单元，含内联提示词与休眠任务） | 12 个单元 |

### 优化目标（按优先级）
1. **去AI味 / 文学质量**：本系统自带 21 维文学质量规则打分（感知过滤缺失、冲突太干净、总结式收尾、解释性对白、意象复用、句式单调、自我重复等都是扣分维度）与「蓝图 v2 反AI味」机制。生成类模板（雪花各步、场景蓝图、中性稿、风格化、续写、改写）要把这些维度转译成**可执行的写作指令与禁令**，而不是「写得更生动」式空话。评审/QC 类模板则要求发现项**证据化、可定位、可执行**。
2. **弱模型鲁棒性**：真实执行模型是用户在系统设置里配置的**中档中转模型**（当前典型为 oneapi 中转的 deepseek-v4-flash 一类，而非模板路由里名义上的 gpt-5）。已知病症：**结构化输出不稳**（字段自造、枚举越界、JSON 夹杂散文）与**产出薄**（抽取类返回 0 条或每条只写一半字段）。对策：指令显式分步、字段逐个说明用途并给填写范例、给**产出下限**（最少条数/字数）、把「找不到就返回空」与「必须凑满」的边界讲清楚。注意系统已有降级链路（见 §1），schema 可能被整段内联进 system prompt——schema 本身也是提示词，要精简自描述。

### 硬约束（违反即返工）
1. **structured_schema 的字段名、required 列表、枚举值一律冻结**——下游解析器按名取值（每个单元标注了解析器位置）。确有必要改 schema 时，放进单独的《schema 变更提案》区并说明需要同步改哪处代码，**不得**混进回写块。hard_qc / soft_qc 的 resolution_code / next_action 枚举更是被运行时代码强制合并（§9「qc_schema_alignment」），改了也会被覆盖。
2. **运行时自动追加的内容不要写进模板**：语言锁、角色连续性指令、「Return only valid JSON…」收尾、枚举列举、上下文分节、[STYLE_REFERENCE] 注入块与反抄袭红线、发散化前缀——这些全部由代码追加（清单见 §9）。模板里复写 = 双份指令互相打架。
3. **占位符原样保留**：`{paragraphs}`、`{scene_context_block}`、`{text}`、`{facts_block}`、`{controlling_idea}`、`{ending_state}`、`{chain_block}`、`{banned_terms_list}` 等花括号槽位是代码 format 的接缝，一个都不能丢或改名。
4. **输出语言契约不变**：多数模板是英文指令 + 要求中文产出（scene_text 为中文散文、评审意见跟随草稿语言）。你可以判断某模板改成中文指令对弱模型更稳——允许，但必须在该模板的策略段里说明理由，且语言锁语义不得削弱。
5. **input_token_budget 是输入预算**（不是输出）：task_prompt 加长要克制，上下文大头是自动注入的分节。
6. **version 字段必须 bump**（建议 `2026-07-04.v2` 风格）；`prompt_hash` 会随内容自动变化，无缓存冲突。
7. **反抄袭 / 版权红线语义只增不减**：所有涉参考书的模板（批次 D、风格化）中「抽象风格、禁抄招牌意象、禁复制原文」的约束是法务级要求。
8. **孤儿/休眠/保留单元（标 P2）默认跳过**，除非用户点名。评测集提示词（§10）**勿动**。

### 回写格式（每批次的最终输出）
- **yaml 模板**：每个改动模板输出一个完整可替换块——
  ````
  ### 回写 · <template_key>
  ```yaml
  <template_key>:
    version: "<bumped>"
    input_token_budget: <n>
    system_prompt: |
      ...
    task_prompt: |
      ...
    structured_schema:
      ...（原样保留，除非走《schema 变更提案》）
  ```
  ````
  用户会用它整段替换 `config/prompts.yaml` 里的同名键（顶格两空格缩进，与原文件一致）。
- **Python 内联提示词**：输出「文件路径 + 旧字符串（逐字）→ 新字符串（逐字）」对，供精确替换；占位符与外围引号拼接方式保持原状。
- **不改的模板**：显式列出「跳过：<key>（理由一句话）」。
- **《schema 变更提案》**（如有）：单独一节，含动机、影响的解析器位置、建议的代码改动点。

### 你没有的信息（防幻觉声明）
你看到的是模板与机制，**看不到运行时的真实上下文实例**（bundle 分节内容、参考书 findings 等）。涉及输入实态的判断请以「假设：…」标注；不要虚构本文档未记载的字段名、路由或代码行为。

> 本文档由 `python -m novel_system.tools.export_prompt_handoff` 生成；数字对账见 §12（模板 54、注册节点 60、调用点 38）。

## §1 系统与调用架构速览

**管线图景**：雪花十步构思 →（分诊+物化）→ ChapterGoal/SceneCard → 场景运行管线（bundle 上下文 → 场景蓝图 → 中性稿 → 风格化 Best-of-N（规则盲评选优）→ 可选 LLM 编辑评审 → 硬/软 QC → 近终稿评审）→ 归档/资料库派生。旁路子系统：风格参考（参考书 → 分类 → 四层抽取 → Profile → 注入/验证）、作家评审（四镜头诊断+修订+深评）、文学评测。

**LLM 物理出口只有两类**：
1. `LLMClient.generate`（`backend/src/novel_system/services/llm_client.py:344`）——全部业务调用汇聚于此；
2. 系统设置的连通性探针/模型列表（`backend/src/novel_system/services/system_config.py:1853` 等 3 处裸 httpx，无业务提示词）。
全仓无任何 openai/anthropic SDK 直连、无 embedding API（向量为本地确定性哈希）。

**四条调用路径**（每个单元标注了自己走哪条）：
1. `LLMNodeRunner.run(node_id=…)`——审计路径：`PromptBuilder` 组装、落 `LlmCall` 审计行、上下文预算超限抛连续性错误；
2. `LLMNodeRunner.run_task(task_name=…)`——顾问路径：内联提示词、不落草稿、失败快速降级；别名表 `auto_critique_llm→soft_qc`、`narrative_event_extract→extraction`（借道路由，不占独立节点）；
3. `style_reference/_llm_helper.call_llm_node(node_id, payload)`——user_prompt = 模板 task_prompt + `\n\n` + JSON payload；超时保底 120s；
4. 直接 `LLMClient.generate`：雪花工作台（模板 + JSON payload）、段落分类器（`{paragraphs}` 占位符）、文学评测（内联提示词）。

**PromptBuilder 组装契约**（路径 1 的所有模板）：`system_prompt` **原样发送、无变量替换**；`user_prompt` = task_prompt + 运行时指令（语言锁/角色连续性，仅特定模板）+ schema 收尾指令 + 带英文标签的上下文分节（bundle 快照按 token 预算与 allowlist 裁剪；标签清单见 §9）。所以模板正文里**不出现**花括号变量——数据全部以分节/JSON 形式进 user_prompt。

**路由双层**：`config/models.yaml` 的 task_routing 只是静态兜底；系统设置「模型与接入」写入 DB node_routing（provider/model/api_mode 按「写作主力/审稿质检/提炼整理」三个角色槽批量路由），**DB 优先**。本文档标注的模型/温度是 yaml 默认值——真实执行以用户 DB 配置为准（当前典型：中转 deepseek-v4-flash 类中档模型）。

**降级阶梯**（`LLMClient.generate` 内建，对提示词设计有直接影响）：`/responses` 404 → 换 chat；wire `json_schema` 被拒 → 退 `json_object` → 再退无 response_format，**同时把 schema 以中文提示内联进 system prompt**（原文见 §9「schema_inline_hint」）；空正文（思考烧光预算）→ 关 reasoning + 预算×2 重试。结论按 (provider, model) 进程内缓存。含义：**schema 本身会成为提示词的一部分**，字段名要自解释。

**重试预算**（models.yaml）：hard_partial_max=2，hard_full_max=1，soft_patch_max=2，total_attempt_budget=4。

**提示词的运行时真源**：yaml 模板可被 DB 系统配置快照（category=prompts）**整体覆盖**（`POST /api/v1/system-config/drafts` + activate；导出现行版本用 `GET /api/v1/system-config/export/prompts`）。6 处 Python 内联提示词**不受**快照覆盖。**本文档模板取自：config/prompts.yaml（无生效的 DB prompts 快照）**。优化回写后：若曾激活过 prompts 快照，改文件不生效，需重新走 drafts+activate（或清掉快照）。

## §2 全量 LLM 调用清单（零遗漏）

注册表 60 节点 + 2 个未注册的休眠 ad-hoc 任务 + 连通性探针。状态口径：**活跃**=有真实调用点；**孤儿**=active 且 requires_llm 但无调用点；**模板载体**=仅为镜头节点提供模板名；**保留/本地**=设计上不调 LLM；**休眠**=代码在但无路由无注册，生产不可达。

| # | 节点 / 任务 | 组 | 状态 | 提示词来源 | 调用点 |
|---|---|---|---|---|---|
| 1 | `project_outline_plan` | project | 活跃 | yaml:`project_outline_plan` | `backend/src/novel_system/services/projects.py:487` |
| 2 | `extraction` | reference | 活跃 | 内联:`prose_event_extractor.py` | `backend/src/novel_system/services/prose_event_extractor.py:87` |
| 3 | `library_derive` | project | 活跃 | yaml:`library_derive` | `backend/src/novel_system/services/library_derive.py:121` |
| 4 | `snowflake_step_candidates` | project | 活跃 | yaml:`snowflake_step_candidates` | `backend/src/novel_system/services/snowflake_workspace_llm.py:292` |
| 5 | `chapter_audit_adjudicate` | quality | 活跃 | yaml:`chapter_audit_adjudicate` | `backend/src/novel_system/services/longform_tower.py:680` |
| 6 | `style_profile_extract` | reference | 活跃 | yaml:`style_profile_extract` | `backend/src/novel_system/services/style_profile.py:196` |
| 7 | `reference_sample_ranker` | reference | 孤儿 | yaml:`reference_sample_ranker` | — |
| 8 | `reference_style_structure_extract` | reference | 孤儿 | yaml:`reference_style_structure_extract` | — |
| 9 | `reference_profile_synthesize` | reference | 孤儿 | yaml:`reference_profile_synthesize` | — |
| 10 | `style_ref_paragraph_classify_anchor` | style_reference | 活跃 | yaml:`style_ref_paragraph_classify_anchor` | `backend/src/novel_system/services/style_reference/segmentation/llm.py:201` |
| 11 | `style_ref_paragraph_classify_bulk` | style_reference | 活跃 | yaml:`style_ref_paragraph_classify_bulk` | `backend/src/novel_system/services/style_reference/segmentation/llm.py:201` |
| 12 | `style_ref_extract_language` | style_reference | 活跃 | yaml:`style_ref_extract_language` | `backend/src/novel_system/services/style_reference/extractors/base.py:506` |
| 13 | `style_ref_extract_narrative` | style_reference | 活跃 | yaml:`style_ref_extract_narrative` | `backend/src/novel_system/services/style_reference/extractors/base.py:506` |
| 14 | `style_ref_extract_scene` | style_reference | 活跃 | yaml:`style_ref_extract_scene` | `backend/src/novel_system/services/style_reference/extractors/base.py:506` |
| 15 | `style_ref_extract_theme` | style_reference | 活跃 | yaml:`style_ref_extract_theme` | `backend/src/novel_system/services/style_reference/extractors/base.py:506` |
| 16 | `style_ref_supplement_evidence` | style_reference | 活跃 | yaml:`style_ref_supplement_evidence` | `backend/src/novel_system/services/style_reference/extractors/base.py:506` |
| 17 | `style_ref_synthesize_profile` | style_reference | 活跃 | yaml:`style_ref_synthesize_profile` | `backend/src/novel_system/services/style_reference/profile_synthesizer.py:154` |
| 18 | `style_ref_preview_generate` | style_reference | 活跃 | yaml:`style_ref_preview_generate` | `backend/src/novel_system/services/style_reference/preview.py:164` |
| 19 | `style_ref_validate_semantic` | style_reference | 活跃 | yaml:`style_ref_validate_semantic` | `backend/src/novel_system/services/style_reference/validation/semantic.py:49` |
| 20 | `style_ref_validate_forbidden` | style_reference | 活跃 | yaml:`style_ref_validate_forbidden` | `backend/src/novel_system/services/style_reference/validation/forbidden_semantic.py:62` |
| 21 | `style_ref_rag_rerank` | style_reference | 保留 | yaml:`style_ref_rag_rerank` | — |
| 22 | `snowflake_step_generate` | snowflake | 活跃 | yaml:`snowflake_generate_book_brief` | `backend/src/novel_system/services/snowflake_workspace_llm.py:292` |
| 23 | `snowflake_workspace_assistant` | snowflake | 活跃 | yaml:`snowflake_workspace_assistant` | `backend/src/novel_system/services/snowflake_workspace_llm.py:292` |
| 24 | `snowflake_scene_triage` | snowflake | 活跃 | yaml:`snowflake_scene_triage_suggest` | `backend/src/novel_system/services/snowflake_workspace_llm.py:292` |
| 25 | `scene_blueprint` | scene_generation | 活跃 | yaml:`scene_blueprint` | `backend/src/novel_system/services/scene_blueprint.py:84` |
| 26 | `character_pressure_blueprint` | scene_generation | 活跃 | yaml:`character_pressure_blueprint` | `backend/src/novel_system/services/near_final.py:218` |
| 27 | `chapter_story_architecture` | scene_generation | 活跃 | yaml:`chapter_story_architecture` | `backend/src/novel_system/services/near_final.py:161` |
| 28 | `neutral_draft` | scene_generation | 活跃 | yaml:`neutral_draft` | `backend/src/novel_system/services/scene_generation.py:223` |
| 29 | `style_draft` | scene_generation | 活跃 | yaml:`style_draft` | `backend/src/novel_system/services/scene_generation.py:835` |
| 30 | `style_patch` | scene_generation | 活跃 | yaml:`style_draft` | `backend/src/novel_system/services/scene_generation.py:835`；`backend/src/novel_system/services/scene_generation.py:958` |
| 31 | `scene_literary_rewrite` | rewrite | 活跃 | yaml:`scene_literary_rewrite` | `backend/src/novel_system/services/scene_generation.py:835` |
| 32 | `scene_auto_rewrite` | rewrite | 活跃 | 内联:`scene_quality.py` | `backend/src/novel_system/services/scene_quality.py:572` |
| 33 | `long_form_continuation` | scene_generation | 活跃 | yaml:`long_form_continuation` | `backend/src/novel_system/services/scene_generation.py:693` |
| 34 | `hard_qc` | quality | 活跃 | yaml:`hard_qc` | `backend/src/novel_system/services/qc_engine.py:655` |
| 35 | `soft_qc` | quality | 活跃 | yaml:`soft_qc` | `backend/src/novel_system/services/qc_engine.py:1347` |
| 36 | `scene_quality_contract` | quality | 孤儿·无模板 | 无 | — |
| 37 | `near_final_acceptance_review` | quality | 活跃 | yaml:`near_final_acceptance_review` | `backend/src/novel_system/services/near_final.py:460` |
| 38 | `chapter_near_final_review` | quality | 活跃 | yaml:`chapter_near_final_review` | `backend/src/novel_system/services/near_final.py:531` |
| 39 | `literary_eval_live` | evaluation | 活跃 | 内联:`literary_eval.py` | `backend/src/novel_system/services/literary_eval.py:209` |
| 40 | `writer_scene_diagnosis` | writer_review | 模板载体（镜头节点共用，不直接调用） | yaml:`writer_scene_diagnosis` | — |
| 41 | `writer_scene_story_diagnosis` | writer_review | 活跃 | yaml:`writer_scene_diagnosis` | `backend/src/novel_system/services/writer_review.py:766` |
| 42 | `writer_scene_character_diagnosis` | writer_review | 活跃 | yaml:`writer_scene_diagnosis` | `backend/src/novel_system/services/writer_review.py:766` |
| 43 | `writer_scene_prose_diagnosis` | writer_review | 活跃 | yaml:`writer_scene_diagnosis` | `backend/src/novel_system/services/writer_review.py:766` |
| 44 | `writer_scene_reader_diagnosis` | writer_review | 活跃 | yaml:`writer_scene_diagnosis` | `backend/src/novel_system/services/writer_review.py:766` |
| 45 | `writer_scene_revision` | writer_review | 活跃 | yaml:`writer_scene_revision` | `backend/src/novel_system/services/writer_review.py:810` |
| 46 | `writer_chapter_diagnosis` | writer_review | 模板载体（镜头节点共用，不直接调用） | yaml:`writer_chapter_diagnosis` | — |
| 47 | `writer_chapter_story_diagnosis` | writer_review | 活跃 | yaml:`writer_chapter_diagnosis` | `backend/src/novel_system/services/writer_review.py:766` |
| 48 | `writer_chapter_character_diagnosis` | writer_review | 活跃 | yaml:`writer_chapter_diagnosis` | `backend/src/novel_system/services/writer_review.py:766` |
| 49 | `writer_chapter_prose_diagnosis` | writer_review | 活跃 | yaml:`writer_chapter_diagnosis` | `backend/src/novel_system/services/writer_review.py:766` |
| 50 | `writer_chapter_reader_diagnosis` | writer_review | 活跃 | yaml:`writer_chapter_diagnosis` | `backend/src/novel_system/services/writer_review.py:766` |
| 51 | `writer_chapter_revision` | writer_review | 活跃 | yaml:`writer_chapter_revision` | `backend/src/novel_system/services/writer_review.py:845` |
| 52 | `writer_passage_patch` | rewrite | 活跃 | yaml:`writer_passage_patch` | `backend/src/novel_system/services/writer_deep_review.py:522` |
| 53 | `writer_deep_review` | deep_review | 活跃 | yaml:`writer_deep_review` | `backend/src/novel_system/services/writer_deep_review.py:390` |
| 54 | `author_structure_extract` | evaluation | 活跃 | yaml:`author_structure_extract` | `backend/src/novel_system/services/author_drafts.py:918` |
| 55 | `author_proposal_generate` | writer_review | 活跃 | yaml:`author_proposal_generate` | `backend/src/novel_system/services/author_drafts.py:652` |
| 56 | `writer_reference_application_review` | evaluation | 孤儿 | yaml:`writer_reference_application_review` | — |
| 57 | `chapter_summary` | local | 保留 | yaml:`chapter_summary` | — |
| 58 | `continuity_compression` | local | 保留 | yaml:`continuity_compression` | — |
| 59 | `archive` | local | 本地保留 | 无 | — |
| 60 | `chapter_aggregate` | local | 本地保留 | 无 | — |
| — | `auto_critique_llm`（run_task 任务名） | — | 顾问·活跃（别名→soft_qc） | 内联:`auto_critique.py` | `backend/src/novel_system/services/auto_critique.py:306` |
| — | `narrative_event_extract`（run_task 任务名） | — | 顾问·活跃（别名→extraction） | 内联:`prose_event_extractor.py` | `backend/src/novel_system/services/prose_event_extractor.py:87` |
| — | `consistency_extract`（run_task 任务名） | — | 顾问·休眠（无路由无注册） | 内联:`narrative_event_log.py` | `backend/src/novel_system/services/narrative_event_log.py:501` |
| — | `causal_skeleton_refine`（run_task 任务名） | — | 顾问·休眠（无路由无注册） | 内联:`reverse_causal_skeleton.py` | `backend/src/novel_system/services/reverse_causal_skeleton.py:180` |
| — | `stylize`（task_routing 键） | — | 别名/兜底路由 | 别名/兜底路由：style_draft 与 style_patch 节点的注… | — |
| — | 连通性探针 / 模型列表 | — | 管理路径（无业务提示词） | 无 | `backend/src/novel_system/services/system_config.py:1853`；`backend/src/novel_system/services/system_config.py:389`；`backend/src/novel_system/services/system_config.py:907` |

**调用点合计 38 处**：21× `LLMNodeRunner.run` + 4× `run_task`（2 休眠）+ 7× `call_llm_node` + 3× 直接 `generate` + 3× 管理裸 HTTP。

### 查证过不存在的调用形态（负面证据）

- 无任何 LLM SDK 直连：全仓 grep 无 `import openai` / `import anthropic` / google-genai——12 家 provider 全部是 `services/llm_providers/` 手写 adapter 构造裸 HTTP payload，业务出口唯一收敛在 `LLMClient.generate`。
- 无 embedding API 调用：ChromaDB 使用进程内确定性嵌入 `_DeterministicEmbeddingFunction`（vector_store.py，字符哈希 → 64 维 L2 归一向量），style_reference RAG 三粒度召回同样走它——全系统 0 次 /embeddings 网络调用。
- RAG 注入热路径无 LLM：`style_reference/injection.py` 与 `rag.py` 全确定性（inject <50ms 契约）；`style_ref_rag_rerank` 节点为保留 hook，从未被调用。
- 前端不产出提示词：`frontend-react` 里的 `scnBuildPrompt` / `s2GenPrompt` 是从未被调用的参考死代码（注释明示管线由后端 config/prompts.yaml 组装）；实际请求只带 author_note / 结构化上下文等用户输入。旧 Vue 端仅有只读的注入块预览。
- 同名不同物：`best_of_n_blind_eval.py` 是人工 A/B 盲评 + 二项检验（无 LLM 评委）；`literary_quality.py` 21 维全规则打分；`self_repetition.py` 为 n-gram/模式守卫（无嵌入无 LLM）；`snowflake_workspace_assistant.py`（服务文件）是确定性 fallback 回复器，LLM 助手在 `snowflake_workspace_llm.py`。
- config/writer_rubrics.yaml（评分标尺文本）不注入任何提示词——代码只引用 rubric_id 字符串。
- 测试代码（backend/tests/）与种子工具不发起真实 LLM 调用（Fake/Offline 客户端）。

## §3 批次 A · 雪花构思管线（14 个模板）

十步雪花法的逐步生成（10 个 `snowflake_generate_*` 模板共用节点 `snowflake_step_generate` 的路由）+ 候选发散 / 工作台助手 / 场景分诊 + 项目大纲。共同机制：`snowflake_workspace_llm.py` 的 `_run_structured_task` 把模板 task_prompt 与 JSON 化 payload 拼成 user_prompt（`_render_user_prompt`），system_prompt 原样；LLM 未启用时整体走确定性 fallback，不报错。

### [A-01] snowflake_generate_book_brief — 雪花步骤：读者定位 / 一书简报

- **状态**：活跃（10 个步骤模板共用节点 snowflake_step_generate 的路由）
- **优先级**：P0
- **节点**：`snowflake_step_generate`
- **模板**：`config/prompts.yaml` → `snowflake_generate_book_brief`（version `2026-04-28.v1`，input_token_budget 2600）
- **路由（yaml 兜底，DB 优先）** `默认路由`：model=`gpt-5`，profile=`quality_strong`，temperature=0.25，max_output_tokens=3200，response_format=`json_object`
- **用途**：雪花法第「读者定位 / 一书简报」步的整步草稿生成/补全。
- **触发**：构思工作台「生成本步」端点（api/routes/snowflake_workspace.py → SnowflakeWorkspaceService.generate_step）。
- **调用链**：`backend/src/novel_system/services/snowflake_workspace_llm.py:85`（generate_step 动态选模板）；`backend/src/novel_system/services/snowflake_workspace_llm.py:292`（_run_structured_task 出口）
- **输入组装**：user_prompt = task_prompt + JSON payload（_render_user_prompt）。payload 键：project（项目元信息）、step_key/step_label/step_description/step_instruction/step_guidance/step_editor（步骤定义与编辑器约束）、approved_steps（上游已确认步骤的成果——跨步一致性的唯一来源）、current_draft（合并后的当前草稿）、pressure_rubric + current_pressure_diagnosis（压力评分标尺与当前诊断）、scene_rules（场景规则，后期步骤）。
- **输出契约**：structured_schema 见下；输出是「整步 patch」，经 _normalize_full_step_output 归一 + _assert_meaningful_generation_patch 拒绝空洞补丁（不满足 → SNOWFLAKE_LLM_RESPONSE_INVALID_SCHEMA 409）。（解析/校验：`backend/src/novel_system/services/snowflake_workspace_llm.py:631`、`backend/src/novel_system/services/snowflake_workspace_llm.py:731`）
- **失败与降级**：LLM 未启用 → 确定性 fallback payload（source="fallback"）；路由/模板缺失 → SNOWFLAKE_LLM_ROUTE_OR_PROMPT_MISSING（附「一键补齐」引导）；调用失败 → SNOWFLAKE_LLM_CALL_FAILED。
- **优化注意**：开卷定位：目标读者、爽点承诺、题材基调。优化方向：让承诺具体可验收，避免营销腔空话。 弱模型注意：约束「每字段最少条数/字数」，防空 patch 触发 INVALID_SCHEMA。

**system_prompt（原样发送）**

```text
You are a senior fiction development editor working inside a snowflake-method planning workspace.
Produce transferable planning guidance only. Do not copy protected source text, characters, settings, or signature imagery.
Preserve the user's input language and all approved snowflake facts. Every field should make later scenes easier to write through goal, opposition, cost, and change.
```

**task_prompt（运行时在其后追加指令与上下文）**

```text
Generate the book-brief layer for the current project.
Keep the output concrete, reader-facing, and pressure-aware. Use the provided pressure_rubric and current_pressure_diagnosis to repair generic reader promise, story pressure, or missing cost.
```

**structured_schema（wire 层 + 降级时内联；字段名冻结）**

```json
{
  "additionalProperties": false,
  "properties": {
    "category": {
      "type": "string"
    },
    "delight_reason": {
      "type": "string"
    },
    "expected_reader_emotion": {
      "type": "string"
    },
    "genre_promise": {
      "type": "string"
    },
    "safety_rules": {
      "items": {
        "type": "string"
      },
      "type": "array"
    },
    "story_kind": {
      "type": "string"
    },
    "target_reader": {
      "type": "string"
    }
  },
  "required": [
    "category",
    "target_reader",
    "story_kind",
    "delight_reason",
    "genre_promise",
    "expected_reader_emotion",
    "safety_rules"
  ],
  "type": "object"
}
```

### [A-02] snowflake_generate_one_sentence_summary — 雪花步骤：一句话梗概

- **状态**：活跃（10 个步骤模板共用节点 snowflake_step_generate 的路由）
- **优先级**：P0
- **节点**：`snowflake_step_generate`
- **模板**：`config/prompts.yaml` → `snowflake_generate_one_sentence_summary`（version `2026-04-28.v1`，input_token_budget 2200）
- **路由（yaml 兜底，DB 优先）** `默认路由`：model=`gpt-5`，profile=`quality_strong`，temperature=0.25，max_output_tokens=3200，response_format=`json_object`
- **用途**：雪花法第「一句话梗概」步的整步草稿生成/补全。
- **触发**：构思工作台「生成本步」端点（api/routes/snowflake_workspace.py → SnowflakeWorkspaceService.generate_step）。
- **调用链**：`backend/src/novel_system/services/snowflake_workspace_llm.py:85`（generate_step 动态选模板）；`backend/src/novel_system/services/snowflake_workspace_llm.py:292`（_run_structured_task 出口）
- **输入组装**：user_prompt = task_prompt + JSON payload（_render_user_prompt）。payload 键：project（项目元信息）、step_key/step_label/step_description/step_instruction/step_guidance/step_editor（步骤定义与编辑器约束）、approved_steps（上游已确认步骤的成果——跨步一致性的唯一来源）、current_draft（合并后的当前草稿）、pressure_rubric + current_pressure_diagnosis（压力评分标尺与当前诊断）、scene_rules（场景规则，后期步骤）。
- **输出契约**：structured_schema 见下；输出是「整步 patch」，经 _normalize_full_step_output 归一 + _assert_meaningful_generation_patch 拒绝空洞补丁（不满足 → SNOWFLAKE_LLM_RESPONSE_INVALID_SCHEMA 409）。（解析/校验：`backend/src/novel_system/services/snowflake_workspace_llm.py:631`、`backend/src/novel_system/services/snowflake_workspace_llm.py:731`）
- **失败与降级**：LLM 未启用 → 确定性 fallback payload（source="fallback"）；路由/模板缺失 → SNOWFLAKE_LLM_ROUTE_OR_PROMPT_MISSING（附「一键补齐」引导）；调用失败 → SNOWFLAKE_LLM_CALL_FAILED。
- **优化注意**：15~25 字级别的钩子句。优化方向：主角+欲望+障碍+反差，禁形容词堆砌。 弱模型注意：约束「每字段最少条数/字数」，防空 patch 触发 INVALID_SCHEMA。

**system_prompt（原样发送）**

```text
You are refining a snowflake-method novel premise into a memorable one-sentence summary.
Preserve causal clarity and concrete stakes.
Preserve the user's input language and approved facts; do not drift into a new premise.
```

**task_prompt（运行时在其后追加指令与上下文）**

```text
Return one sentence that captures protagonist, desire, conflict, and cost. Use the pressure_rubric to make the sentence expandable into scenes.
```

**structured_schema（wire 层 + 降级时内联；字段名冻结）**

```json
{
  "additionalProperties": false,
  "properties": {
    "summary": {
      "type": "string"
    }
  },
  "required": [
    "summary"
  ],
  "type": "object"
}
```

### [A-03] snowflake_generate_one_paragraph_summary — 雪花步骤：一段话梗概

- **状态**：活跃（10 个步骤模板共用节点 snowflake_step_generate 的路由）
- **优先级**：P0
- **节点**：`snowflake_step_generate`
- **模板**：`config/prompts.yaml` → `snowflake_generate_one_paragraph_summary`（version `2026-04-28.v1`，input_token_budget 2600）
- **路由（yaml 兜底，DB 优先）** `默认路由`：model=`gpt-5`，profile=`quality_strong`，temperature=0.25，max_output_tokens=3200，response_format=`json_object`
- **用途**：雪花法第「一段话梗概」步的整步草稿生成/补全。
- **触发**：构思工作台「生成本步」端点（api/routes/snowflake_workspace.py → SnowflakeWorkspaceService.generate_step）。
- **调用链**：`backend/src/novel_system/services/snowflake_workspace_llm.py:85`（generate_step 动态选模板）；`backend/src/novel_system/services/snowflake_workspace_llm.py:292`（_run_structured_task 出口）
- **输入组装**：user_prompt = task_prompt + JSON payload（_render_user_prompt）。payload 键：project（项目元信息）、step_key/step_label/step_description/step_instruction/step_guidance/step_editor（步骤定义与编辑器约束）、approved_steps（上游已确认步骤的成果——跨步一致性的唯一来源）、current_draft（合并后的当前草稿）、pressure_rubric + current_pressure_diagnosis（压力评分标尺与当前诊断）、scene_rules（场景规则，后期步骤）。
- **输出契约**：structured_schema 见下；输出是「整步 patch」，经 _normalize_full_step_output 归一 + _assert_meaningful_generation_patch 拒绝空洞补丁（不满足 → SNOWFLAKE_LLM_RESPONSE_INVALID_SCHEMA 409）。（解析/校验：`backend/src/novel_system/services/snowflake_workspace_llm.py:631`、`backend/src/novel_system/services/snowflake_workspace_llm.py:731`）
- **失败与降级**：LLM 未启用 → 确定性 fallback payload（source="fallback"）；路由/模板缺失 → SNOWFLAKE_LLM_ROUTE_OR_PROMPT_MISSING（附「一键补齐」引导）；调用失败 → SNOWFLAKE_LLM_CALL_FAILED。
- **优化注意**：五句结构（开局-三灾-结局）。优化方向：每句都要有不可逆转折，不许「然后」式流水。 弱模型注意：约束「每字段最少条数/字数」，防空 patch 触发 INVALID_SCHEMA。

**system_prompt（原样发送）**

```text
You are expanding a one-sentence premise into a five-sentence snowflake summary.
Keep the escalation causal and specific.
Preserve the user's input language and approved facts; each sentence should make the next pressure turn necessary.
```

**task_prompt（运行时在其后追加指令与上下文）**

```text
Return five key sentences and a moral premise. Sentences 2/3/4 ARE the three disasters and sentence 5 is the ending — the three-act check is derived from them, so do not return it separately. Use the pressure_rubric and current_pressure_diagnosis to strengthen weak disasters, moral turns, and ending cost.
```

**structured_schema（wire 层 + 降级时内联；字段名冻结）**

```json
{
  "additionalProperties": false,
  "properties": {
    "moral_premise": {
      "type": "string"
    },
    "sentences": {
      "items": {
        "type": "string"
      },
      "type": "array"
    }
  },
  "required": [
    "sentences",
    "moral_premise"
  ],
  "type": "object"
}
```

### [A-04] snowflake_generate_character_sheets — 雪花步骤：角色卡

- **状态**：活跃（10 个步骤模板共用节点 snowflake_step_generate 的路由）
- **优先级**：P0
- **节点**：`snowflake_step_generate`
- **模板**：`config/prompts.yaml` → `snowflake_generate_character_sheets`（version `2026-04-28.v1`，input_token_budget 2800）
- **路由（yaml 兜底，DB 优先）** `默认路由`：model=`gpt-5`，profile=`quality_strong`，temperature=0.25，max_output_tokens=3200，response_format=`json_object`
- **用途**：雪花法第「角色卡」步的整步草稿生成/补全。
- **触发**：构思工作台「生成本步」端点（api/routes/snowflake_workspace.py → SnowflakeWorkspaceService.generate_step）。
- **调用链**：`backend/src/novel_system/services/snowflake_workspace_llm.py:85`（generate_step 动态选模板）；`backend/src/novel_system/services/snowflake_workspace_llm.py:292`（_run_structured_task 出口）
- **输入组装**：user_prompt = task_prompt + JSON payload（_render_user_prompt）。payload 键：project（项目元信息）、step_key/step_label/step_description/step_instruction/step_guidance/step_editor（步骤定义与编辑器约束）、approved_steps（上游已确认步骤的成果——跨步一致性的唯一来源）、current_draft（合并后的当前草稿）、pressure_rubric + current_pressure_diagnosis（压力评分标尺与当前诊断）、scene_rules（场景规则，后期步骤）。
- **输出契约**：structured_schema 见下；输出是「整步 patch」，经 _normalize_full_step_output 归一 + _assert_meaningful_generation_patch 拒绝空洞补丁（不满足 → SNOWFLAKE_LLM_RESPONSE_INVALID_SCHEMA 409）。（解析/校验：`backend/src/novel_system/services/snowflake_workspace_llm.py:631`、`backend/src/novel_system/services/snowflake_workspace_llm.py:731`）
- **失败与降级**：LLM 未启用 → 确定性 fallback payload（source="fallback"）；路由/模板缺失 → SNOWFLAKE_LLM_ROUTE_OR_PROMPT_MISSING（附「一键补齐」引导）；调用失败 → SNOWFLAKE_LLM_CALL_FAILED。
- **优化注意**：主要角色的欲望/冲突/顿悟骨架。优化方向：目标-价值观-冲突三角要互相咬合，禁标签化人设。 弱模型注意：约束「每字段最少条数/字数」，防空 patch 触发 INVALID_SCHEMA。

**system_prompt（原样发送）**

```text
You are outlining major character pressure inside a snowflake-method workspace.
Make each character distinct in desire, value, conflict, and change.
Preserve the user's input language and approved facts; every important character should feel like the lead of their own pressure story.
```

**task_prompt（运行时在其后追加指令与上下文）**

```text
Return structured character sheets for the key cast. Emphasize concrete goals, blocking forces, value conflicts, epiphanies, and how each character can generate scenes.
```

**structured_schema（wire 层 + 降级时内联；字段名冻结）**

```json
{
  "additionalProperties": false,
  "properties": {
    "characters": {
      "items": {
        "additionalProperties": true,
        "type": "object"
      },
      "type": "array"
    }
  },
  "required": [
    "characters"
  ],
  "type": "object"
}
```

### [A-05] snowflake_generate_short_synopsis — 雪花步骤：一页梗概

- **状态**：活跃（10 个步骤模板共用节点 snowflake_step_generate 的路由）
- **优先级**：P0
- **节点**：`snowflake_step_generate`
- **模板**：`config/prompts.yaml` → `snowflake_generate_short_synopsis`（version `2026-04-28.v1`，input_token_budget 2600）
- **路由（yaml 兜底，DB 优先）** `默认路由`：model=`gpt-5`，profile=`quality_strong`，temperature=0.25，max_output_tokens=3200，response_format=`json_object`
- **用途**：雪花法第「一页梗概」步的整步草稿生成/补全。
- **触发**：构思工作台「生成本步」端点（api/routes/snowflake_workspace.py → SnowflakeWorkspaceService.generate_step）。
- **调用链**：`backend/src/novel_system/services/snowflake_workspace_llm.py:85`（generate_step 动态选模板）；`backend/src/novel_system/services/snowflake_workspace_llm.py:292`（_run_structured_task 出口）
- **输入组装**：user_prompt = task_prompt + JSON payload（_render_user_prompt）。payload 键：project（项目元信息）、step_key/step_label/step_description/step_instruction/step_guidance/step_editor（步骤定义与编辑器约束）、approved_steps（上游已确认步骤的成果——跨步一致性的唯一来源）、current_draft（合并后的当前草稿）、pressure_rubric + current_pressure_diagnosis（压力评分标尺与当前诊断）、scene_rules（场景规则，后期步骤）。
- **输出契约**：structured_schema 见下；输出是「整步 patch」，经 _normalize_full_step_output 归一 + _assert_meaningful_generation_patch 拒绝空洞补丁（不满足 → SNOWFLAKE_LLM_RESPONSE_INVALID_SCHEMA 409）。（解析/校验：`backend/src/novel_system/services/snowflake_workspace_llm.py:631`、`backend/src/novel_system/services/snowflake_workspace_llm.py:731`）
- **失败与降级**：LLM 未启用 → 确定性 fallback payload（source="fallback"）；路由/模板缺失 → SNOWFLAKE_LLM_ROUTE_OR_PROMPT_MISSING（附「一键补齐」引导）；调用失败 → SNOWFLAKE_LLM_CALL_FAILED。
- **优化注意**：一段话梗概逐句扩为段。优化方向：因果链显式（因为…所以…不料…），保持灾难升级坡度。 弱模型注意：约束「每字段最少条数/字数」，防空 patch 触发 INVALID_SCHEMA。

**system_prompt（原样发送）**

```text
You are expanding a five-sentence snowflake summary into a short synopsis.
Keep the synopsis act-shaped and causally linked.
Preserve the user's input language and approved facts; avoid summary filler that does not raise pressure or cost.
```

**task_prompt（运行时在其后追加指令与上下文）**

```text
Return a short synopsis as structured paragraphs. Each paragraph should contain a pressure turn: action, resistance, consequence, and changed situation.
```

**structured_schema（wire 层 + 降级时内联；字段名冻结）**

```json
{
  "additionalProperties": false,
  "properties": {
    "paragraphs": {
      "items": {
        "type": "string"
      },
      "type": "array"
    }
  },
  "required": [
    "paragraphs"
  ],
  "type": "object"
}
```

### [A-06] snowflake_generate_character_synopses — 雪花步骤：角色梗概

- **状态**：活跃（10 个步骤模板共用节点 snowflake_step_generate 的路由）
- **优先级**：P0
- **节点**：`snowflake_step_generate`
- **模板**：`config/prompts.yaml` → `snowflake_generate_character_synopses`（version `2026-04-28.v1`，input_token_budget 2800）
- **路由（yaml 兜底，DB 优先）** `默认路由`：model=`gpt-5`，profile=`quality_strong`，temperature=0.25，max_output_tokens=3200，response_format=`json_object`
- **用途**：雪花法第「角色梗概」步的整步草稿生成/补全。
- **触发**：构思工作台「生成本步」端点（api/routes/snowflake_workspace.py → SnowflakeWorkspaceService.generate_step）。
- **调用链**：`backend/src/novel_system/services/snowflake_workspace_llm.py:85`（generate_step 动态选模板）；`backend/src/novel_system/services/snowflake_workspace_llm.py:292`（_run_structured_task 出口）
- **输入组装**：user_prompt = task_prompt + JSON payload（_render_user_prompt）。payload 键：project（项目元信息）、step_key/step_label/step_description/step_instruction/step_guidance/step_editor（步骤定义与编辑器约束）、approved_steps（上游已确认步骤的成果——跨步一致性的唯一来源）、current_draft（合并后的当前草稿）、pressure_rubric + current_pressure_diagnosis（压力评分标尺与当前诊断）、scene_rules（场景规则，后期步骤）。
- **输出契约**：structured_schema 见下；输出是「整步 patch」，经 _normalize_full_step_output 归一 + _assert_meaningful_generation_patch 拒绝空洞补丁（不满足 → SNOWFLAKE_LLM_RESPONSE_INVALID_SCHEMA 409）。（解析/校验：`backend/src/novel_system/services/snowflake_workspace_llm.py:631`、`backend/src/novel_system/services/snowflake_workspace_llm.py:731`）
- **失败与降级**：LLM 未启用 → 确定性 fallback payload（source="fallback"）；路由/模板缺失 → SNOWFLAKE_LLM_ROUTE_OR_PROMPT_MISSING（附「一键补齐」引导）；调用失败 → SNOWFLAKE_LLM_CALL_FAILED。
- **优化注意**：每个角色视角重述故事。优化方向：视角差异要产生信息差与动机冲突，不是同一故事换主语。 弱模型注意：约束「每字段最少条数/字数」，防空 patch 触发 INVALID_SCHEMA。

**system_prompt（原样发送）**

```text
You are writing concise character-throughline synopses for a snowflake workspace.
Emphasize how each character enters the story conflict and changes under pressure.
Preserve the user's input language and approved facts; do not invent unrelated cast members.
```

**task_prompt（运行时在其后追加指令与上下文）**

```text
Return structured character synopses for the current cast. Tie backstory to present-story desire, fear, opposition, and scene behavior.
```

**structured_schema（wire 层 + 降级时内联；字段名冻结）**

```json
{
  "additionalProperties": false,
  "properties": {
    "characters": {
      "items": {
        "additionalProperties": true,
        "type": "object"
      },
      "type": "array"
    }
  },
  "required": [
    "characters"
  ],
  "type": "object"
}
```

### [A-07] snowflake_generate_long_synopsis — 雪花步骤：长纲

- **状态**：活跃（10 个步骤模板共用节点 snowflake_step_generate 的路由）
- **优先级**：P0
- **节点**：`snowflake_step_generate`
- **模板**：`config/prompts.yaml` → `snowflake_generate_long_synopsis`（version `2026-04-28.v1`，input_token_budget 3200）
- **路由（yaml 兜底，DB 优先）** `默认路由`：model=`gpt-5`，profile=`quality_strong`，temperature=0.25，max_output_tokens=3200，response_format=`json_object`
- **用途**：雪花法第「长纲」步的整步草稿生成/补全。
- **触发**：构思工作台「生成本步」端点（api/routes/snowflake_workspace.py → SnowflakeWorkspaceService.generate_step）。
- **调用链**：`backend/src/novel_system/services/snowflake_workspace_llm.py:85`（generate_step 动态选模板）；`backend/src/novel_system/services/snowflake_workspace_llm.py:292`（_run_structured_task 出口）
- **输入组装**：user_prompt = task_prompt + JSON payload（_render_user_prompt）。payload 键：project（项目元信息）、step_key/step_label/step_description/step_instruction/step_guidance/step_editor（步骤定义与编辑器约束）、approved_steps（上游已确认步骤的成果——跨步一致性的唯一来源）、current_draft（合并后的当前草稿）、pressure_rubric + current_pressure_diagnosis（压力评分标尺与当前诊断）、scene_rules（场景规则，后期步骤）。
- **输出契约**：structured_schema 见下；输出是「整步 patch」，经 _normalize_full_step_output 归一 + _assert_meaningful_generation_patch 拒绝空洞补丁（不满足 → SNOWFLAKE_LLM_RESPONSE_INVALID_SCHEMA 409）。（解析/校验：`backend/src/novel_system/services/snowflake_workspace_llm.py:631`、`backend/src/novel_system/services/snowflake_workspace_llm.py:731`）
- **失败与降级**：LLM 未启用 → 确定性 fallback payload（source="fallback"）；路由/模板缺失 → SNOWFLAKE_LLM_ROUTE_OR_PROMPT_MISSING（附「一键补齐」引导）；调用失败 → SNOWFLAKE_LLM_CALL_FAILED。
- **优化注意**：一页梗概扩为数页长纲。优化方向：中段防塌陷——每节都要有代价与状态变化。 弱模型注意：约束「每字段最少条数/字数」，防空 patch 触发 INVALID_SCHEMA。

**system_prompt（原样发送）**

```text
You are expanding a short snowflake synopsis into a fuller long synopsis.
Preserve escalation, reversals, and ending cost.
Preserve the user's input language and approved facts; deepen the same story rather than replacing it.
```

**task_prompt（运行时在其后追加指令与上下文）**

```text
Return the long synopsis as structured paragraphs. Maintain causal escalation, clear reversals, and pressure that can later become scene goals and setbacks.
```

**structured_schema（wire 层 + 降级时内联；字段名冻结）**

```json
{
  "additionalProperties": false,
  "properties": {
    "paragraphs": {
      "items": {
        "type": "string"
      },
      "type": "array"
    }
  },
  "required": [
    "paragraphs"
  ],
  "type": "object"
}
```

### [A-08] snowflake_generate_character_bibles — 雪花步骤：角色圣经

- **状态**：活跃（10 个步骤模板共用节点 snowflake_step_generate 的路由）
- **优先级**：P0
- **节点**：`snowflake_step_generate`
- **模板**：`config/prompts.yaml` → `snowflake_generate_character_bibles`（version `2026-04-28.v1`，input_token_budget 3200）
- **路由（yaml 兜底，DB 优先）** `默认路由`：model=`gpt-5`，profile=`quality_strong`，temperature=0.25，max_output_tokens=3200，response_format=`json_object`
- **用途**：雪花法第「角色圣经」步的整步草稿生成/补全。
- **触发**：构思工作台「生成本步」端点（api/routes/snowflake_workspace.py → SnowflakeWorkspaceService.generate_step）。
- **调用链**：`backend/src/novel_system/services/snowflake_workspace_llm.py:85`（generate_step 动态选模板）；`backend/src/novel_system/services/snowflake_workspace_llm.py:292`（_run_structured_task 出口）
- **输入组装**：user_prompt = task_prompt + JSON payload（_render_user_prompt）。payload 键：project（项目元信息）、step_key/step_label/step_description/step_instruction/step_guidance/step_editor（步骤定义与编辑器约束）、approved_steps（上游已确认步骤的成果——跨步一致性的唯一来源）、current_draft（合并后的当前草稿）、pressure_rubric + current_pressure_diagnosis（压力评分标尺与当前诊断）、scene_rules（场景规则，后期步骤）。
- **输出契约**：structured_schema 见下；输出是「整步 patch」，经 _normalize_full_step_output 归一 + _assert_meaningful_generation_patch 拒绝空洞补丁（不满足 → SNOWFLAKE_LLM_RESPONSE_INVALID_SCHEMA 409）。（解析/校验：`backend/src/novel_system/services/snowflake_workspace_llm.py:631`、`backend/src/novel_system/services/snowflake_workspace_llm.py:731`）
- **失败与降级**：LLM 未启用 → 确定性 fallback payload（source="fallback"）；路由/模板缺失 → SNOWFLAKE_LLM_ROUTE_OR_PROMPT_MISSING（附「一键补齐」引导）；调用失败 → SNOWFLAKE_LLM_CALL_FAILED。
- **优化注意**：角色全维度设定。优化方向：条目要「可写作调用」（说话习惯、决策偏好），不是百科罗列。 弱模型注意：约束「每字段最少条数/字数」，防空 patch 触发 INVALID_SCHEMA。

**system_prompt（原样发送）**

```text
You are deepening character bibles for a snowflake-method novel.
Keep biography in service of scene pressure and transformation.
Preserve the user's input language and approved facts; every detail should help future scene behavior, conflict, or change.
```

**task_prompt（运行时在其后追加指令与上下文）**

```text
Return structured character bible entries for the core cast. Prioritize wounds, values, contradictions, fears, and visible behaviors under pressure.
```

**structured_schema（wire 层 + 降级时内联；字段名冻结）**

```json
{
  "additionalProperties": false,
  "properties": {
    "characters": {
      "items": {
        "additionalProperties": true,
        "type": "object"
      },
      "type": "array"
    }
  },
  "required": [
    "characters"
  ],
  "type": "object"
}
```

### [A-09] snowflake_generate_scene_list — 雪花步骤：场景清单

- **状态**：活跃（10 个步骤模板共用节点 snowflake_step_generate 的路由）
- **优先级**：P0
- **节点**：`snowflake_step_generate`
- **模板**：`config/prompts.yaml` → `snowflake_generate_scene_list`（version `2026-04-28.v1`，input_token_budget 3200）
- **路由（yaml 兜底，DB 优先）** `默认路由`：model=`gpt-5`，profile=`quality_strong`，temperature=0.25，max_output_tokens=3200，response_format=`json_object`
- **用途**：雪花法第「场景清单」步的整步草稿生成/补全。
- **触发**：构思工作台「生成本步」端点（api/routes/snowflake_workspace.py → SnowflakeWorkspaceService.generate_step）。
- **调用链**：`backend/src/novel_system/services/snowflake_workspace_llm.py:85`（generate_step 动态选模板）；`backend/src/novel_system/services/snowflake_workspace_llm.py:292`（_run_structured_task 出口）
- **输入组装**：user_prompt = task_prompt + JSON payload（_render_user_prompt）。payload 键：project（项目元信息）、step_key/step_label/step_description/step_instruction/step_guidance/step_editor（步骤定义与编辑器约束）、approved_steps（上游已确认步骤的成果——跨步一致性的唯一来源）、current_draft（合并后的当前草稿）、pressure_rubric + current_pressure_diagnosis（压力评分标尺与当前诊断）、scene_rules（场景规则，后期步骤）。
- **输出契约**：structured_schema 见下；输出是「整步 patch」，经 _normalize_full_step_output 归一 + _assert_meaningful_generation_patch 拒绝空洞补丁（不满足 → SNOWFLAKE_LLM_RESPONSE_INVALID_SCHEMA 409）。（解析/校验：`backend/src/novel_system/services/snowflake_workspace_llm.py:631`、`backend/src/novel_system/services/snowflake_workspace_llm.py:731`）
- **失败与降级**：LLM 未启用 → 确定性 fallback payload（source="fallback"）；路由/模板缺失 → SNOWFLAKE_LLM_ROUTE_OR_PROMPT_MISSING（附「一键补齐」引导）；调用失败 → SNOWFLAKE_LLM_CALL_FAILED。
- **优化注意**：长纲切分为场景行（POV/目标/冲突）。优化方向：主动场景 Goal-Conflict-Setback、反应场景 Reaction-Dilemma-Decision 的骨架完整度。 弱模型注意：约束「每字段最少条数/字数」，防空 patch 触发 INVALID_SCHEMA。

**system_prompt（原样发送）**

```text
You are breaking a snowflake synopsis into a scene list.
Each scene should have a clear job in the chapter and a distinct point-of-view pressure.
Preserve the user's input language and approved facts; do not add scenes that only explain backstory or atmosphere.
```

**task_prompt（运行时在其后追加指令与上下文）**

```text
Return the scene list as structured scene cards. Each scene needs POV pressure, conflict, and a result/change that forces the next scene.
```

**structured_schema（wire 层 + 降级时内联；字段名冻结）**

```json
{
  "additionalProperties": false,
  "properties": {
    "scenes": {
      "items": {
        "additionalProperties": true,
        "type": "object"
      },
      "type": "array"
    }
  },
  "required": [
    "scenes"
  ],
  "type": "object"
}
```

### [A-10] snowflake_generate_scene_details — 雪花步骤：场景规划

- **状态**：活跃（10 个步骤模板共用节点 snowflake_step_generate 的路由）
- **优先级**：P0
- **节点**：`snowflake_step_generate`
- **模板**：`config/prompts.yaml` → `snowflake_generate_scene_details`（version `2026-04-28.v1`，input_token_budget 3600）
- **路由（yaml 兜底，DB 优先）** `默认路由`：model=`gpt-5`，profile=`quality_strong`，temperature=0.25，max_output_tokens=3200，response_format=`json_object`
- **用途**：雪花法第「场景规划」步的整步草稿生成/补全。
- **触发**：构思工作台「生成本步」端点（api/routes/snowflake_workspace.py → SnowflakeWorkspaceService.generate_step）。
- **调用链**：`backend/src/novel_system/services/snowflake_workspace_llm.py:85`（generate_step 动态选模板）；`backend/src/novel_system/services/snowflake_workspace_llm.py:292`（_run_structured_task 出口）
- **输入组装**：user_prompt = task_prompt + JSON payload（_render_user_prompt）。payload 键：project（项目元信息）、step_key/step_label/step_description/step_instruction/step_guidance/step_editor（步骤定义与编辑器约束）、approved_steps（上游已确认步骤的成果——跨步一致性的唯一来源）、current_draft（合并后的当前草稿）、pressure_rubric + current_pressure_diagnosis（压力评分标尺与当前诊断）、scene_rules（场景规则，后期步骤）。
- **输出契约**：structured_schema 见下；输出是「整步 patch」，经 _normalize_full_step_output 归一 + _assert_meaningful_generation_patch 拒绝空洞补丁（不满足 → SNOWFLAKE_LLM_RESPONSE_INVALID_SCHEMA 409）。（解析/校验：`backend/src/novel_system/services/snowflake_workspace_llm.py:631`、`backend/src/novel_system/services/snowflake_workspace_llm.py:731`）
- **失败与降级**：LLM 未启用 → 确定性 fallback payload（source="fallback"）；路由/模板缺失 → SNOWFLAKE_LLM_ROUTE_OR_PROMPT_MISSING（附「一键补齐」引导）；调用失败 → SNOWFLAKE_LLM_CALL_FAILED。
- **优化注意**：逐场景细化（分诊的输入）。优化方向：压力值/必备三要素饱满，直接决定物化后 SceneCard.writer_brief 质量。 弱模型注意：约束「每字段最少条数/字数」，防空 patch 触发 INVALID_SCHEMA。

**system_prompt（原样发送）**

```text
You are converting a scene list into Scene / Sequel detail.
Respect existing scene membership and order. Do not invent extra scenes.
Preserve the user's input language, scene IDs, chapter membership, and approved facts.
```

**task_prompt（运行时在其后追加指令与上下文）**

```text
For each scene, deepen the summary, scene crucible, and the required proactive or reactive trio. Use pressure_rubric and current_pressure_diagnosis to avoid weak conflict, weak setback, fake dilemma, and decisions that do not trigger the next goal.
```

**structured_schema（wire 层 + 降级时内联；字段名冻结）**

```json
{
  "additionalProperties": false,
  "properties": {
    "scenes": {
      "items": {
        "additionalProperties": true,
        "type": "object"
      },
      "type": "array"
    }
  },
  "required": [
    "scenes"
  ],
  "type": "object"
}
```

### [A-11] snowflake_step_candidates — 构思步骤 3 条发散候选

- **状态**：活跃
- **优先级**：P1
- **节点**：`snowflake_step_candidates`
- **模板**：`config/prompts.yaml` → `snowflake_step_candidates`（version `2026-06-12.v1`，input_token_budget 2600）
- **路由（yaml 兜底，DB 优先）** `默认路由`：model=`gpt-5`，profile=`quality_strong`，temperature=0.7，max_output_tokens=1800，response_format=`json_object`
- **用途**：构思视图「生成 3 条不同方向候选」——同一步骤给出三个方向上真正不同的草稿候选。
- **触发**：POST /api/v2/projects/{id}/snowflake-workspace/steps/{key}/fe-candidates（前端带折叠上下文）。
- **调用链**：`backend/src/novel_system/services/snowflake_workspace_llm.py:123`（step_candidates）
- **输入组装**：payload 键：project、步骤定义/指引、upstream_context（前端折叠的上游上下文文本）、current_draft_text、target_chars（目标字数）。
- **输出契约**：candidates 数组；经 _normalize_candidates_output 归一。（解析/校验：`backend/src/novel_system/services/snowflake_workspace_llm.py:609`）
- **失败与降级**：LLM 未启用 → fallback {"candidates": []}；错误码同雪花家族。
- **优化注意**：「三个方向不同」是核心——当前弱模型易产出三条同质候选。优化时把差异维度显式化（题材切口/情绪基调/结构策略各占一条），并给每条候选字数下限。

**system_prompt（原样发送）**

```text
You are a snowflake-method writing assistant generating divergent draft candidates for one step of a long-form Chinese novel plan.
Stay strictly consistent with the upstream material (characters, conflicts, moral premise). Never invent facts that contradict it.
Write candidate text in the author's input language (Chinese unless the material says otherwise).
```

**task_prompt（运行时在其后追加指令与上下文）**

```text
Produce exactly 3 candidates that take genuinely different directions (for example emotion-led, plot-push-led, contrast-led, or any axis that fits this step).
Each candidate's text must be directly adoptable prose for the step itself - no explanations, no headings - and stay within target_chars characters.
Each label is at most 4 Chinese characters; each tag is one positioning phrase of at most 12 characters; notes are up to 3 bullets of at most 6 characters each.
```

**structured_schema（wire 层 + 降级时内联；字段名冻结）**

```json
{
  "additionalProperties": false,
  "properties": {
    "candidates": {
      "items": {
        "additionalProperties": false,
        "properties": {
          "label": {
            "type": "string"
          },
          "notes": {
            "items": {
              "type": "string"
            },
            "type": "array"
          },
          "tag": {
            "type": "string"
          },
          "text": {
            "type": "string"
          }
        },
        "required": [
          "label",
          "tag",
          "text",
          "notes"
        ],
        "type": "object"
      },
      "type": "array"
    }
  },
  "required": [
    "candidates"
  ],
  "type": "object"
}
```

### [A-12] snowflake_workspace_assistant — 构思工作台对话助手

- **状态**：活跃
- **优先级**：P1
- **节点**：`snowflake_workspace_assistant`
- **模板**：`config/prompts.yaml` → `snowflake_workspace_assistant`（version `2026-04-28.v1`，input_token_budget 2600）
- **路由（yaml 兜底，DB 优先）** `默认路由`：model=`gpt-5`，profile=`quality_strong`，temperature=0.35，max_output_tokens=2200，response_format=`json_object`
- **用途**：步骤内多轮教练式对话：根据作者 message 与当前草稿给出建议或直接产出草稿 patch。
- **触发**：构思工作台助手端点（api/routes/snowflake_workspace.py → request_assistant）。
- **调用链**：`backend/src/novel_system/services/snowflake_workspace_llm.py:165`（assistant_reply）
- **输入组装**：payload 键：project、步骤定义/指引/editor、draft（当前草稿）、message（作者输入）、approved_context（已确认上游）、focus_scene_id/focus_scene（场景聚焦）、pressure_rubric + 诊断、scene_rules。
- **输出契约**：回复 + 可选 patch；经 _normalize_assistant_output 归一（含与 base_draft 的合并语义）。（解析/校验：`backend/src/novel_system/services/snowflake_workspace_llm.py:644`）
- **失败与降级**：LLM 未启用 → SnowflakeWorkspaceAssistantService 的确定性 fallback 回复（source="fallback"）。
- **优化注意**：区分「建议模式」与「改稿模式」的判据要明确（何时回话、何时给 patch）；patch 必须尊重 approved 上游事实。

**system_prompt（原样发送）**

```text
You are a resident snowflake-method writing coach.
Give concrete editorial guidance tied to the author's current step, and only propose writeback for the current step.
Preserve the user's input language and approved facts. Prioritize structural pressure over decorative prose.
```

**task_prompt（运行时在其后追加指令与上下文）**

```text
Answer the author's question, give a few concise suggestions, and optionally return a structured candidate patch for the current step.
If no safe writeback is appropriate, return an empty object for candidate_patch and an empty string for candidate_label.
Use pressure_rubric and current_pressure_diagnosis to target missing goal, opposition, cost, change, or next-step expandability.
```

**structured_schema（wire 层 + 降级时内联；字段名冻结）**

```json
{
  "additionalProperties": false,
  "properties": {
    "candidate_label": {
      "type": "string"
    },
    "candidate_patch": {
      "additionalProperties": true,
      "type": "object"
    },
    "reply": {
      "type": "string"
    },
    "suggestions": {
      "items": {
        "type": "string"
      },
      "type": "array"
    }
  },
  "required": [
    "reply",
    "suggestions",
    "candidate_label",
    "candidate_patch"
  ],
  "type": "object"
}
```

### [A-13] snowflake_scene_triage_suggest — 场景三态分诊建议（节点 snowflake_scene_triage）

- **状态**：活跃
- **优先级**：P1
- **节点**：`snowflake_scene_triage`
- **模板**：`config/prompts.yaml` → `snowflake_scene_triage_suggest`（version `2026-04-28.v1`，input_token_budget 2600）
- **路由（yaml 兜底，DB 优先）** `默认路由`：model=`gpt-5`，profile=`quality_strong`，temperature=0.15，max_output_tokens=2200，response_format=`json_object`
- **用途**：物化前对每个场景计划给 pass / maybe / rewrite 三态建议（qualified/needs_fix/rewrite 分诊的 LLM 辅助）。
- **触发**：POST …/snowflake-workspace/scene-triage/suggest（api/routes/snowflake_workspace.py → suggest_scene_triage）。
- **调用链**：`backend/src/novel_system/services/snowflake_workspace_llm.py:208`（scene_triage_suggestions）
- **输入组装**：payload 键：project、scene_details 草稿全量、approved_context、pressure_rubric + 诊断、triage_rules（三态判据文本，代码内固定英文——判据也可作为优化对象但要连模板一起改）、scene_rules。
- **输出契约**：items 数组（逐场景三态 + 理由）；经 _normalize_triage_output 与草稿对齐（缺失场景回填 fallback 判定）。（解析/校验：`backend/src/novel_system/services/snowflake_workspace_llm.py:672`）
- **失败与降级**：LLM 未启用 → _fallback_triage_items 确定性分诊。
- **优化注意**：三态边界（尤其 maybe vs rewrite）要给判例；要求每条建议附具体缺陷点而非笼统评语，供作者一键修复。

**system_prompt（原样发送）**

```text
You are reviewing scene pressure in a snowflake workspace before outline materialization.
Evaluate only whether each scene is passable, needs revision, or should be rebuilt.
Preserve scene IDs and the user's input language. Diagnose pressure, not prose polish.
```

**task_prompt（运行时在其后追加指令与上下文）**

```text
Return triage suggestions for each scene. Use only the legal statuses pass, maybe, and rewrite.
Flag scenes with weak conflict, weak setback, fake dilemma, or decisions that do not create a next goal even when required fields are filled.
```

**structured_schema（wire 层 + 降级时内联；字段名冻结）**

```json
{
  "additionalProperties": false,
  "properties": {
    "items": {
      "items": {
        "additionalProperties": false,
        "properties": {
          "fix_steps": {
            "items": {
              "type": "string"
            },
            "type": "array"
          },
          "missing_fields": {
            "items": {
              "type": "string"
            },
            "type": "array"
          },
          "notes": {
            "type": "string"
          },
          "repair_patch": {
            "additionalProperties": true,
            "type": "object"
          },
          "scene_id": {
            "type": "string"
          },
          "status": {
            "enum": [
              "pass",
              "maybe",
              "rewrite"
            ],
            "type": "string"
          }
        },
        "required": [
          "scene_id",
          "status",
          "notes",
          "missing_fields",
          "fix_steps",
          "repair_patch"
        ],
        "type": "object"
      },
      "type": "array"
    }
  },
  "required": [
    "items"
  ],
  "type": "object"
}
```

### [A-14] project_outline_plan — 项目大纲规划

- **状态**：活跃
- **优先级**：P1
- **节点**：`project_outline_plan`
- **模板**：`config/prompts.yaml` → `project_outline_plan`（version `2026-04-26.v1`，input_token_budget 3000）
- **路由（yaml 兜底，DB 优先）** `默认路由`：model=`gpt-5`，temperature=0.25，max_output_tokens=3200，response_format=`json_object`
- **用途**：项目级 OutlinePlan 的 LLM 生成（雪花之外的粗纲入口）。
- **触发**：POST /api/v1/projects/{id}/outline（api/routes/projects.py → OutlinePlannerService）。
- **调用链**：`backend/src/novel_system/services/projects.py:487`（_build_llm_plan，经 PromptBuilder）
- **输入组装**：PromptBuilder 组装：项目快照上下文分节 + task_prompt + schema 指令。
- **输出契约**：大纲计划结构；服务内手工解析归一。（解析/校验：`backend/src/novel_system/services/projects.py:487`）
- **失败与降级**：LLMNodeExecutionError 上抛（路由未配则 409 引导配置）。
- **优化注意**：与雪花管线的分工要在提示词里说清（粗纲 vs 十步细化），避免产出与雪花步骤重复的粒度。

**system_prompt（原样发送）**

```text
You convert a user's free-form novel outline into a reviewable chapter and scene plan.
Use only abstract reference-style guidance. Do not copy source-book wording, characters, settings, plot turns, or signature imagery.
```

**task_prompt（运行时在其后追加指令与上下文）**

```text
Split the outline into chapters and scenes that can map directly to ChapterGoal and SceneCard.
Return chapter_goal, main_plot_push, emotional_target, ending_effect, must_not, and scenes.
Each scene must include scene_goal, beats_json, must_include_text, forbidden_text, exit_change, hook, target_length_band, and scene_type.
The user will approve this plan before any prose is drafted.
```

**structured_schema（wire 层 + 降级时内联；字段名冻结）**

```json
{
  "additionalProperties": false,
  "properties": {
    "chapters": {
      "items": {
        "additionalProperties": true,
        "type": "object"
      },
      "type": "array"
    },
    "reference_safety": {
      "items": {
        "type": "string"
      },
      "type": "array"
    }
  },
  "required": [
    "chapters",
    "reference_safety"
  ],
  "type": "object"
}
```

## §4 批次 B · 场景生成与改写（9 个单元，去AI味主战场）

场景运行管线（编排：`orchestrator.py` — bundle 上下文 → 蓝图 → 中性稿 → 风格化 Best-of-N → QC → 近终稿）里的全部生成/改写节点。这些节点经 `PromptBuilder` 组装：system_prompt 原样，user_prompt = task_prompt + 运行时语言锁/连续性指令 + schema 指令 + 按预算裁剪的上下文分节（见 §9 片段附录）。风格化节点还会被注入 [STYLE_REFERENCE] 系统块（含反抄袭红线）与发散化前缀。

### [B-01] scene_blueprint — 场景文学蓝图（蓝图 v2）

- **状态**：活跃
- **优先级**：P0
- **节点**：`scene_blueprint`
- **模板**：`config/prompts.yaml` → `scene_blueprint`（version `2026-04-25.v2`，input_token_budget 2200）
- **路由（yaml 兜底，DB 优先）** `默认路由`：model=`gpt-5`，temperature=0.25，max_output_tokens=1800，response_format=`json_object`
- **用途**：起草前的场景文学蓝图：感知策略、意象预算、冲突走向等写作策略层决策（质量地板 v2 的第一环）。
- **触发**：场景运行管线自动（orchestrator）或 POST /api/v1/scenes/{id}/blueprint。
- **调用链**：`backend/src/novel_system/services/scene_blueprint.py:84`（SceneBlueprintService.generate，经 PromptBuilder）
- **输入组装**：PromptBuilder：chapter_goal / scene_card / 角色连续性 / 张力约束等分节 + task_prompt + schema 指令。
- **输出契约**：蓝图 payload，经 _validate_blueprint_payload 校验（字段缺失即拒）。产物作为 Scene Literary Blueprint 分节注入后续 neutral/style 生成。（解析/校验：`backend/src/novel_system/services/scene_blueprint.py:95`）
- **失败与降级**：离线走 OfflineSceneBlueprintClient 确定性桩；LLMNodeExecutionError 上抛。
- **优化注意**：蓝图质量直接放大到正文——把「反AI味」决策前置到这里（感知过滤器选择、冲突不许太干净、意象复用禁令），比在正文模板里堆规则更有效。

**system_prompt（原样发送）**

```text
You are a fiction planning editor.
Before prose generation, produce a compact scene readability proposal explaining why this scene is worth reading.
Stay original, concrete, and tied to the supplied chapter and scene intent.
```

**task_prompt（运行时在其后追加指令与上下文）**

```text
Build the scene readability proposal v2 from the supplied chapter goal, scene card, and writer brief.
Write string fields in Chinese when the source context is Chinese, while preserving English schema keys.
Output fixed fields only: visible_desire, forced_choice, price_paid, information_release, relationship_turn, image_anchor, ending_action, next_scene_pull, anti_summary_rule.
Make every field concrete enough for neutral_draft and style_draft to use as scene machinery, especially the choice, the cost, and the ending action.
```

**structured_schema（wire 层 + 降级时内联；字段名冻结）**

```json
{
  "additionalProperties": false,
  "properties": {
    "anti_summary_rule": {
      "type": "string"
    },
    "ending_action": {
      "type": "string"
    },
    "forced_choice": {
      "type": "string"
    },
    "image_anchor": {
      "type": "string"
    },
    "information_release": {
      "type": "string"
    },
    "next_scene_pull": {
      "type": "string"
    },
    "price_paid": {
      "type": "string"
    },
    "relationship_turn": {
      "type": "string"
    },
    "visible_desire": {
      "type": "string"
    }
  },
  "required": [
    "visible_desire",
    "forced_choice",
    "price_paid",
    "information_release",
    "relationship_turn",
    "image_anchor",
    "ending_action",
    "next_scene_pull",
    "anti_summary_rule"
  ],
  "type": "object"
}
```

### [B-02] chapter_story_architecture — 章级故事架构

- **状态**：活跃
- **优先级**：P0
- **节点**：`chapter_story_architecture`
- **模板**：`config/prompts.yaml` → `chapter_story_architecture`（version `2026-04-25.v1`，input_token_budget 2400）
- **路由（yaml 兜底，DB 优先）** `默认路由`：model=`gpt-5`，temperature=0.25，max_output_tokens=2200，response_format=`json_object`
- **用途**：近终稿规划：章级承诺-兑现结构、场景间的势能分配（写进后续生成的上下文分节）。
- **触发**：场景执行契约生成（POST /api/v1/scenes/{id}/execution-contract → NearFinalPlanningService）。
- **调用链**：`backend/src/novel_system/services/near_final.py:161`（_generate_chapter_architecture，经 PromptBuilder）
- **输入组装**：PromptBuilder：章/场景快照（不含既有架构）+ _planning_user_prompt 附加段。
- **输出契约**：架构 payload，经 _normalize_chapter_architecture_payload 归一。（解析/校验：`backend/src/novel_system/services/near_final.py:161`）
- **失败与降级**：离线 → _fallback_chapter_architecture_payload（skip_runner_when_offline）。
- **优化注意**：关注章内张力曲线的显式化（每场景的势能增减必须有数值/方向），供 tension_curve 规则层可核。

**system_prompt（原样发送）**

```text
You are a senior long-form fiction architect.
Before scene drafting, define the chapter-level promise, escalation, reveal/payoff plan, character shift, and ending question.
Stay concrete and preserve the supplied chapter and scene facts.
```

**task_prompt（运行时在其后追加指令与上下文）**

```text
Build a compact chapter story architecture from the supplied chapter goal, chapter writer brief, scene cards, and longform guidance.
Write string fields in Chinese when the source context is Chinese, while preserving English schema keys.
The architecture must help later scene prompts avoid isolated good scenes that fail chapter payoff.
```

**structured_schema（wire 层 + 降级时内联；字段名冻结）**

```json
{
  "additionalProperties": false,
  "properties": {
    "chapter_promise": {
      "type": "string"
    },
    "character_shift": {
      "type": "string"
    },
    "ending_question": {
      "type": "string"
    },
    "escalation_path": {
      "items": {
        "type": "string"
      },
      "type": "array"
    },
    "payoff_target": {
      "type": "string"
    },
    "reveal_plan": {
      "items": {
        "type": "string"
      },
      "type": "array"
    }
  },
  "required": [
    "chapter_promise",
    "escalation_path",
    "reveal_plan",
    "payoff_target",
    "character_shift",
    "ending_question"
  ],
  "type": "object"
}
```

### [B-03] character_pressure_blueprint — 角色压力蓝图

- **状态**：活跃
- **优先级**：P0
- **节点**：`character_pressure_blueprint`
- **模板**：`config/prompts.yaml` → `character_pressure_blueprint`（version `2026-04-25.v1`，input_token_budget 2400）
- **路由（yaml 兜底，DB 优先）** `默认路由`：model=`gpt-5`，temperature=0.25，max_output_tokens=1800，response_format=`json_object`
- **用途**：近终稿规划：本场景对每个到场角色施加的压力/代价/决策点（Character Pressure 分节的来源）。
- **触发**：同上（执行契约生成，include_chapter_architecture=True 后串行）。
- **调用链**：`backend/src/novel_system/services/near_final.py:218`（_generate_character_pressure，经 PromptBuilder）
- **输入组装**：PromptBuilder：含章架构在内的快照 + _planning_user_prompt。
- **输出契约**：压力蓝图 payload，_normalize_character_pressure_payload 归一。（解析/校验：`backend/src/novel_system/services/near_final.py:224`）
- **失败与降级**：离线 → _fallback_character_pressure_payload。
- **优化注意**：「冲突太干净」的第一道防线：要求每个角色的压力必须有不可白拿的代价与未消化的残留情绪。

**system_prompt（原样发送）**

```text
You are a severe character dramaturg.
Before prose generation, identify the character pressure that must become visible on the page without explanatory summary.
```

**task_prompt（运行时在其后追加指令与上下文）**

```text
Build one character pressure blueprint for the scene's point-of-view or primary decision-maker.
Write string fields in Chinese when the source context is Chinese, while preserving English schema keys.
Every field must be usable by drafting and near-final review: surface_goal, hidden_fear, wrong_belief, shame_point, avoidance_strategy, relationship_debt, and current_mask.
```

**structured_schema（wire 层 + 降级时内联；字段名冻结）**

```json
{
  "additionalProperties": false,
  "properties": {
    "avoidance_strategy": {
      "type": "string"
    },
    "current_mask": {
      "type": "string"
    },
    "hidden_fear": {
      "type": "string"
    },
    "relationship_debt": {
      "type": "string"
    },
    "shame_point": {
      "type": "string"
    },
    "surface_goal": {
      "type": "string"
    },
    "wrong_belief": {
      "type": "string"
    }
  },
  "required": [
    "surface_goal",
    "hidden_fear",
    "wrong_belief",
    "shame_point",
    "avoidance_strategy",
    "relationship_debt",
    "current_mask"
  ],
  "type": "object"
}
```

### [B-04] neutral_draft — 中性初稿

- **状态**：活跃
- **优先级**：P0
- **节点**：`neutral_draft`
- **模板**：`config/prompts.yaml` → `neutral_draft`（version `2026-04-25.v2`，input_token_budget 2600）
- **路由（yaml 兜底，DB 优先）** `默认路由`：model=`gpt-5`，temperature=0.6，max_output_tokens=6000，response_format=`json_object`
- **用途**：无风格化的场景正文初稿——把 spec（目标/冲突/挫败或反应/两难/决定）落成完整叙事，供风格层加工。
- **触发**：场景运行管线（POST /api/v1/scenes/{id}/run/jobs → Orchestrator.run_scene）。
- **调用链**：`backend/src/novel_system/services/scene_generation.py:223`（generate_neutral_draft，经 PromptBuilder）
- **输入组装**：PromptBuilder 全量上下文分节（chapter_goal/scene_card/scene_blueprint/character_pressure/POV voice/世界规则/前情记忆/伏笔/避免近期表达…）+ 语言锁 + 角色连续性指令 + schema 指令。
- **输出契约**：scene_text（+元信息），_extract_scene_text 解析 → NeutralGenerationResult；正文进 SceneDraft 行。（解析/校验：`backend/src/novel_system/services/scene_generation.py:223`）
- **失败与降级**：离线 OfflineNeutralClient；连续性预算超限 → LLMNodeContinuityError（建议拆场景）。
- **优化注意**：去AI味在此层管「叙事骨架不塌」：动作-反应节拍完整、信息经由压力而非旁白倾倒。风格留给 style 层，本模板应抑制修辞欲。

**system_prompt（原样发送）**

```text
You are drafting a neutral, continuity-safe web-novel scene.
Follow the supplied bundle facts exactly and preserve causal clarity.
```

**task_prompt（运行时在其后追加指令与上下文）**

```text
Write the next scene draft from the supplied bundle snapshot.
Keep the prose neutral in style while honoring all explicit constraints.
Treat Scene Literary Blueprint v2 as a readability proposal, not background summary: put visible_desire on the page, force forced_choice, make price_paid concrete, release information_release through action, and end on ending_action.
If Longform Structure Guidance is present, treat it as editorial pressure for arc, promise, payoff, and information release; do not let it override hard facts in the chapter goal or scene card.
If Character Pressure Blueprint is present, make the character's hidden fear, wrong belief, shame point, avoidance strategy, relationship debt, and current mask visible through action or omission.
If Chapter Story Architecture is present, obey its promise, escalation path, reveal plan, payoff target, character shift, and ending question.
Avoid model-voice shortcuts: no explanatory dialogue dump, no no-choice scene, no summary ending, and keep image anchors varied rather than repetitive.
Write prose in the same language as the chapter goal and scene card.
If the chapter goal or scene card contains Chinese text, scene_text must be Chinese prose; do not translate Chinese settings, beats, or required text into English.
```

**structured_schema（wire 层 + 降级时内联；字段名冻结）**

```json
{
  "additionalProperties": false,
  "properties": {
    "continuity_notes": {
      "items": {
        "type": "string"
      },
      "type": "array"
    },
    "scene_text": {
      "type": "string"
    }
  },
  "required": [
    "scene_text"
  ],
  "type": "object"
}
```

### [B-05] style_draft（节点 style_draft + style_patch；stylize 为路由别名）— 风格化生成/软补丁

- **状态**：活跃（注册表 template_name="stylize" 只是路由别名；实际提示词即本模板）
- **优先级**：P0
- **节点**：`style_draft`、`style_patch`
- **模板**：`config/prompts.yaml` → `style_draft`（version `2026-04-25.v2`，input_token_budget 2600）
- **路由（yaml 兜底，DB 优先）** `style_draft`：model=`gpt-5`，temperature=0.8，max_output_tokens=6000，response_format=`json_object`，frequency_penalty=0.3，presence_penalty=0.15
- **路由（yaml 兜底，DB 优先）** `style_patch`：model=`gpt-5`，temperature=0.8，max_output_tokens=6000，response_format=`json_object`，frequency_penalty=0.3，presence_penalty=0.15
- **用途**：把中性稿加工成风格化正文（Best-of-N 多候选）；soft_patch 分支按 QC 的 patch_brief 做定向修补；另有去模板化 pass 复用 style_patch 节点。
- **触发**：场景运行管线风格阶段；软 QC patch 分支；去模板化触发（反AI味 gate 命中时）。
- **调用链**：`backend/src/novel_system/services/scene_generation.py:835`（_run_style_generation 动态节点）；`backend/src/novel_system/services/scene_generation.py:958`（_run_de_template_pass 去模板化）
- **输入组装**：PromptBuilder(style_draft) + [STYLE_REFERENCE] 注入块（绑定 Profile 时，含反抄袭红线）+ 中性稿正文 + author_note 附加指令 + patch_brief（补丁分支）+ 发散化/风格强调前缀（低分散重试）。采样带 frequency_penalty 0.3 / presence_penalty 0.15（§7 反均值）。
- **输出契约**：scene_text；_extract_scene_text → StyleGenerationResult；候选进 Best-of-N 排序（adversarial_rank_score 规则盲评）。（解析/校验：`backend/src/novel_system/services/scene_generation.py:1024`）
- **失败与降级**：离线 OfflineStyleClient（patch_mode 区分）；失败记 AttemptTracker 后上抛原错误。
- **优化注意**：去AI味核心战场。对照 literary_quality 21 维中的高频失分项写硬约束：感知过滤器（每段落至少一处经由 POV 身体/情绪过滤的感知）、禁总结式收尾、禁「as you know」式对白倾倒、意象不许跨段复用、句式长短交替。注意语言锁与反抄袭红线是自动追加的，模板里不要重复。

**system_prompt（原样发送）**

```text
You are drafting a stylistically tuned web-novel scene from a structured Style Feature Contract.
Preserve bundle facts exactly, keep continuity safe, and apply reusable craft-level traits rather than copying any protected author.
```

**task_prompt（运行时在其后追加指令与上下文）**

```text
Rewrite the scene draft with stronger style adherence without changing factual continuity.
Rewrite the approved neutral draft without changing factual continuity.
Preserve the Scene Literary Blueprint v2 pressure: visible_desire, forced_choice, price_paid, information_release, relationship_turn, image_anchor, ending_action, and next_scene_pull must remain legible in prose.
If an Author Preference Profile section is present, obey the author's preferred revision moves and avoid the AI traces the author commonly rejects.
If Longform Structure Guidance is present, use it as structural pressure for arc, payoff, and release timing; do not let it override hard continuity or scene-card facts.
If Character Pressure Blueprint is present, preserve its hidden fear, wrong belief, shame point, avoidance strategy, relationship debt, and current mask as scene pressure rather than explanation.
If Chapter Story Architecture is present, make the rewritten scene serve the chapter promise, reveal plan, payoff target, character shift, and ending question.
Preserve the source draft language; do not translate the scene while styling it.
If the draft or scene card is Chinese, scene_text must remain Chinese prose.
Follow the Style Feature Contract dimension by dimension:
- rhythm: sentence beat, pause placement, paragraph endings.
- syntax: sentence length mix, clause shape, dialogue/narration texture.
- imagery: recurring sensory fields, tactile anchors, gesture logic.
- narrative_distance: POV closeness, interiority, exposition distance.
- emotion_curve: how pressure rises, turns, and resolves inside the scene.
- paragraph_density: block length, line-break frequency, compression level.
- dialogue_ratio: spoken line share and silence around speech.
Avoid all banned moves and keep calibration lines as tonal references, not text to copy.
```

**structured_schema（wire 层 + 降级时内联；字段名冻结）**

```json
{
  "additionalProperties": false,
  "properties": {
    "scene_text": {
      "type": "string"
    },
    "style_notes": {
      "items": {
        "type": "string"
      },
      "type": "array"
    }
  },
  "required": [
    "scene_text"
  ],
  "type": "object"
}
```

### [B-06] long_form_continuation — 长文续写

- **状态**：活跃
- **优先级**：P0
- **节点**：`long_form_continuation`
- **模板**：`config/prompts.yaml` → `long_form_continuation`（version `2026-05-31.v1`，input_token_budget 2600）
- **路由（yaml 兜底，DB 优先）** `默认路由`：model=`gpt-5`，profile=`quality_strong`，temperature=0.7，max_output_tokens=4000，response_format=`json_object`，refresh_every_chars=8000
- **用途**：长场景/长章的分段续写，每 8000 字符重新拉取 [STYLE_REFERENCE] 注入防风格漂移（refresh_every_chars=8000）。
- **触发**：场景运行管线长文分支（generate_long_form_continuation）。
- **调用链**：`backend/src/novel_system/services/scene_generation.py:693`（generate_long_form_continuation）
- **输入组装**：PromptBuilder(long_form_continuation)：前文尾部 + 上下文分节 + 语言锁；风格注入定期刷新。
- **输出契约**：scene_text 续段；_extract_scene_text。（解析/校验：`backend/src/novel_system/services/scene_generation.py:693`）
- **失败与降级**：同 style 路径（离线桩 / AttemptTracker）。
- **优化注意**：续写的病是「重启感」：开头重复设景、情绪归零。约束续段必须从前文最后一个未消化动作/情绪接力，禁重新介绍人物。

**system_prompt（原样发送）**

```text
You are continuing a long-form web-novel scene from an approved source draft and prior generated continuation.
Preserve continuity, factual safety, and reusable style pressure exactly.
```

**task_prompt（运行时在其后追加指令与上下文）**

```text
Continue the scene from the supplied source draft and continuation-so-far.
Do not restart the scene, summarize earlier beats, or repeat the last paragraph with minor wording changes.
Preserve character identity, POV distance, scene pressure, and style-reference guidance across the continuation.
If Longform Structure Guidance is present, treat it as pressure for arc, promise, payoff, and information release timing.
End this continuation chunk on live forward motion rather than explanation.
```

**structured_schema（wire 层 + 降级时内联；字段名冻结）**

```json
{
  "additionalProperties": false,
  "properties": {
    "continuation_notes": {
      "items": {
        "type": "string"
      },
      "type": "array"
    },
    "scene_text": {
      "type": "string"
    }
  },
  "required": [
    "scene_text"
  ],
  "type": "object"
}
```

### [B-07] scene_literary_rewrite — 场景文学化改写

- **状态**：活跃
- **优先级**：P0
- **节点**：`scene_literary_rewrite`
- **模板**：`config/prompts.yaml` → `scene_literary_rewrite`（version `2026-04-25.v1`，input_token_budget 3000）
- **路由（yaml 兜底，DB 优先）** `默认路由`：model=`gpt-5`，profile=`quality_strong`，temperature=0.55，max_output_tokens=6000，response_format=`json_object`
- **用途**：近终稿阶段的整场文学化重写（比 style_draft 更激进的质量拉升，quality_strong 档）。
- **触发**：场景运行管线 rewrite 分支（llm_step="scene_literary_rewrite" 时走专用模板）。
- **调用链**：`backend/src/novel_system/services/scene_generation.py:801`（_run_style_generation 模板切换）
- **输入组装**：同 style 路径（PromptBuilder + 风格注入 + 源稿正文）。
- **输出契约**：scene_text；_extract_scene_text。（解析/校验：`backend/src/novel_system/services/scene_generation.py:801`）
- **失败与降级**：同 style 路径。
- **优化注意**：与 style_draft 拉开定位差：本模板允许结构级手术（调句序、并段、删冗），但必须保护事实/伏笔/必含文本——把「可动什么/不可动什么」写成清单。

**system_prompt（原样发送）**

```text
You are rewriting a fiction scene toward near-final quality for a working author.
Preserve all hard facts, names, continuity constraints, and source language.
```

**task_prompt（运行时在其后追加指令与上下文）**

```text
Rewrite the supplied scene as a complete revised scene, not advice.
Prioritize character pressure, dialogue edge, information rhythm, prose freshness, image necessity, and ending drive.
If Character Pressure Blueprint is present, make hidden fear, wrong belief, shame point, avoidance strategy, relationship debt, and current mask visible through action, silence, and subtext.
If Chapter Story Architecture is present, serve the chapter promise, reveal plan, payoff target, character shift, and ending question.
Avoid model-voice shortcuts, explanatory dialogue dumps, no-choice scenes, summary endings, and repeated generic gestures.
Return Chinese prose when the source scene is Chinese.
```

**structured_schema（wire 层 + 降级时内联；字段名冻结）**

```json
{
  "additionalProperties": false,
  "properties": {
    "rewrite_notes": {
      "items": {
        "type": "string"
      },
      "type": "array"
    },
    "scene_text": {
      "type": "string"
    }
  },
  "required": [
    "scene_text"
  ],
  "type": "object"
}
```

### [B-08] scene_auto_rewrite — 场景自动改写（Python 内联提示词）

- **状态**：活跃（内联：不受 DB prompts 快照覆盖，注册表 template_name 指向不存在的 yaml 键）
- **优先级**：P0
- **节点**：`scene_auto_rewrite`
- **内联提示词**：`backend/src/novel_system/services/scene_quality.py`（不受 DB 快照覆盖）
- **路由（yaml 兜底，DB 优先）** `默认路由`：model=`gpt-5`，profile=`quality_strong`，temperature=0.55，max_output_tokens=5000，response_format=`json_object`
- **用途**：质量契约兜底改写：按诊断/门禁结果对场景做 full_scene 或局部分支改写，产出候选走人工确认。
- **触发**：POST /api/v1/scenes/{id}/auto-rewrite（api/routes/scenes.py → SceneAutoRewriteService.run）。
- **调用链**：`backend/src/novel_system/services/scene_quality.py:572`（_generate_llm_candidate（occurrence 1 是离线审计行））
- **输入组装**：user_prompt = canonical_json 快照（contract/source_text/diagnosis/gate_results/constraints——含 preserve_required_terms/forbidden_text）。
- **输出契约**：scene_text 必填（缺失 → SCENE_AUTO_REWRITE_EMPTY 502）；rewrite_notes 可选。（解析/校验：`backend/src/novel_system/services/scene_quality.py:593`）
- **失败与降级**：路由缺失/调用失败 → SCENE_AUTO_REWRITE_LLM_FAILED 409（引导配路由）；离线走确定性候选并落审计行。
- **优化注意**：system_prompt 只有一句话，信息量过低——是全系统最值得重写的内联提示词。改写目标、保护项、分支语义（full_scene vs 局部）都应进 system_prompt；改动要回写 scene_quality.py（无 yaml）。

**system_prompt（函数内联，_generate_llm_candidate）**

```text
You are a senior fiction revision model. Rewrite only within the supplied facts, preserve protected names and required evidence, and return JSON.
```

**structured_schema（代码内联；字段名冻结）**

```json
{
  "type": "object",
  "properties": {
    "scene_text": {
      "type": "string"
    },
    "rewrite_notes": {
      "type": "array",
      "items": {
        "type": "string"
      }
    }
  },
  "required": [
    "scene_text"
  ],
  "additionalProperties": true
}
```

> user_prompt 是 canonical_json 序列化的快照（键：scene_id / chapter_id / branch / contract(质量契约 payload) / source_text(原稿全文) / diagnosis / gate_results / constraints{preserve_facts, preserve_required_terms, forbidden_text, return_complete_scene_text}）。没有 yaml 模板——改提示词要直接改 scene_quality.py。

### [B-09] writer_passage_patch — 段落级修补

- **状态**：活跃
- **优先级**：P1
- **节点**：`writer_passage_patch`
- **模板**：`config/prompts.yaml` → `writer_passage_patch`（version `2026-04-25.v1`，input_token_budget 2400）
- **路由（yaml 兜底，DB 优先）** `默认路由`：model=`gpt-5`，temperature=0.45，max_output_tokens=2600，response_format=`json_object`
- **用途**：深评/写作间里对选中段落的定向修补（保持上下文咬合的局部重写）。
- **触发**：深评修补端点（api/routes/writer_deep_review.py → create_patch_candidate）。
- **调用链**：`backend/src/novel_system/services/writer_deep_review.py:522`（_run_passage_patch）
- **输入组装**：PromptBuilder(writer_passage_patch)：目标段落 + 前后文 + 修补指令。
- **输出契约**：修补后的段落文本 + 说明；服务内归一。（解析/校验：`backend/src/novel_system/services/writer_deep_review.py:522`）
- **失败与降级**：OfflineWriterDeepReviewClient 桩；错误上抛为 blocked。
- **优化注意**：最大风险是补丁与前后文脱榫：约束首尾句必须与邻段在时序/视点/语气上连续，禁引入新事实。

**system_prompt（原样发送）**

```text
You are preparing a local passage patch for a fiction author.
The patch is a candidate only: do not claim it has been applied, and do not rewrite unrelated text.
```

**task_prompt（运行时在其后追加指令与上下文）**

```text
Given the source passage, selected issue, evidence, and target dimensions, produce replacement options.
Return at least 2 and at most 3 distinct replacement options with different tones
(for example: shorter / sharper / subtler), so the author has a real choice.
Write in the source language. Preserve continuity, names, facts, and author intent.
Return concise patch records that the author can manually accept or reject.
```

**structured_schema（wire 层 + 降级时内联；字段名冻结）**

```json
{
  "additionalProperties": false,
  "properties": {
    "manual_only": {
      "type": "boolean"
    },
    "patches": {
      "items": {
        "additionalProperties": false,
        "properties": {
          "changed_dimensions": {
            "items": {
              "type": "string"
            },
            "type": "array"
          },
          "patch_type": {
            "type": "string"
          },
          "replacement_text": {
            "type": "string"
          },
          "source_excerpt": {
            "type": "string"
          },
          "target_text_ref": {
            "type": "string"
          },
          "why_it_helps": {
            "type": "string"
          }
        },
        "required": [
          "target_text_ref",
          "source_excerpt",
          "replacement_text",
          "patch_type",
          "changed_dimensions",
          "why_it_helps"
        ],
        "type": "object"
      },
      "maxItems": 3,
      "minItems": 2,
      "type": "array"
    },
    "rationale": {
      "type": "string"
    }
  },
  "required": [
    "patches",
    "rationale",
    "manual_only"
  ],
  "type": "object"
}
```

## §5 批次 C · 质量门与裁定（6 个单元）

硬/软 QC 闸门、近终稿验收、章级违约裁定与独立编辑评审。共同要求：保守、证据化、禁臆造；结构化输出的枚举字段（resolution_code / next_action）由运行时代码强制合并，属冻结契约。

### [C-01] hard_qc — 硬 QC 闸门

- **状态**：活跃
- **优先级**：P1
- **节点**：`hard_qc`
- **模板**：`config/prompts.yaml` → `hard_qc`（version `2026-04-14.v1`，input_token_budget 2200）
- **路由（yaml 兜底，DB 优先）** `默认路由`：model=`gpt-5`，temperature=0.2，max_output_tokens=2200，response_format=`json_object`
- **用途**：阻断级质量闸：事实/连续性/必含文本/禁词等硬约束违反检测，决定 pass/部分重写/全量重写/转人工。
- **触发**：场景运行管线 QC 阶段（HardQcEngine.evaluate）。
- **调用链**：`backend/src/novel_system/services/qc_engine.py:655`（HardQcEngine.evaluate，经 PromptBuilder）
- **输入组装**：PromptBuilder(hard_qc)：草稿 + 事实/约束/角色契约分节（hard_qc 任务型预算策略优先保事实上下文）+ QC 语言锁。
- **输出契约**：HardQCOutput（contracts/qc.py）Pydantic 校验；resolution_code / next_action 枚举由运行时对齐冻结（hard_pass/hard_fail_partial/hard_fail_full/hard_block_human；pass/partial_rewrite/full_rewrite/human_review_required）；rewrite_brief 为必填 string[]。（解析/校验：`backend/src/novel_system/services/qc_validator.py:33`）
- **失败与降级**：离线 OfflineHardQcClient；重试预算 hard_partial_max 2 / hard_full_max 1（models.yaml retry_budget）；确定性 gates 叠加在 LLM 结果之上。
- **优化注意**：保守性最重要：只报可证的违反、evidence 必须可定位；rewrite_brief 要「可执行」（指向段落+改法），它直接喂给重写分支。

**system_prompt（原样发送）**

```text
You are a hard continuity and requirements checker for scene drafts.
Fail any contradiction, missing hard constraint, or unsupported event.
```

**task_prompt（运行时在其后追加指令与上下文）**

```text
Audit the scene draft against the bundle snapshot and return only structured findings.
Use one legal outcome tuple only:
hard_pass / true / pass,
hard_fail_partial / false / partial_rewrite,
hard_fail_full / false / full_rewrite,
hard_block_human / false / human_review_required.
Always include rewrite_brief; use an empty array when the draft passes.
```

**structured_schema（wire 层 + 降级时内联；字段名冻结）**

```json
{
  "additionalProperties": false,
  "properties": {
    "issues": {
      "items": {
        "additionalProperties": false,
        "properties": {
          "issue_key": {
            "type": "string"
          },
          "message": {
            "type": "string"
          }
        },
        "required": [
          "issue_key",
          "message"
        ],
        "type": "object"
      },
      "type": "array"
    },
    "next_action": {
      "enum": [
        "pass",
        "partial_rewrite",
        "full_rewrite",
        "human_review_required"
      ],
      "type": "string"
    },
    "pass_flag": {
      "type": "boolean"
    },
    "resolution_code": {
      "enum": [
        "hard_pass",
        "hard_fail_partial",
        "hard_fail_full",
        "hard_block_human"
      ],
      "type": "string"
    },
    "rewrite_brief": {
      "items": {
        "type": "string"
      },
      "type": "array"
    }
  },
  "required": [
    "resolution_code",
    "pass_flag",
    "next_action",
    "issues",
    "rewrite_brief"
  ],
  "type": "object"
}
```

### [C-02] soft_qc — 软 QC 闸门（auto_critique 借道同一路由）

- **状态**：活跃
- **优先级**：P1
- **节点**：`soft_qc`
- **模板**：`config/prompts.yaml` → `soft_qc`（version `2026-04-25.v2`，input_token_budget 1800）
- **路由（yaml 兜底，DB 优先）** `默认路由`：model=`gpt-5-mini`，temperature=0.2，max_output_tokens=1800，response_format=`json_object`
- **用途**：风格/表达层质量评审：产出 patch 建议或放行（soft_pass/soft_patch/soft_waive/soft_block_human）。
- **触发**：场景运行管线 QC 阶段（SoftQcEngine.evaluate）。
- **调用链**：`backend/src/novel_system/services/qc_engine.py:1347`（SoftQcEngine.evaluate，经 PromptBuilder）
- **输入组装**：PromptBuilder(soft_qc)：风格草稿 + style_rule/banned_rule/校准行等分节（soft_qc allowlist 治理）+ QC 语言锁。
- **输出契约**：SoftQCOutput Pydantic 校验；枚举冻结同上；patch 建议进 style_patch 分支的 patch_brief。（解析/校验：`backend/src/novel_system/services/qc_validator.py:33`）
- **失败与降级**：离线 OfflineSoftQcClient；soft_patch_max 2；LLM 事件旗标仅 advisory。
- **优化注意**：patch 建议的粒度决定 style_patch 成败：每条 patch 指令应含「位置锚 + 病名 + 改法示例」。注意本路由还被 auto_critique_llm 借用——温度/模型改动会影响两个消费方。

**system_prompt（原样发送）**

```text
You are a soft quality-control reviewer for prose polish and Style Feature Contract adherence.
Focus on readability, cadence, emotional clarity, style-feature match, and whether the draft needs one controlled patch.
```

**task_prompt（运行时在其后追加指令与上下文）**

```text
Review the draft for polish opportunities and return only structured soft QC guidance.
Score style adherence from 0 to 1 using rhythm, syntax, imagery, narrative_distance, emotion_curve, paragraph_density, and dialogue_ratio.
Also flag literary risks without blocking finalization: model_voice, image_homogeneity, expository_dialogue, no_choice_scene, summary_ending, weak choice_pressure, and weak ending_drive.
If Longform Structure Guidance is present, check whether the draft meaningfully answers it while preserving scene-card facts.
If style drift is patchable, put precise instructions in rewrite_brief and style_deviations.patch_brief.
Use one legal outcome tuple only:
soft_pass / true / pass,
soft_patch / false / patch,
soft_waive / true / pass_with_notes,
soft_block_human / false / human_review_required.
```

**structured_schema（wire 层 + 降级时内联；字段名冻结）**

```json
{
  "additionalProperties": false,
  "properties": {
    "carry_forward_note": {
      "type": "boolean"
    },
    "carry_note_text": {
      "type": "string"
    },
    "issues": {
      "items": {
        "additionalProperties": false,
        "properties": {
          "issue_key": {
            "type": "string"
          },
          "message": {
            "type": "string"
          }
        },
        "required": [
          "issue_key",
          "message"
        ],
        "type": "object"
      },
      "type": "array"
    },
    "next_action": {
      "enum": [
        "pass",
        "patch",
        "pass_with_notes",
        "human_review_required"
      ],
      "type": "string"
    },
    "note_scope": {
      "type": "string"
    },
    "pass_flag": {
      "type": "boolean"
    },
    "resolution_code": {
      "enum": [
        "soft_pass",
        "soft_patch",
        "soft_waive",
        "soft_block_human"
      ],
      "type": "string"
    },
    "rewrite_brief": {
      "items": {
        "type": "string"
      },
      "type": "array"
    },
    "style_deviations": {
      "items": {
        "additionalProperties": false,
        "properties": {
          "dimension": {
            "type": "string"
          },
          "evidence": {
            "type": "string"
          },
          "patch_brief": {
            "type": "string"
          },
          "severity": {
            "type": "string"
          }
        },
        "required": [
          "dimension",
          "severity",
          "patch_brief"
        ],
        "type": "object"
      },
      "type": "array"
    },
    "style_dimensions": {
      "items": {
        "additionalProperties": false,
        "properties": {
          "evidence": {
            "type": "string"
          },
          "name": {
            "type": "string"
          },
          "score": {
            "type": "number"
          }
        },
        "required": [
          "name",
          "score",
          "evidence"
        ],
        "type": "object"
      },
      "type": "array"
    },
    "style_score": {
      "type": "number"
    }
  },
  "required": [
    "resolution_code",
    "pass_flag",
    "next_action",
    "issues",
    "rewrite_brief"
  ],
  "type": "object"
}
```

### [C-03] near_final_acceptance_review — 场景近终稿验收

- **状态**：活跃
- **优先级**：P1
- **节点**：`near_final_acceptance_review`
- **模板**：`config/prompts.yaml` → `near_final_acceptance_review`（version `2026-04-25.v1`，input_token_budget 2600）
- **路由（yaml 兜底，DB 优先）** `默认路由`：model=`gpt-5`，temperature=0.15，max_output_tokens=2600，response_format=`json_object`
- **用途**：场景级近终稿验收评审：对照执行契约/架构工件做放行判断。
- **触发**：近终稿管线（NearFinalAcceptanceService.evaluate_scene）。
- **调用链**：`backend/src/novel_system/services/near_final.py:460`（evaluate_scene，经 PromptBuilder）
- **输入组装**：PromptBuilder：终稿 + 契约/架构分节。
- **输出契约**：验收 payload（发现项+判定）；服务内归一。（解析/校验：`backend/src/novel_system/services/near_final.py:460`）
- **失败与降级**：离线桩 / 上抛。
- **优化注意**：与 hard_qc 分工：这里查「承诺兑现」而非硬事实。防止它退化成第二个 hard_qc——判据应围绕契约条款逐条对账。

**system_prompt（原样发送）**

```text
You are a near-final acceptance editor for long-form Chinese fiction.
Decide whether a scene is close enough for author line-editing; do not mark weak drafts as ready.
```

**task_prompt（运行时在其后追加指令与上下文）**

```text
Review the supplied scene for near_final_acceptance_v1.
Write Chinese string fields while preserving English schema keys.
A ready scene must have story necessity, character pressure, forced choice pressure, dialogue edge, information release, prose freshness, ending drive, continuity, author voice match, low model_voice_risk, and reference safety.
Do not pass scenes that rely on abstract summary, explanatory cause-and-effect, no-choice motion, generic "she knew" clarity, or soft atmospheric ending instead of a hard next-scene action.
Use failure_class only from: fact_blocker, scene_structure_failure, character_flatness, prose_model_voice, ending_weakness, chapter_payoff_gap, reference_safety.
If the scene is ready, near_final_status must be near_final_ready and pass_flag true. Otherwise near_final_status must be revision_required and pass_flag false.
```

**structured_schema（wire 层 + 降级时内联；字段名冻结）**

```json
{
  "additionalProperties": false,
  "properties": {
    "failure_class": {
      "type": "string"
    },
    "findings": {
      "items": {
        "type": "object"
      },
      "type": "array"
    },
    "near_final_status": {
      "enum": [
        "near_final_ready",
        "revision_required",
        "human_review_required"
      ],
      "type": "string"
    },
    "overall_score": {
      "type": "number"
    },
    "pass_flag": {
      "type": "boolean"
    },
    "requires_human_review": {
      "type": "boolean"
    },
    "revision_brief": {
      "items": {
        "type": "object"
      },
      "type": "array"
    },
    "scores": {
      "type": "object"
    }
  },
  "required": [
    "near_final_status",
    "pass_flag",
    "overall_score",
    "scores",
    "findings",
    "revision_brief",
    "failure_class",
    "requires_human_review"
  ],
  "type": "object"
}
```

### [C-04] chapter_near_final_review — 章级近终稿评审

- **状态**：活跃
- **优先级**：P1
- **节点**：`chapter_near_final_review`
- **模板**：`config/prompts.yaml` → `chapter_near_final_review`（version `2026-04-25.v1`，input_token_budget 3200）
- **路由（yaml 兜底，DB 优先）** `默认路由`：model=`gpt-5`，temperature=0.15，max_output_tokens=3200，response_format=`json_object`
- **用途**：章级整体验收：场景间衔接、章承诺兑现、节奏塌陷检查。
- **触发**：章运行管线（NearFinalAcceptanceService.evaluate_chapter）。
- **调用链**：`backend/src/novel_system/services/near_final.py:531`（evaluate_chapter）
- **输入组装**：PromptBuilder：章内各场景终稿 + 章目标/记忆分节（chapter_review 预算策略）。
- **输出契约**：章级评审 payload；服务内归一。（解析/校验：`backend/src/novel_system/services/near_final.py:531`）
- **失败与降级**：离线桩 / 上抛。
- **优化注意**：章长导致输入截断风险最高的评审节点——指令应要求「先列场景清单再逐场衔接判定」，弱模型才不会只评开头。

**system_prompt（原样发送）**

```text
You are a near-final acceptance editor for chapter-level long-form fiction.
A chapter can fail even when individual scenes are readable if promise, escalation, payoff, or ending drive are weak.
```

**task_prompt（运行时在其后追加指令与上下文）**

```text
Review the supplied chapter aggregate for chapter-level near-final readiness.
Write Chinese string fields while preserving English schema keys.
Use failure_class only from: chapter_payoff_gap, scene_structure_failure, character_flatness, prose_model_voice, ending_weakness, fact_blocker, reference_safety.
```

**structured_schema（wire 层 + 降级时内联；字段名冻结）**

```json
{
  "additionalProperties": false,
  "properties": {
    "failure_class": {
      "type": "string"
    },
    "findings": {
      "items": {
        "type": "object"
      },
      "type": "array"
    },
    "near_final_status": {
      "enum": [
        "near_final_ready",
        "revision_required",
        "human_review_required"
      ],
      "type": "string"
    },
    "overall_score": {
      "type": "number"
    },
    "pass_flag": {
      "type": "boolean"
    },
    "requires_human_review": {
      "type": "boolean"
    },
    "revision_brief": {
      "items": {
        "type": "object"
      },
      "type": "array"
    },
    "scores": {
      "type": "object"
    }
  },
  "required": [
    "near_final_status",
    "pass_flag",
    "overall_score",
    "scores",
    "findings",
    "revision_brief",
    "failure_class",
    "requires_human_review"
  ],
  "type": "object"
}
```

### [C-05] chapter_audit_adjudicate — 章级违约裁定

- **状态**：活跃
- **优先级**：P1
- **节点**：`chapter_audit_adjudicate`
- **模板**：`config/prompts.yaml` → `chapter_audit_adjudicate`（version `2026-06-25.v1`，input_token_budget 3600）
- **路由（yaml 兜底，DB 优先）** `默认路由`：model=`gpt-5`，profile=`quality_strong`，temperature=0.1，max_output_tokens=2400，response_format=`json_object`
- **用途**：长篇塔：判定章草稿是否违反交接契约条款/锚点事实——只判违约，证据句必须逐字摘自 chapter_prose。
- **触发**：POST /api/v1/longform-tower/…/adjudicate（LongformTowerService.adjudicate_draft）。
- **调用链**：`backend/src/novel_system/services/longform_tower.py:680`（_adjudicate_violations）
- **输入组装**：task_prompt + JSON payload（chapter_prose、编号契约条款、anchor_hits/anchor_misses）。
- **输出契约**：violations 数组（clause_ref/kind/severity/text/evidence_sentence/at/suggested_fix；kind 枚举 drift/stall/deflation/causal_break/unplanted_reveal/unfair_clue/overdue/arc）。（解析/校验：`backend/src/novel_system/services/longform_tower.py:680`）
- **失败与降级**：LLMNodeError → 服务降级处理。
- **优化注意**：「宁缺毋滥」已写在提示词里，弱模型上反而会漏报——可加「先对每条条款给 hit/miss 草表再产 violations」的中间步骤指令提高召回。

**system_prompt（原样发送）**

```text
You are a continuity audit editor for a Chinese web novel. You judge ONLY whether the
chapter draft VIOLATES the handoff-contract constraints (and pinned story anchors).
A violation means the prose contradicts a constraint, omits a mandated element, lets a
promised beat deflate/stall, or drifts from a pinned fact. Never invent facts that are
not present in chapter_prose. Every violation MUST include evidence_sentence copied
verbatim from chapter_prose. If nothing clearly violates a constraint, return an empty
violations list — never manufacture issues to seem useful.
```

**task_prompt（运行时在其后追加指令与上下文）**

```text
Compare chapter_prose against each numbered constraint and the anchor_hits / anchor_misses.
Return violations only. For each violation provide:
clause_ref (which constraint index or anchor subject it breaks),
kind (one of: drift, stall, deflation, causal_break, unplanted_reveal, unfair_clue, overdue, arc),
severity (warn | block; use block only for a hard contradiction of a pinned fact or a mandated beat),
text (one concise Chinese sentence naming the violation),
evidence_sentence (a sentence copied verbatim from chapter_prose proving it),
at (scene title or location if identifiable, else empty),
suggested_fix (one concrete Chinese revision direction).
Be conservative and strictly evidence-bound.
```

**structured_schema（wire 层 + 降级时内联；字段名冻结）**

```json
{
  "additionalProperties": false,
  "properties": {
    "violations": {
      "items": {
        "additionalProperties": true,
        "type": "object"
      },
      "type": "array"
    }
  },
  "required": [
    "violations"
  ],
  "type": "object"
}
```

### [C-06] auto_critique_llm — 独立 LLM 编辑评审（Python 内联，借 soft_qc 路由）

- **状态**：活跃·可选（NOVEL_SYSTEM_LLM_AUTO_CRITIQUE_ENABLED=true 时启用；路由别名 → soft_qc）
- **优先级**：P1
- **run_task 任务名**：`auto_critique_llm`
- **内联提示词**：`backend/src/novel_system/services/auto_critique.py`（不受 DB 快照覆盖）
- **路由（yaml 兜底，DB 优先）** `默认路由`：（models.yaml 无此路由）
- **用途**：§8 Reflexion 式冷读编辑：Best-of-N 之后、软 QC 之前的独立语义评审，6 维度出改写指令。
- **触发**：场景运行管线（orchestrator 接线 llm_auto_critique；opt-in）。
- **调用链**：`backend/src/novel_system/services/auto_critique.py:306`（llm_auto_critique → run_task）
- **输入组装**：CRITIC_TASK_PROMPT_TEMPLATE.format(scene_context_block, text)——场景目标/张力目标/角色简报 + 正文。
- **输出契约**：{should_rewrite, issues[{dimension, directive, evidence}]}；dimension 白名单 6 值，directive ≤80 词；_parse_llm_response 手工解析。（解析/校验：`backend/src/novel_system/services/auto_critique.py:314`）
- **失败与降级**：任何异常 → 仅返回规则评审结果（永不阻塞）。
- **优化注意**：与规则评审按 dimension 去重合并——directive 措辞要与规则产出风格一致（[LLM·dim] 前缀已由代码加）。改动回写 auto_critique.py 模块常量。

**system_prompt（模块常量）**（`auto_critique.CRITIC_SYSTEM_PROMPT`）

```text
You are an independent fiction editor.  Your role is to perform a semantic
critique of a scene draft.  You are NOT the writer — you are a cold reader
who checks whether the scene actually achieves its dramatic goals on the page.

Your critique dimensions (check each one):

1. **Character consistency** — Does any character act in a way that
   contradicts their established personality, knowledge, or emotional state?
   Flag specific lines where the character seems to break voice.

2. **Earned emotion** — Is every emotional beat set up by prior action,
   pressure, or revealed information?  Flag any emotion that appears without
   a visible cause or that escalates faster than the scene has earned.

3. **Conflict credibility** — Does the central conflict of the scene resolve
   too easily, without the character paying a real cost?  A conflict that
   evaporates, gets talked away, or is solved by coincidence is a problem.

4. **Information dumping** — Is exposition delivered through dialogue ("as
   you know" patterns), internal monologue dumps, or narrator asides that
   stop the scene?  The reader should learn facts through pressure, not
   lecture.

5. **Show vs. tell** — Does the draft describe an emotional state
   ("she felt angry") instead of rendering it through action, body
   language, dialogue subtext, or environmental reaction?

6. **Pacing** — Given the scene's tension target, is the pacing
   appropriate?  A high-tension scene that lingers on atmospheric
   description is too slow; a quiet aftermath scene that rushes through
   reflection is too fast.

Respond in JSON with this exact schema:

{
  "should_rewrite": true/false,
  "issues": [
    {
      "dimension": "<one of: character_consistency | earned_emotion | conflict_credibility | information_dumping | show_vs_tell | pacing>",
      "directive": "<specific rewrite instruction for the writer>",
      "evidence": "<quote or paraphrase of the problematic passage>"
    }
  ]
}

Rules:
- Only report genuine problems.  Do not pad the list.
- If the scene is clean, return {"should_rewrite": false, "issues": []}.
- Keep each directive actionable and under 80 words.
- Quote or closely paraphrase the offending text in "evidence".
- Do NOT suggest style preferences — only flag craft failures.
```

**task_prompt 模板（{scene_context_block} / {text} 占位符必须保留）**（`auto_critique.CRITIC_TASK_PROMPT_TEMPLATE`）

```text
## Scene context

{scene_context_block}

## Scene text to critique

{text}
```

> §8 Reflexion 式独立编辑：规则评审之上叠加 LLM 冷读评审，6 个固定维度（character_consistency / earned_emotion / conflict_credibility / information_dumping / show_vs_tell / pacing——维度枚举被 _LLM_CRITIC_DIMENSIONS 白名单校验，越界归入 llm_general）。

## §6 批次 D · 风格参考子系统（12 个模板，弱模型鲁棒性主战场）

参考书风格引擎：段落分类 → 四层十六维抽取 → 证据补抽 → Profile 聚合 → 预览/验证。全部经 `style_reference/_llm_helper.call_llm_node`（user_prompt = task_prompt + "\n\n" + JSON payload；超时保底 120s）或分段分类器直连。已知痛点：中档中转模型上「抽取产出薄」（同 payload 可能返回 0 findings）——本批优化以提高产出饱满度与结构化输出稳定性为先。

### [D-01] style_ref_paragraph_classify_anchor — 段落分类（锚定集，强模型）

- **状态**：活跃
- **优先级**：P0
- **节点**：`style_ref_paragraph_classify_anchor`
- **模板**：`config/prompts.yaml` → `style_ref_paragraph_classify_anchor`（version `2026-05-23.v1`，input_token_budget 2400）
- **路由（yaml 兜底，DB 优先）** `默认路由`：model=`gpt-5`，temperature=0.1，max_output_tokens=2000，response_format=`json_object`
- **用途**：参考书段落 8 类分型的锚定集标注：抽样段落用强模型分类，与快模型比对一致率（≥0.85 才放行快模型批量，否则全书强模型）。
- **触发**：参考书导入/重分类（IngestService → classify_paragraphs → classify_with_llm）。
- **调用链**：`backend/src/novel_system/services/style_reference/segmentation/llm.py:201`（_classify_via_node（NODE_ANCHOR/NODE_BULK 共用））
- **输入组装**：task_prompt 的 {paragraphs} 占位符替换为 JSON（paragraph_index + 每段截 600 字），无占位符则追加；按 BATCH_SIZE 分批。
- **输出契约**：classifications[{paragraph_type, confidence(high/medium/low)}]；数量与批不符时补 narration/截断；confidence 映射 0.9/0.6/0.3。（解析/校验：`backend/src/novel_system/services/style_reference/segmentation/llm.py:232`）
- **失败与降级**：SegmentationLLMError → 整体回退启发式分类（记录 fallback_reason）。
- **优化注意**：8 类边界判例（对白夹叙、诗句、书信体等）要给例；要求逐段输出、禁跳段——弱模型漏段是补 narration 的主因，直接伤后续抽样质量。

**system_prompt（原样发送）**

```text
你是中文叙事段落分类专家。给定一批段落,逐段判断其类型,从 8 类中严格选择一个:
dialogue / narration / psychology / description_env / description_char / action / transition / flashback。
判断原则见 task_prompt。本任务是锚定集的强模型分类,作为后续快模型校准的基准。
```

**task_prompt（运行时在其后追加指令与上下文）**

```text
8 类定义:
  1. dialogue          含明确引号或"……说""……道"
  2. narration         全知视角推进剧情的散文体段落
  3. psychology        内心活动、回忆、内省(典型词:想着/觉得/暗忖/恍惚)
  4. description_env   刻画场所、天气、自然或物件
  5. description_char  刻画外貌、衣着、神态
  6. action            连续动作动词
  7. transition        场景切换/时间跳跃句(通常短)
  8. flashback         对过去事件的追述(典型词:记得/那年/从前)
规则:一段只归一类,多种特征以主导(>50%)为准;含直接引语优先 dialogue;短段(<30 字)且无对话/心理标识默认 transition。
仅看当前段本身,不考虑上下文。
输出 JSON: { "classifications": [ {"paragraph_index": int, "paragraph_type": str, "confidence": "high"|"medium"|"low"}, ... ] }
```

**structured_schema（wire 层 + 降级时内联；字段名冻结）**

```json
{
  "additionalProperties": false,
  "properties": {
    "classifications": {
      "items": {
        "additionalProperties": false,
        "properties": {
          "confidence": {
            "enum": [
              "high",
              "medium",
              "low"
            ],
            "type": "string"
          },
          "paragraph_index": {
            "type": "integer"
          },
          "paragraph_type": {
            "enum": [
              "dialogue",
              "narration",
              "psychology",
              "description_env",
              "description_char",
              "action",
              "transition",
              "flashback"
            ],
            "type": "string"
          }
        },
        "required": [
          "paragraph_index",
          "paragraph_type",
          "confidence"
        ],
        "type": "object"
      },
      "type": "array"
    }
  },
  "required": [
    "classifications"
  ],
  "type": "object"
}
```

### [D-02] style_ref_paragraph_classify_bulk — 段落分类（批量，快模型）

- **状态**：活跃
- **优先级**：P0
- **节点**：`style_ref_paragraph_classify_bulk`
- **模板**：`config/prompts.yaml` → `style_ref_paragraph_classify_bulk`（version `2026-05-23.v1`，input_token_budget 2400）
- **路由（yaml 兜底，DB 优先）** `默认路由`：model=`gpt-5-mini`，temperature=0.1，max_output_tokens=2000，response_format=`json_object`
- **用途**：锚定集校准通过后，余下段落的快模型批量分类。
- **触发**：同上（校准通过分支）。
- **调用链**：`backend/src/novel_system/services/style_reference/segmentation/llm.py:201`（同一出口，node=NODE_BULK）
- **输入组装**：同 anchor（{paragraphs} JSON 批量）。
- **输出契约**：同 anchor。（解析/校验：`backend/src/novel_system/services/style_reference/segmentation/llm.py:232`）
- **失败与降级**：同 anchor（回退启发式）。
- **优化注意**：该模板极简（bulk 版）——与 anchor 版保持判据一致是硬要求，否则一致率校准失真；优化时两模板同改同测。

**system_prompt（原样发送）**

```text
你是中文叙事段落分类专家。给定一批段落,逐段判断其类型,从 8 类中严格选择一个:
dialogue / narration / psychology / description_env / description_char / action / transition / flashback。
本任务是 bulk 路径的快模型分类,在锚定集 agreement ≥ 0.85 时启用。
```

**task_prompt（运行时在其后追加指令与上下文）**

```text
8 类定义与判断原则同 style_ref_paragraph_classify_anchor。
输出 JSON: { "classifications": [ {"paragraph_index": int, "paragraph_type": str, "confidence": "high"|"medium"|"low"}, ... ] }
```

**structured_schema（wire 层 + 降级时内联；字段名冻结）**

```json
{
  "additionalProperties": false,
  "properties": {
    "classifications": {
      "items": {
        "additionalProperties": false,
        "properties": {
          "confidence": {
            "enum": [
              "high",
              "medium",
              "low"
            ],
            "type": "string"
          },
          "paragraph_index": {
            "type": "integer"
          },
          "paragraph_type": {
            "enum": [
              "dialogue",
              "narration",
              "psychology",
              "description_env",
              "description_char",
              "action",
              "transition",
              "flashback"
            ],
            "type": "string"
          }
        },
        "required": [
          "paragraph_index",
          "paragraph_type",
          "confidence"
        ],
        "type": "object"
      },
      "type": "array"
    }
  },
  "required": [
    "classifications"
  ],
  "type": "object"
}
```

### [D-03] style_ref_extract_language — 语言层风格抽取（4 sub_dim）

- **状态**：活跃
- **优先级**：P0
- **节点**：`style_ref_extract_language`
- **模板**：`config/prompts.yaml` → `style_ref_extract_language`（version `2026-05-23.v1`，input_token_budget 3000）
- **路由（yaml 兜底，DB 优先）** `默认路由`：model=`gpt-5`，temperature=0.15，max_output_tokens=3200，response_format=`json_object`，timeout_seconds=180
- **用途**：语言层（句法节奏/词汇质感/修辞/对白语言）的风格发现抽取：每条 finding 须 ≥2 证据 span、禁模糊形容词。
- **触发**：抽取 run（POST /api/v2/style-reference/…/extract → run_orchestrator 调度四层）。
- **调用链**：`backend/src/novel_system/services/style_reference/extractors/base.py:506`（BaseExtractor._call_llm（extract_node_id=本节点））
- **输入组装**：task_prompt + JSON payload：sub_dim 定义 + 按段落类型定向抽样的原文段落（20 段级）+ 观察数/证据数指标（config/style_reference/extraction.yaml）。按 sub_dim 逐项调用、逐项 checkpoint 提交。
- **输出契约**：findings（observation 或 forbidden_pattern，finding_kind 区分）：statement 禁 banned_adjectives.yaml 词表、evidence ≥2 且 span 必须能在原文定位（Pydantic + span 校验）。（解析/校验：`backend/src/novel_system/services/style_reference/extractors/base.py:506`）
- **失败与降级**：两级重试：先 style_ref_supplement_evidence 定向补证，仍不达标整 sub_dim 重抽；最终失败记 _ExtractLLMError、该 sub_dim 缺失。
- **优化注意**：弱模型「产出薄」重灾区（deepseek-v4-flash 同 payload 可能 0 findings）。优化抓手：给最少 findings 数硬指标、每 finding 的字段填写范例（好/坏对照）、把「禁模糊形容词」具象成替换示范；statement 要写成可执行的写作规则而非鉴赏评语。

**system_prompt（原样发送）**

```text
你是中文叙事风格抽取专家。给定一个 sub_dimension(如 language.rhetoric)
与一批段落,产出该 sub_dimension 下的:
  - 0-8 条 observations(正向特征)
  - 0-3 条 forbidden_patterns(反向禁忌)
下列硬指标已对全文计算完毕,你提取的 observation 必须与之一致;
若你的描述与硬指标矛盾,以硬指标为准重新组织语言。
约束:
- 每条 observation / forbidden_pattern 必须 ≥ 2 evidence;每条 evidence 引用
  paragraph_id + span + 原文 quote(quote 必须是段落原句,不允许改写)
- 严禁使用空泛形容词(如"文笔优美""画面感强""叙事流畅"等),要用具体、可
  被验证的写作机制描述
- forbidden_pattern 描述作者明确不会用的写作模式(反向写作习惯);evidence 可以是
  paragraph_quote / author_avoidance(统计反推)/ counter_example(LLM 合成反例)
```

**task_prompt（运行时在其后追加指令与上下文）**

```text
输入 payload 含 sub_dimension / metrics_anchor / paragraphs。
请按 schema 输出 observations 与 forbidden_patterns。
若你不确定某条 observation 是否成立(evidence 不足或不典型),请不要输出。
宁可输出更少的高质量条目,也不要凑数。
```

**structured_schema（wire 层 + 降级时内联；字段名冻结）**

```json
{
  "additionalProperties": false,
  "properties": {
    "forbidden_patterns": {
      "items": {
        "additionalProperties": false,
        "properties": {
          "confidence": {
            "enum": [
              "high",
              "medium",
              "low"
            ],
            "type": "string"
          },
          "evidence": {
            "items": {
              "additionalProperties": false,
              "properties": {
                "anchor_kind": {
                  "enum": [
                    "paragraph_quote",
                    "author_avoidance",
                    "counter_example"
                  ],
                  "type": "string"
                },
                "illustrates_dims": {
                  "items": {
                    "type": "string"
                  },
                  "type": "array"
                },
                "is_synthetic": {
                  "type": "integer"
                },
                "note": {
                  "type": "string"
                },
                "paragraph_id": {
                  "type": "string"
                },
                "quote": {
                  "type": "string"
                },
                "span": {
                  "items": {
                    "type": "integer"
                  },
                  "maxItems": 2,
                  "minItems": 2,
                  "type": "array"
                }
              },
              "required": [
                "quote"
              ],
              "type": "object"
            },
            "minItems": 2,
            "type": "array"
          },
          "finding_kind": {
            "enum": [
              "forbidden_pattern"
            ],
            "type": "string"
          },
          "statement": {
            "type": "string"
          },
          "sub_dimension": {
            "type": "string"
          }
        },
        "required": [
          "statement",
          "finding_kind",
          "evidence",
          "sub_dimension"
        ],
        "type": "object"
      },
      "maxItems": 3,
      "type": "array"
    },
    "observations": {
      "items": {
        "additionalProperties": false,
        "properties": {
          "confidence": {
            "enum": [
              "high",
              "medium",
              "low"
            ],
            "type": "string"
          },
          "evidence": {
            "items": {
              "additionalProperties": false,
              "properties": {
                "anchor_kind": {
                  "enum": [
                    "paragraph_quote",
                    "author_avoidance",
                    "counter_example"
                  ],
                  "type": "string"
                },
                "illustrates_dims": {
                  "items": {
                    "type": "string"
                  },
                  "type": "array"
                },
                "is_synthetic": {
                  "type": "integer"
                },
                "note": {
                  "type": "string"
                },
                "paragraph_id": {
                  "type": "string"
                },
                "quote": {
                  "type": "string"
                },
                "span": {
                  "items": {
                    "type": "integer"
                  },
                  "maxItems": 2,
                  "minItems": 2,
                  "type": "array"
                }
              },
              "required": [
                "quote"
              ],
              "type": "object"
            },
            "minItems": 2,
            "type": "array"
          },
          "finding_kind": {
            "enum": [
              "observation"
            ],
            "type": "string"
          },
          "statement": {
            "type": "string"
          },
          "sub_dimension": {
            "type": "string"
          }
        },
        "required": [
          "statement",
          "finding_kind",
          "evidence",
          "sub_dimension"
        ],
        "type": "object"
      },
      "maxItems": 8,
      "type": "array"
    }
  },
  "required": [
    "observations",
    "forbidden_patterns"
  ],
  "type": "object"
}
```

### [D-04] style_ref_extract_narrative — 叙事层风格抽取（4 sub_dim）

- **状态**：活跃
- **优先级**：P0
- **节点**：`style_ref_extract_narrative`
- **模板**：`config/prompts.yaml` → `style_ref_extract_narrative`（version `2026-05-23.v1`，input_token_budget 3000）
- **路由（yaml 兜底，DB 优先）** `默认路由`：model=`gpt-5`，temperature=0.15，max_output_tokens=3200，response_format=`json_object`，timeout_seconds=180
- **用途**：叙事层（视点/时序/叙述距离/信息释放）抽取，机制同语言层。
- **触发**：同上。
- **调用链**：`backend/src/novel_system/services/style_reference/extractors/base.py:506`（extract_node_id=本节点）
- **输入组装**：同语言层（sub_dim 定义不同）。
- **输出契约**：同语言层。（解析/校验：`backend/src/novel_system/services/style_reference/extractors/base.py:506`）
- **失败与降级**：同语言层。
- **优化注意**：叙事层最抽象、最易产「万金油」结论——要求每条 finding 绑定具体叙事决策点（何处切视点/何处压缩时间），并给反例。

**system_prompt（原样发送）**

```text
你是中文叙事风格抽取专家(叙事层)。给定一个 sub_dimension(如
narrative.pacing)与一批段落,产出该 sub_dimension 下的 0-8 条
observations 与 0-3 条 forbidden_patterns。
约束与 style_ref_extract_language 一致;尤其注意叙事层关心视角(perspective)、
节奏(pacing)、时间处理(time_handling)、信息密度(information_density)。
```

**task_prompt（运行时在其后追加指令与上下文）**

```text
输入 payload 含 sub_dimension / metrics_anchor / paragraphs。
请按 schema 输出 observations 与 forbidden_patterns。
宁可输出更少的高质量条目,也不要凑数。
```

**structured_schema（wire 层 + 降级时内联；字段名冻结）**

```json
{
  "additionalProperties": false,
  "properties": {
    "forbidden_patterns": {
      "items": {
        "additionalProperties": false,
        "properties": {
          "confidence": {
            "enum": [
              "high",
              "medium",
              "low"
            ],
            "type": "string"
          },
          "evidence": {
            "items": {
              "additionalProperties": false,
              "properties": {
                "anchor_kind": {
                  "enum": [
                    "paragraph_quote",
                    "author_avoidance",
                    "counter_example"
                  ],
                  "type": "string"
                },
                "illustrates_dims": {
                  "items": {
                    "type": "string"
                  },
                  "type": "array"
                },
                "is_synthetic": {
                  "type": "integer"
                },
                "note": {
                  "type": "string"
                },
                "paragraph_id": {
                  "type": "string"
                },
                "quote": {
                  "type": "string"
                },
                "span": {
                  "items": {
                    "type": "integer"
                  },
                  "maxItems": 2,
                  "minItems": 2,
                  "type": "array"
                }
              },
              "required": [
                "quote"
              ],
              "type": "object"
            },
            "minItems": 2,
            "type": "array"
          },
          "finding_kind": {
            "enum": [
              "forbidden_pattern"
            ],
            "type": "string"
          },
          "statement": {
            "type": "string"
          },
          "sub_dimension": {
            "type": "string"
          }
        },
        "required": [
          "statement",
          "finding_kind",
          "evidence",
          "sub_dimension"
        ],
        "type": "object"
      },
      "maxItems": 3,
      "type": "array"
    },
    "observations": {
      "items": {
        "additionalProperties": false,
        "properties": {
          "confidence": {
            "enum": [
              "high",
              "medium",
              "low"
            ],
            "type": "string"
          },
          "evidence": {
            "items": {
              "additionalProperties": false,
              "properties": {
                "anchor_kind": {
                  "enum": [
                    "paragraph_quote",
                    "author_avoidance",
                    "counter_example"
                  ],
                  "type": "string"
                },
                "illustrates_dims": {
                  "items": {
                    "type": "string"
                  },
                  "type": "array"
                },
                "is_synthetic": {
                  "type": "integer"
                },
                "note": {
                  "type": "string"
                },
                "paragraph_id": {
                  "type": "string"
                },
                "quote": {
                  "type": "string"
                },
                "span": {
                  "items": {
                    "type": "integer"
                  },
                  "maxItems": 2,
                  "minItems": 2,
                  "type": "array"
                }
              },
              "required": [
                "quote"
              ],
              "type": "object"
            },
            "minItems": 2,
            "type": "array"
          },
          "finding_kind": {
            "enum": [
              "observation"
            ],
            "type": "string"
          },
          "statement": {
            "type": "string"
          },
          "sub_dimension": {
            "type": "string"
          }
        },
        "required": [
          "statement",
          "finding_kind",
          "evidence",
          "sub_dimension"
        ],
        "type": "object"
      },
      "maxItems": 8,
      "type": "array"
    }
  },
  "required": [
    "observations",
    "forbidden_patterns"
  ],
  "type": "object"
}
```

### [D-05] style_ref_extract_scene — 场景层风格抽取（4 sub_dim）

- **状态**：活跃
- **优先级**：P0
- **节点**：`style_ref_extract_scene`
- **模板**：`config/prompts.yaml` → `style_ref_extract_scene`（version `2026-05-25.v1`，input_token_budget 3000）
- **路由（yaml 兜底，DB 优先）** `默认路由`：model=`gpt-5`，temperature=0.15，max_output_tokens=3200，response_format=`json_object`，timeout_seconds=180
- **用途**：场景层（空间调度/感官布置/动作编排/氛围营造）抽取。
- **触发**：同上。
- **调用链**：`backend/src/novel_system/services/style_reference/extractors/base.py:506`（extract_node_id=本节点）
- **输入组装**：同语言层。
- **输出契约**：同语言层。（解析/校验：`backend/src/novel_system/services/style_reference/extractors/base.py:506`）
- **失败与降级**：同语言层。
- **优化注意**：感官词证据与 sensory_lexicon.yaml 的量化基线互补——findings 应偏「布置策略」而非重复量化指标（那由 metrics.py 硬算）。

**system_prompt（原样发送）**

```text
你是中文叙事场景层风格抽取专家(scene)。给定一个 sub_dimension
(如 scene.dialogue)与一批段落,产出该 sub_dimension 下的 0-8 条
observations 与 0-3 条 forbidden_patterns。
场景层重点:
- environment:场所、天气、自然物的呈现机制(空间布局 / 视点切换 / 光影)
- character_portrayal:人物外貌、衣着、神态、行为的展示手法
- dialogue:对话的密度、长短、轮次、隐喻性、副语言
- sensory_priority:五感(视/听/嗅/触/味)的优先级与并置方式
约束与 language / narrative 层一致:每条 finding ≥2 evidence;严禁空泛
形容词("画面感强""感官丰富"等);forbidden_pattern 描述模式而非引用。
```

**task_prompt（运行时在其后追加指令与上下文）**

```text
输入 payload 含 sub_dimension / metrics_anchor / paragraphs。
请按 schema 输出 observations 与 forbidden_patterns。
宁可输出更少的高质量条目,也不要凑数。
```

**structured_schema（wire 层 + 降级时内联；字段名冻结）**

```json
{
  "additionalProperties": false,
  "properties": {
    "forbidden_patterns": {
      "items": {
        "additionalProperties": false,
        "properties": {
          "confidence": {
            "enum": [
              "high",
              "medium",
              "low"
            ],
            "type": "string"
          },
          "evidence": {
            "items": {
              "additionalProperties": false,
              "properties": {
                "anchor_kind": {
                  "enum": [
                    "paragraph_quote",
                    "author_avoidance",
                    "counter_example"
                  ],
                  "type": "string"
                },
                "illustrates_dims": {
                  "items": {
                    "type": "string"
                  },
                  "type": "array"
                },
                "is_synthetic": {
                  "type": "integer"
                },
                "note": {
                  "type": "string"
                },
                "paragraph_id": {
                  "type": "string"
                },
                "quote": {
                  "type": "string"
                },
                "span": {
                  "items": {
                    "type": "integer"
                  },
                  "maxItems": 2,
                  "minItems": 2,
                  "type": "array"
                }
              },
              "required": [
                "quote"
              ],
              "type": "object"
            },
            "minItems": 2,
            "type": "array"
          },
          "finding_kind": {
            "enum": [
              "forbidden_pattern"
            ],
            "type": "string"
          },
          "statement": {
            "type": "string"
          },
          "sub_dimension": {
            "type": "string"
          }
        },
        "required": [
          "statement",
          "finding_kind",
          "evidence",
          "sub_dimension"
        ],
        "type": "object"
      },
      "maxItems": 3,
      "type": "array"
    },
    "observations": {
      "items": {
        "additionalProperties": false,
        "properties": {
          "confidence": {
            "enum": [
              "high",
              "medium",
              "low"
            ],
            "type": "string"
          },
          "evidence": {
            "items": {
              "additionalProperties": false,
              "properties": {
                "anchor_kind": {
                  "enum": [
                    "paragraph_quote",
                    "author_avoidance",
                    "counter_example"
                  ],
                  "type": "string"
                },
                "illustrates_dims": {
                  "items": {
                    "type": "string"
                  },
                  "type": "array"
                },
                "is_synthetic": {
                  "type": "integer"
                },
                "note": {
                  "type": "string"
                },
                "paragraph_id": {
                  "type": "string"
                },
                "quote": {
                  "type": "string"
                },
                "span": {
                  "items": {
                    "type": "integer"
                  },
                  "maxItems": 2,
                  "minItems": 2,
                  "type": "array"
                }
              },
              "required": [
                "quote"
              ],
              "type": "object"
            },
            "minItems": 2,
            "type": "array"
          },
          "finding_kind": {
            "enum": [
              "observation"
            ],
            "type": "string"
          },
          "statement": {
            "type": "string"
          },
          "sub_dimension": {
            "type": "string"
          }
        },
        "required": [
          "statement",
          "finding_kind",
          "evidence",
          "sub_dimension"
        ],
        "type": "object"
      },
      "maxItems": 8,
      "type": "array"
    }
  },
  "required": [
    "observations",
    "forbidden_patterns"
  ],
  "type": "object"
}
```

### [D-06] style_ref_extract_theme — 主题层风格抽取（4 sub_dim）

- **状态**：活跃
- **优先级**：P0
- **节点**：`style_ref_extract_theme`
- **模板**：`config/prompts.yaml` → `style_ref_extract_theme`（version `2026-05-25.v1`，input_token_budget 3000）
- **路由（yaml 兜底，DB 优先）** `默认路由`：model=`gpt-5`，temperature=0.15，max_output_tokens=3200，response_format=`json_object`，timeout_seconds=180
- **用途**：主题层（母题/象征系统/价值张力/情感曲线）抽取。
- **触发**：同上。
- **调用链**：`backend/src/novel_system/services/style_reference/extractors/base.py:506`（extract_node_id=本节点）
- **输入组装**：同语言层。
- **输出契约**：同语言层；注意主题层 forbidden_pattern（招牌意象）是反克隆关键。（解析/校验：`backend/src/novel_system/services/style_reference/extractors/base.py:506`）
- **失败与降级**：同语言层。
- **优化注意**：反抄袭敏感层：指令必须强化「抽象策略、不许摘招牌意象为可用素材」——招牌意象只能进 forbidden_pattern。

**system_prompt（原样发送）**

```text
你是中文叙事主题层风格抽取专家(theme)。给定一个 sub_dimension
(如 theme.emotional_tone)与一批段落,产出该 sub_dimension 下的 0-8 条
observations 与 0-3 条 forbidden_patterns。
主题层重点:
- emotional_tone:情绪基调与节奏(克制 / 沸腾 / 灰冷 / 高亢)
- values:作品潜在的价值观倾向(集体 vs 个体 / 出世 vs 入世)
- motifs:反复出现的意象与母题(雪 / 雾 / 镜 / 牲口 / 钱财)
- narrative_philosophy:对人/历史/命运的态度(悲悯 / 嘲讽 / 反讽 / 史诗)
约束:theme 层抽象,observation 必须给出"作品如何通过 X 表达 Y"的具体
机制,不要泛泛说"作者关心 X";每条 finding ≥2 evidence;严禁空泛
形容词("思想深刻""主题宏大"等);forbidden_pattern 描述模式而非引用。
```

**task_prompt（运行时在其后追加指令与上下文）**

```text
输入 payload 含 sub_dimension / metrics_anchor / paragraphs。
请按 schema 输出 observations 与 forbidden_patterns。
宁可输出更少的高质量条目,也不要凑数。
```

**structured_schema（wire 层 + 降级时内联；字段名冻结）**

```json
{
  "additionalProperties": false,
  "properties": {
    "forbidden_patterns": {
      "items": {
        "additionalProperties": false,
        "properties": {
          "confidence": {
            "enum": [
              "high",
              "medium",
              "low"
            ],
            "type": "string"
          },
          "evidence": {
            "items": {
              "additionalProperties": false,
              "properties": {
                "anchor_kind": {
                  "enum": [
                    "paragraph_quote",
                    "author_avoidance",
                    "counter_example"
                  ],
                  "type": "string"
                },
                "illustrates_dims": {
                  "items": {
                    "type": "string"
                  },
                  "type": "array"
                },
                "is_synthetic": {
                  "type": "integer"
                },
                "note": {
                  "type": "string"
                },
                "paragraph_id": {
                  "type": "string"
                },
                "quote": {
                  "type": "string"
                },
                "span": {
                  "items": {
                    "type": "integer"
                  },
                  "maxItems": 2,
                  "minItems": 2,
                  "type": "array"
                }
              },
              "required": [
                "quote"
              ],
              "type": "object"
            },
            "minItems": 2,
            "type": "array"
          },
          "finding_kind": {
            "enum": [
              "forbidden_pattern"
            ],
            "type": "string"
          },
          "statement": {
            "type": "string"
          },
          "sub_dimension": {
            "type": "string"
          }
        },
        "required": [
          "statement",
          "finding_kind",
          "evidence",
          "sub_dimension"
        ],
        "type": "object"
      },
      "maxItems": 3,
      "type": "array"
    },
    "observations": {
      "items": {
        "additionalProperties": false,
        "properties": {
          "confidence": {
            "enum": [
              "high",
              "medium",
              "low"
            ],
            "type": "string"
          },
          "evidence": {
            "items": {
              "additionalProperties": false,
              "properties": {
                "anchor_kind": {
                  "enum": [
                    "paragraph_quote",
                    "author_avoidance",
                    "counter_example"
                  ],
                  "type": "string"
                },
                "illustrates_dims": {
                  "items": {
                    "type": "string"
                  },
                  "type": "array"
                },
                "is_synthetic": {
                  "type": "integer"
                },
                "note": {
                  "type": "string"
                },
                "paragraph_id": {
                  "type": "string"
                },
                "quote": {
                  "type": "string"
                },
                "span": {
                  "items": {
                    "type": "integer"
                  },
                  "maxItems": 2,
                  "minItems": 2,
                  "type": "array"
                }
              },
              "required": [
                "quote"
              ],
              "type": "object"
            },
            "minItems": 2,
            "type": "array"
          },
          "finding_kind": {
            "enum": [
              "observation"
            ],
            "type": "string"
          },
          "statement": {
            "type": "string"
          },
          "sub_dimension": {
            "type": "string"
          }
        },
        "required": [
          "statement",
          "finding_kind",
          "evidence",
          "sub_dimension"
        ],
        "type": "object"
      },
      "maxItems": 8,
      "type": "array"
    }
  },
  "required": [
    "observations",
    "forbidden_patterns"
  ],
  "type": "object"
}
```

### [D-07] style_ref_supplement_evidence — 单 observation 定向补证

- **状态**：活跃
- **优先级**：P0
- **节点**：`style_ref_supplement_evidence`
- **模板**：`config/prompts.yaml` → `style_ref_supplement_evidence`（version `2026-05-23.v1`，input_token_budget 2000）
- **路由（yaml 兜底，DB 优先）** `默认路由`：model=`gpt-5-mini`，temperature=0.15，max_output_tokens=1500，response_format=`json_object`
- **用途**：两级重试第一级：对证据不足的单条 observation，从新采样段落里定向补 evidence span。
- **触发**：抽取 run 内部（_supplement_* 路径）。
- **调用链**：`backend/src/novel_system/services/style_reference/extractors/base.py:506`（supplement_node_id 固定为本节点）
- **输入组装**：task_prompt + JSON：目标 observation + 候选段落。
- **输出契约**：SupplementEvidenceOutput.model_validate（Pydantic）；span 必须可定位。（解析/校验：`backend/src/novel_system/services/style_reference/extractors/base.py:481`）
- **失败与降级**：失败升级为整 sub_dim 重抽。
- **优化注意**：小任务小模型：指令要极窄——只找支持既有 statement 的原文 span，明示「找不到就返回空」比硬凑重要。

**system_prompt（原样发送）**

```text
你是中文段落证据补抽专家。某条已抽出的 observation 当前 evidence 不足(<2)。
在给定的段落池中找出能支撑该 observation 的额外 evidence(quote 必须是段落原句)。
```

**task_prompt（运行时在其后追加指令与上下文）**

```text
输入 payload 含 finding_statement / finding_kind / sub_dimension /
existing_evidence_count / paragraphs。
请返回 additional_evidence 列表(≥1 条);若段落池中无合适证据,返回空数组。
```

**structured_schema（wire 层 + 降级时内联；字段名冻结）**

```json
{
  "additionalProperties": false,
  "properties": {
    "additional_evidence": {
      "items": {
        "additionalProperties": false,
        "properties": {
          "anchor_kind": {
            "enum": [
              "paragraph_quote",
              "author_avoidance",
              "counter_example"
            ],
            "type": "string"
          },
          "illustrates_dims": {
            "items": {
              "type": "string"
            },
            "type": "array"
          },
          "is_synthetic": {
            "type": "integer"
          },
          "note": {
            "type": "string"
          },
          "paragraph_id": {
            "type": "string"
          },
          "quote": {
            "type": "string"
          },
          "span": {
            "items": {
              "type": "integer"
            },
            "maxItems": 2,
            "minItems": 2,
            "type": "array"
          }
        },
        "required": [
          "quote"
        ],
        "type": "object"
      },
      "type": "array"
    }
  },
  "required": [
    "additional_evidence"
  ],
  "type": "object"
}
```

### [D-08] style_ref_synthesize_profile — Profile 聚合（16 sub_dim → StyleProfile）

- **状态**：活跃
- **优先级**：P0
- **节点**：`style_ref_synthesize_profile`
- **模板**：`config/prompts.yaml` → `style_ref_synthesize_profile`（version `2026-05-23.v1`，input_token_budget 3500）
- **路由（yaml 兜底，DB 优先）** `默认路由`：model=`gpt-5`，temperature=0.2，max_output_tokens=3500，response_format=`json_object`，timeout_seconds=180
- **用途**：把 16 个 sub_dim 的 findings 聚合为可注入的分层 StyleProfile（+量化指标基线合流），聚合完触发 RAG 索引构建。
- **触发**：POST /api/v2/style-reference/…/synthesize（ProfileSynthesizer.synthesize）。
- **调用链**：`backend/src/novel_system/services/style_reference/profile_synthesizer.py:154`（SYNTHESIZE_NODE_ID）
- **输入组装**：task_prompt + JSON：全部 findings（含 forbidden_pattern）+ metrics 基线。
- **输出契约**：SynthesizedProfile.model_validate（Pydantic，严格）；失败 SynthesizeError。（解析/校验：`backend/src/novel_system/services/style_reference/profile_synthesizer.py:106`）
- **失败与降级**：LLM 未启用 → LLMRequiredError；RAG 索引构建失败容错不阻塞。
- **优化注意**：输出即最终注入文本的直接素材：要求每条 profile 规则「指令化」（做什么/不做什么/示例句式骨架），并保留 forbidden_pattern 的独立区块。schema 大且严——弱模型上失败率高，指令中把 schema 关键字段用途讲一遍。

**system_prompt（原样发送）**

```text
你是中文叙事风格 Profile 聚合专家。给定一本书的 8 sub_dim findings 摘要
(observations + forbidden_patterns)与硬指标 baseline,聚合为一份 StyleProfile,
包含:
  - profile_title:简短(<20 字)的画像标题
  - narrative_summary:80-200 字的整体风格简述
  - style_features:可迁移的语言层 / 节奏层写作机制(短句,可直接作 style_rule 用)
  - narrative_patterns:可迁移的叙事 / 场景层模式
  - banned_replication_rules:禁止复制的具体表达 / 模式(基于 forbidden_patterns 聚合)
  - calibration_guidance:校准提示句(每条针对一个常见漂移,作 calibration_line 用)
约束:
- 输出字段全部为短句陈述(<120 字),不要复述 evidence
- 严禁空泛形容词("文笔优美""画面感强")
- 严禁照抄原文(banned_replication_rules 描述模式而非引用)
```

**task_prompt（运行时在其后追加指令与上下文）**

```text
输入 payload 含 book_title / sub_dimensions / metrics_baseline / sample_quotes。
请按 schema 输出 profile;style_features / narrative_patterns /
banned_replication_rules / calibration_guidance 每个数组 4-10 条。
```

**structured_schema（wire 层 + 降级时内联；字段名冻结）**

```json
{
  "additionalProperties": false,
  "properties": {
    "banned_replication_rules": {
      "items": {
        "type": "string"
      },
      "type": "array"
    },
    "calibration_guidance": {
      "items": {
        "type": "string"
      },
      "type": "array"
    },
    "narrative_patterns": {
      "items": {
        "type": "string"
      },
      "type": "array"
    },
    "narrative_summary": {
      "type": "string"
    },
    "profile_title": {
      "type": "string"
    },
    "style_features": {
      "items": {
        "type": "string"
      },
      "type": "array"
    }
  },
  "required": [
    "profile_title",
    "narrative_summary",
    "style_features",
    "narrative_patterns",
    "banned_replication_rules"
  ],
  "type": "object"
}
```

### [D-09] style_ref_preview_generate — 风格预览样本

- **状态**：活跃
- **优先级**：P1
- **节点**：`style_ref_preview_generate`
- **模板**：`config/prompts.yaml` → `style_ref_preview_generate`（version `2026-05-23.v1`，input_token_budget 1500）
- **路由（yaml 兜底，DB 优先）** `默认路由`：model=`gpt-5-mini`，temperature=0.7，max_output_tokens=1500，response_format=`json_object`
- **用途**：Profile 效果预览：按 Profile 生成 3 段示例文本给作者判断风格拟合度。
- **触发**：预览端点（PreviewService，3 样本逐个调用）。
- **调用链**：`backend/src/novel_system/services/style_reference/preview.py:164`（逐样本调用）
- **输入组装**：task_prompt + JSON：Profile 摘要 + 样本题面。
- **输出契约**：PreviewGeneratedSample（Pydantic）。（解析/校验：`backend/src/novel_system/services/style_reference/preview.py:164`）
- **失败与降级**：单样本失败标 error="llm_call_failed"，不阻塞其余样本。
- **优化注意**：预览要「放大」风格特征让人眼可辨——可指示样本各侧重一层（语言/叙事/场景），并遵守 forbidden_pattern。

**system_prompt（原样发送）**

```text
你是中文叙事写作示例生成助手。给定一份 StyleProfile 摘要与一个 paragraph_type
(dialogue / description_env / psychology 三选一),生成一段 ≤500 字的示例
中文文本,体现该 profile 的语言与叙事特征。
约束:
- 严禁照抄 seed_quote(只作为风格参考,不直接复用句子)
- 严禁使用空泛形容词("文笔优美""画面感强")
- 段落自包含,不依赖未给出的上下文
```

**task_prompt（运行时在其后追加指令与上下文）**

```text
输入 payload 含 profile_summary / paragraph_type / seed_quote / style_features。
请返回 sample_text(≤500 字中文)与 paragraph_type。
```

**structured_schema（wire 层 + 降级时内联；字段名冻结）**

```json
{
  "additionalProperties": false,
  "properties": {
    "paragraph_type": {
      "type": "string"
    },
    "sample_text": {
      "type": "string"
    }
  },
  "required": [
    "sample_text"
  ],
  "type": "object"
}
```

### [D-10] style_ref_validate_semantic — 语义评审校验

- **状态**：活跃
- **优先级**：P1
- **节点**：`style_ref_validate_semantic`
- **模板**：`config/prompts.yaml` → `style_ref_validate_semantic`（version `2026-05-25.v1`，input_token_budget 2000）
- **路由（yaml 兜底，DB 优先）** `默认路由`：model=`gpt-5`，temperature=0.2，max_output_tokens=2000，response_format=`json_object`
- **用途**：验证三通道之一：批评家 LLM 判定生成文与 Profile 的语义符合度（逐维打分+引文）。
- **触发**：验证 async_full 通道（ValidationOrchestrator 派发；sync 快路径不走 LLM）。
- **调用链**：`backend/src/novel_system/services/style_reference/validation/semantic.py:49`（check_semantic）
- **输入组装**：task_prompt + JSON：待验文本 + Profile 要点。
- **输出契约**：SemanticReportItem 列表；引用必须带「」直角引号，否则该项分数被压到 ≤4（代码强制）。（解析/校验：`backend/src/novel_system/services/style_reference/validation/semantic.py:49`）
- **失败与降级**：LLMNodeError → 该通道降级 semantic=[]（不阻塞验证报告）。
- **优化注意**：「」引号是解析契约——指令里已有也不可删。打分尺度要给锚例（3/6/9 分各长什么样），否则弱模型分数挤中间。

**system_prompt（原样发送）**

```text
你是中文叙事 critic。给定一段生成文本与目标 StyleProfile 的 style_features /
narrative_summary,对若干 dimension(rhythm / tone / motif / pacing / language)
给出 0-10 分评分与 explanation。

硬约束:
- explanation **必须用「...」中文弯引号** 引用至少一个生成文本的原句作为证据
- 若 explanation 不含「...」引文,系统会自动把 score 截至 4 分
- explanation 200 字以内
- score 0-10,7+ 视为风格匹配良好;4-6 部分匹配;<4 严重不匹配
```

**task_prompt（运行时在其后追加指令与上下文）**

```text
输入 payload 含 generated_text / style_features / narrative_summary。
请按 schema 输出 dimension_scores 数组(3-5 个 dimension)。
```

**structured_schema（wire 层 + 降级时内联；字段名冻结）**

```json
{
  "additionalProperties": false,
  "properties": {
    "dimension_scores": {
      "items": {
        "additionalProperties": false,
        "properties": {
          "dimension": {
            "type": "string"
          },
          "explanation": {
            "type": "string"
          },
          "score": {
            "type": "number"
          }
        },
        "required": [
          "dimension",
          "score",
          "explanation"
        ],
        "type": "object"
      },
      "type": "array"
    }
  },
  "required": [
    "dimension_scores"
  ],
  "type": "object"
}
```

### [D-11] style_ref_validate_forbidden — 禁忌模式触发判定

- **状态**：活跃
- **优先级**：P1
- **节点**：`style_ref_validate_forbidden`
- **模板**：`config/prompts.yaml` → `style_ref_validate_forbidden`（version `2026-05-25.v1`，input_token_budget 800）
- **路由（yaml 兜底，DB 优先）** `默认路由`：model=`gpt-5-mini`，temperature=0.1，max_output_tokens=800，response_format=`json_object`
- **用途**：对 Profile 的每条 forbidden_pattern 单独判定生成文是否触犯（语义级，补 forbidden_local 字面扫描的盲区）。
- **触发**：验证 async_full 通道。
- **调用链**：`backend/src/novel_system/services/style_reference/validation/forbidden_semantic.py:62`（每 pattern 一次调用）
- **输入组装**：task_prompt + JSON：单条 forbidden_pattern + 待验文本。
- **输出契约**：ForbiddenHit（命中与证据）。（解析/校验：`backend/src/novel_system/services/style_reference/validation/forbidden_semantic.py:62`）
- **失败与降级**：单 pattern 失败 try/except 跳过。
- **优化注意**：二分类小任务：输出宜收窄为 {hit, evidence, reason}；「变体/转写也算命中」的语义扩展判据要写明。

**system_prompt（原样发送）**

```text
你判断给定生成文本是否触发了某条 forbidden_pattern(作者明确不会用的写作模式)。
返回 {triggered, excerpt, reasoning}:
- triggered=true 时,excerpt 给出生成文本中命中该模式的原句节选(<60 字)
- triggered=false 时,excerpt 为空,reasoning 简述为何不算触发
- 仅看是否"模式被采用",不看字面词命中(那是 forbidden_local 的事)
```

**task_prompt（运行时在其后追加指令与上下文）**

```text
输入 payload 含 generated_text / forbidden_statement / sub_dimension。
请按 schema 输出 triggered / excerpt / reasoning。
```

**structured_schema（wire 层 + 降级时内联；字段名冻结）**

```json
{
  "additionalProperties": false,
  "properties": {
    "excerpt": {
      "type": "string"
    },
    "reasoning": {
      "type": "string"
    },
    "triggered": {
      "type": "boolean"
    }
  },
  "required": [
    "triggered"
  ],
  "type": "object"
}
```

### [D-12] style_ref_rag_rerank — RAG 候选重排（保留 hook，未接线）

- **状态**：保留（status=reserved；rag.py 用确定性重排，inject 热路径 <50ms 无 LLM——本节点从未被调用）
- **优先级**：P2
- **节点**：`style_ref_rag_rerank`
- **模板**：`config/prompts.yaml` → `style_ref_rag_rerank`（version `2026-06-18.v1`，input_token_budget 800）
- **路由（yaml 兜底，DB 优先）** `默认路由`：model=`gpt-5-mini`，temperature=0.1，max_output_tokens=800，response_format=`json_object`
- **用途**：预留的离线/预览增强 rerank 钩子；当前 Strategy C 的三粒度召回 + 重排全为确定性。
- **触发**：无（未接线）。
- **调用链**：`backend/src/novel_system/services/style_reference/rag.py:44`（仅常量定义，无调用）
- **输入组装**：（未接线）模板设定为候选片段重排。
- **输出契约**：（未接线）。
- **失败与降级**：—
- **优化注意**：P2：接线前不必优化；若未来启用，注意它在 inject 热路径之外（延迟不敏感，可用强模型）。

**system_prompt（原样发送）**

```text
你是风格检索重排器。给定"当前生成上下文"与若干"参考风格候选片段",
按候选片段对当前上下文在句式、节奏、语气上的风格借鉴价值从高到低重排。
只评估风格可借鉴性(句式/节奏/肌理),不评估情节相关性;
严禁输出任何候选原文的改写、续写或翻译,只输出重排结果。
```

**task_prompt（运行时在其后追加指令与上下文）**

```text
输入 payload 含 context_text 与 candidates(每条 {id, granularity, text})。
请按 schema 输出 ranked:候选 id 按风格借鉴价值降序排列,各附 0-1 的 score。
```

**structured_schema（wire 层 + 降级时内联；字段名冻结）**

```json
{
  "additionalProperties": false,
  "properties": {
    "ranked": {
      "items": {
        "additionalProperties": false,
        "properties": {
          "id": {
            "type": "string"
          },
          "score": {
            "type": "number"
          }
        },
        "required": [
          "id",
          "score"
        ],
        "type": "object"
      },
      "type": "array"
    }
  },
  "required": [
    "ranked"
  ],
  "type": "object"
}
```

## §7 批次 E · 作家评审（7 个单元）

写作者视角的场景/章节多镜头诊断（story/character/prose/reader 四镜头共享同一模板，镜头差异经 user_prompt 上下文注入）、修订稿生成、深度评审与作者提案。

### [E-01] writer_scene_diagnosis — 场景四镜头诊断（story/character/prose/reader 共享模板）

- **状态**：活跃（4 个镜头节点各自路由、共享本模板；基节点 writer_scene_diagnosis 仅作模板载体，从不直接调用）
- **优先级**：P1
- **节点**：`writer_scene_diagnosis`、`writer_scene_story_diagnosis`、`writer_scene_character_diagnosis`、`writer_scene_prose_diagnosis`、`writer_scene_reader_diagnosis`
- **模板**：`config/prompts.yaml` → `writer_scene_diagnosis`（version `2026-04-24.v1`，input_token_budget 2200）
- **路由（yaml 兜底，DB 优先）** `writer_scene_diagnosis`：model=`gpt-5`，temperature=0.2，max_output_tokens=2200，response_format=`json_object`
- **用途**：写作者场景评审：故事/角色/文笔/读者四镜头并行诊断，产出问题清单与修改方向。
- **触发**：POST 写作者评审端点（api/routes/writer_review.py → run_scene_review，按 WRITER_REVIEW_LENSES 逐镜头调用）。
- **调用链**：`backend/src/novel_system/services/writer_review.py:102`（镜头表定义）；`backend/src/novel_system/services/writer_review.py:766`（_run_writer_diagnosis 动态节点，经 PromptBuilder(writer_scene_diagnosis)）
- **输入组装**：PromptBuilder(writer_scene_diagnosis) + _writer_review_user_prompt（object_type/object_id/正文 source/writer_context——镜头差异由此注入）。
- **输出契约**：_validate_writer_diagnosis_payload 手工校验的诊断 payload（维度/发现/建议）。（解析/校验：`backend/src/novel_system/services/writer_review.py:774`）
- **失败与降级**：OfflineWriterReviewClient 桩；LLMNodeExecutionError → blocked payload（前端可见「诊断被阻断」）。
- **优化注意**：一份模板服务四镜头：模板必须按 writer_context 中的镜头标识切换判据，且四镜头产出不重叠（story 管结构、prose 管句子……）——在模板里给四镜头各自的检查清单与禁越界说明。

**system_prompt（原样发送）**

```text
You are a professional fiction editor diagnosing whether a scene works dramatically.
Focus on desire, obstacle, stakes, turn, subtext, irreversible change, scene necessity, reader hook, and continuity.
Also evaluate character agency, dialogue edge, information rhythm, imagery freshness, expression repetition, power shift, and ending drive.
Do not overwrite final prose; produce structured diagnosis and actionable revision briefs only.
```

**task_prompt（运行时在其后追加指令与上下文）**

```text
Diagnose the supplied scene against drama_effectiveness_v1.
Write string fields in Chinese while preserving the schema keys.
Every finding must cite concrete source-text evidence, where it appears, and why it matters to the reader.
If any required rubric field is uncertain or missing, mark requires_human_review true and add a blocker finding.
```

**structured_schema（wire 层 + 降级时内联；字段名冻结）**

```json
{
  "additionalProperties": false,
  "properties": {
    "findings": {
      "items": {
        "additionalProperties": false,
        "properties": {
          "dimension": {
            "type": "string"
          },
          "evidence_excerpt": {
            "type": "string"
          },
          "evidence_location": {
            "type": "string"
          },
          "issue": {
            "type": "string"
          },
          "recommendation": {
            "type": "string"
          },
          "severity": {
            "type": "string"
          },
          "why_it_matters": {
            "type": "string"
          }
        },
        "required": [
          "dimension",
          "severity",
          "issue",
          "recommendation",
          "evidence_excerpt",
          "evidence_location",
          "why_it_matters"
        ],
        "type": "object"
      },
      "type": "array"
    },
    "overall_score": {
      "type": "number"
    },
    "requires_human_review": {
      "type": "boolean"
    },
    "revision_brief": {
      "items": {
        "additionalProperties": false,
        "properties": {
          "action": {
            "type": "string"
          },
          "dimension": {
            "type": "string"
          },
          "priority": {
            "type": "string"
          }
        },
        "required": [
          "dimension",
          "action",
          "priority"
        ],
        "type": "object"
      },
      "type": "array"
    },
    "scores": {
      "additionalProperties": false,
      "properties": {
        "character_agency": {
          "type": "number"
        },
        "continuity": {
          "type": "number"
        },
        "desire": {
          "type": "number"
        },
        "dialogue_edge": {
          "type": "number"
        },
        "ending_drive": {
          "type": "number"
        },
        "expression_repetition": {
          "type": "number"
        },
        "imagery_freshness": {
          "type": "number"
        },
        "information_rhythm": {
          "type": "number"
        },
        "irreversible_change": {
          "type": "number"
        },
        "obstacle": {
          "type": "number"
        },
        "power_shift": {
          "type": "number"
        },
        "reader_hook": {
          "type": "number"
        },
        "scene_necessity": {
          "type": "number"
        },
        "stakes": {
          "type": "number"
        },
        "subtext": {
          "type": "number"
        },
        "turn": {
          "type": "number"
        }
      },
      "required": [
        "desire",
        "obstacle",
        "stakes",
        "turn",
        "subtext",
        "irreversible_change",
        "scene_necessity",
        "reader_hook",
        "continuity",
        "character_agency",
        "dialogue_edge",
        "information_rhythm",
        "imagery_freshness",
        "expression_repetition",
        "power_shift",
        "ending_drive"
      ],
      "type": "object"
    }
  },
  "required": [
    "overall_score",
    "scores",
    "findings",
    "revision_brief",
    "requires_human_review"
  ],
  "type": "object"
}
```

### [E-02] writer_scene_revision — 场景修订稿

- **状态**：活跃
- **优先级**：P1
- **节点**：`writer_scene_revision`
- **模板**：`config/prompts.yaml` → `writer_scene_revision`（version `2026-04-24.v1`，input_token_budget 2600）
- **路由（yaml 兜底，DB 优先）** `默认路由`：model=`gpt-5`，temperature=0.5，max_output_tokens=5000，response_format=`json_object`
- **用途**：按四镜头诊断结果产出修订稿（写作者可对照采纳）。
- **触发**：写作者评审端点 revision 阶段（run_scene_review 内串行）。
- **调用链**：`backend/src/novel_system/services/writer_review.py:810`（_run_scene_revision）
- **输入组装**：PromptBuilder(writer_scene_revision)：原稿 + 诊断汇总。
- **输出契约**：修订稿 payload；服务内归一。（解析/校验：`backend/src/novel_system/services/writer_review.py:810`）
- **失败与降级**：同诊断（桩/blocked）。
- **优化注意**：「按诊断改、不夹带私改」是契约：要求逐条诊断给出对应改动或明确拒绝理由，禁顺手重写无病段落。

**system_prompt（原样发送）**

```text
You are preparing a candidate revision for a fiction author.
Keep the candidate separate from the approved final text; never claim it has been applied.
```

**task_prompt（运行时在其后追加指令与上下文）**

```text
Rewrite the supplied scene using the writer diagnosis and revision brief.
Preserve continuity and source language. If the source is Chinese, output Chinese prose.
Return a complete revised scene as revised_text, not advice appended to the old text.
```

**structured_schema（wire 层 + 降级时内联；字段名冻结）**

```json
{
  "additionalProperties": false,
  "properties": {
    "changed_dimensions": {
      "items": {
        "type": "string"
      },
      "type": "array"
    },
    "diff_summary": {
      "type": "string"
    },
    "revised_text": {
      "type": "string"
    },
    "rewrite_strategy": {
      "type": "string"
    }
  },
  "required": [
    "revised_text",
    "diff_summary",
    "changed_dimensions",
    "rewrite_strategy"
  ],
  "type": "object"
}
```

### [E-03] writer_chapter_diagnosis — 章节四镜头诊断（共享模板）

- **状态**：活跃（同场景侧：4 镜头节点共享，基节点仅模板载体）
- **优先级**：P1
- **节点**：`writer_chapter_diagnosis`、`writer_chapter_story_diagnosis`、`writer_chapter_character_diagnosis`、`writer_chapter_prose_diagnosis`、`writer_chapter_reader_diagnosis`
- **模板**：`config/prompts.yaml` → `writer_chapter_diagnosis`（version `2026-04-24.v1`，input_token_budget 3200）
- **路由（yaml 兜底，DB 优先）** `writer_chapter_diagnosis`：model=`gpt-5`，temperature=0.2，max_output_tokens=3200，response_format=`json_object`
- **用途**：章级四镜头诊断（输入为整章）。
- **触发**：run_chapter_review（api/routes/writer_review.py）。
- **调用链**：`backend/src/novel_system/services/writer_review.py:103`（镜头表定义）；`backend/src/novel_system/services/writer_review.py:766`（同一动态调用点）
- **输入组装**：同场景侧，输入为章级 source。
- **输出契约**：同场景侧。（解析/校验：`backend/src/novel_system/services/writer_review.py:774`）
- **失败与降级**：同场景侧。
- **优化注意**：章长输入下弱模型「只看前三分之一」问题突出——指令要求按场景分段给出覆盖证据（每场景至少一条观察）再汇总。

**system_prompt（原样发送）**

```text
You are a professional fiction editor diagnosing chapter-level dramatic effectiveness.
Focus on chapter promise, scene necessity, rhythm breakpoints, continuity, escalation, ending hook, and missing scene functions.
Also evaluate character agency, dialogue edge, information rhythm, imagery freshness, expression repetition, power shift, and ending drive.
```

**task_prompt（运行时在其后追加指令与上下文）**

```text
Diagnose the assembled or aggregate chapter against drama_effectiveness_v1.
Write string fields in Chinese while preserving the schema keys.
Every finding must cite concrete source-text evidence, where it appears, and why it matters to the reader.
If the chapter lacks enough source text or a required dimension is unclear, mark requires_human_review true.
```

**structured_schema（wire 层 + 降级时内联；字段名冻结）**

```json
{
  "additionalProperties": false,
  "properties": {
    "findings": {
      "items": {
        "additionalProperties": false,
        "properties": {
          "dimension": {
            "type": "string"
          },
          "evidence_excerpt": {
            "type": "string"
          },
          "evidence_location": {
            "type": "string"
          },
          "issue": {
            "type": "string"
          },
          "recommendation": {
            "type": "string"
          },
          "severity": {
            "type": "string"
          },
          "why_it_matters": {
            "type": "string"
          }
        },
        "required": [
          "dimension",
          "severity",
          "issue",
          "recommendation",
          "evidence_excerpt",
          "evidence_location",
          "why_it_matters"
        ],
        "type": "object"
      },
      "type": "array"
    },
    "overall_score": {
      "type": "number"
    },
    "requires_human_review": {
      "type": "boolean"
    },
    "revision_brief": {
      "items": {
        "additionalProperties": false,
        "properties": {
          "action": {
            "type": "string"
          },
          "dimension": {
            "type": "string"
          },
          "priority": {
            "type": "string"
          }
        },
        "required": [
          "dimension",
          "action",
          "priority"
        ],
        "type": "object"
      },
      "type": "array"
    },
    "scores": {
      "additionalProperties": false,
      "properties": {
        "character_agency": {
          "type": "number"
        },
        "continuity": {
          "type": "number"
        },
        "desire": {
          "type": "number"
        },
        "dialogue_edge": {
          "type": "number"
        },
        "ending_drive": {
          "type": "number"
        },
        "expression_repetition": {
          "type": "number"
        },
        "imagery_freshness": {
          "type": "number"
        },
        "information_rhythm": {
          "type": "number"
        },
        "irreversible_change": {
          "type": "number"
        },
        "obstacle": {
          "type": "number"
        },
        "power_shift": {
          "type": "number"
        },
        "reader_hook": {
          "type": "number"
        },
        "scene_necessity": {
          "type": "number"
        },
        "stakes": {
          "type": "number"
        },
        "subtext": {
          "type": "number"
        },
        "turn": {
          "type": "number"
        }
      },
      "required": [
        "desire",
        "obstacle",
        "stakes",
        "turn",
        "subtext",
        "irreversible_change",
        "scene_necessity",
        "reader_hook",
        "continuity",
        "character_agency",
        "dialogue_edge",
        "information_rhythm",
        "imagery_freshness",
        "expression_repetition",
        "power_shift",
        "ending_drive"
      ],
      "type": "object"
    }
  },
  "required": [
    "overall_score",
    "scores",
    "findings",
    "revision_brief",
    "requires_human_review"
  ],
  "type": "object"
}
```

### [E-04] writer_chapter_revision — 章节修订稿

- **状态**：活跃
- **优先级**：P1
- **节点**：`writer_chapter_revision`
- **模板**：`config/prompts.yaml` → `writer_chapter_revision`（version `2026-04-25.v1`，input_token_budget 3600）
- **路由（yaml 兜底，DB 优先）** `默认路由`：model=`gpt-5`，temperature=0.45，max_output_tokens=4200，response_format=`json_object`
- **用途**：章级修订（跨场景衔接/节奏级改动）。
- **触发**：run_chapter_review revision 阶段。
- **调用链**：`backend/src/novel_system/services/writer_review.py:845`（_run_chapter_revision）
- **输入组装**：PromptBuilder(writer_chapter_revision)：整章 + 诊断汇总。
- **输出契约**：修订 payload；服务内归一。（解析/校验：`backend/src/novel_system/services/writer_review.py:845`）
- **失败与降级**：同上。
- **优化注意**：输出长度上限（max_output_tokens 4200）撑不下整章重写——模板应导向「定点手术清单 + 关键段落重写」而非全文重排。

**system_prompt（原样发送）**

```text
You are preparing a chapter-level candidate revision plan for a fiction author.
Keep the candidate separate from approved final text; never claim it has been applied.
Do not rewrite the whole chapter unless explicitly asked. Prefer a concise plan plus selected high-impact passage rewrites.
```

**task_prompt（运行时在其后追加指令与上下文）**

```text
Use the writer diagnosis and revision brief to produce a chapter revision plan.
Write all strings in Chinese while preserving schema keys.
Preserve continuity and source language. For selected passages, quote only short source excerpts and provide rewritten replacements.
```

**structured_schema（wire 层 + 降级时内联；字段名冻结）**

```json
{
  "additionalProperties": false,
  "properties": {
    "changed_dimensions": {
      "items": {
        "type": "string"
      },
      "type": "array"
    },
    "diff_summary": {
      "type": "string"
    },
    "revision_plan": {
      "items": {
        "type": "string"
      },
      "type": "array"
    },
    "rewrite_strategy": {
      "type": "string"
    },
    "selected_rewrite_passages": {
      "items": {
        "additionalProperties": false,
        "properties": {
          "reason": {
            "type": "string"
          },
          "revised_text": {
            "type": "string"
          },
          "source_excerpt": {
            "type": "string"
          }
        },
        "required": [
          "source_excerpt",
          "revised_text",
          "reason"
        ],
        "type": "object"
      },
      "type": "array"
    }
  },
  "required": [
    "revision_plan",
    "selected_rewrite_passages",
    "diff_summary"
  ],
  "type": "object"
}
```

### [E-05] writer_deep_review — 深度评审

- **状态**：活跃
- **优先级**：P1
- **节点**：`writer_deep_review`
- **模板**：`config/prompts.yaml` → `writer_deep_review`（version `2026-04-25.v1`，input_token_budget 3000）
- **路由（yaml 兜底，DB 优先）** `默认路由`：model=`gpt-5`，temperature=0.15，max_output_tokens=3600，response_format=`json_object`
- **用途**：单入口深评：比四镜头更综合的深读报告（问题分层 + 段落级定位 + 修补候选入口）。
- **触发**：api/routes/writer_deep_review.py → run_scene_review / run_chapter_review。
- **调用链**：`backend/src/novel_system/services/writer_deep_review.py:390`（_create_deep_review_with_llm）
- **输入组装**：PromptBuilder(writer_deep_review)：正文 + 上下文分节。
- **输出契约**：_normalize_deep_review_output 归一的深评报告。（解析/校验：`backend/src/novel_system/services/writer_deep_review.py:409`）
- **失败与降级**：OfflineWriterDeepReviewClient 桩。
- **优化注意**：深评发现须能锚定段落（供 writer_passage_patch 消费）——要求每条发现带原文引句或段落序号。

**system_prompt（原样发送）**

```text
You are a severe Chinese fiction revision editor for a working author.
Diagnose literary revision needs without inflating scores. Ordinary usable prose should not receive excellent scores.
Separate blocking structural failures, local revision needs, and taste-level suggestions.
```

**task_prompt（运行时在其后追加指令与上下文）**

```text
Diagnose the supplied passage against literary_revision_v1.
Write Chinese string fields while preserving English schema keys.
Every finding must cite source-text evidence and classify the issue as blocking, revision, or taste.
Focus on character contradiction, choice pressure, relationship tension, dialogue subtext, information rhythm,
voice distinction, image necessity, repetitive expression, ending drive, and theme pressure.
```

**structured_schema（wire 层 + 降级时内联；字段名冻结）**

```json
{
  "additionalProperties": false,
  "properties": {
    "findings": {
      "items": {
        "type": "object"
      },
      "type": "array"
    },
    "overall_score": {
      "type": "number"
    },
    "requires_human_review": {
      "type": "boolean"
    },
    "revision_brief": {
      "items": {
        "type": "object"
      },
      "type": "array"
    },
    "scores": {
      "type": "object"
    }
  },
  "required": [
    "overall_score",
    "scores",
    "findings",
    "revision_brief",
    "requires_human_review"
  ],
  "type": "object"
}
```

### [E-06] writer_reference_application_review — 参考应用评审（孤儿）

- **状态**：孤儿（模板+路由+注册均在，但无任何调用点——评审「参考风格是否被正确应用」的预留功能）
- **优先级**：P2
- **节点**：`writer_reference_application_review`
- **模板**：`config/prompts.yaml` → `writer_reference_application_review`（version `2026-04-24.v1`，input_token_budget 2200）
- **路由（yaml 兜底，DB 优先）** `默认路由`：model=`gpt-5-mini`，temperature=0.1，max_output_tokens=1800，response_format=`json_object`
- **用途**：（预留）评审生成文对参考风格的应用程度。与 style_ref_validate_semantic 定位重叠，接线前先想清分工。
- **触发**：无。
- **输入组装**：（未接线）。
- **输出契约**：（未接线）。
- **失败与降级**：—
- **优化注意**：P2：暂不优化；若接线，建议并入 style_ref 验证家族避免双轨。

**system_prompt（原样发送）**

```text
You review whether learned reference techniques are applied as transferable craft rather than copied expression.
Separate usable technique, forbidden replication, and suitable application scene.
```

**task_prompt（运行时在其后追加指令与上下文）**

```text
Review the reference profile and current target scene/chapter.
Return concise Chinese guidance using stable English schema keys.
```

**structured_schema（wire 层 + 降级时内联；字段名冻结）**

```json
{
  "additionalProperties": false,
  "properties": {
    "forbidden_replication": {
      "items": {
        "type": "string"
      },
      "type": "array"
    },
    "requires_human_review": {
      "type": "boolean"
    },
    "suitable_scenes": {
      "items": {
        "type": "string"
      },
      "type": "array"
    },
    "transferable_techniques": {
      "items": {
        "type": "string"
      },
      "type": "array"
    }
  },
  "required": [
    "transferable_techniques",
    "forbidden_replication",
    "suitable_scenes",
    "requires_human_review"
  ],
  "type": "object"
}
```

### [E-07] author_proposal_generate — 作者修订提案

- **状态**：活跃
- **优先级**：P1
- **节点**：`author_proposal_generate`
- **模板**：`config/prompts.yaml` → `author_proposal_generate`（version `2026-05-14.v1`，input_token_budget 3200）
- **路由（yaml 兜底，DB 优先）** `默认路由`：model=`gpt-5`，temperature=0.45，max_output_tokens=2600，response_format=`json_object`
- **用途**：对作者草稿生成修订提案（proposal / proposal_set，供作者挑选采纳）。
- **触发**：api/routes/author_drafts.py → generate_proposal(_set)。
- **调用链**：`backend/src/novel_system/services/author_drafts.py:652`（_generate_proposal_content）
- **输入组装**：PromptBuilder(author_proposal_generate)：作者草稿 + 项目上下文。
- **输出契约**：structured_output 手工解析（提案文本+理由）。（解析/校验：`backend/src/novel_system/services/author_drafts.py:652`）
- **失败与降级**：OfflineAuthorProposalClient 桩。
- **优化注意**：提案集要方向互斥（保守修 / 结构改 / 风格改各一），并标注每案代价——否则弱模型给三条近似提案。

**system_prompt（原样发送）**

```text
You are a Chinese fiction revision partner for a working author.
Generate one concrete proposal for the current author draft, but preserve the author's intent and do not invent story-specific props, names, places, or lore unless they already appear in the supplied draft or metadata.
Use the author preference summary as constraints: avoid rejected traces and lean toward accepted move types.
When the source draft is thin, give a useful but clearly generic fallback instead of pretending to know the story.
```

**task_prompt（运行时在其后追加指令与上下文）**

```text
Read the supplied author draft, target metadata, proposal request, and author preference summary.
Return exactly one proposal. Write Chinese prose when the source material is Chinese; preserve English schema keys.
The content field should be directly usable as the candidate text or revision note for the requested proposal_type.
The rationale field should briefly explain why this proposal helps and should mention the user instruction when present.
```

**structured_schema（wire 层 + 降级时内联；字段名冻结）**

```json
{
  "additionalProperties": false,
  "properties": {
    "content": {
      "type": "string"
    },
    "rationale": {
      "type": "string"
    }
  },
  "required": [
    "content",
    "rationale"
  ],
  "type": "object"
}
```

## §8 批次 F · 项目与杂项（12 个单元，含内联提示词与休眠任务）

资料库派生、作者样稿画像/结构抽取、遗留 reference_* 孤儿模板、本地保留模板，以及 4 个写死在 Python 里的顾问型提示词（文学评测生成 / 事件抽取 / 一致性校验 / 因果精炼——后两个休眠）。

### [F-01] library_derive — 资料库半自动派生

- **状态**：活跃
- **优先级**：P1
- **节点**：`library_derive`
- **模板**：`config/prompts.yaml` → `library_derive`（version `2026-06-11.v1`，input_token_budget 3200）
- **路由（yaml 兜底，DB 优先）** `默认路由`：model=`gpt-5-mini`，temperature=0.1，max_output_tokens=1600，response_format=`json_object`
- **用途**：从归档章节正文提取新实体（地点/物品/势力/概念）与时间线事件候选，进待办确认（不直接入库）。
- **触发**：POST /api/v1/library/…/derive-from-chapter（LibraryDeriveService.derive_from_chapter）。
- **调用链**：`backend/src/novel_system/services/library_derive.py:121`（_extract）
- **输入组装**：task_prompt + JSON：chapter_text + known_names（已知名单，用于去重）。
- **输出契约**：entities[{name,kind,summary,aliases}] + timeline_events[{label,time_label,note}]；kind 枚举 location/item/faction/concept；服务内手工解析。（解析/校验：`backend/src/novel_system/services/library_derive.py:121`）
- **失败与降级**：LLMNodeError → 降级（空结果）。
- **优化注意**：查全 vs 保守的平衡：known_names 去重规则要涵盖别名/简称；弱模型上「漏报」多于误报，可要求先列候选再自筛。

**system_prompt（原样发送）**

```text
You extract story-bible candidates from finished Chinese novel chapter text.
Only surface NEW named locations, items, factions, concepts, and timeline events.
Skip anything already listed in known_names. Never invent facts not present in the text.
```

**task_prompt（运行时在其后追加指令与上下文）**

```text
Read chapter_text and return new entity candidates and timeline events.
entities: name, kind (location|item|faction|concept), one-sentence summary, aliases.
timeline_events: label, time_label (as written in text, may be empty), short note.
Be conservative: only clearly named, story-relevant items.
```

**structured_schema（wire 层 + 降级时内联；字段名冻结）**

```json
{
  "additionalProperties": false,
  "properties": {
    "entities": {
      "items": {
        "additionalProperties": true,
        "type": "object"
      },
      "type": "array"
    },
    "timeline_events": {
      "items": {
        "additionalProperties": true,
        "type": "object"
      },
      "type": "array"
    }
  },
  "required": [
    "entities",
    "timeline_events"
  ],
  "type": "object"
}
```

### [F-02] style_profile_extract — 旧版 7 特征风格画像

- **状态**：活跃（旧版抽象风格契约：rhythm/syntax/imagery/narrative_distance 等 7 特征——与 style_reference 子系统并存）
- **优先级**：P1
- **节点**：`style_profile_extract`
- **模板**：`config/prompts.yaml` → `style_profile_extract`（version `2026-04-18.v1`，input_token_budget 1800）
- **路由（yaml 兜底，DB 优先）** `默认路由`：model=`gpt-5-mini`，temperature=0.15，max_output_tokens=2200，response_format=`json_object`
- **用途**：从作者文本抽取 7 维抽象风格特征契约（Style Feature Contract 分节的来源之一）。
- **触发**：api/routes/style_profile.py → StyleProfileService.extract。
- **调用链**：`backend/src/novel_system/services/style_profile.py:196`（_extract_with_llm，经 PromptBuilder）
- **输入组装**：PromptBuilder(style_profile_extract)：作者样本文本。
- **输出契约**：_normalize_style_profile_payload 归一（另有确定性 YAML 解析路径 _parse_structured_profile）。（解析/校验：`backend/src/novel_system/services/style_profile.py:196`）
- **失败与降级**：LLMNodeExecutionError 上抛。
- **优化注意**：与 style_reference 16 维的分工：这里是「作者自己的风格」轻量画像——特征值要可直接进生成上下文（短、指令化）。

**system_prompt（原样发送）**

```text
You extract transferable prose style features from examples or approved style rules.
Do not identify or imitate a protected author; describe reusable craft-level traits only.
```

**task_prompt（运行时在其后追加指令与上下文）**

```text
Convert the supplied samples into a Style Feature Contract.
Use rhythm, syntax, imagery, narrative_distance, emotion_curve, paragraph_density, and dialogue_ratio.
Include calibration lines and banned moves only when explicitly supported by the input.
```

**structured_schema（wire 层 + 降级时内联；字段名冻结）**

```json
{
  "additionalProperties": false,
  "properties": {
    "banned_moves": {
      "items": {
        "type": "string"
      },
      "type": "array"
    },
    "calibration_lines": {
      "items": {
        "type": "string"
      },
      "type": "array"
    },
    "contract_version": {
      "type": "string"
    },
    "features": {
      "type": "object"
    }
  },
  "required": [
    "contract_version",
    "features"
  ],
  "type": "object"
}
```

### [F-03] author_structure_extract — 作者样稿结构抽取

- **状态**：活跃
- **优先级**：P1
- **节点**：`author_structure_extract`
- **模板**：`config/prompts.yaml` → `author_structure_extract`（version `2026-04-25.v1`，input_token_budget 2600）
- **路由（yaml 兜底，DB 优先）** `默认路由`：model=`gpt-5-mini`，temperature=0.2，max_output_tokens=2200，response_format=`json_object`
- **用途**：从作者上传样稿中抽取结构骨架（节拍/场景切分），用于对齐系统结构模型。
- **触发**：api/routes/author_drafts.py → extract_structure。
- **调用链**：`backend/src/novel_system/services/author_drafts.py:918`（extract_structure）
- **输入组装**：PromptBuilder(author_structure_extract)：样稿文本。
- **输出契约**：结构 payload 手工解析。（解析/校验：`backend/src/novel_system/services/author_drafts.py:918`）
- **失败与降级**：上抛/桩。
- **优化注意**：切分粒度定义要客观（以场景为最小单元、给切分判据），防止弱模型按段落乱切。

**system_prompt（原样发送）**

```text
You are a Chinese fiction dramaturg reading an author's free draft.
Extract only candidate structure understanding; do not write prose and do not claim the candidate has been applied.
Keep uncertain inferences explicit instead of turning ambiguous material into hard facts.
```

**task_prompt（运行时在其后追加指令与上下文）**

```text
Read the supplied author draft and metadata, then propose a writer-brief candidate for the target object.
Write all string values in Chinese while preserving English schema keys.
If the target is a scene, candidate_brief should use scene brief fields such as character_desire, obstacle, stakes,
secret_or_misunderstanding, subtext, irreversible_change, reader_question, choice_under_pressure, power_shift,
new_information, emotional_turn, image_anchor, and reader_aftertaste.
If the target is a chapter, candidate_brief should use chapter brief fields such as core_promise, plot_movement,
character_shift, chapter_question, ending_aftertaste, chapter_promise, escalation_path, relationship_delta,
reveal_or_reversal, payoff_target, and ending_question.
Do not include final prose, and do not overwrite existing cards.
```

**structured_schema（wire 层 + 降级时内联；字段名冻结）**

```json
{
  "additionalProperties": false,
  "properties": {
    "candidate_brief": {
      "type": "object"
    },
    "rationale": {
      "type": "string"
    },
    "uncertainty_notes": {
      "items": {
        "type": "string"
      },
      "type": "array"
    }
  },
  "required": [
    "candidate_brief",
    "uncertainty_notes",
    "rationale"
  ],
  "type": "object"
}
```

### [F-04] reference_sample_ranker — 参考样本排序（孤儿）

- **状态**：孤儿（旧 reference_learning 时代遗留：模板+路由在，无调用点；功能已被 style_reference 子系统取代）
- **优先级**：P2
- **节点**：`reference_sample_ranker`
- **模板**：`config/prompts.yaml` → `reference_sample_ranker`（version `2026-04-19.v1`，input_token_budget 2200）
- **路由（yaml 兜底，DB 优先）** `默认路由`：model=`gpt-5-mini`，temperature=0.1，max_output_tokens=1400，response_format=`json_object`
- **用途**：（遗留）参考风格样本排序。
- **触发**：无。
- **输入组装**：（未接线）。
- **输出契约**：（未接线）。
- **失败与降级**：—
- **优化注意**：P2：建议随遗留清理一并处置（删或归档），不投入优化轮次。

**system_prompt（原样发送）**

```text
You select representative samples from a reference book for craft-level analysis.
Cover prose rhythm, dialogue density, action or conflict, imagery, emotional turns, chapter movement, openings, and endings.
Do not request or preserve long verbatim passages.
```

**task_prompt（运行时在其后追加指令与上下文）**

```text
Rank the supplied segment metadata and short previews.
Return 5 to 8 segment ids with a reason, target dimension, and risk note for each.
If locale_hint is zh, write all returned string fields in Chinese (中文) while preserving the JSON schema keys.
```

**structured_schema（wire 层 + 降级时内联；字段名冻结）**

```json
{
  "additionalProperties": false,
  "properties": {
    "selections": {
      "items": {
        "additionalProperties": false,
        "properties": {
          "dimension": {
            "type": "string"
          },
          "reason": {
            "type": "string"
          },
          "risk_note": {
            "type": "string"
          },
          "segment_id": {
            "type": "string"
          }
        },
        "required": [
          "segment_id",
          "dimension",
          "reason",
          "risk_note"
        ],
        "type": "object"
      },
      "maxItems": 8,
      "minItems": 5,
      "type": "array"
    }
  },
  "required": [
    "selections"
  ],
  "type": "object"
}
```

### [F-05] reference_style_structure_extract — 参考风格结构抽取（孤儿）

- **状态**：孤儿（同上，被 style_ref_extract_* 家族取代）
- **优先级**：P2
- **节点**：`reference_style_structure_extract`
- **模板**：`config/prompts.yaml` → `reference_style_structure_extract`（version `2026-04-19.v1`，input_token_budget 2400）
- **路由（yaml 兜底，DB 优先）** `默认路由`：model=`gpt-5-mini`，temperature=0.15，max_output_tokens=2200，response_format=`json_object`
- **用途**：（遗留）参考书风格与结构抽取。
- **触发**：无。
- **输入组装**：（未接线）。
- **输出契约**：（未接线）。
- **失败与降级**：—
- **优化注意**：P2：同上。

**system_prompt（原样发送）**

```text
You extract reusable prose and narrative-structure techniques from approved reference snippets.
Keep only abstract craft guidance: rhythm, syntax, imagery, narrative distance, emotion curve, chapter pacing, suspense movement, conflict structure, and ending hooks.
Never copy protected expression, characters, settings, names, long sentences, or identifiable plot bridges.
```

**task_prompt（运行时在其后追加指令与上下文）**

```text
Analyze the supplied segment and return one review-ready finding.
The finding must be suitable for style_rule_set, style_observation, narrative_pattern, banned_rule_cluster, or calibration_candidate.
If locale_hint is zh, write all returned string fields in Chinese (中文) while preserving the JSON schema keys.
```

**structured_schema（wire 层 + 降级时内联；字段名冻结）**

```json
{
  "additionalProperties": false,
  "properties": {
    "banned_replication_rule": {
      "type": "string"
    },
    "confidence": {
      "type": "number"
    },
    "dimension": {
      "type": "string"
    },
    "item_type": {
      "type": "string"
    },
    "summary": {
      "type": "string"
    },
    "transferable_rule": {
      "type": "string"
    }
  },
  "required": [
    "item_type",
    "dimension",
    "summary",
    "transferable_rule",
    "banned_replication_rule"
  ],
  "type": "object"
}
```

### [F-06] reference_profile_synthesize — 参考画像合成（孤儿）

- **状态**：孤儿（同上，被 style_ref_synthesize_profile 取代；仅测试引用）
- **优先级**：P2
- **节点**：`reference_profile_synthesize`
- **模板**：`config/prompts.yaml` → `reference_profile_synthesize`（version `2026-04-19.v1`，input_token_budget 2600）
- **路由（yaml 兜底，DB 优先）** `默认路由`：model=`gpt-5`，temperature=0.2，max_output_tokens=3200，response_format=`json_object`
- **用途**：（遗留）参考风格画像合成。
- **触发**：无。
- **输入组装**：（未接线）。
- **输出契约**：（未接线）。
- **失败与降级**：—
- **优化注意**：P2：同上。

**system_prompt（原样发送）**

```text
You synthesize an independent reference-book profile from approved abstract findings.
The profile is not a writing sample cache. It must contain only transferable style features, narrative patterns, calibration guidance, and anti-copy rules.
```

**task_prompt（运行时在其后追加指令与上下文）**

```text
Combine the approved findings into a compact reference profile.
Separate prose features from narrative patterns and include clear forbidden replication rules.
If locale_hint is zh, write all returned string fields in Chinese (中文) while preserving the JSON schema keys.
```

**structured_schema（wire 层 + 降级时内联；字段名冻结）**

```json
{
  "additionalProperties": false,
  "properties": {
    "banned_replication_rules": {
      "items": {
        "type": "string"
      },
      "type": "array"
    },
    "calibration_guidance": {
      "items": {
        "type": "string"
      },
      "type": "array"
    },
    "narrative_patterns": {
      "items": {
        "type": "string"
      },
      "type": "array"
    },
    "profile_title": {
      "type": "string"
    },
    "style_features": {
      "items": {
        "type": "string"
      },
      "type": "array"
    }
  },
  "required": [
    "profile_title",
    "style_features",
    "narrative_patterns",
    "banned_replication_rules"
  ],
  "type": "object"
}
```

### [F-07] chapter_summary — 章节摘要（local 保留位）

- **状态**：本地保留（节点 status=reserved、requires_llm=False：摘要当前由确定性流程产出；模板留作未来接线）
- **优先级**：P2
- **节点**：`chapter_summary`
- **模板**：`config/prompts.yaml` → `chapter_summary`（version `2026-04-14.v1`，input_token_budget 1800）
- **路由（yaml 兜底，DB 优先）** `默认路由`：（models.yaml 无此路由）
- **用途**：（保留）章节摘要生成模板。
- **触发**：无 LLM 调用。
- **输入组装**：（未接线）。
- **输出契约**：（未接线）。
- **失败与降级**：—
- **优化注意**：P2：接线前不优化；若接线，注意摘要进 Chapter Summary 上下文分节，格式须与现有确定性摘要兼容。

**system_prompt（原样发送）**

```text
You are summarizing a completed chapter for future continuity use.
Keep it factual, compressed, and easy to retrieve later.
```

**task_prompt（运行时在其后追加指令与上下文）**

```text
Produce a compact chapter summary and carry-forward notes from the supplied bundle context.
```

**structured_schema（wire 层 + 降级时内联；字段名冻结）**

```json
{
  "additionalProperties": false,
  "properties": {
    "carry_forward": {
      "items": {
        "type": "string"
      },
      "type": "array"
    },
    "summary": {
      "type": "string"
    }
  },
  "required": [
    "summary",
    "carry_forward"
  ],
  "type": "object"
}
```

### [F-08] continuity_compression — 连续性压缩（local 保留位）

- **状态**：本地保留（同上：上下文压缩当前是确定性策略，模板未接线）
- **优先级**：P2
- **节点**：`continuity_compression`
- **模板**：`config/prompts.yaml` → `continuity_compression`（version `2026-04-14.v1`，input_token_budget 1400）
- **路由（yaml 兜底，DB 优先）** `默认路由`：（models.yaml 无此路由）
- **用途**：（保留）连续性/记忆上下文压缩模板。
- **触发**：无 LLM 调用。
- **输入组装**：（未接线）。
- **输出契约**：（未接线）。
- **失败与降级**：—
- **优化注意**：P2：同上。

**system_prompt（原样发送）**

```text
You are compressing continuity context for downstream drafting.
Preserve hard facts, remove redundancy, and surface any split-scene recommendation clearly.
```

**task_prompt（运行时在其后追加指令与上下文）**

```text
Compress the continuity payload while keeping essential carry-forward constraints intact.
```

**structured_schema（wire 层 + 降级时内联；字段名冻结）**

```json
{
  "additionalProperties": false,
  "properties": {
    "compressed_context": {
      "type": "string"
    },
    "dropped_sections": {
      "items": {
        "type": "string"
      },
      "type": "array"
    },
    "split_scene_recommended": {
      "type": "boolean"
    }
  },
  "required": [
    "compressed_context",
    "split_scene_recommended"
  ],
  "type": "object"
}
```

### [F-09] literary_eval_live — 文学评测 live 生成（Python 内联提示词）

- **状态**：活跃（内联：注册表 template_name 指向不存在的 yaml 键；提示词在 literary_eval.py）
- **优先级**：P1
- **节点**：`literary_eval_live`
- **内联提示词**：`backend/src/novel_system/services/literary_eval.py`（不受 DB 快照覆盖）
- **路由（yaml 兜底，DB 优先）** `默认路由`：model=`gpt-5-mini`，temperature=0.2，max_output_tokens=2400，response_format=`json_object`
- **用途**：文学质量评测的 live 通道：按评测用例（config/evals/literary_small.yaml）生成候选场景，交给规则引擎打分（LLM 不当评委）。
- **触发**：api/routes/literary_eval.py → LiteraryEvalRunner.run（live 模式）；报告写 NOVEL_SYSTEM_LITERARY_EVAL_REPORT_PATH。
- **调用链**：`backend/src/novel_system/services/literary_eval.py:209`（LiveLiteraryEvalGenerator.__call__）
- **输入组装**：内联 system_prompt + _case_user_prompt（用例 prompt + 各类 cues/banned terms + 长度带）。
- **输出契约**：{scene_text}（缺失 → ValueError）。（解析/校验：`backend/src/novel_system/services/literary_eval.py:211`）
- **失败与降级**：异常上抛（评测路径，可容忍失败）。
- **优化注意**：评测生成器的提示词改动会整体抬/压分数基线——若要改，须重跑基线对照并记录；用例本身的 prompt 字段勿动（§10）。

**system_prompt（函数内联，_request）**

```text
You are generating original fiction for a style-feature evaluation. Do not imitate a living or named author's protected expression. Return JSON with one field: scene_text.
```

**user_prompt 骨架（_case_user_prompt 动态拼装，逐行 f-string）**

```text
Case ID: {case.case_id}
Title: {case.title}

## Writing Task
{case.prompt}

## Evaluation Constraints
required terms: …
style cues: …
character contradiction cues: …
dialogue edge cues: …
image necessity cues: …
ending drive cues: …
choice pressure cues: …
image variety cues: …
banned terms: …
model voice banned terms: …
expository dialogue banned terms: …
summary ending banned terms: …
length band: {min_chars}-{max_chars} characters

Return JSON exactly like: {"scene_text": "..."}
```

> 评测 live 生成：LLM 只负责按评测用例写场景，打分是规则引擎（literary_quality 21 维），不是 LLM 评委。

### [F-10] narrative_event_extract — 成稿散文事件抽取（Python 内联，借 extraction 路由）

- **状态**：活跃·可选（NOVEL_SYSTEM_LLM_EVENT_EXTRACTION_ENABLED=true 时启用；别名路由 → extraction 节点。注意：extraction 节点注册的 template_name="extraction" 无 yaml 模板——该节点的实际提示词即本内联提示词）
- **优先级**：P1
- **节点**：`extraction`
- **run_task 任务名**：`narrative_event_extract`
- **内联提示词**：`backend/src/novel_system/services/prose_event_extractor.py`（不受 DB 快照覆盖）
- **路由（yaml 兜底，DB 优先）** `默认路由`：model=`gpt-5-mini`，temperature=0.1，max_output_tokens=1200，response_format=`json_object`
- **用途**：§2 事件溯源补全：从「实际生成的散文」抽取改变状态的硬事实（伤残/位置/得知/关系），advisory 写入 NarrativeEvent。
- **触发**：场景运行管线收尾（orchestrator 接线 extract_events_from_prose；opt-in）。
- **调用链**：`backend/src/novel_system/services/prose_event_extractor.py:87`（extract_events_from_prose → run_task）
- **输入组装**：EXTRACTOR_SYSTEM_PROMPT + "## Scene prose" + 正文前 6000 字。
- **输出契约**：{events[{event_type,entity_id,fact_key,fact_value,evidence}]}；event_type 白名单 4 值，越界丢弃；fact_value ≤200 字。（解析/校验：`backend/src/novel_system/services/prose_event_extractor.py:60`）
- **失败与降级**：任何异常/未启用 → []（advisory，永不阻塞）。
- **优化注意**：弱模型抽取薄的另一现场：可加「先逐段扫描列候选、再按耐久性筛选」两步式指令；「宁缺毋滥」保留但给最低敏感度示例（断肢/得知秘密必须报）。

**system_prompt（模块常量）**（`prose_event_extractor.EXTRACTOR_SYSTEM_PROMPT`）

```text
You are a precise continuity fact-extractor for a long-form novel.
Read the scene prose and extract ONLY concrete, on-the-page facts that CHANGE STATE —
not mood, not interpretation, not transient action.

Event types (use exactly one of these strings):
- character_state: a durable change to a character (injury, item gained/lost, a
  condition that persists beyond this scene)
- location_change: a character is now at a specific place
- character_learns: a character gains specific knowledge/information
- relation_change: the relationship between two characters shifts

Respond with JSON only, no prose:
{
  "events": [
    {
      "event_type": "character_state|location_change|character_learns|relation_change",
      "entity_id": "<character name/id exactly as written>",
      "fact_key": "<short snake_case key, e.g. injury / location / learned / stance_toward_X>",
      "fact_value": "<concise factual value>",
      "evidence": "<short quote from the prose supporting this fact>"
    }
  ]
}

Rules:
- Only facts literally supported by the prose. When unsure, omit it.
- Prefer durable facts (matter in later scenes) over momentary action.
- fact_value under 200 chars. Return {"events": []} if nothing qualifies.
```

> task_prompt = "## Scene prose\n\n" + 正文前 6000 字。事件类型白名单 4 种（character_state / location_change / character_learns / relation_change），越界条目直接丢弃；entity_id / fact_key / fact_value 任一为空即丢弃。

### [F-11] consistency_extract — 连续性 LLM 校验（Python 内联，休眠）

- **状态**：休眠（models.yaml 无路由、注册表无节点，生产不可达——仅测试注入 runner 可跑；QC 用的是确定性 check_consistency）
- **优先级**：P2
- **run_task 任务名**：`consistency_extract`
- **内联提示词**：`backend/src/novel_system/services/narrative_event_log.py`（不受 DB 快照覆盖）
- **路由（yaml 兜底，DB 优先）** `默认路由`：（models.yaml 无此路由）
- **用途**：§15 混合一致性的 advisory LLM 层：判断散文是否与已确立硬事实（生死/位置/断肢/持有物/外貌/能力）矛盾。
- **触发**：check_consistency_llm（当前无生产调用方）。
- **调用链**：`backend/src/novel_system/services/narrative_event_log.py:501`（check_consistency_llm → run_task）
- **输入组装**：_LLM_CONSISTENCY_TASK_TEMPLATE.format(facts_block, text)。
- **输出契约**：{violations[{entity,fact_key,expected,actual,evidence}]}；容错解析（```json 围栏/前后杂文均可）；结果标 source="llm_flag" 仅 advisory。（解析/校验：`backend/src/novel_system/services/narrative_event_log.py:863`）
- **失败与降级**：任何异常 → 仅关键词校验结果。
- **优化注意**：P2：接线（加路由/注册或别名）之前优化无收益；提示词本身已相当克制，接线后再按误报率调。

**system_prompt（模块常量）**（`narrative_event_log._LLM_CONSISTENCY_SYSTEM_PROMPT`）

```text
你是连续性校验器。只做一件事：判断给定散文是否与【已确立的硬事实】矛盾。硬事实指角色生死、位置、身体状态（如断肢）、持有物、外貌、能力。规则：(1) 只报矛盾，不报风格问题；(2) 绝不臆造事实清单之外的内容；(3) 不确定时不报；(4) 严格输出 JSON，无任何额外文字。JSON 格式：{"violations": [{"entity": "角色名", "fact_key": "字段", "expected": "事实值", "actual": "文中矛盾表现", "evidence": "原文片段"}]}
```

**task_prompt 模板（{facts_block} / {text} 占位符必须保留）**（`narrative_event_log._LLM_CONSISTENCY_TASK_TEMPLATE`）

```text
【已确立的硬事实】
{facts_block}

【待校验散文】
{text}

请仅输出矛盾项的 JSON。若无矛盾，输出 {{"violations": []}}。
```

> 休眠：models.yaml 无此路由、注册表无此节点，生产不可达（仅测试注入 runner）。接线前优化收益为零。

### [F-12] causal_skeleton_refine — 逆向因果骨架精炼（Python 内联，休眠）

- **状态**：休眠（同 consistency_extract：无路由无注册，仅测试可达）
- **优先级**：P2
- **run_task 任务名**：`causal_skeleton_refine`
- **内联提示词**：`backend/src/novel_system/services/reverse_causal_skeleton.py`（不受 DB 快照覆盖）
- **路由（yaml 兜底，DB 优先）** `默认路由`：（models.yaml 无此路由）
- **用途**：§4 逆向因果骨架的 LLM 精炼：找出因果链缺口并提出最小必要前置事件（advisory，不改写骨架）。
- **触发**：refine_skeleton_with_llm（当前无生产调用方）。
- **调用链**：`backend/src/novel_system/services/reverse_causal_skeleton.py:180`（refine_skeleton_with_llm → run_task）
- **输入组装**：_REFINE_TASK_TEMPLATE.format(controlling_idea, ending_state, chain_block)。
- **输出契约**：{gaps[{after_step,missing_premise,why}]}；_parse_causal_gaps 容错解析。（解析/校验：`backend/src/novel_system/services/reverse_causal_skeleton.py:189`）
- **失败与降级**：任何异常 → []。
- **优化注意**：P2：同上，接线前不投入。

**system_prompt（模块常量）**（`reverse_causal_skeleton._REFINE_SYSTEM_PROMPT`）

```text
你是因果结构编辑。给定一条从终局反推的因果链，你的任务是找出链条中的因果缺口——即某一步要可信，前一步却没有为它提供充分的前提。对每个缺口，提出需要在两步之间补充的、最小且必要的前置事件。规则：(1) 只补因果必需的前置，不扩写情节；(2) 不臆造与控制性理念无关的内容；(3) 严格输出 JSON，无额外文字。JSON 格式：{"gaps": [{"after_step": 整数, "missing_premise": "需要补充的前置事件", "why": "为什么没有它下一步不可信"}]}
```

**task_prompt 模板（{controlling_idea} / {ending_state} / {chain_block} 占位符必须保留）**（`reverse_causal_skeleton._REFINE_TASK_TEMPLATE`）

```text
控制性理念：{controlling_idea}
终局：{ending_state}

当前因果链（从开端到终局）：
{chain_block}

请找出因果缺口并仅输出 JSON。若链条因果自洽，输出 {{"gaps": []}}。
```

> 休眠：同 consistency_extract，无路由无注册，生产不可达。

## §9 运行时拼接片段附录

以下内容由代码**自动追加**到模板之外——优化模板时**不要**把它们复写进 system_prompt/task_prompt；若要改这些片段本身，需改对应源码。

### 角色连续性指令（追加到 5 个语言锁模板的 user_prompt 尾部）

- 位置：`backend/src/novel_system/services/prompt_builder.py`
- 机制：PromptBuilder 对 neutral_draft / style_draft / long_form_continuation / hard_qc / soft_qc 的 task_prompt 追加语言锁后再拼本指令。

**指令原文**

```text
Preserve character identity and pronoun continuity across the scene. Do not change a character's gender, role, or name cues from the scene card, POV voice, relation digest, previous scene memory, or source draft. When pronouns are ambiguous, repeat the character name.
```

### 语言锁指令（_append_runtime_template_instruction，按模板名追加）

- 位置：`backend/src/novel_system/services/prompt_builder.py`
- 机制：5 个模板各有一条：防止中文场景被写成/译成英文、QC 输出跟随草稿语言并保护中文人名。函数内 dict，逐字如下。

**neutral_draft**

```text
Write prose in the same language as the chapter goal and scene card. If the chapter goal or scene card contains Chinese text, scene_text must be Chinese prose; do not translate Chinese settings, beats, or required text into English.
```

**style_draft**

```text
Preserve the source draft language; do not translate the scene while styling it. If the draft or scene card is Chinese, scene_text must remain Chinese prose.
```

**long_form_continuation**

```text
Preserve the source draft language; do not translate the scene while continuing it. If the draft or scene card is Chinese, scene_text must remain Chinese prose.
```

**hard_qc / soft_qc**

```text
If the draft under review is Chinese, write issue messages and rewrite_brief in Chinese; preserve Chinese character names exactly and do not romanize or translate them.
```

### JSON/schema 收尾指令（_append_schema_instruction + _enum_instruction，追加到所有 PromptBuilder 模板）

- 位置：`backend/src/novel_system/services/prompt_builder.py`
- 机制：user_prompt 末尾自动追加：required 键列举 + 枚举取值列举 + 「只返回合法 JSON」。模板 task_prompt 里不必重复这些话。

**固定句式**

```text
Required top-level JSON keys: <required...>.
Allowed JSON enum values: <key> must be one of: <values...>.
Return only valid JSON. Do not wrap it in markdown fences.
```

### hard_qc / soft_qc schema 运行时对齐（_align_schema_with_runtime_contract）

- 位置：`backend/src/novel_system/services/prompt_builder.py`
- 机制：构建时强制合并进 schema（属冻结契约，模板里的 structured_schema 改了也会被覆盖回来）：
- hard_qc：补 rewrite_brief（string[]，必填）；resolution_code 枚举 = hard_pass / hard_fail_partial / hard_fail_full / hard_block_human；next_action 枚举 = pass / partial_rewrite / full_rewrite / human_review_required。
- soft_qc：resolution_code 枚举 = soft_pass / soft_patch / soft_waive / soft_block_human；next_action 枚举 = pass / patch / pass_with_notes / human_review_required。

**代码锚点**

```text
（见 prompt_builder.py `_align_schema_with_runtime_contract`）
```

### 上下文分节标签（context_budget.SECTION_SPECS，PromptBuilder 类模板的 user_prompt 主体）

- 位置：`backend/src/novel_system/services/context_budget.py`
- 机制：bundle 快照被序列化为带英文标签的上下文分节追加到 user_prompt（受 token 预算与 config/allowlists.yaml 治理，超预算按连续性策略压缩/丢弃）。模板 task_prompt 里引用输入时用这些分节名（如 chapter_goal / scene_card / scene_blueprint）即可，标签清单见下。

**分节 (name → label) 清单**（共 38 个分节，按注入顺序）

- `chapter_goal` → “Chapter Goal”
- `scene_card` → “Scene Card”
- `chapter_writer_brief` → “Chapter Writer Brief”
- `scene_writer_brief` → “Scene Writer Brief”
- `scene_blueprint` → “Scene Literary Blueprint”
- `character_pressure` → “Character Pressure Blueprint”
- `chapter_story_architecture` → “Chapter Story Architecture”
- `character_contract` → “Character Continuity Contract”
- `narrative_state` → “Authoritative Character State (Event Log)”
- `information_asymmetry` → “Information Asymmetry (who knows what)”
- `tension_pacing` → “Tension & Pacing Constraint”
- `theme_expression_budget` → “Theme Anchor & Expression Budget”
- `pov_voice` → “POV Voice”
- `style_profile` → “Style Feature Contract”
- `author_preference_profile` → “Author Preference Profile”
- `literary_freshness_budget` → “Literary Freshness Budget”
- `longform_structure_guidance` → “Longform Structure Guidance”
- `style_rules` → “Style Rules”
- `banned_rules` → “Banned Rules”
- `open_foreshadow` → “Open Foreshadow”
- `foreshadow_directives` → “Foreshadow Lifecycle Directives”
- `chapter_transition_buffer` → “Chapter Transition Buffer”
- `pov_voice_coloring` → “POV Voice Coloring”
- `character_psychology` → “Character Psychology Model”
- `voice_fingerprint` → “Voice Fingerprint”
- `relationship_matrix` → “Relationship Dynamics Matrix”
- `character_arc_weights` → “Character Decision Weights (arc progression)”
- `similar_scene_context` → “Similar Scene Context”
- `style_observations` → “Style Observations”
- `narrative_patterns` → “Narrative Patterns”
- `calibration_lines` → “Calibration Lines”
- `relation_digest` → “Relation Digest”
- `world_rules` → “World Rules”
- `scene_memory_digest` → “Previous Scene Memory”
- `scene_summary` → “Scene Summary”
- `chapter_summary` → “Chapter Summary”
- `volume_summary` → “Volume Summary (atmosphere only)”
- `avoid_recent_expressions` → “Avoid Recent Expressions”

### 低分散重试的发散化前缀（§6.3，Best-of-N 候选相似度过高时加到 system_prompt 头部）

- 位置：`backend/src/novel_system/services/scene_generation.py`
- 机制：style 生成候选分散度过低时重试，随附本前缀或风格强调轮换前缀（extra_system_prefix）。

**发散化前缀**

```text
[DIVERSIFICATION] 前一轮生成的候选在表达上高度相似。请刻意尝试不同的叙述入口：
换一种感官开场（如果之前用了视觉，试听觉或触觉）、
换一种时间结构（如果之前是顺叙，试倒叙或插叙的片段）、
换一种节奏（如果之前是长句铺陈，试短句切入）。
保持场景spec的所有结构要求不变，只改变'怎么去'。
```

**风格强调轮换前缀（2 条）**

（第 1 条）

```text
[风格强调·禁忌优先] 本次生成请特别关注参考风格中的禁忌模式——绝对避开被标记为禁忌的表达方式,并让'不做什么'成为本次风格选择的首要约束。
```

（第 2 条）

```text
[风格强调·节奏指标优先] 本次生成请严格对齐风格参考中的硬指标锚点——句长分布、感官词频率、对话比例等量化基线。让数字说话,节奏先行。
```

### 作者改写指令附加段（author_note_instruction，FE-ALIGN G3）

- 位置：`backend/src/novel_system/services/scene_generation.py`
- 机制：前端场景运行请求里的 author_note（≤500 字自由文本）被格式化为附加指令拼入风格生成 user_prompt；空 note 无影响。动态函数，无固定文本。

**代码锚点**

```text
（见 scene_generation.py `author_note_instruction`）
```

### [STYLE_REFERENCE] 风格注入块 + 反抄袭红线（injection.py 组装，无 LLM）

- 位置：`config/style_reference/anti_plagiarism_template.txt`
- 机制：绑定了 ready Profile 的项目在场景生成时，system_prompt 会被注入确定性组装的 [STYLE_REFERENCE] 块（A=系统提示 / B=few-shot / C=RAG 三策略，按 style_intensity 与预算裁剪），其中反抄袭红线段永不截断、{banned_terms_list} 占位符运行时填充。红线模板原文如下。

**`config/style_reference/anti_plagiarism_template.txt` 原文**

```text
## 严格禁止
- 复用或微改任何参考样本中的完整句子
- 直接搬运超过 5 个连续字符的独特表达(常用词、人名、地名除外)
- 参考样本中的意象(如承载象征意义的具体物象)可重复使用,
  但承载这些意象的句子必须完全重写
- 若你不确定某个表达是否来自参考样本,默认认为是,改写它

此外,以下专有名词严禁出现在生成文本中(可能引发版权或角色混淆):
{banned_terms_list}
```

### 降级时的 schema 内联提示（llm_client._inline_schema_into_messages）

- 位置：`backend/src/novel_system/services/llm_client.py`
- 机制：当 wire 层 json_schema 被中转拒绝而降级为 json_object/无格式时，schema 会以下述中文提示内联进 system prompt——所以 structured_schema 本身要精简、自描述（字段名即文档）。

**内联提示原文**

```text
输出必须是**单个 JSON 对象**,且严格符合以下 JSON Schema(字段名一字不差,不要输出 Schema 之外的字段或任何非 JSON 文本):
<schema JSON>
```

### scene_generation.JSON_SCHEMA_INSTRUCTION（风格 user_prompt 收尾句）

- 位置：`backend/src/novel_system/services/scene_generation.py`
- 机制：风格生成 user_prompt 组装时使用的固定收尾句。

**原文**

```text
Return JSON that matches the structured schema exactly.
```

## §10 评测集提示词附录（勿动）

`config/evals/literary_small.yaml` 共 9 个用例——`literary_eval_live` 通道会把用例的 `prompt` 嵌入 user_prompt 生成候选场景，再由**规则引擎**打分。改这些 prompt 会破坏历史评测可比性，**列出仅为完整性**。

### 用例 `reunion_pressure_gate` Reunion pressure at the gate

```text
Write a short scene in which two estranged leads meet at a city gate. Keep the prose tense, gesture-led, and concrete. A letter must change hands, but no one should explain the whole backstory.
```

### 用例 `archive_room_suspicion` Archive room suspicion

```text
Write a compact scene in an archive room where a character discovers a missing page. Use tactile imagery and short paragraph turns. The emotion should move from routine attention to suspicion.
```

### 用例 `dockside_cliffhanger` Dockside cliffhanger

```text
Write the last beat of a scene at a dock. The scene should end on a hard visual hook rather than summary. Use sparse dialogue and a clear emotional turn toward urgency.
```

### 用例 `chinese_archive_choice` 中文档案室选择压力

```text
写一个中文原创短场景：修复师在档案室听到录音，必须决定是否公开证据。 场景要有反问、沉默和动作，不要解释完整前史。
```

### 用例 `chinese_family_hook` 中文家门口关系钩子

```text
写一个中文原创短场景：多年不见的姐弟在旧屋门口交出钥匙。 对白要克制但有刺，物件必须改变关系，结尾要推动下一章。
```

### 用例 `chinese_strong_plot_choice_cost` 中文强情节选择代价

```text
写一个中文原创短场景：档案修复师拿到能公开真相的录音， 但公开会暴露幸存者位置。必须出现选择、代价和一个推动下一场的硬动作。 不要用总结句解释主题。
```

### 用例 `chinese_strong_plot_ending_drive` 中文强情节结尾驱动

```text
写一个中文原创短场景结尾：人物必须延后公开证据以保护一个人， 结尾用视觉动作推动下一章。对白要短，不能解释完整前史。
```

### 用例 `chinese_anti_template_repeated_gesture` 中文反模板重复动作闸门

```text
写一个中文原创短场景：调查员拿到公开令和证据袋，但公开会暴露幸存者地址。 必须让人物在动作中做选择，避免“低头看着、沉默了片刻、她知道”等模板化承接。
```

### 用例 `chinese_anti_template_cross_scene_reuse` 中文跨场景复用闸门

```text
写一个中文原创短场景：旧码头交易录音，人物必须在保护亲人与交出证据之间取舍。 不要复用“盐霜、低鸣、手指停顿、沉默了片刻”等连续场景里常见的意象和动作。
```

## §11 遗留与待清理（供系统作者决策；Sonnet 5 默认跳过）

1. **活跃孤儿节点（7 个）**：`reference_profile_synthesize`、`reference_sample_ranker`、`reference_style_structure_extract`、`scene_quality_contract`、`writer_chapter_diagnosis`、`writer_reference_application_review`、`writer_scene_diagnosis` —— 有模板/路由/注册但无调用点（其中两个 diagnosis 基节点是镜头模板载体属正常设计；三个 reference_* 是被 style_reference 子系统取代的遗留；`scene_quality_contract` 无模板、服务实际走 scene_auto_rewrite；`writer_reference_application_review` 是未接线的预留功能）。
2. **休眠 ad-hoc 任务（2 个）**：`consistency_extract`、`causal_skeleton_refine` —— 提示词写好、无路由无注册，生产不可达；接线需在 models.yaml/节点注册或别名表补路由。
3. **`DRAFTING_TEMPLATE_NAMES` 里的陈旧名（无对应模板，仅分类集合残留）**：`near_final_rewrite`、`snowflake_generate_character_lineup`、`snowflake_generate_character_plan`、`snowflake_generate_logline`、`snowflake_generate_one_paragraph`、`snowflake_generate_plot_beats`、`snowflake_generate_scene_plan`。
4. **疑似废弃文件**：`config/style_reference/prompts/style_ref_paragraph_classify.txt` —— 无任何代码加载（现行分类器用 yaml 的 anchor/bulk 双模板）。原文附下，供比对后删除或归档：

```text
你是中文叙事段落分类专家。给定一批段落,逐段判断其类型,从下列 8 类中**严格选择一个**:

1. dialogue          — 对话:含明确的引号(""「」'')或"……说""……道"等说话标识
2. narration         — 叙述:作者全知视角推进剧情的散文体段落,不含对话引号
3. psychology        — 心理:角色内心活动、回忆、内省;典型标记词如"想着""觉得""暗忖""恍惚"
4. description_env   — 环境描写:刻画场所、天气、自然或物件;典型如"屋外""山脚下""暮色""路边的"
5. description_char  — 人物描写:刻画外貌、衣着、神态;典型如"脸色""眼神""穿着""身上"
6. action            — 动作:角色明确执行动作的连续动词;典型如"走""转身""扑""握""推开"
7. transition        — 过渡:章节/场景切换句、时间跳跃句;通常较短(<60 字),如"几日后""又过了一会儿"
8. flashback         — 闪回:对过去事件的追述;典型标记词如"记得""那年""从前""昔日""旧时"

判断原则:
- 一段只能归一类。若多种特征并存,**以主导特征为准**(占比 >50% 的内容)。
- 含直接引语优先归 dialogue;否则按主导内容分类。
- 短段(<30 字)且无对话/心理标识,默认 transition。
- 与上下文的关系不参与判断,只看当前段本身。

输出严格的 JSON,格式:
{
  "classifications": [
    {"paragraph_index": 0, "paragraph_type": "narration", "confidence": "high"},
    {"paragraph_index": 1, "paragraph_type": "dialogue", "confidence": "high"},
    ...
  ]
}

confidence 三档:high / medium / low。若一段同时具备 2 类强特征,降为 medium;含糊不清的 low。
```

5. **DB prompts 快照对账**：若系统曾激活 prompts 快照，`config/prompts.yaml` 与运行时真源会分叉——回写优化结果前先 `GET /api/v1/system-config/export/prompts` 对账（本文档 §1 已注明本次生成用的来源）。

## §12 完整性自审计

- 生成命令：`cd backend && python -m novel_system.tools.export_prompt_handoff`（2026-07-04）
- 模板来源：config/prompts.yaml（无生效的 DB prompts 快照）
- prompts 模板：**54** 个，全部出现在 §3–§8（脚本断言双向覆盖）
- 注册节点：**60** 个，全部出现在 §2 总表；未进单元的仅 `archive`、`chapter_aggregate`、`scene_quality_contract`（无提示词，§11 说明）
- models.yaml task_routing：**59** 键，全部为注册节点或已说明的别名（`stylize`）
- 调用点：**38** 处，锚点全部在当前源码命中（行号为生成时解析）
- Python 内联提示词：**6** 组（AST 字面量提取 + 函数内联逐字拷贝经源码包含性断言）
- 运行时片段：**10** 组；评测用例：**9** 个
- 负面证据（无 SDK 直连 / 无 embedding API / 前端无提示词 / RAG 注入无 LLM 等）见 §2 末尾

以上任一数字与源码漂移时，生成脚本会以非零退出并列出差异——重新盘点后更新 `novel_system/tools/prompt_handoff_annotations.py` 再生成。

