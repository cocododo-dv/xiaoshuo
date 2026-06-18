# 指标审计：对抗性 vs 顺从性

> 对应蓝图 §17 动作 A · 审计日期：2026-06-16
> 源文件：`backend/src/novel_system/services/literary_quality.py`
> 辅助源：`config/writer_rubrics.yaml`
>
> **目的：** 判断现有指标体系能否支撑 Best-of-N 分级选择（蓝图 §6）。
> 如果指标大半顺从性 → 分级自动初筛方案暂不成立，先补对抗性指标。
> 如果已有一批对抗性的 → 分级方案可立刻试。

---

## 一、分类定义

| 类型 | 定义 | Best-of-N 中的作用 |
|------|------|-------------------|
| **对抗性** | 惩罚 AI 味——值越**高**越差（套路密度、感知过滤词、前文重复） | 初筛淘汰最差候选 |
| **结构性** | 检测叙事结构缺失——缺失即扣分（无选择、无代价、无推进） | 初筛淘汰结构空洞候选 |
| **顺从性** | 奖励规整——值越**高**越好（流畅度、语法正确率） | ⚠️ 用它们选 = 精确地挑出最平庸的那个 |

> **关键洞察（蓝图 §6.1）：** 用顺从性指标做 Best-of-N 初筛会**强化** AI 味。
> 只有对抗性 + 结构性指标才适合做自动初筛。

---

## 二、18 维度逐项审计

### A. 对抗性指标（惩罚 AI 味，越低越好）

| # | 维度 | 权重 | 检测逻辑 | 分类理由 | 蓝图 §8 对应 |
|---|------|------|----------|----------|-------------|
| 1 | `model_voice` | 0.09 | 匹配 MODEL_VOICE_TERMS（"突然意识到"/"仿佛命运"等） | **纯对抗**：直接惩罚 LLM 口癖 | "直接命名情绪" |
| 2 | `false_clarity` | 0.02 | 匹配 FALSE_CLARITY_TERMS（"她知道"/"终于明白"） | **纯对抗**：惩罚虚假确定性 | "感知过滤词" |
| 3 | `over_explained_motive` | 0.04 | 匹配 MOTIVE_EXPLANATION_TERMS（"因为她"/"所以他"） | **纯对抗**：惩罚动机过度解释 | "过度解释" |
| 4 | `template_action_reuse` | 0.06 | 句子模板计数 ≥3 同模板 | **纯对抗**：惩罚句式套路 | "段落起承转合套用同一模式" |
| 5 | `syntax_monotony` | 0.03 | 句法模式计数 ≥3 同模式 | **纯对抗**：惩罚句法单调 | "段落起承转合套用同一模式" |
| 6 | `repetitive_action` | 0.05 | 动作词计数 ≥4 同词 | **纯对抗**：惩罚动作口癖 | 蓝图 §9 反重复 |
| 7 | `image_homogeneity` | 0.05 | 意象词计数 ≥3 同词 | **纯对抗**：惩罚意象同质化 | 蓝图 §9 反重复 |
| 8 | `image_field_reuse` | 0.03 | 氛围意象 ≥4 且 ≥3 种 | **纯对抗**：惩罚氛围堆砌 | — |
| 9 | `decorative_imagery` | 0.05 | 装饰意象词 ≥2 | **纯对抗**：惩罚"不服务于行动/信息/主题的意象" | — |
| 10 | `false_poetic_closure` | 0.04 | 结尾含诗意词汇但无动作 | **纯对抗**：惩罚虚假诗意收束 | — |
| 11 | `expository_dialogue` | 0.07 | 对话含解释性词汇 | **纯对抗**：惩罚"对话当解释" | "冲突化解太干净/角色太讲理" |
| 12 | `dialogue_as_report` | 0.07 | 对话含报告性词汇 | **纯对抗**：惩罚"对话当报告" | — |

**小计：12 个，总权重 0.60**

### B. 结构性指标（检测叙事结构缺失）

