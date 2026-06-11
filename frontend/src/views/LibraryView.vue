<script setup>
import { ArrowRight, BookUser, Boxes, Landmark, Link2, MapPin, Plus, Sparkles, Trash2, Users } from "lucide-vue-next";
import { computed, onActivated, onMounted, ref } from "vue";

import { useShellRouter } from "../router";
import { useLibraryStore } from "../stores/library";
import { useSnowflakeWorkbenchStore } from "../stores/snowflakeWorkbench";

const emit = defineEmits(["notice"]);

const router = useShellRouter();
const library = useLibraryStore();
const snowflake = useSnowflakeWorkbenchStore();

const KIND_SECTIONS = [
  { kind: "character", label: "人物", icon: Users, hint: "来自雪花角色档案的权威实体,在构思里维护。" },
  { kind: "location", label: "地点", icon: MapPin, hint: "故事发生的舞台:城市、屋宅、街巷。" },
  { kind: "item", label: "物品", icon: Boxes, hint: "承载线索与情感的关键道具。" },
  { kind: "faction", label: "阵营", icon: Landmark, hint: "组织、家族与势力。" },
  { kind: "concept", label: "设定", icon: Sparkles, hint: "世界观规则、术语与约定。" },
];

const editingId = ref("");
const form = ref({ kind: "location", name: "", summary: "", tags: "" });
const relationForm = ref({ from_ref: "", to_ref: "", kind: "related", note: "" });

async function refresh() {
  try {
    await snowflake.initialize();
  } catch {
    /* 项目列表加载失败时下方显示空态 */
  }
  const projectId = snowflake.selectedProjectId || snowflake.project?.project_id || "";
  if (projectId) {
    await library.load(projectId).catch(() => {});
  }
}

onMounted(refresh);
onActivated(() => {
  const projectId = snowflake.selectedProjectId || snowflake.project?.project_id || "";
  if (projectId && projectId !== library.projectId) {
    library.load(projectId).catch(() => {});
  }
});

const hasProject = computed(() => Boolean(library.projectId));
const characters = computed(() => library.characters);
const refNames = computed(() => Object.fromEntries(library.allRefs.map((item) => [item.ref, item.name])));

function sectionEntities(kind) {
  return kind === "character" ? characters.value : library.entitiesByKind(kind);
}

function startCreate(kind) {
  editingId.value = "";
  form.value = { kind: kind === "character" ? "location" : kind, name: "", summary: "", tags: "" };
}

function startEdit(entity) {
  editingId.value = entity.entity_id;
  form.value = {
    kind: entity.kind,
    name: entity.name,
    summary: entity.summary || "",
    tags: (entity.tags || []).join("、"),
  };
}

async function submitEntity() {
  const payload = {
    kind: form.value.kind,
    name: form.value.name.trim(),
    summary: form.value.summary.trim(),
    tags: form.value.tags.split(/[、,，\s]+/).map((tag) => tag.trim()).filter(Boolean),
  };
  if (!payload.name) {
    return;
  }
  if (editingId.value) {
    await library.updateEntity(editingId.value, payload);
    emit("notice", { type: "success", message: `「${payload.name}」已更新。` });
  } else {
    await library.createEntity(payload);
    emit("notice", { type: "success", message: `「${payload.name}」已登记进资料库。` });
  }
  startCreate(payload.kind);
}

async function archiveEntity(entity) {
  await library.updateEntity(entity.entity_id, { status: "archived" });
  emit("notice", { type: "success", message: `「${entity.name}」已归档。` });
}

async function submitRelation() {
  if (!relationForm.value.from_ref || !relationForm.value.to_ref) {
    return;
  }
  await library.createRelation({ ...relationForm.value, note: relationForm.value.note.trim() });
  emit("notice", { type: "success", message: "关系已记录。" });
  relationForm.value = { from_ref: "", to_ref: "", kind: "related", note: "" };
}

async function removeRelation(relation) {
  await library.removeRelation(relation.relation_id);
  emit("notice", { type: "success", message: "关系已删除。" });
}

/* —— 关系网(设计稿 lib-graph 的 P0:确定性圆环布局,零依赖)—— */
const GRAPH_W = 640;
const GRAPH_H = 380;
const KIND_COLORS = {
  character: "var(--crimson)",
  location: "var(--sage)",
  item: "var(--gold)",
  faction: "var(--slate)",
  concept: "var(--rose)",
};
const hoveredRef = ref("");

