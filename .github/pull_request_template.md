## Summary

- Describe the runtime-shell or documentation-sync changes in 2-4 bullets.
- Call out any workflow changes reviewers should pay attention to.
- Call out changes to chapter runtime, domain read APIs, cursor pagination, or runtime-ops behavior when relevant.

## Validation

- [ ] `powershell -ExecutionPolicy Bypass -File scripts/verify_windows.ps1`
- [ ] Backend pytest evidence called out for `backend/tests/test_scene_generation.py`, `backend/tests/test_qc_engine.py`, and `backend/tests/test_chapter_runner.py` plus `backend/tests/test_chapter_runtime.py`
- [ ] `powershell -ExecutionPolicy Bypass -File scripts/verify_react_e2e.ps1`
- [ ] `wsl -d Ubuntu-24.04 bash -lc "cd <current-checkout-in-wsl> && bash scripts/verify_wsl_strict.sh"` using the checkout/worktree under review
- [ ] `cd backend && alembic upgrade head`
- [ ] Fresh `cd backend && python -m alembic upgrade head` matches ORM schema (`tests/test_metadata_isolation.py`)
- [ ] GitHub Actions CI passed
- [ ] If a real-provider smoke run was used, it is documented as local-only evidence and kept separate from CI-required fake-provider/deterministic coverage

## Isolated React Contract E2E

- [ ] Record the `scripts/verify_react_e2e.ps1` result
- [ ] Record the fixture operator identities: `ops.chapter.e2e`, `ops.scene-llm.e2e`, `ops.runtime.e2e`, `ops.knowledge.e2e`, and `ops.interop.e2e`
- [ ] Confirm the E2E lane covered `Scene Workbench` chapter runtime backfill / manual hold / final aggregate on `CH200_SC01`
- [ ] Confirm the E2E lane covered the focused `Scene Workbench` LLM pipeline on `CH001_SC01`: mocked/offline generation evidence, QC pass, and archived final scene
- [ ] Confirm the E2E lane covered `Scene Workbench`, `Review Inbox`, `Index Console`, due promotions, recovery sweep, and human-review follow-up
- [ ] Confirm the E2E lane covered Knowledge Console workflow/provenance and the Interop Center preview/import/export/replay path
- [ ] Confirm the E2E lane checked receipts, runtime ledger entries, target activity, and cross-view target focus for actor / linked-target integrity
- [ ] Confirm the browser evidence is labeled as fake-provider/deterministic coverage, not real-provider CI coverage

## Provider / Prompt Evidence

- [ ] Record provider config used for verification, including whether `NOVEL_SYSTEM_LLM_ENABLED` stayed false and any local-only real-provider overrides
- [ ] Record prompt template name/version for the exercised templates from `config/prompts.yaml`
- [ ] Record generation evidence: provider, model, prompt hash, finish reason, and final scene row id / archive receipt
- [ ] Record QC evidence: hard/soft resolution code, next action, pass flag, and any human-review outcome if applicable

## Domain / Pagination Notes

- Describe whether `/api/v1/knowledge-entries`, `/api/v1/vector-alias-scopes`, `/api/v1/jobs`, `/api/v1/activity-events`, and `/api/v1/target-activity-groups` were part of the change or were revalidated as the current shell read path.
- Note where dual pagination (`page/page_size` and `cursor/limit`) was validated for review items, human review events, jobs, and scene attempts.

## WSL Strict Chroma Notes

- Record the exact distro, command result, and any environment caveats.

## Operator Ref Notes

- Describe how the automated or manual `Operator Ref` was set.
- Note which POST-driven actions were validated with `X-Operator-Ref` and whether that evidence came from `ops.chapter.e2e`, `ops.scene-llm.e2e`, `ops.runtime.e2e`, `ops.knowledge.e2e`, `ops.interop.e2e`, manual spot-checks, or both.

## Risks / Follow-ups

- None.

