<script setup>
const props = defineProps({
  title: {
    type: String,
    required: true,
  },
  description: {
    type: String,
    default: "",
  },
  summary: {
    type: String,
    default: "",
  },
  badge: {
    type: String,
    default: "",
  },
  expanded: {
    type: Boolean,
    default: false,
  },
  loading: {
    type: Boolean,
    default: false,
  },
  testId: {
    type: String,
    default: "",
  },
  toggleTestId: {
    type: String,
    default: "",
  },
});

defineEmits(["toggle"]);
</script>

<template>
  <article
    class="paper receipt-card activity-section-card"
    :data-testid="props.testId || undefined"
  >
    <div class="receipt-head activity-section-head">
      <div>
        <h3>{{ props.title }}</h3>
        <p v-if="props.description" class="muted receipt-copy">{{ props.description }}</p>
        <p v-if="props.summary" class="muted activity-section-summary">{{ props.summary }}</p>
      </div>
      <div class="activity-section-actions">
        <span v-if="props.badge" class="badge">{{ props.badge }}</span>
        <button
          type="button"
          class="ghost"
          :data-testid="props.toggleTestId || undefined"
          @click="$emit('toggle')"
        >
          {{ props.expanded ? "收起" : "展开" }}
        </button>
      </div>
    </div>

    <div v-if="props.expanded" class="receipt-detail">
      <div v-if="props.loading" class="empty">正在加载...</div>
      <slot v-else />
    </div>
  </article>
</template>
