<script setup>
import { computed } from "vue";
import { MessageSquare, WandSparkles } from "lucide-vue-next";
import { diagnosticLabel, fieldLabel, patchKeyListLabel } from "../lib/snowflakeDisplay";

const props = defineProps({
  item: {
    type: Object,
    required: true,
  },
});

const emit = defineEmits(["update:item-field", "update:list-field", "apply-repair", "ask-assistant"]);

const status = computed(() =>
  String(props.item?.effective_status || props.item?.status || props.item?.recommended_status || "").toLowerCase(),
);
const sceneType = computed(() => String(props.item?.primary_form || props.item?.scene_type || "proactive").toLowerCase());
const patchKeys = computed(() => Object.keys(props.item?.repair_patch || {}));
const patchKeySummary = computed(() => patchKeyListLabel(props.item?.repair_patch || {}));
const missingFieldSummary = computed(() => (props.item?.missing_fields || []).map(fieldLabel).join("、"));
const structureTitle = computed(() =>
  sceneType.value === "reactive" ? "反应场景（反应→困境→决定）" : "主动场景（目标→冲突→挫折）",
);
const structureFields = computed(() => {
  const crucible = {
    key: "scene_crucible",
    label: "坩埚",
    fallbackKey: "crucible",
    hint: "困住角色、让他无法轻易退出的压力。",
  };
  if (sceneType.value === "reactive") {
    return [
      crucible,
      { key: "reaction", label: "反应", hint: "先情感/身体反应，再进入理性。" },
      { key: "dilemma", label: "困境", hint: "真正的两难，每个选项都要付代价。" },
      { key: "decision", label: "决定", hint: "决定必须引发下一场的新目标。" },
    ];
  }
  return [
    crucible,
    { key: "goal", label: "目标", hint: "可拍摄、可判断是否达成的目标。" },
    { key: "conflict", label: "冲突", hint: "多轮尝试与受阻，而不是一次性说明。" },
    { key: "setback", label: "挫折", hint: "结尾比开场更糟，留下开放循环。" },
  ];
});
const repairGuideTitle = computed(() => (status.value === "rewrite" ? "废除指南" : "急救步骤"));
const repairGuideItems = computed(() => {
  if (status.value === "rewrite") {
    return [
      "先保留有用的对白、意象或信息零件。",
      "确认这场真正想承担的剧情职责。",
      "重新设计一个有坩埚和不可逆变化的替代场景。",
    ];
  }
  return [
    "确认场景类型和坩埚是否清楚。",
    "补齐对应结构节点，并让压力逐轮升级。",
    "检查结尾是否制造开放循环，或决定是否能引出下一目标。",
  ];
});

function statusLabel(value) {
  if (value === "pass") {
    return "合格";
  }
  if (value === "maybe") {
    return "需修改";
  }
  if (value === "rewrite") {
    return "废除重写";
  }
  return "未诊断";
}

function scoreLabel(value) {
  return typeof value === "number" ? `${value}` : "--";
}

function fieldValue(field) {
  return props.item?.[field.key] || props.item?.[field.fallbackKey] || "";
}

function joinLines(value) {
  return Array.isArray(value) ? value.join("\n") : "";
}
</script>

