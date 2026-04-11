# Review / Index Query Closure Design

> Date: 2026-04-11
> Target slice: close the next retrieval gap in `Review Inbox` and `Index Console` by moving view filters from frontend-only shaping to backend-supported query parameters.

---

## 1. Background

The current shell is now functionally closed for the major P2 operator loops:

- `Scene Workbench` can run seeded scene flows end to end.
- `Review Inbox` can approve, release, and act on human review follow-up items.
- `Index Console` can retry verify jobs, run due promotions, and run recovery sweep.
- `Knowledge Console` can now complete `approve -> verify -> release` inside its own detail drawer.
- `Interop Center` can preview, import, export, and replay worksheet bundles.

However, `Review Inbox` and `Index Console` still rely on broad list reads and then shape data locally in the frontend:

- `Review Inbox` loads all `review_items` and all `human_review_events`, then filters or prioritizes in client state.
- `Index Console` loads all alias scopes, all jobs, and the full runtime ledger payload, then derives focused subsets client-side.

This is already workable for the seeded demo, but it diverges from the repository's intended P2 direction: the frontend should not depend on reading whole operational tables and then simulating server-side filtering in the browser.

This slice closes that gap without introducing pagination or breaking the existing endpoint layout.

---

## 2. Goals

1. Add backend-supported query filters to the existing `Review Inbox` and `Index Console` list endpoints.
2. Add matching frontend filter controls and store state so those views load narrowed result sets directly from the backend.
3. Make `runtime-ledger` filtering authoritative on the server, including recomputation of `target_activity_groups` from the filtered timeline inputs.
4. Preserve current operator workflows, response shapes, and seeded E2E coverage while removing the need for broad unfiltered reads during normal view use.

---

## 3. Non-Goals

- No pagination, cursoring, or `limit` support in this slice.
- No new parallel endpoints for review, jobs, or ledger data.
- No schema migrations.
- No new workflow actions.
- No changes to `Knowledge Console` workflow aggregation beyond any read-only compatibility updates forced by shared helpers.
- No splitting of `runtime-ledger` into separate `recovery`, `system`, `operator`, or `target-activity` APIs.

---

## 4. Approaches Considered

### Approach A: Minimal parameter pass-through

Add query params to the current backend endpoints and wire simple frontend controls to them, but treat `runtime-ledger` filtering as a shallow top-level trim.

Pros:

- Lowest implementation cost.
- Minimal UI and backend churn.

Cons:

- Leaves `target_activity_groups` semantically ambiguous if built from pre-filtered or partially filtered sources.
- Risks a UI that appears filtered while still carrying unrelated activity context.

### Approach B: Query closure within the existing endpoint map

Keep the current endpoint layout, add explicit backend query parameters per view surface, and define `runtime-ledger` filtering in terms of filtered timeline inputs that then rebuild `target_activity_groups`.

Pros:

- Fixes the current architectural gap without expanding the public API surface.
- Keeps existing view and test structure mostly intact.
- Leaves room for a later pagination or endpoint-split slice if needed.

Cons:

- Requires careful definition of filter semantics for `runtime-ledger`.

### Approach C: Split ledger and operational lists into multiple new endpoints

Create separate server APIs for recovery timeline, system activity, operator activity, and target activity, and similarly split view data into more specialized endpoints.

Pros:

- Cleanest long-term decomposition.

Cons:

- Too large for this slice.
- Expands both backend and frontend scope beyond the agreed "filtering only, no pagination" boundary.

### Decision

Adopt Approach B.

This slice keeps the current endpoint map stable, adds authoritative backend filtering, and makes frontend filters express the server contract directly.

---

## 5. Backend Contract Changes

### 5.1 Review Inbox endpoints

#### `GET /api/v1/review-items`

Keep the response shape unchanged:

- `data.items`

Add optional query params:

- `status`
- `item_type`
- `target_collection`
- `scene_id`
- `chapter_id`

Behavior:

- Every supplied query param is an AND filter.
- Omitted params do not constrain the query.
- Ordering remains stable and descending by creation time, then `review_id` as needed for tie-break consistency.

#### `GET /api/v1/human-review-events`

