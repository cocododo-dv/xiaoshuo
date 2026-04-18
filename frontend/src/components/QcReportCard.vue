<script setup>
const props = defineProps({
  hardSummary: {
    type: Object,
    default: null,
  },
  softSummary: {
    type: Object,
    default: null,
  },
  rewriteCounters: {
    type: Object,
    default: null,
  },
  humanReviewSummary: {
    type: Object,
    default: null,
  },
});

function formatValue(value) {
  if (value === null || value === undefined || value === "") {
    return "-";
  }
  return value;
}

function normalizeIssueKeys(summary) {
  return summary?.issue_keys?.length ? summary.issue_keys.join(", ") : "-";
}

function normalizeRewriteBrief(summary) {
  return summary?.rewrite_brief?.length ? summary.rewrite_brief.join("; ") : "-";
}

function formatPercent(value) {
  if (typeof value !== "number" || Number.isNaN(value)) {
    return "-";
  }
  return `${Math.round(value * 100)}%`;
}

function hasStyleSummary(summary) {
  return Boolean(
    summary
      && (
        typeof summary.style_score === "number"
        || summary.style_dimensions?.length
        || summary.style_deviations?.length
      ),
  );
}
</script>

<template>
  <article class="paper" data-testid="scene-qc-report-card">
    <h3>QC 报告</h3>
    <div class="qc-report-stack">
      <section>
        <div class="receipt-head">
          <div>
            <h4>Hard QC</h4>
            <p v-if="hardSummary" class="muted">{{ hardSummary.qc_type || "hard_qc" }}</p>
          </div>
          <span v-if="hardSummary" class="badge">{{ hardSummary.pass_flag ? "PASS" : "FAIL" }}</span>
        </div>
        <p v-if="hardSummary"><strong>Resolution</strong><br />{{ formatValue(hardSummary.resolution_code) }}</p>
        <p v-if="hardSummary"><strong>Issue Keys</strong><br />{{ normalizeIssueKeys(hardSummary) }}</p>
        <p v-if="hardSummary"><strong>Next Action</strong><br />{{ formatValue(hardSummary.next_action) }}</p>
        <p v-if="hardSummary"><strong>Rewrite Brief</strong><br />{{ normalizeRewriteBrief(hardSummary) }}</p>
        <p v-else class="muted">暂无硬 QC 结果。</p>
      </section>

      <section>
        <div class="receipt-head">
          <div>
            <h4>Soft QC</h4>
            <p v-if="softSummary" class="muted">{{ softSummary.qc_type || "soft_qc" }}</p>
          </div>
          <span v-if="softSummary" class="badge">{{ softSummary.pass_flag ? "PASS" : "FAIL" }}</span>
        </div>
        <p v-if="softSummary"><strong>Resolution</strong><br />{{ formatValue(softSummary.resolution_code) }}</p>
        <p v-if="softSummary"><strong>Issue Keys</strong><br />{{ normalizeIssueKeys(softSummary) }}</p>
        <p v-if="softSummary"><strong>Next Action</strong><br />{{ formatValue(softSummary.next_action) }}</p>
        <p v-if="softSummary"><strong>Rewrite Brief</strong><br />{{ normalizeRewriteBrief(softSummary) }}</p>
        <div v-if="hasStyleSummary(softSummary)" class="style-score-block">
          <div class="receipt-head">
            <strong>风格命中</strong>
            <span class="badge">{{ formatPercent(softSummary.style_score) }}</span>
          </div>
          <ul v-if="softSummary.style_dimensions?.length" class="style-score-list">
            <li v-for="dimension in softSummary.style_dimensions" :key="dimension.name">
              <span>{{ dimension.name }}</span>
              <strong>{{ formatPercent(dimension.score) }}</strong>
              <small>{{ dimension.evidence }}</small>
            </li>
          </ul>
          <ul v-if="softSummary.style_deviations?.length" class="style-score-list">
            <li v-for="deviation in softSummary.style_deviations" :key="`${deviation.dimension}-${deviation.patch_brief}`">
              <span>{{ deviation.dimension }}</span>
              <strong>{{ deviation.severity || "-" }}</strong>
              <small>{{ deviation.patch_brief }}</small>
            </li>
          </ul>
        </div>
        <p v-if="!softSummary" class="muted">暂无软 QC 结果。</p>
      </section>

      <section v-if="rewriteCounters" class="qc-report-summary">
        <h4>Rewrite Counters</h4>
        <p><strong>Hard Partial</strong><br />{{ formatValue(rewriteCounters.hard_partial_rewrite_count) }}</p>
        <p><strong>Hard Full</strong><br />{{ formatValue(rewriteCounters.hard_full_rewrite_count) }}</p>
        <p><strong>Soft Patch</strong><br />{{ formatValue(rewriteCounters.soft_patch_count) }}</p>
        <p><strong>Repeat Issue</strong><br />{{ formatValue(rewriteCounters.repeat_issue_key) }} / {{ formatValue(rewriteCounters.repeat_issue_count) }}</p>
      </section>
      <section v-else class="qc-report-summary">
        <h4>Rewrite Counters</h4>
        <p class="muted">暂无重写计数。</p>
      </section>

      <section v-if="humanReviewSummary" class="qc-report-summary">
        <h4>Human Review</h4>
        <p><strong>Status</strong><br />{{ formatValue(humanReviewSummary.status) }}</p>
        <p><strong>Trigger</strong><br />{{ formatValue(humanReviewSummary.trigger_reason) }}</p>
        <p><strong>Action</strong><br />{{ formatValue(humanReviewSummary.recommended_action) }}</p>
        <p><strong>Linked Target</strong><br />{{ formatValue(humanReviewSummary.linked_target_ref) }}</p>
        <p v-if="humanReviewSummary.failure_reason"><strong>Why</strong><br />{{ humanReviewSummary.failure_reason }}</p>
      </section>
      <section v-else class="qc-report-summary">
        <h4>Human Review</h4>
        <p class="muted">当前没有人工复核摘要。</p>
      </section>
    </div>
  </article>
</template>
