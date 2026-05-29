<script setup>
// Style Reference v1.1 — 视图(PR-5 重写)
// 删除旧 round-based UI;新结构基于 PR-1~PR-4 后端 18 端点。
// 流程:导入 → 启动 run → DimensionMatrix → FindingsByDimension 审阅 →
// synthesize → PreviewPanel → ProfileApplyDialog → ReviewInbox。

import { computed, onActivated, onMounted, ref } from "vue";

import FlowActionReceipt from "../components/FlowActionReceipt.vue";
import LazySection from "../components/LazySection.vue";
import WorkflowPageHeader from "../components/WorkflowPageHeader.vue";
import BaseBadge from "../components/base/BaseBadge.vue";
import BaseButton from "../components/base/BaseButton.vue";
import BaseEmptyState from "../components/base/BaseEmptyState.vue";

import DimensionMatrix from "../components/styleReference/DimensionMatrix.vue";
import FindingCard from "../components/styleReference/FindingCard.vue";
import PreviewPanel from "../components/styleReference/PreviewPanel.vue";
import ProfileApplyDialog from "../components/styleReference/ProfileApplyDialog.vue";

import { useFlowActionFeedback } from "../composables/useFlowActionFeedback";
import { useShellRouter } from "../router";
import { useReferenceLearningStore } from "../stores/referenceLearning";

const emit = defineEmits(["notice"]);

const store = useReferenceLearningStore();
const { navigate } = useShellRouter();

const { receipt, runFlowAction } = useFlowActionFeedback({
  emitNotice: (message) => emit("notice", message),
});

const STYLE_REF_IMPORT_SCOPE = "style_reference:import";
const STYLE_REF_RUN_SCOPE = "style_reference:run";
const STYLE_REF_SYNTHESIZE_SCOPE = "style_reference:synthesize";
const STYLE_REF_PREVIEW_SCOPE = "style_reference:preview";
const STYLE_REF_APPLY_SCOPE = "style_reference:apply";
const STYLE_REF_REVIEW_SCOPE = "style_reference:review";

const applyDialogOpen = ref(false);
const highlightedDim = ref("");
const subDimRefs = ref({});
const reviewingFindingId = ref(null);

const importMode = computed({
  get: () => store.importMode,
  set: (value) => { store.importMode = value; },
});

const stats = computed(() => store.currentBook?.stats_json ?? {});
const inputAssessment = computed(() => stats.value.input_assessment ?? {});
const paragraphTypeDist = computed(() => stats.value.paragraph_type_distribution ?? {});

const findingsBySubDim = computed(() => {
  const result = [];
  for (const [subDim, bucket] of Object.entries(store.findings)) {
    result.push({
      subDim,
      observations: bucket.observations || [],
      forbidden_patterns: bucket.forbidden_patterns || [],
    });
  }
  return result;
});

const totalFindings = computed(() => {
  let total = 0;
  for (const bucket of Object.values(store.findings)) {
    total += (bucket.observations?.length ?? 0) + (bucket.forbidden_patterns?.length ?? 0);
  }
  return total;
});

onMounted(() => {
  if (!store.loaded) {
    store.initialize().catch(() => { /* error 已经存到 store.error */ });
  }
});

onActivated(() => {
  if (store.stale) {
    store.initialize().catch(() => {});
  }
});

function setImportMode(mode) {
  store.importMode = mode;
}

function handleFileChange(event) {
  const file = event.target.files?.[0] ?? null;
  store.uploadDraft.file = file;
}

async function submitImport() {
  await runFlowAction({
    scopeKey: STYLE_REF_IMPORT_SCOPE,
    actionLabel: "导入参考书",
    runningMessage: "正在解析文件、计算硬指标、跑分段分类器...",
    successMessage: () => store.lastActionMessage || "参考书已导入。",
    action: () => importMode.value === "path" ? store.importPath() : store.importUpload(),
  });
}

async function selectBook(bookId) {
  await store.selectBook(bookId);
}

async function deleteBook(bookId) {
  if (!window.confirm("确认删除该参考书及其所有衍生数据(findings / quotes / profile / bindings)?")) {
    return;
  }
  await store.deleteBook(bookId);
}

async function startRun() {
  await runFlowAction({
    scopeKey: STYLE_REF_RUN_SCOPE,
    actionLabel: "启动抽取 run",
    runningMessage: "调度 LLM 抽 8 sub_dim findings(language + narrative)...",
    successMessage: () => store.lastActionMessage || "抽取完成。",
    nextStep: () => "下一步:在维度矩阵中点击某个 sub_dim,审阅 findings 卡片。",
    action: () => store.startRun(),
  });
}

