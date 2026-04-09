<script setup>
defineProps({
  eyebrow: {
    type: String,
    required: true,
  },
  title: {
    type: String,
    required: true,
  },
  description: {
    type: String,
    default: "",
  },
});
</script>

<template>
  <section class="panel">
    <header class="panel-head">
      <div>
        <div class="eyebrow">{{ eyebrow }}</div>
        <h2>{{ title }}</h2>
        <p v-if="description" class="panel-copy">{{ description }}</p>
      </div>
      <div v-if="$slots.actions" class="actions">
        <slot name="actions" />
      </div>
    </header>
    <slot />
  </section>
</template>
