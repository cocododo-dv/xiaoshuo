# Wave 2 实施计划：QC 分级和可靠成稿模式

> 设计依据：`docs/superpowers/specs/2026-07-10-ai-novel-outcome-governance-design.md` v1.1 §4.2/§4.4/§5.4/§6.1 + Wave 2 条目
>
> 纪律：不新增外围文学模块；不修改与本 Wave 无关的代码；测试先行（先红后绿）；
> Wave 1 完成门已过（提交 9e104b2；2026-07-11 本机复跑定向 30 项 + vitest 73 项通过，全量回归复跑通过）。
>
> 完成门：**使用当前真实模型重复旧三章场景时，至少能交付三份可编辑正文；只有真实 Q0/Q1 能阻断归档。**

## 1. 现状事实表（2026-07-11 逐项核实）

| # | 事实 | 位置 |
|---|---|---|
| F1 | HardQcEngine 按 LLM `next_action` 直接分支：full_rewrite / partial_rewrite / human_review_required 均断头（确定性 sanity 只做反向剔除，不做正向复核）——**LLM 单独判断即可硬阻断**，违反 §5.4 提案—复核纪律 | `qc_engine.py:748,794-813` |
| F2 | 确定性 gate `_deterministic_quality_issues` 混合 Q1 级（pronoun drift、event_log keyword violation）与 Q2/Q3 级（theme low、tension low、mechanical listing）；**任一存在**都把 pass 强制成 partial_rewrite（hard）/ patch（soft） | `qc_engine.py:374-533,927-964,1574-1613` |
| F3 | SoftQcEngine：branch=human_review_required（blocking 词表命中或 LLM 主动要求）→ 建阻断事件 + scene_status=human_review_required + 清 current_style/final 指针 → orchestrator 早退无 FinalScene——**G-03 主体** | `qc_engine.py:1453-1505`、`orchestrator.py:249-268` |
| F4 | 阻断词表 `BLOCKING_QC_ISSUE_KEYS` 中 `instruction_residue`/`scene_conflict_missing`/`source_leak_risk` **没有任何确定性生产者**（全仓唯一出处是词表本身），只能来自软 QC LLM 自由输出；`character_pronoun_drift`/`mechanical_required_beat_listing` 有确定性检测器 | `character_continuity.py:9-15,63,102` |
| F5 | 硬/软 QC 执行失败（LLM 不可用/超时/payload 无效/continuity 超预算）一律 fallback 到 human_review_required 硬阻断——违反 §5.4「QC 超时、模型不可用不撤销已有正文」 | `qc_engine.py:665-732,1357-1424` |
| F6 | near-final：`requires_human_review`（仅 LLM 提案或执行失败可产生）→ human_review_required 断头；`revision_required` 二评仍 fail → near_final_revision_required 断头；两者都不产生 FinalScene | `orchestrator.py:277-315`、`near_final.py:814-843,1016-1036` |
| F7 | near-final LLM 执行失败 payload 硬编码 `failure_class=fact_blocker + requires_human_review=True` → 阻断 | `near_final.py:1016-1036` |
| F8 | style validation gate：partial → rewrite_partial 断头；fail/plagiarism → human_review_required。plagiarism 是确定性 n-gram（Q0 合理）；fail/partial 是量化容差+语义评审（Q2/Q3 级） | `qc_engine.py:751-775` |
| F9 | 自动修订现状 = soft patch ≤1（`soft_patch_count>=1` → block/waive）+ near-final rewrite ≤1 = 总 2 次，与 §5.4 上限一致；但达上限的出路是断头而非「交付最佳稿」 | `qc_engine.py:1431-1443`、`orchestrator.py:277-292` |
| F10 | `QcReport.issues_json` 现存 issue 仅 issue_key/message(+自由字段)，无 §6.1 的 quality_level/blocking/verified_by；`QCIssue` extra="allow"，扩展字段可存活验证 | `contracts/qc.py`、`qc_engine.py:1671-1708` |
| F11 | orchestrator 四处早退 payload 均不带 author_state / latest_valid_draft_row_id（Wave 2 项 5 缺口）；`_clear_downstream_outputs` 清 current_* 但 Wave 1 的 latest_valid 指针保留 | `orchestrator.py:126-143,249-268,294-346`、`qc_engine.py:1200,1768` |
| F12 | run/full 与 run/jobs 均不接受 run_policy；`SceneRunState` 无 run_policy 列（**列属 Wave 3 迁移**，本 Wave 只做请求级参数，不动模型不写迁移） | `routes/scenes.py:156-172`、`scene_run_jobs.py:37-59,248` |
| F13 | adopt-current 已有确定性来源安全 Q0 守卫；对 hard_blocked（verified Q1 未解决）不拒——author_state 投影的 can_archive=False 未被端点强制 | `routes/scenes.py:680-821` |
| F14 | author_state 投影的 blocking_findings/quality_warnings 只从 scene_status 粗粒度透出（Wave 1 计划 D1 预告本 Wave 精化） | `services/author_state.py:85-96` |
| F15 | FE：`scnRun` 有产出一律「待裁决 ready」，无 hard_blocked/quality_warning 区分；`onArchive`（ws-scene.jsx DecisionBar）不看 can_archive；展示层在 ws-scene.jsx（设计文件列表列的 ws-scene-run.jsx 是引擎层，两者同属一个改动边界） | `ws-scene-run.jsx:232-319`、`ws-scene.jsx:493-507` |
| F16 | ws-quality.jsx 是 21 维纯诊断台（只读 literary-quality API，不参与阻断）——已符合 Q3「只进诊断」语义，预计零/极小改动 | `ws-quality.jsx` |

