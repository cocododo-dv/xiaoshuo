<script setup>
defineProps({
  item: {
    type: Object,
    required: true,
  },
});

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

function formatStatus(status) {
  return STATUS_LABELS[status] || status || "-";
}

function formatYesNo(value) {
  return value ? "是" : "否";
}
</script>

<template>
  <article class="paper">
    <h3>{{ item.alias_scope }}</h3>
    <p class="muted">{{ item.object_type }} / {{ item.scope }} / {{ item.scope_ref_id || "-" }}</p>
    <p><strong>集合族</strong> {{ item.collection_family }}</p>
    <p><strong>生效别名</strong> {{ item.active_alias || "-" }}</p>
    <p><strong>候选别名</strong> {{ item.candidate_alias || "-" }}</p>
    <p class="muted">
      快照版本：{{ item.active_snapshot_version || "-" }} / {{ item.candidate_snapshot_version || "-" }}
    </p>
    <p class="muted">校验状态：{{ formatStatus(item.verify_status) }}</p>
    <p class="muted">
      向量版本：{{ item.active_embedding_version || "-" }} / {{ item.candidate_embedding_version || "-" }}
    </p>
    <p class="muted">示例查询成功：{{ formatYesNo(item.sample_query_success) }}</p>
    <p class="muted">更新时间：{{ item.updated_at || "-" }}</p>

    <div v-if="item.recent_fault_summary" class="fault-summary">
      <div class="fault-head">
        <strong>最近一次别名故障</strong>
        <span class="badge">{{ item.recent_fault_summary.severity }}</span>
      </div>
      <p class="muted">{{ item.recent_fault_summary.created_at }}</p>
      <pre>{{ JSON.stringify(item.recent_fault_summary.details_json, null, 2) }}</pre>
    </div>
  </article>
</template>
