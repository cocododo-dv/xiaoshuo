# Release Checklist

Use this checklist before converting a Draft PR to ready state or treating the current branch as release-ready.

## Automatic PR checks

- GitHub Actions backend job passed.
- GitHub Actions frontend job passed.

## Required local checks on this machine

- Run `powershell -ExecutionPolicy Bypass -File scripts/verify_windows.ps1`
- Run `cd frontend && npm run test:e2e`
- Run `wsl -d Ubuntu-24.04 bash -lc "cd /mnt/e/codex/xiaoshuo/codex && bash scripts/verify_wsl_strict.sh"`

## Seeded browser E2E acceptance

- Record the `npm run test:e2e` result in the PR
- Record the fixture operator identities: `ops.runtime.e2e` and `ops.knowledge.e2e`
- Confirm the lane covers `Scene Workbench`, `Review Inbox`, `Index Console`, due promotions, recovery sweep, human-review follow-up, and Knowledge Console filter/detail jumps
- Confirm the lane checks actor identity, linked-target identity, and cross-view target focus via receipts plus target activity
- Confirm the Knowledge Console slice checks object / scope / scope-ref / status filters, detail reset on empty filters, linked review refs, and linked bundle refs
- Use the manual walkthrough from the README only if the automated E2E lane fails or extra exploratory validation is needed

## PR evidence

- Paste or summarize the Windows verification result in the PR.
- Paste or summarize the seeded browser E2E result in the PR.
- Paste or summarize the WSL strict Chroma result in the PR.
- Describe how `X-Operator-Ref` was validated during the seeded E2E lane.
- Note which assertions came from `ops.runtime.e2e` and which came from `ops.knowledge.e2e`.
- Summarize any manual recovery / promotion / human-review follow-up checks only if you ran extra spot-checks beyond E2E.
- Note any environment caveats or skipped checks.

## Release gate

- Keep the PR as draft until both local verification lanes and GitHub Actions are green.
- If any risk remains, document it in the PR before marking the work ready.

