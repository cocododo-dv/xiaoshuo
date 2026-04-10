# Release Checklist

Use this checklist before converting a Draft PR to ready state or treating the current branch as release-ready.

## Automatic PR checks

- GitHub Actions backend job passed.
- GitHub Actions frontend job passed.

## Required local checks on this machine

- Run `powershell -ExecutionPolicy Bypass -File scripts/verify_windows.ps1`
- Run `wsl -d Ubuntu-24.04 bash -lc "cd /mnt/e/codex/xiaoshuo/codex && bash scripts/verify_wsl_strict.sh"`

## Seeded manual acceptance

- Run `cd backend && alembic upgrade head`
- Run `cd backend && python -m novel_system.tools.seed_demo`
- Start the backend and frontend demo lane
- Record the `Operator Ref` used for the session
- Run `CH001_SC01` from `Scene Workbench`
- Approve and release `review_demo_style_observation`
- Exercise human review follow-up actions from `Review Inbox`
- Exercise verify retry, `run due promotions`, and `recovery sweep` from `Index Console`
- Confirm the latest receipt, runtime ledger, and target activity views all show the expected actor and linked target state

## PR evidence

- Paste or summarize the Windows verification result in the PR.
- Paste or summarize the WSL strict Chroma result in the PR.
- Describe how `X-Operator-Ref` was validated during the seeded demo.
- Summarize the recovery / promotion / human-review follow-up manual acceptance run.
- Note any environment caveats or skipped checks.

## Release gate

- Keep the PR as draft until both local verification lanes and GitHub Actions are green.
- If any risk remains, document it in the PR before marking the work ready.

