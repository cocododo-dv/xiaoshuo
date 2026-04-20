# Three-Chapter Real LLM QA Report

Operator: `qa.three-chapters.real-llm`  
API Base: `http://127.0.0.1:8000`  
Frontend: `http://127.0.0.1:5173`  
Provider: `local_qwen3` / `openai_compatible` / `Qwen3-14B-Q8_0.gguf`

## Result

The three-chapter creation loop completed with real LLM generation:

| Chapter | Scene | Final scene row | Chapter final memory | Run status |
| --- | --- | --- | --- | --- |
| `CHQA01` | `CHQA01_SC01` | `final_scene_CHQA01_SC01_v5` | `chapter_memory_final_CHQA01_v1` | `completed` |
| `CHQA02` | `CHQA02_SC01` | `final_scene_CHQA02_SC01_v5` | `chapter_memory_final_CHQA02_v1` | `completed` |
| `CHQA03` | `CHQA03_SC01` | `final_scene_CHQA03_SC01_v5` | `chapter_memory_final_CHQA03_v1` | `completed` |

All three scenes are `archived`, each chapter has `chapter_passed_scene_count = 1`, no aggregate block, no manual hold, and no pending backfill.

## Page Coverage

| Page | User-flow coverage | Outcome |
| --- | --- | --- |
| System Config | API base probe, provider probe, node route save/validation, baseline/live literary eval, API category export, style profile extract and review candidate | Live eval passed `3/3`, mean score `0.8889`; style review approved/released |
| Reference Learning | Imported `frontend/tests/e2e/fixtures/reference-learning.md`, started run, advanced analysis, approved 7 findings, rejected 1 finding, generated profile, applied profile to `chapter:CHQA01` | Completed; profile `refprofile_refbook_0174cef49962_8f7236fecf` ready and applied |
| Review Inbox | Approved/released reference apply reviews and system-config style profile review; inspected human review list | Completed; approved cards required switching from pending to approved filter before release |
| Index Console | Ran due promotions, recovery sweep, expanded activity sections, inspected jobs/ledger | Completed; stale failed verify job remains visible for older calibration candidate |
| Author Workspace | Created and edited `CHQA01..03`; created scenes; opened workbench; created isolated trash-test chapter | Completed |
| Scene Workbench | Loaded each scene, checked preflight, ran full scene, saw evidence/QC/timeline, set/cleared manual hold, ran final aggregate | Completed with real LLM final scenes |
| Knowledge Console | Created voice, relation, style, and calibration candidates; used active-on-approve and approve-verify-release paths; opened details/refs | Completed |
| Interop Center | Previewed/imported/exported worksheet bundle; replayed `final_scene_CHQA01_SC01_v5`; checked envelope and comparisons | Completed |
| Author Trash | Used separate `CHQAT885328` test chapter: moved scene to trash, restored it, moved chapter to trash, purged chapter | Completed; `CHQA01..03` untouched |

## Screenshots

Stored in `output/playwright/three-chapter-qa/`:

- `author-workspace-complete.png`
- `workbench-complete.png`
- `workbench-chqa03-final.png`
- `knowledge-console-complete.png`
- `reference-after-profile-apply.png`
- `review-inbox-complete.png`
- `index-console-complete.png`
- `interop-center-complete.png`
- `system-config-complete.png`
- `author-trash-complete.png`

## Fixed Issues

| Priority | Issue | Root cause | Fix |
| --- | --- | --- | --- |
| P0 | Live literary eval rejected credential-free local provider | API/tool required global `llm_api_key` and ignored provider `credential_mode: none` | Credential availability now checks provider config, selected provider, provider token, and global key |
| P1 | Hard QC partial rewrite could loop without escalating | Orchestrator reset hard retry counters and repeat issue tracking on every run | Preserve hard QC retry state while no final scene exists |
| P1 | Chapter runner could mark a scene run complete without final scene | Chapter runner only checked human review, not final scene output | Block with `CHAPTER_RUN_SCENE_INCOMPLETE` when no final row exists |
| P1 | Real LLM hard QC false positives blocked valid drafts | Hard QC trusted LLM claims over deterministic scene-card facts | Added deterministic sanity layer for forbidden text, required text, unsupported event, duplicate, and style-only false positives |
| P1 | Chapter `run-status` stayed blocked/failed after workbench produced final scenes | Job reconciliation only trusted job payload, not archived scene state | Run-status now reconciles scenes with `current_final_scene_row_id`, while preserving genuine backfill/human-review/failed states |

## Open Issues / UX Notes

| Priority | Issue | Evidence | Suggested solution |
| --- | --- | --- | --- |
| P2 | Reference first-round advance exceeded the initial 240s automation wait | Real LLM generated 8 findings, but serial batch took longer than 4 minutes | Add progress per segment, longer route-specific timeout, and partial completion status |
| P2 | Review pending filter hides a card immediately after approval, so release is not a same-row continuation | Style review disappeared from pending after approve; release worked after switching to approved filter | Keep recently approved card pinned in the current list or provide an approve-and-release receipt action |
| P2 | Workbench reload still tries default `CH001_SC01` in this DB and emits 404 console errors | Console shows 404 for `/api/v1/scenes/CH001_SC01/workbench` and attempts | Persist last valid scene id or start with empty scene id when default is missing |
| P3 | Author scene creation is timing-sensitive after a freshly created chapter | A scripted click on `新建场景` after saving a chapter left the scene form empty; API setup plus UI trash actions worked | Make the new-scene action explicitly select the current chapter and initialize draft state, or disable until refresh finishes |
| P3 | Old failed verify job remains visible after candidate changes | `verify_review_qa_calibration_three_chapters` reports stale target mismatch | Surface this as expected stale-target history or provide a clearer cleanup/retry decision |

## Verification

Passed:

```text
python -m pytest backend/tests/test_qc_engine.py backend/tests/test_chapter_runner.py backend/tests/test_scene_generation.py backend/tests/test_literary_eval.py backend/tests/test_prompt_builder.py backend/tests/test_scene_workbench_preflight.py -q
70 passed in 15.26s
```

Browser/API verification:

- Frontend/backend healthy after restart.
- `CHQA01..03` chapter run-status all `completed`.
- Live literary eval latest report: `3/3` passed, mean score `0.8889`.
- Trash payload empty after purging the isolated test chapter.

Not run:

- Full `scripts/verify_windows.ps1 -BackendOnly`; targeted backend coverage was used because the task required long real-LLM browser execution.
