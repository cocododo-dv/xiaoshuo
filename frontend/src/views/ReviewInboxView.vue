<script setup>
import { computed, onMounted, ref, watch } from "vue";

import CursorPager from "../components/CursorPager.vue";
import HumanReviewDrawer from "../components/HumanReviewDrawer.vue";
import PanelShell from "../components/PanelShell.vue";
import ReviewCard from "../components/ReviewCard.vue";
import { getVisibleHumanReviewItems, shouldClearReviewFocus } from "../lib/filterFocus";
import { useShellRouter } from "../router";
import { useIndexConsoleStore } from "../stores/indexConsole";
import { useReviewInboxStore } from "../stores/reviewInbox";

const emit = defineEmits(["notice"]);

const reviewInbox = useReviewInboxStore();
const indexConsole = useIndexConsoleStore();
const shellRouter = useShellRouter();
// const { activeView, focusTarget, openTarget } = useShellRouter()
const { activeView, focusTarget, openTarget, clearFocus, pendingFocusView, settleFocusView } = shellRouter;
const reviewFocusRefreshPending = ref(false);

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
      title: "Manual Scene Review",
      description: "Manual scene review events that match the current filters appear here.",
      badge: "manual_scene_review",
      countLabel: "manual review event",
      empty: "No manual scene review events match the current filters.",
    };
  }
  return {
    title: "System Recovery",
    description: "Recovery-generated human review events are surfaced here first for operator triage.",
    badge: "idempotency_recovery",
    countLabel: "recovery event",
    empty: "No recovery-generated human review events match the current filters.",
  };
});

const prioritizedHumanReviewItems = computed(() => {
  const focusEventId = focusTarget.value?.target_type === "human_review_event" ? focusTarget.value.target_id : null;
  const items = [...visibleHumanReviewItems.value];
  if (!focusEventId) {
    return items;
  }
  return items.sort((left, right) => Number(right.event_id === focusEventId) - Number(left.event_id === focusEventId));
});

const prioritizedReviewItems = computed(() => {
  const focusReviewId = focusTarget.value?.target_type === "review_item" ? focusTarget.value.target_id : null;
  const items = [...reviewInbox.items];
  if (!focusReviewId) {
    return items;
  }
  return items.sort((left, right) => Number(right.review_id === focusReviewId) - Number(left.review_id === focusReviewId));
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
    return "Approved here";
  }
  if (focusTarget.value?.source_type === "review_release") {
    return "Released here";
  }
  if (focusTarget.value?.source_type === "review_card_open") {
    return "Opened in index";
  }
  return "";
}

function reviewFocusDeferred() {
  return reviewFocusRefreshPending.value || pendingFocusView.value === "review";
}

async function refreshReviews() {
  await reviewInbox.load();
  if (reviewInbox.error) {
    emit("notice", reviewInbox.error);
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
    await indexConsole.load();
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
    await indexConsole.load();
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
    await indexConsole.load();
    emit("notice", message);
  } catch (error) {
    emit("notice", error.message);
  }
}

function handleOpenTarget(target) {
  openTarget(target);
  emit("notice", `Opened ${target.target_ref}`);
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
  emit("notice", `Opened ${target.target_ref}`);
}

onMounted(() => {
  refreshReviews();
});

watch(
  () => activeView.value,
  async (nextView, previousView) => {
    if (nextView === "review" && previousView !== "review") {
      reviewFocusRefreshPending.value = true;
      try {
        await refreshReviews();
      } finally {
        reviewFocusRefreshPending.value = false;
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
  },
);

watch(
  () => [
    focusTarget.value,
    reviewInbox.loading,
    pendingFocusView.value,
    reviewFocusRefreshPending.value,
    reviewInbox.items,
    visibleHumanReviewItems.value,
  ],
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
  { deep: true },
);
</script>

<template>
  <section class="panel-grid" data-testid="review-inbox-view">
    <PanelShell
      eyebrow="Review Inbox"
      title="Approve, materialize, and release"
      description="Keep a tight loop between review decisions and index state."
    >
      <template #actions>
        <div class="field-inline">
          <button @click="refreshReviews">Refresh</button>
          <span v-if="visibleHumanReviewItems.length" class="badge">
            {{ visibleHumanReviewItems.length }} {{ humanReviewSection.countLabel }}{{
              visibleHumanReviewItems.length === 1 ? "" : "s"
            }}
          </span>
        </div>
      </template>

      <div v-if="reviewInbox.loading" class="empty">Loading review inbox...</div>
      <div v-else-if="reviewInbox.error" class="empty">{{ reviewInbox.error }}</div>
      <template v-else>
        <div class="field-inline">
          <select v-model="reviewInbox.reviewFilters.status" data-testid="review-filter-status">
            <option value="">All review statuses</option>
            <option value="pending">pending</option>
            <option value="approved">approved</option>
            <option value="rejected">rejected</option>
          </select>
          <button data-testid="review-filter-refresh" @click="refreshReviews">Refresh</button>
          <button data-testid="review-filter-clear" @click="clearReviewFilters">Clear</button>
        </div>
        <div class="field-inline">
          <select v-model="reviewInbox.humanReviewFilters.eventSource" data-testid="human-review-filter-event-source">
            <option value="">All event sources</option>
            <option value="idempotency_recovery">idempotency_recovery</option>
            <option value="manual_scene_review">manual_scene_review</option>
          </select>
          <button data-testid="human-review-filter-refresh" @click="refreshReviews">Refresh</button>
          <button data-testid="human-review-filter-clear" @click="clearHumanReviewFilters">Clear</button>
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

        <div v-if="!reviewInbox.items.length" class="empty">No review items are waiting.</div>
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
