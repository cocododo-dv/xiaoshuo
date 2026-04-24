<script setup>
import { computed } from "vue";

import CursorPager from "./CursorPager.vue";
import ProgressiveList from "./ProgressiveList.vue";
import { useUiMode } from "../composables/useUiMode";
import { formatGuidedTargetRef, formatReadableTargetRef } from "../lib/readableRefs";

const props = defineProps({
  group: {
    type: Object,
    required: true,
  },
  expanded: {
    type: Boolean,
    default: false,
  },
  loading: {
    type: Boolean,
    default: false,
  },
  items: {
    type: Array,
    default: () => [],
  },
  pagination: {
    type: Object,
    default: () => null,
  },
  canPrevious: {
    type: Boolean,
    default: false,
  },
  canNext: {
    type: Boolean,
    default: false,
  },
  focused: {
    type: Boolean,
    default: false,
  },
  focusedActivityKey: {
    type: String,
    default: "",
  },
  sourceLinkedActivityKey: {
    type: String,
    default: "",
  },
});

const emit = defineEmits(["toggle", "open-target", "previous", "next"]);
const { isAdvancedMode } = useUiMode();
const readableTarget = computed(() =>
  isAdvancedMode.value
    ? formatReadableTargetRef(props.group.target.target_ref)
    : formatGuidedTargetRef(props.group.target.target_ref),
);
const rawTarget = computed(() => formatReadableTargetRef(props.group.target.target_ref).raw || "-");

function formatValue(value, fallback = "-") {
  return value === null || value === undefined || value === "" ? fallback : String(value);
}

function formatSources(sources) {
  if (!sources?.length) {
    return "-";
  }
  return sources.join(", ");
}

function targetButtonLabel(target) {
  if (target?.target_type === "review_item") {
    return "打开审核";
  }
  if (target?.target_type === "verify_job") {
    return "打开校验任务";
  }
  if (target?.target_type === "reindex_job") {
    return "打开重建任务";
  }
  if (target?.target_type === "human_review_event") {
    return "打开恢复事件";
  }
  return target?.target_ref || "打开目标";
}

function activitySummaryFor(item) {
  if (!isAdvancedMode.value) {
    return [
      item?.label || item?.source || "活动",
      item?.status || "-",
      formatValue(item?.timestamp),
    ].join(" | ");
  }
  return [
    item?.source || "-",
    item?.status || "-",
    formatValue(item?.actor_ref),
    formatValue(item?.timestamp),
  ].join(" | ");
}

function isHighlightedActivityKey(activityKey) {
  return activityKey && (
    activityKey === props.focusedActivityKey
    || activityKey === props.sourceLinkedActivityKey
  );
}

function targetActionRows(item) {
  return (item.target_refs || []).map((target) => ({
    target,
    key: `${item.activity_key}:${target.target_ref}`,
    label: targetButtonLabel(target),
  }));
}

function riskConfirmationFor(item) {
  const direct = item?.risk_confirmation;
  if (direct?.reason) {
    return direct;
  }
  const fromPayload = item?.payload_json?.request_payload?.risk_confirmation;
  return fromPayload?.reason ? fromPayload : null;
}

function targetActivityRow(item) {
  const activityKey = item.activity_key;
  const riskConfirmation = riskConfirmationFor(item);
  return {
    item,
    activityKey,
    title: item.label || item.source || "-",
    summaryLine: activitySummaryFor(item),
    summary: item.summary || "-",
    riskConfirmation,
    highlighted: isHighlightedActivityKey(activityKey),
    focused: activityKey === props.focusedActivityKey,
    targets: targetActionRows(item),
  };
}
</script>

<template>
  <article
    class="target-activity-group-card receipt-list-item"
    :data-testid="`target-activity-group-${props.group.target.target_ref}`"
    :class="{ 'focused-card': props.focused }"
  >
    <div class="target-group-head">
      <div class="target-group-meta">
        <strong>{{ readableTarget.label }}</strong><br />
        <span v-if="isAdvancedMode" class="muted" data-testid="index-target-technical-ref">
          高级详情：{{ rawTarget }}
        </span><br v-if="isAdvancedMode" />
        最近时间：{{ props.group.latest_at || "-" }} | 数量：{{ props.group.activity_count ?? 0 }} | 来源：{{ formatSources(props.group.sources) }}
      </div>
      <button
        type="button"
        class="ghost target-group-toggle"
        :data-testid="`target-activity-toggle-${props.group.target.target_ref}`"
        @click="emit('toggle', props.group)"
      >
        {{ props.expanded ? "收起活动" : "显示活动" }}
      </button>
    </div>

    <div class="card-actions">
      <button type="button" class="ghost" @click="emit('open-target', props.group.target)">
        {{ targetButtonLabel(props.group.target) }}
      </button>
    </div>

    <div v-if="props.expanded" class="receipt-detail">
      <div v-if="props.loading" class="empty">正在加载活动详情...</div>
      <template v-else-if="props.items.length">
        <ProgressiveList
          :items="props.items"
          :enabled="props.items.length > 8"
          :initial-count="8"
          :batch-size="6"
          :threshold="8"
          :map-item="targetActivityRow"
          :map-version="`${props.focusedActivityKey}:${props.sourceLinkedActivityKey}:${isAdvancedMode ? 'advanced' : 'guided'}`"
          test-id="target-group-progressive-list"
        >
          <template #default="{ items }">
            <ul class="receipt-list">
              <li
                v-for="row in items"
                :key="row.activityKey"
                :data-activity-key="row.activityKey"
                :data-testid="`target-activity-item-${row.activityKey}`"
                :class="{
                  'focused-card': row.highlighted,
                  'focused-activity-item': row.focused,
                }"
              >
                <strong>{{ row.title }}</strong><br />
                {{ row.summaryLine }}<br />
                {{ row.summary }}
                <p
                  v-if="row.riskConfirmation"
                  class="muted activity-risk-confirmation"
                  :data-testid="`target-activity-risk-confirmation-${row.activityKey}`"
                >
                  高风险确认：{{ row.riskConfirmation.reason }}
                </p>
                <div v-if="row.targets.length" class="card-actions">
                  <button
                    v-for="targetRow in row.targets"
                    :key="targetRow.key"
                    type="button"
                    class="ghost"
                    @click="emit('open-target', targetRow.target)"
                  >
                    {{ targetRow.label }}
                  </button>
                </div>
              </li>
            </ul>
          </template>
        </ProgressiveList>
        <CursorPager
          :test-id-prefix="`target-group-pager-${props.group.target.target_ref}`"
          :pagination="props.pagination"
          :can-previous="props.canPrevious"
          :can-next="props.canNext"
          :disabled="props.loading"
          @previous="emit('previous', props.group.target.target_ref)"
          @next="emit('next', props.group.target.target_ref)"
        />
      </template>
      <p v-else class="muted target-group-empty">这个目标下还没有活动记录。</p>
    </div>
  </article>
</template>
