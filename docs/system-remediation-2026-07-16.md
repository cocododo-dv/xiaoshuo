# AI 小说写作系统整改记录（2026-07-16）

本文记录本轮“深度分析并逐一修复”已落地的能力、可重复验证证据，以及仍不能由当前系统自动解决的边界。结论适用于当前仓库和受控的单机、单作者运行形态，不等同于生产 SLA、安全认证、版权合规意见或文学质量保证。

## 整改结论

本轮发现的仓库内可修复问题已经逐项落地，并完成前后端全量或交叉回归、生产构建、真实 Chroma 定向验证、空库迁移与数据库预检。系统现在能以真实项目为主线完成雪花规划、章节编排、场景写作、终稿确认和归档，同时对批准态不可变、严格章节顺序、成稿完整性、幂等失败发布、因果链方向、内容安全、额度记账和后台恢复建立了可验证契约。

“全部完善”在这里是指：本轮代码审计识别出的、能够在当前仓库范围内闭环的问题均已修复并有自动化证据。真实供应商质量、文学审美、内容与版权法律判断、多租户生产架构、跨设备灾难恢复和前端性能预算仍属于部署或人工治理范围，不能宣称已经由代码彻底解决。

## 修复矩阵

| 范围 | 已修复 | 验证证据 | 仍属系统边界 |
| --- | --- | --- | --- |
| 产品主线与演示隔离 | 默认进入真实作品主页；新建作品走 `/api/v2/projects`；雪花十步可保存、批准、物化和回流；章节编排可启动真实整章任务并轮询；结构控制塔只对明确的演示作品开放，演示数据保持只读并清晰标识。 | React 全量测试与构建；旧 Vue 兼容测试、smoke 与构建；`test_projects.py`、`test_catalog_api.py`。 | 演示控制塔不代表真实作品已经完成结构诊断；真实生成质量仍需供应商环境验收。 |
| 已批准章节不可变与严格顺序 | 已批准章节不能被普通写入路径静默改写；重开会留下审计并撤销依赖它的后续批准。章节终审严格依据项目当前章节和规范顺序推进；目录中的结构性 `review` 标签不会被误判为当前章节已进入终审。 | `test_approved_chapter_guards.py`、目录与章节 API 回归。 | 若绕过应用直接修改数据库，仍需依赖主机权限、备份和数据库审计防线。 |
| 成稿完整性、通读确认、批准与重开 | 成稿批准前会检查项目章节是否完整、正文是否存在以及规范版本是否一致；作者必须针对当前正文哈希完成通读确认后才能批准。批准后终稿被锁定；重开会审计并级联撤销受影响状态，不再把缺章或旧确认包装为“可归档”。 | `ws-manuscripts-flow.test.jsx`、`test_canonical_manuscripts.py`、`test_approved_chapter_guards.py`。 | 哈希确认能证明“确认的是哪一版”，不能证明作者真的逐字阅读或文学上认可。 |
| 写作、AI 采纳与冲突恢复 | 草稿写入使用版本约束；离线、409、配额失败和 AI 覆盖风险会生成可比较、导出、重试的恢复稿；AI 候选不会无提示覆盖作者稿。 | `wr-doc-store.test.jsx`、`wr-recovery-center.test.jsx`、`ws-scene-run.test.jsx`。 | 恢复稿依赖当前浏览器站点存储，不跨浏览器或设备，也不能替代服务端快照和异地备份。 |
| 后台任务恢复 | 启动时扫描可恢复的场景、章节、风格学习和验证任务；以持久化 CAS/租约减少重复接管；无主 LLM 预留可按 TTL 回收。 | `test_background_recovery.py`、`test_scene_run_checkpoint_resume.py`；迁移 `20260716_0071`。 | 工作者仍在应用进程内；多节点调度、死信队列和外部 worker 尚未建立，补偿恢复不等于分布式 exactly-once。 |
| 向量 verify 失败发布 | verify 动作本身保持可回滚；只有持有当前幂等所有权且 CAS 校验成功的 worker，才能通过失败回调在同一事务中发布 job、alias、registry 和 fault 的失败状态。陈旧 worker、已被重领的 attempt、陈旧 candidate 或已被新版本取代的 snapshot 都不能降级新状态；失败回调自身异常也会整体回滚。 | `test_vector_lifecycle_service.py`、`test_idempotency_contract.py`、真实 Chroma 交叉回归。 | 单机事务与 owner-CAS 不能代替跨数据库、跨队列的分布式事务；外部向量服务的区域故障仍需生产演练。 |
| 反向因果骨架 | 明确定义 `opening→ending` 与兼容的历史 `ending→opening` 顺序；新增带 schema/version/direction 的兼容 codec，旧产物仍可反序列化。雪花产物按时间正序供场景执行，避免后续场景错误消费“未来原因”；只有确有相邻状态证据时才计算完整性，没有证据时返回 `unknown/null`，不再伪装为 `true`。 | `test_snowflake_planner.py`、`test_scene_execution_causal_order.py`、因果骨架核心回归。 | 自然语言中的隐含因果、主题呼应和人物动机强度仍需要编辑判断；未绑定序号只能作为提示，不能安全地硬阻断。 |
| 写作简报与幂等输入边界 | 章节与场景写作简报的 OpenAPI 契约明确为 `object|null`；输入会在领取幂等键前归一化和校验。无效输入不会污染幂等记录，同一键修正请求后仍可正常执行和重放。 | 写作、章节、场景与幂等 API 回归；OpenAPI schema 断言。 | JSON 结构合法不代表写作意图合理；语义冲突仍需业务校验或作者裁决。 |
| 网络与 API 边界 | 默认只接受回环请求；远程模式强制共享 token；CORS 预检与真实请求分离；统一 request ID、访问日志和不回显输入的校验错误；提供 `/live` 与数据库感知的 `/ready`。 | `test_api_app_config.py`、`test_system_config.py`、`test_api_input_boundaries.py`、`client.test.js`。 | 共享 token 不是身份系统；尚无用户登录、RBAC、租户级密钥轮换、会话撤销和反向代理安全基线。 |
| LLM 额度与记账 | 增加日、月、项目 token，日请求数、并发数和可选费用硬限制；预留与结算分离，供应商真实用量进入全局额度；陈旧预留可恢复。 | `test_llm_accounting.py`、`test_llm_task_runner.py`、`ws-cost.test.jsx`。 | 费用依赖手工价格配置；供应商补记、退款、缓存计价、税费和账单对账不在系统内。单机数据库闸门不等于分布式全局配额。 |
| 作者指令与偏好 | 作者指令不再静默截断；指令、偏好和作用域被冻结进 bundle/hash。偏好须经批准且只允许提示词安全字段，按全局→题材→项目→章节覆盖。 | `test_author_drafts.py`、`test_author_preference_constraints.py`、`test_context_budget.py`、`test_hash_engine.py`；迁移 `20260716_0072`。 | 系统能证明使用了哪份指令，不能证明指令本身无偏见、文学上正确或适合目标读者。 |
| 长篇契约与连续性 | `ChapterContract` 和锚点进入冻结 bundle；确定性阻断条款、豁免审计、来源追踪和哈希复核接入最终门。终稿状态拆分为 `safe_to_archive`、`literary_warnings_unresolved`、`author_confirmed_final`；人物与时间线事实得到扩展。 | `test_longform_bundle_gate.py`、`test_continuity_extended_facts.py`、`test_model_independence.py`；[长篇运行时契约](longform-runtime-contract.md)。 | 无可机器核验词组的自然语言约束只能标记 `human_verification_required`；主题完成度和人物弧光等开放文学命题仍需人工判断。 |
| 内容安全 | 高风险启发式发现进入最终门；作者必须按当前返回的精确 finding code 复核，新发现不会复用旧确认；确认摘要与正文哈希进入归档审计。 | `test_content_safety.py`、`test_scene_adopt_archive.py`、`test_canonical_manuscripts.py`、`wr-content-safety-review.test.jsx`、`ws-writer-content-safety.test.jsx`。 | 当前规则存在误报、漏报和语境误判；确认 finding code 不是法律年龄、真实同意或操作者身份的证明。高风险发布仍需人工政策审查。 |
| 参考书与版权边界 | 路径导入默认关闭并限制允许根目录；运行包只携带抽象风格画像和来源安全提示；明显复刻风险可阻断；安全阈值可配置并记录证据。实际候选正文会被扫描，来源风险与文学阻断可以同时保留。 | `test_source_safety.py`、`test_reference_safety_extraction.py`、`test_reference_untrusted_data.py`、`test_scene_quality_auto_rewrite.py`、`test_style_reference_hardening.py`。 | 本地相似度与规则不能覆盖公开语料、未导入作品、情节实质相似或各法域合理使用。系统不是版权清查工具，商业发布前仍需来源台账、授权证明和法律复核。 |
| 文学质量与模型独立性 | 文学指标明确降级为诊断信号；中文和非空格文本估算得到修正；模型独立性按实际 writer/critic/judge 路由给出 `independent`、`correlated` 或 `unknown`，覆盖不足时不宣称整体独立。 | `test_literary_quality.py`、`test_literary_eval.py`、`test_model_independence.py`。 | 启发式分数不等于读者偏好、可出版性或审美价值；同源模型即使换角色仍可能相关。需要真实读者盲评、编辑评审和跨供应商实验。 |
| 审计隐私与数据库就绪 | 新 LLM 审计只保存有界元数据和指纹，不持久化提示词及模型正文副本；历史敏感审计在 `0073` 中不可逆脱敏；预检和 `/ready` 能识别迁移漂移。 | `test_llm_audit_privacy.py`、`test_database_preflight.py`；迁移 `20260716_0073`；`llm_audit_scrub --dry-run`。 | 权威业务表仍必须保存用户正文，需要独立的备份加密、保留期、删除请求、主机权限和泄露响应制度。脱敏迁移不可逆。 |
| 可观测性与错误处理 | 关键降级路径增加结构化日志；请求附带 request ID；内部异常不直接返回给客户端；健康检查区分进程存活与可服务状态。 | `test_api_app_config.py`、`test_chapter_runner.py`、`test_idempotency_contract.py`。 | 尚无集中日志、指标告警、分布式追踪、SLO、跨进程关联和容量基线。日志存在不等于事故能被及时发现。 |

