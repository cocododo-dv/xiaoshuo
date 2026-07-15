# 发布证据归档（durable evidence）

`output/playwright/` 整体在 `.gitignore` 中，QA 运行的原始产物（截图、run-log、
final-scenes）留在那里；但按结果治理路线图的证据规则 2——"每个完成结论都必须能
回指配置、原始产物、汇总报告和复算命令"——**汇总报告与门禁判定必须落在可入库
路径**。

`scripts/run-currentdb-three-chapter-qa.cjs`（含 R2.1 固定 lane
`run-public-domain-source-safety-five-chapter-qa.cjs`）每次运行结束（成功、门禁
失败或致命错误）都会把以下文件复制到本目录的 `<运行输出目录名>/` 下：

- `report.md` — 全量汇总报告（环境、六阶段 UI 证据、各章结果、保护词扫描）
- `outcome-gate-verdict.md` — 结果门禁判定（唯一权威判定）
- `source-safety-gate-verdict.md` — 逐场来源安全结论

作为发布证据引用的运行，其归档目录应当提交入库；日常调试运行的归档可以删除。
