<script setup>
import { computed, onMounted } from "vue";

import HumanReviewDrawer from "../components/HumanReviewDrawer.vue";
import PanelShell from "../components/PanelShell.vue";
import ReviewCard from "../components/ReviewCard.vue";
import { useShellRouter } from "../router";
import { useIndexConsoleStore } from "../stores/indexConsole";
import { useReviewInboxStore } from "../stores/reviewInbox";

const emit = defineEmits(["notice"]);

const reviewInbox = useReviewInboxStore();
const indexConsole = useIndexConsoleStore();
const { focusTarget, openTarget } = useShellRouter();

const prioritizedRecoveryItems = computed(() => {
  const focusEventId = focusTarget.value?.target_type === "human_review_event" ? focusTarget.value.target_id : null;
  const items = [...reviewInbox.systemRecoveryItems];
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

async function refreshReviews() {
  await reviewInbox.load();
  if (reviewInbox.error) {
    emit("notice", reviewInbox.error);
  }
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
          <span v-if="reviewInbox.systemRecoveryItems.length" class="badge">
            {{ reviewInbox.systemRecoveryItems.length }} recovery event{{
              reviewInbox.systemRecoveryItems.length === 1 ? "" : "s"
            }}
          </span>
        </div>
      </template>

      <div v-if="reviewInbox.loading" class="empty">Loading review inbox...</div>
      <div v-else-if="reviewInbox.error" class="empty">{{ reviewInbox.error }}</div>
      <template v-else>
        <article v-if="reviewInbox.systemRecoveryItems.length" class="paper inline-error">
          <div class="receipt-head">
            <div>
              <h3>System Recovery</h3>
              <p class="muted receipt-copy">Recovery-generated human review events are surfaced here first for operator triage.</p>
            </div>
            <span class="badge">idempotency_recovery</span>
          </div>
          <HumanReviewDrawer
            :items="prioritizedRecoveryItems"
            :action-id="reviewInbox.actionId"
            :focus-event-id="focusedRecoveryEventId()"
            interactive
            @action="handleHumanReviewAction"
            @open-target="handleOpenTarget"
          />
        </article>

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
      </template>
    </PanelShell>
  </section>
</template>
