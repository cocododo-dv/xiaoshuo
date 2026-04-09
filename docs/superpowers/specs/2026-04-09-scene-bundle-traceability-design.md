# Scene Bundle Traceability Design

> 日期：2026-04-09
> 目标阶段：把 `voice/relation` 从 bundle 构建阶段的占位输入，升级成有实体、有版本来源、缺失即失败的可追溯输入。

---

## 1. 背景

当前 `BundleBuilder` 已经会把 `chapter_goal`、`scene_card`、上一条 `scene_memory` 注入 bundle，并基于 `BundleSnapshotHashProjection` 计算哈希。

但 `voice` 与 `relation` 仍然存在两个问题：

1. `Resolver` 只返回派生 ID，例如 `VOICE_CHAR_A`、`REL_CHAR_A_CHAR_B`，这些 ID 没有真实实体表承接。
2. `inline_digests` 仍然使用占位文本，例如 `"voice profile for CHAR_A"` 和 `"relation context resolved"`，导致 replay/export 无法回答“当时到底注入了哪条内容”。

这会让 bundle hash 具备结构稳定性，但缺少输入可追溯性。

---

## 2. 目标

本次只解决 bundle 输入可追溯性，不扩展通用版本平台：

1. 新增 `voice_profiles` 与 `relation_profiles` 两类最小实体。
2. 每类实体使用“逻辑 ID + 物理版本行 + active_flag”的轻量版本语义。
3. `Resolver` 从“派生 ID”升级为“解析逻辑 ID，再解析当前有效版本行”。
4. `BundleBuilder` 仅允许注入真实已存储版本；缺失时返回明确领域错误。
5. `source_version_refs` 记录逻辑 ID、物理行 ID、版本号；`inline_digests` 直接来自实体内容。

成功标准：

- 构建 bundle 时，`voice/relation` 不再使用占位文本。
- 导出的 bundle worksheet 能看出具体引用了哪一版 `voice/relation`。
- 缺少活跃版本时，scene 运行在 bundle 阶段显式失败，而不是静默降级。

---

## 3. 非目标

- 不把 `voice/relation` 接入 `VersionRegistry`、`ReindexJob`、`VerifyJob` 整套通用发布链。
- 不在本次扩展 `style_rule`、`world_rule`、`foreshadow` 的实体化来源。
- 不改动前端界面结构。
- 不引入自动生成缺省 `voice/relation` 的兜底记录。

---

## 4. 方案选择

### 方案 A：只加当前表，不做版本化

优点：改动最少。
缺点：无法清楚表达 bundle 当时引用的是哪一版内容。

### 方案 B：轻量版本化

做法：新增 `voice_profiles` 与 `relation_profiles`，每条记录包含逻辑 ID、版本号、物理行 ID、内容、`active_flag`。

优点：满足本次“真实版本源 + 可追溯”目标，成本可控。
缺点：未来若要全量统一版本平台，还要再做一次归并。

### 方案 C：直接接入现有 `VersionRegistry`

优点：长期最统一。
缺点：范围过大，会把这次 bundle 能力升级扩展成通用版本平台改造。

### 决策

采用方案 B。

---

## 5. 结构设计

### 5.1 新增实体

新增 `VoiceProfile`：

- `row_id`
- `voice_profile_id`
- `version`
- `character_id`
- `content`
- `active_flag`
- `source_note`
- `created_at`
- `updated_at`

新增 `RelationProfile`：

- `row_id`
- `relation_profile_id`
- `left_character_id`
- `right_character_id`
- `version`
- `content`
- `active_flag`
- `source_note`
- `created_at`
- `updated_at`

约束：

- 同一逻辑 ID 可存在多条版本行。
- bundle 构建时只读取 `active_flag = 1` 的当前有效版本。
- 若不存在有效版本，则视为阻塞错误。

### 5.2 Resolver 行为

保留“逻辑 ID 解析”与“实体行解析”两层职责：

- `resolve_voice_profile_id(scene)`：从 `pov_character_id` 解析逻辑 voice ID。
- `resolve_relation_profile_id(scene)`：优先使用 `resolved_relation_id`，否则从双人场景推导 relation ID。
- `resolve_active_voice_profile(session, scene)`：基于逻辑 ID 读取唯一活跃版本行。
- `resolve_active_relation_profile(session, scene)`：基于逻辑 ID 读取唯一活跃版本行。

缺失处理：

- 如果 scene 需要 `voice/relation` 但没有活跃版本行，抛出 `DomainError("BUNDLE_SOURCE_MISSING", ...)`。

### 5.3 Bundle Contract

`BundleSnapshotHashProjection` 保持整体结构不变，但 `source_version_refs` 增补具体版本信息：

- `voice_profile_id`
- `voice_profile_row_id`
- `voice_profile_version`
- `relation_profile_id`
- `relation_profile_row_id`
- `relation_profile_version`

`ordered_injections` 继续沿用：

- `pov_voice`
- `relation`

`inline_digests` 的值直接来自实体表 `content`，不再写占位摘要。

### 5.4 Seed 与运行路径

为了让现有 scene happy path 继续可运行：

- `seed_demo` 写入 `CH001_SC01` 对应的活跃 `VoiceProfile` 和 `RelationProfile`。
- `test_orchestrator_flow.seed_story()` 也同步补齐最小版本化 seed。

这样 `run_scene()` 在 bundle 阶段就能读取真实来源，不会被新增失败策略卡住。

---

## 6. 错误处理

新增领域错误：

- `BUNDLE_SOURCE_MISSING`

触发场景：

- `pov_character_id` 存在，但找不到活跃 `VoiceProfile`
- 双人关系可解析，但找不到活跃 `RelationProfile`

返回策略：

- API 层保持现有 `DomainError` 响应格式
- 不做静默降级
- 不自动创建默认记录

---

## 7. 测试设计

### 7.1 BundleBuilder 合同测试

新增/扩展测试验证：

- bundle 快照包含 `voice_profile_row_id/version`
- bundle 快照包含 `relation_profile_row_id/version`
- `inline_digests.voice_card` 与 `inline_digests.relation_card` 来自实体内容

### 7.2 缺失源失败测试

新增测试验证：

- 缺失活跃 `VoiceProfile` 时，`run_scene` 返回 `409` 且错误码为 `BUNDLE_SOURCE_MISSING`
- 缺失活跃 `RelationProfile` 时，`run_scene` 返回 `409` 且错误码为 `BUNDLE_SOURCE_MISSING`

### 7.3 Demo/Seed 回归

新增测试验证：

- demo seed 会写入活跃 `voice/relation` 版本行
- 原有 scene happy path 和 acceptance happy path 继续可运行

---

## 8. 实施顺序

1. 扩展测试，先把 traceability 与缺失失败场景写红。
2. 新增实体模型与迁移。
3. 升级 `Resolver` 与 `BundleBuilder`。
4. 更新 seed 和测试辅助数据。
5. 跑目标测试与 Windows 后端回归。

---

## 9. 验收定义

满足以下条件即视为完成：

- `voice/relation` 已有真实实体和版本行来源。
- bundle worksheet 可追溯到具体 `row_id/version`。
- 缺失活跃版本时，bundle 构建显式失败。
- scene happy path 与现有 backend Windows 安全测试通过。
