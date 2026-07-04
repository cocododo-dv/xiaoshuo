#!/usr/bin/env bash
# Linux dev equivalent of start-dev.cmd's backend leg (this box has no PowerShell).
# Safe to re-run: stops any previous instance (by pidfile, falling back to
# whatever is bound to the port) before starting a fresh one.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
# shellcheck source=lib/dev-lifecycle.sh
source "$SCRIPT_DIR/lib/dev-lifecycle.sh"

RUN_DIR="$REPO_ROOT/.codex-run"
mkdir -p "$RUN_DIR"
PID_FILE="$RUN_DIR/backend.pid"
URL_FILE="$RUN_DIR/backend.url"
PORT="${NOVEL_SYSTEM_BACKEND_PORT:-8000}"

dev_stop_pidfile "$PID_FILE"
dev_stop_port "$PORT"

cd "$REPO_ROOT/backend"

export NOVEL_SYSTEM_VECTOR_BACKEND=memory
export NOVEL_SYSTEM_CONFIG_SECRET="${NOVEL_SYSTEM_CONFIG_SECRET:-dev-local-secret-change-me}"

.venv/bin/python -m alembic upgrade head

echo "http://127.0.0.1:${PORT}" > "$URL_FILE"
echo $$ > "$PID_FILE"
exec .venv/bin/python -m uvicorn novel_system.api.app:create_app --factory --reload \
  --host 127.0.0.1 --port "$PORT" --app-dir src
