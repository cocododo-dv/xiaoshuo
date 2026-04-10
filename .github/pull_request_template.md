## Summary

- Describe the release-hardening changes in 2-4 bullets.
- Call out any workflow changes reviewers should pay attention to.
- Call out runtime-ops changes such as `operator_ref`, runtime ledger updates, recovery sweep, due promotions, and human review follow-up behavior when relevant.

## Validation

- [ ] `powershell -ExecutionPolicy Bypass -File scripts/verify_windows.ps1`
- [ ] `wsl -d Ubuntu-24.04 bash -lc "cd /mnt/e/codex/xiaoshuo/codex && bash scripts/verify_wsl_strict.sh"`
- [ ] `cd backend && alembic upgrade head`
- [ ] `cd backend && python -m novel_system.tools.seed_demo`
- [ ] GitHub Actions CI passed

## Seeded Manual Acceptance

- [ ] Record the `Operator Ref` used during the demo session
- [ ] Run `CH001_SC01` from `Scene Workbench`
- [ ] Approve / release `review_demo_style_observation`
- [ ] Exercise human review follow-up actions from `Review Inbox`
- [ ] Exercise verify retry / `run due promotions` / `recovery sweep` from `Index Console`
- [ ] Confirm receipts, runtime ledger entries, and target activity groups show the expected actor and target links

## WSL Strict Chroma Notes

- Record the exact distro, command result, and any environment caveats.

## Operator Ref Notes

- Describe how the active `Operator Ref` was set.
- Note which POST-driven actions were validated with `X-Operator-Ref`.

## Risks / Follow-ups

- None.

