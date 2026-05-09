<script setup>
import { computed, ref } from "vue";

import { formatReadableTargetRef } from "../lib/readableRefs";

const props = defineProps({
  item: {
    type: Object,
    required: true,
  },
});

const faultExpanded = ref(false);
const readableAliasScope = computed(() => formatReadableTargetRef(props.item.alias_scope));

const STATUS_LABELS = {
  pending: "待处理",
  failed: "失败",
  succeeded: "成功",
  approved: "已批准",
  released: "已发布",
  active: "生效中",
  candidate: "候选中",
  resolved: "已解决",
  unknown: "未知",
};

const faultSummary = computed(() => {
  const summary = props.item.recent_fault_summary;
  if (!summary) {
    return "";
  }
  return [summary.severity, summary.created_at].filter(Boolean).join(" / ");
});

const formattedFaultDetails = computed(() =>
  faultExpanded.value && props.item.recent_fault_summary?.details_json
    ? JSON.stringify(props.item.recent_fault_summary.details_json, null, 2)
    : "",
);

function formatStatus(status) {
  return STATUS_LABELS[status] || status || "-";
}

function formatYesNo(value) {
  return value ? "是" : "否";
}
</script>

<template>
  <article class="paper">
    <h3 class="line-clamp-2">{{ readableAliasScope.label }}</h3>
    <p class="muted">高级详情：<span class="technical-ref">{{ readableAliasScope.technical || readableAliasScope.raw || "-" }}</span></p>
    <p class="muted wrap-anywhere">{{ item.object_type }} / {{ item.scope }} / {{ item.scope_ref_id || "-" }}</p>
    <p><strong>集合族</strong> {{ item.collection_family }}</p>
    <p><strong>生效别名</strong> {{ item.active_alias || "-" }}</p>
    <p><strong>候选别名</strong> {{ item.candidate_alias || "-" }}</p>
    <p class="muted">快照版本：{{ item.active_snapshot_version || "-" }} / {{ item.candidate_snapshot_version || "-" }}</p>
    <p class="muted">校验状态：{{ formatStatus(item.verify_status) }}</p>
    <p class="muted">向量版本：{{ item.active_embedding_version || "-" }} / {{ item.candidate_embedding_version || "-" }}</p>
    <p class="muted">示例查询成功：{{ formatYesNo(item.sample_query_success) }}</p>
    <p class="muted">更新时间：{{ item.updated_at || "-" }}</p>

    <div v-if="item.recent_fault_summary" class="fault-summary">
      <div class="fault-head">
        <strong>最近一次别名故障</strong>
        <span class="badge">{{ item.recent_fault_summary.severity }}</span>
      </div>
      <p class="muted">{{ faultSummary }}</p>
      <div class="card-actions">
        <button
          class="ghost"
          :data-testid="`alias-scope-toggle-fault-${item.alias_scope}`"
          @click="faultExpanded = !faultExpanded"
        >
          {{ faultExpanded ? "收起详情" : "展开详情" }}
        </button>
      </div>
      <pre v-if="faultExpanded" class="json-block">{{ formattedFaultDetails }}</pre>
    </div>
  </article>
</template>
