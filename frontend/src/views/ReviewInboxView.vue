<script setup>
import { computed, onActivated, onDeactivated, ref, watch } from "vue";

import CursorPager from "../components/CursorPager.vue";
import FlowActionReceipt from "../components/FlowActionReceipt.vue";
import HumanReviewDrawer from "../components/HumanReviewDrawer.vue";
import PanelShell from "../components/PanelShell.vue";
import ReviewCard from "../components/ReviewCard.vue";
import VirtualList from "../components/VirtualList.vue";
import WorkflowPageHeader from "../components/WorkflowPageHeader.vue";
import { useFlowActionFeedback } from "../composables/useFlowActionFeedback";
import { getVisibleHumanReviewItems, shouldClearReviewFocus } from "../lib/filterFocus";
import { prioritizeMatchingItem } from "../lib/listPriority";
import { useShellRouter } from "../router";
import { useIndexConsoleStore } from "../stores/indexConsole";
import { useKnowledgeConsoleStore } from "../stores/knowledgeConsole";
import { useReviewInboxStore } from "../stores/reviewInbox";
import { useWorkbenchStore } from "../stores/workbench";

const emit = defineEmits(["notice"]);

const reviewInbox = useReviewInboxStore();
const indexConsole = useIndexConsoleStore();
const knowledgeConsole = useKnowledgeConsoleStore();
const workbench = useWorkbenchStore();
const shellRouter = useShellRouter();
const { activeView, focusTarget, openTarget, clearFocus, pendingFocusView, settleFocusView } = shellRouter;
const { navigate } = shellRouter;
const isViewActive = ref(false);
const reviewFocusRefreshPending = ref(false);
const { receipt, runFlowAction } = useFlowActionFeedback({
  emitNotice: (message) => emit("notice", message),
});
const focusTargetType = computed(() => focusTarget.value?.target_type || "");
const focusTargetId = computed(() => focusTarget.value?.target_id || "");
const focusTargetRef = computed(() => focusTarget.value?.target_ref || "");

const visibleHumanReviewItems = computed(() =>
  getVisibleHumanReviewItems(
    reviewInbox.humanReviewItems,
    reviewInbox.humanReviewFilters.eventSource,
    reviewInbox.systemRecoveryItems,
    reviewInbox.humanReviewFilters.status,
  ),
);
const hasHumanReviewFilter = computed(() =>
  Boolean(
    reviewInbox.humanReviewFilters.eventSource ||
      reviewInbox.humanReviewFilters.status ||
      reviewInbox.humanReviewFilters.priority ||
      reviewInbox.humanReviewFilters.owner ||
      reviewInbox.humanReviewFilters.sceneId ||
      reviewInbox.humanReviewFilters.chapterId,
  ),
);
const shouldShowHumanReviewSection = computed(() => visibleHumanReviewItems.value.length > 0 || hasHumanReviewFilter.value);
const shouldShowHumanReviewPager = computed(() =>
  visibleHumanReviewItems.value.length > 0 ||
  Boolean(reviewInbox.humanReviewCursorStack.length) ||
  Boolean(reviewInbox.humanReviewPagination?.has_next),
);
const reviewItemsSummary = computed(() => {
  const pagination = reviewInbox.reviewPagination || {};
  const returned = pagination.returned ?? reviewInbox.items.length;
  const total = pagination.total ?? reviewInbox.items.length;
  return `当前 ${returned} / 共 ${total}`;
});

const humanReviewSection = computed(() => {
  if (reviewInbox.humanReviewFilters.eventSource === "manual_scene_review") {
    return {
      title: "手动场景审核",
      description: "这里会展示符合当前筛选条件的手动场景审核事件。",
      badge: "manual_scene_review",
      countLabel: "条手动审核事件",
      empty: "当前筛选条件下没有手动场景审核事件。",
    };
  }
  return {
    title: "系统恢复",
    description: "恢复流程产生的人工作业会优先汇总到这里，供操作员继续处理。",
    badge: "idempotency_recovery",
    countLabel: "条恢复事件",
    empty: "当前筛选条件下没有恢复流程生成的人工作业事件。",
  };
});

const prioritizedHumanReviewItems = computed(() => {
  const focusEventId = focusTargetType.value === "human_review_event" ? focusTargetId.value : null;
  return prioritizeMatchingItem(visibleHumanReviewItems.value, (item) => item.event_id === focusEventId);
});

const prioritizedReviewItems = computed(() => {
  const focusReviewId = focusTargetType.value === "review_item" ? focusTargetId.value : null;
  return prioritizeMatchingItem(reviewInbox.items, (item) => item.review_id === focusReviewId);
});

