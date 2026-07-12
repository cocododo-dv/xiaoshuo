# Wave 5 实施计划：质量实验室与人类盲评

> 设计：`docs/superpowers/specs/2026-07-10-ai-novel-outcome-governance-design.md`（v1.1）§5.1 / §6.2 / §6.3 / §8 Wave 5 / §9.1 / §9.4
>
> 日期：2026-07-12
>
> 纪律：Wave 4 完成门已过（提交 `60a0a40`，全量 1489 passed）；只改本 Wave 相关代码；测试先行；涉 ORM 改动交付「模型 + Alembic 迁移 + 漂移守卫」三件套；独立提交。

## 0. 前置门禁复核（开工前先跑）

```bash
cd backend && .venv/bin/python -m pytest tests/test_best_of_n_blind_eval.py \
  tests/test_metadata_isolation.py tests/test_generation_persistence.py -q
```

三文件全绿 → 基线确认。红灯先查环境漂移，不在红基线上叠加。

## 1. 目标与完成门

**目标（§8 Wave 5）**：证明哪些模块真的提升偏好——用匿名 A/B 人类盲评量化 Best-of-N 终选（及后续消融）相对单发基线的偏好收益。

**完成门**：产出**可复算**的 30 组投票报告，并给每个被测模块明确**保留 / 降级 / 关闭**结论。

**可复算自证（本机离线）**：
- 给定固定的 pair 集 + 固定投票，报告函数确定性算出偏好率、非平局 n、精确双侧二项 p、最小胜场阈值、token/耗时倍率与 verdict——同输入同输出（纯函数 + CLI 工具复算）。
- 盲化不泄漏：`next-pair` 只返回 `pair_id` 与左右纯文本，映射/策略/模型/分数一律不出现在响应。
- §9.4 默认策略判据：非平局 30 组、≥21 胜、双侧 p<0.05 → treatment 可升级默认；未达标 → 保持可选（负结果是有效结论，不构成门失败）。

**离线边界（归 §9.3 发布门）**：真实 treatment/control 正文生成需 LLM；真实 30 次人类投票需用户本人。二者本机不可跑（CentOS7/node16/无额度）。本 Wave 交付**基础设施 + 可复算报告机制**，用合成 pair/投票证明报告正确；真实跑归发布门（与 Wave 0 红灯、Wave 4 悬疑 LLM 同批）。这是设计允许的分层——§9.4 明确「30 组盲评已完成并产出可复算报告」是发布门项，不是本 Wave 的本机门。

## 2. 关键设计决策

### D1：复用现有纯函数核心，只加持久化 + 平局 + 阈值表

`services/best_of_n_blind_eval.py` 已有 `build_blind_plan`（盲化 A/B + 隐藏键）、`tally_votes`、`binomial_two_sided_p`、`evaluate`（verdict）。**不重写**。Wave 5 新增：
- `tally_votes_with_ties`：平局照记（`ties`）、不计胜场；显著性在非平局 n 上算（§6.2）。
- `min_wins_for_significance(n, alpha=0.05)`：最小胜场阈值表（计算式，断言锚点 n=30→21、n=25→18、n=27→20、n=28→20、n=29→21 与设计一致）。
- 报告层的 §9.4 默认策略判据 + 每模块 keep/downgrade/disable 结论。

### D2：三张新表（§6.2），迁移三件套

`EvaluationExperiment` / `EvaluationPair` / `EvaluationVote`，字段按 §6.2。补充：
- `EvaluationPair` 除 `left_artifact_ref`/`right_artifact_ref` 外加 `left_text`/`right_text`（冻结纯文本，供 `next-pair` 直供前端）与 `blind_mapping_json`（隐藏键，**永不序列化给前端**）、`no_contrast`（Best-of-N==baseline）。
- 唯一性「每快照至多一对」（§6.2）在**服务层**强制（查重后插入，报 `SNAPSHOT_ALREADY_USED`），不依赖 DB inline UNIQUE（避免 sqlite autoindex 与漂移守卫的边角）；命名索引仅加查询用的 `ix_evaluation_pairs_experiment` / `ix_evaluation_votes_pair`，模型 `__table_args__` 与迁移同名同建。
- 迁移 `20260712_0063_wave5_evaluation_experiments.py`（head 0062→0063），`op.create_table` 带 `has_table` 存在性守卫（仓库惯例）；同步更新 `test_generation_persistence.py:380/540` 硬编码 head 为 `20260712_0063`。

