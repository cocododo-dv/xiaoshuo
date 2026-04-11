<script setup>
import { computed, onMounted, reactive, watch } from "vue";

import PanelShell from "../components/PanelShell.vue";
import { useShellRouter } from "../router";
import { useKnowledgeConsoleStore } from "../stores/knowledgeConsole";

const emit = defineEmits(["notice"]);

const knowledgeConsole = useKnowledgeConsoleStore();
const { focusTarget, navigate, openTarget } = useShellRouter();

const filters = reactive({
  objectType: knowledgeConsole.filters?.objectType || "",
  scope: knowledgeConsole.filters?.scope || "",
  scopeRefId: knowledgeConsole.filters?.scopeRefId || "",
  status: knowledgeConsole.filters?.status || "",
});
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
  knowledgeConsole.selectedObjectType && knowledgeConsole.selectedLineageKey
    ? `${knowledgeConsole.selectedObjectType}:${knowledgeConsole.selectedLineageKey}`
    : "",
);

const catalogItems = computed(() => knowledgeConsole.items || []);
const detailReviewRefs = computed(() => knowledgeConsole.detail?.review_refs || []);
const detailBundleRefs = computed(() => knowledgeConsole.detail?.bundle_refs || []);
const detailWorkflow = computed(() => knowledgeConsole.detail?.workflow || {});
const workflowReviewItems = computed(() => detailWorkflow.value.review_items || []);
const workflowJobs = computed(() => detailWorkflow.value.jobs || []);
const workflowHumanReviewEvents = computed(() => detailWorkflow.value.human_review_events || []);
const workflowTargetActivityGroups = computed(() => detailWorkflow.value.target_activity_groups || []);
const primaryWorkflowAction = computed(() => detailWorkflow.value.recommended_primary_action || null);
const workflowStatusItems = computed(() => {
  const reviewStatus = workflowReviewItems.value[0]?.status || "clear";
  const verifyJob = workflowJobs.value.find((job) => job.job_type === "verify");
  const verifyStatus = verifyJob?.status || knowledgeConsole.detail?.runtime_refs?.verify_status || "not_required";
  const unresolvedHumanReview = workflowHumanReviewEvents.value.find((item) => item.status !== "resolved");
  return [
    { label: "Knowledge", value: knowledgeConsole.detail?.status || "unknown" },
    { label: "Review", value: reviewStatus },
    { label: "Verify", value: verifyStatus },
    {
      label: "Human Review",
      value: unresolvedHumanReview?.status || (workflowHumanReviewEvents.value.length ? "resolved" : "clear"),
    },
  ];
});

function previewText(version) {
  if (!version?.text) {
    return "No staged text";
  }
  return version.text;
}

function actionLabel(action) {
  return {
    approve_review: "Approve",
    retry_verify: "Retry Verify",
    release_review: "Release",
    retry_request: "Retry Request",
    inspect: "Inspect",
  }[action] || action?.replaceAll("_", " ") || "Action";
}

function canReleaseReview(review) {
  if (!review?.approved_item_row_id) {
    return false;
  }
  if (knowledgeConsole.detail?.active_version?.row_id === review.approved_item_row_id) {
    return false;
  }
  return !workflowJobs.value.some(
    (job) => job.job_type === "verify" && job.review_id === review.review_id && job.status !== "succeeded",
  );
}

function jobTarget(job) {
  if (!job?.job_id || !job?.job_type) {
    return null;
  }
  const targetType = job.job_type === "reindex" ? "reindex_job" : "verify_job";
  return {
    target_type: targetType,
    target_id: job.job_id,
    target_ref: `${targetType}:${job.job_id}`,
  };
}

function selectEntry(item) {
  knowledgeConsole.selectItem(item.object_type, item.lineage_key).catch((error) => {
    emit("notice", error.message);
  });
}

async function refreshKnowledge() {
  const hadSelection = Boolean(knowledgeConsole.selectedObjectType && knowledgeConsole.selectedLineageKey);
  await knowledgeConsole.load(filters);
  if (!hadSelection && !knowledgeConsole.selectedObjectType && !knowledgeConsole.selectedLineageKey && !knowledgeConsole.detail && knowledgeConsole.items.length) {
    await knowledgeConsole.selectItem(knowledgeConsole.items[0].object_type, knowledgeConsole.items[0].lineage_key);
  }
  if (knowledgeConsole.error) {
    emit("notice", knowledgeConsole.error);
  }
}

