<script setup>
import { computed, onActivated, onDeactivated, reactive, ref, watch } from "vue";

import LazySection from "../components/LazySection.vue";
import ProgressiveList from "../components/ProgressiveList.vue";
import PanelShell from "../components/PanelShell.vue";
import VirtualList from "../components/VirtualList.vue";
import { prioritizeMatchingItem } from "../lib/listPriority";
import { useShellRouter } from "../router";
import { useKnowledgeConsoleStore } from "../stores/knowledgeConsole";

const emit = defineEmits(["notice"]);

const knowledgeConsole = useKnowledgeConsoleStore();
const { focusTarget, navigate, openTarget } = useShellRouter();
const isViewActive = ref(false);

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

const pinnedCatalogKeys = computed(() => (selectedEntryKey.value ? [selectedEntryKey.value] : []));
const catalogItems = computed(() => knowledgeConsole.items || []);
const prioritizedCatalogItems = computed(() =>
  prioritizeMatchingItem(catalogItems.value, (item) => knowledgeItemKey(item) === selectedEntryKey.value),
);
const detailReviewRefs = computed(() => knowledgeConsole.detail?.review_refs || []);
const detailBundleRefs = computed(() => knowledgeConsole.detail?.bundle_refs || []);
const detailWorkflow = computed(() => knowledgeConsole.detail?.workflow || {});
const workflowReviewItems = computed(() => detailWorkflow.value.review_items || []);
const workflowJobs = computed(() => detailWorkflow.value.jobs || []);
const workflowHumanReviewEvents = computed(() => detailWorkflow.value.human_review_events || []);
const workflowTargetActivityGroups = computed(() => detailWorkflow.value.target_activity_groups || []);
const primaryWorkflowAction = computed(() => detailWorkflow.value.recommended_primary_action || null);
const workflowActionItems = computed(() => {
  const pendingReviews = [];
  const retryableJobs = [];
  const releasableReviews = [];
  const blockedReleaseReviewIds = new Set();
  const activeVersionRowId = knowledgeConsole.detail?.active_version?.row_id || "";

  workflowJobs.value.forEach((job) => {
    if (job.job_type !== "verify" || job.status === "succeeded") {
      return;
    }
    retryableJobs.push(job);
    if (job.review_id) {
      blockedReleaseReviewIds.add(job.review_id);
    }
  });

  workflowReviewItems.value.forEach((review) => {
    if (review.status === "pending") {
      pendingReviews.push(review);
      return;
    }
    if (
      review.status === "approved"
      && review.materialize_status === "succeeded"
      && review.approved_item_row_id
      && activeVersionRowId !== review.approved_item_row_id
      && !blockedReleaseReviewIds.has(review.review_id)
    ) {
      releasableReviews.push(review);
    }
  });

  return {
    pendingReviews,
    retryableJobs,
    releasableReviews,
  };
});
const ITEM_TYPE_LABELS = {
  style_rule: "风格规则",
  style_observation: "风格观察",
  banned_rule_cluster: "禁忌规则簇",
  voice_card: "声线卡",
  relation_card: "关系卡",
  world_rule: "世界规则",
  calibration_line: "校准句",
  foreshadow: "伏笔",
  scene_summary: "场景摘要",
  chapter_summary: "章节摘要",
};

const STATUS_LABELS = {
  active: "生效中",
  candidate: "候选中",
  resolved: "已解决",
  pending: "待处理",
  approved: "已批准",
  rejected: "已拒绝",
  clear: "正常",
  not_required: "无需校验",
  unknown: "未知",
  succeeded: "成功",
  failed: "失败",
  running: "进行中",
  tracked: "已跟踪",
  released: "已发布",
};

const JOB_TYPE_LABELS = {
  verify: "校验任务",
  reindex: "重建索引任务",
};

const ACTION_LABELS = {
  approve_review: "批准审核",
  retry_verify: "重试校验",
  release_review: "发布审核",
  retry_request: "重试请求",
  inspect: "查看详情",
};

function formatItemType(itemType) {
  return ITEM_TYPE_LABELS[itemType] || itemType || "-";
}