async function reviewFinding(findingId, decision) {
  reviewingFindingId.value = findingId;
  try {
    await runFlowAction({
      scopeKey: STYLE_REF_REVIEW_SCOPE,
      actionLabel: "审阅 finding",
      runningMessage: "更新审阅状态...",
      successMessage: () => store.lastActionMessage || "已更新。",
      action: () => store.reviewFinding(findingId, decision),
    });
  } finally {
    reviewingFindingId.value = null;
  }
}

async function synthesize() {
  if (!store.currentRun?.run_id) return;
  await runFlowAction({
    scopeKey: STYLE_REF_SYNTHESIZE_SCOPE,
    actionLabel: "聚合为 Profile",
    runningMessage: "调 LLM 聚合 16 sub-profile → StyleProfile...",
    successMessage: () => store.lastActionMessage || "Profile 已生成。",
    nextStep: () => "下一步:点击「生成 3 段示例」预览风格,或直接应用到项目。",
    action: () => store.synthesizeProfile(store.currentRun.run_id),
  });
}

async function regeneratePreview() {
  if (!store.currentProfile?.profile_id) return;
  await runFlowAction({
    scopeKey: STYLE_REF_PREVIEW_SCOPE,
    actionLabel: "生成 3 段示例",
    runningMessage: "LLM 在 dialogue / description_env / psychology 各生成 1 段并验证...",
    successMessage: () => store.lastActionMessage || "示例已生成。",
    action: () => store.previewProfile(store.currentProfile.profile_id),
  });
}

async function applyProfile(draft) {
  if (!store.currentProfile?.profile_id) return;
  store.applyDraft = { ...draft };
  applyDialogOpen.value = false;
  await runFlowAction({
    scopeKey: STYLE_REF_APPLY_SCOPE,
    actionLabel: "应用 Profile",
    runningMessage: "创建 ReviewItem 进 ReviewInbox(待人工审批)...",
    successMessage: () => store.lastActionMessage || "已应用。",
    nextStep: () => "下一步:打开 ReviewInbox 审阅 `review_style_ref_apply_*` 条目,审通过后规则自动入 4 集合。",
    action: () => store.applyProfile(store.currentProfile.profile_id),
  });
}

async function refreshInjectionPreview(draft) {
  if (!store.currentProfile?.profile_id) return;
  store.applyDraft = { ...draft };
  try {
    await store.dryrunInjectionPreview(store.currentProfile.profile_id, draft);
  } catch (err) {
    // 静默降级:preview 失败不阻塞 apply 流程,InjectionBundlePreview 显示 error 即可
  }
}

function scrollToSubDim(dimPath) {
  highlightedDim.value = dimPath;
  const el = subDimRefs.value[dimPath];
  if (el && typeof el.scrollIntoView === "function") {
    el.scrollIntoView({ behavior: "smooth", block: "start" });
  }
}

function setSubDimRef(dimPath, el) {
  if (el) {
    subDimRefs.value[dimPath] = el;
  } else {
    delete subDimRefs.value[dimPath];
  }
}

function gotoReviewInbox() {
  navigate("review");
}

function gotoSystemConfig() {
  navigate("system-config");
}

function describeSubDim(dimPath) {
  const labels = {
    "language.sentence_structure": "句法",
    "language.vocabulary": "词汇",
    "language.rhetoric": "修辞",
    "language.punctuation": "标点",
    "narrative.perspective": "视角",
    "narrative.pacing": "节奏",
    "narrative.time_handling": "时间",
    "narrative.information_density": "信息密度",
  };
  return labels[dimPath] || dimPath;
}
</script>

