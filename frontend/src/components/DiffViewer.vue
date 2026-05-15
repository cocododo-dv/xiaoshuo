<script setup>
import { computed } from "vue";

const props = defineProps({
  beforeText: {
    type: String,
    default: "",
  },
  afterText: {
    type: String,
    default: "",
  },
  status: {
    type: String,
    default: "clean",
  },
});

function splitLines(value) {
  const lines = String(value || "").split(/\r?\n/);
  return lines.length ? lines : [""];
}

function lineRows(before, after, kind) {
  const peer = new Set(splitLines(kind === "before" ? after : before).map((line) => line.trim()).filter(Boolean));
  return splitLines(kind === "before" ? before : after).map((line, index) => {
    const trimmed = line.trim();
    const changed = Boolean(trimmed && !peer.has(trimmed));
    return {
      key: `${kind}-${index}-${line.slice(0, 12)}`,
      text: line,
      className: changed ? (kind === "before" ? "diff-line-removed" : "diff-line-added") : "diff-line-neutral",
    };
  });
}

const beforeRows = computed(() => lineRows(props.beforeText, props.afterText, "before"));
const afterRows = computed(() => lineRows(props.beforeText, props.afterText, "after"));
</script>

<template>
  <div class="diff-viewer" :data-status="status">
    <section class="diff-viewer-pane" data-testid="diff-viewer-before">
      <header>
        <span>修改前</span>
      </header>
      <p v-for="row in beforeRows" :key="row.key" :class="row.className">{{ row.text || " " }}</p>
    </section>
    <section class="diff-viewer-pane" data-testid="diff-viewer-after">
      <header>
        <span>修改后</span>
      </header>
      <p v-for="row in afterRows" :key="row.key" :class="row.className">{{ row.text || " " }}</p>
    </section>
  </div>
</template>

<style scoped>
.diff-viewer {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
}

.diff-viewer-pane {
  min-width: 0;
  overflow: hidden;
  border: 1px solid rgba(47, 111, 98, 0.16);
  border-radius: 8px;
  background: #fffefa;
}

.diff-viewer-pane header {
  padding: 8px 10px;
  border-bottom: 1px solid rgba(47, 111, 98, 0.12);
  color: #345b53;
  font-weight: 800;
}

.diff-viewer-pane p {
  margin: 0;
  padding: 5px 10px;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  line-height: 1.55;
}

.diff-line-removed {
  background: #fff0eb;
  color: #8b3d2f;
}

.diff-line-added {
  background: #edf8f1;
  color: #235f51;
}

.diff-line-neutral {
  color: #2f3f3a;
}

@media (max-width: 760px) {
  .diff-viewer {
    grid-template-columns: 1fr;
  }
}
</style>
