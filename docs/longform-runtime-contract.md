# 长篇运行时契约与终稿状态

## Bundle 冻结规则

- 场景生成只读取状态为 `dispatched` 或 `archived` 的 `ChapterContract`；`drafting`、`ready` 不构成运行时权威。
- Bundle 会冻结契约、契约引用的全部锚点，以及仍为 `pinned` 的 `fact`、`trait`、`setting`、`timeline` 锚点。
- 契约引用的锚点即使后来标记为 `faded`，仍会随该契约进入 Bundle；引用不存在的锚点或同章存在多个已下发契约时，构建会失败并要求先修复权威来源。
- `chapter_contract_id`、锚点 ID、更新时间和正文都进入 Bundle 哈希投影；终稿门会重新计算含长篇契约的完整投影哈希，哈希不一致时拒绝归档，后续编辑不能反向改变历史生成证据。

## 可机器核验的契约条款

每条约束支持以下审计字段：

| 字段 | 含义 |
| --- | --- |
| `constraint_id` | 稳定条款标识；未提供时由服务端生成 |
| `enforcement` | `advisory`（默认）或 `blocking` |
| `check_terms` | 作者明确提供的可核验正文词组 |
| `match_mode` | `any` 或 `all` |
| `waived` | 是否由作者豁免 |
| `waiver_reason` | 豁免理由；豁免时必填 |
| `waiver_actor_ref` / `waived_at` | 服务端记录的操作者与时间 |

`constraint_id` 在同一契约内必须唯一；`waived` 只接受布尔值。原样保存已豁免条款会保留最初操作者和时间，条款内容或理由发生实质变化时才生成新的豁免审计。缺少理由、操作者或时间的豁免不能绕过阻断条款。

只有带 `check_terms` 的条款（或明确的 `required_text`、`must_include`、`exact_text` 字面条款）才能形成确定性阻断。普通自然语言创作要求只会进入 `human_verification_required`，不会用关键词启发式伪装成可靠文学判定。

终稿门的 `longform_contract` 会返回 `key_hits`、`waivers`、`unresolved`、`blockers` 和锚点 `provenance`；归档审计会持久化同一份摘要。冻结契约无法解码时会按完整性故障关闭归档，而不是静默跳过长篇约束。

## 终稿三态语义

不要再从 `near_final_ready` 或 `archived` 一个字符串推断所有含义。所有终稿相关结果均分别给出：

- `safe_to_archive`：精确正文是否通过来源安全和确定性连续性/契约硬门。
- `literary_warnings_unresolved`：仍有文学或近终稿咨询意见，且尚未由作者明确确认。
- `author_confirmed_final`：作者是否通过采纳或 canonical promotion 明确确认该正文。

三者同时位于 `finality` 对象中；旧字段 `archivable` 暂时保留为 `safe_to_archive` 的兼容别名。

## 模型独立性证据

`model_independence` 分别比较 `critic_independent`、`judge_advisory`、`chapter_judge_advisory` 与 `writer_primary`。结果为 `independent`、`correlated` 或 `unknown`；实际调用覆盖不完整时为 `independent_observed_partial`，且不会宣称整体独立。近终稿 `WriterEvaluation.contract_field_refs_json._model_independence` 会冻结评审当时的证据，避免配置变化后改写历史判断。
