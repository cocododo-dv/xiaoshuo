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
  highlighted: {
    type: Boolean,
    default: false,
  },
  sourceActionLabel: {
    type: String,
    default: "",
  },
});

defineEmits(["approve", "release", "open-target"]);
</script>

<template>
  <article
    class="review-card"
    :class="{ 'focused-card': props.highlighted }"
    :data-testid="`review-card-${props.item.review_id}`"
  >
    <div class="review-meta">
      <span class="badge">{{ props.item.target_collection }}</span>
      <span class="muted">{{ props.item.review_id }}</span>
      <span v-if="props.sourceActionLabel" class="badge">{{ props.sourceActionLabel }}</span>
    </div>
    <h3>{{ props.item.candidate_text || "Empty candidate" }}</h3>
    <pre>{{ JSON.stringify(props.item.candidate_payload_json, null, 2) }}</pre>
    <div class="card-actions">
      <button
        :disabled="loading"
        :data-testid="`review-approve-${props.item.review_id}`"
        @click="$emit('approve', props.item.review_id)"
      >
        Approve
      </button>
      <button
        :disabled="loading || props.item.materialize_status !== 'succeeded'"
        :data-testid="`review-release-${props.item.review_id}`"
        @click="$emit('release', props.item.review_id)"
      >
        Release
      </button>
      <button
        class="ghost"
        :data-testid="`review-open-target-${props.item.review_id}`"
        @click='$emit("open-target", props.item.review_id)'
      >
        Open In Index
      </button>
    </div>
  </article>
</template>