const graphNodes = computed(() => {
  const refs = library.allRefs.slice(0, 24);
  const cx = GRAPH_W / 2;
  const cy = GRAPH_H / 2;
  const radius = Math.min(cx, cy) - 46;
  return refs.map((item, index) => {
    const angle = (index / Math.max(refs.length, 1)) * Math.PI * 2 - Math.PI / 2;
    return {
      ...item,
      x: cx + radius * Math.cos(angle),
      y: cy + radius * Math.sin(angle),
      color: KIND_COLORS[item.kind] || "var(--ink-3)",
      anchor: Math.cos(angle) > 0.25 ? "start" : Math.cos(angle) < -0.25 ? "end" : "middle",
    };
  });
});

const graphNodeMap = computed(() => Object.fromEntries(graphNodes.value.map((node) => [node.ref, node])));

const graphEdges = computed(() =>
  library.relations
    .map((relation) => {
      const from = graphNodeMap.value[relation.from_ref];
      const to = graphNodeMap.value[relation.to_ref];
      if (!from || !to) {
        return null;
      }
      return {
        id: relation.relation_id,
        kind: relation.kind,
        from,
        to,
        mx: (from.x + to.x) / 2,
        my: (from.y + to.y) / 2,
        hot: hoveredRef.value && (relation.from_ref === hoveredRef.value || relation.to_ref === hoveredRef.value),
      };
    })
    .filter(Boolean),
);

const graphOverflow = computed(() => Math.max(0, library.allRefs.length - 24));

function goCharacters() {
  router.navigate("snowflake-workbench", { target: { step: "character_sheets" } });
}
</script>

