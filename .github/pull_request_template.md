## Summary

- Describe the runtime-shell or documentation-sync changes in 2-4 bullets.
- Call out any workflow changes reviewers should pay attention to.
- Call out changes to chapter runtime, domain read APIs, cursor pagination, or runtime-ops behavior when relevant.

## Validation

- [ ] `powershell -ExecutionPolicy Bypass -File scripts/verify_windows.ps1`
- [ ] `cd frontend && npm run test:e2e`
- [ ] `wsl -d Ubuntu-24.04 bash -lc "cd /mnt/e/codex/xiaoshuo/codex && bash scripts/verify_wsl_strict.sh"`
- [ ] `cd backend && alembic upgrade head`
- [ ] `cd backend && python -m novel_system.tools.seed_demo`
- [ ] GitHub Actions CI passed

## Seeded Runtime-Ops E2E

- [ ] Record the `npm run test:e2e` result
- [ ] Record the fixture operator identities: `ops.chapter.e2e`, `ops.runtime.e2e`, `ops.knowledge.e2e`, and `ops.interop.e2e`
- [ ] Confirm the E2E lane covered `Scene Workbench` chapter runtime backfill / manual hold / final aggregate on `CH200_SC01`
- [ ] Confirm the E2E lane covered `Scene Workbench`, `Review Inbox`, `Index Console`, due promotions, recovery sweep, and human-review follow-up
- [ ] Confirm the E2E lane covered Knowledge Console workflow/provenance and the Interop Center preview/import/export/replay path
- [ ] Confirm the E2E lane checked receipts, runtime ledger entries, target activity, and cross-view target focus for actor / linked-target integrity

## Domain / Pagination Notes

- Describe whether `/api/v1/knowledge-entries`, `/api/v1/vector-alias-scopes`, `/api/v1/jobs`, `/api/v1/activity-events`, and `/api/v1/target-activity-groups` were part of the change or were revalidated as the current shell read path.
- Note where dual pagination (`page/page_size` and `cursor/limit`) was validated for review items, human review events, jobs, and scene attempts.

## WSL Strict Chroma Notes

- Record the exact distro, command result, and any environment caveats.

## Operator Ref Notes

- Describe how the automated or manual `Operator Ref` was set.
- Note which POST-driven actions were validated with `X-Operator-Ref` and whether that evidence came from `ops.chapter.e2e`, `ops.runtime.e2e`, `ops.knowledge.e2e`, `ops.interop.e2e`, manual spot-checks, or both.

## Risks / Follow-ups

- None.