const pinnedReviewKeys = computed(() => {
  if (focusTargetType.value !== "review_item" || !focusTargetId.value) {
    return [];
  }

  return [focusTargetId.value];
});
const reviewRowMapVersion = computed(() => [
  focusTargetType.value,
  focusTargetId.value,
  focusTarget.value?.source_type || "",
  reviewInbox.actionId || "",
].join("::"));

function focusedReviewId(reviewId) {
  return focusTarget.value?.target_type === "review_item" && focusTarget.value.target_id === reviewId;
}

function focusedRecoveryEventId() {
  return focusTarget.value?.target_type === "human_review_event" ? focusTarget.value.target_id : "";
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

function reviewSourceActionLabel(reviewId) {
  if (!(focusTarget.value?.target_type === "review_item" && focusTarget.value.target_id === reviewId)) {
    return "";
  }
  if (focusTarget.value?.source_type === "review_approve") {
    return "已在此批准";
  }
  if (focusTarget.value?.source_type === "review_release") {
    return "已在此发布";
  }
  if (focusTarget.value?.source_type === "review_card_open") {
    return "已在索引页打开";
  }
  return "";
}

function reviewInboxRow(item) {
  const reviewId = item?.review_id || "";

  return {
    item,
    reviewId,
    highlighted: focusedReviewId(reviewId),
    sourceActionLabel: reviewSourceActionLabel(reviewId),
    loading: reviewInbox.actionId === reviewId,
  };
}

function reviewFocusDeferred() {
  return reviewFocusRefreshPending.value || pendingFocusView.value === "review";
}

function markDependentViewsStale() {
  indexConsole.markStale();
  knowledgeConsole.markStale();
  workbench.markStale();
}

function reviewReceiptScope(reviewId) {
  return `review:${reviewId || "unknown"}`;
}

function humanReviewReceiptScope(eventId) {
  return `human-review:${eventId || "unknown"}`;
}

function focusReviewAction(reviewId, sourceType) {
  if (activeView.value !== "review") {
    return;
  }
  openTarget(reviewTarget(reviewId), {
    view_id: "review",
    source_type: sourceType,
    source_id: reviewId,
  });
}

async function refreshReviews() {
  await reviewInbox.load({ force: true });
  if (reviewInbox.error) {
    emit("notice", reviewInbox.error);
  }
}

async function ensureReviewInboxLoaded() {
  reviewFocusRefreshPending.value = true;
  try {
    await reviewInbox.ensureLoaded();
  } finally {
    reviewFocusRefreshPending.value = false;
  }

  if (reviewInbox.error) {
    emit("notice", reviewInbox.error);
  }

  settleFocusView("review");
  if (
    shouldClearReviewFocus(
      activeView.value,
      reviewInbox.loading,
      reviewFocusDeferred(),
      focusTarget.value,
      (reviewId) => reviewInbox.hasReviewItem(reviewId),
      (eventId) => reviewInbox.hasVisibleHumanReviewEvent(eventId, reviewInbox.humanReviewFilters.eventSource),
    )
  ) {
    clearFocus();
  }
}

async function nextReviewPage() {
  await reviewInbox.nextReviewPage();
  if (reviewInbox.error) {
    emit("notice", reviewInbox.error);
  }
}

async function previousReviewPage() {
  await reviewInbox.previousReviewPage();
  if (reviewInbox.error) {
    emit("notice", reviewInbox.error);
  }
}

async function nextHumanReviewPage() {
  await reviewInbox.nextHumanReviewPage();
  if (reviewInbox.error) {
    emit("notice", reviewInbox.error);
  }
}

async function previousHumanReviewPage() {
  await reviewInbox.previousHumanReviewPage();
  if (reviewInbox.error) {
    emit("notice", reviewInbox.error);
  }
}

function clearReviewFilters() {
  reviewInbox.clearReviewFilters();
  refreshReviews();
}

function clearHumanReviewFilters() {
  reviewInbox.clearHumanReviewFilters();
  refreshReviews();
}

async function approve(reviewId, payload = {}) {
  const result = await runFlowAction({
    scopeKey: reviewReceiptScope(reviewId),
    actionLabel: "批准审核",
    runningMessage: "正在提交批准并落地候选内容...",
    successMessage: (message) => message || "审核已批准。",
    nextStep: () => "下一步：如果发布按钮亮起，继续点击「发布」让内容进入生效链路。",
    action: () => reviewInbox.approve(reviewId, payload),
  });
  if (result) {
    markDependentViewsStale();
    focusReviewAction(reviewId, "review_approve");
  }
}

async function release(reviewId) {
  const result = await runFlowAction({
    scopeKey: reviewReceiptScope(reviewId),
    actionLabel: "发布审核",
    runningMessage: "正在发布已批准内容...",
    successMessage: (message) => message || "审核已发布。",
    nextStep: () => "下一步：查看知识控制台或场景工作台，确认运行时 bundle 已引用新内容。",
    action: () => reviewInbox.release(reviewId),
  });
  if (result) {
    markDependentViewsStale();
    focusReviewAction(reviewId, "review_release");
  }
}

async function handleHumanReviewAction({ eventId, action }) {
  const result = await runFlowAction({
    scopeKey: humanReviewReceiptScope(eventId),
    actionLabel: "处理人工审核",
    runningMessage: "正在执行恢复/人工审核动作...",
    successMessage: (message) => message || "人工审核动作已完成。",
    nextStep: () => "下一步：打开关联目标或刷新列表，继续处理后续项。",
    action: () => reviewInbox.actOnHumanReviewEvent(eventId, action),
  });
  if (result) {
    indexConsole.recordRecoveryAction(reviewInbox.lastActionResult);
    markDependentViewsStale();
  }
}

function handleOpenTarget(target) {
  openTarget(target);
  emit("notice", `已打开 ${target.target_ref}`);
}

function handleReviewOpenTarget(reviewId) {
  const target = reviewTarget(reviewId);
  if (!target) {
    return;
  }
  openTarget(target, {
    view_id: "index",
    source_type: "review_card_open",
    source_id: reviewId,
  });
  emit("notice", `已打开 ${target.target_ref}`);
}

function handleReviewOpenVerifyJob(jobId, reviewId) {
  if (!jobId) {
    return;
  }
  const target = {
    target_type: "verify_job",
    target_id: jobId,
    target_ref: `verify_job:${jobId}`,
  };
  openTarget(target, {
    view_id: "index",
    source_type: "review_verify_job",
    source_id: reviewId,
  });
  emit("notice", `已打开校验任务 ${jobId}`);
}

function handleReviewOpenReference(reviewId) {
  navigate("reference");
  emit("notice", reviewId ? `已回到参考书学习：${reviewId}` : "已回到参考书学习");
}

onActivated(() => {
  isViewActive.value = true;
  ensureReviewInboxLoaded();
});

onDeactivated(() => {
  isViewActive.value = false;
  reviewFocusRefreshPending.value = false;
});

watch(
  () => [
    activeView.value,
    reviewInbox.loading,
    pendingFocusView.value || "",
    reviewFocusRefreshPending.value,
    focusTargetType.value,
    focusTargetId.value,
    focusTargetRef.value,
    reviewInbox.reviewItemsVersion,
    reviewInbox.humanReviewItemsVersion,
    reviewInbox.humanReviewFilters.eventSource,
  ],
  () => {
    if (!isViewActive.value) {
      return;
    }
    if (
      shouldClearReviewFocus(
        activeView.value,
        reviewInbox.loading,
        reviewFocusDeferred(),
        focusTarget.value,
        (reviewId) => reviewInbox.hasReviewItem(reviewId),
        (eventId) => reviewInbox.hasVisibleHumanReviewEvent(eventId, reviewInbox.humanReviewFilters.eventSource),
      )
    ) {
      clearFocus();
    }
  },
  { immediate: true },
);
</script>

<template>
  <section class="panel-grid" data-testid="review-inbox-view">
    <WorkflowPageHeader view-id="review" />
    <PanelShell
      eyebrow="审核收件箱"
      title="批准、落地与发布"
      description="让审核决策与索引状态保持紧密闭环。"
    >
      <template #actions>
        <div class="field-inline">
          <button @click="refreshReviews">刷新</button>
          <span v-if="visibleHumanReviewItems.length" class="badge">
            {{ visibleHumanReviewItems.length }}{{ humanReviewSection.countLabel }}
          </span>
        </div>
      </template>

      <div v-if="reviewInbox.loading" class="empty">正在加载审核收件箱...</div>
      <div v-else-if="reviewInbox.error" class="empty">{{ reviewInbox.error }}</div>
      <template v-else>
        <section class="review-inbox-section review-inbox-filters" data-testid="review-inbox-filters">
          <div>
            <h3>筛选</h3>
            <p class="muted">普通审核项和人工事件分开筛选，避免两个列表互相干扰。</p>
          </div>
          <div class="review-filter-grid">
            <div class="field-inline">
              <select v-model="reviewInbox.reviewFilters.status" data-testid="review-filter-status">
                <option value="">所有审核状态</option>
                <option value="pending">待处理</option>
                <option value="approved">已批准</option>
                <option value="rejected">已拒绝</option>
              </select>
              <button data-testid="review-filter-refresh" @click="refreshReviews">刷新审核项</button>
              <button data-testid="review-filter-clear" @click="clearReviewFilters">清空</button>
            </div>
            <div class="field-inline">
              <select v-model="reviewInbox.humanReviewFilters.eventSource" data-testid="human-review-filter-event-source">
                <option value="">所有事件来源</option>
                <option value="idempotency_recovery">幂等恢复</option>
                <option value="manual_scene_review">手动场景审核</option>
              </select>
              <button data-testid="human-review-filter-refresh" @click="refreshReviews">刷新人工事件</button>
              <button data-testid="human-review-filter-clear" @click="clearHumanReviewFilters">清空</button>
            </div>
          </div>
        </section>

        <section v-if="shouldShowHumanReviewSection" class="review-inbox-section" data-testid="human-review-section">
          <div class="review-inbox-section-head">
            <div>
              <h3>{{ humanReviewSection.title }}</h3>
              <p class="muted receipt-copy">{{ humanReviewSection.description }}</p>
            </div>
            <span class="badge">{{ visibleHumanReviewItems.length }}{{ humanReviewSection.countLabel }}</span>
          </div>
          <HumanReviewDrawer
            v-if="visibleHumanReviewItems.length"
            :items="prioritizedHumanReviewItems"
            :action-id="reviewInbox.actionId"
            :focus-event-id="focusedRecoveryEventId()"
            interactive
            @action="handleHumanReviewAction"
            @open-target="handleOpenTarget"
          />
          <FlowActionReceipt
            v-if="focusedRecoveryEventId()"
            compact
            :receipt="receipt(humanReviewReceiptScope(focusedRecoveryEventId()))"
          />
          <div v-if="!visibleHumanReviewItems.length" class="empty subtle-empty">{{ humanReviewSection.empty }}</div>
          <CursorPager
            v-if="shouldShowHumanReviewPager"
            label="人工事件"
            :hide-when-empty="true"
            test-id-prefix="human-review-pager"
            :pagination="reviewInbox.humanReviewPagination"
            :can-previous="Boolean(reviewInbox.humanReviewCursorStack.length)"
            :can-next="Boolean(reviewInbox.humanReviewPagination?.has_next)"
            :disabled="reviewInbox.loading"
            @previous="previousHumanReviewPage"
            @next="nextHumanReviewPage"
          />
        </section>

        <section class="review-inbox-section" data-testid="review-items-section">
          <div class="review-inbox-section-head">
            <div>
              <h3>审核项</h3>
              <p class="muted">普通候选在这里批准、发布，技术载荷默认收起。</p>
            </div>
            <span class="badge">审核项 · {{ reviewItemsSummary }}</span>
          </div>
          <div v-if="!reviewInbox.items.length" class="empty">当前没有待处理审核项。</div>
          <VirtualList
            v-else
            class="review-list"
            :items="prioritizedReviewItems"
            item-key="review_id"
            :estimated-item-height="220"
            :pinned-keys="pinnedReviewKeys"
            :threshold="10"
            :viewport-height="640"
            :map-item="reviewInboxRow"
            :map-version="reviewRowMapVersion"
            test-id="review-inbox-virtual-list"
          >
            <template #default="{ row }">
              <div class="flow-action-card-shell">
                <ReviewCard
                  :item="row.item"
                  :highlighted="row.highlighted"
                  :source-action-label="row.sourceActionLabel"
                  :loading="row.loading"
                  @approve="approve"
                  @release="release"
                  @open-target="handleReviewOpenTarget"
                  @open-reference="handleReviewOpenReference"
                  @open-verify-job="handleReviewOpenVerifyJob"
                />
                <FlowActionReceipt compact :receipt="receipt(reviewReceiptScope(row.reviewId))" />
              </div>
            </template>
          </VirtualList>
          <CursorPager
            label="审核项"
            :hide-when-empty="true"
            test-id-prefix="review-items-pager"
            :pagination="reviewInbox.reviewPagination"
            :can-previous="Boolean(reviewInbox.reviewCursorStack.length)"
            :can-next="Boolean(reviewInbox.reviewPagination?.has_next)"
            :disabled="reviewInbox.loading"
            @previous="previousReviewPage"
            @next="nextReviewPage"
          />
        </section>
      </template>
    </PanelShell>
  </section>
</template>