<template>
  <div class="ws-page ws-view lib" data-testid="library-view">
    <header class="page-header">
      <div>
        <div class="page-eyebrow">资料库</div>
        <h1 class="page-title">随写随查的世界档案</h1>
        <p class="page-subtitle">人物、地点、物品与设定登记在册,关系连成网——写到哪儿,查到哪儿。</p>
      </div>
    </header>

    <p v-if="!hasProject && !library.loading" class="text-muted">先在构思里创建作品,资料库会跟着这部作品建档。</p>
    <p v-if="library.error" class="lib-error">{{ library.error }}</p>

    <template v-if="hasProject">
      <section v-for="section in KIND_SECTIONS" :key="section.kind" class="lib-section" :data-testid="`library-section-${section.kind}`">
        <div class="lib-section-head">
          <span class="lib-section-ic"><component :is="section.icon" :size="17" /></span>
          <h2 class="lib-section-title">{{ section.label }}</h2>
          <span class="lib-section-count tab-num">{{ sectionEntities(section.kind).length }}</span>
          <span class="lib-section-hint">{{ section.hint }}</span>
          <button
            v-if="section.kind !== 'character'"
            type="button"
            class="btn btn-ghost btn-sm"
            :data-testid="`library-add-${section.kind}`"
            @click="startCreate(section.kind)"
          >
            <Plus :size="14" /> 登记
          </button>
          <button v-else type="button" class="btn btn-quiet btn-sm" @click="goCharacters">
            去角色档案 <ArrowRight :size="13" />
          </button>
        </div>

        <div v-if="sectionEntities(section.kind).length" class="lib-grid">
          <article
            v-for="entity in sectionEntities(section.kind)"
            :key="entity.ref"
            class="card lib-card"
            :data-testid="`library-card-${entity.ref}`"
          >
            <div class="lib-card-head">
              <strong class="lib-card-name">{{ entity.name }}</strong>
              <span v-if="entity.role" class="pill pill-slate text-xs">{{ entity.role }}</span>
            </div>
            <p class="lib-card-summary">{{ entity.summary || "(还没有摘要)" }}</p>
            <div class="lib-card-foot">
              <span v-for="tag in entity.tags || []" :key="tag" class="pill text-xs">{{ tag }}</span>
              <span class="flex-1" />
              <template v-if="section.kind !== 'character'">
                <button type="button" class="btn btn-quiet btn-sm" @click="startEdit(entity)">编辑</button>
                <button type="button" class="btn btn-quiet btn-sm lib-archive" title="归档(可在数据层恢复)" @click="archiveEntity(entity)">
                  <Trash2 :size="13" />
                </button>
              </template>
              <button v-else type="button" class="btn btn-quiet btn-sm" @click="goCharacters">详情</button>
            </div>
          </article>
        </div>
        <p v-else class="lib-empty">
          {{ section.kind === "character" ? "还没有角色——到构思第 4 步建立角色摘要表。" : `还没有${section.label}——写到它们时顺手登记一笔。` }}
        </p>
      </section>

      <section class="lib-section" data-testid="library-editor">
        <div class="lib-section-head">
          <span class="lib-section-ic"><BookUser :size="17" /></span>
          <h2 class="lib-section-title">{{ editingId ? "编辑实体" : "登记新实体" }}</h2>
        </div>
        <div class="lib-form card">
          <label>
            <span>类别</span>
            <select v-model="form.kind" class="control-input" data-testid="library-form-kind">
              <option value="location">地点</option>
              <option value="item">物品</option>
              <option value="faction">阵营</option>
              <option value="concept">设定</option>
            </select>
          </label>
          <label>
            <span>名称(必填)</span>
            <input v-model="form.name" class="control-input" data-testid="library-form-name" placeholder="例如:盐场 / 旧工牌 / 档案馆" />
          </label>
          <label class="lib-form-wide">
            <span>摘要</span>
            <textarea v-model="form.summary" class="control-input" rows="2" placeholder="一两句话:它是什么、为什么重要。" />
          </label>
          <label class="lib-form-wide">
            <span>标签(顿号或空格分隔)</span>
            <input v-model="form.tags" class="control-input" placeholder="第一幕、线索" />
          </label>
          <div class="lib-form-actions">
            <button v-if="editingId" type="button" class="btn btn-ghost" @click="startCreate(form.kind)">取消编辑</button>
            <button
              type="button"
              class="btn btn-accent"
              data-testid="library-form-submit"
              :disabled="!form.name.trim() || library.actionId.startsWith('entity')"
              @click="submitEntity"
            >
              {{ editingId ? "保存修改" : "登记" }}
            </button>
          </div>
        </div>
      </section>

      <section v-if="graphNodes.length > 1" class="lib-section" data-testid="library-graph">
        <div class="lib-section-head">
          <span class="lib-section-ic"><Link2 :size="17" /></span>
          <h2 class="lib-section-title">关系网</h2>
          <span class="lib-section-hint">
            悬停节点高亮它的连线{{ graphOverflow ? ` · 仅显示前 24 个对象(还有 ${graphOverflow} 个未入图)` : "" }}
          </span>
        </div>
        <div class="lib-graph card">
          <svg :viewBox="`0 0 ${GRAPH_W} ${GRAPH_H}`" class="lib-graph-svg" role="img" aria-label="实体关系网">
            <g>
              <line
                v-for="edge in graphEdges"
                :key="edge.id"
                :x1="edge.from.x"
                :y1="edge.from.y"
                :x2="edge.to.x"
                :y2="edge.to.y"
                class="lib-graph-edge"
                :class="{ 'is-hot': edge.hot, 'is-dim': hoveredRef && !edge.hot }"
              />
            </g>
            <g>
              <text
                v-for="edge in graphEdges"
                v-show="edge.hot"
                :key="`label-${edge.id}`"
                :x="edge.mx"
                :y="edge.my - 5"
                text-anchor="middle"
                class="lib-graph-edge-label"
              >
                {{ edge.kind }}
              </text>
            </g>
            <g
              v-for="node in graphNodes"
              :key="node.ref"
              class="lib-graph-node"
              :class="{ 'is-dim': hoveredRef && hoveredRef !== node.ref && !graphEdges.some((edge) => edge.hot && (edge.from.ref === node.ref || edge.to.ref === node.ref)) }"
              @mouseenter="hoveredRef = node.ref"
              @mouseleave="hoveredRef = ''"
            >
              <circle :cx="node.x" :cy="node.y" r="7" :fill="node.color" />
              <text
                :x="node.x + (node.anchor === 'start' ? 12 : node.anchor === 'end' ? -12 : 0)"
                :y="node.y + (node.anchor === 'middle' ? (node.y < GRAPH_H / 2 ? -13 : 21) : 4)"
                :text-anchor="node.anchor"
                class="lib-graph-label"
              >
                {{ node.name }}
              </text>
            </g>
          </svg>
        </div>
      </section>

      <section class="lib-section" data-testid="library-relations">
        <div class="lib-section-head">
          <span class="lib-section-ic"><Link2 :size="17" /></span>
          <h2 class="lib-section-title">关系</h2>
          <span class="lib-section-count tab-num">{{ library.relations.length }}</span>
          <span class="lib-section-hint">谁住在哪、谁属于谁、什么牵着什么——图谱视图在路上,先把边记下来。</span>
        </div>

        <div class="lib-relation-form card">
          <select v-model="relationForm.from_ref" class="control-input" data-testid="library-relation-from">
            <option value="">选起点…</option>
            <option v-for="item in library.allRefs" :key="`from-${item.ref}`" :value="item.ref">{{ item.name }}</option>
          </select>
          <input v-model="relationForm.kind" class="control-input lib-relation-kind" placeholder="关系,如 lives_in / 师徒" />
          <select v-model="relationForm.to_ref" class="control-input" data-testid="library-relation-to">
            <option value="">选终点…</option>
            <option v-for="item in library.allRefs" :key="`to-${item.ref}`" :value="item.ref">{{ item.name }}</option>
          </select>
          <input v-model="relationForm.note" class="control-input lib-relation-note" placeholder="备注(可选)" />
          <button
            type="button"
            class="btn btn-accent"
            data-testid="library-relation-submit"
            :disabled="!relationForm.from_ref || !relationForm.to_ref || library.actionId === 'relation-create'"
            @click="submitRelation"
          >
            连线
          </button>
        </div>

        <ul v-if="library.relations.length" class="lib-relation-list">
          <li v-for="relation in library.relations" :key="relation.relation_id" :data-testid="`library-relation-${relation.relation_id}`">
            <strong>{{ refNames[relation.from_ref] || relation.from_ref }}</strong>
            <span class="pill pill-gold text-xs">{{ relation.kind }}</span>
            <strong>{{ refNames[relation.to_ref] || relation.to_ref }}</strong>
            <small v-if="relation.note" class="text-muted">{{ relation.note }}</small>
            <span class="flex-1" />
            <button type="button" class="btn btn-quiet btn-sm" @click="removeRelation(relation)"><Trash2 :size="13" /></button>
          </li>
        </ul>
        <p v-else class="lib-empty">还没有关系边。</p>
      </section>
    </template>
  </div>
