<script setup>
import { onMounted } from "vue";

import PanelShell from "../components/PanelShell.vue";
import ReviewCard from "../components/ReviewCard.vue";
import { useIndexConsoleStore } from "../stores/indexConsole";
import { useReviewInboxStore } from "../stores/reviewInbox";

const emit = defineEmits(["notice"]);

const reviewInbox = useReviewInboxStore();
const indexConsole = useIndexConsoleStore();

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
    emit("notice", message);
  } catch (error) {
    emit("notice", error.message);
  }
}

async function release(reviewId) {
  try {
    const message = await reviewInbox.release(reviewId);
    await indexConsole.load();
    emit("notice", message);
  } catch (error) {
    emit("notice", error.message);
  }
}

onMounted(() => {
  refreshReviews();
});
</script>

<template>
  <section class="panel-grid">
    <PanelShell
      eyebrow="Review Inbox"
      title="Approve, materialize, and release"
      description="Keep a tight loop between review decisions and index state."
    >
      <template #actions>
        <button @click="refreshReviews">Refresh</button>
      </template>

      <div v-if="reviewInbox.loading" class="empty">Loading review items...</div>
      <div v-else-if="reviewInbox.error" class="empty">{{ reviewInbox.error }}</div>
      <div v-else-if="!reviewInbox.items.length" class="empty">No review items are waiting.</div>
      <div v-else class="review-list">
        <ReviewCard
          v-for="item in reviewInbox.items"
          :key="item.review_id"
          :item="item"
          :loading="reviewInbox.actionId === item.review_id"
          @approve="approve"
          @release="release"
        />
      </div>
    </PanelShell>
  </section>
</template>
