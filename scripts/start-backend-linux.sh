#!/usr/bin/env bash
# Linux dev equivalent of start-dev.cmd's backend leg (this box has no PowerShell).
set -euo pipefail
cd "$(dirname "$0")/../backend"

export NOVEL_SYSTEM_VECTOR_BACKEND=memory
export NOVEL_SYSTEM_CONFIG_SECRET="${NOVEL_SYSTEM_CONFIG_SECRET:-dev-local-secret-change-me}"

.venv/bin/python -m alembic upgrade head

exec .venv/bin/python -m uvicorn novel_system.api.app:create_app --factory --reload \
  --host 127.0.0.1 --port "${NOVEL_SYSTEM_BACKEND_PORT:-8000}" --app-dir src
