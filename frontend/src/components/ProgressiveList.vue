<script setup>
import { computed, onBeforeUnmount, ref, watch } from "vue";

import { buildProgressivePlan, nextProgressiveCount } from "../lib/progressiveList";

const props = defineProps({
  items: {
    type: Array,
    default: () => [],
  },
  enabled: {
    type: Boolean,
    default: true,
  },
  initialCount: {
    type: Number,
    default: 8,
  },
  batchSize: {
    type: Number,
    default: 8,
  },
  threshold: {
    type: Number,
    default: 12,
  },
  testId: {
    type: String,
    default: "",
  },
});

const renderedCount = ref(0);
const frameId = ref(0);

const plan = computed(() =>
  buildProgressivePlan({
    items: props.items,
    enabled: props.enabled,
    initialCount: props.initialCount,
    batchSize: props.batchSize,
    threshold: props.threshold,
  }),
);

const renderedItems = computed(() => props.items.slice(0, renderedCount.value));
const pending = computed(() => renderedCount.value < props.items.length);

function cancelFrame() {
  if (!frameId.value) {
    return;
  }

  cancelAnimationFrame(frameId.value);
  frameId.value = 0;
}

function scheduleNextFrame() {
  cancelFrame();

  if (!pending.value) {
    return;
  }

  frameId.value = requestAnimationFrame(() => {
    frameId.value = 0;
    renderedCount.value = nextProgressiveCount({
      renderedCount: renderedCount.value,
      itemCount: props.items.length,
      batchSize: plan.value.batchSize,
    });

    if (pending.value) {
      scheduleNextFrame();
    }
  });
}

watch(
  plan,
  (nextPlan) => {
    cancelFrame();
    renderedCount.value = nextPlan.renderedCount;

    if (nextPlan.pending) {
      scheduleNextFrame();
    }
  },
  { immediate: true },
);

onBeforeUnmount(() => {
  cancelFrame();
});
</script>

<template>
  <div :data-testid="props.testId || undefined">
    <slot
      :items="renderedItems"
      :rendered-count="renderedCount"
      :total-count="props.items.length"
      :pending="pending"
    />
  </div>
</template>
