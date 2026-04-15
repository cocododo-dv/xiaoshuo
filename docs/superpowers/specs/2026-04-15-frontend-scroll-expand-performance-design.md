# Frontend Scroll and Expand Performance Design

> Date: 2026-04-15
> Target slice: reduce in-page scroll and expand jank across `Review Inbox`, `Index Console`, and `Author Workspace` after the desktop light keep-alive shell rollout.

---

## 1. Background

The 2026-04-15 shell smoothness slice already improved page-to-page navigation:

- the desktop shell now keeps visited views alive instead of remounting every page swap
- hidden views stop running focus sync, smooth scrolling, and heavy reload side effects
- store-side version markers replaced several string-join watch signatures

That work reduced navigation churn, but it did not fully address the next bottleneck:

- opening a heavy section can still mount a large block of DOM in one burst
- long card and timeline lists still keep too many items live during scroll
- expanded JSON, action history, and timeline detail blocks still participate in layout and paint more than necessary

The remaining user-facing complaint is therefore page-internal jank rather than route transitions. The next slice should optimize the rendering rhythm inside already-open views without changing backend contracts or the existing light keep-alive behavior.

---

## 2. Goals

1. Reduce visible dropped frames when scrolling long lists in `Review Inbox`, `Index Console`, and `Author Workspace`.
2. Reduce the one-frame or multi-frame hitch that happens when expanding heavy detail blocks or activity sections.
3. Reuse a shared frontend pattern instead of adding one-off performance logic to each page.
4. Preserve current focus targeting, jump-to-target behavior, action buttons, pagination, and test selectors.

---

## 3. Non-Goals

- No backend API changes.
- No route or shell lifecycle redesign beyond the existing light keep-alive slice.
- No full-app virtualization for every surface.
- No drag-and-drop or interaction redesign for authoring flows.
- No removal of current explicit expand/collapse controls.

---

## 4. Design Summary

This slice uses a mixed strategy instead of a single global virtualization layer:

- `ProgressiveList` handles heavy expand paths by rendering an initial batch immediately and then appending additional items over later animation frames.
- `VirtualList` handles flat, scroll-heavy collections by rendering only the visible window plus overscan.
- complex editing surfaces that depend on stable DOM position keep real rendering and only adopt progressive detail mounting where needed.

This combination is preferred over an all-virtualized design because the current shell has several focus, jump, and action flows that assume stable target availability. The mixed design captures most of the scroll benefit while limiting focus regressions.

---

## 5. Shared Rendering Primitives

### 5.1 `ProgressiveList`

`ProgressiveList` is a shared component or composable-backed component used when a section is opened and many items would otherwise mount at once.

Contract:

- accepts `items`
- accepts an `initialCount`
- accepts a `batchSize`
- accepts an `enabled` flag
- exposes the currently rendered slice to a slot

Behavior:

- when disabled, render the full collection immediately
- when enabled, render only the first batch immediately
- schedule additional batches with `requestAnimationFrame`
- reset batching when the source items change substantially or the section collapses

Primary targets in this slice:

- `HumanReviewDrawer` item list
- expanded action history inside human review cards
- expanded heavy detail lists inside `Index Console` sections when inner virtualization would be too fragile

### 5.2 `VirtualList`

`VirtualList` is a shared list container for flat, scroll-heavy collections.

Contract:

- accepts `items`
- accepts `itemKey`
- accepts an estimated item height
- accepts `overscan`
- accepts optional `pinnedKeys`
- accepts optional `scrollToKey`
- renders items through a slot

Behavior:

- render only the visible range plus overscan
- maintain top and bottom spacer sizes so scroll height remains correct
- measure rendered row heights and feed the measurements back into the range calculation
- keep pinned items mounted even when they would otherwise fall outside the current window

This component should support variable-height rows. The current shell contains cards with badges, action bars, optional detail blocks, and selection state, so a fixed-height virtualizer would be too brittle.

---

## 6. Surface Integration

### 6.1 `Review Inbox`

`ReviewCard` list:

- migrate the `review-list` container to `VirtualList`
- use `review_id` as the stable key
- keep the currently focused review in `pinnedKeys`
- preserve existing `ReviewCard` internals and `data-testid` values

`HumanReviewDrawer`:

- keep the drawer as the interaction shell
- render the event list through `ProgressiveList`
- keep detail and history toggles explicit
- when history or details are expanded, progressively mount the nested heavy content instead of rendering all nested DOM at once

Rationale:

- review cards are the cleanest flat list in the app and should benefit immediately from virtualization
- human review items have richer nested state, so progressive mounting is safer than deep virtualization on the first pass

### 6.2 `Index Console`

Jobs:

- migrate the `job-table` list to `VirtualList`
- use `job_id` as the key
- pin the focused job when shell focus points to `verify_job` or `reindex_job`

Timeline sections:

