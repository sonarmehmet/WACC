"""SQLite storage with WAL and versioned migrations.

Projects are archived, never hard-deleted: irreversible deletion needs explicit user approval.
"""

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

MIGRATIONS = [
    # version 1
    """
    CREATE TABLE projects (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL UNIQUE,
        description TEXT NOT NULL DEFAULT '',
        status TEXT NOT NULL DEFAULT 'ACTIVE',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    """,
    # version 2: Task Engine (jobs) and Agent Manager (agent registry), engine flags
    """
    CREATE TABLE jobs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        project_id INTEGER REFERENCES projects(id),
        kind TEXT NOT NULL,
        title TEXT NOT NULL,
        payload TEXT NOT NULL DEFAULT '{}',
        status TEXT NOT NULL DEFAULT 'QUEUED',
        priority INTEGER NOT NULL DEFAULT 5,
        attempts INTEGER NOT NULL DEFAULT 0,
        max_attempts INTEGER NOT NULL DEFAULT 3,
        run_after TEXT NOT NULL,
        claimed_by TEXT,
        result TEXT,
        error TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        started_at TEXT,
        finished_at TEXT
    );
    CREATE INDEX idx_jobs_claim ON jobs(status, run_after, priority);
    CREATE TABLE agent_registry (
        name TEXT PRIMARY KEY,
        role TEXT NOT NULL,
        capabilities TEXT NOT NULL DEFAULT '[]',
        status TEXT NOT NULL DEFAULT 'OFFLINE',
        current_job INTEGER,
        last_seen TEXT,
        registered_at TEXT NOT NULL
    );
    CREATE TABLE engine_flags (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    );
    INSERT INTO engine_flags(key, value) VALUES ('paused', '0');
    """,
]
PROJECT_STATUSES = ("ACTIVE", "PAUSED", "ARCHIVED")


class StorageError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


class Storage:
    def __init__(self, db_path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.migrate()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=10, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=10000")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    @contextmanager
    def tx(self):
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            try:
                yield conn
                conn.execute("COMMIT")
            except BaseException:
                conn.execute("ROLLBACK")
                raise
        finally:
            conn.close()

    def migrate(self) -> int:
        with self.tx() as conn:
            conn.execute("CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL)")
            row = conn.execute("SELECT MAX(version) v FROM schema_version").fetchone()
            current = row["v"] or 0
            for version, sql in enumerate(MIGRATIONS, start=1):
                if version > current:
                    # executescript() would commit mid-transaction, so run statements one by one
                    for statement in _split(sql):
                        conn.execute(statement)
                    conn.execute("INSERT INTO schema_version(version) VALUES (?)", (version,))
                    current = version
            return current

    def schema_version(self) -> int:
        conn = self._connect()
        try:
            return conn.execute("SELECT MAX(version) v FROM schema_version").fetchone()["v"] or 0
        finally:
            conn.close()

    # -------------------------------------------------------------- projects
    def create_project(self, name: str, description: str = "") -> dict:
        name = (name or "").strip()
        if not name or len(name) > 120:
            raise StorageError("BAD_NAME", "Project name must be 1-120 characters")
        if len(description or "") > 5000:
            raise StorageError("BAD_DESCRIPTION", "Description is too long")
        now = _now()
        try:
            with self.tx() as conn:
                cur = conn.execute(
                    "INSERT INTO projects(name, description, created_at, updated_at) VALUES (?,?,?,?)",
                    (name, description or "", now, now))
                return dict(conn.execute("SELECT * FROM projects WHERE id=?", (cur.lastrowid,)).fetchone())
        except sqlite3.IntegrityError:
            raise StorageError("DUPLICATE", f"A project named {name!r} already exists")

    def list_projects(self, include_archived: bool = False) -> List[dict]:
        sql = "SELECT * FROM projects"
        if not include_archived:
            sql += " WHERE status != 'ARCHIVED'"
        conn = self._connect()
        try:
            return [dict(r) for r in conn.execute(sql + " ORDER BY id").fetchall()]
        finally:
            conn.close()

    def get_project(self, project_id: int) -> Optional[dict]:
        conn = self._connect()
        try:
            r = conn.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone()
            return dict(r) if r else None
        finally:
            conn.close()

    def update_project(self, project_id: int, name=None, description=None, status=None) -> dict:
        if status is not None and status not in PROJECT_STATUSES:
            raise StorageError("BAD_STATUS", f"Status must be one of {PROJECT_STATUSES}")
        if name is not None and (not name.strip() or len(name) > 120):
            raise StorageError("BAD_NAME", "Project name must be 1-120 characters")
        try:
            with self.tx() as conn:
                cur = conn.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone()
                if not cur:
                    raise StorageError("NOT_FOUND", f"Project {project_id} not found")
                conn.execute(
                    "UPDATE projects SET name=?, description=?, status=?, updated_at=? WHERE id=?",
                    (name.strip() if name is not None else cur["name"],
                     description if description is not None else cur["description"],
                     status or cur["status"], _now(), project_id))
                return dict(conn.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone())
        except sqlite3.IntegrityError:
            raise StorageError("DUPLICATE", "Another project already uses that name")

    def archive_project(self, project_id: int) -> dict:
        return self.update_project(project_id, status="ARCHIVED")


def _split(script: str):
    return [s.strip() for s in script.split(";") if s.strip()]