function formatStatus(status) {
  return STATUS_LABELS[status] || status || "-";
}

function formatJobType(jobType) {
  return JOB_TYPE_LABELS[jobType] || jobType || "-";
}

function formatAction(action) {
  return ACTION_LABELS[action] || action || "-";
}

function knowledgeItemKey(item) {
  return `${item.object_type}:${item.lineage_key}`;
}

const workflowStatusItems = computed(() => {
  const reviewStatus = workflowReviewItems.value[0]?.status || "clear";
  const verifyJob = workflowJobs.value.find((job) => job.job_type === "verify");
  const verifyStatus = verifyJob?.status || knowledgeConsole.detail?.runtime_refs?.verify_status || "not_required";
  const unresolvedHumanReview = workflowHumanReviewEvents.value.find((item) => item.status !== "resolved");
  return [
    { label: "知识", value: formatStatus(knowledgeConsole.detail?.status || "unknown") },
    { label: "审核", value: formatStatus(reviewStatus) },
    { label: "校验", value: formatStatus(verifyStatus) },
    {
      label: "人工审核",
      value: formatStatus(
        unresolvedHumanReview?.status || (workflowHumanReviewEvents.value.length ? "resolved" : "clear"),
      ),
    },
  ];
});

function previewText(version) {
  if (!version?.text) {
    return "暂无文本";
  }
  return version.text;
}

function previewSummaryText(version) {
  const text = previewText(version);
  if (text === "暂无文本" || text.length <= 120) {
    return text;
  }
  return `${text.slice(0, 120)}...`;
}

function actionLabel(action) {
  return formatAction(action);
}

function formatJsonPayload(value) {
  return JSON.stringify(value ?? {}, null, 2);
}

function formatSources(sources, fallback = "活动") {
  return sources?.length ? sources.join(", ") : fallback;
}

function knowledgeVersionRow(version) {
  return {
    version,
    rowId: version.row_id,
    versionLabel: `v${version.version || "候选"}`,
    text: version.text || "-",
  };
}

function knowledgeWorkflowReviewRow(review) {
  return {
    review,
    reviewId: review.review_id,
    statusLabel: formatStatus(review.status),
    materializeStatusLabel: formatStatus(review.materialize_status || "pending"),
  };
}

function knowledgeWorkflowJobRow(job) {
  return {
    job,
    jobId: job.job_id,
    statusLabel: formatStatus(job.status),
    summary: `${formatJobType(job.job_type)} / ${job.alias_scope || "直接读取"}`,
  };
}

function knowledgeHumanReviewRow(event) {
  const eventId = event.event_id;
  return {
    event,
    eventId,
    statusLabel: formatStatus(event.status),
    defaultActionLabel: formatAction(event.default_action || "inspect"),
    actions: (event.allowed_actions_json || []).map((action) => ({
      action,
      key: `${eventId}-${action}`,
      label: actionLabel(action),
    })),
  };
}

function knowledgeActivityRow(group) {
  const targetRef = group.target?.target_ref || "";
  return {
    group,
    targetRef,
    activityCount: group.activity_count ?? 0,
    sourcesLabel: formatSources(group.sources),
  };
}

function knowledgeReviewRefRow(reviewRef) {
  return {
    reviewRef,
    targetType: "review_item",
  };
}

function knowledgeBundleRefRow(bundleRef) {
  return {
    bundleRef,
    bundleId: bundleRef.bundle_id,
    sceneId: bundleRef.scene_id,
    chapterId: bundleRef.chapter_id || "-",
  };
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
  await knowledgeConsole.load(filters, { force: true });
  if (!hadSelection && !knowledgeConsole.selectedObjectType && !knowledgeConsole.selectedLineageKey && !knowledgeConsole.detail && knowledgeConsole.items.length) {
    await knowledgeConsole.selectItem(knowledgeConsole.items[0].object_type, knowledgeConsole.items[0].lineage_key);
  }
  if (knowledgeConsole.error) {
    emit("notice", knowledgeConsole.error);
  }
}