## 2. 架构决策

- **D1 · 统一分类器**（新 `services/quality_classifier.py`，纯函数可测）：
  - 注册表 `ISSUE_KEY_POLICY`：issue_key → (确定性复核通过时的级别, 复核器 id, 未复核时的级别)。盘点映射：
    - **Q0**（复核后）：`source_leak_risk`（复核器=scan_source_safety 重扫）、`style_plagiarism`（确定性 n-gram，由 style gate verdict 映射）
    - **Q1**（复核后）：`character_pronoun_drift`（确定性检测器产出即 verified）、`event_log_consistency_violation`（keyword 源）、`forbidden_text`（`_contains_forbidden_term` 证实）、`missing_required_text`/`missing_hard_constraint`（must_include 确定性缺失证实）
    - **Q2**（默认，含一切未知 key 与未复核的 LLM 提案）：`unsupported_event`、`scene_conflict_missing`、`instruction_residue`、`mechanical_required_beat_listing`、`character_role_inconsistency`、`duplicate_text`、`event_log_consistency_llm_flag`、`theme_relevance_warning`、QC 执行失败类（`*_execution_failed`/`invalid_*_payload`/`continuity_budget_exceeded`）、near-final `scene_structure_failure`
    - **Q3**：`style_compliance`/`style_rule_violation`/`style_profile_drift`/`style_validation_*`、`tension_*`、`character_pronoun_ambiguity`/`_continuity`、near-final `prose_model_voice`
  - `classify_issues(issues, *, verified_keys)` 输出 §6.1 完整结构：`quality_level`、`blocking`（由级别派生：仅 Q0/Q1 为 true，强制不可自由组合）、`verified_by`（Q0/Q1 必填=复核器 id）、`authority_ref`/`evidence_spans`/`confidence`/`recommended_action`/`source`。未经确定性复核的 Q0/Q1 候选自动降 Q2 并记 `downgraded_from` + `downgrade_reason="no_deterministic_verification"`（§5.4）。
  - `run_deterministic_verifiers(scene, content, issues)`：对 Q0/Q1 候选逐条跑上表复核器，返回 verified issue 指纹集——LLM 提案要升级必须过这道确定性门。
  - `blocking_issues()`/`warning_issues()` 供引擎、投影、adopt 共用（阻断策略单一来源）。
- **D2 · 引擎接分类器（阻断策略统一）**：
  - HardQcEngine：分类后 branch 由分类结果派生——存在 verified Q0/Q1 → 保留原阻断分支；否则**强制 continue**，原 LLM 意见降为 Q2/Q3 warnings 随 QcReport 持久化。确定性 gate 只对 Q1 级 issue（pronoun drift / event_log keyword）强制 partial_rewrite；theme/tension/mechanical 只附加不改分支。
  - SoftQcEngine：`has_blocking_qc_issue` 词表判断替换为分类器（verified Q0/Q1 才 block）；LLM 主动要求 human_review 但无 verified Q0/Q1 → 降级为 waive（pass_with_notes + carry note，复用 `_waive_repeat_patch_payload` 形状）。patch 分支保留（自动修订，非阻断）。
  - QC 执行失败（F5）：不再 human_review_required 断头——硬 QC 失败时确定性 gates 照跑，无 verified Q0/Q1 即 continue 并携带 `hard_qc_execution_failed`（Q2）警告；软 QC 失败同理走 waive。来源安全始终有 adopt 兜底扫描，不因 QC 缺席而漏检（§5.9 检测器与写作模型分离）。
  - style gate：plagiarism → 保持阻断（Q0）；fail/partial → 降为 Q2/Q3 警告不改分支。
  - near-final：执行失败 payload 改为非阻断形状（Q2 警告）；`requires_human_review`（纯 LLM 提案）不再断头——orchestrator 层按 D4 处置。
