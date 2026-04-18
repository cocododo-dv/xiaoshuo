<script setup>
const props = defineProps({
  risk: {
    type: Object,
    default: null,
  },
  testId: {
    type: String,
    default: "style-profile-risk-warning",
  },
});
</script>

<template>
  <aside
    v-if="props.risk?.available"
    class="style-profile-risk-warning"
    :class="`style-profile-risk-warning-${props.risk.severity}`"
    :data-testid="props.testId"
  >
    <div class="style-profile-risk-mark">!</div>
    <div>
      <strong>{{ props.risk.title }}</strong>
      <p v-for="reason in props.risk.reasons" :key="reason">{{ reason }}</p>
      <small>{{ props.risk.actionHint }}</small>
    </div>
  </aside>
</template>
