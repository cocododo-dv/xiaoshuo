<script setup>
import { ref } from "vue";

defineProps({
  text: {
    type: String,
    required: true,
  },
});

const tipId = `tip-${Math.random().toString(36).slice(2, 8)}`;
const open = ref(false);
</script>

<template>
  <span class="base-tooltip" @mouseenter="open = true" @mouseleave="open = false">
    <span
      class="base-tooltip-trigger"
      tabindex="0"
      :aria-describedby="tipId"
      @focus="open = true"
      @blur="open = false"
    >
      <slot />
    </span>
    <span
      :id="tipId"
      role="tooltip"
      class="base-tooltip-bubble"
      :class="{ 'is-open': open }"
    >
      {{ text }}
    </span>
  </span>
</template>

<style scoped>
.base-tooltip {
  position: relative;
  display: inline-flex;
}

.base-tooltip-trigger {
  display: inline-flex;
  align-items: center;
  border-bottom: 1px dotted currentColor;
  cursor: help;
}

.base-tooltip-trigger:focus-visible {
  outline: none;
  box-shadow: var(--focus-ring, 0 0 0 3px rgba(163, 63, 47, 0.15));
  border-radius: 2px;
}

.base-tooltip-bubble {
  position: absolute;
  bottom: calc(100% + 0.4rem);
  left: 50%;
  z-index: 40;
  width: max-content;
  max-width: 18rem;
  padding: 0.45rem 0.6rem;
  border-radius: var(--radius-control, 8px);
  background: var(--color-rail, #223039);
  color: #fbf5ea;
  font-size: 0.78rem;
  font-weight: 600;
  line-height: 1.4;
  white-space: normal;
  transform: translate(-50%, 0.25rem);
  opacity: 0;
  pointer-events: none;
  transition: opacity var(--transition-fast, 120ms ease), transform var(--transition-fast, 120ms ease);
}

.base-tooltip-bubble.is-open {
  opacity: 1;
  transform: translate(-50%, 0);
}
</style>
