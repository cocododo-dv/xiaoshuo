# 《龙族》参考样本到三章修仙 Demo 闭环 QA

## Scope

- 目标样本：`refbook_d4ae8e00eea8`，若本地缺失则按标题或文件名中的“龙族/Dragon”兜底查找。
- 目标产物：`XXDEMO_CH01`、`XXDEMO_CH02`、`XXDEMO_CH03`，每章一个场景，题材为原创修仙。
- 安全约束：普通 UI 不展示来源原文片段；最终文本和 bundle snapshot 不包含源作品专名、来源站点标记、版权声明或可识别桥段标记。

## Findings

1. Reference Learning 的候选 finding 曾向产品界面暴露 `source_segment.preview` / `evidence_preview`，存在把参考书原文片段带入普通 UI 的风险。已改为默认隐藏来源摘录，只展示抽象 summary、片段类型和 `source_excerpt_hidden`。
2. Profile 卡片曾直接从 `profile_json` 生成预览，后续若清洗策略变更容易把证据字段带到界面。已新增安全展示字段，并让前端预览优先使用 `preview_items` / `display_profile_json`。
3. 三章修仙 demo 之前主要存在于 E2E helper 和 API 拼装流程中，不是产品入口。已在 Reference Learning 增加 Demo Studio 工作区，可显示样本、画像、章节运行、QC 和泄漏检查。
4. 本地真实《龙族》样本可能处于 unsafe/stale 状态。新 demo run 在没有 ready 且 safe 的 profile 时返回 `409` blocker，不自动使用不安全画像。
5. `.vector_store` 不是本次《龙族》参考样本来源；闭环以本地 SQLite reference book 记录为准。
6. 当 `NOVEL_SYSTEM_LLM_ENABLED=false` 或 API key 缺失时，系统只能产出 `offline_placeholder`，只能算管线 smoke，不能宣称真实原创小说已生成。

## Verification

- 后端单测覆盖：
  - finding/detail 默认不返回来源 preview。
  - unsafe/stale profile 阻止 demo run。
  - safe profile 幂等创建三章三场景并运行。
  - final scene 和 bundle snapshot 泄漏检查命中列表为空。
- 前端单测覆盖：
  - API helper 调用 demo status/run。
  - Reference Learning 源码不再渲染 `source_segment.preview`。
  - Demo Studio 工作区、运行按钮、安全 profile preview 字段存在。
- E2E 覆盖：
  - 使用安全 fixture 生成 reference profile。
  - 通过新 Demo Studio 产品入口点击运行。
  - 验证三章最终场景、工作台展示和泄漏检查。
