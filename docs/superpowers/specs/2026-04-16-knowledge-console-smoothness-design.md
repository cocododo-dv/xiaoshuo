# Knowledge Console Smoothness Design

## Summary

This slice improves `KnowledgeConsoleView` runtime smoothness without changing backend APIs or the visible information architecture. The target is the remaining long `v-for` surfaces in the knowledge page: the catalog list and the expanded detail workflow/history sections. We will reuse the existing `VirtualList` and `ProgressiveList` primitives introduced in the previous frontend smoothness work.

The goal is to reduce DOM work during catalog browsing, detail expansion, and cross-page jumps while keeping filters, selected detail state, workflow actions, and review/index/workbench navigation behavior unchanged.

## Current State

`KnowledgeConsoleView.vue` is now one of the largest remaining frontend views. It renders:

- a catalog of merged active/candidate knowledge rows with a plain `v-for`
- detail workflow action buttons with small `v-for` lists
- multiple expanded history lists for versions, reviews, verify jobs, human review events, target activity groups, review refs, and bundle refs

`LazySection` already prevents some detail JSON from rendering until expanded, but once a history section is expanded, all rows mount at once. On large knowledge/workflow payloads this can cause frame drops during detail selection, section expansion, and page navigation.

## Goals

- Virtualize the knowledge catalog so large filter result sets do not mount every card at once.
- Progressive-render detail workflow/history sections that can grow large but do not need scroll-position virtualization.
- Preserve selected catalog card highlighting and all existing action buttons.
- Keep cross-page navigation intact: knowledge to review, index, and workbench should continue focusing the target item.
- Avoid broad product restructuring, backend pagination work, or visual redesign in this slice.

## Non-Goals

- Do not change API contracts, response shapes, or backend pagination.
- Do not change the Knowledge Console filter semantics.
- Do not redesign the page layout beyond adding list wrappers and stable test anchors.
- Do not refactor unrelated views such as `AuthorTrashView` in this slice.

## Approach

Use `VirtualList` for the catalog because it is a top-level scroll-heavy card list with stable item identity. Use `ProgressiveList` inside detail lazy sections because those sections are independently expandable and mostly read as compact history stacks. This keeps implementation aligned with existing primitives and avoids introducing another rendering model.

The catalog item key will remain `${item.object_type}:${item.lineage_key}`. The selected entry key will be passed as a pinned key so the focused catalog card remains mounted when the virtual window moves.

Detail sections will render through a small helper pattern rather than a new generic component. Each section keeps its current markup, action buttons, empty state, and test ids, but wraps repeated rows in `ProgressiveList` with section-specific `test-id` values.

## Components And Files

Modify:

- `frontend/src/views/KnowledgeConsoleView.vue`
- `frontend/tests/smoothness.spec.js`
- `frontend/tests/scrollPerformance.spec.js`
- `frontend/tests/e2e/knowledge-console.spec.js`

Reuse:

- `frontend/src/components/VirtualList.vue`
- `frontend/src/components/ProgressiveList.vue`
- `frontend/src/components/LazySection.vue`

No new production component is required for this slice.

## Rendering Details

Catalog:

- Import `VirtualList`.
- Replace the catalog `div.knowledge-list > article v-for` with `VirtualList`.
- Use `test-id="knowledge-catalog-virtual-list"`.
- Use `viewport-height` near the existing visual height of the catalog panel.
- Use `threshold` low enough to virtualize medium/large result sets while leaving tiny lists simple.
- Pin `selectedEntryKey` when present.
- Preserve each card's current `data-testid`, focused-card class, detail button, review navigation button, and index navigation button.

Detail history:

- Import `ProgressiveList`.
- Convert these lists when non-empty:
  - versions: `test-id="knowledge-versions-progressive-list"`
  - related reviews: `test-id="knowledge-reviews-progressive-list"`
  - related verify jobs: `test-id="knowledge-jobs-progressive-list"`
  - related human review events: `test-id="knowledge-human-review-progressive-list"`
  - target activity groups: `test-id="knowledge-activity-progressive-list"`
  - review refs: `test-id="knowledge-review-refs-progressive-list"`
  - bundle refs: `test-id="knowledge-bundle-refs-progressive-list"`
- Keep existing empty states and lazy section toggles.
- Keep all action buttons mounted for visible/progressively revealed rows.

Workflow action buttons:

- Leave the small workflow action button groups as plain `v-for`; they are not the primary frame-drop source and are easier to scan inline.

## State And Side Effects

- Keep existing store state unchanged.
- Keep `selectedEntryKey` as the single selection source.
- Do not trigger additional loads from virtualization or progressive reveal.
- Existing `onActivated`/watch behavior should remain unchanged; this slice only reduces render cost.
- No hidden page side effects should be introduced.

## Testing Strategy

Runtime tests in `frontend/tests/scrollPerformance.spec.js`:

- Mount `KnowledgeConsoleView` with a large synthetic catalog and assert only a window of catalog rows mounts.
- Assert the selected catalog row stays mounted through `pinnedKeys` after virtual scroll.
- Mount a synthetic detail payload with large workflow/history arrays and assert each converted detail section exposes its `ProgressiveList` anchor and initially renders fewer rows than the full array.
- Assert representative action buttons remain available for visible rows.

Source tests in `frontend/tests/smoothness.spec.js`:

- Assert `KnowledgeConsoleView.vue` imports `VirtualList` and `ProgressiveList`.
- Assert all new `knowledge-*virtual-list` / `knowledge-*progressive-list` anchors exist.
- Assert the old catalog full-list pattern no longer appears.

E2E in `frontend/tests/e2e/knowledge-console.spec.js`:

- Extend the existing knowledge flow to assert the catalog virtual list is visible after loading/filtering.
- After opening a detail record, expand review refs and bundle refs and assert their progressive-list anchors or existing empty states appear.
- Keep existing navigation assertions to review inbox and workbench.

Verification:

- `npm exec vitest run tests/scrollPerformance.spec.js tests/smoothness.spec.js`
- `npx playwright test tests/e2e/knowledge-console.spec.js`
- `npm test`
- `npm run build`

## Risks And Mitigations

- Risk: Virtualized catalog could unmount the selected card during scrolling.
  Mitigation: Use `selectedEntryKey` as a pinned key and add a runtime regression.

- Risk: Detail progressive lists could hide action buttons that tests expect immediately.
  Mitigation: Keep initial render count high enough for common detail rows and update tests to target visible rows or explicitly reveal more when needed.

- Risk: Lazy section empty states can be confused with loading states in E2E.
  Mitigation: Prefer section-scoped assertions and allow either progressive-list anchor or stable empty state where backend data may vary.

- Risk: `KnowledgeConsoleView.vue` grows harder to maintain.
  Mitigation: Keep this slice focused and reuse existing primitives; if the view remains difficult after this pass, extract detail-list row components in a separate cleanup.

## Acceptance Criteria

- Knowledge catalog uses `VirtualList` and exposes `knowledge-catalog-virtual-list`.
- Detail workflow/history repeated sections use `ProgressiveList` anchors listed above.
- Existing knowledge creation, approval, review navigation, index/workbench navigation, and bundle provenance E2E path continue to pass.
- Runtime tests prove windowing/progressive rendering instead of relying only on source string assertions.
- Full frontend tests and production build pass.
