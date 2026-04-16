# Scene Workbench Progressive Smoothness Design

## Summary

Improve Scene Workbench page-internal scrolling by progressively rendering the run preflight groups and pending staged backfill controls. These sections currently mount every item with direct `v-for` loops as soon as a scene loads. The change keeps all behavior and controls intact while reducing initial DOM work for large preflight/backfill payloads.

## Goals

- Reduce first-render and scroll work when `run_preflight` contains many blocking, warning, or context items.
- Reduce DOM pressure when a chapter has many pending staged backfill items.
- Preserve all existing Scene Workbench behavior: run-button gating, preflight text, backfill strategy select, execute button, manual hold controls, receipts, and E2E flows.
- Use the shared `ProgressiveList` primitive already used by Knowledge Console, Review Inbox, and Target Activity cards.
- Add tests that prevent these heavy Scene Workbench sections from regressing back to full-list rendering.

## Non-Goals

- Do not change backend APIs, store payload shapes, or pagination.
- Do not virtualize the entire Scene Workbench page.
- Do not alter Attempt Timeline, Human Review Drawer, Bundle Provenance, or the Interop/Knowledge views in this slice.
- Do not change product copy or visual layout beyond preserving spacing inside progressive list wrappers.

## Architecture

`SceneWorkbenchView.vue` remains the only production file that changes behavior. It imports `ProgressiveList` and replaces four direct list renderers:

- `runPreflight.blocking_items`
- `runPreflight.warning_items`
- `runPreflight.context_items`
- `pendingStagedBackfillItems`

Each group keeps its existing section wrapper and row body. Only the rendering driver changes from direct `v-for` to a scoped slot receiving `items` from `ProgressiveList`.

Preflight groups should use small batches because they are mostly static text:

- `:initial-count="6"`
- `:batch-size="6"`
- `:threshold="6"`

Backfill controls should use smaller batches because each row includes a select and button:

- `:initial-count="4"`
- `:batch-size="4"`
- `:threshold="4"`

## Component Contract

Preflight lists expose stable anchors:

- `scene-run-preflight-blocking-progressive-list`
- `scene-run-preflight-warning-progressive-list`
- `scene-run-preflight-context-progressive-list`

Backfill exposes:

- `chapter-backfill-progressive-list`

Rows keep the existing anchors:

- `scene-run-preflight-item-${item.code}`
- `chapter-backfill-item-${item.stage_id}`
- `chapter-backfill-strategy-${item.stage_id}`
- `chapter-backfill-run-${item.stage_id}`

## Styling

Reuse existing spacing wherever possible. If wrapping backfill rows in `ProgressiveList` changes spacing, extend the local list shell with minimal CSS so `.chapter-backfill-list .progressive-list` keeps the same vertical rhythm. Do not introduce new visual treatment.

## Testing

Add a runtime test in `frontend/tests/scrollPerformance.spec.js` that mounts `SceneWorkbenchView` with:

- more than six blocking preflight items
- more than six warning preflight items
- more than six context preflight items
- more than four pending staged backfill items

The test verifies:

- all four progressive-list anchors exist
- initial rendered item counts are below source array sizes
- the first visible preflight item keeps its existing text/test id
- the first visible backfill select and run button remain usable

Add source guardrails in `frontend/tests/smoothness.spec.js` or the existing Scene Workbench source tests to verify:

- `SceneWorkbenchView.vue` imports `ProgressiveList`
- all four progressive-list anchors exist
- the direct `v-for` expressions for the four heavy lists are removed

Extend existing E2E tests only where useful:

- `scene-preflight.spec.js` should still find preflight blocker/warning text.
- `chapter-ops.spec.js` should still find the first backfill item, select a strategy, and run it.

If E2E data only includes a small list, the anchor assertion is enough for lifecycle coverage; the large-list progressive branch is covered by Vitest.

## Verification

Run:

```bash
npm exec vitest run tests/scrollPerformance.spec.js tests/smoothness.spec.js tests/sceneWorkbenchPreflight.spec.js tests/workbenchChapterRuntime.spec.js
npx playwright test tests/e2e/scene-preflight.spec.js tests/e2e/chapter-ops.spec.js
npm test
npm run build
```

Expected result: all commands pass.

## Risks

- `ProgressiveList` hides later rows until the user expands the list. This is acceptable for long lists but must not hide the first actionable backfill row used by current E2E flows.
- If operators need to act on many staged backfill rows quickly, they will need to click "load more" to reveal later rows. This trades a small interaction cost for smoother initial rendering.
- Backfill rows include form controls; the implementation must keep `selectedStrategies` keyed by `stage_id` so hidden/revealed rows preserve their selected strategy.
