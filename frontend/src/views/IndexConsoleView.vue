<script setup>
import { computed, nextTick, onMounted, ref, watch } from "vue";

import AliasScopeCard from "../components/AliasScopeCard.vue";
import CursorPager from "../components/CursorPager.vue";
import PanelShell from "../components/PanelShell.vue";
import { shouldClearIndexFocus } from "../lib/filterFocus";
import {
  focusedActivityKeyForGroup,
  nextExpandedTargetRefs,
  orderedActivityItems,
  toggleExpandedTargetRef,
} from "../lib/targetActivity";
import { useShellRouter } from "../router";
import { useIndexConsoleStore } from "../stores/indexConsole";

const emit = defineEmits(["notice"]);

const indexConsole = useIndexConsoleStore();
const { activeView, focusTarget, openTarget, clearFocus, pendingFocusView, settleFocusView } = useShellRouter();
const expandedTargetRefs = ref([]);
const indexFocusRefreshPending = ref(false);

const prioritizedJobs = computed(() => {
  const focusJobId =
    focusTarget.value?.target_type === "verify_job" || focusTarget.value?.target_type === "reindex_job"
      ? focusTarget.value.target_id
      : null;
  const items = [...indexConsole.jobs];
  if (!focusJobId) {
    return items;
  }
  return items.sort((left, right) => Number(right.job_id === focusJobId) - Number(left.job_id === focusJobId));
});

const prioritizedTargetActivityGroups = computed(() => {
  const focusRef = focusTarget.value?.target_ref || "";
  const items = [...(indexConsole.targetActivityGroups || [])];
  if (!focusRef) {
    return items;
  }
  return items.sort((left, right) => Number(right.target?.target_ref === focusRef) - Number(left.target?.target_ref === focusRef));
});

const focusedActivityKey = computed(() => {
  const focusRef = focusTarget.value?.target_ref || "";
  if (!focusRef) {
    return "";
  }
  const focusGroup = (indexConsole.targetActivityGroups || []).find((group) => group?.target?.target_ref === focusRef);
  return focusedActivityKeyForGroup(focusGroup, focusRef);
});

const focusedSourceType = computed(() => focusTarget.value?.source_type || "");
const focusedSourceId = computed(() => focusTarget.value?.source_id ?? null);

function indexFocusDeferred() {
  return indexFocusRefreshPending.value || pendingFocusView.value === "index";
}

watch(
  () => [focusTarget.value?.target_ref || "", indexConsole.targetActivityGroups],
  ([focusRef, groups]) => {
    expandedTargetRefs.value = nextExpandedTargetRefs(expandedTargetRefs.value, groups || [], focusRef);
  },
  { immediate: true, deep: true },
);

watch(
  focusedActivityKey,
  async (activityKey) => {
    if (!activityKey || typeof document === "undefined") {
      return;
    }
    await nextTick();
    document.querySelector(`[data-activity-key="${activityKey}"]`)?.scrollIntoView?.({
      block: "nearest",
      behavior: "smooth",
    });
  },
  { immediate: true },
);

function recoveryEventTimestamp(item) {
  return item?.details_json?.last_action_at || item?.last_action_at || item?.created_at || "-";
}

function recoveryEventTarget(item) {
  return item?.linked_target_ref || item?.details_json?.linked_target_ref || "-";
}

function recoveryEventResolution(item) {
  return item?.resolution_reason || item?.details_json?.resolution_reason || "-";
}

function recoveryEventAction(item) {
  return item?.action || item?.last_action || item?.details_json?.last_action || item?.default_action || "inspect";
}

function recoveryEventActor(item) {
  return item?.actor_ref || item?.last_actor_ref || item?.details_json?.last_actor_ref || "-";
}

function recoveryEventFollowup(item) {
  const action = item?.followup_action || item?.details_json?.followup_action;
  const target = item?.followup_target_ref || item?.details_json?.followup_target_ref;
  if (!action && !target) {
    return "-";
  }
  return [action, target].filter(Boolean).join(" -> ");
}

function systemActivityActor(item) {
  return item?.actor_ref || item?.payload_json?.actor_ref || "-";
}

function systemActivitySummary(item) {
  return item?.summary || item?.payload_json?.summary || "-";
}

function systemActivityDetail(item) {
  return (
    item?.payload_json?.review_id ||
    item?.payload_json?.event_id ||
    item?.payload_json?.job_id ||
    item?.payload_json?.alias_scope ||
    item?.object_ref ||
    "-"
  );
}

function systemActivityTargets(item) {
  return item?.target_refs || [];
}

