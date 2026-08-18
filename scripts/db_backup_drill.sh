#!/usr/bin/env bash
# 数据库备份 / WAL 一致性 / 恢复演练（结果闭环治理设计 §8 Wave 7 项 5）。
#
# 演练：备份现库 → 复制一份「生产副本」→ 故意破坏它 → 从备份恢复 → integrity_check 绿。
# 用真实 SQLite 在线备份 API（backend/src/novel_system/tools/db_backup.py），不动真正现库。
#
# 先停止应用写入，再运行：bash scripts/db_backup_drill.sh [DB_PATH]
#   DB_PATH 缺省取 backend/novel_system.db；也可传 sqlite URL / 任意 sqlite 文件。
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_DIR="$REPO_ROOT/backend"
PY="${PYTHON:-$REPO_ROOT/backend/.venv/bin/python}"
[ -x "$PY" ] || PY="python3"
export PYTHONPATH="$BACKEND_DIR/src${PYTHONPATH:+:$PYTHONPATH}"

SRC_INPUT="${1:-$REPO_ROOT/backend/novel_system.db}"
# 解析 sqlite URL → 文件路径（复用工具的解析逻辑）
SRC="$("$PY" -c "import os,sys; from novel_system.tools.db_backup import resolve_sqlite_path as r; print(os.path.abspath(r(sys.argv[1])))" "$SRC_INPUT")"

if [ ! -f "$SRC" ]; then
  echo "[drill] 源库不存在：$SRC —— 先启动一次服务或建库再演练。" >&2
  exit 2
fi

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
COPY="$WORK/prod_copy.db"
BACKUP="$WORK/backup.db"

echo "[drill] 1/5 复制生产副本（不动真正现库 $SRC）"
"$PY" -m novel_system.tools.db_backup --backup "$SRC" "$COPY" >/dev/null

echo "[drill] 2/5 对副本做一致性备份"
"$PY" -m novel_system.tools.db_backup --backup "$COPY" "$BACKUP" >/dev/null

echo "[drill] 3/5 校验备份"
"$PY" -m novel_system.tools.db_backup --verify "$BACKUP"

echo "[drill] 4/5 故意破坏生产副本"
head -c 128 /dev/zero > "$COPY"

echo "[drill] 5/5 从备份恢复副本并校验"
"$PY" -m novel_system.tools.db_backup --restore "$BACKUP" "$COPY" >/dev/null
"$PY" -m novel_system.tools.db_backup --verify "$COPY"

echo "[drill] ✅ 恢复演练通过：备份可用、恢复后 integrity_check 绿。"
