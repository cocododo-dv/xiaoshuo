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
  actions: {
    type: Array,
    default: null,
  },
  tone: {
    type: String,
    default: "",
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
const effectiveTone = computed(() => props.tone || props.receipt?.status || "success");
const liveRole = computed(() => (effectiveTone.value === "error" ? "alert" : "status"));
const liveMode = computed(() => (effectiveTone.value === "error" ? "assertive" : "polite"));
const receiptActions = computed(() => props.actions || props.receipt?.actions || []);
const traceId = computed(() => props.receipt?.requestId || props.receipt?.clientRequestId || "");
const phaseLabel = computed(() => props.receipt?.phaseLabel || "");

function navigate() {
  if (props.receipt?.target && props.onNavigate) {
    props.onNavigate(props.receipt.target);
  }
}

function runAction(action) {
  if (typeof action?.onClick === "function") {
    action.onClick(props.receipt);
    return;
  }
  if (action?.target && props.onNavigate) {
    props.onNavigate(action.target);
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
    :role="liveRole"
    :aria-live="liveMode"
    :data-tone="effectiveTone"
    data-testid="flow-action-receipt"
  >
    <div class="flow-action-status">
      <span class="flow-action-dot" aria-hidden="true"></span>
      <span>{{ statusLabel }}</span>
    </div>
    <div class="flow-action-body">
      <strong>{{ receipt.actionLabel }}</strong>
      <p v-if="phaseLabel" class="flow-action-phase">{{ phaseLabel }}</p>
      <p class="flow-action-message">{{ receipt.message }}</p>
      <p v-if="receipt.nextStep" class="flow-action-next">{{ receipt.nextStep }}</p>
      <p v-if="traceId" class="flow-action-trace" data-testid="flow-action-trace">
        错误线索：<code>{{ traceId }}</code>
      </p>
    </div>
    <div v-if="receipt.target || receiptActions.length || onDismiss" class="flow-action-controls">
      <button
        v-if="receipt.target"
        type="button"
        class="ghost"
        data-testid="flow-action-target"
        @click="navigate"
      >
        {{ receipt.target.label || "打开" }}
      </button>
      <button
        v-for="(action, index) in receiptActions"
        :key="action.label || index"
        type="button"
        class="ghost"
        :data-testid="`flow-action-action-${index}`"
        @click="runAction(action)"
      >
        {{ action.label || "继续" }}
      </button>
      <button
        v-if="onDismiss"
        type="button"
        class="ghost"
        data-testid="flow-action-dismiss"
        @click="dismiss"
      >
        收起
      </button>
    </div>
  </aside>
</template>
