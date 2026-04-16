# Index Console Timeline Virtualization Design

> Date: 2026-04-16
> Target slice: reduce in-page scroll jank in `Index Console` by virtualizing the remaining flat event timelines in `system_runtime` and `operator_action`.

---

## 1. Background

The 2026-04-15 scroll and expand performance slice already improved the heaviest read surfaces:

- `Review Inbox` review cards now use `VirtualList`
- `HumanReviewDrawer` and target-group inner activity items now use `ProgressiveList`
- `Index Console` jobs, recovery timeline, and target-group summaries now use `VirtualList`
- `Author Workspace` chapter and scene lists now use `VirtualList`

The largest remaining gap inside the current branch is still in `Index Console`:

- `system_runtime` and `operator_action` still render their full event collections with plain `ul/li`
- these sections can grow long and carry multiple action buttons per row
- unlike the already-virtualized recovery timeline, they still keep every row live during scroll

This slice narrows the follow-up work to those two remaining flat timelines so we can keep the change small and targeted.

---

## 2. Goals

1. Reduce scroll-time dropped frames in the `system_runtime` and `operator_action` sections.
2. Reuse the existing shared `VirtualList` primitive instead of adding a new rendering path.
3. Preserve current focus behavior, jump actions, pagination, and row-level test hooks.
4. Keep the change local to `Index Console` plus regression coverage.

---

## 3. Non-Goals

- No backend API or store loading protocol changes.
- No redesign of the existing `ActivitySectionCard` interaction model.
- No changes to `Review Inbox`, `Author Workspace`, `Knowledge Console`, or `Author Trash`.
- No nested virtualization inside target-group activity items.
- No replacement of the current `ProgressiveList` strategy for expand-heavy sections.

---

## 4. Recommended Approach

Use the same pattern already proven in `recovery_timeline`:

- replace the `system_runtime` and `operator_action` `ul/li` blocks with `VirtualList`
- keep their current row content and button actions intact
- derive stable row keys from the existing `activityItemKey(sectionId, item)` helper
- keep focused items mounted with section-specific `pinnedKeys`
- add explicit section-level test ids so runtime and E2E tests can scope assertions without relying on incidental DOM ancestry

This is preferred over `ProgressiveList` because the primary remaining complaint is scroll cost, not expand-burst cost. It is also preferred over CSS-only tuning because these surfaces still pay the DOM-count cost of rendering every row.

---

## 5. Component and View Changes

### 5.1 `IndexConsoleView.vue`

`system_runtime` section:

- replace the current `ul.receipt-list > li` rendering with `VirtualList`
- use `activityItemKey("system_runtime", item)` as the item key
- keep `data-activity-key`, `focused-card`, and the existing target action buttons on each rendered row
- set a conservative threshold and viewport height consistent with other console surfaces

`operator_action` section:

- replace the current `ul.receipt-list > li` rendering with `VirtualList`
- use `activityItemKey("operator_action", item)` as the item key
- preserve all current action buttons and `focused-card` behavior

Shared view behavior:

- add `pinnedSystemRuntimeKeys` and `pinnedOperatorActionKeys`
- pin the currently focused event when shell focus points to `system_activity` or `operator_action`
- add explicit section test ids for the two timeline cards so tests can scope queries semantically

### 5.2 `ActivitySectionCard.vue`

- continue to act as the section shell
- accept explicit section test ids where needed
- do not take on virtualization logic itself

---

## 6. Focus and Interaction Constraints

This slice must preserve the current operator workflow.

Required behavior:

- when shell focus points at a `system_activity` row, that row remains mounted through `pinnedKeys`
- when shell focus points at an `operator_action` row, that row remains mounted through `pinnedKeys`
- the existing `data-activity-key` values remain available on rendered rows
- current target action buttons still dispatch `jumpToTarget(withIndexFocusTarget(...))` exactly as before
- section pagination and empty states remain unchanged

This slice does not introduce any new expand/collapse behavior. It only changes how the list body is rendered once a section is open.

---

## 7. Styling Expectations

No new rendering primitive is required.

Expected styling behavior:

- reuse the existing `.virtual-list`, `.virtual-list-spacer`, and `.virtual-list-row` hooks
- keep row cards visually aligned with the existing `receipt-list-item` look
- avoid applying containment to the measured wrapper in a way that can poison persisted row heights

---

## 8. Testing and Verification

### 8.1 Runtime regression coverage

Extend `frontend/tests/scrollPerformance.spec.js` to prove:

- `system_runtime` mounts through `VirtualList` at runtime
- `operator_action` mounts through `VirtualList` at runtime
- each section renders fewer rows than the full backing collection when the list is long
- scrolling the virtual container still keeps a focused row mounted through `pinnedKeys`
- action buttons remain present on rendered rows after virtualization

### 8.2 Source regression coverage

Extend `frontend/tests/smoothness.spec.js` or adjacent targeted source checks to prove:

- `IndexConsoleView.vue` routes both sections through `VirtualList`
- explicit section test ids exist for the new runtime/E2E anchors

These source checks are secondary. Runtime coverage is the primary protection for this slice.

### 8.3 End-to-end coverage

Extend `frontend/tests/e2e/smoothness-navigation.spec.js` to prove:

- opening `system_runtime` shows a virtualized list surface
- opening `operator_action` shows a virtualized list surface
- the page remains interactive after expanding and navigating between the heavy review/index/author surfaces

### 8.4 Verification commands

Required commands:

- `npm exec vitest run tests/scrollPerformance.spec.js tests/smoothness.spec.js`
- `npx playwright test tests/e2e/smoothness-navigation.spec.js`
- `npm test`
- `npm run build`

Expected result: all commands pass with the new timeline virtualization in place.

---

## 9. Scope Check

This design is intentionally narrow:

- one existing shared list primitive
- one existing view as the only production integration target
- existing test files extended instead of adding a large new test surface

That keeps the next implementation plan small enough for a single focused execution slice.
