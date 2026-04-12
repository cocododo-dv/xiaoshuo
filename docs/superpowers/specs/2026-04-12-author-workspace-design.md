# Author Workspace v1 Design

> Date: 2026-04-12
> Target slice: close the runtime-shell milestone and add a separate author source-of-truth workspace for chapter and scene editing.

---

## 1. Background

The current runtime shell is already closed as an operator-facing milestone:

- `Scene Workbench` is the runtime execution and receipt surface.
- `Review Inbox`, `Knowledge Console`, `Index Console`, and `Interop Center` already cover the review, knowledge, indexing, and replay loops.
- the remaining authoring gap is that `chapter_goals` and `scene_cards` still lack a dedicated source-of-truth editing view.

That gap now matters more than another runtime-shell expansion. Authors need a place to create and edit chapter goals, update scene cards, and reorder chapter-local scene intent without mixing those source-of-truth edits into the runtime controls.

---

## 2. Goals

1. Add a dedicated `Author Workspace` view separate from `Scene Workbench`.
2. Expose ordered chapter summaries and chapter-scoped author detail reads from the backend.
3. Preserve the existing `POST /api/v1/chapters` and `POST /api/v1/scenes` upsert surfaces while making scene creation append to the end when `scene_seq` is omitted.
4. Add a chapter-scoped reorder endpoint that becomes the single authority for contiguous `scene_seq` values and the one `is_chapter_last` flag.
5. Keep handoff into `Scene Workbench` easy so runtime execution continues to flow through the existing operator surface.

---

## 3. Non-Goals

- No delete endpoints for chapters or scenes in v1.
- No schema migrations or new tables.
- No runtime execution, recovery, review, or index controls inside the authoring view.
- No drag-and-drop reorder, bulk import, or rollback tooling.
- No change to existing runtime/review/index/knowledge/interop response contracts outside the new author-facing reads.

---

## 4. Backend Contract

### 4.1 `GET /api/v1/chapters`

This endpoint returns chapter summaries ordered by `chapter_id`.

Each item includes:

- chapter author fields from `chapter_goals`
- `current_phase`
- `chapter_passed_scene_count`
- `chapter_backfill_pending_count`

This read is intentionally light-weight: it powers the sidebar and chapter selection state without forcing a full chapter-scene aggregate load on every navigation click.

### 4.2 `GET /api/v1/chapters/{chapter_id}/author-workspace`

This endpoint returns the author editing payload for one chapter:

- `chapter`
- `chapter_state`
- `scenes`

`scenes` are ordered by `scene_seq` and include the author-editable scene card fields plus light runtime context:

- `scene_status`
- `current_bundle_id`
- `current_final_scene_row_id`

The runtime fields are read-only context for author handoff; they are not part of the scene upsert payload.

### 4.3 Existing upserts stay authoritative

`POST /api/v1/chapters` remains the chapter create/update surface.

`POST /api/v1/scenes` remains the scene create/update surface with two added rules:

- reject writes when `chapter_id` does not resolve to an existing chapter
- when creating a new scene and `scene_seq` is omitted, append the scene to the end of that chapter

When updating an existing scene without `scene_seq`, preserve the current ordering.

### 4.4 `POST /api/v1/chapters/{chapter_id}/scene-order`

This endpoint accepts:

- ordered `scene_ids`
- `last_scene_id`

Behavior:

- the payload must contain every scene in the chapter exactly once
- scene ids must all belong to the target chapter
- the backend rewrites contiguous `scene_seq` values
- the backend normalizes `is_chapter_last` so exactly one scene in the chapter remains marked last

The reorder endpoint is the only authoring feature allowed to rewrite `scene_seq`.

### 4.5 Compatibility expectations

The new author workspace read endpoints do not change existing runtime shell endpoints. `Scene Workbench` and other consoles continue to work exactly as before, and they now consume author-edited source-of-truth data rather than taking over those edits themselves.

---

## 5. Frontend Contract

### 5.1 New top-level view

Add a new top-level nav entry named `Author Workspace`.

The view is intentionally separate from `Scene Workbench` so the product keeps a clear distinction between:

- authoring source-of-truth edits
- runtime execution and operational follow-up

### 5.2 Store responsibilities

The author workspace store owns:

- chapter list loading
- selected chapter loading
- chapter save
- scene save
- chapter-scoped reorder save
- transient loading, action, and error state

The store talks only to the new author read endpoints plus the existing chapter/scene upsert endpoints and the new reorder endpoint. It must not call runtime mutation endpoints directly.

### 5.3 View composition

The view is composed from three focused areas:

- chapter list/sidebar
- chapter form
- ordered scene list/editor

Scene interactions are explicit and low-friction:

- move up
- move down
- mark as chapter last
- open selected scene in `Scene Workbench`

The handoff action keeps runtime work discoverable without duplicating runtime buttons into the authoring surface.

---

## 6. Testing and Verification

Backend coverage must prove:

- chapter list/detail payload shape and ordering
- append-to-end scene creation when `scene_seq` is omitted
- missing-chapter scene writes fail explicitly
- reorder is chapter-scoped, contiguous, and single-last-scene

Frontend coverage must prove:

- nav registration and dedicated store/view wiring
- chapter save, scene save, reorder, and chapter-last interactions
- no runtime mutation leakage from the authoring store
- handoff to `Scene Workbench` preserves scene focus behavior

Seeded browser coverage must prove the full authoring path:

- create a chapter
- create/edit scenes
- reorder and mark chapter last
- open the selected scene in `Scene Workbench`
- confirm the updated source-of-truth is visible there

Repository verification remains:

- `powershell -ExecutionPolicy Bypass -File scripts/verify_windows.ps1`
- `cd frontend && npm run test:e2e`
- `wsl -d Ubuntu-24.04 bash -lc "cd /mnt/e/codex/xiaoshuo/codex && bash scripts/verify_wsl_strict.sh"`
