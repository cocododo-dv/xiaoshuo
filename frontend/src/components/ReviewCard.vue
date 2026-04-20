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

const emit = defineEmits(["approve", "release", "open-target", "open-reference"]);

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

const COLLECTION_LABELS = {
  style_rules: "风格规则",
  style_observations: "风格观察",
  calibration_lines: "校准参考",
  banned_rule_clusters: "禁用复刻规则",
  narrative_patterns: "叙事结构",
  voice_cards: "角色声线",
  relation_cards: "关系卡",
  world_rules: "世界规则",
  foreshadow_tracker: "伏笔",
  scene_memories: "场景记忆",
  chapter_memories: "章节记忆",
};

const ITEM_LABELS = {
  style_rule_set: "文笔规则",
  style_observation: "风格观察",
  calibration_candidate: "校准参考",
  banned_rule_cluster: "禁用复刻规则",
  narrative_pattern: "叙事结构",
};

const SOURCE_LABELS = {
  reference_book_learning: "参考书学习",
  reference_profile_apply: "参考画像应用",
  style_profile_extract: "样本文本提取",
  knowledge_console: "知识控制台",
  manual: "人工录入",
};

const REFERENCE_SOURCES = new Set(["reference_book_learning", "reference_profile_apply"]);
const REFERENCE_SAFE_TECHNICAL_KEYS = new Set([
  "source",
  "scope",
  "scope_ref_id",
  "lineage_key",
  "reference_book_id",
  "reference_segment_id",
  "dimension",
  "contract_version",
  "source_excerpt_hidden",
  "stripped_count",
  "blocked_markers",
]);

const SCOPE_LABELS = {
  global: "全局",
  chapter: "章节",
  scene: "场景",
};

const payload = computed(() =>
  props.item.candidate_payload_json && typeof props.item.candidate_payload_json === "object"
    ? props.item.candidate_payload_json
    : {},
);
const isReferenceSource = computed(() => REFERENCE_SOURCES.has(payload.value.source));

const collectionLabel = computed(
  () => COLLECTION_LABELS[props.item.target_collection] || ITEM_LABELS[props.item.item_type] || props.item.target_collection || "审核候选",
);

const sourceLabel = computed(() => SOURCE_LABELS[payload.value.source] || payload.value.source || "审核候选");
const referenceSourceLabel = computed(() => (isReferenceSource.value ? "来自参考书学习" : ""));

const scopeSummary = computed(() => {
  const scope = payload.value.scope || "";
  const scopeRef = payload.value.scope_ref_id || payload.value.scene_id || payload.value.chapter_id || "";
  if (!scope && !scopeRef) {
    return "";
  }
  const label = SCOPE_LABELS[scope] || scope || "范围";
  return scopeRef ? `${label} ${scopeRef}` : label;
});

const reviewTitle = computed(() => {
  if (payload.value.source === "reference_profile_apply") {
    return `参考画像应用 · ${collectionLabel.value}`;
  }
  return `${collectionLabel.value} · ${sourceLabel.value}`;
});

const payloadSummary = computed(() => {
  if (payload.value.source === "reference_profile_apply") {
    const profileTitle = "参考书画像";
    return `${profileTitle}${scopeSummary.value ? ` · 应用到${scopeSummary.value}` : ""}`;
  }
  const parts = [
    scopeSummary.value,
    payload.value.contract_version || payload.value.style_profile?.contract_version || "",
  ].filter(Boolean);
  return parts.join(" · ") || "技术详情中可查看完整载荷";
});

const formattedPayload = computed(() => {
  if (!payloadExpanded.value) {
    return "";
  }
  return JSON.stringify(reviewTechnicalPayload(), null, 2);
});
const reviewImpactSummary = computed(() => buildReviewImpactSummary(props.item));
const publicReviewImpactSummary = computed(() => ({
  ...reviewImpactSummary.value,
  sourceLabel: sourceLabel.value,
  sourceDetail: isReferenceSource.value
    ? "已抽象化参考画像"
    : reviewImpactSummary.value.sourceDetail,
  targetLabel: collectionLabel.value,
  targetDetail: scopeSummary.value || "",
}));
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

function reviewTechnicalPayload() {
  const candidatePayload = isReferenceSource.value
    ? redactReferencePayload(props.item.candidate_payload_json || {})
    : props.item.candidate_payload_json || {};
  return {
    review_id: props.item.review_id,
    item_type: props.item.item_type,
    target_collection: props.item.target_collection,
    status: props.item.status,
    materialize_status: props.item.materialize_status,
    candidate_text: isReferenceSource.value ? "Reference-derived text hidden in technical detail." : props.item.candidate_text,
    candidate_payload_json: candidatePayload,
  };
}

function redactReferencePayload(value, key = "") {
  if (Array.isArray(value)) {
    return value.map((item) => redactReferencePayload(item, key));
  }
  if (value && typeof value === "object") {
    return Object.fromEntries(
      Object.entries(value).map(([entryKey, entryValue]) => [
        entryKey,
        redactReferencePayload(entryValue, entryKey),
      ]),
    );
  }
  if (typeof value === "string" && !REFERENCE_SAFE_TECHNICAL_KEYS.has(key)) {
    return "[reference-derived content hidden]";
  }
  return value;
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
      <span class="badge">{{ collectionLabel }}</span>
      <span class="muted">{{ sourceLabel }}</span>
      <span v-if="referenceSourceLabel" class="badge ghost">{{ referenceSourceLabel }}</span>
      <span v-if="props.sourceActionLabel" class="badge">{{ props.sourceActionLabel }}</span>
    </div>

    <h3>{{ reviewTitle }}</h3>
    <p class="muted">状态：{{ formatStatus(props.item.status) }}</p>
    <p class="muted">摘要：{{ payloadSummary }}</p>

    <dl v-if="publicReviewImpactSummary.available" class="review-impact-summary" data-testid="review-impact-summary">
      <div>
        <dt>来源</dt>
        <dd>
          <strong>{{ publicReviewImpactSummary.sourceLabel }}</strong>
          <small v-if="publicReviewImpactSummary.sourceDetail">{{ publicReviewImpactSummary.sourceDetail }}</small>
        </dd>
      </div>
      <div>
        <dt>影响</dt>
        <dd>
          <strong>{{ publicReviewImpactSummary.targetLabel }}</strong>
          <small v-if="publicReviewImpactSummary.targetDetail">{{ publicReviewImpactSummary.targetDetail }}</small>
        </dd>
      </div>
      <div>
        <dt>运行时</dt>
        <dd>
          <strong>{{ publicReviewImpactSummary.runtimeLabel }}</strong>
          <small>{{ publicReviewImpactSummary.runtimeDetail }}</small>
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
        {{ payloadExpanded ? "收起技术详情" : "技术详情" }}
      </button>
      <button
        v-if="isReferenceSource"
        class="ghost"
        :data-testid="`review-open-reference-${props.item.review_id}`"
        @click="emit('open-reference', props.item.review_id)"
      >
        回到参考书学习
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
