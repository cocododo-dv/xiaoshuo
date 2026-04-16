# Author Trash Smoothness Design

## Summary

This slice improves `AuthorTrashView` runtime smoothness by virtualizing the two remaining long recycle-bin lists: trashed chapters and trashed scenes. The goal is to reduce DOM work during trash-page entry, scrolling, and bulk selection while preserving the existing restore/purge workflow, disabled states, blocking reasons, and end-to-end behavior.

The implementation will reuse the existing `VirtualList` primitive. No backend API, store contract, route, or visual redesign is required.

## Current State

`AuthorTrashView.vue` renders:

- trashed chapters with a plain `v-for`
- trashed scenes with a plain `v-for`
- checkbox selections stored in `selectedChapterIds` and `selectedSceneIds`
- derived restore/purge button state based on the selected IDs and the current store lists

The store already exposes `chapterListVersion` and `sceneListVersion`, and the view already uses those versions to keep selections valid. This avoids the old heavy string-signature watch pattern. The remaining smoothness issue is that large trash payloads still mount every row at once.

## Goals

- Route trashed chapters through `VirtualList`.
- Route trashed scenes through `VirtualList`.
- Keep all current row content, checkbox behavior, disabled states, blocking reason copy, and action buttons.
- Keep selected rows mounted as pinned keys so selection does not feel unstable while scrolling.
- Add runtime tests proving large trash lists render through a virtual window and preserve selected rows after scrolling.
- Extend source and E2E guardrails with stable virtual-list anchors.

## Non-Goals

- Do not add backend pagination or change trash API response shapes.
- Do not change restore/purge semantics.
- Do not redesign the Author Trash layout.
- Do not refactor `AuthorWorkspaceView` or unrelated author runtime flows.
- Do not change the existing confirmation dialogs.

## Approach

Import `VirtualList` in `AuthorTrashView.vue` and replace only the two plain trash-list render blocks.

Chapter list:

- Use `:items="chapters"`.
- Use `item-key="chapter_id"`.
- Use `:viewport-height="560"`.
- Use `:threshold="8"`.
- Use `:pinned-keys="selectedChapterIds"`.
- Expose `test-id="author-trash-chapter-virtual-list"`.
- Preserve each row's existing `author-trash-chapter-row-*` and `author-trash-chapter-select-*` test ids.

Scene list:

- Use `:items="scenes"`.
- Use `item-key="scene_id"`.
- Use `:viewport-height="560"` and `:threshold="8"`.
- Use `:pinned-keys="selectedSceneIds"`.
- Expose `test-id="author-trash-scene-virtual-list"`.
- Preserve each row's existing `author-trash-scene-row-*` and `author-trash-scene-select-*` test ids.

Styling:

- Reuse the existing `.trash-list` class on the `VirtualList` root.
- Add `.trash-list .virtual-list-row` to the shared virtual-row spacing selector so row gaps remain consistent with current cards.
- Avoid layout changes outside the list wrappers.

## State And Side Effects

Selection remains stored in `selectedChapterIds` and `selectedSceneIds`. The current `syncSelections()` flow remains the only cleanup mechanism when the store lists change.

Virtualization must not trigger extra loading, refreshes, or store writes. Checkbox state must survive row unmount/remount through the existing array-backed `v-model` values.

## Testing Strategy

Runtime tests in `frontend/tests/scrollPerformance.spec.js`:

- Mount `AuthorTrashView` with synthetic large chapter and scene trash payloads.
- Assert both lists expose `author-trash-chapter-virtual-list` and `author-trash-scene-virtual-list`.
- Assert mounted row counts are less than the full source arrays.
- Select one chapter and one scene, scroll both virtual lists, and assert the selected rows remain mounted through pinned keys.
- Assert restore/purge buttons still respond to selected restorable/purgeable rows.

Source guard in `frontend/tests/smoothness.spec.js` or `frontend/tests/authorWorkspace.spec.js`:

- Assert `AuthorTrashView.vue` imports `VirtualList`.
- Assert both new virtual-list anchors are present.
- Assert the old full-list `v-for="chapter in chapters"` and `v-for="scene in scenes"` patterns no longer appear.

E2E in `frontend/tests/e2e/author-trash.spec.js`:

- Assert the author trash page shows both virtual-list anchors when trash rows exist.
- Keep the existing flow for moving scenes/chapters to trash, restoring scenes, and purging chapters.

Verification:

- `npm exec vitest run tests/scrollPerformance.spec.js tests/smoothness.spec.js tests/authorWorkspace.spec.js`
- `npx playwright test tests/e2e/author-trash.spec.js`
- `npm test`
- `npm run build`

## Risks And Mitigations

- Risk: Virtual row unmounting could make checked rows feel lost while scrolling.
  Mitigation: Pin selected chapter and scene keys.

- Risk: Checkbox `v-model` could behave differently when rows remount.
  Mitigation: Keep existing array values and add runtime tests that select rows, scroll, and verify selected rows remain checked and action buttons stay enabled.

- Risk: Row spacing could collapse because `VirtualList` wraps rows.
  Mitigation: Extend the existing virtual-row spacing CSS for `.trash-list .virtual-list-row`.

- Risk: Source-string tests can be brittle.
  Mitigation: Keep source assertions narrow and pair them with runtime and E2E checks that prove behavior.

## Acceptance Criteria

- `AuthorTrashView` uses `VirtualList` for both chapter and scene trash lists.
- Existing row test ids and action buttons continue to work.
- Selected trash rows remain mounted after virtual scrolling.
- Author Trash E2E continues to pass.
- Full frontend tests and production build pass.
