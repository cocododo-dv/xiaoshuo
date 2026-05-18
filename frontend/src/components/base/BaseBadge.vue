<script setup>
defineProps({
  tone: {
    type: String,
    default: "neutral",
    validator: (value) => ["neutral", "info", "success", "warning", "danger", "accent"].includes(value),
  },
});
</script>

<template>
  <span class="base-badge" :class="`base-badge-${tone}`"><slot /></span>
</template>

<style scoped>
.base-badge {
  display: inline-flex;
  align-items: center;
  gap: 0.3rem;
  width: fit-content;
  max-width: 100%;
  min-height: 1.55rem;
  padding: 0.16rem 0.5rem;
  border: 1px solid transparent;
  border-radius: var(--radius-pill, 999px);
  font-size: 0.74rem;
  font-weight: 700;
  line-height: 1.2;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.base-badge-neutral {
  border-color: var(--button-secondary-border, rgba(37, 51, 66, 0.16));
  background: var(--button-secondary-bg, rgba(37, 51, 66, 0.08));
  color: var(--button-secondary-text, rgba(37, 51, 66, 0.78));
}

.base-badge-info {
  border-color: rgba(49, 90, 115, 0.22);
  background: rgba(49, 90, 115, 0.12);
  color: #285063;
}

.base-badge-success {
  border-color: rgba(47, 111, 98, 0.24);
  background: rgba(47, 111, 98, 0.14);
  color: var(--color-primary-strong, #24564d);
}

.base-badge-warning {
  border-color: rgba(176, 122, 31, 0.26);
  background: rgba(176, 122, 31, 0.14);
  color: color-mix(in srgb, var(--color-warning, #b07a1f) 72%, #1b1815);
}

.base-badge-danger {
  border-color: rgba(159, 58, 45, 0.26);
  background: rgba(159, 58, 45, 0.13);
  color: color-mix(in srgb, var(--color-danger, #9f3a2d) 78%, #1b1815);
}

.base-badge-accent {
  border-color: rgba(163, 63, 47, 0.26);
  background: rgba(163, 63, 47, 0.13);
  color: color-mix(in srgb, var(--color-accent, #a33f2f) 78%, #1b1815);
}
</style>
