#!/usr/bin/env bash
# Linux dev equivalent of start-dev.cmd's React-frontend leg.
# Node 16 (the newest build this CentOS 7 glibc 2.17 host can run) lacks the
# global WebCrypto that Vite 6 needs, so preload crypto-polyfill.cjs.
set -euo pipefail
cd "$(dirname "$0")/../frontend-react"

export NVM_DIR="$HOME/.nvm"
# shellcheck disable=SC1091
[ -s "$NVM_DIR/nvm.sh" ] && . "$NVM_DIR/nvm.sh"
nvm use 16 > /dev/null

export NODE_OPTIONS="--require ./crypto-polyfill.cjs"
exec npm run dev -- --host 127.0.0.1 --port "${NOVEL_SYSTEM_FRONTEND_PORT:-5174}"
