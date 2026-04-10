<script setup>
import { computed, onMounted, reactive, ref } from "vue";

import PanelShell from "../components/PanelShell.vue";
import { useShellRouter } from "../router";
import { useKnowledgeConsoleStore } from "../stores/knowledgeConsole";

const emit = defineEmits(["notice"]);

const knowledgeConsole = useKnowledgeConsoleStore();
const { navigate, openTarget } = useShellRouter();

const objectTypeFilter = ref("");
const draft = reactive({
  reviewId: "",
  itemType: "style_rule_set",
  lineageKey: "",
  candidateText: "",
  scope: "global",
  scopeRefId: "global",
  chapterId: "CH001",
  sceneId: "CH001_SC01",
  characterId: "",
  leftCharacterId: "",
  rightCharacterId: "",
  ruleTier: "",
  activeOnApprove: 1,
  extraPayload: "",
});

const selectedEntryKey = computed(() =>
  knowledgeConsole.detail ? `${knowledgeConsole.detail.object_type}:${knowledgeConsole.detail.lineage_key}` : "",
);

const catalogItems = computed(() => knowledgeConsole.items || []);

function previewText(version) {
  if (!version?.text) {
    return "No staged text";
  }
  return version.text;
}

function selectEntry(item) {
  knowledgeConsole.selectItem(item.object_type, item.lineage_key).catch((error) => {
    emit("notice", error.message);
  });
}

async function refreshKnowledge() {
  await knowledgeConsole.load(objectTypeFilter.value);
  if (!knowledgeConsole.detail && knowledgeConsole.items.length) {
    await knowledgeConsole.selectItem(knowledgeConsole.items[0].object_type, knowledgeConsole.items[0].lineage_key);
  }
  if (knowledgeConsole.error) {
    emit("notice", knowledgeConsole.error);
  }
}

async function submitCandidate() {
  try {
    const message = await knowledgeConsole.createCandidate(draft);
    if (knowledgeConsole.lastCreateResult?.review_id) {
      openTarget(
        {
          target_type: "review_item",
          target_id: knowledgeConsole.lastCreateResult.review_id,
          target_ref: `review_item:${knowledgeConsole.lastCreateResult.review_id}`,
        },
        {
          view_id: "review",
          source_type: "knowledge_create",
          source_id: knowledgeConsole.lastCreateResult.review_id,
        },
      );
    }
    emit("notice", message);
  } catch (error) {
    emit("notice", error.message);
  }
}

function openReviewInbox(item) {
  const reviewId = item?.candidate_version?.review_id || item?.review_refs?.[0];
  if (!reviewId) {
    navigate("review");
    emit("notice", "Opened Review Inbox");
    return;
  }
  openTarget(
    {
      target_type: "review_item",
      target_id: reviewId,
      target_ref: `review_item:${reviewId}`,
    },
    {
      view_id: "review",
      source_type: "knowledge_console",
      source_id: reviewId,
    },
  );
  emit("notice", `Opened review_item:${reviewId}`);
}

function openIndexConsole(item) {
  navigate("index");
  emit("notice", `Opened Index Console for ${item.object_type}:${item.lineage_key}`);
}

onMounted(() => {
  refreshKnowledge();
});
</script>

