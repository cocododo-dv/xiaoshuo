<script setup>
defineProps({
  items: {
    type: Array,
    default: () => [],
  },
});
</script>

<template>
  <div class="drawer-body">
    <div v-if="!items.length" class="empty">No human review events are queued.</div>
    <article v-for="item in items" :key="item.event_id || item.status" class="paper mini">
      <h3>{{ item.event_source }}</h3>
      <p class="muted">Status: {{ item.status }}</p>
      <p class="muted">Actions: {{ (item.allowed_actions_json || []).join(" / ") || "-" }}</p>
    </article>
  </div>
</template>
