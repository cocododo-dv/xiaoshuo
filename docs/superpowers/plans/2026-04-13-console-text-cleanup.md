# Console Text Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove residual English and mojibake from the console shell, authoring surfaces, and directly surfaced author-lifecycle messages while keeping behavior unchanged.

**Architecture:** Lock the cleanup with tests first at three layers: backend author-lifecycle payload text, frontend source/unit assertions, and browser-visible authoring flows. Then apply the smallest copy-only changes across backend constants, Pinia notices, Vue templates, and README naming so all user-facing surfaces agree on one Chinese vocabulary.

**Tech Stack:** Python 3.12, FastAPI service strings, Vue 3, Pinia, Vitest, Playwright, Markdown.

---

### Task 1: Lock the expected Chinese copy in backend, unit, and E2E tests

**Files:**
- Modify: `backend/tests/test_author_lifecycle.py`
- Modify: `frontend/tests/authorWorkspace.spec.js`
- Modify: `frontend/tests/app.spec.js`
- Modify: `frontend/tests/e2e/author-workspace.spec.js`
- Modify: `frontend/tests/e2e/author-trash.spec.js`

- [ ] **Step 1: Update the backend author-lifecycle expectations to the final Chinese block reasons**

```python
assert chapters_response.json()["data"]["items"] == [
    {
        "chapter_id": "CH600",
        "planned_scene_count": 3,
        "chapter_goal": "Trash a single scene",
        "main_plot_push": "push CH600",
        "emotional_target": "emotion CH600",
        "ending_effect": "ending CH600",
        "must_not": "avoid CH600",
        "notes": "notes CH600",
        "current_phase": "drafting",
        "chapter_passed_scene_count": 0,
        "chapter_backfill_pending_count": 0,
        "active_scene_count": 1,
        "trashed_scene_count": 1,
        "trash_allowed": 0,
        "trash_block_reason": "章节下已有单独移入回收站的场景",
    }
]

assert chapter_trash_response.json()["data"] == {
    "processed": [],
    "blocked": [
        {
            "chapter_id": "CH610",
            "code": "CHAPTER_TRASH_BLOCKED_HAS_TRASHED_SCENES",
            "message": "章节下已有单独移入回收站的场景",
        }
    ],
    "actor_ref": "operator",
}

assert author_trash_response.json()["data"]["scenes"] == [
    {
        "scene_id": "CH620_SC01",
        "chapter_id": "CH620",
        "scene_seq": 1,
        "scene_goal": "goal for CH620_SC01",
        "trashed_at": author_trash_response.json()["data"]["scenes"][0]["trashed_at"],
        "trashed_by": "ops.author.chapter",
        "chapter_trashed": 1,
        "restore_allowed": 0,
        "restore_block_reason": "请先恢复所属章节，再恢复该场景",
        "purge_allowed": 0,
        "purge_block_reason": "该场景随章节一起回收，请在章节行中处理",
    },
    {
        "scene_id": "CH620_SC02",
        "chapter_id": "CH620",
        "scene_seq": 2,
        "scene_goal": "goal for CH620_SC02",
        "trashed_at": author_trash_response.json()["data"]["scenes"][1]["trashed_at"],
        "trashed_by": "ops.author.chapter",
        "chapter_trashed": 1,
        "restore_allowed": 0,
        "restore_block_reason": "请先恢复所属章节，再恢复该场景",
        "purge_allowed": 0,
        "purge_block_reason": "该场景随章节一起回收，请在章节行中处理",
    },
]

assert scene_restore_response.json()["data"] == {
    "processed": [],
    "blocked": [
        {
            "scene_id": "CH620_SC01",
            "code": "SCENE_RESTORE_BLOCKED_CHAPTER_TRASHED",
            "message": "请先恢复所属章节，再恢复该场景",
        }
    ],
    "actor_ref": "operator",
}
```

- [ ] **Step 2: Run the backend contract test and confirm it fails on the old English strings**

Run:

```powershell
cd backend
python -m pytest tests/test_author_lifecycle.py -q
```

Expected: `FAIL` with string mismatches such as `"chapter contains individually trashed scenes"` and `"restore the chapter to recover this scene"`.

- [ ] **Step 3: Update the frontend source-level tests to expect the final Chinese shell, store, and authoring copy**