## 最终自动化证据

以下结果均来自最终整改代码状态：

- React 前端：`27 files / 214 tests passed`；生产构建通过。当前产物为 JS `1,351.29 kB`（gzip `422.03 kB`）、CSS `440.80 kB`（gzip `69.45 kB`），体积告警已作为下方性能盲区保留。
- 旧 Vue 兼容层：`59 files / 545 tests passed`；smoke 通过；生产构建通过。
- 后端正式 non-Chroma 全量：共收集 `2778` 项（另有 `17` 个外部 Chroma 项未纳入该标记集），分成 4 个 shard 执行，4 个 shard 均 `exit 0`；合计 `2773 passed, 5 skipped`。
- 受影响领域交叉回归：包含真实 Chroma，`299 passed`。
- Pydantic 并发告警清理：对应目标测试以 `-W error::pydantic.warnings.UnsupportedFieldAttributeWarning` 执行，`1 passed`，未再产生该告警。
- 数据库：从空库迁移到唯一 head `20260716_0073` 成功；`database_preflight` 返回 `ready: true`、`integrity: ok`，外键与孤儿记录检查均通过。
- 浏览器 E2E：在隔离数据库和真实开发服务器上覆盖 `2 个作品 × 16 个视图 = 32 页`，保存 32 张截图；前端 HTTP 200，`/live=live`、`/ready=ready`。`console`、`pageerror`、`requestfailed`、HTTP 4xx/5xx、error boundary 与 crawl exception 均为 0。爬虫留下的 2 条启发式提示已人工复核为误报：雪花字段中的“错误信念”不是系统错误；`Ctrl+K` 命令面板可实际打开，只是爬虫使用了旧类名。进一步核实了 tide 10 章、salt 3 章、批准章结构和正文只读、缺场景时生成动作禁用、演示归档完全只读以及雪花 01–10 步。证据见 [findings.json](../output/playwright/e2e-final/crawl/findings.json) 与 [页面截图](../output/playwright/e2e-final/crawl/shots)。