### D3：盲化威胁模型 = 防无意识偏倚（§6.2）

本地单用户直接读库可破盲——设计明示盲评目标是防无意识偏倚、非防蓄意作弊。因此 `blind_mapping` 用「隐藏」（不下发）而非加密即可；`next-pair` 严格只出 `pair_id`+左右文本，投票落库后 `report`/`reveal` 才含映射。

### D4：不自动翻转生产默认（§11 规则 7 / §9.4）

报告只**输出**每模块建议（keep_optional / upgrade_to_default / downgrade / disable），**不自动改任何生产默认**——无真实人评证据时宣称模块提升质量或翻默认违 §11 规则 7。翻默认是另一步、需真实 30 票，归发布门。消融是多假设序列，报告对「升级默认」标 `requires_fresh_replication`（§8 项 8，第二批 30 组非平局对复验防多重比较假阳性）。

### D5：实验通道与生产隔离（§5.1 / §6.2）

- 实验通道**不写 FinalScene**，只写三张实验表（§5.1）。
- 项目隔离：`EvaluationExperiment` 记 `isolation_mode`（seed_project|time_isolated）与 `snapshot_source_ref`；报告回显并断言 pair 的 `scene_snapshot_hash` 全互异（30 组来自 30 个快照）。生产终选场重叠的强校验（需生产内容哈希）归发布门，本 Wave 以「唯一快照 + 声明隔离」为可测核心。

### D6：最小 React 投票页

新 store `ws-eval.jsx`（`WsEval`，API-backed）+ 最小投票视图，接 `next-pair`/`vote`/`report`。store vitest 测试证明**盲化消费**（只渲染左右文本、只回传 choice+duration，不读映射/元数据）+ 乐观投票。浏览器走查归 Windows lane。不动无关文件。

## 3. 分步实施（测试先行）

### Step A — 统计扩展（纯函数，先行）

**测试** `tests/test_best_of_n_blind_eval.py` 追加（先红）：
- `test_tally_votes_with_ties_excludes_ties_from_wins`：平局计入 `ties`、不计胜负。
- `test_min_wins_threshold_table_matches_design`：n=30→21、25→18、27→20、28→20、29→21；且各阈值双侧 p<0.05、阈值-1 不显著。
- `test_report_upgrade_requires_21_of_30_nontie`：30 非平局、21 胜 → upgrade_to_default 且 p<0.05；20 胜 → keep_optional。

**实现** `services/best_of_n_blind_eval.py` 追加 `tally_votes_with_ties`、`min_wins_for_significance`、`default_strategy_decision(...)`（不改现有函数签名）。

### Step B — 三张表 + 迁移三件套

**测试**（先红）：
- `tests/test_metadata_isolation.py` 复用既有漂移守卫（新表须两侧一致）——加迁移后应绿。
- `tests/test_evaluation_experiment_store.py::test_tables_exist_after_migration`（隔离库 alembic upgrade head → 三表存在）。

**实现**：models.py 加三类；迁移 `20260712_0063`；更新 `test_generation_persistence` head 常量。

### Step C — 实验服务

**测试** `tests/test_evaluation_experiment_service.py`（先红后绿）：
- `create_experiment` 持久化元数据。
- `add_pair` 盲化随机左右 + 隐藏键；重复 `scene_snapshot_hash` 报 `SNAPSHOT_ALREADY_USED`。
- `next_pair` 只返回 pair_id+左右文本（断言无 mapping/ref/policy 键泄漏）；返回未投票对；全投完返回空。
- `record_vote`（left|right|tie，非法值报错）；同 (pair,reviewer) 幂等（重复返回同一票，不双计）。
- `report` 折叠映射 → treatment/control/tie，算偏好率/非平局 n/双侧 p/阈值/token·耗时倍率/verdict/每模块结论；`requires_fresh_replication` 标注。
- `report` 断言 30 快照互异（伪重复守卫）。

