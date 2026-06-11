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

// PR-23 — 证据区:anchor_kind → 徽章文案 / tone
function paragraphIndex(paragraphId) {
  if (!paragraphId) return null;
  const matched = /_(\d+)$/.exec(paragraphId);
  return matched ? Number(matched[1]) : null;
}

function anchorLabel(ev) {
  if (ev.anchor_kind === "author_avoidance") return "负空间";
  if (ev.anchor_kind === "counter_example") return "合成反例";
  const idx = paragraphIndex(ev.paragraph_id);
  return idx === null ? "段落引文" : `段落 #${idx}`;
}

function anchorTone(anchorKind) {
  if (anchorKind === "author_avoidance") return "accent";
  if (anchorKind === "counter_example") return "warning";
  return "info";
}
</script>

<template>
  <article
    class="finding-card"
    :class="`finding-kind-${finding.finding_kind}`"
    :data-testid="`reference-finding-${finding.finding_id}`"
  >
    <header class="card-head">
      <BaseBadge
        :tone="finding.finding_kind === 'forbidden_pattern' ? 'danger' : 'success'"
        :aria-label="`类型:${finding.finding_kind === 'forbidden_pattern' ? '禁忌模式' : '正向特征'}`"
      >
        {{ finding.finding_kind === "forbidden_pattern" ? "禁忌" : "正向" }}
      </BaseBadge>
      <BaseBadge
        :tone="finding.confidence === 'high' ? 'success' : finding.confidence === 'low' ? 'warning' : 'info'"
        :aria-label="`置信度:${finding.confidence || 'medium'}`"
      >
        {{ finding.confidence || "medium" }}
      </BaseBadge>
      <BaseBadge
        :tone="finding.status === 'approved' ? 'success' : finding.status === 'rejected' ? 'danger' : 'neutral'"
        :aria-label="`状态:${finding.status}`"
      >
        {{ finding.status }}
      </BaseBadge>
    </header>
    <p class="card-statement">{{ finding.statement }}</p>
    <section
      v-if="finding.evidence && finding.evidence.length"
      class="card-evidence"
      :data-testid="`reference-evidence-${finding.finding_id}`"
    >
      <header class="evidence-head">
        <span class="evidence-title">证据 · {{ finding.evidence.length }}</span>
        <BaseBadge :tone="finding.evidence.length >= 2 ? 'success' : 'warning'">
          {{ finding.evidence.length >= 2 ? "已满足 ≥2" : "不足" }}
        </BaseBadge>
      </header>
      <ul class="evidence-list">
        <li
          v-for="ev in finding.evidence"
          :key="ev.evidence_id"
          class="evidence-item"
        >
          <div class="evidence-meta">
            <BaseBadge :tone="anchorTone(ev.anchor_kind)">{{ anchorLabel(ev) }}</BaseBadge>
            <BaseBadge v-if="ev.is_synthetic" tone="warning">合成</BaseBadge>
          </div>
          <blockquote class="evidence-quote">{{ ev.quote_text }}</blockquote>
        </li>
      </ul>
    </section>
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
.card-evidence {
  display: grid;
  gap: 0.45rem;
  padding: 0.55rem 0.65rem;
  border: 1px dashed var(--surface-line, rgba(33, 26, 21, 0.15));
  border-radius: var(--radius-md, 6px);
  background: rgba(33, 26, 21, 0.03);
}
.evidence-head { display: flex; align-items: center; gap: 0.4rem; }
.evidence-title { font-size: 0.78rem; font-weight: 700; color: rgba(33, 26, 21, 0.66); }
.evidence-list { display: grid; gap: 0.45rem; margin: 0; padding: 0; list-style: none; }
.evidence-item { display: grid; gap: 0.3rem; }
.evidence-meta { display: flex; flex-wrap: wrap; gap: 0.3rem; }
.evidence-quote {
  margin: 0;
  padding-left: 0.6rem;
  border-left: 2px solid rgba(33, 26, 21, 0.2);
  font-family: Georgia, "Songti SC", "SimSun", serif;
  font-size: 0.88rem;
  line-height: 1.6;
  color: rgba(33, 26, 21, 0.82);
}
.card-actions { display: flex; gap: 0.4rem; flex-wrap: wrap; }
</style>