后端正式 non-Chroma 分片结果：

| Shard | 结果 | 退出码 |
| --- | ---: | ---: |
| 0 | 695 passed | 0 |
| 1 | 695 passed | 0 |
| 2 | 693 passed, 1 skipped | 0 |
| 3 | 690 passed, 4 skipped | 0 |
| 合计 | 2773 passed, 5 skipped | 全部为 0 |

这些证据证明已覆盖的代码契约在当前环境没有回归，但不代表真实供应商、真实长篇文学质量、版权合规、生产负载或灾难恢复已经完成验收。

## 必须保留在发布清单中的盲区

1. **真实供应商未完成生产验收**：本轮没有以各目标供应商的真实 API 凭据覆盖网络抖动、超时、流式中断、usage 偏差、费用、限流、内容过滤和模型输出漂移。上线前应逐一做小额实测、故障注入与账单对账。
2. **文学、安全与版权仍是启发式判断**：这三类规则只能生成诊断证据、阻断明显风险和要求人工确认，不能成为自动出版许可。文学价值由读者和编辑判断，内容政策由专业审核判断，版权与合理使用由权利台账和法律复核判断。
3. **多租户与外部队列缺失**：当前共享 token、SQLite/单机数据库和进程内后台任务适合受控单作者环境，不适合不互信用户、横向扩容或高可用生产部署。生产化仍需身份与 RBAC、租户隔离、密钥轮换、外部队列、独立 worker、死信与分布式可观测性。
4. **浏览器本地恢复有限**：恢复中心能缓解离线和同步冲突，但站点存储不提供跨设备同步、服务端完整版本历史或灾难恢复。重要稿件必须另有加密、离线且可验证恢复的备份。
5. **前端大包性能尚未专项治理**：当前构建仍存在大 chunk 和静态/动态混合导入警告。功能正确不代表低端设备和慢网络体验合格；后续应先拆出共享契约与状态，再做路由级懒加载和冷启动/深链回归，最后分拆全局 CSS，并建立首屏体积与加载时延预算。

更具体的运维设置见[运行安全与资源边界](runtime-safety.md)。
