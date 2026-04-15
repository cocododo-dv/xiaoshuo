<script setup>
import { computed, ref } from "vue";

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

function formatStatus(status) {
  return STATUS_LABELS[status] || status || "-";
}
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
        :disabled="loading"
        :data-testid="`review-approve-${props.item.review_id}`"
        @click="emit('approve', props.item.review_id)"
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
