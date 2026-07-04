#!/usr/bin/env bash
# One-click start: backend + React frontend, both backgrounded and logged
# under .codex-run/. Safe to re-run — each leg stops its own previous
# instance first (see start-backend-linux.sh / start-frontend-linux.sh).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
# shellcheck source=lib/dev-lifecycle.sh
source "$SCRIPT_DIR/lib/dev-lifecycle.sh"

RUN_DIR="$REPO_ROOT/.codex-run"
LOG_DIR="$RUN_DIR/logs"
mkdir -p "$LOG_DIR"

BACKEND_PORT="${NOVEL_SYSTEM_BACKEND_PORT:-8000}"
FRONTEND_PORT="${NOVEL_SYSTEM_FRONTEND_PORT:-5174}"
BACKEND_URL="http://127.0.0.1:${BACKEND_PORT}"
FRONTEND_URL="http://127.0.0.1:${FRONTEND_PORT}"

echo "==> starting backend (log: $LOG_DIR/backend.log)"
# setsid makes the leg script the leader of a fresh process group, so
# stop-all-linux.sh (or the next start-all-linux.sh run) can cleanly kill the
# whole subtree — uvicorn --reload's worker, npm's vite child, etc.
setsid "$SCRIPT_DIR/start-backend-linux.sh" >"$LOG_DIR/backend.log" 2>&1 &
disown

echo "==> waiting for backend health (${BACKEND_URL}/api/v1/chapters)"
if ! dev_wait_http_ok "${BACKEND_URL}/api/v1/chapters" 90; then
  echo "!! backend did not become healthy in time; see $LOG_DIR/backend.log" >&2
  exit 1
fi

echo "==> starting frontend (log: $LOG_DIR/frontend-react.log)"
setsid "$SCRIPT_DIR/start-frontend-linux.sh" >"$LOG_DIR/frontend-react.log" 2>&1 &
disown

echo "==> waiting for frontend (${FRONTEND_URL})"
if ! dev_wait_http_ok "$FRONTEND_URL" 60; then
  echo "!! frontend did not come up in time; see $LOG_DIR/frontend-react.log" >&2
  exit 1
fi

echo "==> backend:  $BACKEND_URL"
echo "==> frontend: $FRONTEND_URL"
echo "==> logs:     $LOG_DIR/"
echo "==> stop with: scripts/stop-all-linux.sh"
