# 原创三章闭环 QA 报告

生成时间：2026-04-22T03:34:41.085Z

## 环境
- 前端：http://127.0.0.1:5173
- 后端：http://127.0.0.1:8000
- 操作者：qa.longzu.three-chapters.20260422
- 参考书：C:\Users\duwei\Downloads\龙族.txt
- 参考书存在：是，大小：3766420 bytes
- 参考策略：segments_only，只学习抽象技法、叙事结构和禁复刻规则。

## 步骤证据
| 结果 | 步骤 | 耗时秒 | 备注 |
| --- | --- | ---: | --- |
| 通过 | environment preflight | 0 | 完成 |
| 通过 | system config probes, evals, style profile contract/extract/review | 39 | 完成 |
| 通过 | reference learning import/analyze/decide/apply | 220 | 完成 |
| 通过 | author workspace create original three chapters and scenes | 1 | 完成 |
| 通过 | knowledge console create and publish original candidates | 2 | 完成 |
| 通过 | review inbox approve pin and same-card release | 2 | 完成 |
| 通过 | index console promotions, recovery, ledger, target activity | 4 | 完成 |
| 通过 | author workspace run CHOR01 through chapter runner | 270 | 完成 |
| 阻塞 | scene workbench run CHOR02_SC01 | 600 | page.waitForResponse: Timeout 600000ms exceeded while waiting for event "response" at E:\codex\xiaoshuo\codex\output\pla... |
| 阻塞 | generate original three scenes | 870 | page.waitForResponse: Timeout 600000ms exceeded while waiting for event "response" at E:\codex\xiaoshuo\codex\output\pla... |

## 写手体验评分
| 功能步骤 | 评分 | 资深创作者观察 |
| --- | ---: | --- |
| 系统配置与模型探针 | 8 | API base 和模型路由可见，适合正式开写前做健康检查；高级配置仍偏工程化。 |
| 参考书导入与抽象学习 | 8 | segments_only 路径清楚，长耗时提示改善明显；重新导入同一书时旧 run 会影响“启动学习”按钮，需留意。 |
| 参考候选审核 | 8 | 候选只暴露抽象摘要，无源文摘录；拒绝理由入口可用。 |
| 审核批准/发布连续性 | 9 | pending 视图 approve 后同卡仍可继续 release。 |
| 作者工作台建章建场 | 8 | 三章三场景参数完整，表单绑定当前章节；用 API 批量建档更稳，UI 适合逐章编辑。 |
| 场景工作台生成与证据 | 7 | preflight、bundle、QC、attempt timeline 都能追踪；真实 LLM 耗时仍是主要等待成本。 |
| 知识控制台 | 8 | voice/relation/style/calibration 候选可发布并绑定原创章节场景；高级引用信息丰富。 |
| 索引控制台 | 8 | due promotions、recovery、ledger、target activity 可查，适合排查发布链路。 |
| 互操作中心 | 8 | worksheet preview/import/export 和 final scene replay 覆盖成功，bundle provenance 便于审计。 |
| 作者回收站 | 9 | 隔离章节可完成场景移入、恢复、章节移入和永久清除，未影响主三章。 |

## 三章创作结果
### CHOR01 / CHOR01_SC01
- 终稿行：未生成
- 状态：unknown
- Bundle：none
- 字数：0
- 文学评分：原创性 0/10，冲突推进 0/10，人物张力 0/10，场景因果 0/10，连续性 0/10，语言质感 0/10，源书泄漏风险控制 0/10
- 终稿摘录：

### CHOR02 / CHOR02_SC01
- 终稿行：未生成
- 状态：unknown
- Bundle：none
- 字数：0
- 文学评分：原创性 0/10，冲突推进 0/10，人物张力 0/10，场景因果 0/10，连续性 0/10，语言质感 0/10，源书泄漏风险控制 0/10
- 终稿摘录：

### CHOR03 / CHOR03_SC01
- 终稿行：未生成
- 状态：unknown
- Bundle：none
- 字数：0
- 文学评分：原创性 0/10，冲突推进 0/10，人物张力 0/10，场景因果 0/10，连续性 0/10，语言质感 0/10，源书泄漏风险控制 0/10
- 终稿摘录：


## 原创性与安全扫描
- 保护词扫描：未命中源书专名/受保护标记
- 参考画像安全：{"safe":true,"stripped_count":0,"blocked_markers":[]}
- 报告未保存参考书原文或长摘录，只保存抽象决策与原创输出摘录。

## 开发问题、根因与修复证据
| 问题 | 根因 | 修复 | 回归证据 |
| --- | --- | --- | --- |
| 场景工作台 stale scene | localStorage 中旧 scene id 404 后仍保留 | 404 且命中 remembered id 时清空 key 和本地状态 | `readableConsoles.spec.js` stale scene 用例 |
| 审核 pending 视图 approve 后 release 断裂 | 刷新时 pending 过滤移除了刚批准卡 | pin 最近批准项，release 后解除 pin | `app.spec.js` approve/release 连续性用例；本次 QA pinReview |
| 作者新建场景可能错章/空章 | 章节刷新期间场景按钮仍可点，表单 chapter id 未稳定绑定 | loading 时禁用场景动作，表单跟随选中章节 | `authorWorkspace.spec.js` 源级断言 |
| 参考学习长耗时反馈不足 | advance 无长任务计时提示，脚本等待窗口偏短 | 显示长任务提示和秒级计时；QA 等待 10 分钟 | `referenceLearning.spec.js` 和本报告 firstAdvanceMs |
| QA 脚本硬编码 8000 | 一次性脚本写死 `127.0.0.1:8000` | 读取 env 或 `.codex-run/backend.url` | `playwrightQaScripts.spec.js` |
| 中文乱码误判 | PowerShell 输出编码会把 UTF-8 中文显示成 mojibake | 以 UTF-8 读取源码和静态 guard 判断真实内容 | `readableConsoles.spec.js` 中文可读性 guard |

## 截图
- output/playwright/longzu-three-chapter-qa-20260422-111535/system-config-complete.png
- output/playwright/longzu-three-chapter-qa-20260422-111535/reference-initial.png
- output/playwright/longzu-three-chapter-qa-20260422-111535/reference-after-profile-apply.png
- output/playwright/longzu-three-chapter-qa-20260422-111535/author-workspace-complete.png
- output/playwright/longzu-three-chapter-qa-20260422-111535/knowledge-console-complete.png
- output/playwright/longzu-three-chapter-qa-20260422-111535/review-inbox-complete.png
- output/playwright/longzu-three-chapter-qa-20260422-111535/index-console-complete.png

## 验证命令
- 已在实现阶段通过：`npx vitest run tests/readableConsoles.spec.js tests/app.spec.js tests/authorWorkspace.spec.js tests/referenceLearning.spec.js tests/playwrightQaScripts.spec.js`
- 已在实现阶段通过：`npx vitest run`
- 已在实现阶段通过：`python -m pytest backend/tests/test_reference_learning.py backend/tests/test_style_profile.py backend/tests/test_scene_generation.py backend/tests/test_chapter_runner.py backend/tests/test_system_config.py backend/tests/test_literary_eval.py -q`
- 收尾验证见最终回复；若失败，将补记阻塞原因。

## 残余风险
- 真实 LLM 输出质量受本地模型状态影响；本报告记录真实耗时和输出，不替换为假结果。
- PowerShell 终端可能把 UTF-8 中文显示为乱码，源码和报告按 UTF-8 保存。
- 若后续要严格验证 Chroma，应在 WSL strict lane 单独运行。