<template>
  <main class="style-reference-view" data-testid="reference-learning-view">
    <WorkflowPageHeader viewId="reference" kicker="抽取阶段" />

    <FlowActionReceipt :receipt="receipt" />

    <p v-if="store.error" class="view-error" role="alert">
      {{ store.error }}
      <BaseButton v-if="store.error.includes('LLM')" variant="primary" size="sm" @click="gotoSystemConfig">
        前往 SystemConfig
      </BaseButton>
    </p>

    <section class="reference-layout">
      <!-- 左侧:books 列表 + 导入 -->
      <aside class="books-side">
        <section class="import-card">
          <header class="card-head">
            <p class="card-title">导入参考书</p>
          </header>
          <nav class="import-tabs">
            <button
              type="button"
              class="tab"
              :class="{ 'tab-active': importMode === 'path' }"
              data-testid="reference-import-toggle"
              @click="setImportMode('path')"
            >文件路径</button>
            <button
              type="button"
              class="tab"
              :class="{ 'tab-active': importMode === 'upload' }"
              data-testid="reference-import-toggle-upload"
              @click="setImportMode('upload')"
            >上传文件</button>
          </nav>

          <div v-if="importMode === 'path'" class="form">
            <label class="field">
              <span class="field-label">文件路径(后端可读)</span>
              <input
                type="text"
                v-model="store.pathDraft.file_path"
                placeholder="如 backend/tests/golden/style_reference/corpus/luxun_short_stories.txt"
                data-testid="reference-import-path"
              />
            </label>
            <label class="field">
              <span class="field-label">书名</span>
              <input type="text" v-model="store.pathDraft.title" placeholder="例:鲁迅短篇集" />
            </label>
            <label class="field">
              <span class="field-label">作者(可选)</span>
              <input type="text" v-model="store.pathDraft.author_label" />
            </label>
            <label class="field">
              <span class="field-label">云策略</span>
              <select v-model="store.pathDraft.cloud_policy">
                <option value="local_only">local_only(完全本地)</option>
                <option value="segments_only">segments_only(只云片段)</option>
                <option value="allow_full_cloud">allow_full_cloud(全文上云)</option>
              </select>
            </label>
            <BaseButton
              variant="primary"
              block
              :loading="store.loading"
              data-testid="reference-import-submit"
              @click="submitImport"
            >
              开始导入
            </BaseButton>
          </div>

          <div v-else class="form">
            <label class="field">
              <span class="field-label">选择文件(.txt / .md)</span>
              <input type="file" accept=".txt,.md,.markdown" @change="handleFileChange" />
            </label>
            <label class="field">
              <span class="field-label">书名</span>
              <input type="text" v-model="store.uploadDraft.title" />
            </label>
            <label class="field">
              <span class="field-label">作者(可选)</span>
              <input type="text" v-model="store.uploadDraft.author_label" />
            </label>
            <label class="field">
              <span class="field-label">云策略</span>
              <select v-model="store.uploadDraft.cloud_policy">
                <option value="local_only">local_only</option>
                <option value="segments_only">segments_only</option>
                <option value="allow_full_cloud">allow_full_cloud</option>
              </select>
            </label>
            <BaseButton variant="primary" block :loading="store.loading" @click="submitImport">
              开始上传
            </BaseButton>
          </div>
        </section>

        <section class="books-list-card">
          <header class="card-head">
            <p class="card-title">参考书列表({{ store.books.length }})</p>
          </header>
          <BaseEmptyState
            v-if="store.books.length === 0"
            title="尚无参考书"
            description="导入第一本 TXT/MD 文件开始风格抽取。"
          />
          <ul v-else class="books-list" data-testid="reference-book-list">
            <li
              v-for="book in store.books"
              :key="book.book_id"
              class="book-row"
              :class="{ 'book-row-selected': store.selectedBookId === book.book_id }"
            >
              <button type="button" class="book-row-main" @click="selectBook(book.book_id)">
                <strong>{{ book.title }}</strong>
                <span class="book-row-meta">
                  {{ book.author_label || "—" }} · {{ book.total_chars }} 字 · {{ book.status }}
                </span>
              </button>
              <BaseButton variant="ghost" size="sm" @click="deleteBook(book.book_id)">删除</BaseButton>
            </li>
          </ul>
        </section>
      </aside>

      <!-- 右侧:主区 -->
      <section class="main-side">
        <BaseEmptyState
          v-if="!store.currentBook"
          title="尚未选择参考书"
          description="左侧选择一本书查看维度矩阵 / findings / profile,或导入新书。"
        />

        <template v-else>
          <!-- 书 stats header -->
          <header class="book-stats-head">
            <div class="book-title-row">
              <h2 class="book-title">{{ store.currentBook.title }}</h2>
              <BaseBadge :tone="store.currentBook.status === 'ready' ? 'success' : 'info'">
                {{ store.currentBook.status }}
              </BaseBadge>
            </div>
            <p class="book-meta">
              {{ store.currentBook.author_label || "—" }} · {{ store.currentBook.total_chars }} 字 ·
              cloud_policy = {{ store.currentBook.cloud_policy }}
            </p>
            <div class="stats-rows">
              <div class="stat-block">
                <p class="stat-label">输入量评估</p>
                <p class="stat-value">
                  <BaseBadge v-for="(level, layer) in inputAssessment" :key="layer" tone="info">
                    {{ layer }}:{{ level }}
                  </BaseBadge>
                </p>
              </div>
              <div v-if="Object.keys(paragraphTypeDist).length > 0" class="stat-block">
                <p class="stat-label">段落类型分布</p>
                <p class="stat-value">
                  <span v-for="(ratio, ptype) in paragraphTypeDist" :key="ptype" class="ptype-chip">
                    {{ ptype }}: {{ Math.round(ratio * 100) }}%
                  </span>
                </p>
              </div>
            </div>
          </header>

          <!-- 启动 run / 维度矩阵 -->
          <section v-if="!store.currentRun" class="empty-run">
            <BaseEmptyState
              title="尚未启动抽取"
              description="点击下方按钮启动 RunOrchestrator 调度 8 sub_dim 的 LLM 抽取。"
            >
              <template #action>
                <BaseButton
                  variant="primary"
                  :loading="store.loading"
                  data-testid="reference-start-run"
                  @click="startRun"
                >
                  启动抽取 run
                </BaseButton>
              </template>
            </BaseEmptyState>
          </section>

          <template v-else>
            <section class="run-summary">
              <BaseBadge :tone="store.currentRun.status === 'done' ? 'success' : 'info'">
                run {{ store.currentRun.run_id.slice(-12) }} · {{ store.currentRun.status }}
              </BaseBadge>
              <span class="run-hint">共 {{ totalFindings }} 条 findings。</span>
            </section>

            <DimensionMatrix
              :findings="store.findings"
              :input-assessment="inputAssessment"
              :highlight-dim="highlightedDim"
              @select-sub-dim="scrollToSubDim"
            />

            <LazySection title="按 sub_dim 审阅 findings" initiallyOpen>
              <BaseEmptyState
                v-if="totalFindings === 0"
                title="该 run 暂无 findings"
                description="可能 LLM 未启用,或抽取结果都被两级重试丢弃了。前往 SystemConfig 检查 LLM provider。"
              />
              <div v-else class="findings-by-dim" data-testid="reference-finding-list">
                <article
                  v-for="bucket in findingsBySubDim"
                  :key="bucket.subDim"
                  :ref="(el) => setSubDimRef(bucket.subDim, el)"
                  class="dim-block"
                  :class="{ 'dim-block-highlight': highlightedDim === bucket.subDim }"
                >
                  <header class="dim-head">
                    <p class="dim-title">{{ describeSubDim(bucket.subDim) }}({{ bucket.subDim }})</p>
                    <p class="dim-counts">
                      {{ bucket.observations.length }} 正向 ·
                      {{ bucket.forbidden_patterns.length }} 禁忌
                    </p>
                  </header>
                  <div v-if="bucket.observations.length + bucket.forbidden_patterns.length > 0" class="dim-findings">
                    <FindingCard
                      v-for="f in bucket.observations"
                      :key="f.finding_id"
                      :finding="f"
                      :busy="reviewingFindingId === f.finding_id"
                      @review="(decision) => reviewFinding(f.finding_id, decision)"
                    />
                    <FindingCard
                      v-for="f in bucket.forbidden_patterns"
                      :key="f.finding_id"
                      :finding="f"
                      :busy="reviewingFindingId === f.finding_id"
                      @review="(decision) => reviewFinding(f.finding_id, decision)"
                    />
                  </div>
                  <p v-else class="dim-empty">该 sub_dim 无 finding(可能输入量不足或全部被重试丢弃)。</p>
                </article>
              </div>
            </LazySection>

            <!-- Profile section -->
            <section v-if="store.currentRun.status === 'done'" class="profile-section">
              <div v-if="!store.currentProfile" class="profile-empty">
                <BaseEmptyState
                  title="尚未聚合 Profile"
                  description="审阅完 findings 后,点击聚合按钮把 8 sub_dim 整合为 StyleProfile。"
                >
                  <template #action>
                    <BaseButton
                      variant="primary"
                      :loading="store.loading"
                      data-testid="reference-advance-run"
                      @click="synthesize"
                    >
                      聚合为 Profile
                    </BaseButton>
                  </template>
                </BaseEmptyState>
              </div>

              <article v-else class="profile-card">
                <header class="profile-head">
                  <h3>{{ store.currentProfile.title }}</h3>
                  <BaseBadge :tone="store.currentProfile.status === 'active' ? 'success' : 'info'">
                    {{ store.currentProfile.status }}
                  </BaseBadge>
                </header>
                <p class="profile-summary">
                  {{ store.currentProfile.profile_json?.narrative_summary || "(无简述)" }}
                </p>
                <div class="profile-feature-block">
                  <p class="feature-title">style_features({{ (store.currentProfile.profile_json?.style_features || []).length }})</p>
                  <ul class="feature-list">
                    <li v-for="item in (store.currentProfile.profile_json?.style_features || [])" :key="item">{{ item }}</li>
                  </ul>
                </div>
                <div class="profile-feature-block">
                  <p class="feature-title">narrative_patterns({{ (store.currentProfile.profile_json?.narrative_patterns || []).length }})</p>
                  <ul class="feature-list">
                    <li v-for="item in (store.currentProfile.profile_json?.narrative_patterns || [])" :key="item">{{ item }}</li>
                  </ul>
                </div>
                <div class="profile-feature-block">
                  <p class="feature-title">banned_replication_rules({{ (store.currentProfile.profile_json?.banned_replication_rules || []).length }})</p>
                  <ul class="feature-list feature-list-danger">
                    <li v-for="item in (store.currentProfile.profile_json?.banned_replication_rules || [])" :key="item">{{ item }}</li>
                  </ul>
                </div>

                <PreviewPanel :samples="store.previewSamples" :busy="store.loading" @regenerate="regeneratePreview" />

                <footer class="profile-actions">
                  <BaseButton
                    variant="primary"
                    data-testid="reference-apply-button"
                    @click="applyDialogOpen = true"
                  >应用 Profile</BaseButton>
                  <BaseButton variant="ghost" @click="gotoReviewInbox">查看 ReviewInbox</BaseButton>
                </footer>
              </article>
            </section>
          </template>
        </template>
      </section>
    </section>

    <ProfileApplyDialog
      :open="applyDialogOpen"
      :draft="store.applyDraft"
      :busy="store.loading"
      :preview="store.currentInjectionPreview"
      :preview-loading="store.injectionPreviewLoading"
      :preview-error="store.error || ''"
      @close="applyDialogOpen = false"
      @submit="applyProfile"
      @update:draft="(value) => (store.applyDraft = value)"
      @request-preview="refreshInjectionPreview"
    />
  </main>
