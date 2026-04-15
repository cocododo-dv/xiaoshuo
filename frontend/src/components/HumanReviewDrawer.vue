<script setup>
import { reactive } from "vue";

import ProgressiveList from "./ProgressiveList.vue";

const props = defineProps({
  items: {
    type: Array,
    default: () => [],
  },
  interactive: {
    type: Boolean,
    default: false,
  },
  actionId: {
    type: String,
    default: "",
  },
  focusEventId: {
    type: String,
    default: "",
  },
});

const emit = defineEmits(["action", "open-target"]);

const expandedDetails = reactive({});
const expandedHistory = reactive({});

const ACTION_LABELS = {
  retry_request: "重试请求",
  retry_verify: "重试校验",
  release_review: "发布审核",
  inspect: "查看详情",
  approve_review: "批准审核",
};

const EVENT_SOURCE_LABELS = {
  idempotency_recovery: "幂等恢复",
  manual_scene_review: "手动场景审核",
};

const STATUS_LABELS = {
  pending: "待处理",
  resolved: "已解决",
  approved: "已批准",
  rejected: "已拒绝",
  failed: "失败",
  succeeded: "成功",
  running: "进行中",
};

function actionLabel(action) {
  return ACTION_LABELS[action] || action || "-";
}

function eventSourceLabel(source) {
  return EVENT_SOURCE_LABELS[source] || source || "-";
}

function formatStatus(status) {
  return STATUS_LABELS[status] || status || "-";
}

function actionHistory(item) {
  return item.details_json?.action_history || [];
}

function replaySummary(replayResult) {
  if (!replayResult) {
    return "";
  }
  if (replayResult.review_id && replayResult.materialize_status) {
    return `${replayResult.review_id} -> ${replayResult.materialize_status}`;
  }
  if (replayResult.review_id && replayResult.released !== undefined) {
    return `${replayResult.review_id} -> 已发布 ${replayResult.released ? "是" : "否"}`;
  }
  if (replayResult.job_id && replayResult.status) {
    return `${replayResult.job_id} -> ${replayResult.status}`;
  }
  return JSON.stringify(replayResult);
}

function targetSummary(item) {
  return item.linked_target?.target_ref || item.details_json?.linked_target_ref || "-";
}

function parseTargetRef(targetRef) {
  if (!targetRef || !targetRef.includes(":")) {
    return null;
  }

  const [targetType, targetId] = targetRef.split(":", 2);
  if (!targetType || !targetId) {
    return null;
  }

  return {
    target_type: targetType,
    target_id: targetId,
    target_ref: targetRef,
  };
}

function linkedTarget(item) {
  if (item.linked_target) {
    return item.linked_target;
  }

  const fromRef = parseTargetRef(item.details_json?.linked_target_ref);
  if (fromRef) {
    return fromRef;
  }

  if (item.scene_id) {
    return {
      target_type: "scene_card",
      target_id: item.scene_id,
      target_ref: `scene_card:${item.scene_id}`,
    };
  }

  return null;
}

function followupTarget(item) {
  if (item.followup_target) {
    return item.followup_target;
  }
  return parseTargetRef(item.details_json?.followup_target_ref);
}

function replayTargetFromResult(replayResult) {
  if (replayResult?.review_id) {
    return {
      target_type: "review_item",
      target_id: replayResult.review_id,
      target_ref: `review_item:${replayResult.review_id}`,
    };
  }

  if (replayResult?.job_id) {
    const targetType = replayResult.job_type === "reindex" ? "reindex_job" : "verify_job";
    return {
      target_type: targetType,
      target_id: replayResult.job_id,
      target_ref: `${targetType}:${replayResult.job_id}`,
    };
  }

  return null;
}

function replayTarget(item) {
  if (item.replay_target) {
    return item.replay_target;
  }
  return replayTargetFromResult(item.replay_result || item.details_json?.last_replay_result);
}

function historyReplayTarget(entry) {
  if (entry.replay_target) {
    return entry.replay_target;
  }
  return replayTargetFromResult(entry.replay_result);
}

function sourceFocusedTarget(target, eventId) {
  if (!target) {
    return null;
  }

  if (["review_item", "verify_job", "reindex_job"].includes(target.target_type)) {
    return {
      ...target,
      source_type: "recovery_timeline",
      source_id: eventId,
      view_id: "index",
    };
  }

  return target;
}

function toggleDetails(eventId) {
  expandedDetails[eventId] = !expandedDetails[eventId];
}

function toggleHistory(eventId) {
  expandedHistory[eventId] = !expandedHistory[eventId];
}

function formattedDetails(item) {
  return JSON.stringify(item.details_json || {}, null, 2);
}
</script>