```javascript
expect(routerSource).toContain('{ id: "author", label: "作者工作台" }');
expect(routerSource).toContain('{ id: "trash", label: "作者回收站" }');
expect(routerSource).toContain('{ id: "workbench", label: "场景工作台" }');
expect(routerSource).toContain('{ id: "review", label: "审核收件箱" }');
expect(routerSource).toContain('{ id: "index", label: "索引控制台" }');
expect(routerSource).toContain('{ id: "knowledge", label: "知识控制台" }');
expect(routerSource).toContain('{ id: "interop", label: "互操作中心" }');

expect(appSource).toContain("已保存 API 地址");
expect(appSource).toContain("已保存操作员标识");
expect(appSource).toContain("刷新全部视图");
expect(appSource).not.toContain("Saved API base");
expect(appSource).not.toContain("Saved operator ref");
expect(appSource).not.toContain("Refresh Everything");

expect(sceneTrashMessage).toContain("已移入作者回收站");
expect(chapterTrashMessage).toContain("已移入作者回收站");
expect(restoreMessage).toContain("已恢复");
expect(purgeMessage).toContain("已彻底清理");

expect(source).toContain('eyebrow="作者工作台"');
expect(source).toContain("将所选章节移入回收站");
expect(source).toContain("在场景工作台打开");

expect(source).toContain('eyebrow="作者回收站"');
expect(source).toContain("恢复所选章节");
expect(source).toContain("彻底清理所选场景");
```

- [ ] **Step 4: Run the frontend unit tests and confirm they fail on the current English/mojibake copy**

Run:

```powershell
cd frontend
npm exec vitest run tests/authorWorkspace.spec.js tests/app.spec.js
```

Expected: `FAIL` with missing strings such as `"作者工作台"`, `"已保存 API 地址"`, and other Chinese assertions that are not yet present.

- [ ] **Step 5: Update the browser assertions to the final Chinese UI text**

```javascript
await expect(page.getByTestId("author-workspace-view")).toContainText("作者工作台");
await expect(page.getByTestId("notice-stack")).toContainText("已保存章节 CH300");
await expect(page.getByTestId("notice-stack")).toContainText("已保存场景 CH300_SC01");
await page.getByLabel("地点").last().fill("North archive");
await expect(page.getByTestId("scene-workbench-view")).toContainText("地点：Clock bridge");

await expect(page.getByTestId("author-chapter-trash-block-CH310")).toContainText("回收站");
await expect(page.getByTestId("author-trash-view")).toContainText("作者回收站");
await expect(page.getByTestId("author-trash-empty")).toContainText("作者回收站为空");
```

- [ ] **Step 6: Run the targeted E2E specs and confirm they fail before implementation**

Run:

```powershell
cd frontend
npm run test:e2e -- tests/e2e/author-workspace.spec.js tests/e2e/author-trash.spec.js
```

Expected: `FAIL` on assertions that now require `"作者工作台"`, `"已保存章节 CH300"`, `"地点"`, and Chinese trash-state copy.

---

### Task 2: Implement the copy cleanup in backend constants, stores, router, and Vue views

**Files:**
- Modify: `backend/src/novel_system/services/author_lifecycle.py`
- Modify: `frontend/src/router.js`
- Modify: `frontend/src/App.vue`
- Modify: `frontend/src/stores/authorWorkspace.js`
- Modify: `frontend/src/stores/authorTrash.js`
- Modify: `frontend/src/views/AuthorWorkspaceView.vue`
- Modify: `frontend/src/views/AuthorTrashView.vue`

- [ ] **Step 1: Translate the backend author-lifecycle constants that are surfaced verbatim in the UI**

```python
TRASH_BLOCK_REASON_HAS_TRASHED_SCENES = "章节下已有单独移入回收站的场景"
SCENE_RUNTIME_ARTIFACTS_REASON = "场景已有下游运行产物"
CHAPTER_RUNTIME_ARTIFACTS_REASON = "章节下仍有场景存在下游运行产物"
SCENE_CHAPTER_TRASHED_RESTORE_REASON = "请先恢复所属章节，再恢复该场景"
SCENE_CHAPTER_TRASHED_PURGE_REASON = "该场景随章节一起回收，请在章节行中处理"
```

- [ ] **Step 2: Replace the shell navigation labels and top-level notices with Chinese copy, and remove the mojibake snapshot comment block**

```javascript
const views = [
  { id: "author", label: "作者工作台" },
  { id: "trash", label: "作者回收站" },
  { id: "workbench", label: "场景工作台" },
  { id: "review", label: "审核收件箱" },
  { id: "index", label: "索引控制台" },
  { id: "knowledge", label: "知识控制台" },
  { id: "interop", label: "互操作中心" },
];
```

