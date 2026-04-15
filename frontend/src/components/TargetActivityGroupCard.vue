<script setup>
import CursorPager from "./CursorPager.vue";
import ProgressiveList from "./ProgressiveList.vue";

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

function activitySummary(item) {
  return [
    item?.source || "-",
    item?.status || "-",
    formatValue(item?.actor_ref),
    formatValue(item?.timestamp),
  ].join(" | ");
}

function isHighlighted(item) {
  return item?.activity_key && (
    item.activity_key === props.focusedActivityKey
    || item.activity_key === props.sourceLinkedActivityKey
  );
}
</script>

<template>
  <li
    class="target-activity-group-card"
    :data-testid="`target-activity-group-${props.group.target.target_ref}`"
    :class="{ 'focused-card': props.focused }"
  >
    <div class="target-group-head">
      <div class="target-group-meta">
        <strong>{{ props.group.target.target_ref }}</strong><br />
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
          test-id="target-group-progressive-list"
        >
          <template #default="{ items }">
            <ul class="receipt-list">
              <li
                v-for="item in items"
                :key="item.activity_key"
                :data-activity-key="item.activity_key"
                :data-testid="`target-activity-item-${item.activity_key}`"
                :class="{
                  'focused-card': isHighlighted(item),
                  'focused-activity-item': item.activity_key === props.focusedActivityKey,
                }"
              >
                <strong>{{ item.label || item.source || "-" }}</strong><br />
                {{ activitySummary(item) }}<br />
                {{ item.summary || "-" }}
                <div v-if="item.target_refs?.length" class="card-actions">
                  <button
                    v-for="target in item.target_refs"
                    :key="`${item.activity_key}:${target.target_ref}`"
                    type="button"
                    class="ghost"
                    @click="emit('open-target', target)"
                  >
                    {{ targetButtonLabel(target) }}
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
  </li>
</template>
