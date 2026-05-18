<script setup>
defineProps({
  title: {
    type: String,
    default: "",
  },
  description: {
    type: String,
    default: "",
  },
});
</script>

<template>
  <div class="base-empty">
    <div v-if="$slots.icon" class="base-empty-icon" aria-hidden="true"><slot name="icon" /></div>
    <strong v-if="title" class="base-empty-title">{{ title }}</strong>
    <p v-if="description" class="base-empty-desc">{{ description }}</p>
    <p v-if="$slots.default" class="base-empty-desc"><slot /></p>
    <div v-if="$slots.action" class="base-empty-action"><slot name="action" /></div>
  </div>
</template>

<style scoped>
.base-empty {
  display: grid;
  justify-items: center;
  gap: 0.5rem;
  padding: 1.6rem 1.2rem;
  border: 1px dashed var(--surface-line, rgba(33, 26, 21, 0.15));
  border-radius: var(--radius-panel, 8px);
  background: color-mix(in srgb, var(--color-panel-solid, #fffdf7) 76%, transparent);
  text-align: center;
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.54);
}

.base-empty-icon {
  display: inline-flex;
  opacity: 0.65;
}

.base-empty-title {
  color: var(--surface-heading, #16110e);
  font-family: var(--font-display, serif);
  font-size: 1rem;
}

.base-empty-desc {
  margin: 0;
  max-width: 32rem;
  color: var(--surface-muted, rgba(33, 26, 21, 0.72));
  line-height: 1.5;
  overflow-wrap: anywhere;
}

.base-empty-action {
  margin-top: 0.35rem;
}
</style>