</template>

<style scoped>
.lib-section {
  margin-bottom: 26px;
}

.lib-section-head {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  margin-bottom: 12px;
}

.lib-section-ic {
  width: 30px;
  height: 30px;
  border-radius: 9px;
  display: grid;
  place-items: center;
  background: var(--crimson-wash);
  color: var(--crimson);
}

.lib-section-title {
  font-family: var(--font-serif);
  font-size: 18px;
  font-weight: 600;
  margin: 0;
}

.lib-section-count {
  font-family: var(--font-serif);
  font-size: 15px;
  color: var(--ink-3);
}

.lib-section-hint {
  font-size: 12px;
  color: var(--ink-4);
  flex: 1;
  min-width: 12ch;
}

.lib-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(230px, 1fr));
  gap: 12px;
}

.lib-card {
  padding: 14px 16px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.lib-card-head {
  display: flex;
  align-items: center;
  gap: 8px;
  justify-content: space-between;
}

.lib-card-name {
  font-family: var(--font-serif);
  font-size: 15.5px;
  color: var(--ink-1);
}

.lib-card-summary {
  margin: 0;
  font-size: 12.5px;
  color: var(--ink-3);
  line-height: 1.6;
  flex: 1;
}

.lib-card-foot {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}

.lib-archive:hover {
  color: var(--rose);
}

.lib-empty {
  font-size: 12.5px;
  color: var(--ink-4);
  border: 1px dashed var(--line-2);
  border-radius: var(--r-md);
  padding: 14px;
}

.lib-error {
  color: var(--rose);
  font-size: 13px;
}

.lib-form {
  display: grid;
  grid-template-columns: minmax(120px, 160px) minmax(0, 1fr);
  gap: 12px;
}

.lib-form label {
  display: grid;
  gap: 5px;
}

.lib-form label span {
  font-size: 12px;
  color: var(--ink-3);
}

.lib-form-wide {
  grid-column: 1 / -1;
}

.lib-form-actions {
  grid-column: 1 / -1;
  display: flex;
  justify-content: flex-end;
  gap: 8px;
}

.lib-graph {
  padding: 10px;
}

.lib-graph-svg {
  width: 100%;
  height: auto;
  display: block;
}

.lib-graph-edge {
  stroke: var(--line-2);
  stroke-width: 1.5;
  transition: stroke 120ms ease, opacity 120ms ease;
}

.lib-graph-edge.is-hot {
  stroke: var(--crimson);
  stroke-width: 2.5;
}

.lib-graph-edge.is-dim {
  opacity: 0.25;
}

.lib-graph-edge-label {
  font-size: 10px;
  fill: var(--crimson);
  font-family: var(--font-mono);
}

.lib-graph-node {
  cursor: pointer;
}

.lib-graph-node.is-dim {
  opacity: 0.3;
}

.lib-graph-label {
  font-size: 11.5px;
  fill: var(--ink-2);
  font-family: var(--font-serif);
}

.lib-relation-form {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(110px, 150px) minmax(0, 1fr) minmax(0, 1fr) auto;
  gap: 8px;
  align-items: center;
  margin-bottom: 12px;
}

.lib-relation-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  gap: 4px;
}

.lib-relation-list li {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  padding: 9px 12px;
  border: 1px solid var(--line-1);
  border-radius: var(--r-md);
  background: var(--paper-1);
  font-size: 13px;
}

.lib-relation-list strong {
  font-family: var(--font-serif);
}

@media (max-width: 900px) {
  .lib-form,
  .lib-relation-form {
    grid-template-columns: 1fr;
  }
}
</style>