| # | 维度 | 权重 | 检测逻辑 | 分类理由 |
|---|------|------|----------|----------|
| 13 | `no_choice_scene` | 0.08 | 文本中无任何选择/决定词汇 | **结构缺失**：场景无选择 = 结构空洞 |
| 14 | `choice_pressure` | 0.08 | 文本中无压力/代价词汇 | **结构缺失**：选择无代价 = 免费选择 |
| 15 | `painless_scene` | 0.10 | 无代价/牺牲/风险词汇 | **结构缺失**：场景无痛感 |
| 16 | `ending_drive` | 0.08 | 结尾无动作词汇 | **结构缺失**：结尾不推进 |
| 17 | `summary_ending` | 0.06 | 结尾含总结性词汇 | **边界案例**：既是结构缺失（不推进）也是对抗性（AI 爱总结）。**归入结构性。** |

**小计：5 个，总权重 0.40**

### C. 顺从性指标

| # | 维度 | 权重 | 分类理由 |
|---|------|------|----------|
| 18 | `valid_ambiguity` | 0.00 | 权重为零，score 恒为 1.0，实质是占位符 |

**小计：0 个有效顺从性指标，总权重 0.00**

---

## 三、Rubric 维度审计

### drama_effectiveness_v1（9 维度）

| 维度 | 分类 | 理由 |
|------|------|------|
| `desire` | 结构性 | 人物有无清晰欲望 |
| `obstacle` | 结构性 | 有无具体阻碍 |
| `stakes` | 结构性 | 有无代价/风险 |
| `turn` | 结构性 | 有无转折 |
| `subtext` | 对抗性 | 惩罚表面化——无潜文本 = AI 味 |
| `irreversible_change` | 结构性 | 有无不可逆变化 |
| `scene_necessity` | 结构性 | 场景是否必要 |
| `reader_hook` | 结构性 | 有无阅读钩子 |
| `continuity` | 结构性 | 连续性——接近顺从性但不奖励规整 |

### literary_revision_v1（10 维度）

| 维度 | 分类 | 理由 |
|------|------|------|
| `character_contradiction` | 结构性 | 有无内外冲突 |
| `choice_pressure` | 结构性 | 同上 |
| `relationship_tension` | 结构性 | 关系是否变化 |
| `dialogue_subtext` | 对抗性 | 惩罚直白——无潜文本 = AI 味 |
| `information_rhythm` | 对抗性 | 惩罚解释性释放——应通过行动释放 |
| `voice_distinction` | 对抗性 | 惩罚无辨识度——通用声音 = AI 味 |
| `image_necessity` | 对抗性 | 惩罚装饰——不推动叙事的意象 |
| `repetitive_expression` | 对抗性 | 惩罚重复 |
| `ending_drive` | 结构性 | 同上 |
| `theme_pressure` | 结构性 | 有无主题压力 |

---

## 四、审计结论

### 指标分布

| 类型 | 数量（18 维度） | 权重占比 | 数量（rubrics 19 维度） |
|------|----------------|----------|----------------------|
| **对抗性** | **14** | **0.63** | **6** |
| **结构性** | **5** | **0.33** | **12** |
| **顺从性** | **0** | **0.00** | **1**（continuity，弱） |

> 注：PR1-PR3 实施后从 18→20 维度（+perception_filter +self_repetition），对抗性占比进一步提升。

### 关键发现

1. **当前指标体系几乎全是对抗性 + 结构性，零有效顺从性。** 这是一个极好的起点——蓝图 §6.5 的前置门（"如果指标大半顺从性 → 分级方案暂不成立"）**已通过**。

2. **对抗性指标权重 0.60 > 结构性 0.40。** 初筛用对抗性指标淘汰"最 AI 味"的候选，在当前体系下有足够的指标支撑。

3. **结构性指标全部基于"缺失检测"（absence signal），不是"正面奖励"。** `no_choice_scene` 检测的是"文本中没有选择/决定词汇"，不是"有选择就加分"。这意味着它们实质上也是对抗性的——惩罚结构空洞，而非奖励结构完整。

