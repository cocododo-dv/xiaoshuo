<script setup>
import { computed, nextTick, onActivated, onBeforeUnmount, onDeactivated, reactive, ref, watch } from "vue";

import ActivitySectionCard from "../components/ActivitySectionCard.vue";
import AliasScopeCard from "../components/AliasScopeCard.vue";
import CursorPager from "../components/CursorPager.vue";
import PanelShell from "../components/PanelShell.vue";
import TargetActivityGroupCard from "../components/TargetActivityGroupCard.vue";
import VirtualList from "../components/VirtualList.vue";
import { shouldClearIndexFocus } from "../lib/filterFocus";
import { prioritizeMatchingItem } from "../lib/listPriority";
import { useShellRouter } from "../router";
import { useIndexConsoleStore } from "../stores/indexConsole";

const emit = defineEmits(["notice"]);
const indexConsole = useIndexConsoleStore();
const { activeView, focusTarget, openTarget, clearFocus, pendingFocusView, settleFocusView } = useShellRouter();
const isViewActive = ref(false);

const expandedSections = reactive({
  recovery_timeline: false,
  system_runtime: false,
  operator_action: false,
  target_groups: false,
});
const activeTargetGroupRef = ref("");
const indexFocusRefreshPending = ref(false);
const focusedActivityScrollFrameId = ref(0);
const maxFocusedActivityScrollAttempts = 12;

const actionLabels = {
  approve_review: "批准审核",
  release_review: "发布审核",
  retry_request: "重试请求",
  retry_verify: "重试校验",
  inspect: "查看详情",
};
const jobTypeLabels = { verify: "校验任务", reindex: "重建任务" };
const sourceLabels = {
  recovery_timeline: "恢复时间线",
  system_runtime: "系统活动",
  operator_action: "人工操作",
};
const statusLabels = {
  pending: "待处理",
  failed: "失败",
  succeeded: "成功",
  approved: "已批准",
  rejected: "已拒绝",
  resolved: "已解决",
  running: "进行中",
  queued: "排队中",
  released: "已发布",
};

const focusTargetType = computed(() => focusTarget.value?.target_type || "");
const focusTargetId = computed(() => focusTarget.value?.target_id || "");
const focusTargetRef = computed(() => focusTarget.value?.target_ref || "");
const focusedSourceType = computed(() => focusTarget.value?.source_type || "");
const focusedSourceId = computed(() => focusTarget.value?.source_id ?? null);

const prioritizedJobs = computed(() => {
  const focusJobId = ["verify_job", "reindex_job"].includes(focusTargetType.value) ? focusTargetId.value : null;
  return prioritizeMatchingItem(indexConsole.jobs, (item) => item.job_id === focusJobId);
});
const pinnedJobKeys = computed(() => {
  if (!["verify_job", "reindex_job"].includes(focusTargetType.value) || !focusTargetId.value) {
    return [];
  }
  return [focusTargetId.value];
});
const prioritizedTargetGroups = computed(() =>
  prioritizeMatchingItem(indexConsole.targetActivityGroups, (item) => item.target?.target_ref === focusTargetRef.value),
);
const pinnedTargetGroupKeys = computed(() => {
  if (!focusNeedsTargetGroups() || !focusTargetRef.value) {
    return [];
  }
  return [focusTargetRef.value];
});
const focusedTargetGroupMeta = computed(() => {
  if (!focusTargetRef.value) return null;
  return indexConsole.targetGroupMeta(focusTargetRef.value)
    || indexConsole.targetActivityGroups.find((group) => group?.target?.target_ref === focusTargetRef.value)
    || null;
});
const focusedActivityKey = computed(() => focusedTargetGroupMeta.value?.latestActivityKey || focusedTargetGroupMeta.value?.latest_activity_key || "");
const sourceLinkedActivityKey = computed(() => {
  if (["recovery_receipt", "recovery_timeline"].includes(focusedSourceType.value)) {
    return focusedSourceId.value ? `recovery_timeline:${focusedSourceId.value}` : "";
  }
  if (focusedSourceType.value === "system_activity") {
    return focusedSourceId.value ? `system_runtime:${focusedSourceId.value}` : "";
  }
  if (focusedSourceType.value === "operator_action") {
    return focusedSourceId.value ? `operator_action:${focusedSourceId.value}` : "";
  }
  return "";
});

