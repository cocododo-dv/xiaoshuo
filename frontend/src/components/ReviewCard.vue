<script setup>
const props = defineProps({
  item: {
    type: Object,
    required: true,
  },
  loading: {
    type: Boolean,
    default: false,
  },
});

defineEmits(["approve", "release"]);
</script>

<template>
  <article class="review-card">
    <div class="review-meta">
      <span class="badge">{{ props.item.target_collection }}</span>
      <span class="muted">{{ props.item.review_id }}</span>
    </div>
    <h3>{{ props.item.candidate_text || "Empty candidate" }}</h3>
    <pre>{{ JSON.stringify(props.item.candidate_payload_json, null, 2) }}</pre>
    <div class="card-actions">
      <button :disabled="loading" @click="$emit('approve', props.item.review_id)">Approve</button>
      <button
        :disabled="loading || props.item.materialize_status !== 'succeeded'"
        @click="$emit('release', props.item.review_id)"
      >
        Release
      </button>
    </div>
  </article>
</template>