**实现** `services/evaluation_experiment.py`。

### Step D — 路由（§6.3 四核心 + seed-pairs）

**测试** `tests/test_evaluation_experiment_routes.py`（TestClient，先红后绿）：
- `POST /api/v1/evaluation-experiments` 建实验。
- `POST /api/v1/evaluation-experiments/{id}/pairs` 冻结文本对入库（服务端盲化）——seeding 基础设施（§6.3 四核心的补充）。
- `GET .../{id}/next-pair` 响应体断言**只含** pair_id+左右文本。
- `POST /api/v1/evaluation-pairs/{id}/vote` 幂等（X-Idempotency-Key）。
- `GET .../{id}/report` 可复算报告。

**实现** 新 `api/routes/evaluation_experiments.py`，app.py 挂载。

### Step E — 可复算报告 CLI 工具

`tools/evaluation_experiment_report.py`（镜像 `tools/best_of_n_blind_eval.py`）：从 DB 或 JSON 复算报告并 `format_report`。测试：给定固定 pair+投票，CLI 输出确定。这是完成门「可复算报告」的复算入口。

### Step F — 最小 React 投票页

- `frontend-react/src/ws-eval.jsx`（`WsEval` store）+ `tests/`/`src/ws-eval.test.jsx`（vitest，`installApiRouter` 路由 `next-pair`/`vote`/`report`）：断言只消费 pair_id+左右文本、乐观投票+回滚。
- 最小视图接入导航（高级/实验模式），不动无关文件。
- 跑 vitest + build。

### Step G — 进度账本

`docs/outcome-governance-progress.md` 追加 Wave 5 节。

## 4. 回归与验证命令

```bash
cd backend && .venv/bin/python -m pytest tests/test_best_of_n_blind_eval.py \
  tests/test_evaluation_experiment_service.py tests/test_evaluation_experiment_routes.py \
  tests/test_evaluation_experiment_store.py tests/test_metadata_isolation.py \
  tests/test_generation_persistence.py -q                                   # 定向 + 三件套
cd backend && .venv/bin/python -m pytest -q -m "not chroma_integration"     # 全量回归
cd frontend-react && NODE_OPTIONS="--require ./crypto-polyfill.cjs" npx vitest run   # 投票 store
cd frontend-react && NODE_OPTIONS="--require ./crypto-polyfill.cjs" npm run build    # 构建
# 迁移隔离库验证：alembic upgrade head → 三表存在
```

## 5. 预期剩余风险

- 真实 30 票 + 真实 treatment/control LLM 生成本机不可跑 → 归 §9.3 发布门；合成 pair/投票证明报告可复算与判据正确。
- 项目隔离以「唯一快照 + 声明 isolation_mode」为可测核心；与生产终选场的内容重叠强校验归发布门（需生产内容哈希）。
- 报告只输出建议、不翻生产默认（§11 规则 7）；翻默认需真实人评，另行执行。
- 消融序列多重比较：报告标 `requires_fresh_replication`，实际复验归发布门（§8 项 8）。

## 6. 提交边界（只提交本 Wave 文件）

- `backend/src/novel_system/services/best_of_n_blind_eval.py`（追加平局/阈值/判据）
- `backend/src/novel_system/services/evaluation_experiment.py`（新）
- `backend/src/novel_system/db/models.py`（三类）+ `alembic/versions/20260712_0063_wave5_evaluation_experiments.py`（新）
- `backend/src/novel_system/api/routes/evaluation_experiments.py`（新）+ `api/app.py`（挂载）
- `backend/src/novel_system/tools/evaluation_experiment_report.py`（新）
- `backend/tests/test_best_of_n_blind_eval.py`（追加）、`test_evaluation_experiment_service.py`（新）、`test_evaluation_experiment_routes.py`（新）、`test_evaluation_experiment_store.py`（新）
- `backend/tests/test_generation_persistence.py`（head 常量 0062→0063）
- `frontend-react/src/ws-eval.jsx`（新）+ `src/ws-eval.test.jsx`（新）+ 最小视图接入
- `docs/outcome-governance-progress.md`（Wave 5 节）+ 本计划文件