const fmtAction = (value, fallback = "-") => actionLabels[value] || value || fallback;
const fmtJobType = (value, fallback = "-") => jobTypeLabels[value] || value || fallback;
const fmtSource = (value, fallback = "-") => sourceLabels[value] || value || fallback;
const fmtStatus = (value, fallback = "-") => statusLabels[value] || value || fallback;
const fmtValue = (value, fallback = "-") => (value === null || value === undefined || value === "" ? fallback : String(value));
const sectionSummary = {
  recovery_timeline: () => `已加载 ${indexConsole.recoveryTimelineItems.length} 条恢复活动`,
  system_runtime: () => `已加载 ${indexConsole.systemRuntimeTimelineItems.length} 条系统活动`,
  operator_action: () => `已加载 ${indexConsole.operatorActionTimelineItems.length} 条人工活动`,
  target_groups: () => `已加载 ${indexConsole.targetActivityGroups.length} 个目标摘要`,
};
const recoveryTimestamp = (item) => item?.details_json?.last_action_at || item?.last_action_at || item?.created_at || "-";
const recoveryActor = (item) => item?.actor_ref || item?.last_actor_ref || item?.details_json?.last_actor_ref || "-";
const recoveryTargetRef = (item) => item?.linked_target_ref || item?.details_json?.linked_target_ref || "-";
const recoveryResolution = (item) => item?.resolution_reason || item?.details_json?.resolution_reason || "-";
const recoveryAction = (item) => item?.action || item?.last_action || item?.details_json?.last_action || item?.default_action || "inspect";
const recoveryFollowup = (item) => [item?.followup_action || item?.details_json?.followup_action, item?.followup_target_ref || item?.details_json?.followup_target_ref].filter(Boolean).join(" -> ") || "-";
const operatorSummary = (item) => [fmtAction(item?.action, item?.action || "-"), fmtStatus(item?.status_before, item?.status_before || "-"), "->", fmtStatus(item?.status_after, item?.status_after || "-")].join(" ");
const targetSummary = (item) => [fmtSource(item?.source, item?.source || "-"), fmtStatus(item?.status, item?.status || "-"), fmtValue(item?.actor_ref), fmtValue(item?.timestamp)].join(" | ");

function parseTargetRef(targetRef) {
  if (!targetRef || !targetRef.includes(":")) return null;
  const [targetType, targetId] = targetRef.split(":", 2);
  return targetType && targetId ? { target_type: targetType, target_id: targetId, target_ref: targetRef } : null;
}
function replayTargetFromResult(result) {
  if (result?.review_id) return { target_type: "review_item", target_id: result.review_id, target_ref: `review_item:${result.review_id}` };
  if (!result?.job_id) return null;
  const type = result.job_type === "reindex" ? "reindex_job" : "verify_job";
  return { target_type: type, target_id: result.job_id, target_ref: `${type}:${result.job_id}` };
}
const recoveryLinkedTarget = (item) => item?.linked_target || parseTargetRef(item?.linked_target_ref || item?.details_json?.linked_target_ref);
const recoveryFollowupTarget = (item) => item?.followup_target || parseTargetRef(item?.followup_target_ref || item?.details_json?.followup_target_ref);
const recoveryReplayTarget = (item) => item?.replay_target || replayTargetFromResult(item?.replay_result || item?.last_replay_result || item?.details_json?.last_replay_result);
const reviewTarget = (reviewId) => (reviewId ? { target_type: "review_item", target_id: reviewId, target_ref: `review_item:${reviewId}` } : null);
const humanReviewTarget = (eventId) => (eventId ? { target_type: "human_review_event", target_id: eventId, target_ref: `human_review_event:${eventId}` } : null);
const jobTarget = (item) => item?.job_id ? { target_type: item.job_type === "reindex" ? "reindex_job" : "verify_job", target_id: item.job_id, target_ref: `${item.job_type === "reindex" ? "reindex_job" : "verify_job"}:${item.job_id}` } : null;
const activityItemKey = (sectionId, item) => {
  if (item?.activity_key) return item.activity_key;
  if (sectionId === "recovery_timeline" && item?.event_id) return `recovery_timeline:${item.event_id}`;
  if (sectionId === "system_runtime" && item?.operation_id !== undefined) return `system_runtime:${item.operation_id}`;
  if (sectionId === "operator_action" && item?.operation_id !== undefined) return `operator_action:${item.operation_id}`;
  return "";
};
const activityTargets = (item) => {
  if (Array.isArray(item?.target_refs) && item.target_refs.length) return item.target_refs;
  const parsedTarget = parseTargetRef(item?.target_ref);
  return parsedTarget ? [parsedTarget] : [];
};

function withSourceTarget(target, sourceType, sourceId) {
  if (!target) return null;
  return { ...target, source_type: sourceType, source_id: sourceId };
}
function withIndexFocusTarget(target, sourceType, sourceId) {
  if (!target) return null;
  return { ...withSourceTarget(target, sourceType, sourceId), view_id: "index" };
}
function jumpToTarget(target) {
  if (!target) return;
  openTarget(target);
  if (target.view_id === "index") {
    syncIndexFocus();
  }
  emit("notice", `已打开目标：${target.target_ref}`);
}
function targetActionLabel(target) {
  if (target?.target_type === "review_item") return "打开审核";
  if (target?.target_type === "human_review_event") return "打开恢复事件";
  if (target?.target_type === "verify_job") return "打开校验任务";
  if (target?.target_type === "reindex_job") return "打开重建任务";
  return target?.target_ref || "打开目标";
}
function isFocusedSource(type, id) { return focusedSourceType.value === type && focusedSourceId.value === id; }
function focusNeedsTargetGroups() { return Boolean(focusTargetRef.value) && !["verify_job", "reindex_job"].includes(focusTargetType.value); }
function focusedSourceSection() {
  if (["recovery_receipt", "recovery_timeline"].includes(focusedSourceType.value)) return "recovery_timeline";
  if (focusedSourceType.value === "system_activity") return "system_runtime";
  if (focusedSourceType.value === "operator_action") return "operator_action";
  return "";
}
function groupItems(targetRef) { return indexConsole.targetGroupItemsByRef[targetRef] || []; }
function groupLoading(targetRef) { return Boolean(indexConsole.targetGroupState(targetRef)?.loading); }
function groupCanPrevious(targetRef) { return Boolean(indexConsole.targetGroupState(targetRef)?.pager?.cursorStack?.length); }
function groupCanNext(targetRef) { return Boolean(indexConsole.targetGroupPagination(targetRef)?.has_next); }
function sectionCanPrevious(sectionId) { return Boolean(indexConsole.activitySectionState(sectionId)?.pager?.cursorStack?.length); }
function sectionCanNext(sectionId) { return Boolean(indexConsole.activitySectionPagination(sectionId)?.has_next); }

