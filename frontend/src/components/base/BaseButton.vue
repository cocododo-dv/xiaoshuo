<script setup>
defineProps({
  variant: {
    type: String,
    default: "secondary",
    validator: (value) => ["primary", "secondary", "ghost", "danger"].includes(value),
  },
  size: {
    type: String,
    default: "md",
    validator: (value) => ["sm", "md"].includes(value),
  },
  type: {
    type: String,
    default: "button",
  },
  loading: {
    type: Boolean,
    default: false,
  },
  disabled: {
    type: Boolean,
    default: false,
  },
  block: {
    type: Boolean,
    default: false,
  },
});
</script>

<template>
  <button
    :type="type"
    class="base-btn"
    :class="[`base-btn-${variant}`, `base-btn-${size}`, { 'base-btn-block': block, 'base-btn-loading': loading }]"
    :disabled="disabled || loading"
    :aria-busy="loading ? 'true' : undefined"
  >
    <span v-if="loading" class="base-btn-spinner" aria-hidden="true" />
    <span v-if="$slots.icon" class="base-btn-icon" aria-hidden="true"><slot name="icon" /></span>
    <span class="base-btn-label"><slot /></span>
  </button>
</template>

<style scoped>
.base-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 0.45rem;
  min-height: 2.5rem;
  min-width: 0;
  padding: 0.55rem 1.15rem;
  border: 1px solid transparent;
  border-radius: var(--radius-pill, 999px);
  font: inherit;
  font-weight: 700;
  line-height: 1.2;
  cursor: pointer;
  transition: background var(--transition-fast, 120ms ease), border-color var(--transition-fast, 120ms ease),
    color var(--transition-fast, 120ms ease);
}

.base-btn-sm {
  min-height: 2rem;
  padding: 0.32rem 0.75rem;
  font-size: 0.82rem;
}

.base-btn-block {
  display: flex;
  width: 100%;
}

.base-btn:focus-visible {
  outline: none;
  box-shadow: var(--shadow-focus, 0 0 0 3px rgba(163, 63, 47, 0.15));
}

.base-btn-primary {
  background: var(--button-primary-bg, #253342);
  color: #fbf5ea;
}

.base-btn-primary:hover:not(:disabled) {
  background: var(--button-primary-hover, #364a60);
}

.base-btn-secondary {
  background: var(--button-secondary-bg, rgba(37, 51, 66, 0.1));
  border-color: var(--button-secondary-border, rgba(37, 51, 66, 0.16));
  color: var(--button-secondary-text, #253342);
}

.base-btn-secondary:hover:not(:disabled) {
  background: var(--button-secondary-hover, rgba(37, 51, 66, 0.16));
}

.base-btn-ghost {
  background: transparent;
  border-color: var(--surface-line, rgba(33, 26, 21, 0.15));
  color: var(--surface-text, #211a15);
}

.base-btn-ghost:hover:not(:disabled) {
  background: var(--surface-raised, rgba(255, 255, 255, 0.72));
}

.base-btn-danger {
  background: var(--danger-bg, #9f3a2d);
  color: #fbf5ea;
}

.base-btn-danger:hover:not(:disabled) {
  background: var(--danger-hover, #bc4b3a);
}

.base-btn:disabled {
  background: var(--button-disabled-bg, rgba(37, 51, 66, 0.16));
  border-color: transparent;
  color: var(--button-disabled-text, rgba(33, 26, 21, 0.48));
  cursor: not-allowed;
}

.base-btn-loading {
  cursor: progress;
}

.base-btn-spinner {
  width: 0.95em;
  height: 0.95em;
  border: 2px solid currentColor;
  border-right-color: transparent;
  border-radius: 50%;
  animation: base-btn-spin 0.7s linear infinite;
}

.base-btn-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 1.05em;
  height: 1.05em;
  flex: 0 0 auto;
}

.base-btn-icon :deep(svg) {
  display: block;
  width: 1em;
  height: 1em;
  stroke-width: 2;
}

.base-btn-label {
  min-width: 0;
  overflow-wrap: anywhere;
}

@keyframes base-btn-spin {
  to {
    transform: rotate(360deg);
  }
}

@media (prefers-reduced-motion: reduce) {
  .base-btn-spinner {
    animation-duration: 1.4s;
  }
}
</style>