- each expanded `receipt-list` inside `recovery_timeline`, `system_runtime`, and `operator_action` moves to `VirtualList`
- use `activity_key` when available and fall back to the existing helper-generated key
- preserve current `data-activity-key` attributes so focus scrolling and tests keep working

Target group summaries:

- migrate the outer `target-group-list` to `VirtualList`
- keep the focused target group pinned

Target group activity items:

- do not introduce nested full virtualization immediately inside every expanded group
- first apply `ProgressiveList` to the group's inner activity items
- allow a later follow-up to add second-level virtualization only if evidence shows inner groups remain a bottleneck after this slice

Rationale:

- the console contains the densest long-form read surfaces in the shell
- the outer lists are strong virtualization candidates
- nested target-group content is a higher-risk path because it intersects with focus-linked scrolling and on-demand group loading

### 6.3 `Author Workspace`

Chapter list:

- migrate the left-side chapter summary list to `VirtualList`
- use `chapter_id` as the key
- pin the currently selected chapter

Scene list:

- migrate the chapter scene list to `VirtualList`
- use `scene_id` as the key
- pin the selected scene

Editing surfaces:

- keep the chapter form and scene form as normal DOM
- do not virtualize the active editing pane
- keep reorder buttons, selection checkboxes, and open-in-workbench actions unchanged

Rationale:

- the author lists can grow long, but the actual editing controls need stable DOM for input focus and predictable button behavior
- list virtualization provides the scroll win while leaving edit forms simple and reliable

---

## 7. Interaction Constraints

This slice must preserve the current operator model.

### 7.1 Focus and jump targets

The shell already supports cross-view jump targets and in-view focused cards. Virtualization must not break that model.

Required behavior:

- focused or target-linked items remain mounted through `pinnedKeys`
- `scrollToKey` resolves before a focus-clearing path decides the target is missing
- existing `data-testid` and `data-activity-key` hooks remain available on rendered items

### 7.2 Expand behavior

Expand actions should feel immediate even when the full content is large.

Required behavior:

- the first visible batch appears in the same interaction cycle as the expand click
- later batches append without resetting the section's scroll position
- collapsing a section cancels any remaining progressive batch work

### 7.3 Small-list fallback

Virtualization is not mandatory for small lists.

Required behavior:

- below a threshold, `VirtualList` falls back to direct rendering
- the threshold should be configurable and conservative
- fallback mode must preserve the same slot structure so callers do not need separate templates

### 7.4 Overscan and stability

The first implementation should bias toward stability instead of minimal DOM.

Required behavior:

- overscan is intentionally larger than the bare minimum
- measured row heights update the model gradually to avoid visible scroll jumps
- if a surface proves too unstable under virtualization, that surface can fall back to progressive rendering only without invalidating the overall design

---

## 8. Styling and Layout Expectations

This slice should pair rendering changes with layout containment where it is safe.

Expected style support:

- list rows and heavy cards can use containment hints where they do not interfere with sticky headers or focus styles
- virtualized list containers should have explicit scroll ownership when needed rather than relying on accidental overflow behavior
- expanded heavy details should avoid triggering full-list relayout when only one card changes

This is an implementation detail rather than a separate product feature. The user-facing goal is simply smoother scroll and expand behavior.

---

## 9. Testing and Verification

Unit coverage must prove:

- `ProgressiveList` renders an initial batch, schedules later batches, and resets correctly on collapse or item replacement
- `VirtualList` computes ranges correctly, honors overscan, keeps `pinnedKeys` mounted, and supports `scrollToKey`
- small-list fallback renders all items directly

Frontend regression coverage must prove:

- `Review Inbox` review cards and human review items enter the new rendering paths without breaking action buttons or focus clearing
- `Index Console` jobs, timelines, and target group summaries preserve key hooks such as `data-activity-key`
- `Author Workspace` chapter and scene selection continue to work while their lists are virtualized

E2E coverage must prove:

- long-list scrolling remains interactive in `Review Inbox`, `Index Console`, and `Author Workspace`
- expanding payloads, history, or timeline sections does not block the UI long enough to break scripted interaction
- focus-linked jumps still land on visible mounted items

Repository verification for the implementation phase should continue to include:

- `cd frontend && npm test`
- `cd frontend && npm run build`
- `cd frontend && npx playwright test tests/e2e/smoothness-navigation.spec.js`

Additional focused tests for the new list primitives should be added to the frontend test suite during implementation.

---

## 10. Implementation Boundaries

The implementation plan for this design should be staged:

1. add shared `ProgressiveList` and `VirtualList` primitives with focused unit coverage
2. integrate `Review Inbox` and `Index Console` flat lists first
3. integrate `Author Workspace` lists
4. add any targeted containment styles and regression updates
5. verify with the existing smoothness checks plus new long-list regression coverage

This staged order keeps the highest-value read surfaces first while isolating risk before the authoring interactions are touched.