function cancelFocusedActivityScroll() {
  if (!focusedActivityScrollFrameId.value) return;
  cancelAnimationFrame(focusedActivityScrollFrameId.value);
  focusedActivityScrollFrameId.value = 0;
}

function scheduleFocusedActivityScroll(activityKey, targetRef, attempt = 0) {
  cancelFocusedActivityScroll();
  if (!activityKey || !targetRef || typeof document === "undefined") return;

  focusedActivityScrollFrameId.value = requestAnimationFrame(async () => {
    focusedActivityScrollFrameId.value = 0;
    if (!isViewActive.value || activeView.value !== "index" || !expandedSections.target_groups) return;
    if (activeTargetGroupRef.value !== targetRef) return;

    await nextTick();
    const activityElement = document.querySelector(`[data-activity-key="${activityKey}"]`);
    if (activityElement?.scrollIntoView) {
      activityElement.scrollIntoView({ block: "nearest", behavior: "smooth" });
      return;
    }

    if (attempt + 1 >= maxFocusedActivityScrollAttempts) return;
    scheduleFocusedActivityScroll(activityKey, targetRef, attempt + 1);
  });
}

async function openSection(sectionId, force = false) {
  expandedSections[sectionId] = true;
  await indexConsole.ensureActivitySectionLoaded(sectionId, { force });
}
async function toggleSection(sectionId) {
  if (expandedSections[sectionId]) {
    expandedSections[sectionId] = false;
    if (sectionId === "target_groups") activeTargetGroupRef.value = "";
    return;
  }
  await openSection(sectionId);
}
async function toggleTargetGroup(group) {
  const targetRef = group?.target?.target_ref || "";
  if (!targetRef) return;
  if (activeTargetGroupRef.value === targetRef) {
    activeTargetGroupRef.value = "";
    return;
  }
  activeTargetGroupRef.value = targetRef;
  await indexConsole.ensureTargetGroupItemsLoaded(targetRef);
}
async function ensureFocusSections(force = false) {
  const sourceSection = focusedSourceSection();
  if (sourceSection) await openSection(sourceSection, force);
  if (!focusNeedsTargetGroups()) return;
  await openSection("target_groups", force);
  if (indexConsole.hasTargetActivityGroup(focusTargetRef.value)) {
    activeTargetGroupRef.value = focusTargetRef.value;
    await indexConsole.ensureTargetGroupItemsLoaded(focusTargetRef.value, { force });
  }
}
async function syncIndexFocus(force = false) {
  if (!focusTargetRef.value && !focusedSourceSection()) return;
  indexFocusRefreshPending.value = true;
  try {
    await ensureFocusSections(force);
  } finally {
    indexFocusRefreshPending.value = false;
  }
}
async function ensureVisibleSections(force = false) {
  const openSections = Object.keys(expandedSections).filter((key) => expandedSections[key]);
  await Promise.all(openSections.map((sectionId) => indexConsole.ensureActivitySectionLoaded(sectionId, { force })));
  if (expandedSections.target_groups && activeTargetGroupRef.value) {
    await indexConsole.ensureTargetGroupItemsLoaded(activeTargetGroupRef.value, { force });
  }
}
async function ensureIndexLoaded() {
  indexFocusRefreshPending.value = true;
  try {
    await indexConsole.ensureLoaded();
    await ensureFocusSections();
    await ensureVisibleSections();
  } finally {
    indexFocusRefreshPending.value = false;
  }
  if (indexConsole.error) emit("notice", indexConsole.error);
  settleFocusView("index");
  if (
    shouldClearIndexFocus(
      activeView.value,
      indexConsole.loading || indexConsole.activityLoading,
      indexFocusRefreshPending.value || pendingFocusView.value === "index",
      focusTarget.value,
      indexConsole.aliasScopes,
      (jobId) => indexConsole.hasJob(jobId),
      (targetRef) => indexConsole.hasTargetActivityGroup(targetRef),
    )
  ) {
    clearFocus();
  }
}
async function refreshIndex() {
  indexFocusRefreshPending.value = true;
  try {
    await indexConsole.ensureLoaded({ force: true });
    await ensureVisibleSections(true);
    await ensureFocusSections(true);
  } finally {
    indexFocusRefreshPending.value = false;
  }
  if (indexConsole.error) emit("notice", indexConsole.error);
}
const previousJobPage = async () => { await indexConsole.previousJobPage(); if (indexConsole.error) emit("notice", indexConsole.error); };
const nextJobPage = async () => { await indexConsole.nextJobPage(); if (indexConsole.error) emit("notice", indexConsole.error); };
const previousSectionPage = async (sectionId) => { await indexConsole.previousActivitySectionPage(sectionId); if (indexConsole.error) emit("notice", indexConsole.error); };
const nextSectionPage = async (sectionId) => { await indexConsole.nextActivitySectionPage(sectionId); if (indexConsole.error) emit("notice", indexConsole.error); };
const previousGroupPage = async (targetRef) => { await indexConsole.previousTargetGroupItemsPage(targetRef); if (indexConsole.error) emit("notice", indexConsole.error); };
const nextGroupPage = async (targetRef) => { await indexConsole.nextTargetGroupItemsPage(targetRef); if (indexConsole.error) emit("notice", indexConsole.error); };
const clearAliasFilters = async () => { indexConsole.clearAliasFilters(); await refreshIndex(); };
const clearJobFilters = async () => { indexConsole.clearJobFilters(); await refreshIndex(); };
const clearLedgerFilters = async () => { indexConsole.clearLedgerFilters(); await refreshIndex(); };
const runRecovery = async () => { try { emit("notice", await indexConsole.runRecovery()); await ensureVisibleSections(true); await ensureFocusSections(true); } catch (error) { emit("notice", error.message); } };
const runDuePromotions = async () => { try { emit("notice", await indexConsole.runDuePromotions()); await ensureVisibleSections(true); await ensureFocusSections(true); } catch (error) { emit("notice", error.message); } };
const retry = async (jobId) => { try { emit("notice", await indexConsole.retryVerifyJob(jobId)); await ensureVisibleSections(true); await ensureFocusSections(true); } catch (error) { emit("notice", error.message); } };