- **D3 · run_policy 请求级参数**（reliable|strict，默认 reliable；**不加列不写迁移**，列属 Wave 3）：
  - `run_scene(scene_id, run_policy="reliable")`；routes run/full + run/jobs 的 payload 接受并透传（job payload_json 已是自由 dict）。
  - reliable：Q2/Q3 不停管线 → 归档，warnings 进 carry notes（§5.4「交付当前最好稿」）。
  - strict：near-final 后若存在 Q2 warnings → 不自动归档，scene_status=`quality_warning_pending_acceptance`（新词值，映射 author_state=quality_warning、can_archive=true），作者经 adopt-current 归档即显式接受 Q2（adopt 的 carry note 记 `accepted_quality_levels`）。
  - Q0/Q1 verified：两种模式一致阻断（§5.4 分类纪律与模式无关）。
- **D4 · 自动修订 ≤2 与「达上限交付最佳稿」**：上限维持现状结构（soft patch ≤1 + near-final rewrite ≤1 = 2）；行为变化是出路——near-final 二评仍 fail 时**不再断头**，reliable 直接继续归档、strict 停 quality_warning，findings 转 Q2/Q3 warnings + `recommended_actions`（作者行动建议）。
- **D5 · 早退结果契约**：orchestrator 全部 return 路径统一附 `author_state` 投影字段（含 latest_valid_draft_row_id），由 `compute_author_state` 单点产出（Wave 2 项 5）。
- **D6 · 投影精化**（F14）：`compute_author_state` 读 `state.current_qc_report_id` 的 classified issues_json → blocking_findings=Q0/Q1 条目、quality_warnings=Q2/Q3 条目（保留 scene_status 粗粒度兜底）；`quality_warning_pending_acceptance` 加入 _QUALITY_WARNING_STATUSES。
- **D7 · adopt-current 强制 can_archive**（F13）：投影 can_archive=False（hard_blocked）→ 409 `HARD_BLOCKED`（details 带 blocking_findings；正文保留，§7.2）。Q1 的作者解除通路复用现有 human-review resolve 流程，不新建通道。
- **D8 · FE 分开展示**（F15）：
  - `ws-scene-run.jsx`：`scnRun`/`scnHydrateFromBackend` 从 workbench/status 取投影，产出 `gate = {authorState, blockingFindings, qualityWarnings, recommendedActions, canArchive}` 随运行结果持久化；`scnAdoptToDoc` 前置 can_archive 检查。
  - `ws-scene.jsx`：DecisionBar/ReviewStage 按 gate 分开展示——hard_blocked →「无法继续：需处理硬问题（正文已保留）」+ 禁用归档；quality_warning →「已有稿，建议修改」+ 允许归档。
  - `ws-review.jsx`：审阅项按 payload 内 quality_level 轻量标注阻断/建议（有则显示，无则不猜）；`ws-quality.jsx` 确认零改动（F16）。

## 3. 改动清单

后端（`backend/`）：
1. `src/novel_system/services/quality_classifier.py`（新）— D1
2. `src/novel_system/services/qc_engine.py` — D2（两引擎接分类器）
3. `src/novel_system/services/near_final.py` — D2（执行失败非阻断形状）
4. `src/novel_system/services/orchestrator.py` — D3/D4/D5
5. `src/novel_system/services/author_state.py` — D6
6. `src/novel_system/api/routes/scenes.py` — D3（run_policy 透传）/ D7（adopt 409）
7. `src/novel_system/services/scene_run_jobs.py` — D3（job payload 透传 run_policy）
8. `tests/test_quality_classifier.py`（新）+ `tests/test_qc_grading_reliable_mode.py`（新）+ 既有 `test_qc_engine.py`/`test_orchestrator_flow.py`/`test_near_final_engine.py`/`test_author_state_projection.py`/`test_scene_adopt_archive.py` 断言按新语义更新

前端（`frontend-react/src/`）：
9. `ws-scene-run.jsx` — gate 产出 + adopt 前置检查
10. `ws-scene.jsx` — 两态分开展示
11. `ws-review.jsx` — quality_level 轻量标注
12. `ws-scene-run.test.jsx` 扩展（gate 判定 + adopt 拦截先红后绿）