async function submitCandidate() {
  try {
    const message = await knowledgeConsole.createCandidate(draft);
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

function parseKnowledgeTarget(targetRef) {
  if (!targetRef?.startsWith("knowledge_entry:")) {
    return null;
  }
  const [, objectType, ...rest] = targetRef.split(":");
  const lineageKey = rest.join(":");
  if (!objectType || !lineageKey) {
    return null;
  }
  return { objectType, lineageKey };
}

function openReviewRef(reviewId) {
  if (!reviewId) {
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
      source_type: "knowledge_detail_review_ref",
      source_id: reviewId,
    },
  );
  emit("notice", `Opened review_item:${reviewId}`);
}

function openBundleWorkbench(bundleRef) {
  if (!bundleRef?.scene_id) {
    return;
  }
  openTarget(
    {
      target_type: "scene_card",
      target_id: bundleRef.scene_id,
      target_ref: `scene_card:${bundleRef.scene_id}`,
    },
    {
      view_id: "workbench",
      source_type: "knowledge_bundle_ref",
      source_id: bundleRef.bundle_id,
    },
  );
  emit("notice", `Opened scene_card:${bundleRef.scene_id}`);
}

function openJobTarget(job) {
  const target = jobTarget(job);
  if (!target) {
    return;
  }
  openTarget(target, {
    source_type: "knowledge_workflow_job",
    source_id: job.job_id,
  });
  emit("notice", `Opened ${target.target_ref}`);
}

function openHumanReviewEvent(event) {
  if (!event?.event_id) {
    return;
  }
  openTarget(
    {
      target_type: "human_review_event",
      target_id: event.event_id,
      target_ref: `human_review_event:${event.event_id}`,
    },
    {
      view_id: "review",
      source_type: "knowledge_workflow_event",
      source_id: event.event_id,
    },
  );
  emit("notice", `Opened human_review_event:${event.event_id}`);
}

function openActivityTarget(group) {
  if (!group?.target) {
    return;
  }
  openTarget(group.target, {
    source_type: "knowledge_target_activity",
    source_id: group.target.target_ref,
  });
  emit("notice", `Opened ${group.target.target_ref}`);
}

async function runApprove(reviewId) {
  try {
    emit("notice", await knowledgeConsole.approveReview(reviewId));
  } catch (error) {
    emit("notice", error.message);
  }
}

async function runRetryVerify(jobId) {
  try {
    emit("notice", await knowledgeConsole.retryVerifyJob(jobId));
  } catch (error) {
    emit("notice", error.message);
  }
}

async function runRelease(reviewId) {
  try {
    emit("notice", await knowledgeConsole.releaseReview(reviewId));
  } catch (error) {
    emit("notice", error.message);
  }
}

async function runHumanReviewAction(eventId, action) {
  try {
    emit("notice", await knowledgeConsole.actOnHumanReviewEvent(eventId, action));
  } catch (error) {
    emit("notice", error.message);
  }
}

async function runPrimaryWorkflowAction() {
  const action = primaryWorkflowAction.value;
  if (!action) {
    return;
  }
  if (action.kind === "review" && action.action === "approve_review") {
    await runApprove(action.review_id);
    return;
  }
  if (action.kind === "review" && action.action === "release_review") {
    await runRelease(action.review_id);
    return;
  }
  if (action.kind === "verify_job" && action.action === "retry_verify") {
    await runRetryVerify(action.job_id);
    return;
  }
  if (action.kind === "human_review_event") {
    await runHumanReviewAction(action.event_id, action.action);
  }
}

onMounted(() => {
  refreshKnowledge();
});

watch(
  () => focusTarget.value?.target_ref || "",
  async (targetRef) => {
    const target = parseKnowledgeTarget(targetRef);
    if (!target) {
      return;
    }
    if (!knowledgeConsole.items.length) {
      await refreshKnowledge();
    }
    try {
      await knowledgeConsole.selectItem(target.objectType, target.lineageKey);
    } catch (error) {
      emit("notice", error.message);
    }
  },
);
</script>

<template>
  <section class="panel-grid" data-testid="knowledge-console-view">
    <PanelShell
      eyebrow="Knowledge Console"
      title="Stage new candidates and inspect active knowledge"
      description="Track active rows, pending review candidates, version history, and runtime references for each knowledge family."
    >
      <template #actions>
        <div class="knowledge-filter-grid">
          <label>
            <span>Object Type</span>
            <select v-model="filters.objectType" class="control-input" data-testid="knowledge-filter-select">
              <option value="">All families</option>
              <option v-for="objectType in knowledgeConsole.supportedObjectTypes" :key="objectType" :value="objectType">
                {{ objectType }}
              </option>
            </select>
          </label>
          <label>
            <span>Scope</span>
            <input v-model="filters.scope" class="control-input" data-testid="knowledge-scope-filter" placeholder="global" />
          </label>
          <label>
            <span>Scope Ref</span>
            <input
              v-model="filters.scopeRefId"
              class="control-input"
              data-testid="knowledge-scope-ref-filter"
              placeholder="global / chapter / scene"
            />
          </label>
          <label>
            <span>Status</span>
            <select v-model="filters.status" class="control-input" data-testid="knowledge-status-filter">
              <option value="">All statuses</option>
              <option value="active">active</option>
              <option value="candidate">candidate</option>
              <option value="resolved">resolved</option>
            </select>
          </label>
          <button data-testid="knowledge-refresh-button" @click="refreshKnowledge">Refresh</button>
        </div>
      </template>

      <div class="knowledge-layout">
        <article class="paper knowledge-form-card">
          <div class="receipt-head">
            <div>
              <h3>New Candidate</h3>
              <p class="muted receipt-copy">Create a review candidate here, then finish approval, verify, release, and follow-up from the detail drawer.</p>
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
                <button
                  class="ghost"
                  :data-testid="`knowledge-view-detail-${item.object_type}-${item.lineage_key}`"
                  @click="selectEntry(item)"
                >
                  View Detail
                </button>
                <button class="ghost" @click="openReviewInbox(item)">View Review Inbox</button>
                <button class="ghost" @click="openIndexConsole(item)">Open Index Console</button>
              </div>
            </article>
          </div>
        </article>

        <article class="paper knowledge-detail-card" data-testid="knowledge-detail-drawer">
          <div class="receipt-head">
            <div>
              <h3>Detail Drawer</h3>
              <p class="muted receipt-copy">Inspect active and candidate state, then drive review, verify, release, and follow-up without leaving Knowledge Console.</p>
            </div>
            <span v-if="knowledgeConsole.detail" class="badge">{{ knowledgeConsole.detail.object_type }}</span>
          </div>

          <div v-if="!knowledgeConsole.detail" class="empty" data-testid="knowledge-detail-empty">
            Select a lineage to inspect version history and runtime refs.
          </div>
          <template v-else>
            <p data-testid="knowledge-detail-lineage"><strong>Lineage</strong><br />{{ knowledgeConsole.detail.lineage_key }}</p>
            <p><strong>Active Version</strong><br />{{ previewText(knowledgeConsole.detail.active_version) }}</p>
            <p><strong>Candidate Version</strong><br />{{ previewText(knowledgeConsole.detail.candidate_version) }}</p>
            <div class="history-stack">
              <p class="history-title">Workflow Status</p>
              <div class="card-actions">
                <span v-for="item in workflowStatusItems" :key="item.label" class="badge">{{ item.label }}: {{ item.value }}</span>
              </div>
            </div>
            <div class="history-stack">
              <p class="history-title">Workflow Actions</p>
              <div class="card-actions">
                <button
                  v-if="primaryWorkflowAction"
                  class="ghost"
                  data-testid="knowledge-workflow-primary-action"
                  :disabled="Boolean(knowledgeConsole.actionId)"
                  @click="runPrimaryWorkflowAction"
                >
                  {{ primaryWorkflowAction.label }}
                </button>
                <button
                  v-for="review in workflowReviewItems.filter((item) => item.status === 'pending')"
                  :key="`approve-${review.review_id}`"
                  class="ghost"
                  :data-testid="`knowledge-approve-review-${review.review_id}`"
                  :disabled="Boolean(knowledgeConsole.actionId)"
                  @click="runApprove(review.review_id)"
                >
                  Approve
                </button>
                <button
                  v-for="job in workflowJobs.filter((item) => item.job_type === 'verify' && item.status !== 'succeeded')"
                  :key="`verify-${job.job_id}`"
                  class="ghost"
                  :data-testid="`knowledge-retry-verify-${job.job_id}`"
                  :disabled="Boolean(knowledgeConsole.actionId)"
                  @click="runRetryVerify(job.job_id)"
                >
                  Retry Verify
                </button>
                <button
                  v-for="review in workflowReviewItems.filter((item) => item.status === 'approved' && item.materialize_status === 'succeeded' && canReleaseReview(item))"
                  :key="`release-${review.review_id}`"
                  class="ghost"
                  :data-testid="`knowledge-release-review-${review.review_id}`"
                  :disabled="Boolean(knowledgeConsole.actionId)"
                  @click="runRelease(review.review_id)"
                >
                  Release
                </button>
              </div>
            </div>
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
            <div class="history-stack">
              <p class="history-title">Related Reviews</p>
              <ol v-if="workflowReviewItems.length" class="history-list">
                <li v-for="review in workflowReviewItems" :key="review.review_id" class="history-entry">
                  <p class="history-meta">
                    <strong>{{ review.review_id }}</strong>
                    <span>{{ review.status }}</span>
                  </p>
                  <p class="muted">{{ review.materialize_status || "pending" }}</p>
                  <div class="card-actions">
                    <button
                      class="ghost"
                      :data-testid="`knowledge-open-related-review-${review.review_id}`"
                      @click="openReviewRef(review.review_id)"
                    >
                      Open Review Inbox
                    </button>
                  </div>
                </li>
              </ol>
              <p v-else class="muted">No related reviews yet.</p>
            </div>
            <div class="history-stack">
              <p class="history-title">Related Jobs</p>
              <ol v-if="workflowJobs.length" class="history-list">
                <li v-for="job in workflowJobs" :key="job.job_id" class="history-entry">
                  <p class="history-meta">
                    <strong>{{ job.job_id }}</strong>
                    <span>{{ job.status }}</span>
                  </p>
                  <p class="muted">{{ job.job_type }} / {{ job.alias_scope || "direct" }}</p>
                  <div class="card-actions">
                    <button class="ghost" @click="openJobTarget(job)">
                      Open Index Console
                    </button>
                  </div>
                </li>
              </ol>
              <p v-else class="muted">No related jobs yet.</p>
            </div>
            <div class="history-stack">
              <p class="history-title">Related Human Review</p>
              <ol v-if="workflowHumanReviewEvents.length" class="history-list">
                <li v-for="event in workflowHumanReviewEvents" :key="event.event_id" class="history-entry">
                  <p class="history-meta">
                    <strong>{{ event.event_id }}</strong>
                    <span>{{ event.status }}</span>
                  </p>
                  <p class="muted">{{ event.default_action || "inspect" }}</p>
                  <div class="card-actions">
                    <button class="ghost" @click="openHumanReviewEvent(event)">
                      Open Review Inbox
                    </button>
                    <button
                      v-for="action in event.allowed_actions_json || []"
                      :key="`${event.event_id}-${action}`"
                      class="ghost"
                      :data-testid="`knowledge-human-review-action-${event.event_id}-${action}`"
                      :disabled="Boolean(knowledgeConsole.actionId)"
                      @click="runHumanReviewAction(event.event_id, action)"
                    >
                      {{ actionLabel(action) }}
                    </button>
                  </div>
                </li>
              </ol>
              <p v-else class="muted">No related human review follow-up items.</p>
            </div>
            <div class="history-stack">
              <p class="history-title">Target Activity</p>
              <ol v-if="workflowTargetActivityGroups.length" class="history-list">
                <li v-for="group in workflowTargetActivityGroups" :key="group.target.target_ref" class="history-entry">
                  <p class="history-meta">
                    <strong>{{ group.target.target_ref }}</strong>
                    <span>{{ group.activity_count }} activities</span>
                  </p>
                  <p class="muted">{{ (group.sources || []).join(", ") || "activity" }}</p>
                  <div class="card-actions">
                    <button class="ghost" @click="openActivityTarget(group)">
                      Open Target
                    </button>
                  </div>
                </li>
              </ol>
              <p v-else class="muted">No related target activity yet.</p>
            </div>
            <div class="history-stack">
              <p class="history-title">Review refs</p>
              <ol v-if="detailReviewRefs.length" class="history-list">
                <li v-for="reviewRef in detailReviewRefs" :key="reviewRef" class="history-entry">
                  <p class="history-meta">
                    <strong>{{ reviewRef }}</strong>
                    <span>review_item</span>
                  </p>
                  <div class="card-actions">
                    <button
                      class="ghost"
                      :data-testid="`knowledge-open-review-ref-${reviewRef}`"
                      @click="openReviewRef(reviewRef)"
                    >
                      Open Review Inbox
                    </button>
                  </div>
                </li>
              </ol>
              <p v-else class="muted">No linked review refs yet.</p>
            </div>
            <div class="history-stack">
              <p class="history-title">Bundle refs</p>
              <ol v-if="detailBundleRefs.length" class="history-list">
                <li v-for="bundleRef in detailBundleRefs" :key="bundleRef.bundle_id" class="history-entry">
                  <p class="history-meta">
                    <strong>{{ bundleRef.bundle_id }}</strong>
                    <span>{{ bundleRef.scene_id }}</span>
                  </p>
                  <p class="muted">Chapter {{ bundleRef.chapter_id || "-" }}</p>
                  <div class="card-actions">
                    <button
                      class="ghost"
                      :data-testid="`knowledge-open-bundle-ref-${bundleRef.bundle_id}`"
                      @click="openBundleWorkbench(bundleRef)"
                    >
                      Open Scene Workbench
                    </button>
                  </div>
                </li>
              </ol>
              <p v-else class="muted">No bundle refs yet.</p>
            </div>
          </template>
        </article>
      </div>
    </PanelShell>
  </section>
</template>