Keep the response shape unchanged:

- `data.items`

Add optional query params:

- `status`
- `event_source`
- `priority`
- `owner`
- `scene_id`
- `chapter_id`

Behavior:

- Every supplied query param is an AND filter.
- Existing event serialization remains unchanged, including `linked_target`, `followup_target`, and `replay_target`.

### 5.2 Index Console endpoints

#### `GET /api/v1/index/alias-scopes`

Keep the response shape unchanged:

- `data.items`

Add optional query params:

- `object_type`
- `scope`
- `scope_ref_id`
- `verify_status`

Behavior:

- Filters apply directly to `VectorAliasRegistry` rows.
- `recent_fault_summary` continues to be returned for matching rows only.

#### `GET /api/v1/index/jobs`

Keep the response shape unchanged:

- `data.items`

Add optional query params:

- `job_type`
- `status`
- `object_type`
- `review_id`
- `alias_scope`

Behavior:

- `job_type=reindex` returns only reindex jobs.
- `job_type=verify` returns only verify jobs.
- Other supplied params remain AND filters.
- Sorting remains stable and deterministic.

#### `GET /api/v1/index/runtime-ledger`

Keep the response shape unchanged:

- `latest_recovery_action_receipt`
- `recovery_timeline_items`
- `system_runtime_timeline_items`
- `operator_action_timeline_items`
- `target_activity_groups`

Add optional query params:

- `target_ref`
- `source`
- `actor_ref`

Supported `source` values:

- `recovery_timeline`
- `system_runtime`
- `operator_action`

Behavior:

- Filtering is authoritative on the server.
- `recovery_timeline_items`, `system_runtime_timeline_items`, and `operator_action_timeline_items` are each filtered before aggregation.
- `target_activity_groups` must be rebuilt from the filtered timeline inputs, not filtered from a precomputed full list.
- `latest_recovery_action_receipt` should reflect the latest item from the filtered recovery timeline, or `null` if no filtered recovery item has an action receipt.

### 5.3 Runtime ledger filtering semantics

#### `target_ref`

If `target_ref` is supplied:

- Recovery timeline keeps only events whose linked, follow-up, or replay target matches `target_ref`.
- System runtime timeline keeps only operation logs whose `target_refs` include `target_ref`.
- Operator action timeline keeps only operation logs whose `target_refs` include `target_ref`.
- `target_activity_groups` is rebuilt from the filtered timelines and therefore contains only the matching target group.

#### `actor_ref`

If `actor_ref` is supplied:

- Recovery timeline keeps only events whose effective actor is that actor.
- System runtime timeline keeps only entries whose `actor_ref` matches.
- Operator action timeline keeps only entries whose `actor_ref` matches.
- `target_activity_groups` is rebuilt from only those filtered items.

#### `source`

If `source` is supplied:

- Only the selected timeline contributes items.
- Non-selected timelines return empty lists.
- `target_activity_groups` is rebuilt only from the selected timeline input.

#### Combined filters

If multiple query params are supplied:

- Each filtered timeline applies all relevant constraints.
- `target_activity_groups` is rebuilt from the final filtered timelines.

---

## 6. Frontend Changes

### 6.1 Review Inbox

Add explicit filter state to `reviewInbox` store and `ReviewInboxView`:

- review item filters:
  - `status`
  - `itemType`
  - `targetCollection`
  - `sceneId`
  - `chapterId`
- human review filters:
  - `status`
  - `eventSource`
  - `priority`
  - `owner`
  - `sceneId`
  - `chapterId`

Behavior:

- `load()` sends the active filter set to each backend endpoint.
- The view shows lightweight filter controls plus `Refresh` and `Clear`.
- Existing approve / release / human-review actions remain unchanged.
- After action-triggered reloads, current filters remain applied.

Focus behavior:

- If the currently focused review or human-review event is still present after reload, preserve focus.
- If it is filtered out, clear that local focus state instead of showing stale highlighting against no longer visible rows.

### 6.2 Index Console

Add explicit filter state to `indexConsole` store and `IndexConsoleView`:

- alias filters:
  - `objectType`
  - `scope`
  - `scopeRefId`
  - `verifyStatus`
