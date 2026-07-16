# 系统整改记录（2026-07-16）

本文记录本轮“逐一修复”的已落地能力、可重复验证证据和仍不能由系统自动解决的盲区。它描述的是当前单机工作区，不是生产 SLA 或合规认证。

## 整改矩阵

| 范围 | 已修复 | 验证证据 | 仍属系统盲区 |
| --- | --- | --- | --- |
| 产品主线与演示隔离 | 默认进入主页；真实新建作品走 `/api/v2/projects`；雪花十步可保存、批准、物化和回流；章节编排可启动真实整章任务并轮询；成稿中心以“通读正文哈希确认→项目级批准”锁定终稿，重开会审计并级联撤销后续批准；结构控制塔只对 `潮汐档案` 演示作品开放。 | `frontend-react/src/ws-works.test.jsx`、`ws-snow.test.jsx`、`ws-chapter-run.test.jsx`、`ws-manuscripts-flow.test.jsx`；后端 `test_projects.py`、`test_catalog_api.py`。 | 真实供应商生成质量和进程内 worker 的生产可靠性仍需部署环境验收；演示控制塔不能代表真实作品已经完成结构诊断。 |
| 写作、AI 采纳与冲突恢复 | 草稿写入使用版本约束；离线、409、配额失败和 AI 覆盖风险会生成可比较、导出、重试的恢复稿；AI 候选不会无提示覆盖作者稿。 | `wr-doc-store.test.jsx`、`wr-recovery-center.test.jsx`、`ws-scene-run.test.jsx`。 | 恢复稿依赖当前浏览器的站点存储，不跨浏览器/设备，也不能替代服务端快照或异地备份。 |
| 后台任务恢复 | 启动时扫描可恢复的场景、章节、风格学习和验证任务；通过持久化 CAS/租约减少重复接管；旧的无主 LLM 预留可按 TTL 回收。 | `backend/tests/test_background_recovery.py`、`test_scene_run_checkpoint_resume.py`；迁移 `20260716_0071`。 | 工作者仍在应用进程内；进程崩溃后的恢复是补偿机制，不是外部队列的 exactly-once 保证。多节点调度、死信队列和独立 worker 尚未建立。 |
| 网络与 API 边界 | 默认只接受回环请求；远程模式强制共享 token；CORS 预检与真实请求分离；统一请求 ID、访问日志和不回显输入的校验错误；提供 `/live` 与数据库感知的 `/ready`。 | `backend/tests/test_api_app_config.py`、`test_api_input_boundaries.py`、`frontend-react/src/lib/client.test.js`。 | 共享 token 不是身份系统。没有用户登录、RBAC、租户级密钥轮换、会话撤销、审计主体证明或反向代理基线。 |
| LLM 额度与记账 | 增加日/月/项目 token、日请求数、并发数和可选费用硬限制；预留与结算分离，供应商真实用量进入全局额度；陈旧预留可恢复。 | `backend/tests/test_llm_accounting.py`、`test_llm_task_runner.py`、前端 `ws-cost.test.jsx`。 | 费用依赖手工价格配置；供应商补记、退款、缓存计价、区域税费和账单对账不在系统内。单机数据库上的并发闸门不等于分布式全局配额。 |
| 作者指令与偏好 | 作者指令不再静默截断，长度上限明确；指令、偏好和作用域被冻结进 bundle/hash；偏好须经批准且只允许提示词安全字段，按全局→题材→项目→章节覆盖。 | `test_author_drafts.py`、`test_author_preference_constraints.py`、`test_context_budget.py`、`test_hash_engine.py`；迁移 `20260716_0072`。 | 系统能证明“使用了哪份指令”，不能证明指令本身文学上正确、无偏见或适合目标读者。 |
| 长篇契约与连续性 | `ChapterContract` 和锚点进入冻结 bundle；确定性阻断条款、豁免审计、来源追踪和哈希复核已接最终门；终稿拆分为 `safe_to_archive`、`literary_warnings_unresolved`、`author_confirmed_final` 三态；扩展人物与时间线事实。 | `test_longform_bundle_gate.py`、`test_continuity_extended_facts.py`、`test_model_independence.py`；[长篇运行时契约](longform-runtime-contract.md)。 | 自然语言约束若无可机器核验词组，只能标记 `human_verification_required`；系统无法可靠判断主题完成度、人物弧光是否“动人”等开放文学命题。 |
| 内容安全 | 高风险启发式发现进入最终门；作者必须按当前返回的精确 finding code 复核，新发现不会复用旧确认；确认摘要与正文哈希进入归档审计。 | `test_content_safety.py`、`test_scene_adopt_archive.py`、`test_canonical_manuscripts.py`、前端 `wr-content-safety-review.test.jsx`、`ws-writer-content-safety.test.jsx`。 | 当前是规则/启发式扫描，存在误报、漏报和语境误判；勾选发现码也不是法律年龄、真实同意或操作者身份的证明。高风险发布仍需人工政策审查，必要时接专业审核服务。 |
| 参考书与版权边界 | 路径导入默认关闭并限制允许根目录；运行包只携带抽象风格画像与来源安全提示；明显复刻风险可阻断；安全阈值可配置并记录证据。 | `test_source_safety.py`、`test_reference_safety_extraction.py`、`test_style_reference_hardening.py`、`test_style_reference_control_plane_boundaries.py`。 | 本地相似度与规则不能覆盖公开语料、未导入作品、情节实质相似或各法域的合理使用判断。系统不是版权清查工具，商业发布前仍需来源台账、授权证明和法律复核。 |
| 文学质量与模型独立性 | 文学指标明确降级为诊断信号；中文/非空格文本估算得到修正；模型独立性按实际 writer/critic/judge 路由给出 `independent / correlated / unknown`，覆盖不足时不宣称整体独立。 | `test_literary_quality.py`、`test_literary_eval.py`、`test_model_independence.py`。 | 启发式分数不等于读者偏好、可出版性或审美价值；同源模型即使换角色仍可能相关。需要真实读者盲评、编辑评审和跨模型/跨供应商实验。 |
| 审计隐私与数据库就绪 | 新 LLM 审计只保存有界元数据/指纹，不持久化提示词和模型正文副本；历史敏感审计在 `0073` 中不可逆脱敏；预检和 `/ready` 识别迁移漂移。 | `test_llm_audit_privacy.py`、`test_database_preflight.py`；迁移 `20260716_0073`；`llm_audit_scrub --dry-run`。 | 权威业务表仍必须保存用户正文；这需要独立的备份加密、保留期、删除请求、主机权限和泄露响应制度。脱敏迁移不能撤销还原。 |
| 可观测性与错误处理 | 关键降级路径增加结构化日志；请求附带 request ID；任意内部异常不再直接返回给客户端；健康检查区分进程存活与可服务状态。 | `test_api_app_config.py`、`test_chapter_runner.py`、`test_idempotency_contract.py`。 | 尚无集中日志、指标告警、分布式追踪、SLO、跨进程关联和容量基线。日志存在不等于事故可及时发现。 |