4. **蓝图 §6.2 的"不对称性"成立：** 对抗性指标定义下界（没有 AI 味错误），但满足全部 12 条只是"没犯明显错误"，离"好"还很远。上界仍需人来判断。

### 已知盲区（对抗性不足的地方）

| 盲区 | 说明 | 补强方向 |
|------|------|----------|
| **前文自我重复** | 当前只查单文本内重复，不比对前 N 场景 | 用 n-gram 做跨场景比对，输出"禁用表达列表" |
| **感知过滤词** | `false_clarity` 覆盖了"她知道/终于明白"，但缺"她觉得/他看到/她注意到" | 扩展 FALSE_CLARITY_TERMS 或新建 `perception_filter` 维度 |
| **段落级节奏套路** | `syntax_monotony` 查句法模式，但不查"每段都是 叙述→对话→内心独白" 的段落模式 | 新增 `paragraph_rhythm_monotony` 维度 |
| **中文特有 AI 口癖** | MODEL_VOICE_TERMS 中文条目较少（6 条），英文 8 条 | 扩充：如"心中一紧""不禁"/"心头一热"/"微微一笑"/"深深地"/四字成语堆砌 |
| **分散度** | 无候选间相似度计算 | Best-of-N 引入时新增 |

---

## 五、Best-of-N 可行性判定

### ✅ 结论：可以开始试 Best-of-N

**理由：**
- 12 个对抗性指标（权重 0.60）足以做初筛淘汰。
- 5 个结构性指标（权重 0.40）可作为辅助筛。
- 零顺从性指标 = 不存在"初筛精确地挑出最平庸版本"的风险。

### 建议的 Best-of-N 初筛公式

```python
def adversarial_score(signals: dict) -> float:
    """越高越好——0.0 = 全部对抗性指标都触发（最 AI 味），1.0 = 无触发"""
    ADVERSARIAL_DIMS = [
        "model_voice", "false_clarity", "over_explained_motive",
        "template_action_reuse", "syntax_monotony", "repetitive_action",
        "image_homogeneity", "image_field_reuse", "decorative_imagery",
        "false_poetic_closure", "expository_dialogue", "dialogue_as_report",
    ]
    total_weight = sum(DIMENSION_WEIGHTS[d] for d in ADVERSARIAL_DIMS)
    weighted_sum = sum(
        signals[d]["score"] * DIMENSION_WEIGHTS[d]
        for d in ADVERSARIAL_DIMS
    )
    return weighted_sum / total_weight if total_weight else 1.0


def structural_score(signals: dict) -> float:
    """越高越好——0.0 = 全部结构性指标都缺失，1.0 = 全部满足"""
    STRUCTURAL_DIMS = [
        "no_choice_scene", "choice_pressure", "painless_scene",
        "ending_drive", "summary_ending",
    ]
    total_weight = sum(DIMENSION_WEIGHTS[d] for d in STRUCTURAL_DIMS)
    weighted_sum = sum(
        signals[d]["score"] * DIMENSION_WEIGHTS[d]
        for d in STRUCTURAL_DIMS
    )
    return weighted_sum / total_weight if total_weight else 1.0


def best_of_n_rank(signals: dict) -> float:
    """初筛排序分——越高越好。对抗性 70% + 结构性 30%"""
    return 0.7 * adversarial_score(signals) + 0.3 * structural_score(signals)
```

### 建议的执行计划

1. **先补感知过滤词**（半天）：扩展 `FALSE_CLARITY_TERMS` 或新增 `perception_filter` 维度（"她觉得/他看到/她注意到/她感到"）。
2. **扩充中文 AI 口癖**（半天）：MODEL_VOICE_TERMS 加 10-15 条高频中文 AI 味词汇。
3. **实现 Best-of-N 原型**（1 周）：`scene_generation.py` 中关键场景 N=3，用 `best_of_n_rank` 初筛，输出 top-2 给人终选。
4. **加分散度监控**（2 天）：N 候选两两计算 `fingerprint_literary_quality` 的 Jaccard 距离，报告分散度。
