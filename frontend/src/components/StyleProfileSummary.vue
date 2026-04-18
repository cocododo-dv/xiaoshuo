<script setup>
const props = defineProps({
  summary: {
    type: Object,
    default: null,
  },
  testId: {
    type: String,
    default: "style-profile-summary",
  },
});
</script>

<template>
  <section
    v-if="props.summary?.available"
    class="style-profile-summary"
    :data-testid="props.testId"
  >
    <div class="style-profile-summary-head">
      <div>
        <strong>风格画像</strong>
        <p class="muted">结构化文风特征</p>
      </div>
      <span class="badge">{{ props.summary.contractVersion || "style_profile" }}</span>
    </div>

    <ol class="style-profile-feature-list">
      <li v-for="feature in props.summary.featureRows" :key="feature.key">
        <span>{{ feature.label }}</span>
        <small>{{ feature.guidance.join("；") }}</small>
      </li>
    </ol>

    <p v-if="props.summary.calibrationLines.length" class="muted style-profile-footnote">
      校准句：{{ props.summary.calibrationLines.join("；") }}
    </p>
    <p v-if="props.summary.bannedMoves.length" class="muted style-profile-footnote">
      禁用动作：{{ props.summary.bannedMoves.join("；") }}
    </p>
  </section>
</template>
