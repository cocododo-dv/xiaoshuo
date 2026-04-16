# Interop Comparison Smoothness Design

## Summary

Improve page-internal scroll smoothness in the Interop Center by virtualizing the `source_ref_comparisons` result list. This is a focused runtime-rendering change: keep preview/import/export/replay behavior and comparison card content unchanged, but avoid mounting every comparison card at once when the backend returns a large comparison set.

## Goals

- Reduce DOM work when Interop preview/export/replay produces many source comparison cards.
- Preserve existing Interop flows, target jump buttons, `data-testid` anchors, and comparison copy.
- Use the shared `VirtualList` primitive already used by other heavy frontend surfaces.
- Add regression tests that prove large comparison sets render through the virtual list and do not fall back to full-list `v-for`.

## Non-Goals

- Do not change backend APIs or store payload shapes.
- Do not redesign the Interop Center layout or visual hierarchy.
- Do not change YAML preview/import/export/replay semantics.
- Do not optimize SceneWorkbench preflight or backfill lists in this slice.

## Architecture

`InteropCenterView.vue` remains the owner of presentation-only rendering. The store continues to expose `activeSourceComparisons` as a plain array. The view imports `VirtualList` and replaces the current full `v-for` wrapper with a virtualized comparison list.

The list uses a stable derived key:

```js
`${item.object_type}:${item.lineage_key}:${item.source_ref_key}`
```

This matches the existing row key and keeps the rendered cards addressable with the current `interop-source-comparison-${object_type}-${lineage_key}` test id. Small comparison sets remain effectively unchanged by using a threshold, while large sets render only the visible window.

## Component Contract

The Interop comparison virtual list should use:

- `class="comparison-list"`
- `:items="activeSourceComparisons"`
- `:item-key="comparisonKey"`
- `:estimated-item-height="260"`
- `:threshold="8"`
- `:viewport-height="640"`
- `test-id="interop-comparison-virtual-list"`

Each rendered card keeps:

- `class="paper mini comparison-card"`
- existing diff fields for version/text/source/active rows
- existing source/active text blocks
- existing optional target button and `openComparisonTarget(item)` behavior
- existing `data-testid="interop-source-comparison-..."`

## Styling

Extend the shared virtual-row spacing selector with `.comparison-list .virtual-list-row` so Interop comparison cards keep the same vertical rhythm after virtualization.

No new visual theme is introduced. The goal is smoother runtime rendering, not a visual redesign.

## Testing

Add a runtime test in `frontend/tests/scrollPerformance.spec.js` that mounts `InteropCenterView` with a large `activeSourceComparisons` array and verifies:

- `interop-comparison-virtual-list` exists and has the shared `virtual-list` class.
- `maxHeight` is `640px`.
- rendered comparison cards are fewer than the source array when over threshold.
- a visible target button still opens through the shell router flow.

Add a source guard in `frontend/tests/smoothness.spec.js` that verifies:

- `InteropCenterView.vue` imports `VirtualList`.
- the comparison list exposes `interop-comparison-virtual-list`.
- the source no longer contains `v-for="item in activeSourceComparisons"`.
- `.comparison-list .virtual-list-row` is present in `app.css`.

Update `frontend/tests/e2e/interop-center.spec.js` to assert the new virtual-list anchor is visible after preview/export results load, while preserving the existing lifecycle assertions.

## Verification

Run:

```bash
npm exec vitest run tests/scrollPerformance.spec.js tests/smoothness.spec.js tests/bundleProvenance.spec.js
npx playwright test tests/e2e/interop-center.spec.js
npm test
npm run build
```

Expected result: all commands pass.

## Risks

- E2E uses a small comparison set, so it validates lifecycle and anchors but not the virtualized branch. The runtime Vitest case covers the large-list branch.
- If comparison text content is much taller than `260px`, `VirtualList` may adjust measured heights after first paint. This can cause small scroll-position corrections but should not break functionality.
- The existing test id omits `source_ref_key`, so duplicate `object_type + lineage_key` pairs would share an anchor. This is pre-existing behavior and should not be changed in this performance slice.