<template>
  <article class="triage-detail-card" data-testid="snowflake-triage-scene-card">
    <div class="scene-card-head">
      <div>
        <span class="eyebrow">选中场景</span>
        <h3>{{ item.title || item.scene_id }}</h3>
        <p class="muted">{{ item.scene_id }} · {{ structureTitle }}</p>
      </div>
      <div class="triage-score-ring" :class="status || 'empty'">
        <strong>{{ scoreLabel(item.score) }}</strong>
        <small>诊断分</small>
      </div>
    </div>

    <div class="triage-diagnosis-strip">
      <span>推荐：{{ statusLabel(item.recommended_status) }}</span>
      <span>生效：{{ statusLabel(status) }}</span>
      <span v-if="item.manual_override">人工覆盖自动诊断</span>
      <span v-if="item.blocking">阻止物化</span>
    </div>

    <div class="triage-tag-row" v-if="item.pressure_flags?.length">
      <span v-for="flag in item.pressure_flags" :key="flag">{{ diagnosticLabel(flag) }}</span>
    </div>

    <section class="triage-structure-card">
      <div>
        <span class="eyebrow">场景结构</span>
        <h4>{{ structureTitle }}</h4>
      </div>
      <div class="triage-structure-grid">
        <div v-for="field in structureFields" :key="field.key" class="triage-structure-field">
          <span>{{ field.label }}</span>
          <small>{{ field.hint }}</small>
          <p>{{ fieldValue(field) || "尚未填写" }}</p>
        </div>
      </div>
    </section>

    <label class="triage-repair-field">
      <span>人工评级</span>
      <select
        class="control-input compact"
        :value="item.status || ''"
        @change="emit('update:item-field', 'status', $event.target.value)"
      >
        <option value="">跟随自动诊断</option>
        <option value="pass">合格</option>
        <option value="maybe">需修改</option>
        <option value="rewrite">废除重写</option>
      </select>
    </label>

    <label class="triage-repair-field">
      <span>急救备注</span>
      <textarea
        class="control-input"
        :value="item.notes || ''"
        placeholder="记录这一场的核心缺口、修法或重写理由。"
        @input="emit('update:item-field', 'notes', $event.target.value)"
      />
    </label>

    <div class="triage-detail-columns">
      <label class="triage-repair-field">
        <span>缺失字段</span>
        <small v-if="missingFieldSummary" class="field-hint">显示为：{{ missingFieldSummary }}</small>
        <textarea
          class="control-input compact-textarea"
          :value="joinLines(item.missing_fields)"
          placeholder="每行一个内部字段名，保存时会原样提交。"
          @input="emit('update:list-field', 'missing_fields', $event.target.value)"
        />
      </label>
      <label class="triage-repair-field">
        <span>急救步骤</span>
        <textarea
          class="control-input compact-textarea"
          :value="joinLines(item.fix_steps)"
          placeholder="每行一个修复动作，先改目标/冲突/挫败，再保存。"
          @input="emit('update:list-field', 'fix_steps', $event.target.value)"
        />
      </label>
    </div>

    <section class="triage-static-guide" :class="status || 'empty'">
      <span class="eyebrow">{{ repairGuideTitle }}</span>
      <ol>
        <li v-for="guide in repairGuideItems" :key="guide">{{ guide }}</li>
      </ol>
    </section>

    <div class="triage-action-row">
      <button type="button" class="ghost mini-btn" @click="emit('ask-assistant')">
        <MessageSquare :size="14" />
        <span>检查选中场景</span>
      </button>
      <div v-if="item.triage_id && patchKeys.length" class="triage-repair-apply">
        <div>
          <span class="eyebrow">修复补丁</span>
          <p class="muted">{{ patchKeySummary }}</p>
        </div>
        <button type="button" class="primary mini-btn" @click="emit('apply-repair')">
          <WandSparkles :size="14" />
          <span>应用修复</span>
        </button>
      </div>
    </div>
  </article>
</template>

<style scoped>
.triage-detail-card {
  display: grid;
  gap: 12px;
  border: 1px solid var(--snowflake-line);
  border-radius: 8px;
  background: var(--snowflake-paper-strong);
  color: var(--snowflake-ink);
  padding: 14px;
}

.scene-card-head,
.triage-diagnosis-strip,
.triage-tag-row,
.triage-action-row,
.triage-repair-apply {
  display: flex;
  align-items: center;
  gap: 10px;
}

.scene-card-head,
.triage-action-row {
  justify-content: space-between;
}

.scene-card-head h3,
.triage-structure-card h4,
.muted {
  margin: 0;
}

