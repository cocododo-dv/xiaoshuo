<script setup>
import { reactive } from "vue";

import BaseEmptyState from "./base/BaseEmptyState.vue";
import ProgressiveList from "./ProgressiveList.vue";
import { useUiMode } from "../composables/useUiMode";
import { formatGuidedTargetRef, formatReadableTargetRef } from "../lib/readableRefs";

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
const softRiskReasons = reactive({});
const { isAdvancedMode } = useUiMode();

const ACTION_LABELS = {
  retry_request: "重试请求",
  retry_verify: "重试校验",
  release_review: "发布审核",
  inspect: "查看详情",
  accept_soft_risk: "接受软风险",
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
    return isAdvancedMode.value
      ? `${replayResult.review_id} -> ${replayResult.materialize_status}`
      : `审核项 -> ${formatStatus(replayResult.materialize_status)}`;
  }
  if (replayResult.review_id && replayResult.released !== undefined) {
    return isAdvancedMode.value
      ? `${replayResult.review_id} -> 已发布 ${replayResult.released ? "是" : "否"}`
      : `审核项 -> 已发布 ${replayResult.released ? "是" : "否"}`;
  }
  if (replayResult.job_id && replayResult.status) {
    return isAdvancedMode.value
      ? `${replayResult.job_id} -> ${replayResult.status}`
      : `校验任务 -> ${formatStatus(replayResult.status)}`;
  }
  return JSON.stringify(replayResult);
}

function targetDisplay(targetRef) {
  const readable = isAdvancedMode.value ? formatReadableTargetRef(targetRef) : formatGuidedTargetRef(targetRef);
  return readable.label || readable.raw || "-";
}

function targetSummary(item) {
  return targetDisplay(item.linked_target?.target_ref || item.details_json?.linked_target_ref);
}