function operatorActionTargets(item) {
  return item?.target_refs || [];
}

function operatorActionSummary(item) {
  return [item?.action || "-", item?.status_before || "-", "->", item?.status_after || "-"].join(" ");
}

function targetActivitySummary(item) {
  return [item?.source || "-", item?.status || "-", item?.actor_ref || "-", item?.timestamp || "-"].join(" | ");
}

function isTargetGroupExpanded(group) {
  return expandedTargetRefs.value.includes(group?.target?.target_ref);
}

function toggleTargetGroup(group) {
  expandedTargetRefs.value = toggleExpandedTargetRef(expandedTargetRefs.value, group?.target?.target_ref);
}

function orderedTargetActivityItems(group) {
  return orderedActivityItems(group?.activity_items || []);
}

function isFocusedActivityItem(group, item) {
  return item?.activity_key && item.activity_key === focusedActivityKeyForGroup(group, focusTarget.value?.target_ref || "");
}

function withSourceFocusTarget(target, sourceType, sourceId) {
  if (!target) {
    return null;
  }
  const keepInIndex = ["review_item", "verify_job", "reindex_job"].includes(target.target_type);
  return {
    ...target,
    source_type: sourceType,
    source_id: sourceId,
    ...(keepInIndex ? { view_id: "index" } : {}),
  };
}

function isFocusedSource(sourceType, sourceId) {
  return focusedSourceType.value === sourceType && focusedSourceId.value === sourceId;
}

function isFocusedRecoverySweepReceipt() {
  return isFocusedSource("recovery_sweep", indexConsole.lastRecoveryResult?.actor_ref || "__recovery_sweep__");
}

function isFocusedRecoveryReceipt() {
  return isFocusedSource("recovery_receipt", indexConsole.lastRecoveryActionResult?.event_id || null);
}

function isFocusedPromotionReceipt() {
  return isFocusedSource("promotion_receipt", indexConsole.lastPromotionResult?.actor_ref || "__promotion_receipt__");
}

function isFocusedRecoveryTimelineItem(item) {
  return isFocusedSource("recovery_timeline", item?.event_id || null);
}

function isFocusedSystemActivityItem(item) {
  return isFocusedSource("system_activity", item?.operation_id || null);
}

function isFocusedOperatorActionItem(item) {
  return isFocusedSource("operator_action", item?.operation_id || null);
}

