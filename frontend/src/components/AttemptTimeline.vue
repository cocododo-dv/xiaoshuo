<script setup>
defineProps({
  items: {
    type: Array,
    default: () => [],
  },
});
</script>

<template>
  <div class="timeline">
    <div v-if="!items.length" class="empty">No attempts recorded yet.</div>
    <div v-for="item in items" :key="item.attempt_id || item.step" class="attempt">
      <div class="attempt-step">{{ item.step }}</div>
      <div class="attempt-body">
        <div>{{ item.status }}</div>
        <div class="muted">{{ item.source_bundle_id || "pre-bundle" }}</div>
      </div>
    </div>
  </div>
</template>