watch(() => [activeView.value, focusTargetRef.value, focusedSourceType.value, focusedSourceId.value], async ([viewId]) => {
  if (!isViewActive.value) return;
  if (viewId !== "index") return;
  if (!focusTargetRef.value && !focusedSourceSection()) return;
  await syncIndexFocus();
}, { immediate: true });

watch(() => indexConsole.targetGroupsVersion, async () => {
  if (activeTargetGroupRef.value && !indexConsole.hasTargetActivityGroup(activeTargetGroupRef.value)) {
    activeTargetGroupRef.value = "";
  }
  if (!isViewActive.value || activeView.value !== "index" || !focusNeedsTargetGroups()) return;
  if (!indexConsole.hasTargetActivityGroup(focusTargetRef.value)) return;
  activeTargetGroupRef.value = focusTargetRef.value;
  await indexConsole.ensureTargetGroupItemsLoaded(focusTargetRef.value);
}, { immediate: true });

watch(() => [focusedActivityKey.value, sourceLinkedActivityKey.value, activeTargetGroupRef.value, groupItems(activeTargetGroupRef.value).length], ([focusedKey, linkedKey, targetRef]) => {
  if (!isViewActive.value || activeView.value !== "index" || !expandedSections.target_groups) {
    cancelFocusedActivityScroll();
    return;
  }
  if (!targetRef || typeof document === "undefined") {
    cancelFocusedActivityScroll();
    return;
  }
  const activityKey = focusedKey || linkedKey;
  if (!activityKey) {
    cancelFocusedActivityScroll();
    return;
  }
  scheduleFocusedActivityScroll(activityKey, targetRef);
}, { immediate: true });

watch(() => [
  activeView.value,
  indexConsole.loading,
  indexConsole.activityLoading,
  pendingFocusView.value || "",
  indexFocusRefreshPending.value,
  focusTargetType.value,
  focusTargetId.value,
  focusTargetRef.value,
  indexConsole.jobsVersion,
  indexConsole.targetGroupsVersion,
], () => {
  if (!isViewActive.value) return;
  if (
    shouldClearIndexFocus(
      activeView.value,
      indexConsole.loading || indexConsole.activityLoading,
      indexFocusRefreshPending.value || pendingFocusView.value === "index",
      focusTarget.value,
      indexConsole.aliasScopes,
      (jobId) => indexConsole.hasJob(jobId),
      (targetRef) => indexConsole.hasTargetActivityGroup(targetRef),
    )
  ) {
    clearFocus();
  }
}, { immediate: true });

onActivated(() => {
  isViewActive.value = true;
  ensureIndexLoaded();
});

onDeactivated(() => {
  isViewActive.value = false;
  indexFocusRefreshPending.value = false;
  cancelFocusedActivityScroll();
});

onBeforeUnmount(() => {
  cancelFocusedActivityScroll();
});
</script>

