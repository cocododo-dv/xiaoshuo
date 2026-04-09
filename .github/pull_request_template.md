## Summary

- Describe the release-hardening changes in 2-4 bullets.
- Call out any workflow changes reviewers should pay attention to.

## Validation

- [ ] `powershell -ExecutionPolicy Bypass -File scripts/verify_windows.ps1`
- [ ] `wsl -d Ubuntu-24.04 bash -lc "cd /mnt/e/codex/xiaoshuo/codex && bash scripts/verify_wsl_strict.sh"`
- [ ] GitHub Actions CI passed

## WSL Strict Chroma Notes

- Record the exact distro, command result, and any environment caveats.

## Risks / Follow-ups

- None.

