<script setup>
import { computed } from "vue";

const props = defineProps({
  receipt: {
    type: Object,
    default: null,
  },
  compact: {
    type: Boolean,
    default: false,
  },
  onNavigate: {
    type: Function,
    default: null,
  },
  onDismiss: {
    type: Function,
    default: null,
  },
});

const statusLabel = computed(() => {
  if (props.receipt?.status === "running") {
    return "处理中";
  }
  if (props.receipt?.status === "error") {
    return "失败";
  }
  return "成功";
});

function navigate() {
  if (props.receipt?.target && props.onNavigate) {
    props.onNavigate(props.receipt.target);
  }
}

function dismiss() {
  if (props.onDismiss) {
    props.onDismiss(props.receipt);
  }
}
</script>

<template>
  <aside
    v-if="receipt"
    class="flow-action-receipt"
    :class="[`flow-action-${receipt.status || 'success'}`, { compact }]"
    aria-live="polite"
    data-testid="flow-action-receipt"
  >
    <div class="flow-action-status">
      <span class="flow-action-dot" aria-hidden="true"></span>
      <span>{{ statusLabel }}</span>
    </div>
    <div class="flow-action-body">
      <strong>{{ receipt.actionLabel }}</strong>
      <p class="flow-action-message">{{ receipt.message }}</p>
      <p v-if="receipt.nextStep" class="flow-action-next">{{ receipt.nextStep }}</p>
    </div>
    <div v-if="receipt.target || onDismiss" class="flow-action-controls">
      <button
        v-if="receipt.target"
        type="button"
        class="ghost"
        data-testid="flow-action-target"
        @click="navigate"
      >
        {{ receipt.target.label || "打开" }}
      </button>
      <button v-if="onDismiss" type="button" class="ghost" @click="dismiss">收起</button>
    </div>
  </aside>
</template>
