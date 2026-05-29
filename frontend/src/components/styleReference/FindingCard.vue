<script setup>
import BaseBadge from "../base/BaseBadge.vue";
import BaseButton from "../base/BaseButton.vue";

defineProps({
  finding: {
    type: Object,
    required: true,
  },
  busy: {
    type: Boolean,
    default: false,
  },
});

const emit = defineEmits(["review"]);

function review(decision) {
  emit("review", decision);
}
</script>

<template>
  <article
    class="finding-card"
    :class="`finding-kind-${finding.finding_kind}`"
    :data-testid="`reference-finding-${finding.finding_id}`"
  >
    <header class="card-head">
      <BaseBadge :tone="finding.finding_kind === 'forbidden_pattern' ? 'danger' : 'success'">
        {{ finding.finding_kind === "forbidden_pattern" ? "禁忌" : "正向" }}
      </BaseBadge>
      <BaseBadge :tone="finding.confidence === 'high' ? 'success' : finding.confidence === 'low' ? 'warning' : 'info'">
        {{ finding.confidence || "medium" }}
      </BaseBadge>
      <BaseBadge :tone="finding.status === 'approved' ? 'success' : finding.status === 'rejected' ? 'danger' : 'neutral'">
        {{ finding.status }}
      </BaseBadge>
    </header>
    <p class="card-statement">{{ finding.statement }}</p>
    <footer class="card-actions">
      <BaseButton
        v-if="finding.status !== 'approved'"
        variant="primary"
        size="sm"
        :loading="busy"
        :data-testid="`reference-approve-${finding.finding_id}`"
        @click="review('approved')"
      >通过</BaseButton>
      <BaseButton
        v-if="finding.status !== 'rejected'"
        variant="danger"
        size="sm"
        :loading="busy"
        :data-testid="`reference-reject-${finding.finding_id}`"
        @click="review('rejected')"
      >驳回</BaseButton>
      <BaseButton
        v-if="finding.status !== 'pending'"
        variant="ghost"
        size="sm"
        :loading="busy"
        :data-testid="`reference-reset-${finding.finding_id}`"
        @click="review('pending')"
      >重置</BaseButton>
    </footer>
  </article>
</template>

<style scoped>
.finding-card {
  display: grid;
  gap: 0.55rem;
  padding: 0.7rem 0.9rem;
  border: 1px solid var(--surface-line, rgba(33, 26, 21, 0.15));
  border-radius: var(--radius-md, 6px);
  background: var(--color-panel-solid, #fffdf7);
}
.finding-kind-forbidden_pattern { border-left: 4px solid #c14848; }
.finding-kind-observation { border-left: 4px solid #2f8a4d; }
.card-head { display: flex; flex-wrap: wrap; gap: 0.35rem; }
.card-statement { margin: 0; line-height: 1.55; font-size: 0.92rem; }
.card-actions { display: flex; gap: 0.4rem; flex-wrap: wrap; }
</style>