## 本轮自动化证据

- 本轮已有 React 全量 Vitest 与生产构建通过；最终测试数量以合并后的命令输出为准。
- 后端按领域执行了 API 边界、作者偏好、内容安全、长篇契约、LLM 记账、恢复、隐私和数据库预检的定向 pytest 回归。
- 发布前仍应在最终合并状态重新执行：

```powershell
cd frontend-react
npm run test
npm run build
```

```powershell
cd backend
python -m pytest -m "not chroma_integration"
python -m alembic heads
python -m novel_system.tools.database_preflight .\novel_system.db --expected-revision 20260716_0073
```

定向测试通过只证明已覆盖的契约没有回归，不代表真实供应商、真实长篇质量、版权合规或生产负载已经验收。

## 必须保留在发布清单中的盲区

1. **真实供应商未验**：本轮没有以真实 API 凭据完成各模型的网络、超时、流式响应、usage、费用、限流和输出漂移验收。上线前应按目标供应商逐一做小额实测与故障注入。
2. **启发式文学/安全/版权**：三类规则都只能产生证据和提醒，不能成为自动出版许可。最终责任仍在作者、编辑、内容政策和法律审查。
3. **多租户与外部队列缺失**：当前共享 token、SQLite/单机数据库和进程内后台任务适合受控单作者环境，不适合不互信用户、横向扩容或高可用生产部署。
4. **浏览器本地恢复有限**：恢复中心缓解同步冲突，但不提供跨设备、服务端版本历史或灾难恢复。重要稿件必须另有可验证备份。
5. **前端大包**：生产构建仍有大 chunk 以及动态/静态混合导入警告。功能正确不代表低端设备和慢网络体验合格，应继续做路由级拆包、依赖审计和性能预算。

更具体的运维设置见 [运行安全与资源边界](runtime-safety.md)。