function isSourceLinkedActivityItem(item) {
  if (!item?.activity_key) {
    return false;
  }
  if (focusedSourceType.value === "recovery_receipt" || focusedSourceType.value === "recovery_timeline") {
    return item.activity_key === `recovery_timeline:${focusedSourceId.value}`;
  }
  if (focusedSourceType.value === "system_activity") {
    return item.activity_key === `system_runtime:${focusedSourceId.value}`;
  }
  if (focusedSourceType.value === "operator_action") {
    return item.activity_key === `operator_action:${focusedSourceId.value}`;
  }
  return false;
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

function recoveryLinkedTarget(item) {
  return item?.linked_target || parseTargetRef(item?.linked_target_ref || item?.details_json?.linked_target_ref);
}

function recoveryFollowupTarget(item) {
  return item?.followup_target || parseTargetRef(item?.followup_target_ref || item?.details_json?.followup_target_ref);
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

function recoveryReplayTarget(item) {
  if (item?.replay_target) {
    return item.replay_target;
  }
  return replayTargetFromResult(item?.replay_result || item?.last_replay_result || item?.details_json?.last_replay_result);
}

function jobSummaryTarget(item) {
  return item?.target || jobTarget(item);
}

function recoveryCreatedEventTargets(result) {
  if (result?.created_human_review_event_targets?.length) {
    return result.created_human_review_event_targets;
  }
  return (result?.created_human_review_event_ids || []).map((eventId) => ({
    event_id: eventId,
    target: recoveryEventById(eventId),
  }));
}

function promotedReviewTargets(result) {
  if (result?.promoted_review_targets?.length) {
    return result.promoted_review_targets;
  }
  return (result?.promoted_review_ids || []).map((reviewId) => ({
    review_id: reviewId,
    target: reviewTarget(reviewId),
  }));
}

function systemTargetLabel(target) {
  if (target?.target_type === "review_item") {
    return "Open Review";
  }
  if (target?.target_type === "human_review_event") {
    return "Open Recovery Event";
  }
  if (target?.target_type === "verify_job") {
    return "Open Verify Job";
  }
  if (target?.target_type === "reindex_job") {
    return "Open Reindex Job";
  }
  return target?.target_ref || "Open Target";
}

function reviewTarget(reviewId) {
  if (!reviewId) {
    return null;
  }
  return {
    target_type: "review_item",
    target_id: reviewId,
    target_ref: `review_item:${reviewId}`,
  };
}

function recoveryEventById(eventId) {
  if (!eventId) {
    return null;
  }
  return {
    target_type: "human_review_event",
    target_id: eventId,
    target_ref: `human_review_event:${eventId}`,
  };
}

function jobTarget(item) {
  if (!item?.job_id) {
    return null;
  }
  const targetType = item.job_type === "reindex" ? "reindex_job" : "verify_job";
  return {
    target_type: targetType,
    target_id: item.job_id,
    target_ref: `${targetType}:${item.job_id}`,
  };
}

function jumpToTarget(target) {
  if (!target) {
    return;
  }
  openTarget(target);
  emit("notice", `Opened ${target.target_ref}`);
}

function isFocusedJob(jobId) {
  return (
    (focusTarget.value?.target_type === "verify_job" || focusTarget.value?.target_type === "reindex_job")
    && focusTarget.value.target_id === jobId
  );
}

async function refreshIndex() {
  await indexConsole.load();
  if (indexConsole.error) {
    emit("notice", indexConsole.error);
  }
}

async function nextJobPage() {
  await indexConsole.nextJobPage();
  if (indexConsole.error) {
    emit("notice", indexConsole.error);
  }
}

async function previousJobPage() {
  await indexConsole.previousJobPage();
  if (indexConsole.error) {
    emit("notice", indexConsole.error);
  }
}

function clearAliasFilters() {
  indexConsole.clearAliasFilters();
  refreshIndex();
}

function clearJobFilters() {
  indexConsole.clearJobFilters();
  refreshIndex();
}

function clearLedgerFilters() {
  indexConsole.clearLedgerFilters();
  refreshIndex();
}

async function runRecovery() {
  try {
    emit("notice", await indexConsole.runRecovery());
  } catch (error) {
    emit("notice", error.message);
  }
}

async function runDuePromotions() {
  try {
    emit("notice", await indexConsole.runDuePromotions());
  } catch (error) {
    emit("notice", error.message);
  }
}

async function retry(jobId) {
  try {
    emit("notice", await indexConsole.retryVerifyJob(jobId));
  } catch (error) {
    emit("notice", error.message);
  }
}

onMounted(() => {
  refreshIndex();
});

watch(
  () => activeView.value,
  async (nextView, previousView) => {
    if (nextView === "index" && previousView !== "index") {
      indexFocusRefreshPending.value = true;
      try {
        await refreshIndex();
      } finally {
        indexFocusRefreshPending.value = false;
      }
      settleFocusView("index");
      if (
        shouldClearIndexFocus(
          activeView.value,
          indexConsole.loading,
          indexFocusDeferred(),
          focusTarget.value,
          indexConsole.aliasScopes,
          indexConsole.jobs,
          indexConsole.targetActivityGroups,
        )
      ) {
        clearFocus();
      }
    }
  },
);

watch(
  () => [
    focusTarget.value,
    indexConsole.loading,
    pendingFocusView.value,
    indexFocusRefreshPending.value,
    indexConsole.aliasScopes,
    indexConsole.jobs,
    indexConsole.targetActivityGroups,
  ],
  () => {
    if (
      shouldClearIndexFocus(
        activeView.value,
        indexConsole.loading,
        indexFocusDeferred(),
        focusTarget.value,
        indexConsole.aliasScopes,
        indexConsole.jobs,
        indexConsole.targetActivityGroups,
      )
    ) {
      clearFocus();
    }
  },
  { deep: true },
);
</script>

<template>
  <section class="panel-grid" data-testid="index-console-view">
    <PanelShell
      eyebrow="Index Console"
      title="Alias, verify, and recovery"
      description="Inspect alias scopes, verify jobs, and runtime recovery from one board."
    >
      <template #actions>
        <div class="field-inline">
          <button @click="refreshIndex">Refresh</button>
          <button
            :disabled="indexConsole.actionId === 'promotions'"
            data-testid="run-due-promotions-button"
            @click="runDuePromotions"
          >
            {{ indexConsole.actionId === "promotions" ? "Promoting..." : "Run Due Promotions" }}
          </button>
          <button
            :disabled="indexConsole.actionId === 'recovery'"
            data-testid="run-recovery-sweep-button"
            @click="runRecovery"
          >
            {{ indexConsole.actionId === "recovery" ? "Recovering..." : "Recovery Sweep" }}
          </button>
        </div>
      </template>

      <div v-if="indexConsole.loading" class="empty">Loading alias scopes...</div>
      <div v-else-if="indexConsole.error" class="empty">{{ indexConsole.error }}</div>
      <template v-else>
        <div class="field-inline">
          <select v-model="indexConsole.aliasFilters.verifyStatus" data-testid="index-alias-filter-verify-status">
            <option value="">All alias verify states</option>
            <option value="pending">pending</option>
            <option value="failed">failed</option>
            <option value="succeeded">succeeded</option>
          </select>
          <button data-testid="index-alias-filter-refresh" @click="refreshIndex">Refresh</button>
          <button data-testid="index-alias-filter-clear" @click="clearAliasFilters">Clear</button>
        </div>
        <div class="field-inline">
          <select v-model="indexConsole.jobFilters.jobType" data-testid="index-job-filter-job-type">
            <option value="">All jobs</option>
            <option value="verify">verify</option>
            <option value="reindex">reindex</option>
          </select>
          <input v-model="indexConsole.jobFilters.reviewId" data-testid="index-job-filter-review-id" />
          <input v-model="indexConsole.jobFilters.workerId" data-testid="index-job-filter-worker-id" />
          <label class="checkbox-inline">
            <input v-model="indexConsole.jobFilters.stuckOnly" data-testid="index-job-filter-stuck-only" type="checkbox" />
            <span>Stuck only</span>
          </label>
          <button data-testid="index-job-filter-refresh" @click="refreshIndex">Refresh</button>
          <button data-testid="index-job-filter-clear" @click="clearJobFilters">Clear</button>
        </div>
        <div class="field-inline">
          <input v-model="indexConsole.ledgerFilters.targetRef" data-testid="index-ledger-filter-target-ref" />
          <select v-model="indexConsole.ledgerFilters.source" data-testid="index-ledger-filter-source">
            <option value="">All sources</option>
            <option value="recovery_timeline">recovery_timeline</option>
            <option value="system_runtime">system_runtime</option>
            <option value="operator_action">operator_action</option>
          </select>
          <button data-testid="index-ledger-filter-refresh" @click="refreshIndex">Refresh</button>
          <button data-testid="index-ledger-filter-clear" @click="clearLedgerFilters">Clear</button>
        </div>
        <div v-if="!indexConsole.aliasScopes.length" class="empty">No alias scopes exist yet.</div>
        <div v-else class="alias-grid">
          <AliasScopeCard v-for="item in indexConsole.aliasScopes" :key="item.alias_scope" :item="item" />
        </div>

        <article
          v-if="indexConsole.lastRecoveryResult"
          class="paper receipt-card"
          data-testid="recovery-receipt"
          :class="{ 'focused-card': isFocusedRecoverySweepReceipt() }"
        >
          <div class="receipt-head">
            <div>
              <h3>Recovery Receipt</h3>
              <p class="muted receipt-copy">Shows the latest recovery sweep, including reclaimed leases and recent failures.</p>
            </div>
            <span class="badge">recovery/sweep</span>
          </div>
          <div class="receipt-grid">
            <p><strong>Reclaimed Jobs</strong><br />{{ indexConsole.lastRecoveryResult.reclaimed_jobs ?? 0 }}</p>
            <p><strong>Failed Jobs</strong><br />{{ indexConsole.lastRecoveryResult.failed_jobs ?? 0 }}</p>
            <p><strong>Actor</strong><br />{{ indexConsole.lastRecoveryResult.actor_ref || "-" }}</p>
            <p>
              <strong>Reclaimed Keys</strong><br />
              {{ indexConsole.lastRecoveryResult.reclaimed_idempotency_keys ?? 0 }}
            </p>
            <p>
              <strong>Failed Keys</strong><br />
              {{ indexConsole.lastRecoveryResult.failed_idempotency_keys ?? 0 }}
            </p>
            <p>
              <strong>Human Review Events</strong><br />
              {{ indexConsole.lastRecoveryResult.created_human_review_events ?? 0 }}
            </p>
          </div>
          <div
            v-if="indexConsole.lastRecoveryResult.reclaimed_job_summaries?.length"
            class="receipt-detail"
          >
            <h4>Reclaimed Job Summaries</h4>
            <ul class="receipt-list">
              <li
                v-for="item in indexConsole.lastRecoveryResult.reclaimed_job_summaries"
                :key="`${item.job_type}-${item.job_id}`"
              >
                <strong>{{ item.job_type }}</strong> {{ item.job_id }}<br />
                {{ item.alias_scope }}<br />
                Previous worker: {{ item.previous_worker_id || "-" }} | Attempt {{ item.attempt_no ?? 0 }} | Lease
                {{ item.previous_lease_expires_at || "-" }}
                <div class="card-actions">
                  <button
                    class="ghost"
                    @click="jumpToTarget(withSourceFocusTarget(jobSummaryTarget(item), 'recovery_sweep', indexConsole.lastRecoveryResult?.actor_ref || '__recovery_sweep__'))"
                  >
                    Open Job
                  </button>
                </div>
              </li>
            </ul>
          </div>
          <div v-if="indexConsole.lastRecoveryResult.failed_job_summaries?.length" class="receipt-detail">
            <h4>Failed Job Summaries</h4>
            <ul class="receipt-list">
              <li
                v-for="item in indexConsole.lastRecoveryResult.failed_job_summaries"
                :key="`${item.job_type}-${item.job_id}`"
              >
                <strong>{{ item.job_type }}</strong> {{ item.job_id }}<br />
                {{ item.alias_scope }}<br />
                {{ item.error_text || "-" }} | Finished {{ item.finished_at || "-" }}
                <div class="card-actions">
                  <button
                    class="ghost"
                    @click="jumpToTarget(withSourceFocusTarget(jobSummaryTarget(item), 'recovery_sweep', indexConsole.lastRecoveryResult?.actor_ref || '__recovery_sweep__'))"
                  >
                    Open Job
                  </button>
                </div>
              </li>
            </ul>
          </div>
          <div
            v-if="indexConsole.lastRecoveryResult.reclaimed_idempotency_key_summaries?.length"
            class="receipt-detail"
          >
            <h4>Reclaimed Idempotency Keys</h4>
            <ul class="receipt-list">
              <li
                v-for="item in indexConsole.lastRecoveryResult.reclaimed_idempotency_key_summaries"
                :key="item.idempotency_key"
              >
                <strong>{{ item.idempotency_key }}</strong><br />
                Previous worker: {{ item.previous_worker_id || "-" }} | Attempt {{ item.attempt_no ?? 0 }} | Lease
                {{ item.previous_lease_expires_at || "-" }}
              </li>
            </ul>
          </div>
          <div v-if="recoveryCreatedEventTargets(indexConsole.lastRecoveryResult).length" class="receipt-detail">
            <h4>Created Human Review Events</h4>
            <ul class="receipt-list">
              <li
                v-for="item in recoveryCreatedEventTargets(indexConsole.lastRecoveryResult)"
                :key="item.event_id"
              >
                <strong>{{ item.event_id }}</strong>
                <div class="card-actions">
                  <button
                    class="ghost"
                    :data-testid="`recovery-created-event-${item.event_id}`"
                    @click="jumpToTarget(withSourceFocusTarget(item.target, 'recovery_sweep', indexConsole.lastRecoveryResult?.actor_ref || '__recovery_sweep__'))"
                  >
                    Open Recovery Event
                  </button>
                </div>
              </li>
            </ul>
          </div>
        </article>

        <article
          v-if="indexConsole.lastRecoveryActionResult || indexConsole.recoveryTimelineItems.length"
          class="paper receipt-card"
          data-testid="recovery-followup-receipt"
          :class="{ 'focused-card': isFocusedRecoveryReceipt() }"
        >
          <div class="receipt-head">
            <div>
              <h3>Recovery Follow-up</h3>
              <p class="muted receipt-copy">Tracks the latest operator action and the recovery timeline that now follows it.</p>
            </div>
            <span class="badge">recovery/follow-up</span>
          </div>
          <div v-if="indexConsole.lastRecoveryActionResult" class="receipt-grid">
            <p><strong>Event</strong><br />{{ indexConsole.lastRecoveryActionResult.event_id || "-" }}</p>
            <p><strong>Action</strong><br />{{ indexConsole.lastRecoveryActionResult.action || "-" }}</p>
            <p><strong>Actor</strong><br />{{ recoveryEventActor(indexConsole.lastRecoveryActionResult) }}</p>
            <p><strong>Status</strong><br />{{ indexConsole.lastRecoveryActionResult.status || "-" }}</p>
            <p><strong>Linked Target</strong><br />{{ recoveryEventTarget(indexConsole.lastRecoveryActionResult) }}</p>
            <p><strong>Resolution</strong><br />{{ recoveryEventResolution(indexConsole.lastRecoveryActionResult) }}</p>
            <p><strong>Replay Result</strong><br />{{ indexConsole.lastRecoveryActionResult.replay_result?.review_id || indexConsole.lastRecoveryActionResult.replay_result?.job_id || "-" }}</p>
          </div>
          <div
            v-if="recoveryLinkedTarget(indexConsole.lastRecoveryActionResult) || recoveryFollowupTarget(indexConsole.lastRecoveryActionResult) || recoveryReplayTarget(indexConsole.lastRecoveryActionResult)"
            class="card-actions"
          >
            <button
              v-if="recoveryLinkedTarget(indexConsole.lastRecoveryActionResult)"
              class="ghost"
              data-testid="recovery-followup-open-linked-target"
              @click="jumpToTarget(withSourceFocusTarget(recoveryLinkedTarget(indexConsole.lastRecoveryActionResult), 'recovery_receipt', indexConsole.lastRecoveryActionResult?.event_id || null))"
            >
              Open Linked Target
            </button>
            <button
              v-if="recoveryFollowupTarget(indexConsole.lastRecoveryActionResult)"
              class="ghost"
              data-testid="recovery-followup-open-followup-target"
              @click="jumpToTarget(withSourceFocusTarget(recoveryFollowupTarget(indexConsole.lastRecoveryActionResult), 'recovery_receipt', indexConsole.lastRecoveryActionResult?.event_id || null))"
            >
              Open Follow-up Target
            </button>
            <button
              v-if="recoveryReplayTarget(indexConsole.lastRecoveryActionResult)"
              class="ghost"
              data-testid="recovery-followup-open-replay-result"
              @click="jumpToTarget(withSourceFocusTarget(recoveryReplayTarget(indexConsole.lastRecoveryActionResult), 'recovery_receipt', indexConsole.lastRecoveryActionResult?.event_id || null))"
            >
              Open Replay Result
            </button>
          </div>
          <div v-if="indexConsole.recoveryTimelineItems.length" class="receipt-detail">
            <h4>Recovery Timeline</h4>
            <ul class="receipt-list">
              <li
                v-for="item in indexConsole.recoveryTimelineItems"
                :key="item.event_id"
                :class="{ 'focused-card': isFocusedRecoveryTimelineItem(item) }"
              >
                <strong>{{ item.event_id }}</strong><br />
                {{ item.status || "-" }} | {{ recoveryEventAction(item) }} | {{ recoveryEventActor(item) }} | {{ recoveryEventTimestamp(item) }}<br />
                Target: {{ recoveryEventTarget(item) }}<br />
                Resolution: {{ recoveryEventResolution(item) }}<br />
                Next: {{ recoveryEventFollowup(item) }}
                <div v-if="recoveryLinkedTarget(item) || recoveryFollowupTarget(item) || recoveryReplayTarget(item)" class="card-actions">
                  <button
                    v-if="recoveryLinkedTarget(item)"
                    class="ghost"
                    @click="jumpToTarget(withSourceFocusTarget(recoveryLinkedTarget(item), 'recovery_timeline', item.event_id))"
                  >
                    Open Linked Target
                  </button>
                  <button
                    v-if="recoveryFollowupTarget(item)"
                    class="ghost"
                    @click="jumpToTarget(withSourceFocusTarget(recoveryFollowupTarget(item), 'recovery_timeline', item.event_id))"
                  >
                    Open Follow-up Target
                  </button>
                  <button
                    v-if="recoveryReplayTarget(item)"
                    class="ghost"
                    @click="jumpToTarget(withSourceFocusTarget(recoveryReplayTarget(item), 'recovery_timeline', item.event_id))"
                  >
                    Open Replay Result
                  </button>
                </div>
              </li>
            </ul>
          </div>
        </article>

        <article
          v-if="indexConsole.lastPromotionResult"
          class="paper receipt-card"
          data-testid="promotion-receipt"
          :class="{ 'focused-card': isFocusedPromotionReceipt() }"
        >
          <div class="receipt-head">
            <div>
              <h3>Promotion Receipt</h3>
              <p class="muted receipt-copy">Tracks the most recent runtime promotion sweep from this console.</p>
            </div>
            <span class="badge">promotions/run-due</span>
          </div>
          <div class="receipt-grid">
            <p><strong>Promoted</strong><br />{{ indexConsole.lastPromotionResult.promoted ?? 0 }}</p>
            <p><strong>Actor</strong><br />{{ indexConsole.lastPromotionResult.actor_ref || "-" }}</p>
            <p>
              <strong>Alias Scopes</strong><br />
              {{ indexConsole.lastPromotionResult.promoted_alias_scopes?.join(", ") || "-" }}
            </p>
            <p>
              <strong>Review IDs</strong><br />
              {{ indexConsole.lastPromotionResult.promoted_review_ids?.join(", ") || "-" }}
            </p>
            <p>
              <strong>Rows</strong><br />
              {{ indexConsole.lastPromotionResult.promoted_row_ids?.join(", ") || "-" }}
            </p>
          </div>
          <div v-if="promotedReviewTargets(indexConsole.lastPromotionResult).length" class="card-actions">
            <button
              v-for="item in promotedReviewTargets(indexConsole.lastPromotionResult)"
              :key="item.review_id"
              class="ghost"
              :data-testid="`promotion-open-review-${item.review_id}`"
              @click="jumpToTarget(withSourceFocusTarget(item.target, 'promotion_receipt', indexConsole.lastPromotionResult?.actor_ref || '__promotion_receipt__'))"
            >
              Open Review
            </button>
          </div>
        </article>

        <article v-if="indexConsole.systemRuntimeTimelineItems.length" class="paper receipt-card">
          <div class="receipt-head">
            <div>
              <h3>System Activity</h3>
              <p class="muted receipt-copy">Shows system-triggered runtime work alongside the operator receipts above.</p>
            </div>
            <span class="badge">runtime/system</span>
          </div>
          <div class="receipt-detail">
            <ul class="receipt-list">
              <li
                v-for="item in indexConsole.systemRuntimeTimelineItems"
                :key="item.operation_id"
                :class="{ 'focused-card': isFocusedSystemActivityItem(item) }"
              >
                <strong>{{ item.event_type }}</strong><br />
                {{ systemActivitySummary(item) }}<br />
                Actor: {{ systemActivityActor(item) }} | When: {{ item.created_at || "-" }}<br />
                Ref: {{ item.object_ref || "-" }} | Detail: {{ systemActivityDetail(item) }}
                <div v-if="systemActivityTargets(item).length" class="card-actions">
                  <button
                    v-for="target in systemActivityTargets(item)"
                    :key="target.target_ref"
                    class="ghost"
                    @click="jumpToTarget(withSourceFocusTarget(target, 'system_activity', item.operation_id))"
                  >
                    {{ systemTargetLabel(target) }}
                  </button>
                </div>
              </li>
            </ul>
          </div>
        </article>

        <article v-if="indexConsole.operatorActionTimelineItems.length" class="paper receipt-card">
          <div class="receipt-head">
            <div>
              <h3>Operator Activity</h3>
              <p class="muted receipt-copy">Shows persisted operator actions with the same target graph used by recovery receipts.</p>
            </div>
            <span class="badge">runtime/operator</span>
          </div>
          <div class="receipt-detail">
            <ul class="receipt-list">
              <li
                v-for="item in indexConsole.operatorActionTimelineItems"
                :key="item.operation_id"
                :class="{ 'focused-card': isFocusedOperatorActionItem(item) }"
              >
                <strong>{{ item.action || item.event_type }}</strong><br />
                Event: {{ item.event_id || item.object_ref || "-" }}<br />
                Actor: {{ item.actor_ref || "-" }} | When: {{ item.created_at || "-" }}<br />
                {{ operatorActionSummary(item) }}<br />
                Resolution: {{ item.resolution_reason || "-" }}
                <div v-if="operatorActionTargets(item).length" class="card-actions">
                  <button
                    v-for="target in operatorActionTargets(item)"
                    :key="target.target_ref"
                    class="ghost"
                    @click="jumpToTarget(withSourceFocusTarget(target, 'operator_action', item.operation_id))"
                  >
                    {{ systemTargetLabel(target) }}
                  </button>
                </div>
              </li>
            </ul>
          </div>
        </article>

        <article v-if="indexConsole.targetActivityGroups.length" class="paper receipt-card">
          <div class="receipt-head">
            <div>
              <h3>Target Activity</h3>
              <p class="muted receipt-copy">Aggregates recovery, system, and operator history by target so one object shows its full handling chain.</p>
            </div>
            <span class="badge">runtime/target-view</span>
          </div>
          <div class="receipt-detail">
            <ul class="receipt-list">
              <li
                v-for="group in prioritizedTargetActivityGroups"
                :key="group.target.target_ref"
                :data-testid="`target-activity-group-${group.target.target_ref}`"
                :class="{ 'focused-card': focusTarget?.target_ref === group.target.target_ref }"
              >
                <div class="target-group-head">
                  <div class="target-group-meta">
                    <strong>{{ group.target.target_ref }}</strong><br />
                    Latest: {{ group.latest_at || "-" }} | Count: {{ group.activity_count ?? 0 }} | Sources:
                    {{ group.sources?.join(", ") || "-" }}
                  </div>
                    <button
                      class="ghost target-group-toggle"
                      :data-testid="`target-activity-toggle-${group.target.target_ref}`"
                      @click="toggleTargetGroup(group)"
                    >
                      {{ isTargetGroupExpanded(group) ? "Hide Activity" : "Show Activity" }}
                    </button>
                  </div>
                <div class="card-actions">
                  <button class="ghost" @click="jumpToTarget(group.target)">
                    {{ systemTargetLabel(group.target) }}
                  </button>
                </div>
                <div v-if="isTargetGroupExpanded(group) && group.activity_items?.length" class="receipt-detail">
                  <ul class="receipt-list">
                      <li
                        v-for="item in orderedTargetActivityItems(group)"
                        :key="item.activity_key"
                        :data-testid="`target-activity-item-${item.activity_key}`"
                        :data-activity-key="item.activity_key"
                        :class="{
                          'focused-card': isFocusedActivityItem(group, item) || isSourceLinkedActivityItem(item),
                        'focused-activity-item': isFocusedActivityItem(group, item),
                      }"
                    >
                      <strong>{{ item.label || item.source }}</strong>
                      <span v-if="isFocusedActivityItem(group, item)" class="badge">Latest linked activity</span><br />
                      <span v-if="!isFocusedActivityItem(group, item) && isSourceLinkedActivityItem(item)" class="badge">Source-linked activity</span><br v-if="!isFocusedActivityItem(group, item)" />
                      {{ targetActivitySummary(item) }}<br />
                      {{ item.summary || "-" }}
                      <div v-if="item.target_refs?.length" class="card-actions">
                        <button
                          v-for="target in item.target_refs"
                          :key="`${item.activity_key}:${target.target_ref}`"
                          class="ghost"
                          @click="jumpToTarget(target)"
                        >
                          {{ systemTargetLabel(target) }}
                        </button>
                      </div>
                    </li>
                  </ul>
                </div>
                <p v-else-if="isTargetGroupExpanded(group)" class="muted target-group-empty">No activity items for this target yet.</p>
              </li>
            </ul>
          </div>
        </article>
      </template>
    </PanelShell>

    <PanelShell eyebrow="Jobs" title="Reindex / Verify">
      <div v-if="!indexConsole.jobs.length" class="empty">No index jobs are queued.</div>
      <div v-else class="job-table">
        <div
          v-for="item in prioritizedJobs"
          :key="item.job_id"
          class="job-row"
          :data-testid="`verify-job-${item.job_id}`"
          :class="{ 'focused-card': isFocusedJob(item.job_id) }"
        >
          <div class="job-main">
            <strong>{{ item.job_type }}</strong>
            <div class="muted">{{ item.job_id }}</div>
            <div class="muted">{{ item.alias_scope }}</div>
          </div>
          <div class="job-diagnostics">
            <p><strong>Status</strong><br />{{ item.status }}</p>
            <p><strong>Target Snapshot</strong><br />{{ item.target_snapshot_version || "-" }}</p>
            <p><strong>Target Embedding</strong><br />{{ item.target_embedding_version || "-" }}</p>
            <p><strong>Worker</strong><br />{{ item.worker_id || "-" }}</p>
            <p><strong>Attempt</strong><br />{{ item.attempt_no ?? 0 }}</p>
            <p><strong>Heartbeat</strong><br />{{ item.heartbeat_at || "-" }}</p>
            <p><strong>Lease Expires</strong><br />{{ item.lease_expires_at || "-" }}</p>
            <p><strong>Started</strong><br />{{ item.started_at || "-" }}</p>
            <p><strong>Finished</strong><br />{{ item.finished_at || "-" }}</p>
            <p><strong>Error</strong><br />{{ item.error_text || "-" }}</p>
          </div>
          <div class="job-actions">
            <button
              v-if="item.job_type === 'verify'"
              :disabled="indexConsole.actionId === item.job_id"
              :data-testid="`retry-verify-job-${item.job_id}`"
              @click="retry(item.job_id)"
            >
              Retry Verify
            </button>
            <span v-else class="muted">auto built</span>
          </div>
        </div>
      </div>
      <CursorPager
        test-id-prefix="jobs-pager"
        :pagination="indexConsole.jobPagination"
        :can-previous="Boolean(indexConsole.jobCursorStack.length)"
        :can-next="Boolean(indexConsole.jobPagination?.has_next)"
        :disabled="indexConsole.loading"
        @previous="previousJobPage"
        @next="nextJobPage"
      />
    </PanelShell>
  </section>
</template>
