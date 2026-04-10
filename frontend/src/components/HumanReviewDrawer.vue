<script setup>
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

defineEmits(["action", "open-target"]);

function actionLabel(action) {
  if (action === "retry_request") {
    return "Retry Request";
  }
  if (action === "retry_verify") {
    return "Retry Verify";
  }
  if (action === "release_review") {
    return "Release Review";
  }
  if (action === "inspect") {
    return "Inspect";
  }
  return action || "-";
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
    return `${replayResult.review_id} -> released=${replayResult.released}`;
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
</script>

<template>
  <div class="drawer-body">
    <div v-if="!items.length" class="empty">No human review events are queued.</div>
    <article
      v-for="item in props.items"
      :key="item.event_id || item.status"
      class="paper mini"
      :class="{ 'focused-card': props.focusEventId && item.event_id === props.focusEventId }"
    >
      <h3>{{ item.event_source }}</h3>
      <p class="muted">Status: {{ item.status }}</p>
      <p class="muted">Object: {{ item.object_ref || "-" }}</p>
      <p class="muted">Linked target: {{ targetSummary(item) }}</p>
      <p v-if="item.details_json?.created_by_ref" class="muted">
        Created by: {{ item.details_json.created_by_ref }} | {{ item.details_json.created_reason || "-" }}
      </p>
      <p class="muted">Actions: {{ (item.allowed_actions_json || []).join(" / ") || "-" }}</p>
      <p v-if="item.default_action && item.default_action !== 'inspect'" class="muted">
        Recommended next step: {{ actionLabel(item.default_action) }}
      </p>
      <p v-if="item.details_json?.last_action_at" class="muted">
        Last action:
        {{ actionLabel(item.details_json.last_action) }}
        | {{ item.details_json.last_action_at }}
        | {{ item.details_json.last_actor_ref || "-" }}
        | {{ item.details_json.last_action_status || item.status }}
      </p>
      <p v-if="item.details_json?.resolution_reason" class="muted">
        Resolution: {{ item.details_json.resolution_reason }}
      </p>
      <p v-if="item.details_json?.request_path_template" class="muted">
        Request: {{ item.details_json.request_method || "-" }} {{ item.details_json.request_path_template }}
      </p>
      <div v-if="actionHistory(item).length" class="history-stack">
        <p class="history-title">Action history</p>
        <ul class="history-list">
          <li
            v-for="entry in actionHistory(item)"
            :key="`${item.event_id}:${entry.action_at}:${entry.action}`"
            class="history-entry"
          >
            <p class="history-meta">
              <strong>{{ actionLabel(entry.action) }}</strong>
              <span>{{ entry.action_at }} | {{ entry.actor_ref || "-" }} | {{ entry.status_after || "-" }}</span>
            </p>
            <p v-if="entry.linked_target_ref" class="muted history-replay">
              Linked target: {{ entry.linked_target_ref }}
            </p>
            <p v-if="entry.resolution_reason" class="muted history-replay">
              Resolution: {{ entry.resolution_reason }}
            </p>
            <p v-if="entry.replay_result" class="muted history-replay">
              Replay result: {{ replaySummary(entry.replay_result) }}
            </p>
            <div v-if="historyReplayTarget(entry)" class="card-actions">
              <button class="ghost" @click='$emit("open-target", sourceFocusedTarget(historyReplayTarget(entry), item.event_id))'>
                Open Replay Result
              </button>
            </div>
          </li>
        </ul>
      </div>
      <pre v-if="item.details_json && Object.keys(item.details_json).length" class="json-block">{{
        JSON.stringify(item.details_json, null, 2)
      }}</pre>
      <div v-if="linkedTarget(item) || followupTarget(item) || replayTarget(item)" class="card-actions">
        <button
          v-if="linkedTarget(item)"
          class="ghost"
          @click='$emit("open-target", sourceFocusedTarget(linkedTarget(item), item.event_id))'
        >
          Open Linked Target
        </button>
        <button
          v-if="followupTarget(item)"
          class="ghost"
          @click='$emit("open-target", sourceFocusedTarget(followupTarget(item), item.event_id))'
        >
          Open Follow-up Target
        </button>
        <button
          v-if="replayTarget(item)"
          class="ghost"
          @click='$emit("open-target", sourceFocusedTarget(replayTarget(item), item.event_id))'
        >
          Open Replay Result
        </button>
      </div>
      <div v-if="props.interactive && item.allowed_actions_json?.length" class="card-actions">
        <button
          v-for="action in item.allowed_actions_json"
          :key="`${item.event_id}:${action}`"
          :disabled="props.actionId === `${item.event_id}:${action}`"
          @click='$emit("action", { eventId: item.event_id, action })'
        >
          {{
            props.actionId === `${item.event_id}:${action}`
              ? "Working..."
              : actionLabel(action)
          }}
        </button>
      </div>
    </article>
  </div>
</template>