function rawTargetSummary(item) {
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

function detailHasPayload(details) {
  return Boolean(details && Object.keys(details).length);
}

function actionRows(item) {
  return (item.allowed_actions_json || []).map((action) => ({
    action,
    actionId: `${item.event_id}:${action}`,
    label: actionLabel(action),
  }));
}

function lastActionSummary(item) {
  if (!item.details_json?.last_action_at) {
    return null;
  }
  return {
    label: actionLabel(item.details_json.last_action),
    at: item.details_json.last_action_at,
    actor: item.details_json.last_actor_ref || "-",
    status: formatStatus(item.details_json.last_action_status || item.status),
  };
}

function historyRows(item, eventId) {
  return actionHistory(item).map((entry) => {
    const target = historyReplayTarget(entry);
    return {
      entry,
      key: `${eventId}:${entry.action_at}:${entry.action}`,
      actionLabel: actionLabel(entry.action),
      statusLabel: formatStatus(entry.status_after),
      actor: entry.actor_ref || "-",
      linkedTargetRef: entry.linked_target_ref,
      linkedTargetLabel: targetDisplay(entry.linked_target_ref),
      resolutionReason: entry.resolution_reason,
      replayResult: entry.replay_result,
      replaySummary: replaySummary(entry.replay_result),
      replayTarget: sourceFocusedTarget(target, eventId),
    };
  });
}

function humanReviewRow(item) {
  const eventId = item.event_id || item.status;
  const linked = linkedTarget(item);
  const followup = followupTarget(item);
  const replay = replayTarget(item);
  const actions = actionRows(item);

  return {
    item,
    eventId,
    eventSourceLabel: eventSourceLabel(item.event_source),
    statusLabel: formatStatus(item.status),
    targetSummary: targetSummary(item),
    rawTargetSummary: rawTargetSummary(item),
    actionSummary: actions.map((action) => action.label).join(" / ") || "-",
    defaultActionLabel: actionLabel(item.default_action),
    lastAction: lastActionSummary(item),
    history: historyRows(item, eventId),
    hasDetails: detailHasPayload(item.details_json),
    linkedTarget: sourceFocusedTarget(linked, eventId),
    followupTarget: sourceFocusedTarget(followup, eventId),
    replayTarget: sourceFocusedTarget(replay, eventId),
    actions,
  };
}

function formattedDetails(item) {
  return JSON.stringify(item.details_json || {}, null, 2);
}

function actionPayload(row, action) {
  if (action !== "accept_soft_risk") {
    return {};
  }
  return { reason: String(softRiskReasons[row.eventId] || "").trim() };
}

function actionDisabled(row, action) {
  if (props.actionId === `${row.eventId}:${action}`) {
    return true;
  }
  return action === "accept_soft_risk" && !String(softRiskReasons[row.eventId] || "").trim();
}
</script>

<template>
  <div class="drawer-body">
    <BaseEmptyState v-if="!props.items.length" description="当前没有待处理的人工作业事件。" />

    <ProgressiveList
      :items="props.items"
      :enabled="props.items.length > 6"
      :initial-count="6"
      :batch-size="4"
      :threshold="6"
      :map-item="humanReviewRow"
      test-id="human-review-progressive-list"
    >
      <template #default="{ items }">
        <article
          v-for="row in items"
          :key="row.eventId"
          class="paper mini"
          :data-testid="`human-review-event-${row.eventId}`"
          :class="{ 'focused-card': props.focusEventId && row.eventId === props.focusEventId }"
        >
          <h3>{{ row.eventSourceLabel }}</h3>
          <p class="muted" data-testid="human-review-technical-ref">
            {{ isAdvancedMode ? "事件 ID" : "事件" }}：{{ isAdvancedMode ? row.eventId : row.eventSourceLabel }}
          </p>
          <p class="muted">状态：{{ row.statusLabel }}</p>
          <p class="muted">对象：{{ isAdvancedMode ? (row.item.object_ref || "-") : row.eventSourceLabel }}</p>
          <p class="muted">关联目标：{{ row.targetSummary }}</p>

          <p v-if="isAdvancedMode && row.rawTargetSummary !== '-'" class="muted">
            target_ref：{{ row.rawTargetSummary }}
          </p>

          <p v-if="isAdvancedMode && row.item.details_json?.request_path_template" class="muted">
            请求模板：{{ row.item.details_json.request_path_template }}
          </p>

          <p v-if="isAdvancedMode && row.item.details_json?.created_by_ref" class="muted">
            创建来源：{{ row.item.details_json.created_by_ref }} | {{ row.item.details_json.created_reason || "-" }}
          </p>

          <p class="muted">可执行动作：{{ row.actionSummary }}</p>

          <p v-if="row.item.default_action && row.item.default_action !== 'inspect'" class="muted">
            建议下一步：{{ row.defaultActionLabel }}<span v-if="isAdvancedMode"> ({{ row.item.default_action }})</span>
          </p>

          <p v-if="row.lastAction" class="muted">
            最近操作：
            {{ row.lastAction.label }}
            | {{ row.lastAction.at }}
            | {{ row.lastAction.actor }}
            | {{ row.lastAction.status }}
          </p>

          <div class="card-actions">
            <button
              v-if="row.hasDetails"
              class="ghost"
              :data-testid="`human-review-toggle-details-${row.eventId}`"
              @click="toggleDetails(row.eventId)"
            >
              {{ expandedDetails[row.eventId] ? (isAdvancedMode ? "收起详情" : "收起依据") : (isAdvancedMode ? "展开详情" : "查看依据") }}
            </button>

            <button
              v-if="row.history.length"
              class="ghost"
              :data-testid="`human-review-toggle-history-${row.eventId}`"
              @click="toggleHistory(row.eventId)"
            >
              {{ expandedHistory[row.eventId] ? "收起历史" : "展开历史" }}
            </button>
          </div>

          <div v-if="expandedHistory[row.eventId] && row.history.length" class="history-stack">
            <p class="history-title">操作历史</p>
            <ul class="history-list">
              <li
                v-for="entry in row.history"
                :key="entry.key"
                class="history-entry"
              >
                <p class="history-meta">
                  <strong>{{ entry.actionLabel }}</strong>
                  <span>{{ entry.entry.action_at }} | {{ entry.actor }} | {{ entry.statusLabel }}</span>
                </p>

                <p v-if="entry.linkedTargetRef" class="muted history-replay">
                  {{ isAdvancedMode ? "target_ref" : "关联目标" }}：{{ isAdvancedMode ? entry.linkedTargetRef : entry.linkedTargetLabel }}
                </p>
                <p v-if="entry.resolutionReason" class="muted history-replay">处理结果：{{ entry.resolutionReason }}</p>
                <p v-if="entry.replayResult" class="muted history-replay">回放结果：{{ entry.replaySummary }}</p>

                <div v-if="entry.replayTarget" class="card-actions">
                  <button
                    class="ghost"
                    :data-testid="`human-review-open-history-replay-${row.eventId}`"
                    @click="emit('open-target', entry.replayTarget)"
                  >
                    打开回放结果
                  </button>
                </div>
              </li>
            </ul>
          </div>

          <pre
            v-if="expandedDetails[row.eventId] && row.hasDetails"
            class="json-block"
          >{{ formattedDetails(row.item) }}</pre>

          <div v-if="row.linkedTarget || row.followupTarget || row.replayTarget" class="card-actions">
            <button
              v-if="row.linkedTarget"
              class="ghost"
              :data-testid="`human-review-open-linked-${row.eventId}`"
              @click="emit('open-target', row.linkedTarget)"
            >
              打开关联目标
            </button>

            <button
              v-if="row.followupTarget"
              class="ghost"
              :data-testid="`human-review-open-followup-${row.eventId}`"
              @click="emit('open-target', row.followupTarget)"
            >
              打开后续目标
            </button>

            <button
              v-if="row.replayTarget"
              class="ghost"
              :data-testid="`human-review-open-replay-${row.eventId}`"
              @click="emit('open-target', row.replayTarget)"
            >
              打开回放结果
            </button>
          </div>

          <div v-if="props.interactive && row.actions.length" class="card-actions">
            <label
              v-for="action in row.actions.filter((item) => item.action === 'accept_soft_risk')"
              :key="`${action.actionId}:reason`"
              class="soft-risk-reason"
            >
              <span>接受理由</span>
              <input
                v-model="softRiskReasons[row.eventId]"
                type="text"
                :data-testid="`human-review-reason-${row.eventId}`"
                placeholder="说明为什么可以接受这个软风险"
              />
            </label>
            <button
              v-for="action in row.actions"
              :key="action.actionId"
              :disabled="actionDisabled(row, action.action)"
              :data-testid="`human-review-action-${row.eventId}-${action.action}`"
              @click="emit('action', { eventId: row.eventId, action: action.action, payload: actionPayload(row, action.action) })"
            >
              {{ props.actionId === action.actionId ? "处理中..." : action.label }}
            </button>
          </div>
        </article>
      </template>
    </ProgressiveList>
  </div>
</template>