</template>

<style scoped>
.style-reference-view {
  display: grid;
  gap: 1rem;
  padding: 1rem 1.5rem;
}

.view-error {
  display: flex;
  gap: 0.6rem;
  align-items: center;
  padding: 0.65rem 0.9rem;
  border-radius: var(--radius-md, 6px);
  background: #fbeded;
  color: #8a2c2c;
  border: 1px solid rgba(138, 44, 44, 0.18);
  font-size: 0.88rem;
}

.reference-layout {
  display: grid;
  grid-template-columns: 22rem 1fr;
  gap: 1.2rem;
  align-items: start;
}

@media (max-width: 1024px) {
  .reference-layout { grid-template-columns: 1fr; }
}

.books-side { display: grid; gap: 1rem; }

.import-card,
.books-list-card,
.book-stats-head,
.profile-card,
.empty-run,
.profile-section {
  display: grid;
  gap: 0.7rem;
  padding: 1rem 1.2rem;
  border: 1px solid var(--surface-line, rgba(33, 26, 21, 0.15));
  border-radius: var(--radius-panel, 8px);
  background: var(--color-panel-solid, #fffdf7);
}

.card-head { display: flex; justify-content: space-between; align-items: center; }
.card-title { margin: 0; font-weight: 700; font-size: 0.95rem; }

.import-tabs { display: flex; gap: 0.4rem; }
.tab {
  flex: 1;
  padding: 0.45rem 0.6rem;
  border: 1px solid var(--surface-line, rgba(33, 26, 21, 0.15));
  border-radius: var(--radius-sm, 4px);
  background: transparent;
  font: inherit;
  cursor: pointer;
}
.tab-active { background: var(--color-primary, #4a90e2); color: #fff; border-color: var(--color-primary, #4a90e2); }

.form { display: grid; gap: 0.6rem; }
.field { display: grid; gap: 0.25rem; font-size: 0.85rem; }
.field-label { color: var(--text-muted, rgba(33, 26, 21, 0.68)); font-weight: 600; }
.field input,
.field select {
  padding: 0.45rem 0.6rem;
  border: 1px solid var(--surface-line, rgba(33, 26, 21, 0.18));
  border-radius: var(--radius-sm, 4px);
  background: #fff;
  font: inherit;
}

.books-list { list-style: none; margin: 0; padding: 0; display: grid; gap: 0.4rem; }
.book-row {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  padding: 0.5rem 0.65rem;
  border: 1px solid var(--surface-line, rgba(33, 26, 21, 0.12));
  border-radius: var(--radius-md, 6px);
  background: var(--color-panel-solid, #fffdf7);
}
.book-row-selected { border-color: var(--color-primary, #4a90e2); box-shadow: 0 0 0 1px var(--color-primary, #4a90e2); }
.book-row-main {
  flex: 1;
  display: grid;
  gap: 0.15rem;
  background: none;
  border: none;
  text-align: left;
  cursor: pointer;
  font: inherit;
  padding: 0;
}
.book-row-meta { font-size: 0.78rem; color: var(--text-muted, rgba(33, 26, 21, 0.6)); }

.main-side { display: grid; gap: 1rem; }

.book-title-row { display: flex; align-items: center; gap: 0.5rem; }
.book-title { margin: 0; font-size: 1.15rem; }
.book-meta { margin: 0; font-size: 0.84rem; color: var(--text-muted, rgba(33, 26, 21, 0.6)); }
.stats-rows { display: grid; gap: 0.5rem; }
.stat-block { display: grid; gap: 0.25rem; }
.stat-label { margin: 0; font-size: 0.78rem; font-weight: 600; color: var(--text-muted, rgba(33, 26, 21, 0.68)); text-transform: uppercase; letter-spacing: 0.04em; }
.stat-value { margin: 0; display: flex; flex-wrap: wrap; gap: 0.35rem; }
.ptype-chip {
  display: inline-block;
  padding: 0.18rem 0.45rem;
  font-size: 0.74rem;
  border: 1px solid var(--surface-line, rgba(33, 26, 21, 0.12));
  border-radius: var(--radius-pill, 999px);
  background: rgba(0, 0, 0, 0.03);
}

.run-summary {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.55rem 0.8rem;
  border-radius: var(--radius-md, 6px);
  background: color-mix(in srgb, var(--color-panel-solid, #fffdf7) 85%, transparent);
}
.run-hint { font-size: 0.84rem; color: var(--text-muted, rgba(33, 26, 21, 0.62)); }

.findings-by-dim { display: grid; gap: 0.8rem; }
.dim-block {
  display: grid;
  gap: 0.55rem;
  padding: 0.7rem 0.85rem;
  border: 1px solid var(--surface-line, rgba(33, 26, 21, 0.12));
  border-radius: var(--radius-md, 6px);
  background: color-mix(in srgb, var(--color-panel-solid, #fffdf7) 92%, transparent);
  scroll-margin-top: 1rem;
}
.dim-block-highlight { border-color: var(--color-primary, #4a90e2); box-shadow: 0 0 0 1px var(--color-primary, #4a90e2); }
.dim-head { display: flex; justify-content: space-between; align-items: baseline; gap: 0.5rem; }
.dim-title { margin: 0; font-weight: 700; font-size: 0.92rem; }
.dim-counts { margin: 0; font-size: 0.78rem; color: var(--text-muted, rgba(33, 26, 21, 0.62)); }
.dim-findings { display: grid; gap: 0.5rem; }
.dim-empty { margin: 0; font-size: 0.82rem; color: var(--text-muted, rgba(33, 26, 21, 0.55)); }

.profile-section { padding: 0; border: none; background: none; gap: 1rem; }
.profile-empty { display: grid; gap: 0.6rem; }
.profile-card { padding: 1rem 1.2rem; }
.profile-head { display: flex; align-items: center; gap: 0.5rem; }
.profile-head h3 { margin: 0; font-size: 1.05rem; }
.profile-summary { margin: 0; line-height: 1.6; }
.profile-feature-block { display: grid; gap: 0.3rem; }
.feature-title { margin: 0; font-weight: 600; font-size: 0.84rem; color: var(--text-muted, rgba(33, 26, 21, 0.68)); }
.feature-list { margin: 0; padding-left: 1.25rem; display: grid; gap: 0.2rem; font-size: 0.88rem; line-height: 1.55; }
.feature-list-danger li { color: #8c3636; }
.profile-actions { display: flex; gap: 0.5rem; }
</style>
