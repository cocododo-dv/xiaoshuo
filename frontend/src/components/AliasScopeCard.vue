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
    <p class="muted">{{ item.object_type }} / {{ item.scope }} / {{ item.scope_ref_id || "-" }}</p>
    <p><strong>Collection Family</strong> {{ item.collection_family }}</p>
    <p><strong>Active</strong> {{ item.active_alias || "-" }}</p>
    <p><strong>Candidate</strong> {{ item.candidate_alias || "-" }}</p>
    <p class="muted">
      Snapshot: {{ item.active_snapshot_version || "-" }} / {{ item.candidate_snapshot_version || "-" }}
    </p>
    <p class="muted">Verify: {{ item.verify_status }}</p>
    <p class="muted">
      Embedding: {{ item.active_embedding_version || "-" }} / {{ item.candidate_embedding_version || "-" }}
    </p>
    <p class="muted">Sample query success: {{ item.sample_query_success ? "yes" : "no" }}</p>
    <p class="muted">Updated: {{ item.updated_at || "-" }}</p>

    <div v-if="item.recent_fault_summary" class="fault-summary">
      <div class="fault-head">
        <strong>Latest alias fault</strong>
        <span class="badge">{{ item.recent_fault_summary.severity }}</span>
      </div>
      <p class="muted">{{ item.recent_fault_summary.created_at }}</p>
      <pre>{{ JSON.stringify(item.recent_fault_summary.details_json, null, 2) }}</pre>
    </div>
  </article>
</template>
