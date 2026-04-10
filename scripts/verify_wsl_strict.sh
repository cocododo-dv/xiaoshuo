#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_DIR="$REPO_ROOT/backend"

if [[ -n "${PYTHON_BIN:-}" ]]; then
  PYTHON_BIN="$PYTHON_BIN"
elif [[ -x "$BACKEND_DIR/.venv/bin/python" ]]; then
  PYTHON_BIN="$BACKEND_DIR/.venv/bin/python"
else
  while IFS= read -r line; do
    if [[ "$line" == worktree\ * ]]; then
      CANDIDATE_ROOT="${line#worktree }"
      CANDIDATE_PYTHON="$CANDIDATE_ROOT/backend/.venv/bin/python"
      if [[ "$CANDIDATE_ROOT" != "$REPO_ROOT" && -x "$CANDIDATE_PYTHON" ]]; then
        PYTHON_BIN="$CANDIDATE_PYTHON"
        break
      fi
    fi
  done < <(git -C "$REPO_ROOT" worktree list --porcelain)

  PYTHON_BIN="${PYTHON_BIN:-python3}"
fi

run_step() {
  local label="$1"
  shift
  printf '==> %s\n' "$label"
  PYTHONPATH="$BACKEND_DIR/src${PYTHONPATH:+:$PYTHONPATH}" "$@"
}

cd "$BACKEND_DIR"

run_step "Chroma smoke" "$PYTHON_BIN" -m novel_system.tools.chroma_smoke
run_step "Focused Chroma suite" "$PYTHON_BIN" -m pytest tests/test_chroma_smoke.py tests/test_chroma_vector_store.py tests/test_review_release.py tests/test_vector_verify_gate.py tests/test_acceptance_flow.py -q
run_step "Full backend pytest" "$PYTHON_BIN" -m pytest -q
