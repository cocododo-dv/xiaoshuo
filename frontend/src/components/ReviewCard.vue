<script setup>
import { computed, ref, watch } from "vue";

import StyleProfileRiskWarning from "./StyleProfileRiskWarning.vue";
import StyleProfileSummary from "./StyleProfileSummary.vue";
import {
  buildReviewImpactSummary,
  styleProfileRiskFromReviewItem,
  styleProfileSummaryFromReviewItem,
} from "../lib/styleProfileSummary";

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

const emit = defineEmits(["approve", "release", "open-target"]);

const payloadExpanded = ref(false);
const riskAcknowledged = ref(false);
const riskReason = ref("");

const STATUS_LABELS = {
  pending: "待处理",
  approved: "已批准",
  rejected: "已拒绝",
  succeeded: "成功",
  failed: "失败",
  released: "已发布",
};

const payloadSummary = computed(() => {
  const payload = props.item.candidate_payload_json || {};
  const parts = [
    payload.lineage_key,
    payload.scope,
    payload.scope_ref_id,
    payload.scene_id,
    payload.chapter_id,
  ].filter(Boolean);
  return parts.join(" / ") || "无附加载荷摘要";
});

const formattedPayload = computed(() =>
  payloadExpanded.value ? JSON.stringify(props.item.candidate_payload_json || {}, null, 2) : "",
);
const reviewImpactSummary = computed(() => buildReviewImpactSummary(props.item));
const styleProfileSummary = computed(() => styleProfileSummaryFromReviewItem(props.item));
const styleProfileRisk = computed(() => styleProfileRiskFromReviewItem(props.item));
const requiresRiskConfirmation = computed(() => styleProfileRisk.value?.severity === "high");
const riskReasonNormalized = computed(() => riskReason.value.trim());
const canApproveReview = computed(
  () => !requiresRiskConfirmation.value || (riskAcknowledged.value && Boolean(riskReasonNormalized.value)),
);
const approvalPayload = computed(() => {
  if (!requiresRiskConfirmation.value) {
    return {};
  }
  return {
    risk_confirmation: {
      acknowledged: riskAcknowledged.value,
      reason: riskReasonNormalized.value,
      severity: "high",
    },
  };
});

function formatStatus(status) {
  return STATUS_LABELS[status] || status || "-";
}

function approveReview() {
  emit("approve", props.item.review_id, approvalPayload.value);
}

watch(
  () => props.item.review_id,
  () => {
    riskAcknowledged.value = false;
    riskReason.value = "";
  },
);
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

    <h3>{{ props.item.candidate_text || "空候选内容" }}</h3>
    <p class="muted">状态：{{ formatStatus(props.item.status) }}</p>
    <p class="muted">载荷摘要：{{ payloadSummary }}</p>

    <dl v-if="reviewImpactSummary.available" class="review-impact-summary" data-testid="review-impact-summary">
      <div>
        <dt>来源</dt>
        <dd>
          <strong>{{ reviewImpactSummary.sourceLabel }}</strong>
          <small v-if="reviewImpactSummary.sourceDetail">{{ reviewImpactSummary.sourceDetail }}</small>
        </dd>
      </div>
      <div>
        <dt>影响</dt>
        <dd>
          <strong>{{ reviewImpactSummary.targetLabel }}</strong>
          <small v-if="reviewImpactSummary.targetDetail">{{ reviewImpactSummary.targetDetail }}</small>
        </dd>
      </div>
      <div>
        <dt>运行时</dt>
        <dd>
          <strong>{{ reviewImpactSummary.runtimeLabel }}</strong>
          <small>{{ reviewImpactSummary.runtimeDetail }}</small>
        </dd>
      </div>
    </dl>

    <StyleProfileSummary
      :summary="styleProfileSummary"
      test-id="review-style-profile-summary"
    />
    <StyleProfileRiskWarning
      :risk="styleProfileRisk"
      test-id="review-style-profile-risk-warning"
    />

    <div
      v-if="requiresRiskConfirmation"
      class="risk-confirmation"
      :data-testid="`review-risk-confirmation-${props.item.review_id}`"
    >
      <label class="checkbox-inline risk-confirmation-check">
        <input
          v-model="riskAcknowledged"
          type="checkbox"
          :data-testid="`review-risk-confirm-${props.item.review_id}`"
        />
        <span>我已复核高风险风格变更，确认可以覆盖当前生效画像。</span>
      </label>
      <textarea
        v-model="riskReason"
        class="risk-confirmation-reason"
        rows="3"
        :data-testid="`review-risk-reason-${props.item.review_id}`"
        placeholder="填写批准理由，会写入操作日志"
      ></textarea>
      <small>需要明确理由后才能批准，便于之后回放为什么放行这次风格替换。</small>
    </div>

    <div class="card-actions">
      <button
        class="ghost"
        :data-testid="`review-toggle-payload-${props.item.review_id}`"
        @click="payloadExpanded = !payloadExpanded"
      >
        {{ payloadExpanded ? "收起载荷" : "查看载荷" }}
      </button>
    </div>

    <pre v-if="payloadExpanded" class="json-block">{{ formattedPayload }}</pre>

    <div class="card-actions">
      <button
        :disabled="loading || !canApproveReview"
        :data-testid="`review-approve-${props.item.review_id}`"
        @click="approveReview"
      >
        批准
      </button>
      <button
        :disabled="loading || props.item.materialize_status !== 'succeeded'"
        :data-testid="`review-release-${props.item.review_id}`"
        @click="emit('release', props.item.review_id)"
      >
        发布
      </button>
      <button
        class="ghost"
        :data-testid="`review-open-target-${props.item.review_id}`"
        @click="emit('open-target', props.item.review_id)"
      >
        在索引页打开
      </button>
    </div>
  </article>
</template>
