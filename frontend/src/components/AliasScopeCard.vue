<script setup>
defineProps({
  item: {
    type: Object,
    required: true,
  },
});
</script>

<template>
  <article class="paper">
    <h3>{{ item.alias_scope }}</h3>
    <p><strong>Active</strong> {{ item.active_alias || "-" }}</p>
    <p><strong>Candidate</strong> {{ item.candidate_alias || "-" }}</p>
    <p class="muted">Verify: {{ item.verify_status }}</p>
    <p class="muted">
      Embedding: {{ item.active_embedding_version || "-" }} / {{ item.candidate_embedding_version || "-" }}
    </p>
  </article>
</template>
