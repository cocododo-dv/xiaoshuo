# Human Review Runtime Ops Closeout Design

> Date: 2026-04-10
> Target slice: L3 runtime operations closeout for human review, recovery, promotion, and operator-traceable actions.

---

## 1. Background

The current working tree already contains the runtime-ops behavior needed for the L3 slice:

- operator-aware POST handling via `X-Operator-Ref`
- runtime ledger and target activity aggregation
- recovery sweep and due-promotion actions
- human review retry / follow-up flows
- cross-view target jumps across Workbench, Review Inbox, and Index Console

Both supported verification lanes passed on 2026-04-10:

- `powershell -ExecutionPolicy Bypass -File scripts/verify_windows.ps1`
- `wsl -d Ubuntu-24.04 bash -lc "cd /mnt/e/codex/xiaoshuo/codex && bash scripts/verify_wsl_strict.sh"`

This closeout is therefore a documentation and release-hand-off pass, not a new product expansion.

---

## 2. Goals

1. Freeze the public runtime-ops contract now present in the backend and frontend.
2. Document the seeded operator workflow used to validate the slice end to end.
3. Update release materials so a Draft PR captures both automated verification lanes and the seeded runtime-ops acceptance path.

---

## 3. Non-Goals

- No new backend endpoints.
- No schema or wire-shape renames for the runtime ledger or human review event payloads.
- No new UI surface beyond what is already present in the current working tree.
- No expansion into the next milestone after this L3 slice.

---

## 4. Closed-Out Runtime Ops Contract

### 4.1 Operator identity

- The backend reads `X-Operator-Ref` for mutating requests and falls back to `operator`.
- The frontend persists the active operator under `novel-system-operator-ref`.
- Runtime receipts and operation logs must preserve the effective actor for later triage.

### 4.2 Public endpoints now treated as stable for this slice

- `GET /api/v1/index/runtime-ledger`
- `POST /api/v1/runtime/recovery/sweep`
- `POST /api/v1/runtime/promotions/run-due`
- `POST /api/v1/index/verify/{job_id}/retry`
- `GET /api/v1/human-review-events/{event_id}`
- `POST /api/v1/human-review-events/{event_id}/actions`

### 4.3 Documented payload fields

The closeout explicitly treats these response fields as documented contract:

- runtime ledger: `latest_recovery_action_receipt`
- runtime ledger: `recovery_timeline_items`
- runtime ledger: `system_runtime_timeline_items`
- runtime ledger: `operator_action_timeline_items`
- runtime ledger: `target_activity_groups`
- human review detail: `linked_target`
- human review detail: `followup_target`
- human review detail: `replay_target`

These field names are frozen for this closeout and should not be renamed as part of documentation sync.

---

## 5. Seeded Acceptance Flow

The seeded demo flow for runtime-ops closeout is:

1. Start from a database at `alembic upgrade head`.
2. Run `python -m novel_system.tools.seed_demo`.
3. Start the backend and frontend demo lane.
4. Set `Operator Ref` in the shell rail.
5. Run `CH001_SC01` from `Scene Workbench`.
6. Approve and release `review_demo_style_observation`.
7. Use `Index Console` to trigger verify retry, due promotions, and recovery sweep.
8. Open the surfaced human review event in `Review Inbox` and execute the follow-up action.
9. Confirm receipts, runtime ledger entries, and target activity groups retain the expected actor and linked target identity.

---

## 6. Release Handoff

Release-facing documents must capture:

- the exact Windows verification result
- the exact WSL strict Chroma result
- the operator ref used during seeded acceptance
- the manual acceptance outcome for recovery, promotion, and human review follow-up flows

The PR should remain draft until both automated verification lanes and the seeded runtime-ops acceptance path are recorded.