.scene-card-head h3,
.triage-structure-card h4 {
  color: var(--snowflake-heading);
}

.triage-score-ring {
  display: grid;
  justify-items: center;
  min-width: 70px;
  border-radius: 8px;
  background: var(--snowflake-paper);
  color: var(--snowflake-muted);
  padding: 10px;
}

.triage-score-ring strong {
  font-size: 1.4rem;
  line-height: 1;
}

.triage-score-ring.pass {
  background: var(--snowflake-moss-soft);
  color: var(--snowflake-moss-deep);
}

.triage-score-ring.maybe {
  background: var(--snowflake-warning-soft);
  color: var(--snowflake-warning);
}

.triage-score-ring.rewrite {
  background: var(--snowflake-danger-soft);
  color: var(--snowflake-danger);
}

.triage-diagnosis-strip,
.triage-tag-row {
  flex-wrap: wrap;
}

.triage-diagnosis-strip span,
.triage-tag-row span {
  border-radius: 999px;
  background: var(--snowflake-paper);
  color: var(--snowflake-muted);
  font-size: 0.78rem;
  padding: 5px 8px;
}

.triage-structure-card,
.triage-static-guide {
  display: grid;
  gap: 10px;
  border: 1px solid var(--snowflake-line);
  border-radius: 8px;
  background: var(--snowflake-paper);
  padding: 12px;
}

.triage-structure-grid,
.triage-detail-columns {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
}

.triage-structure-field {
  display: grid;
  gap: 4px;
  border-left: 3px solid var(--snowflake-line-strong);
  padding-left: 10px;
}

.triage-structure-field span {
  color: var(--snowflake-heading);
  font-weight: 700;
}

.triage-structure-field small {
  color: var(--snowflake-faint);
  line-height: 1.35;
}

.triage-structure-field p {
  margin: 0;
  color: var(--snowflake-ink);
  line-height: 1.6;
}

.triage-repair-field {
  display: grid;
  gap: 6px;
}

.field-hint {
  color: var(--snowflake-faint);
  font-size: 0.78rem;
  line-height: 1.35;
}

.triage-static-guide.maybe {
  border-color: rgba(140, 103, 43, 0.28);
  background: var(--snowflake-warning-soft);
}

.triage-static-guide.rewrite {
  border-color: rgba(159, 63, 50, 0.25);
  background: var(--snowflake-danger-soft);
}

.triage-static-guide ol {
  margin: 0;
  padding-left: 18px;
}

.triage-repair-apply {
  justify-content: space-between;
  min-width: min(100%, 320px);
  border-left: 1px solid var(--snowflake-line);
  padding-left: 12px;
}

.control-input {
  width: 100%;
  min-height: 42px;
  border: 1px solid var(--snowflake-line);
  border-radius: 8px;
  background: #fff;
  color: var(--snowflake-ink);
  padding: 10px 12px;
}

textarea.control-input {
  min-height: 96px;
  resize: vertical;
}

.compact-textarea {
  min-height: 72px;
}

.mini-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  min-height: 34px;
  border: 1px solid var(--snowflake-line);
  border-radius: 999px;
  color: var(--snowflake-moss-deep);
  cursor: pointer;
  padding: 7px 12px;
}

.ghost {
  background: var(--snowflake-paper-strong);
}

.primary {
  background: var(--snowflake-moss);
  border-color: var(--snowflake-moss);
  color: #fff;
}

@media (max-width: 760px) {
  .scene-card-head,
  .triage-action-row,
  .triage-repair-apply {
    align-items: stretch;
    flex-direction: column;
  }

  .triage-structure-grid,
  .triage-detail-columns {
    grid-template-columns: 1fr;
  }

  .triage-repair-apply {
    border-left: 0;
    border-top: 1px solid var(--snowflake-line);
    padding-left: 0;
    padding-top: 10px;
  }
}
</style>
