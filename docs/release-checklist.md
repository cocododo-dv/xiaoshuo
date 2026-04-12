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
- Record the fixture operator identities: `ops.chapter.e2e`, `ops.runtime.e2e`, `ops.knowledge.e2e`, and `ops.interop.e2e`
- Confirm the lane covers `Scene Workbench` chapter runtime backfill / manual hold / final aggregate on `CH200_SC01`
- Confirm the lane covers `Scene Workbench`, `Review Inbox`, `Index Console`, due promotions, recovery sweep, human-review follow-up, Knowledge Console workflow/provenance, and the Interop Center preview/import/export/replay path
- Confirm the lane checks actor identity, linked-target identity, and cross-view target focus via receipts plus target activity
- Confirm the Knowledge Console slice checks object / scope / scope-ref / status filters, detail reset on empty filters, linked review refs, and linked bundle refs
- Confirm the Interop Center slice checks strict YAML preview, import receipt, worksheet export, final-scene replay, source-ref comparisons, and jump targets back to `Scene Workbench` / `Knowledge Console`
- Note whether domain API decomposition and dual pagination evidence came from browser E2E, automated route/helper tests, or both
- Use the manual walkthrough from the README only if the automated E2E lane fails or extra exploratory validation is needed

## PR evidence

- Paste or summarize the Windows verification result in the PR.
- Paste or summarize the seeded browser E2E result in the PR.
- Paste or summarize the WSL strict Chroma result in the PR.
- Describe how `X-Operator-Ref` was validated during the seeded E2E lane.
- Note which assertions came from `ops.chapter.e2e`, `ops.runtime.e2e`, `ops.knowledge.e2e`, and `ops.interop.e2e`.
- Note where `/api/v1/knowledge-entries`, `/api/v1/vector-alias-scopes`, `/api/v1/jobs`, `/api/v1/activity-events`, and `/api/v1/target-activity-groups` were revalidated if the change touched runtime shell read contracts.
- Note where dual pagination (`page/page_size` and `cursor/limit`) was revalidated for review items, human review events, jobs, and scene attempts.
- Summarize any manual recovery / promotion / human-review follow-up checks only if you ran extra spot-checks beyond E2E.
- Note any environment caveats or skipped checks.

## Release gate

- Keep the PR as draft until both local verification lanes and GitHub Actions are green.
- If any risk remains, document it in the PR before marking the work ready.

