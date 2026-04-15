<script setup>
import { computed, nextTick, onBeforeUnmount, ref, watch } from "vue";

import { buildVirtualWindow } from "../lib/virtualList";

const props = defineProps({
  items: {
    type: Array,
    default: () => [],
  },
  itemKey: {
    type: [String, Function],
    required: true,
  },
  estimatedItemHeight: {
    type: Number,
    default: 160,
  },
  overscan: {
    type: Number,
    default: 2,
  },
  threshold: {
    type: Number,
    default: 20,
  },
  pinnedKeys: {
    type: Array,
    default: () => [],
  },
  testId: {
    type: String,
    default: "",
  },
  viewportHeight: {
    type: Number,
    default: 720,
  },
});

const scrollTop = ref(0);
const measuredHeights = ref({});
const rowElements = new Map();
const rowObservers = new Map();
const measureFrameId = ref(0);

const windowState = computed(() =>
  buildVirtualWindow({
    items: props.items,
    itemKey: props.itemKey,
    viewportHeight: props.viewportHeight,
    scrollTop: scrollTop.value,
    estimatedItemHeight: props.estimatedItemHeight,
    overscan: props.overscan,
    threshold: props.threshold,
    measuredHeights: measuredHeights.value,
    pinnedKeys: props.pinnedKeys,
  }),
);

function resolveItemKey(item) {
  if (typeof props.itemKey === "function") {
    return props.itemKey(item);
  }

  return item?.[props.itemKey];
}

function cancelMeasureFrame() {
  if (!measureFrameId.value) {
    return;
  }

  cancelAnimationFrame(measureFrameId.value);
  measureFrameId.value = 0;
}

function commitMeasuredHeight(key, height) {
  if (key === null || key === undefined) {
    return;
  }

  const roundedHeight = Math.max(Math.round(height), 1);
  const currentHeight = measuredHeights.value[key];
  if (currentHeight && Math.abs(currentHeight - roundedHeight) <= 1) {
    return;
  }

  measuredHeights.value = {
    ...measuredHeights.value,
    [key]: roundedHeight,
  };
}

function queueMeasure(key, element) {
  cancelMeasureFrame();
  measureFrameId.value = requestAnimationFrame(() => {
    measureFrameId.value = 0;

    if (!element?.isConnected) {
      return;
    }

    commitMeasuredHeight(key, element.offsetHeight);
  });
}

function cleanupRow(key) {
  const observer = rowObservers.get(key);
  if (observer) {
    observer.disconnect();
    rowObservers.delete(key);
  }
  rowElements.delete(key);
}

function bindRowElement(key, element) {
  if (rowElements.get(key) === element) {
    return;
  }

  cleanupRow(key);
  if (!element) {
    return;
  }

  rowElements.set(key, element);
  queueMeasure(key, element);

  if (typeof ResizeObserver === "undefined") {
    return;
  }

  const observer = new ResizeObserver(() => {
    queueMeasure(key, element);
  });
  observer.observe(element);
  rowObservers.set(key, observer);
}

function rowRef(entry) {
  return (element) => {
    bindRowElement(entry.key, element);
  };
}

function handleScroll(event) {
  scrollTop.value = event.target.scrollTop;
}

watch(
  () => props.items,
  (items) => {
    const activeKeys = new Set(items.map((item) => String(resolveItemKey(item))));
    measuredHeights.value = Object.fromEntries(
      Object.entries(measuredHeights.value).filter(([key]) => activeKeys.has(key)),
    );
  },
  { deep: false },
);

watch(
  windowState,
  async () => {
    await nextTick();
    windowState.value.renderedEntries.forEach((entry) => {
      const element = rowElements.get(entry.key);
      if (element) {
        queueMeasure(entry.key, element);
      }
    });
  },
  { immediate: true },
);

onBeforeUnmount(() => {
  cancelMeasureFrame();
  rowObservers.forEach((observer) => observer.disconnect());
  rowObservers.clear();
  rowElements.clear();
});
</script>

<template>
  <div
    class="virtual-list"
    :data-testid="props.testId || undefined"
    :style="{ maxHeight: `${props.viewportHeight}px`, overflowY: 'auto', position: 'relative' }"
    @scroll="handleScroll"
  >
    <div
      v-if="windowState.virtualized"
      :style="{ height: `${windowState.totalHeight}px`, position: 'relative' }"
    >
      <div
        v-for="entry in windowState.renderedEntries"
        :key="entry.key"
        :ref="rowRef(entry)"
        :style="{
          position: 'absolute',
          top: `${entry.offsetTop}px`,
          left: '0',
          right: '0',
        }"
      >
        <slot :item="entry.item" :entry="entry" :virtualized="true" />
      </div>
    </div>
    <template v-else>
      <div
        v-for="entry in windowState.renderedEntries"
        :key="entry.key"
        :ref="rowRef(entry)"
      >
        <slot :item="entry.item" :entry="entry" :virtualized="false" />
      </div>
    </template>
  </div>
</template>