<template>
  <section class="panel-grid" data-testid="index-console-view">
    <PanelShell eyebrow="索引控制台" title="别名、校验与恢复" description="把长列表拆成摘要优先、明细按需的控制台。">
      <template #actions>
        <div class="field-inline">
          <button @click="refreshIndex">刷新</button>
          <button :disabled="indexConsole.actionId === 'promotions'" data-testid="run-due-promotions-button" @click="runDuePromotions">{{ indexConsole.actionId === "promotions" ? "发布中..." : "运行到期发布" }}</button>
          <button :disabled="indexConsole.actionId === 'recovery'" data-testid="run-recovery-sweep-button" @click="runRecovery">{{ indexConsole.actionId === "recovery" ? "恢复中..." : "恢复扫描" }}</button>
        </div>
      </template>

      <div v-if="indexConsole.loading" class="empty">正在加载别名范围...</div>
      <div v-else-if="indexConsole.error && !indexConsole.aliasScopes.length && !indexConsole.jobs.length" class="empty">{{ indexConsole.error }}</div>
      <template v-else>
        <div class="field-inline">
          <select v-model="indexConsole.aliasFilters.verifyStatus" data-testid="index-alias-filter-verify-status"><option value="">全部别名校验状态</option><option value="pending">待处理</option><option value="failed">失败</option><option value="succeeded">成功</option></select>
          <button data-testid="index-alias-filter-refresh" @click="refreshIndex">刷新</button>
          <button data-testid="index-alias-filter-clear" @click="clearAliasFilters">清空</button>
        </div>
        <div class="field-inline">
          <select v-model="indexConsole.jobFilters.jobType" data-testid="index-job-filter-job-type"><option value="">全部任务</option><option value="verify">校验任务</option><option value="reindex">重建任务</option></select>
          <input v-model="indexConsole.jobFilters.reviewId" data-testid="index-job-filter-review-id" placeholder="审核 ID" />
          <input v-model="indexConsole.jobFilters.workerId" data-testid="index-job-filter-worker-id" placeholder="工作器 ID" />
          <label class="checkbox-inline"><input v-model="indexConsole.jobFilters.stuckOnly" data-testid="index-job-filter-stuck-only" type="checkbox" /><span>仅看卡住任务</span></label>
          <button data-testid="index-job-filter-refresh" @click="refreshIndex">刷新</button>
          <button data-testid="index-job-filter-clear" @click="clearJobFilters">清空</button>
        </div>
        <div class="field-inline">
          <input v-model="indexConsole.ledgerFilters.targetRef" data-testid="index-ledger-filter-target-ref" placeholder="目标引用" />
          <select v-model="indexConsole.ledgerFilters.source" data-testid="index-ledger-filter-source"><option value="">全部来源</option><option value="recovery_timeline">恢复时间线</option><option value="system_runtime">系统活动</option><option value="operator_action">人工操作活动</option></select>
          <button data-testid="index-ledger-filter-refresh" @click="refreshIndex">刷新</button>
          <button data-testid="index-ledger-filter-clear" @click="clearLedgerFilters">清空</button>
        </div>
        <div v-if="!indexConsole.aliasScopes.length" class="empty">还没有别名范围。</div>
        <div v-else class="alias-grid">
          <AliasScopeCard v-for="item in indexConsole.aliasScopes" :key="item.alias_scope" :item="item" />
        </div>

        <!-- RECEIPTS -->
        <article v-if="indexConsole.lastRecoveryResult" class="paper receipt-card" data-testid="recovery-receipt" :class="{ 'focused-card': isFocusedSource('recovery_sweep', indexConsole.lastRecoveryResult?.actor_ref || '__recovery_sweep__') }">
          <div class="receipt-head"><div><h3>恢复回执</h3><p class="muted receipt-copy">记录最近一次恢复扫描的结果。</p></div><span class="badge">恢复扫描</span></div>
          <div class="receipt-grid">
            <p><strong>回收任务</strong><br />{{ indexConsole.lastRecoveryResult.reclaimed_jobs ?? 0 }}</p>
            <p><strong>失败任务</strong><br />{{ indexConsole.lastRecoveryResult.failed_jobs ?? 0 }}</p>
            <p><strong>执行者</strong><br />{{ indexConsole.lastRecoveryResult.actor_ref || "-" }}</p>
            <p><strong>人工审核事件</strong><br />{{ indexConsole.lastRecoveryResult.created_human_review_events ?? 0 }}</p>
          </div>
          <div v-if="(indexConsole.lastRecoveryResult.created_human_review_event_targets || []).length" class="receipt-detail">
            <div class="card-actions">
              <button v-for="item in indexConsole.lastRecoveryResult.created_human_review_event_targets" :key="item.event_id" type="button" class="ghost" :data-testid="`recovery-created-event-${item.event_id}`" @click="jumpToTarget(withSourceTarget(item.target, 'recovery_sweep', indexConsole.lastRecoveryResult?.actor_ref || '__recovery_sweep__'))">{{ item.event_id }}</button>
            </div>
          </div>
        </article>

        <article v-if="indexConsole.lastRecoveryActionResult" class="paper receipt-card" data-testid="recovery-followup-receipt" :class="{ 'focused-card': isFocusedSource('recovery_receipt', indexConsole.lastRecoveryActionResult?.event_id || null) }">
          <div class="receipt-head"><div><h3>恢复后续</h3><p class="muted receipt-copy">显示最近一次人工处理及其后续目标。</p></div><span class="badge">恢复后续</span></div>
          <div class="receipt-grid">
            <p><strong>事件</strong><br />{{ indexConsole.lastRecoveryActionResult.event_id || "-" }}</p>
            <p><strong>动作</strong><br />{{ fmtAction(indexConsole.lastRecoveryActionResult.action, indexConsole.lastRecoveryActionResult.action || "-") }}</p>
            <p><strong>执行者</strong><br />{{ recoveryActor(indexConsole.lastRecoveryActionResult) }}</p>
            <p><strong>状态</strong><br />{{ fmtStatus(indexConsole.lastRecoveryActionResult.status, indexConsole.lastRecoveryActionResult.status || "-") }}</p>
            <p><strong>关联目标</strong><br />{{ recoveryTargetRef(indexConsole.lastRecoveryActionResult) }}</p>
            <p><strong>处理结论</strong><br />{{ recoveryResolution(indexConsole.lastRecoveryActionResult) }}</p>
          </div>
          <div v-if="recoveryLinkedTarget(indexConsole.lastRecoveryActionResult) || recoveryFollowupTarget(indexConsole.lastRecoveryActionResult) || recoveryReplayTarget(indexConsole.lastRecoveryActionResult)" class="card-actions">
            <button v-if="recoveryLinkedTarget(indexConsole.lastRecoveryActionResult)" type="button" class="ghost" data-testid="recovery-followup-open-linked-target" @click="jumpToTarget(withSourceTarget(recoveryLinkedTarget(indexConsole.lastRecoveryActionResult), 'recovery_receipt', indexConsole.lastRecoveryActionResult?.event_id || null))">打开关联目标</button>
            <button v-if="recoveryFollowupTarget(indexConsole.lastRecoveryActionResult)" type="button" class="ghost" data-testid="recovery-followup-open-followup-target" @click="jumpToTarget(withSourceTarget(recoveryFollowupTarget(indexConsole.lastRecoveryActionResult), 'recovery_receipt', indexConsole.lastRecoveryActionResult?.event_id || null))">打开后续目标</button>
            <button v-if="recoveryReplayTarget(indexConsole.lastRecoveryActionResult)" type="button" class="ghost" data-testid="recovery-followup-open-replay-result" @click="jumpToTarget(withSourceTarget(recoveryReplayTarget(indexConsole.lastRecoveryActionResult), 'recovery_receipt', indexConsole.lastRecoveryActionResult?.event_id || null))">打开回放结果</button>
          </div>
        </article>

        <article v-if="indexConsole.lastPromotionResult" class="paper receipt-card" data-testid="promotion-receipt" :class="{ 'focused-card': isFocusedSource('promotion_receipt', indexConsole.lastPromotionResult?.actor_ref || '__promotion_receipt__') }">
          <div class="receipt-head"><div><h3>发布回执</h3><p class="muted receipt-copy">记录最近一次到期发布。</p></div><span class="badge">到期发布</span></div>
          <div class="receipt-grid">
            <p><strong>已发布数量</strong><br />{{ indexConsole.lastPromotionResult.promoted ?? 0 }}</p>
            <p><strong>执行者</strong><br />{{ indexConsole.lastPromotionResult.actor_ref || "-" }}</p>
            <p><strong>别名范围</strong><br />{{ indexConsole.lastPromotionResult.promoted_alias_scopes?.join(", ") || "-" }}</p>
            <p><strong>审核 ID</strong><br />{{ indexConsole.lastPromotionResult.promoted_review_ids?.join(", ") || "-" }}</p>
          </div>
          <div v-if="(indexConsole.lastPromotionResult.promoted_review_targets || []).length" class="card-actions">
            <button v-for="item in indexConsole.lastPromotionResult.promoted_review_targets" :key="item.review_id" type="button" class="ghost" :data-testid="`promotion-open-review-${item.review_id}`" @click="jumpToTarget(withIndexFocusTarget(item.target || reviewTarget(item.review_id), 'promotion_receipt', indexConsole.lastPromotionResult?.actor_ref || '__promotion_receipt__'))">打开审核 {{ item.review_id }}</button>
          </div>
        </article>

        <ActivitySectionCard
          title="恢复时间线"
          description="恢复事件保持折叠，只有在需要排查时再展开读取。"
          :summary="sectionSummary.recovery_timeline()"
          badge="恢复"
          :expanded="expandedSections.recovery_timeline"
          :loading="indexConsole.activitySectionState('recovery_timeline').loading"
          toggle-test-id="index-toggle-recovery-timeline"
          @toggle="toggleSection('recovery_timeline')"
        >
          <div v-if="!indexConsole.recoveryTimelineItems.length" class="empty">当前没有恢复活动。</div>
          <template v-else>
            <VirtualList
              class="receipt-list"
              :items="indexConsole.recoveryTimelineItems"
              :item-key="(item) => item.event_id || activityItemKey('recovery_timeline', item)"
              :estimated-item-height="176"
              :threshold="8"
              :viewport-height="560"
              test-id="index-recovery-virtual-list"
            >
              <template #default="{ item }">
                <article
                  :data-activity-key="activityItemKey('recovery_timeline', item)"
                  :class="{ 'focused-card': isFocusedSource('recovery_timeline', item.event_id) || isFocusedSource('recovery_receipt', item.event_id) }"
                >
                <strong>{{ item.event_id || item.label || "恢复事件" }}</strong><br />
                {{ recoveryTimestamp(item) }} | {{ fmtStatus(item.status, item.status || "-") }} | {{ recoveryActor(item) }}<br />
                关联目标：{{ recoveryTargetRef(item) }} | 动作：{{ fmtAction(recoveryAction(item), recoveryAction(item)) }} | 结论：{{ recoveryResolution(item) }}
                <p v-if="recoveryFollowup(item) !== '-'" class="muted activity-inline-copy">
                  后续：{{ recoveryFollowup(item) }}
                </p>
                <div class="card-actions">
                  <button
                    v-if="humanReviewTarget(item.event_id)"
                    type="button"
                    class="ghost"
                    @click="jumpToTarget(withSourceTarget(humanReviewTarget(item.event_id), 'recovery_timeline', item.event_id))"
                  >
                    打开恢复事件
                  </button>
                  <button
                    v-if="recoveryLinkedTarget(item)"
                    type="button"
                    class="ghost"
                    @click="jumpToTarget(withIndexFocusTarget(recoveryLinkedTarget(item), 'recovery_timeline', item.event_id))"
                  >
                    打开关联目标
                  </button>
                  <button
                    v-if="recoveryFollowupTarget(item)"
                    type="button"
                    class="ghost"
                    @click="jumpToTarget(withIndexFocusTarget(recoveryFollowupTarget(item), 'recovery_timeline', item.event_id))"
                  >
                    打开后续目标
                  </button>
                  <button
                    v-if="recoveryReplayTarget(item)"
                    type="button"
                    class="ghost"
                    @click="jumpToTarget(withIndexFocusTarget(recoveryReplayTarget(item), 'recovery_timeline', item.event_id))"
                  >
                    打开回放结果
                  </button>
                </div>
                </article>
              </template>
            </VirtualList>
            <CursorPager
              test-id-prefix="recovery-timeline-pager"
              :pagination="indexConsole.activitySectionPagination('recovery_timeline')"
              :can-previous="sectionCanPrevious('recovery_timeline')"
              :can-next="sectionCanNext('recovery_timeline')"
              :disabled="indexConsole.activitySectionState('recovery_timeline').loading"
              @previous="previousSectionPage('recovery_timeline')"
              @next="nextSectionPage('recovery_timeline')"
            />
          </template>
        </ActivitySectionCard>

        <ActivitySectionCard
          title="系统活动"
          description="系统运行时事件按需读取，避免首屏吞掉整包 payload。"
          :summary="sectionSummary.system_runtime()"
          badge="系统"
          :expanded="expandedSections.system_runtime"
          :loading="indexConsole.activitySectionState('system_runtime').loading"
          toggle-test-id="index-toggle-system-runtime"
          @toggle="toggleSection('system_runtime')"
        >
          <div v-if="!indexConsole.systemRuntimeTimelineItems.length" class="empty">当前没有系统活动。</div>
          <template v-else>
            <ul class="receipt-list">
              <li
                v-for="item in indexConsole.systemRuntimeTimelineItems"
                :key="activityItemKey('system_runtime', item)"
                :data-activity-key="activityItemKey('system_runtime', item)"
                :class="{ 'focused-card': isFocusedSource('system_activity', item.operation_id) }"
              >
                <strong>{{ item.label || item.event_type || "系统活动" }}</strong><br />
                {{ targetSummary(item) }}<br />
                {{ item.summary || item.description || "-" }}
                <div v-if="activityTargets(item).length" class="card-actions">
                  <button
                    v-for="target in activityTargets(item)"
                    :key="`${activityItemKey('system_runtime', item)}:${target.target_ref}`"
                    type="button"
                    class="ghost"
                    @click="jumpToTarget(withIndexFocusTarget(target, 'system_activity', item.operation_id))"
                  >
                    {{ targetActionLabel(target) }}
                  </button>
                </div>
              </li>
            </ul>
            <CursorPager
              test-id-prefix="system-runtime-pager"
              :pagination="indexConsole.activitySectionPagination('system_runtime')"
              :can-previous="sectionCanPrevious('system_runtime')"
              :can-next="sectionCanNext('system_runtime')"
              :disabled="indexConsole.activitySectionState('system_runtime').loading"
              @previous="previousSectionPage('system_runtime')"
              @next="nextSectionPage('system_runtime')"
            />
          </template>
        </ActivitySectionCard>

        <ActivitySectionCard
          title="人工操作"
          description="操作流保持收起，避免每次进入索引页都渲染长时间线。"
          :summary="sectionSummary.operator_action()"
          badge="操作"
          :expanded="expandedSections.operator_action"
          :loading="indexConsole.activitySectionState('operator_action').loading"
          toggle-test-id="index-toggle-operator-action"
          @toggle="toggleSection('operator_action')"
        >
          <div v-if="!indexConsole.operatorActionTimelineItems.length" class="empty">当前没有人工操作记录。</div>
          <template v-else>
            <ul class="receipt-list">
              <li
                v-for="item in indexConsole.operatorActionTimelineItems"
                :key="activityItemKey('operator_action', item)"
                :data-activity-key="activityItemKey('operator_action', item)"
                :class="{ 'focused-card': isFocusedSource('operator_action', item.operation_id) }"
              >
                <strong>{{ item.label || item.action || "人工操作" }}</strong><br />
                {{ targetSummary(item) }}<br />
                {{ item.summary || item.description || "-" }}
                <div v-if="activityTargets(item).length" class="card-actions">
                  <button
                    v-for="target in activityTargets(item)"
                    :key="`${activityItemKey('operator_action', item)}:${target.target_ref}`"
                    type="button"
                    class="ghost"
                    @click="jumpToTarget(withIndexFocusTarget(target, 'operator_action', item.operation_id))"
                  >
                    {{ targetActionLabel(target) }}
                  </button>
                </div>
              </li>
            </ul>
            <CursorPager
              test-id-prefix="operator-action-pager"
              :pagination="indexConsole.activitySectionPagination('operator_action')"
              :can-previous="sectionCanPrevious('operator_action')"
              :can-next="sectionCanNext('operator_action')"
              :disabled="indexConsole.activitySectionState('operator_action').loading"
              @previous="previousSectionPage('operator_action')"
              @next="nextSectionPage('operator_action')"
            />
          </template>
        </ActivitySectionCard>

        <ActivitySectionCard
          title="目标活动组"
          description="先展示轻量摘要，展开单个目标时再读取该组明细。"
          :summary="sectionSummary.target_groups()"
          badge="目标"
          :expanded="expandedSections.target_groups"
          :loading="indexConsole.activitySectionState('target_groups').loading"
          toggle-test-id="index-toggle-target-groups"
          @toggle="toggleSection('target_groups')"
        >
          <div v-if="!prioritizedTargetGroups.length" class="empty">当前没有目标活动摘要。</div>
          <template v-else>
            <VirtualList
              class="receipt-list target-group-list"
              :items="prioritizedTargetGroups"
              :item-key="(group) => group.target.target_ref"
              :estimated-item-height="220"
              :threshold="8"
              :viewport-height="640"
              :pinned-keys="pinnedTargetGroupKeys"
              test-id="index-target-groups-virtual-list"
            >
              <template #default="{ item: group }">
                <TargetActivityGroupCard
                  :group="group"
                  :expanded="activeTargetGroupRef === group.target.target_ref"
                  :loading="groupLoading(group.target.target_ref)"
                  :items="groupItems(group.target.target_ref)"
                  :pagination="indexConsole.targetGroupPagination(group.target.target_ref)"
                  :can-previous="groupCanPrevious(group.target.target_ref)"
                  :can-next="groupCanNext(group.target.target_ref)"
                  :focused="group.target.target_ref === focusTargetRef"
                  :focused-activity-key="group.target.target_ref === focusTargetRef ? focusedActivityKey : ''"
                  :source-linked-activity-key="group.target.target_ref === focusTargetRef ? sourceLinkedActivityKey : ''"
                  @toggle="toggleTargetGroup"
                  @open-target="jumpToTarget"
                  @previous="previousGroupPage"
                  @next="nextGroupPage"
                />
              </template>
            </VirtualList>
            <CursorPager
              test-id-prefix="target-groups-pager"
              :pagination="indexConsole.activitySectionPagination('target_groups')"
              :can-previous="sectionCanPrevious('target_groups')"
              :can-next="sectionCanNext('target_groups')"
              :disabled="indexConsole.activitySectionState('target_groups').loading"
              @previous="previousSectionPage('target_groups')"
              @next="nextSectionPage('target_groups')"
            />
          </template>
        </ActivitySectionCard>
      </template>
    </PanelShell>

    <PanelShell eyebrow="任务" title="重建索引与校验">
      <div v-if="!indexConsole.jobs.length" class="empty">当前没有排队中的索引任务。</div>
      <VirtualList
        v-else
        class="job-table"
        :items="prioritizedJobs"
        item-key="job_id"
        :estimated-item-height="240"
        :threshold="8"
        :viewport-height="640"
        :pinned-keys="pinnedJobKeys"
        test-id="index-jobs-virtual-list"
      >
        <template #default="{ item }">
          <div class="job-row" :data-testid="`verify-job-${item.job_id}`" :class="{ 'focused-card': ['verify_job', 'reindex_job'].includes(focusTargetType) && focusTargetId === item.job_id }">
          <div class="job-main"><strong>{{ fmtJobType(item.job_type, item.job_type || "-") }}</strong><div class="muted">{{ item.job_id }}</div><div class="muted">{{ item.alias_scope }}</div></div>
          <div class="job-diagnostics">
            <p><strong>状态</strong><br />{{ fmtStatus(item.status, item.status || "-") }}</p>
            <p><strong>目标快照</strong><br />{{ item.target_snapshot_version || "-" }}</p>
            <p><strong>目标嵌入</strong><br />{{ item.target_embedding_version || "-" }}</p>
            <p><strong>工作器</strong><br />{{ item.worker_id || "-" }}</p>
            <p><strong>尝试次数</strong><br />{{ item.attempt_no ?? 0 }}</p>
            <p><strong>心跳时间</strong><br />{{ item.heartbeat_at || "-" }}</p>
            <p><strong>租约到期</strong><br />{{ item.lease_expires_at || "-" }}</p>
            <p><strong>开始时间</strong><br />{{ item.started_at || "-" }}</p>
            <p><strong>完成时间</strong><br />{{ item.finished_at || "-" }}</p>
            <p><strong>错误</strong><br />{{ item.error_text || "-" }}</p>
          </div>
          <div class="job-actions">
            <button v-if="item.job_type === 'verify'" :disabled="indexConsole.actionId === item.job_id" :data-testid="`retry-verify-job-${item.job_id}`" @click="retry(item.job_id)">重试校验</button>
            <span v-else class="muted">自动生成</span>
          </div>
          </div>
        </template>
      </VirtualList>
      <CursorPager test-id-prefix="jobs-pager" :pagination="indexConsole.jobPagination" :can-previous="Boolean(indexConsole.jobCursorStack.length)" :can-next="Boolean(indexConsole.jobPagination?.has_next)" :disabled="indexConsole.loading" @previous="previousJobPage" @next="nextJobPage" />
    </PanelShell>
  </section>
</template>
