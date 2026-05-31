<script setup>
import { computed, nextTick, ref, watch } from "vue";
import { Sparkles, X } from "lucide-vue-next";

import { useFocusTrap } from "../composables/useFocusTrap";

const props = defineProps({
  open: {
    type: Boolean,
    default: false,
  },
  step: {
    type: Object,
    default: null,
  },
});

const emit = defineEmits(["close", "confirm", "draft-assistant"]);
const reason = ref("");
const reasonInput = ref(null);

// PR-21 a11y — focus trap:Tab/Shift+Tab 在 dialog 内循环(esc 关闭 + open 聚焦 textarea 自留)
const dialogEl = ref(null);
const { onTab } = useFocusTrap(dialogEl);

const canConfirm = computed(() => Boolean(reason.value.trim()));

watch(
  () => props.open,
  async (open) => {
    if (!open) {
      reason.value = "";
      return;
    }
    await nextTick();
    reasonInput.value?.focus?.();
  },
);

function close() {
  emit("close");
}

function confirm() {
  if (!canConfirm.value) {
    reasonInput.value?.focus?.();
    return;
  }
  emit("confirm", reason.value.trim());
}
</script>

<template>
  <div
    v-if="open"
    class="snowflake-skip-dialog-backdrop"
    data-testid="snowflake-skip-dialog"
    @click.self="close"
    @keydown.esc="close"
  >
    <section
      ref="dialogEl"
      class="snowflake-skip-dialog"
      role="dialog"
      aria-modal="true"
      aria-labelledby="snowflake-skip-dialog-title"
      tabindex="-1"
      @keydown.tab="onTab"
    >
      <div class="panel-head">
        <div>
          <span class="eyebrow">暂时绕过</span>
          <h2 id="snowflake-skip-dialog-title">确认要先跳过这一步吗？</h2>
          <p class="muted">{{ step?.label || "当前雪花步骤" }} 之后仍可回头补齐。</p>
        </div>
        <button type="button" class="icon-btn" aria-label="关闭" @click="close">
          <X :size="16" />
        </button>
      </div>

      <div class="snowflake-skip-impact">
        <strong>跳过后的影响</strong>
        <p>系统会记录原因；整理章节结构前，准备度检查仍会提醒这一步带来的风险。</p>
      </div>

      <label class="field-block">
        <span>跳过原因</span>
        <textarea
          ref="reasonInput"
          v-model="reason"
          class="control-input"
          placeholder="例如：这一层信息已经在上一层大纲里明确，先继续推进场景规划。"
          @keydown.ctrl.enter.prevent="confirm"
          @keydown.meta.enter.prevent="confirm"
        />
      </label>

      <div class="snowflake-skip-dialog-actions">
        <button type="button" class="ghost action-btn" @click="close">返回补齐</button>
        <button type="button" class="ghost action-btn" @click="emit('draft-assistant')">
          <Sparkles :size="16" />
          <span>让助手补一版草稿</span>
        </button>
        <button type="button" class="primary action-btn" :disabled="!canConfirm" @click="confirm">
          保存原因并暂时跳过
        </button>
      </div>
    </section>
  </div>
</template>

<style scoped>
.snowflake-skip-dialog-backdrop {
  position: fixed;
  inset: 0;
  z-index: 60;
  display: grid;
  place-items: center;
  background: rgba(21, 38, 32, 0.32);
  padding: 16px;
}

.snowflake-skip-dialog {
  display: grid;
  gap: 14px;
  width: min(560px, 100%);
  max-height: min(90vh, 720px);
  overflow: auto;
  border: 1px solid var(--snowflake-line);
  border-radius: 8px;
  background: var(--snowflake-panel);
  box-shadow: 0 24px 70px rgba(21, 38, 32, 0.28);
  color: var(--snowflake-ink);
  padding: 16px;
}

.snowflake-skip-impact {
  display: grid;
  gap: 6px;
  border: 1px solid rgba(140, 103, 43, 0.28);
  border-radius: 8px;
  background: var(--snowflake-warning-soft);
  padding: 12px;
}

.snowflake-skip-impact p {
  margin: 0;
  color: var(--snowflake-muted);
}

.snowflake-skip-dialog-actions {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 8px;
}

@media (max-width: 640px) {
  .snowflake-skip-dialog-actions {
    align-items: stretch;
    flex-direction: column;
  }

  .snowflake-skip-dialog-actions button {
    width: 100%;
  }
}
</style>