```vue
function updateApiBase() {
  apiBase.value = setApiBase(apiBase.value);
  pushNotice(`已保存 API 地址：${apiBase.value}`);
}

function updateOperator() {
  operatorRef.value = setOperatorRef(operatorRef.value);
  pushNotice(`已保存操作员标识：${operatorRef.value}`);
}

pushNotice("已刷新全部视图。");
```

```vue
<div class="eyebrow">P2 编辑运营台</div>
<h1>小说系统控制台</h1>
<p>在同一个控制台里处理创作、运行审核与索引操作。</p>
<span>API 地址</span>
<span>操作员标识</span>
<button class="ghost" @click="reloadAll">刷新全部视图</button>
```

- [ ] **Step 3: Localize the author workspace copy and notices without changing selectors or behavior**

```javascript
if (!sceneIds.length || !confirmAction(`确认将选中的 ${sceneIds.length} 个场景移入作者回收站吗？`)) {
  return;
}

if (!chapterIds.length || !confirmAction(`确认将选中的 ${chapterIds.length} 个章节移入作者回收站吗？`)) {
  return;
}

emit("notice", `已在场景工作台打开 scene_card:${sceneId}`);
```

```javascript
if (!ids.length && !blockedCount) {
  return `未变更任何${itemLabel}。`;
}
const parts = [];
if (ids.length) {
  parts.push(`${actionLabel}${ids.length}个${itemLabel}：${ids.join(", ")}`);
}
if (blockedCount) {
  parts.push(`已阻止${blockedCount}项`);
}
```

```javascript
return `已保存章节 ${result.chapter_id}`;
return `已保存场景 ${result.scene_id}`;
return `已重排 ${sceneIds.length} 个场景`;
return batchMessage("已移入作者回收站", "场景", result, "scene_id");
return batchMessage("已移入作者回收站", "章节", result, "chapter_id");
```

```vue
<PanelShell
  eyebrow="作者工作台"
  title="在运行前整理当前章节"
  description="维护章节与场景的创作源数据，把不再参与当前流程的记录移入作者回收站，并在需要时把场景交接到场景工作台。"
>
```

```vue
<button data-testid="author-refresh-button" @click="refreshAuthorWorkspace">刷新</button>
<button class="ghost" data-testid="author-new-chapter-button" @click="startNewChapter">新建章节</button>
<button class="ghost" data-testid="author-new-scene-button" :disabled="!authorWorkspace.selectedChapterId" @click="startNewScene">
  新建场景
</button>
<div v-if="authorWorkspace.loading" class="empty">正在加载作者工作台...</div>
<span class="muted">{{ chapter.current_phase }} · {{ chapter.active_scene_count }} 个进行中场景</span>
<span class="badge">{{ chapter.trashed_scene_count }} 个已回收场景</span>
{{ authorWorkspace.actionId === "save-chapter" ? "保存中..." : "保存章节" }}
{{ authorWorkspace.actionId.startsWith("save-scene") ? "保存中..." : "保存场景" }}
```

```vue
<button class="danger-button" data-testid="author-trash-selected-chapters-button" ...>
  将所选章节移入回收站
</button>
<button class="danger-button" data-testid="author-trash-selected-scenes-button" ...>
  将所选场景移入回收站
</button>
<button class="ghost" ...>上移</button>
<button class="ghost" ...>下移</button>
<button class="ghost" ...>设为章节结尾</button>
<button class="ghost" ...>在场景工作台打开</button>
<span class="muted">{{ scene.scene_status }} · {{ scene.location || "未设置地点" }}</span>
```

- [ ] **Step 4: Localize the author trash copy and batch notices without changing action ids or payload handling**

```javascript
if (!chapterIds?.length) {
  return "未选择任何章节。";
}
if (!sceneIds?.length) {
  return "未选择任何场景。";
}
return batchMessage("已恢复", "章节", result, "chapter_id");
return batchMessage("已恢复", "场景", result, "scene_id");
return batchMessage("已彻底清理", "章节", result, "chapter_id");
return batchMessage("已彻底清理", "场景", result, "scene_id");
```