<template>
  <section class="panel-grid" data-testid="knowledge-console-view">
    <PanelShell
      eyebrow="Knowledge Console"
      title="Stage new candidates and inspect active knowledge"
      description="Track active rows, pending review candidates, version history, and runtime references for each knowledge family."
    >
      <template #actions>
        <div class="field-inline">
          <select v-model="objectTypeFilter" class="control-input" data-testid="knowledge-filter-select" @change="refreshKnowledge">
            <option value="">All families</option>
            <option v-for="objectType in knowledgeConsole.supportedObjectTypes" :key="objectType" :value="objectType">
              {{ objectType }}
            </option>
          </select>
          <button data-testid="knowledge-refresh-button" @click="refreshKnowledge">Refresh</button>
        </div>
      </template>

      <div class="knowledge-layout">
        <article class="paper knowledge-form-card">
          <div class="receipt-head">
            <div>
              <h3>New Candidate</h3>
              <p class="muted receipt-copy">Create a review candidate here, then finish approval in Review Inbox and vector ops in Index Console.</p>
            </div>
            <span class="badge">POST /review-items</span>
          </div>
          <div class="knowledge-form-grid">
            <label>
              <span>Review ID</span>
              <input v-model="draft.reviewId" class="control-input" data-testid="knowledge-review-id" />
            </label>
            <label>
              <span>Item Type</span>
              <select v-model="draft.itemType" class="control-input" data-testid="knowledge-item-type">
                <option value="style_rule_set">style_rule_set</option>
                <option value="banned_rule_cluster">banned_rule_cluster</option>
                <option value="voice_card_candidate">voice_card_candidate</option>
                <option value="relation_card_candidate">relation_card_candidate</option>
                <option value="world_rule">world_rule</option>
                <option value="calibration_candidate">calibration_candidate</option>
                <option value="foreshadow_open">foreshadow_open</option>
                <option value="foreshadow_touch">foreshadow_touch</option>
                <option value="foreshadow_resolve">foreshadow_resolve</option>
                <option value="scene_summary">scene_summary</option>
                <option value="chapter_summary">chapter_summary</option>
                <option value="style_observation">style_observation</option>
              </select>
            </label>
            <label>
              <span>Lineage Key</span>
              <input v-model="draft.lineageKey" class="control-input" data-testid="knowledge-lineage-key" />
            </label>
            <label>
              <span>Active On Approve</span>
              <select v-model.number="draft.activeOnApprove" class="control-input" data-testid="knowledge-active-on-approve">
                <option :value="1">Yes</option>
                <option :value="0">No</option>
              </select>
            </label>
            <label>
              <span>Scope</span>
              <input v-model="draft.scope" class="control-input" />
            </label>
            <label>
              <span>Scope Ref</span>
              <input v-model="draft.scopeRefId" class="control-input" />
            </label>
            <label>
              <span>Chapter ID</span>
              <input v-model="draft.chapterId" class="control-input" />
            </label>
            <label>
              <span>Scene ID</span>
              <input v-model="draft.sceneId" class="control-input" />
            </label>
            <label>
              <span>Character ID</span>
              <input v-model="draft.characterId" class="control-input" />
            </label>
            <label>
              <span>Left Character</span>
              <input v-model="draft.leftCharacterId" class="control-input" />
            </label>
            <label>
              <span>Right Character</span>
              <input v-model="draft.rightCharacterId" class="control-input" />
            </label>
            <label>
              <span>Rule Tier</span>
              <input v-model="draft.ruleTier" class="control-input" />
            </label>
            <label class="knowledge-wide">
              <span>Candidate Text</span>
              <textarea v-model="draft.candidateText" class="control-input control-textarea" data-testid="knowledge-candidate-text" />
            </label>
            <label class="knowledge-wide">
              <span>Extra Payload JSON</span>
              <textarea v-model="draft.extraPayload" class="control-input control-textarea" placeholder='{"expires_at":"2099-01-01T00:00:00+00:00"}' />
            </label>
          </div>
          <div class="card-actions">
            <button :disabled="knowledgeConsole.actionId === 'create'" data-testid="knowledge-create-button" @click="submitCandidate">
              {{ knowledgeConsole.actionId === "create" ? "Creating..." : "Create Candidate" }}
            </button>
          </div>
        </article>

        <article class="paper knowledge-catalog-card">
          <div class="receipt-head">
            <div>
              <h3>Catalog</h3>
              <p class="muted receipt-copy">Active rows and staged candidates are merged into one lineage-first view.</p>
            </div>
            <span class="badge">{{ catalogItems.length }} lineages</span>
          </div>

          <div v-if="knowledgeConsole.loading" class="empty">Loading knowledge catalog...</div>
          <div v-else-if="knowledgeConsole.error" class="empty">{{ knowledgeConsole.error }}</div>
          <div v-else-if="!catalogItems.length" class="empty">No knowledge rows or staged candidates match this filter.</div>
          <div v-else class="knowledge-list">
            <article
              v-for="item in catalogItems"
              :key="`${item.object_type}:${item.lineage_key}`"
              class="review-card knowledge-card"
              :class="{ 'focused-card': selectedEntryKey === `${item.object_type}:${item.lineage_key}` }"
              :data-testid="`knowledge-card-${item.object_type}-${item.lineage_key}`"
            >
              <div class="source-top">
                <div>
                  <div class="eyebrow">{{ item.object_type }}</div>
                  <h3>{{ item.lineage_key }}</h3>
                </div>
                <span class="badge">{{ item.status || "tracked" }}</span>
              </div>
              <p><strong>Active</strong><br />{{ previewText(item.active_version) }}</p>
              <p><strong>Candidate</strong><br />{{ previewText(item.candidate_version) }}</p>
              <p class="muted">Runtime: {{ item.runtime_refs?.alias_scope || item.runtime_refs?.mode || "-" }}</p>
              <div class="card-actions">
                <button class="ghost" @click="selectEntry(item)">View Detail</button>
                <button class="ghost" @click="openReviewInbox(item)">View Review Inbox</button>
                <button class="ghost" @click="openIndexConsole(item)">Open Index Console</button>
              </div>
            </article>
          </div>
        </article>

        <article class="paper knowledge-detail-card">
          <div class="receipt-head">
            <div>
              <h3>Detail Drawer</h3>
              <p class="muted receipt-copy">Inspect active and candidate state, then jump to review or indexing workflows.</p>
            </div>
            <span v-if="knowledgeConsole.detail" class="badge">{{ knowledgeConsole.detail.object_type }}</span>
          </div>

          <div v-if="!knowledgeConsole.detail" class="empty">Select a lineage to inspect version history and runtime refs.</div>
          <template v-else>
            <p><strong>Lineage</strong><br />{{ knowledgeConsole.detail.lineage_key }}</p>
            <p><strong>Active Version</strong><br />{{ previewText(knowledgeConsole.detail.active_version) }}</p>
            <p><strong>Candidate Version</strong><br />{{ previewText(knowledgeConsole.detail.candidate_version) }}</p>
            <div class="history-stack">
              <p class="history-title">Runtime refs</p>
              <pre class="json-block">{{ JSON.stringify(knowledgeConsole.detail.runtime_refs || {}, null, 2) }}</pre>
            </div>
            <div class="history-stack">
              <p class="history-title">Version history</p>
              <ol class="history-list">
                <li v-for="version in knowledgeConsole.detail.versions || []" :key="version.row_id" class="history-entry">
                  <p class="history-meta">
                    <strong>{{ version.row_id }}</strong>
                    <span>v{{ version.version || "candidate" }}</span>
                  </p>
                  <p>{{ version.text || "-" }}</p>
                </li>
              </ol>
            </div>
          </template>
        </article>
      </div>
    </PanelShell>
  </section>
</template>
