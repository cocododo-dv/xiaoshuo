# 文档导航

本文档是仓库文档的统一入口，最后核查日期为 2026-08-19。若日期化计划、旧证据与现行代码冲突，以根目录 `README.md`、本页列出的运行时契约和当前代码为准。

## 日常使用

- [操作手册](operator-manual.md)：React 正式工作台的入口、创作主线、异常处理和数据边界。
- [运行安全与资源边界](runtime-safety.md)：网络、令牌、额度、内容复核、路径导入、恢复和备份约束。
- [长篇运行时契约与终稿状态](longform-runtime-contract.md)：冻结契约、连续性检查、批准与重开语义。
- [正史连续性与长篇记忆](canon-continuity.md)：正文事实候选、证据复核、权威提交、上下文注入和历史数据迁移。

## 开发与发布

- [发布检查清单](release-checklist.md)：CI、Windows、React E2E 和 WSL Chroma 发布门。
- [系统整改记录（2026-07-16）](system-remediation-2026-07-16.md)：最新一次全量整改结论、验证范围和明确盲区。
- [QA 五轮工作流](QA-五轮工作流-提示词.md)：真实供应商和长篇 QA 的运行规范；原始产物写入被忽略的 `output/playwright/`，需长期保留的门禁摘要归档到 `docs/evidence/`。
- [提示词交接清单](prompt-optimization-handoff.md)：由 `python -m novel_system.tools.export_prompt_handoff` 生成的 LLM 节点与模板清单，不应手工维护其生成区块。

## 当前专项记录

- [结果治理路线图](outcome-governance-roadmap-2026-07-15.md)与[实施账本](outcome-governance-progress.md)：工程门已完成，真实模型五章、真人盲评和 30 章耐久仍以各自证据门为准。
- [章节编排 LLM 接入设计（2026-07-16，已实现）](chapter-arrangement-llm-design-2026-07-16.md)：章节蓝图一等公民 + 上下文底座 + 候选/补全/体检三通道与只填空补丁纪律。
- [雪花「整理成章节结构」重新设计（2026-07-25，设计稿待实施）](snowflake-chaptering-design-2026-07-25.md)：构思侧章表一等公民 + 可预览分章 + scene_id 撞号与幽灵场两个数据缺陷的修复方案。
- [风格参考设计](style_reference_module_design_v1.1.md)、[实施账本](style-reference-progress.md)与[Phase 3 完成记录](style-reference-phase3-backlog.md)：后两者是历史实施依据，Phase 3 A/B/C 已全部完成。
- [风格参考 RAG v2：内容克制检索](style-reference-rag-content-independence.md)：结构化风格签名、旧索引迁移、合成 A/B 及证据边界。
- [风格参考运行时契约与反馈闭环](style-reference-runtime-contract.md)：冻结风格血缘、统一上下文/基线、降级规则和盲选校准反馈。
- `docs/superpowers/`：保留 2026 年 7 月结果治理工作的计划、规格和机器证据。文件中的 revision、路径和结论只对应其原始运行时间。

## 文档维护规则

1. 根 README 只保留当前启动、主流程、数据迁移和验证入口。
2. 操作手册只描述正式 React 工作台；`frontend/` 的 Vue 应用是兼容回归面，不是产品文档真相源。
3. `output/`、测试截图、PID、日志、IDE 配置和测试缓存不得提交。需要长期引用的运行结论应归档为小型、可复算的摘要或 manifest。
4. 一次性审计、已完成迁移包和过期实施计划不在主线长期保留；Git 历史承担追溯职责。
5. 日期化证据不得被改写成“当前状态”；当前 Alembic head、命令和能力边界必须重新从代码或根 README 核对。