- job filters:
  - `jobType`
  - `status`
  - `objectType`
  - `reviewId`
  - `aliasScope`
- runtime ledger filters:
  - `targetRef`
  - `source`
  - `actorRef`

Behavior:

- `load()` sends the three filter groups to the corresponding existing endpoints.
- The view keeps its current explicit refresh pattern rather than auto-loading on every keystroke.
- `Clear` resets that section's filter group to defaults.
- Retry / recovery / promotion actions still reload current filtered state after success.

Focus and expansion behavior:

- If the currently focused alias, job, or ledger target still exists after reload, preserve focus.
- If it no longer exists under the current filters, clear that local focus state.
- Expanded target activity refs are pruned to the refs still present in the filtered result.

### 6.3 API helpers

Frontend API utilities must support optional filter objects for:

- `fetchReviewItems`
- `fetchHumanReviewEvents`
- `fetchAliasScopes`
- `fetchIndexJobs`
- `fetchIndexRuntimeLedger`

The helpers should encode only non-empty params and otherwise preserve current endpoint URLs and response parsing.

---

## 7. Testing Strategy

### 7.1 Backend tests

Add or expand backend route tests for:

- `review-items` filtering by `status`, `item_type`, `target_collection`, `scene_id`, `chapter_id`
- `human-review-events` filtering by `status`, `event_source`, `priority`, `owner`, `scene_id`, `chapter_id`
- `alias-scopes` filtering by `object_type`, `scope`, `scope_ref_id`, `verify_status`
- `index/jobs` filtering by `job_type`, `status`, `object_type`, `review_id`, `alias_scope`
- `runtime-ledger` filtering by:
  - `target_ref`
  - `actor_ref`
  - `source`
  - combinations of the above

The `runtime-ledger` tests must prove that `target_activity_groups` is rebuilt from filtered timelines rather than post-filtered from the full output.

### 7.2 Frontend store and view tests

Add frontend unit tests for:

- API helper query serialization
- `reviewInbox` store passing current filters through to backend calls
- `indexConsole` store passing current filter groups through to backend calls
- clearing filtered-out focus state after reload
- pruning expanded target activity refs when filtered results shrink

Add store/view tests for:

- `ReviewInboxView` filter controls
- `IndexConsoleView` filter controls
- presence of `Refresh` and `Clear` actions for each filter group

### 7.3 Playwright

Extend the seeded browser E2E lane so it proves:

- `Review Inbox` can narrow to a target review item and a target human review event via filters
- `Index Console` can narrow to a target alias scope, target job, and target activity via filters
- operator actions still succeed under filtered views
- cross-view target focus still works after filtered reloads

This slice should reuse the existing seeded browser path rather than create a new standalone E2E lane.

---

## 8. Risks and Mitigations

### Risk: runtime-ledger filters become ambiguous

Mitigation:

- Keep only three top-level ledger filters in this slice: `target_ref`, `source`, `actor_ref`
- Define exact timeline behavior and rebuild `target_activity_groups` from filtered inputs

### Risk: frontend focus state lingers after filtered reloads

Mitigation:

- Make focus preservation conditional on the focused entity still being present in the returned result
- Clear stale local focus and stale expanded refs when the item disappears

### Risk: scope creeps into pagination or endpoint splitting

Mitigation:

- Treat pagination and endpoint decomposition as explicit non-goals for this slice
- Keep current response envelopes intact

---

## 9. Acceptance Criteria

This slice is complete when all of the following are true:

1. `Review Inbox` no longer requires unfiltered full-table reads during normal filtered use.
2. `Index Console` no longer requires unfiltered full-table reads during normal filtered use.
3. `runtime-ledger` accepts `target_ref`, `source`, and `actor_ref`, and `target_activity_groups` reflects only filtered timeline inputs.
4. Existing actions (`approve`, `release`, `retry verify`, `recovery sweep`, `run due promotions`, `human review action`) still work under filtered view state.
5. Seeded Playwright coverage proves the filter controls and filtered action flows in `Review Inbox` and `Index Console`.
6. Windows-safe verification, frontend browser E2E, and WSL strict Chroma verification all pass after implementation.