async function ensureKnowledgeLoaded() {
  const hadSelection = Boolean(knowledgeConsole.selectedObjectType && knowledgeConsole.selectedLineageKey);
  await knowledgeConsole.ensureLoaded({ filters });
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
    emit("notice", "已打开审核收件箱");
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
  emit("notice", `已打开审核收件箱：review_item:${reviewId}`);
}

function openIndexConsole(item) {
  navigate("index");
  emit("notice", `已打开索引控制台：${item.object_type}:${item.lineage_key}`);
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
  emit("notice", `已打开审核收件箱：review_item:${reviewId}`);
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
  emit("notice", `已打开场景工作台：scene_card:${bundleRef.scene_id}`);
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
  emit("notice", `已打开索引任务：${target.target_ref}`);
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
  emit("notice", `已打开人工审核事件：human_review_event:${event.event_id}`);
}

function openActivityTarget(group) {
  if (!group?.target) {
    return;
  }
  openTarget(group.target, {
    source_type: "knowledge_target_activity",
    source_id: group.target.target_ref,
  });
  emit("notice", `已打开目标：${group.target.target_ref}`);
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

async function syncKnowledgeFocus(targetRef = focusTarget.value?.target_ref || "") {
  if (!isViewActive.value) {
    return;
  }
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
}

onActivated(async () => {
  isViewActive.value = true;
  await ensureKnowledgeLoaded();
  await syncKnowledgeFocus();
});

onDeactivated(() => {
  isViewActive.value = false;
});

watch(
  () => focusTarget.value?.target_ref || "",
  async (targetRef) => {
    await syncKnowledgeFocus(targetRef);
  },
);
</script>

<template>
  <section class="panel-grid" data-testid="knowledge-console-view">
    <PanelShell
      eyebrow="知识控制台"
      title="新建候选并查看生效知识"
      description="按知识家族查看生效行、待审核候选、版本历史和运行时引用。"
    >
      <template #actions>
        <div class="knowledge-filter-grid">
          <label>
            <span>对象类型</span>
            <select v-model="filters.objectType" class="control-input" data-testid="knowledge-filter-select">
              <option value="">全部家族</option>
              <option v-for="objectType in knowledgeConsole.supportedObjectTypes" :key="objectType" :value="objectType">
                {{ formatItemType(objectType) }}
              </option>
            </select>
          </label>
          <label>
            <span>作用域</span>
            <input v-model="filters.scope" class="control-input" data-testid="knowledge-scope-filter" placeholder="global" />
          </label>
          <label>
            <span>作用域引用</span>
            <input
              v-model="filters.scopeRefId"
              class="control-input"
              data-testid="knowledge-scope-ref-filter"
              placeholder="global / chapter / scene"
            />
          </label>
          <label>
            <span>状态</span>
            <select v-model="filters.status" class="control-input" data-testid="knowledge-status-filter">
              <option value="">全部状态</option>
              <option value="active">生效中</option>
              <option value="candidate">候选中</option>
              <option value="resolved">已解决</option>
            </select>
          </label>
          <button data-testid="knowledge-refresh-button" @click="refreshKnowledge">刷新</button>
        </div>
      </template>

      <div class="knowledge-layout">
        <article class="paper knowledge-form-card">
          <div class="receipt-head">
            <div>
              <h3>新建候选</h3>
              <p class="muted receipt-copy">先在这里创建审核候选，再在右侧详情抽屉里完成批准、校验、发布和后续处理。</p>
            </div>
            <span class="badge">创建接口</span>
          </div>
          <div class="knowledge-form-grid">
            <label>
              <span>审核 ID</span>
              <input v-model="draft.reviewId" class="control-input" data-testid="knowledge-review-id" />
            </label>
            <label>
              <span>条目类型</span>
              <select v-model="draft.itemType" class="control-input" data-testid="knowledge-item-type">
                <option value="style_rule_set">风格规则集</option>
                <option value="banned_rule_cluster">禁忌规则簇</option>
                <option value="voice_card_candidate">声线卡候选</option>
                <option value="relation_card_candidate">关系卡候选</option>
                <option value="world_rule">世界规则</option>
                <option value="calibration_candidate">校准句候选</option>
                <option value="foreshadow_open">伏笔开启</option>
                <option value="foreshadow_touch">伏笔触发</option>
                <option value="foreshadow_resolve">伏笔回收</option>
                <option value="scene_summary">场景摘要</option>
                <option value="chapter_summary">章节摘要</option>
                <option value="style_observation">风格观察</option>
              </select>
            </label>
            <label>
              <span>血缘键</span>
              <input v-model="draft.lineageKey" class="control-input" data-testid="knowledge-lineage-key" />
            </label>
            <label>
              <span>批准后生效</span>
              <select v-model.number="draft.activeOnApprove" class="control-input" data-testid="knowledge-active-on-approve">
                <option :value="1">是</option>
                <option :value="0">否</option>
              </select>
            </label>
            <label>
              <span>作用域</span>
              <input v-model="draft.scope" class="control-input" />
            </label>
            <label>
              <span>作用域引用</span>
              <input v-model="draft.scopeRefId" class="control-input" />
            </label>
            <label>
              <span>章节 ID</span>
              <input v-model="draft.chapterId" class="control-input" />
            </label>
            <label>
              <span>场景 ID</span>
              <input v-model="draft.sceneId" class="control-input" />
            </label>
            <label>
              <span>角色 ID</span>
              <input v-model="draft.characterId" class="control-input" />
            </label>
            <label>
              <span>左角色</span>
              <input v-model="draft.leftCharacterId" class="control-input" />
            </label>
            <label>
              <span>右角色</span>
              <input v-model="draft.rightCharacterId" class="control-input" />
            </label>
            <label>
              <span>规则层级</span>
              <input v-model="draft.ruleTier" class="control-input" />
            </label>
            <label class="knowledge-wide">
              <span>候选文本</span>
              <textarea v-model="draft.candidateText" class="control-input control-textarea" data-testid="knowledge-candidate-text" />
            </label>
            <label class="knowledge-wide">
              <span>附加载荷 JSON</span>
              <textarea v-model="draft.extraPayload" class="control-input control-textarea" placeholder='{"expires_at":"2099-01-01T00:00:00+00:00"}' />
            </label>
          </div>
          <div class="card-actions">
            <button :disabled="knowledgeConsole.actionId === 'create'" data-testid="knowledge-create-button" @click="submitCandidate">
              {{ knowledgeConsole.actionId === "create" ? "创建中..." : "创建候选" }}
            </button>
          </div>
        </article>

        <article class="paper knowledge-catalog-card">
          <div class="receipt-head">
            <div>
              <h3>目录</h3>
              <p class="muted receipt-copy">把生效行和暂存候选合并成一份按血缘优先排序的视图。</p>
            </div>
            <span class="badge">{{ catalogItems.length }} 条血缘</span>
          </div>

          <div v-if="knowledgeConsole.loading" class="empty">正在加载知识目录...</div>
          <div v-else-if="knowledgeConsole.error" class="empty">{{ knowledgeConsole.error }}</div>
          <div v-else-if="!catalogItems.length" class="empty">当前筛选下没有匹配的知识行或候选项。</div>
          <VirtualList
            v-else
            class="knowledge-list"
            :items="prioritizedCatalogItems"
            :item-key="knowledgeItemKey"
            :estimated-item-height="220"
            :threshold="8"
            :viewport-height="640"
            :pinned-keys="pinnedCatalogKeys"
            test-id="knowledge-catalog-virtual-list"
          >
            <template #default="{ item }">
              <article
                class="review-card knowledge-card"
                :class="{ 'focused-card': selectedEntryKey === knowledgeItemKey(item) }"
                :data-testid="`knowledge-card-${item.object_type}-${item.lineage_key}`"
              >
                <div class="source-top">
                  <div>
                    <div class="eyebrow">{{ formatItemType(item.object_type) }}</div>
                    <h3>{{ item.lineage_key }}</h3>
                  </div>
                  <span class="badge">{{ formatStatus(item.status || "tracked") }}</span>
                </div>
                <p><strong>生效文本</strong><br />{{ previewSummaryText(item.active_version) }}</p>
                <p><strong>候选文本</strong><br />{{ previewSummaryText(item.candidate_version) }}</p>
                <p class="muted">运行时引用：{{ item.runtime_refs?.alias_scope || item.runtime_refs?.mode || "-" }}</p>
                <div class="card-actions">
                  <button
                    class="ghost"
                    :data-testid="`knowledge-view-detail-${item.object_type}-${item.lineage_key}`"
                    @click="selectEntry(item)"
                  >
                    查看详情
                  </button>
                  <button class="ghost" @click="openReviewInbox(item)">查看审核收件箱</button>
                  <button class="ghost" @click="openIndexConsole(item)">打开索引控制台</button>
                </div>
              </article>
            </template>
          </VirtualList>
        </article>

        <article class="paper knowledge-detail-card" data-testid="knowledge-detail-drawer">
          <div class="receipt-head">
            <div>
              <h3>详情抽屉</h3>
              <p class="muted receipt-copy">在不离开知识控制台的前提下查看生效态、候选态，并继续做审核、校验、发布和后续处理。</p>
            </div>
            <span v-if="knowledgeConsole.detail" class="badge">{{ formatItemType(knowledgeConsole.detail.object_type) }}</span>
          </div>

          <div v-if="!knowledgeConsole.detail" class="empty" data-testid="knowledge-detail-empty">
            先选择一条血缘，再查看版本历史和运行时引用。
          </div>
          <template v-else>
            <p data-testid="knowledge-detail-lineage"><strong>血缘</strong><br />{{ knowledgeConsole.detail.lineage_key }}</p>
            <p><strong>生效版本</strong><br />{{ previewText(knowledgeConsole.detail.active_version) }}</p>
            <p><strong>候选版本</strong><br />{{ previewText(knowledgeConsole.detail.candidate_version) }}</p>
            <div class="history-stack">
              <p class="history-title">流程状态</p>
              <div class="card-actions">
                <span v-for="item in workflowStatusItems" :key="item.label" class="badge">{{ item.label }}: {{ item.value }}</span>
              </div>
            </div>
            <div class="history-stack">
              <p class="history-title">流程动作</p>
              <div class="card-actions">
                <button
                  v-if="primaryWorkflowAction"
                  class="ghost"
                  data-testid="knowledge-workflow-primary-action"
                  :disabled="Boolean(knowledgeConsole.actionId)"
                  @click="runPrimaryWorkflowAction"
                >
                  {{ actionLabel(primaryWorkflowAction.action) }}
                </button>
                <button
                  v-for="review in workflowActionItems.pendingReviews"
                  :key="`approve-${review.review_id}`"
                  class="ghost"
                  :data-testid="`knowledge-approve-review-${review.review_id}`"
                  :disabled="Boolean(knowledgeConsole.actionId)"
                  @click="runApprove(review.review_id)"
                >
                  批准审核
                </button>
                <button
                  v-for="job in workflowActionItems.retryableJobs"
                  :key="`verify-${job.job_id}`"
                  class="ghost"
                  :data-testid="`knowledge-retry-verify-${job.job_id}`"
                  :disabled="Boolean(knowledgeConsole.actionId)"
                  @click="runRetryVerify(job.job_id)"
                >
                  重试校验
                </button>
                <button
                  v-for="review in workflowActionItems.releasableReviews"
                  :key="`release-${review.review_id}`"
                  class="ghost"
                  :data-testid="`knowledge-release-review-${review.review_id}`"
                  :disabled="Boolean(knowledgeConsole.actionId)"
                  @click="runRelease(review.review_id)"
                >
                  发布审核
                </button>
              </div>
            </div>
            <LazySection
              :key="`runtime-${selectedEntryKey}`"
              title="运行时引用"
              toggle-test-id="knowledge-toggle-runtime-refs"
            >
              <pre class="json-block" data-testid="knowledge-runtime-refs-json">{{
                formatJsonPayload(knowledgeConsole.detail.runtime_refs)
              }}</pre>
            </LazySection>
            <LazySection :key="`versions-${selectedEntryKey}`" title="版本历史" toggle-test-id="knowledge-toggle-versions">
              <ProgressiveList
                :items="knowledgeConsole.detail.versions || []"
                :initial-count="6"
                :batch-size="6"
                :threshold="8"
                :map-item="knowledgeVersionRow"
                test-id="knowledge-versions-progressive-list"
              >
                <template #default="{ items }">
                  <ol class="history-list">
                    <li v-for="row in items" :key="row.rowId" class="history-entry" :data-testid="`knowledge-version-row-${row.rowId}`">
                      <p class="history-meta">
                        <strong>{{ row.rowId }}</strong>
                        <span>{{ row.versionLabel }}</span>
                      </p>
                      <p>{{ row.text }}</p>
                    </li>
                  </ol>
                </template>
              </ProgressiveList>
            </LazySection>
            <LazySection :key="`reviews-${selectedEntryKey}`" title="关联审核" toggle-test-id="knowledge-toggle-reviews">
              <ProgressiveList
                :items="workflowReviewItems"
                :initial-count="6"
                :batch-size="6"
                :threshold="8"
                :map-item="knowledgeWorkflowReviewRow"
                test-id="knowledge-reviews-progressive-list"
              >
                <template #default="{ items }">
                  <ol v-if="items.length" class="history-list">
                    <li v-for="row in items" :key="row.reviewId" class="history-entry" :data-testid="`knowledge-review-row-${row.reviewId}`">
                      <p class="history-meta">
                        <strong>{{ row.reviewId }}</strong>
                        <span>{{ row.statusLabel }}</span>
                      </p>
                      <p class="muted">{{ row.materializeStatusLabel }}</p>
                      <div class="card-actions">
                        <button
                          class="ghost"
                          :data-testid="`knowledge-open-related-review-${row.reviewId}`"
                          @click="openReviewRef(row.reviewId)"
                        >
                          打开审核收件箱
                        </button>
                      </div>
                    </li>
                  </ol>
                  <p v-else class="muted">还没有关联审核。</p>
                </template>
              </ProgressiveList>
            </LazySection>
            <LazySection :key="`jobs-${selectedEntryKey}`" title="关联任务" toggle-test-id="knowledge-toggle-jobs">
              <ProgressiveList
                :items="workflowJobs"
                :initial-count="6"
                :batch-size="6"
                :threshold="8"
                :map-item="knowledgeWorkflowJobRow"
                test-id="knowledge-jobs-progressive-list"
              >
                <template #default="{ items }">
                  <ol v-if="items.length" class="history-list">
                    <li v-for="row in items" :key="row.jobId" class="history-entry" :data-testid="`knowledge-job-row-${row.jobId}`">
                      <p class="history-meta">
                        <strong>{{ row.jobId }}</strong>
                        <span>{{ row.statusLabel }}</span>
                      </p>
                      <p class="muted">{{ row.summary }}</p>
                      <div class="card-actions">
                        <button class="ghost" @click="openJobTarget(row.job)">
                          打开索引控制台
                        </button>
                      </div>
                    </li>
                  </ol>
                  <p v-else class="muted">还没有关联任务。</p>
                </template>
              </ProgressiveList>
            </LazySection>
            <LazySection :key="`human-review-${selectedEntryKey}`" title="关联人工审核" toggle-test-id="knowledge-toggle-human-review">
              <ProgressiveList
                :items="workflowHumanReviewEvents"
                :initial-count="6"
                :batch-size="6"
                :threshold="8"
                :map-item="knowledgeHumanReviewRow"
                test-id="knowledge-human-review-progressive-list"
              >
                <template #default="{ items }">
                  <ol v-if="items.length" class="history-list">
                    <li v-for="row in items" :key="row.eventId" class="history-entry" :data-testid="`knowledge-human-review-row-${row.eventId}`">
                      <p class="history-meta">
                        <strong>{{ row.eventId }}</strong>
                        <span>{{ row.statusLabel }}</span>
                      </p>
                      <p class="muted">{{ row.defaultActionLabel }}</p>
                      <div class="card-actions">
                        <button class="ghost" @click="openHumanReviewEvent(row.event)">
                          打开审核收件箱
                        </button>
                        <button
                          v-for="action in row.actions"
                          :key="action.key"
                          class="ghost"
                          :data-testid="`knowledge-human-review-action-${row.eventId}-${action.action}`"
                          :disabled="Boolean(knowledgeConsole.actionId)"
                          @click="runHumanReviewAction(row.eventId, action.action)"
                        >
                          {{ action.label }}
                        </button>
                      </div>
                    </li>
                  </ol>
                  <p v-else class="muted">还没有关联的人工审核后续项。</p>
                </template>
              </ProgressiveList>
            </LazySection>
            <LazySection :key="`activity-${selectedEntryKey}`" title="目标活动" toggle-test-id="knowledge-toggle-activity">
              <ProgressiveList
                :items="workflowTargetActivityGroups"
                :initial-count="6"
                :batch-size="6"
                :threshold="8"
                :map-item="knowledgeActivityRow"
                test-id="knowledge-activity-progressive-list"
              >
                <template #default="{ items }">
                  <ol v-if="items.length" class="history-list">
                    <li v-for="row in items" :key="row.targetRef" class="history-entry" :data-testid="`knowledge-activity-row-${row.targetRef}`">
                      <p class="history-meta">
                        <strong>{{ row.targetRef }}</strong>
                        <span>{{ row.activityCount }} 条活动</span>
                      </p>
                      <p class="muted">{{ row.sourcesLabel }}</p>
                      <div class="card-actions">
                        <button class="ghost" @click="openActivityTarget(row.group)">
                          打开目标
                        </button>
                      </div>
                    </li>
                  </ol>
                  <p v-else class="muted">还没有关联目标活动。</p>
                </template>
              </ProgressiveList>
            </LazySection>
            <LazySection
              :key="`review-refs-${selectedEntryKey}`"
              title="审核引用"
              toggle-test-id="knowledge-toggle-review-refs"
            >
              <ProgressiveList
                :items="detailReviewRefs"
                :initial-count="6"
                :batch-size="6"
                :threshold="8"
                :map-item="knowledgeReviewRefRow"
                test-id="knowledge-review-refs-progressive-list"
              >
                <template #default="{ items }">
                  <ol v-if="items.length" class="history-list">
                    <li v-for="row in items" :key="row.reviewRef" class="history-entry" :data-testid="`knowledge-review-ref-row-${row.reviewRef}`">
                      <p class="history-meta">
                        <strong>{{ row.reviewRef }}</strong>
                        <span>{{ row.targetType }}</span>
                      </p>
                      <div class="card-actions">
                        <button
                          class="ghost"
                          :data-testid="`knowledge-open-review-ref-${row.reviewRef}`"
                          @click="openReviewRef(row.reviewRef)"
                        >
                          打开审核收件箱
                        </button>
                      </div>
                    </li>
                  </ol>
                  <p v-else class="muted">还没有关联审核引用。</p>
                </template>
              </ProgressiveList>
            </LazySection>
            <LazySection
              :key="`bundle-refs-${selectedEntryKey}`"
              title="包引用"
              toggle-test-id="knowledge-toggle-bundle-refs"
            >
              <ProgressiveList
                :items="detailBundleRefs"
                :initial-count="6"
                :batch-size="6"
                :threshold="8"
                :map-item="knowledgeBundleRefRow"
                test-id="knowledge-bundle-refs-progressive-list"
              >
                <template #default="{ items }">
                  <ol v-if="items.length" class="history-list">
                    <li v-for="row in items" :key="row.bundleId" class="history-entry" :data-testid="`knowledge-bundle-ref-row-${row.bundleId}`">
                      <p class="history-meta">
                        <strong>{{ row.bundleId }}</strong>
                        <span>{{ row.sceneId }}</span>
                      </p>
                      <p class="muted">章节 {{ row.chapterId }}</p>
                      <div class="card-actions">
                        <button
                          class="ghost"
                          :data-testid="`knowledge-open-bundle-ref-${row.bundleId}`"
                          @click="openBundleWorkbench(row.bundleRef)"
                        >
                          打开场景工作台
                        </button>
                      </div>
                    </li>
                  </ol>
                  <p v-else class="muted">还没有包引用。</p>
                </template>
              </ProgressiveList>
            </LazySection>
          </template>
        </article>
      </div>
    </PanelShell>
  </section>
</template>
