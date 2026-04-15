# Release Checklist

Use this checklist before converting a Draft PR to ready state or treating the current branch as release-ready.

## Automatic PR checks

- GitHub Actions backend job passed.
- GitHub Actions frontend job passed.

## Required local checks on this machine

- Run `powershell -ExecutionPolicy Bypass -File scripts/verify_windows.ps1`
- Treat the backend pytest half of `scripts/verify_windows.ps1` as the required true-generation backend lane:
  `backend/tests/test_scene_generation.py` for fake-provider generation,
  `backend/tests/test_qc_engine.py` for fake-provider QC,
  and `backend/tests/test_chapter_runner.py` plus `backend/tests/test_chapter_runtime.py` for the current chapter runner/runtime path.
- Run `cd frontend && npm run test:e2e`
- Run `wsl -d Ubuntu-24.04 bash -lc "cd <current-checkout-in-wsl> && bash scripts/verify_wsl_strict.sh"`
- Replace `<current-checkout-in-wsl>` with the checkout/worktree root under review so the WSL lane verifies the same tree as the Windows lane.
- Fake-provider/deterministic verification is required in CI.
- Real-provider smoke tests are local-only evidence until secrets handling is formalized; if you run one, label it separately from CI-required coverage.

## Seeded browser E2E acceptance

- Record the `npm run test:e2e` result in the PR
- Record the fixture operator identities: `ops.chapter.e2e`, `ops.scene-llm.e2e`, `ops.runtime.e2e`, `ops.knowledge.e2e`, and `ops.interop.e2e`
- Confirm the lane covers `Scene Workbench` chapter runtime backfill / manual hold / final aggregate on `CH200_SC01`
- Confirm the lane covers the focused `Scene Workbench` LLM pipeline on `CH001_SC01`: run button -> deterministic generation evidence -> hard/soft QC pass -> final archive
- Confirm the lane covers `Scene Workbench`, `Review Inbox`, `Index Console`, due promotions, recovery sweep, human-review follow-up, Knowledge Console workflow/provenance, and the Interop Center preview/import/export/replay path
- Confirm the lane checks actor identity, linked-target identity, and cross-view target focus via receipts plus target activity
- Confirm the Knowledge Console slice checks object / scope / scope-ref / status filters, detail reset on empty filters, linked review refs, and linked bundle refs
- Confirm the Interop Center slice checks strict YAML preview, import receipt, worksheet export, final-scene replay, source-ref comparisons, and jump targets back to `Scene Workbench` / `Knowledge Console`
- Confirm the browser lane is recorded as deterministic offline/fake-provider evidence rather than a real-provider smoke run
- Note whether domain API decomposition and dual pagination evidence came from browser E2E, automated route/helper tests, or both
- Use the manual walkthrough from the README only if the automated E2E lane fails or extra exploratory validation is needed

## PR evidence

- Paste or summarize the Windows verification result in the PR.
- Paste or summarize the seeded browser E2E result in the PR.
- Paste or summarize the WSL strict Chroma result in the PR.
- Record the provider config used for each verification lane, including whether `NOVEL_SYSTEM_LLM_ENABLED` stayed false / offline and any local-only real-provider overrides.
- Record the prompt template name/version used for the exercised scene pipeline templates from `config/prompts.yaml`.
- Record generation evidence: provider, model, prompt hash, finish reason, and final scene row id / archive receipt.
- Record QC evidence: hard/soft resolution code, next action, pass flag, and any human-review outcome if the lane did not archive cleanly.
- Describe how `X-Operator-Ref` was validated during the seeded E2E lane.
- Note which assertions came from `ops.chapter.e2e`, `ops.scene-llm.e2e`, `ops.runtime.e2e`, `ops.knowledge.e2e`, and `ops.interop.e2e`.
- Note where `/api/v1/knowledge-entries`, `/api/v1/vector-alias-scopes`, `/api/v1/jobs`, `/api/v1/activity-events`, and `/api/v1/target-activity-groups` were revalidated if the change touched runtime shell read contracts.
- Note where dual pagination (`page/page_size` and `cursor/limit`) was revalidated for review items, human review events, jobs, and scene attempts.
- Summarize any manual recovery / promotion / human-review follow-up checks only if you ran extra spot-checks beyond E2E.
- Note any environment caveats or skipped checks.

## Release gate

- Keep the PR as draft until both local verification lanes and GitHub Actions are green.
- If any risk remains, document it in the PR before marking the work ready.