文档：13. 本计划；14. `docs/outcome-governance-progress.md` Wave 2 段。

**不改**：`db/models.py`（本 Wave 零迁移；漂移守卫仍跑以自证）；`narrative_event_log.py`（violation 已带 entity/fact/expected/actual/evidence，authority_ref 直接引用，无需改动）；`scene_generation.py`（patch 计数与 latest 指针 Wave 1 已就位）。

## 4. 测试先行顺序

1. `tests/test_quality_classifier.py`（先红）：注册表逐 key 分级极性；blocking 派生一致（构造「Q2 但 blocking=true」被强制纠正）；Q0/Q1 必带 verified_by；LLM 提案未复核自动降 Q2 + downgraded_from；未知 key 默认 Q2；确定性复核器（forbidden_text/missing_required/source_leak）真伪双向。
2. `tests/test_qc_grading_reliable_mode.py`（先红，G-03 核心回归）：
   - 软 QC LLM 返回 human_review_required + 词表 key（scene_conflict_missing 等，无确定性佐证）→ 管线继续 → FinalScene 归档 + quality_warnings 非空；
   - 硬 QC LLM 返回 full_rewrite（无确定性佐证）→ continue，issue 降 Q2；
   - 确定性 pronoun drift → Q1 verified → 阻断，latest_valid 保留，早退 payload 带 author_state=hard_blocked；
   - near-final 两评仍 fail → reliable 归档 + Q2 warning + recommended_actions；
   - near-final / 软 QC LLM 执行失败 → 不撤销正文，Q2 警告继续；
   - strict：Q2 warnings → 停 quality_warning_pending_acceptance，adopt-current 归档成功且 carry note 记显式接受；
   - adopt-current 对 verified Q1 hard_blocked → 409 HARD_BLOCKED；
   - QcReport.issues_json 每条带 §6.1 字段。
3. 后端实现 → 定向绿 → 既有断言更新 → 漂移守卫 + 全量回归。
4. 前端 vitest 先写（先红）：scnRun 在 status 返回 hard_blocked/quality_warning 时产出正确 gate；scnAdoptToDoc 在 canArchive=false 时不发 POST 直接拒。
5. 前端实现 → vitest 绿 → 构建。
6. 完成门自证（§5）。

## 5. 完成门自证

「重复旧三章场景至少交付三份可编辑正文」：本机以隔离后端（scratch sqlite + memory 向量 + mock LLM，软 QC/near-final 回放旧三章的阻断形状响应）实跑 3 场 `run/full` → 断言 3 场均产生非空 FinalScene 且 archived（pytest 集成测试给可复算证明 + 隔离后端脚本给端到端证据）。「只有真实 Q0/Q1 能阻断归档」：分类器/管线测试双向证明（LLM-only issue 不能阻断；确定性 Q0/Q1 能阻断且 adopt 也被拒）。真实云端模型复跑归 Windows lane 发布门（§9.3），记入剩余风险。

## 6. 本机验证命令

```bash
cd backend && .venv/bin/python -m pytest tests/test_quality_classifier.py tests/test_qc_grading_reliable_mode.py -q
cd backend && .venv/bin/python -m pytest tests/test_qc_engine.py tests/test_orchestrator_flow.py tests/test_near_final_engine.py tests/test_author_state_projection.py tests/test_scene_adopt_archive.py tests/test_metadata_isolation.py -q
cd backend && .venv/bin/python -m pytest -q -m "not chroma_integration"
cd frontend-react && NODE_OPTIONS="--require ./crypto-polyfill.cjs" npx vitest run
cd frontend-react && NODE_OPTIONS="--require ./crypto-polyfill.cjs" npm run build
```

## 7. 边界与剩余风险

- 真实云端模型的三章复跑（完成门字面口径）需 Windows lane / 已配置 LLM——本机 mock 复算已覆盖行为语义，真实模型波动性验证记入 §9.3 发布门。
- strict 模式的停点词值 `quality_warning_pending_acceptance` 是请求级行为（run_policy 不落列），Wave 3 落列后语义不变。
- Q1 的作者「确认/解除」细化通道（差异定位、逐条接受）不在本 Wave——现有 human-review resolve 流程为通路。
- 分类注册表未覆盖的历史 issue_key 一律默认 Q2（保守不阻断）——若存在「本应阻断却未注册」的确定性 key，属于注册表遗漏，需在真实运行观察中补录。
