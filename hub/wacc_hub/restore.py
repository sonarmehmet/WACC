"""Backup and restore of the SQLite databases (Hub and backend).

Restore is deliberately cautious: it only accepts a plain file name from backups/, refuses while the
services are running, checks the file is a healthy database of the right kind, and keeps the database it
replaces (data/pre-restore-<time>-<name>) instead of deleting it.
"""

import re
import socket
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, Optional

NAME_RE = re.compile(r"^(hub|backend)_\d{8}_\d{6}\.db$")
REQUIRED_TABLES = {"hub": {"messages", "tasks", "agents"}, "backend": {"jobs", "approvals"}}
PORTS = {"hub": 8765, "backend": 8800}


class RestoreError(Exception):
    pass


def copy_db(src: Path, dst: Path) -> None:
    """Consistent copy of a (possibly WAL-mode) database."""
    s = sqlite3.connect(str(src))
    d = sqlite3.connect(str(dst))
    try:
        with d:
            s.backup(d)
    finally:
        s.close()
        d.close()


def backup_databases(dbs: Dict[str, Path], dest: Path, stamp: Optional[str] = None) -> Dict[str, str]:
    stamp = stamp or datetime.now().strftime("%Y%m%d_%H%M%S")
    dest.mkdir(parents=True, exist_ok=True)
    out = {}
    for kind, path in dbs.items():
        if Path(path).exists():
            copy_db(Path(path), dest / f"{kind}_{stamp}.db")
            out[kind] = f"backups/{kind}_{stamp}.db"
    return out


def port_open(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.5):
            return True
    except OSError:
        return False


def check_backup(path: Path, kind: str) -> None:
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    except sqlite3.Error as exc:
        raise RestoreError(f"Yedek açılamadı: {exc}")
    try:
        if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise RestoreError("Yedek bozuk (integrity_check başarısız)")
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    except sqlite3.Error as exc:
        raise RestoreError(f"Bu bir WACC veritabanı yedeği değil: {exc}")
    finally:
        conn.close()
    missing = REQUIRED_TABLES[kind] - tables
    if missing:
        raise RestoreError(f"Yedekte beklenen tablolar yok ({kind}): {', '.join(sorted(missing))}")


def restore(name: str, backups_dir: Path, targets: Dict[str, Path], data_dir: Path,
            is_running: Callable[[int], bool] = port_open, now: Optional[datetime] = None) -> dict:
    m = NAME_RE.match(name or "")
    if not m:
        raise RestoreError("Yedek adı hub_YYYYMMDD_HHMMSS.db ya da backend_YYYYMMDD_HHMMSS.db biçiminde olmalı "
                           "(yalnızca dosya adı, yol değil)")
    kind = m.group(1)
    src = Path(backups_dir) / name
    if not src.is_file():
        raise RestoreError(f"Yedek bulunamadı: backups/{name}")
    if is_running(PORTS[kind]):
        raise RestoreError(f"{kind} servisi çalışıyor (port {PORTS[kind]}). Önce tüm WACC pencerelerini kapat, sonra yeniden dene.")
    check_backup(src, kind)

    target = Path(targets[kind])
    data_dir = Path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    stamp = (now or datetime.now()).strftime("%Y%m%d_%H%M%S")
    kept = None
    if target.exists():
        kept = data_dir / f"pre-restore-{stamp}-{target.name}"
        copy_db(target, kept)
    for suffix in ("", "-wal", "-shm"):  # stale WAL files would be replayed on top of the restored file
        Path(str(target) + suffix).unlink(missing_ok=True)
    copy_db(src, target)
    return {"restored": f"backups/{name}", "kind": kind, "previous_kept_as": str(kept.name) if kept else None}
