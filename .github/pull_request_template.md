## Summary

- Describe the release-hardening changes in 2-4 bullets.
- Call out any workflow changes reviewers should pay attention to.
- Call out runtime-ops changes such as `operator_ref`, runtime ledger updates, recovery sweep, due promotions, and human review follow-up behavior when relevant.

## Validation

- [ ] `powershell -ExecutionPolicy Bypass -File scripts/verify_windows.ps1`
- [ ] `cd frontend && npm run test:e2e`
- [ ] `wsl -d Ubuntu-24.04 bash -lc "cd /mnt/e/codex/xiaoshuo/codex && bash scripts/verify_wsl_strict.sh"`
- [ ] `cd backend && alembic upgrade head`
- [ ] `cd backend && python -m novel_system.tools.seed_demo`
- [ ] GitHub Actions CI passed

## Seeded Runtime-Ops E2E

- [ ] Record the `npm run test:e2e` result
- [ ] Record the fixture operator identity: `ops.runtime.e2e`
- [ ] Confirm the E2E lane covered `Scene Workbench`, `Review Inbox`, `Index Console`, due promotions, recovery sweep, and human-review follow-up
- [ ] Confirm the E2E lane checked receipts, runtime ledger entries, target activity, and cross-view target focus for actor / linked-target integrity

## WSL Strict Chroma Notes

- Record the exact distro, command result, and any environment caveats.

## Operator Ref Notes

- Describe how the automated or manual `Operator Ref` was set.
- Note which POST-driven actions were validated with `X-Operator-Ref` and whether that evidence came from `npm run test:e2e`, manual spot-checks, or both.

## Risks / Follow-ups

- None.