<template>
  <div class="drawer-body">
    <div v-if="!props.items.length" class="empty">当前没有待处理的人工作业事件。</div>

    <ProgressiveList
      :items="props.items"
      :enabled="props.items.length > 12"
      test-id="human-review-progressive-list"
    >
      <template #default="{ items }">
        <article
          v-for="item in items"
          :key="item.event_id || item.status"
          class="paper mini"
          :data-testid="`human-review-event-${item.event_id}`"
          :class="{ 'focused-card': props.focusEventId && item.event_id === props.focusEventId }"
        >
          <h3>{{ eventSourceLabel(item.event_source) }}</h3>
          <p class="muted">状态：{{ formatStatus(item.status) }}</p>
          <p class="muted">对象：{{ item.object_ref || "-" }}</p>
          <p class="muted">关联目标：{{ targetSummary(item) }}</p>

          <p v-if="item.details_json?.request_path_template" class="muted">
            请求模板：{{ item.details_json.request_path_template }}
          </p>

          <p v-if="item.details_json?.created_by_ref" class="muted">
            创建来源：{{ item.details_json.created_by_ref }} | {{ item.details_json.created_reason || "-" }}
          </p>

          <p class="muted">可执行动作：{{ (item.allowed_actions_json || []).map(actionLabel).join(" / ") || "-" }}</p>

          <p v-if="item.default_action && item.default_action !== 'inspect'" class="muted">
            建议下一步：{{ actionLabel(item.default_action) }} ({{ item.default_action }})
          </p>

          <p v-if="item.details_json?.last_action_at" class="muted">
            最近操作：
            {{ actionLabel(item.details_json.last_action) }}
            | {{ item.details_json.last_action_at }}
            | {{ item.details_json.last_actor_ref || "-" }}
            | {{ formatStatus(item.details_json.last_action_status || item.status) }}
          </p>

          <div class="card-actions">
            <button
              v-if="item.details_json && Object.keys(item.details_json).length"
              class="ghost"
              :data-testid="`human-review-toggle-details-${item.event_id}`"
              @click="toggleDetails(item.event_id)"
            >
              {{ expandedDetails[item.event_id] ? "收起详情" : "展开详情" }}
            </button>

            <button
              v-if="actionHistory(item).length"
              class="ghost"
              :data-testid="`human-review-toggle-history-${item.event_id}`"
              @click="toggleHistory(item.event_id)"
            >
              {{ expandedHistory[item.event_id] ? "收起历史" : "展开历史" }}
            </button>
          </div>

          <div v-if="expandedHistory[item.event_id] && actionHistory(item).length" class="history-stack">
            <p class="history-title">操作历史</p>
            <ul class="history-list">
              <li
                v-for="entry in actionHistory(item)"
                :key="`${item.event_id}:${entry.action_at}:${entry.action}`"
                class="history-entry"
              >
                <p class="history-meta">
                  <strong>{{ actionLabel(entry.action) }}</strong>
                  <span>{{ entry.action_at }} | {{ entry.actor_ref || "-" }} | {{ formatStatus(entry.status_after) }}</span>
                </p>

                <p v-if="entry.linked_target_ref" class="muted history-replay">关联目标：{{ entry.linked_target_ref }}</p>
                <p v-if="entry.resolution_reason" class="muted history-replay">处理结果：{{ entry.resolution_reason }}</p>
                <p v-if="entry.replay_result" class="muted history-replay">回放结果：{{ replaySummary(entry.replay_result) }}</p>

                <div v-if="historyReplayTarget(entry)" class="card-actions">
                  <button
                    class="ghost"
                    :data-testid="`human-review-open-history-replay-${item.event_id}`"
                    @click="emit('open-target', sourceFocusedTarget(historyReplayTarget(entry), item.event_id))"
                  >
                    打开回放结果
                  </button>
                </div>
              </li>
            </ul>
          </div>

          <pre
            v-if="expandedDetails[item.event_id] && item.details_json && Object.keys(item.details_json).length"
            class="json-block"
          >{{ formattedDetails(item) }}</pre>

          <div v-if="linkedTarget(item) || followupTarget(item) || replayTarget(item)" class="card-actions">
            <button
              v-if="linkedTarget(item)"
              class="ghost"
              :data-testid="`human-review-open-linked-${item.event_id}`"
              @click="emit('open-target', sourceFocusedTarget(linkedTarget(item), item.event_id))"
            >
              打开关联目标
            </button>

            <button
              v-if="followupTarget(item)"
              class="ghost"
              :data-testid="`human-review-open-followup-${item.event_id}`"
              @click="emit('open-target', sourceFocusedTarget(followupTarget(item), item.event_id))"
            >
              打开后续目标
            </button>

            <button
              v-if="replayTarget(item)"
              class="ghost"
              :data-testid="`human-review-open-replay-${item.event_id}`"
              @click="emit('open-target', sourceFocusedTarget(replayTarget(item), item.event_id))"
            >
              打开回放结果
            </button>
          </div>

          <div v-if="props.interactive && item.allowed_actions_json?.length" class="card-actions">
            <button
              v-for="action in item.allowed_actions_json"
              :key="`${item.event_id}:${action}`"
              :disabled="props.actionId === `${item.event_id}:${action}`"
              :data-testid="`human-review-action-${item.event_id}-${action}`"
              @click="emit('action', { eventId: item.event_id, action })"
            >
              {{ props.actionId === `${item.event_id}:${action}` ? "处理中..." : actionLabel(action) }}
            </button>
          </div>
        </article>
      </template>
    </ProgressiveList>
  </div>
</template>