```javascript
if (!value) {
  return "未知时间";
}

if (!chapterIds.length || !confirmAction(`确认恢复选中的 ${chapterIds.length} 个章节吗？`)) {
  return;
}
if (!chapterIds.length || !confirmAction(`确认彻底清理选中的 ${chapterIds.length} 个章节吗？`)) {
  return;
}
if (!sceneIds.length || !confirmAction(`确认恢复选中的 ${sceneIds.length} 个场景吗？`)) {
  return;
}
if (!sceneIds.length || !confirmAction(`确认彻底清理选中的 ${sceneIds.length} 个场景吗？`)) {
  return;
}
```

```vue
<PanelShell
  eyebrow="作者回收站"
  title="恢复或彻底清理创作记录"
  description="移入回收站的章节和场景会暂时离开正常创作与运行流程，恢复后才会重新出现；彻底清理仍会遵守下游运行产物约束。"
>
```

```vue
<button @click="refreshTrash">刷新回收站</button>
<div v-if="authorTrash.loading" class="empty">正在加载作者回收站...</div>
<div v-else-if="!hasTrash" class="empty" data-testid="author-trash-empty">作者回收站为空。</div>
<p class="trash-copy">{{ chapter.chapter_goal || "未记录章节目标。" }}</p>
<p class="muted">操作员：{{ chapter.trashed_by || "未知操作员" }}</p>
<span v-if="scene.chapter_trashed" class="badge">章节已回收</span>
<p class="trash-copy">{{ scene.scene_goal || "未记录场景目标。" }}</p>
```

- [ ] **Step 5: Run the backend and frontend unit tests and confirm they now pass**

Run:

```powershell
cd backend
python -m pytest tests/test_author_lifecycle.py -q
cd ..\frontend
npm exec vitest run tests/authorWorkspace.spec.js tests/app.spec.js
```

Expected: both commands `PASS`; the backend file reports zero failures, and Vitest reports the targeted suites green.

- [ ] **Step 6: Commit the copy cleanup before touching docs**

```powershell
git add backend/src/novel_system/services/author_lifecycle.py backend/tests/test_author_lifecycle.py frontend/src/router.js frontend/src/App.vue frontend/src/stores/authorWorkspace.js frontend/src/stores/authorTrash.js frontend/src/views/AuthorWorkspaceView.vue frontend/src/views/AuthorTrashView.vue frontend/tests/authorWorkspace.spec.js frontend/tests/app.spec.js frontend/tests/e2e/author-workspace.spec.js frontend/tests/e2e/author-trash.spec.js
git commit -m "feat(console): unify chinese shell copy"
```

---

### Task 3: Sync README naming and verify the browser flows

**Files:**
- Modify: `README.md`
- Test: `frontend/tests/e2e/author-workspace.spec.js`
- Test: `frontend/tests/e2e/author-trash.spec.js`

- [ ] **Step 1: Replace the README’s shell-view naming with the same Chinese mapping used in the app**

```markdown
- `Author Workspace` -> `作者工作台`
- `Author Trash` -> `作者回收站`
- `Scene Workbench` -> `场景工作台`
- `Review Inbox` -> `审核收件箱`
- `Index Console` -> `索引控制台`
- `Knowledge Console` -> `知识控制台`
- `Interop Center` -> `互操作中心`
```

Replace the old English view names with the mapped Chinese names in every README section that describes seeded browser coverage, manual walkthroughs, read APIs, or the shell view summary so the document matches the running console.

Update these existing README regions explicitly:

- the `2026-04-12 seeded browser E2E result` summary bullet
- the bullet list under `The Playwright lane ... validates four browser paths`
- the `If you want to inspect the seed manually instead` checklist
- the numbered `Runtime Ops Closeout Demo` walkthrough
- the `Runtime Shell Read APIs` bullets
- the final `The shell currently exposes ...` summary

- [ ] **Step 2: Run the targeted Playwright specs and confirm the cleaned Chinese UI passes end-to-end**

Run:

```powershell
cd frontend
npm run test:e2e -- tests/e2e/author-workspace.spec.js tests/e2e/author-trash.spec.js
```

Expected: `PASS` for both specs, including Chinese assertions for `"作者工作台"`, `"已保存章节 CH300"`, `"地点：Clock bridge"`, and the author trash empty state.

- [ ] **Step 3: Run a final frontend build as a syntax guard after the copy-only Vue edits**

Run:

```powershell
cd frontend
npm run build
```

Expected: Vite build completes successfully with no Vue template syntax errors.

- [ ] **Step 4: Commit the README sync and final verification state**

```powershell
git add README.md
git commit -m "docs: sync chinese console naming"
```
