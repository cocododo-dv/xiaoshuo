#!/usr/bin/env bash
# One-click stop for scripts/start-all-linux.sh. Safe to re-run (and safe to
# run even if nothing is up) — kills by tracked pidfile, then falls back to
# whatever is still bound to the dev ports.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
# shellcheck source=lib/dev-lifecycle.sh
source "$SCRIPT_DIR/lib/dev-lifecycle.sh"

RUN_DIR="$REPO_ROOT/.codex-run"
BACKEND_PORT="${NOVEL_SYSTEM_BACKEND_PORT:-8000}"
FRONTEND_PORT="${NOVEL_SYSTEM_FRONTEND_PORT:-5174}"

echo "==> stopping backend"
dev_stop_pidfile "$RUN_DIR/backend.pid"
dev_stop_port "$BACKEND_PORT"
rm -f "$RUN_DIR/backend.url"

echo "==> stopping frontend"
dev_stop_pidfile "$RUN_DIR/frontend-react.pid"
dev_stop_port "$FRONTEND_PORT"
rm -f "$RUN_DIR/frontend-react.url"

echo "==> stopped"
