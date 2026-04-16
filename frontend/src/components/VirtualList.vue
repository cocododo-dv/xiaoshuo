<script setup>
import { computed, nextTick, onActivated, onBeforeUnmount, onDeactivated, ref, shallowRef, watch } from "vue";

import { buildHeightProfile, buildVirtualWindow, resolvePinnedIndexes } from "../lib/virtualList";

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
  mapItem: {
    type: Function,
    default: null,
  },
  mapVersion: {
    type: [String, Number, Boolean],
    default: "",
  },
});

const scrollTop = ref(0);
const measuredHeights = shallowRef({});
const rowElements = new Map();
const rowObservers = new Map();
const measureFrameId = ref(0);
const scrollFrameId = ref(0);
const pendingMeasurements = new Map();
const active = ref(true);
let pendingScrollTop = 0;
let objectMappedItems = new WeakMap();
let primitiveMappedItems = new Map();

const heightProfile = computed(() =>
  buildHeightProfile(props.items, props.itemKey, measuredHeights.value, props.estimatedItemHeight),
);
const pinnedIndexes = computed(() => resolvePinnedIndexes(props.items, props.itemKey, props.pinnedKeys));

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
    heightProfile: heightProfile.value,
    pinnedIndexes: pinnedIndexes.value,
  }),
);
const renderedEntries = computed(() => {
  if (!props.mapItem) {
    return windowState.value.renderedEntries;
  }

  return windowState.value.renderedEntries.map((entry) => ({
    ...entry,
    row: mapRenderedItem(entry.item, entry.index),
  }));
});

function resetMappedItemCache() {
  objectMappedItems = new WeakMap();
  primitiveMappedItems = new Map();
}

function mapRenderedItem(item, index) {
  if (!props.mapItem) {
    return item;
  }

  if (item !== null && (typeof item === "object" || typeof item === "function")) {
    const cached = objectMappedItems.get(item);
    if (
      cached?.index === index
      && Object.is(cached.version, props.mapVersion)
      && cached.mapper === props.mapItem
    ) {
      return cached.value;
    }
    const value = props.mapItem(item, index);
    objectMappedItems.set(item, {
      index,
      mapper: props.mapItem,
      version: props.mapVersion,
      value,
    });
    return value;
  }

  const primitiveKey = `${String(props.mapVersion)}:${index}:${typeof item}:${String(item)}`;
  const cached = primitiveMappedItems.get(primitiveKey);
  if (cached?.mapper === props.mapItem) {
    return cached.value;
  }
  const value = props.mapItem(item, index);
  primitiveMappedItems.set(primitiveKey, {
    mapper: props.mapItem,
    value,
  });
  return value;
}

function rowForEntry(entry) {
  return props.mapItem ? entry.row : entry.item;
}

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

function cancelScrollFrame() {
  if (!scrollFrameId.value) {
    return;
  }

  cancelAnimationFrame(scrollFrameId.value);
  scrollFrameId.value = 0;
}

function flushPendingMeasurements() {
  measureFrameId.value = 0;

  if (!active.value) {
    pendingMeasurements.clear();
    return;
  }

  const queuedMeasurements = [...pendingMeasurements.entries()];
  pendingMeasurements.clear();
  let nextHeights = measuredHeights.value;
  let changed = false;

  queuedMeasurements.forEach(([key, element]) => {
    if (!element?.isConnected) {
      return;
    }

    const roundedHeight = normalizedMeasuredHeight(element.offsetHeight);
    if (shouldCommitMeasuredHeight(nextHeights, key, roundedHeight)) {
      if (!changed) {
        nextHeights = { ...nextHeights };
        changed = true;
      }
      nextHeights[key] = roundedHeight;
    }
  });

  if (changed) {
    measuredHeights.value = nextHeights;
  }
}

function normalizedMeasuredHeight(height) {
  return Math.max(Math.round(height), 1);
}

function shouldCommitMeasuredHeight(heights, key, roundedHeight) {
  if (key === null || key === undefined) {
    return false;
  }

  const currentHeight = heights[key];
  if (currentHeight && Math.abs(currentHeight - roundedHeight) <= 1) {
    return false;
  }

  return true;
}

function queueMeasure(key, element) {
  if (!active.value) {
    return;
  }

  pendingMeasurements.set(key, element);

  if (measureFrameId.value) {
    return;
  }

  measureFrameId.value = requestAnimationFrame(() => {
    flushPendingMeasurements();
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
  pendingScrollTop = event.target.scrollTop;

  if (scrollFrameId.value) {
    return;
  }

  scrollFrameId.value = requestAnimationFrame(() => {
    scrollFrameId.value = 0;
    if (!active.value) {
      return;
    }
    scrollTop.value = pendingScrollTop;
  });
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
  () => [props.items, props.mapItem, props.mapVersion],
  () => {
    resetMappedItemCache();
  },
);

watch(
  windowState,
  async () => {
    await nextTick();

    if (!active.value) {
      return;
    }

    renderedEntries.value.forEach((entry) => {
      const element = rowElements.get(entry.key);
      if (element) {
        queueMeasure(entry.key, element);
      }
    });
  },
  { immediate: true },
);

onActivated(async () => {
  active.value = true;
  await nextTick();

  renderedEntries.value.forEach((entry) => {
    const element = rowElements.get(entry.key);
    if (element?.isConnected) {
      queueMeasure(entry.key, element);
    }
  });
});

onDeactivated(() => {
  active.value = false;
  cancelMeasureFrame();
  cancelScrollFrame();
  pendingMeasurements.clear();
});

onBeforeUnmount(() => {
  cancelMeasureFrame();
  cancelScrollFrame();
  pendingMeasurements.clear();
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
    @scroll.passive="handleScroll"
  >
    <div
      v-if="windowState.virtualized"
      class="virtual-list-spacer"
      :style="{ height: `${windowState.totalHeight}px`, position: 'relative' }"
    >
      <div
        v-for="entry in renderedEntries"
        :key="entry.key"
        class="virtual-list-row"
        :ref="rowRef(entry)"
        :style="{
          position: 'absolute',
          top: '0',
          left: '0',
          right: '0',
          transform: `translateY(${entry.offsetTop}px)`,
        }"
      >
        <slot :item="entry.item" :row="rowForEntry(entry)" :entry="entry" :virtualized="true" />
      </div>
    </div>
    <template v-else>
      <div
        v-for="entry in renderedEntries"
        :key="entry.key"
        class="virtual-list-row"
        :ref="rowRef(entry)"
      >
        <slot :item="entry.item" :row="rowForEntry(entry)" :entry="entry" :virtualized="false" />
      </div>
    </template>
  </div>
</template>
