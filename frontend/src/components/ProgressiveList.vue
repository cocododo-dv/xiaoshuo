<script setup>
import { computed, onActivated, onBeforeUnmount, onDeactivated, ref, watch } from "vue";

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
const active = ref(true);

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

  if (!active.value || !pending.value) {
    return;
  }

  frameId.value = requestAnimationFrame(() => {
    frameId.value = 0;
    renderedCount.value = nextProgressiveCount({
      renderedCount: renderedCount.value,
      itemCount: props.items.length,
      batchSize: plan.value.batchSize,
    });

    if (active.value && pending.value) {
      scheduleNextFrame();
    }
  });
}

watch(
  plan,
  (nextPlan) => {
    cancelFrame();
    renderedCount.value = nextPlan.renderedCount;

    if (active.value && nextPlan.pending) {
      scheduleNextFrame();
    }
  },
  { immediate: true },
);

onActivated(() => {
  active.value = true;

  if (pending.value) {
    scheduleNextFrame();
  }
});

onDeactivated(() => {
  active.value = false;
  cancelFrame();
});

onBeforeUnmount(() => {
  cancelFrame();
});
</script>

<template>
  <div
    class="progressive-list"
    :data-testid="props.testId || undefined"
  >
    <slot
      :items="renderedItems"
      :rendered-count="renderedCount"
      :total-count="props.items.length"
      :pending="pending"
    />
  </div>
</template>
