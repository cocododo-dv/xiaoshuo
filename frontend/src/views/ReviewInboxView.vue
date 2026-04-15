<script setup>
import { computed, onActivated, ref, watch } from "vue";

import CursorPager from "../components/CursorPager.vue";
import HumanReviewDrawer from "../components/HumanReviewDrawer.vue";
import PanelShell from "../components/PanelShell.vue";
import ReviewCard from "../components/ReviewCard.vue";
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
const reviewFocusRefreshPending = ref(false);
const focusTargetType = computed(() => focusTarget.value?.target_type || "");
const focusTargetId = computed(() => focusTarget.value?.target_id || "");
const focusTargetRef = computed(() => focusTarget.value?.target_ref || "");
const reviewIdsSignature = computed(() => (reviewInbox.items || []).map((item) => item.review_id || "").join("|"));
const visibleHumanReviewIdsSignature = computed(() =>
  visibleHumanReviewItems.value.map((item) => item.event_id || "").join("|"),
);
const reviewFocusSignature = computed(() =>
  [
    activeView.value,
    reviewInbox.loading ? "1" : "0",
    pendingFocusView.value || "",
    reviewFocusRefreshPending.value ? "1" : "0",
    focusTargetType.value,
    focusTargetId.value,
    focusTargetRef.value,
    reviewIdsSignature.value,
    visibleHumanReviewIdsSignature.value,
  ].join("::"),
);

const visibleHumanReviewItems = computed(() =>
  getVisibleHumanReviewItems(
    reviewInbox.humanReviewItems,
    reviewInbox.humanReviewFilters.eventSource,
    reviewInbox.systemRecoveryItems,
  ),
);

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

function reviewFocusDeferred() {
  return reviewFocusRefreshPending.value || pendingFocusView.value === "review";
}

function markDependentViewsStale() {
  indexConsole.markStale();
  knowledgeConsole.markStale();
  workbench.markStale();
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
      reviewInbox.items,
      visibleHumanReviewItems.value,
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

async function approve(reviewId) {
  try {
    const message = await reviewInbox.approve(reviewId);
    markDependentViewsStale();
    openTarget(reviewTarget(reviewId), {
      view_id: "review",
      source_type: "review_approve",
      source_id: reviewId,
    });
    emit("notice", message);
  } catch (error) {
    emit("notice", error.message);
  }
}

async function release(reviewId) {
  try {
    const message = await reviewInbox.release(reviewId);
    markDependentViewsStale();
    openTarget(reviewTarget(reviewId), {
      view_id: "review",
      source_type: "review_release",
      source_id: reviewId,
    });
    emit("notice", message);
  } catch (error) {
    emit("notice", error.message);
  }
}

async function handleHumanReviewAction({ eventId, action }) {
  try {
    const message = await reviewInbox.actOnHumanReviewEvent(eventId, action);
    indexConsole.recordRecoveryAction(reviewInbox.lastActionResult);
    markDependentViewsStale();
    emit("notice", message);
  } catch (error) {
    emit("notice", error.message);
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

onActivated(() => {
  ensureReviewInboxLoaded();
});

watch(
  reviewFocusSignature,
  () => {
    if (
      shouldClearReviewFocus(
        activeView.value,
        reviewInbox.loading,
        reviewFocusDeferred(),
        focusTarget.value,
        reviewInbox.items,
        visibleHumanReviewItems.value,
      )
    ) {
      clearFocus();
    }
  },
);
</script>

<template>
  <section class="panel-grid" data-testid="review-inbox-view">
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
        <div class="field-inline">
          <select v-model="reviewInbox.reviewFilters.status" data-testid="review-filter-status">
            <option value="">所有审核状态</option>
            <option value="pending">待处理</option>
            <option value="approved">已批准</option>
            <option value="rejected">已拒绝</option>
          </select>
          <button data-testid="review-filter-refresh" @click="refreshReviews">刷新</button>
          <button data-testid="review-filter-clear" @click="clearReviewFilters">清空</button>
        </div>
        <div class="field-inline">
          <select v-model="reviewInbox.humanReviewFilters.eventSource" data-testid="human-review-filter-event-source">
            <option value="">所有事件来源</option>
            <option value="idempotency_recovery">幂等恢复</option>
            <option value="manual_scene_review">手动场景审核</option>
          </select>
          <button data-testid="human-review-filter-refresh" @click="refreshReviews">刷新</button>
          <button data-testid="human-review-filter-clear" @click="clearHumanReviewFilters">清空</button>
        </div>
        <article v-if="visibleHumanReviewItems.length" class="paper inline-error">
          <div class="receipt-head">
            <div>
              <h3>{{ humanReviewSection.title }}</h3>
              <p class="muted receipt-copy">{{ humanReviewSection.description }}</p>
            </div>
            <span class="badge">{{ humanReviewSection.badge }}</span>
          </div>
          <HumanReviewDrawer
            :items="prioritizedHumanReviewItems"
            :action-id="reviewInbox.actionId"
            :focus-event-id="focusedRecoveryEventId()"
            interactive
            @action="handleHumanReviewAction"
            @open-target="handleOpenTarget"
          />
        </article>
        <div v-else-if="reviewInbox.humanReviewFilters.eventSource" class="empty">
          {{ humanReviewSection.empty }}
        </div>
        <CursorPager
          test-id-prefix="human-review-pager"
          :pagination="reviewInbox.humanReviewPagination"
          :can-previous="Boolean(reviewInbox.humanReviewCursorStack.length)"
          :can-next="Boolean(reviewInbox.humanReviewPagination?.has_next)"
          :disabled="reviewInbox.loading"
          @previous="previousHumanReviewPage"
          @next="nextHumanReviewPage"
        />

        <div v-if="!reviewInbox.items.length" class="empty">当前没有待处理审核项。</div>
        <div v-else class="review-list">
          <ReviewCard
            v-for="item in prioritizedReviewItems"
            :key="item.review_id"
            :item="item"
            :highlighted="focusedReviewId(item.review_id)"
            :source-action-label="reviewSourceActionLabel(item.review_id)"
            :loading="reviewInbox.actionId === item.review_id"
            @approve="approve"
            @release="release"
            @open-target="handleReviewOpenTarget"
          />
        </div>
        <CursorPager
          test-id-prefix="review-items-pager"
          :pagination="reviewInbox.reviewPagination"
          :can-previous="Boolean(reviewInbox.reviewCursorStack.length)"
          :can-next="Boolean(reviewInbox.reviewPagination?.has_next)"
          :disabled="reviewInbox.loading"
          @previous="previousReviewPage"
          @next="nextReviewPage"
        />
      </template>
    </PanelShell>
  </section>
</template>
