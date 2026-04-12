# P2 Runtime Shell Closeout and Author Workspace v1 Implementation Plan

**Status:** implemented

> Date: 2026-04-12
> Scope: historical runtime-shell closeout plus delivery of a dedicated author source-of-truth workspace.

---

## File Structure

- `docs/superpowers/plans/*.md`
  Historical plan closeout records for the 2026-04-08 through 2026-04-12 slices.
- `docs/superpowers/specs/2026-04-12-author-workspace-design.md`
  Canonical design for the author workspace split.
- `backend/src/novel_system/api/routes/chapters.py`
  Chapter list/detail/reorder authoring reads and writes.
- `backend/src/novel_system/api/routes/scenes.py`
  Scene upsert validation and append-to-end behavior.
- `backend/tests/test_author_workspace.py`
  Backend author workspace contract coverage.
- `frontend/src/lib/api.js`
  Author workspace API helpers.
- `frontend/src/stores/authorWorkspace.js`
  Author workspace state and mutations.
- `frontend/src/views/AuthorWorkspaceView.vue`
  Dedicated authoring UI and workbench handoff.
- `frontend/src/router.js`
  Top-level nav registration and target routing.
- `frontend/tests/authorWorkspace.spec.js`
  Frontend unit/store coverage.
- `frontend/tests/e2e/author-workspace.spec.js`
  Seeded browser coverage for authoring and handoff.

---

### Task 1: Close out historical plans

- [x] Add one-line status headers to the 2026-04-08 through 2026-04-12 historical plan files.
- [x] Check off only steps reflected by current code, tests, or repository docs.
- [x] Replace historical publication-only checklist items with supersede notes where later closeout slices absorbed them.
- [x] Add the new author-workspace design/plan pair after the historical closeout pass.

### Task 2: Implement backend author-workspace reads and writes

- [x] Add `GET /api/v1/chapters` with chapter author fields plus light runtime summary.
- [x] Add `GET /api/v1/chapters/{chapter_id}/author-workspace` with ordered chapter scenes and read-only runtime context.
- [x] Keep `POST /api/v1/chapters` and `POST /api/v1/scenes` as the write surface.
- [x] Support append-to-end scene creation when `scene_seq` is omitted.
- [x] Reject scene writes that reference missing chapters.
- [x] Add `POST /api/v1/chapters/{chapter_id}/scene-order` to rewrite contiguous `scene_seq` values and normalize a single `is_chapter_last`.

### Task 3: Implement the dedicated Author Workspace shell

- [x] Add a new top-level `Author Workspace` nav entry and dedicated view.
- [x] Add an author-workspace store for chapter list/detail loading, chapter save, scene save, and reorder save.
- [x] Build the view around a chapter list, chapter form, and ordered scene editor.
- [x] Support explicit move-up, move-down, and mark-last interactions without drag-and-drop.
- [x] Provide `Open in Scene Workbench` handoff for the selected scene.

### Task 4: Verify the slice

- [x] Run targeted backend author-workspace tests.
- [x] Run targeted frontend author-workspace tests.
- [x] Add a new Playwright author-workspace spec covering authoring plus workbench handoff.
- [x] Re-run repository-level verification before handoff.
