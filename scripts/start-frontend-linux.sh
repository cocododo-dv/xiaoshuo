#!/usr/bin/env bash
# Linux dev equivalent of start-dev.cmd's React-frontend leg.
# Node 16 (the newest build this CentOS 7 glibc 2.17 host can run) lacks the
# global WebCrypto that Vite 6 needs, so preload crypto-polyfill.cjs.
# Safe to re-run: stops any previous instance (by pidfile, falling back to
# whatever is bound to the port) before starting a fresh one.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
# shellcheck source=lib/dev-lifecycle.sh
source "$SCRIPT_DIR/lib/dev-lifecycle.sh"

RUN_DIR="$REPO_ROOT/.codex-run"
mkdir -p "$RUN_DIR"
PID_FILE="$RUN_DIR/frontend-react.pid"
URL_FILE="$RUN_DIR/frontend-react.url"
PORT="${NOVEL_SYSTEM_FRONTEND_PORT:-5174}"

dev_stop_pidfile "$PID_FILE"
dev_stop_port "$PORT"

cd "$REPO_ROOT/frontend-react"

export NVM_DIR="$HOME/.nvm"
# shellcheck disable=SC1091
[ -s "$NVM_DIR/nvm.sh" ] && . "$NVM_DIR/nvm.sh"
nvm use 16 > /dev/null

export NODE_OPTIONS="--require ./crypto-polyfill.cjs"

echo "http://127.0.0.1:${PORT}" > "$URL_FILE"
echo $$ > "$PID_FILE"
exec npm run dev -- --host 127.0.0.1 --port "$PORT"
