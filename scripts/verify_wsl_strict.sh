#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_DIR="$REPO_ROOT/backend"

if [[ -x "$BACKEND_DIR/.venv/bin/python" ]]; then
  PYTHON_BIN="$BACKEND_DIR/.venv/bin/python"
else
  PYTHON_BIN="${PYTHON_BIN:-python3}"
fi

run_step() {
  local label="$1"
  shift
  printf '==> %s\n' "$label"
  "$@"
}

cd "$BACKEND_DIR"

run_step "Chroma smoke" "$PYTHON_BIN" -m novel_system.tools.chroma_smoke
run_step "Focused Chroma suite" "$PYTHON_BIN" -m pytest tests/test_chroma_smoke.py tests/test_chroma_vector_store.py tests/test_review_release.py tests/test_vector_verify_gate.py tests/test_acceptance_flow.py -q
run_step "Full backend pytest" "$PYTHON_BIN" -m pytest -q
