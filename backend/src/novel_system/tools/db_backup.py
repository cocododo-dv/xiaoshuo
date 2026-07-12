"""数据库备份 / WAL 一致性快照 / 恢复演练（结果闭环治理设计 §8 Wave 7 项 5）。

针对 SQLite：用**在线备份 API**（``sqlite3.Connection.backup``）产出一致性单文件快照——
即使写入还在 WAL 里（未 checkpoint），备份 API 复制的是逻辑数据库，快照自洽。备份前先
``wal_checkpoint(TRUNCATE)`` 让主库尽量落盘；备份后写 sidecar ``.meta.json``
（sha256 + 页数 + 时间戳 + 源）。恢复原子替换（临时文件 → ``os.replace``），前置
``verify`` 用 ``PRAGMA integrity_check`` + checksum 双校验，损坏备份拒绝、不碰现库。

纯运维工具，不导入 ORM / settings 硬依赖——可对任意 sqlite 文件独立跑。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import sys
import tempfile
from typing import Any

_META_SUFFIX = ".meta.json"


def resolve_sqlite_path(url_or_path: str) -> str:
    """把 ``sqlite:///rel`` / ``sqlite:////abs`` / 裸路径统一解析为文件路径。"""
    if url_or_path.startswith("sqlite:////"):
        return "/" + url_or_path[len("sqlite:////"):]
    if url_or_path.startswith("sqlite:///"):
        return url_or_path[len("sqlite:///"):]
    if url_or_path.startswith("sqlite://"):  # sqlite://（memory 等）无文件
        return url_or_path[len("sqlite://"):]
    return url_or_path


def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _integrity_ok(path: str) -> str:
    conn = sqlite3.connect(path)
    try:
        row = conn.execute("PRAGMA integrity_check").fetchone()
        return (row[0] if row else "unknown")
    finally:
        conn.close()


def backup_database(src: str, dst: str) -> dict[str, Any]:
    """一致性备份 src → dst（单文件），并写 dst.meta.json。返回元数据。"""
    src_path = resolve_sqlite_path(src)
    dst_path = resolve_sqlite_path(dst)
    if not os.path.exists(src_path):
        raise FileNotFoundError(src_path)
    src_conn = sqlite3.connect(src_path)
    try:
        # WAL checkpoint（尽力）——让主库落盘；即便失败，backup API 仍产一致快照
        try:
            src_conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        except sqlite3.DatabaseError:
            pass
        # 目标先删（含可能残留的 -wal/-shm），再写全新单文件
        for suffix in ("", "-wal", "-shm"):
            p = dst_path + suffix
            if os.path.exists(p):
                os.remove(p)
        dst_conn = sqlite3.connect(dst_path)
        try:
            src_conn.backup(dst_conn)  # 在线备份 API：一致性逻辑复制
        finally:
            dst_conn.close()
    finally:
        src_conn.close()
    meta = {
        "source": src_path,
        "checksum": _sha256(dst_path),
        "page_count": _page_count(dst_path),
        "integrity": _integrity_ok(dst_path),
        "created_at": _utcnow(),
        "tool": "db_backup.v1",
    }
    with open(dst_path + _META_SUFFIX, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    return meta


def _page_count(path: str) -> int:
    conn = sqlite3.connect(path)
    try:
        row = conn.execute("PRAGMA page_count").fetchone()
        return int(row[0]) if row else 0
    finally:
        conn.close()


def verify_backup(path: str) -> dict[str, Any]:
    """双校验：integrity_check == ok 且（有 meta 时）checksum 匹配。"""
    file_path = resolve_sqlite_path(path)
    result: dict[str, Any] = {"ok": False, "integrity": None, "checksum_ok": None}
    if not os.path.exists(file_path):
        result["error"] = "missing"
        return result
    try:
        result["integrity"] = _integrity_ok(file_path)
    except sqlite3.DatabaseError as exc:
        result["error"] = str(exc)
        return result
    meta_path = file_path + _META_SUFFIX
    if os.path.exists(meta_path):
        try:
            meta = json.loads(open(meta_path, encoding="utf-8").read())
            result["checksum_ok"] = _sha256(file_path) == meta.get("checksum")
        except Exception:
            result["checksum_ok"] = False
    result["ok"] = result["integrity"] == "ok" and (result["checksum_ok"] is not False)
    return result


def restore_database(backup_path: str, dst: str) -> dict[str, Any]:
    """校验通过才原子替换 dst；损坏备份拒绝、绝不碰现库。"""
    backup_file = resolve_sqlite_path(backup_path)
    dst_file = resolve_sqlite_path(dst)
    v = verify_backup(backup_file)
    if not v["ok"]:
        raise ValueError(f"refusing to restore from unverified backup: {v}")
    dst_dir = os.path.dirname(os.path.abspath(dst_file)) or "."
    fd, tmp = tempfile.mkstemp(dir=dst_dir, suffix=".restore.tmp")
    os.close(fd)
    # 用备份 API 写临时文件（而非裸拷，确保目标为干净单文件）
    src_conn = sqlite3.connect(backup_file)
    try:
        tmp_conn = sqlite3.connect(tmp)
        try:
            src_conn.backup(tmp_conn)
        finally:
            tmp_conn.close()
    finally:
        src_conn.close()
    # 清 dst 的 -wal/-shm，再原子替换
    for suffix in ("-wal", "-shm"):
        p = dst_file + suffix
        if os.path.exists(p):
            os.remove(p)
    os.replace(tmp, dst_file)
    return {"restored": dst_file, "from": backup_file, "integrity": _integrity_ok(dst_file)}


def _utcnow() -> str:
    import datetime

    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="SQLite 备份 / 恢复 / 校验（Wave 7 §8）")
    sub = parser.add_mutually_exclusive_group(required=True)
    sub.add_argument("--backup", nargs=2, metavar=("SRC", "DST"))
    sub.add_argument("--restore", nargs=2, metavar=("BACKUP", "DST"))
    sub.add_argument("--verify", metavar="PATH")
    args = parser.parse_args(argv)
    try:
        if args.backup:
            meta = backup_database(*args.backup)
            print(json.dumps(meta, ensure_ascii=False, indent=2))
            return 0
        if args.restore:
            print(json.dumps(restore_database(*args.restore), ensure_ascii=False, indent=2))
            return 0
        v = verify_backup(args.verify)
        print(json.dumps(v, ensure_ascii=False, indent=2))
        return 0 if v["ok"] else 1
    except Exception as exc:  # noqa: BLE001 — CLI 边界统一转退出码
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_main())
