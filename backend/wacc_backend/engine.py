"""Task Engine: a durable job queue with atomic claiming, retries and a pause switch.

The engine only schedules and records work. Running real commands on Windows is the job of the
Execution Backend (T-0009), which must follow docs/EXECUTION_SECURITY.md. Handlers registered here
run in-process and are for safe, internal job kinds only.
"""

import json
from datetime import datetime, timedelta, timezone
from typing import Callable, Dict, List, Optional

from .storage import Storage, StorageError

JOB_STATUSES = ("QUEUED", "RUNNING", "SUCCEEDED", "FAILED", "CANCELLED")
TERMINAL = ("SUCCEEDED", "FAILED", "CANCELLED")
MAX_PAYLOAD_BYTES = 100_000
MAX_RETRY_DELAY = 3600
BASE_RETRY_DELAY = 5


def _now_dt() -> datetime:
    return datetime.now(timezone.utc)


def _fmt(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _job(row) -> dict:
    d = dict(row)
    for key in ("payload", "result"):
        if d.get(key):
            try:
                d[key] = json.loads(d[key])
            except ValueError:
                pass
    return d


class PermanentJobError(Exception):
    """Raised by a handler when retrying cannot help (denied action, bad payload, approval needed)."""


class TaskEngine:
    def __init__(self, storage: Storage):
        self.storage = storage
        self.handlers: Dict[str, Callable[[dict], object]] = {}

    # ------------------------------------------------------------------ flags
    def is_paused(self) -> bool:
        conn = self.storage._connect()
        try:
            r = conn.execute("SELECT value FROM engine_flags WHERE key='paused'").fetchone()
            return bool(r and r["value"] == "1")
        finally:
            conn.close()

    def set_paused(self, paused: bool) -> None:
        with self.storage.tx() as conn:
            conn.execute("UPDATE engine_flags SET value=? WHERE key='paused'", ("1" if paused else "0",))

    # ------------------------------------------------------------------ queue
    def enqueue(self, kind: str, title: str, payload: Optional[dict] = None, project_id: Optional[int] = None,
                priority: int = 5, max_attempts: int = 3, delay_seconds: int = 0) -> dict:
        kind, title = (kind or "").strip(), (title or "").strip()
        if not kind or len(kind) > 60:
            raise StorageError("BAD_KIND", "Job kind must be 1-60 characters")
        if not title or len(title) > 200:
            raise StorageError("BAD_TITLE", "Job title must be 1-200 characters")
        if not 1 <= int(priority) <= 9:
            raise StorageError("BAD_PRIORITY", "Priority must be 1 (urgent) to 9 (low)")
        if not 1 <= int(max_attempts) <= 10:
            raise StorageError("BAD_ATTEMPTS", "max_attempts must be 1-10")
        if int(delay_seconds) < 0:
            raise StorageError("BAD_DELAY", "delay_seconds cannot be negative")
        raw = json.dumps(payload or {})
        if len(raw.encode()) > MAX_PAYLOAD_BYTES:
            raise StorageError("PAYLOAD_TOO_LARGE", f"Payload exceeds {MAX_PAYLOAD_BYTES} bytes")
        now = _now_dt()
        with self.storage.tx() as conn:
            if project_id is not None:
                p = conn.execute("SELECT status FROM projects WHERE id=?", (project_id,)).fetchone()
                if not p:
                    raise StorageError("NOT_FOUND", f"Project {project_id} not found")
                if p["status"] == "ARCHIVED":
                    raise StorageError("PROJECT_ARCHIVED", "Cannot add jobs to an archived project")
            cur = conn.execute(
                "INSERT INTO jobs(project_id, kind, title, payload, priority, max_attempts, run_after, "
                "created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
                (project_id, kind, title, raw, int(priority), int(max_attempts),
                 _fmt(now + timedelta(seconds=int(delay_seconds))), _fmt(now), _fmt(now)))
            return _job(conn.execute("SELECT * FROM jobs WHERE id=?", (cur.lastrowid,)).fetchone())

    def claim_next(self, worker: str, kinds: Optional[List[str]] = None) -> Optional[dict]:
        """Atomically take the best runnable job. Returns None when paused or nothing is due."""
        if not worker or len(worker) > 60:
            raise StorageError("BAD_WORKER", "Worker name must be 1-60 characters")
        if self.is_paused():
            return None
        now = _fmt(_now_dt())
        with self.storage.tx() as conn:
            sql = "SELECT * FROM jobs WHERE status='QUEUED' AND run_after<=?"
            params: list = [now]
            if kinds:
                sql += " AND kind IN (%s)" % ",".join("?" * len(kinds))
                params += list(kinds)
            row = conn.execute(sql + " ORDER BY priority, run_after, id LIMIT 1", params).fetchone()
            if not row:
                return None
            conn.execute(
                "UPDATE jobs SET status='RUNNING', claimed_by=?, attempts=attempts+1, started_at=?, updated_at=? "
                "WHERE id=? AND status='QUEUED'", (worker, now, now, row["id"]))
            return _job(conn.execute("SELECT * FROM jobs WHERE id=?", (row["id"],)).fetchone())

    def complete(self, job_id: int, worker: str, result=None) -> dict:
        return self._finish(job_id, worker, "SUCCEEDED", result=result)

    def fail(self, job_id: int, worker: str, error: str, retry: bool = True) -> dict:
        """Mark a failed attempt. Re-queues with exponential backoff while attempts remain."""
        now = _now_dt()
        with self.storage.tx() as conn:
            job = self._owned_running(conn, job_id, worker)
            if retry and job["attempts"] < job["max_attempts"]:
                delay = min(BASE_RETRY_DELAY * 2 ** (job["attempts"] - 1), MAX_RETRY_DELAY)
                conn.execute(
                    "UPDATE jobs SET status='QUEUED', claimed_by=NULL, error=?, run_after=?, updated_at=? WHERE id=?",
                    (str(error)[:2000], _fmt(now + timedelta(seconds=delay)), _fmt(now), job_id))
            else:
                conn.execute(
                    "UPDATE jobs SET status='FAILED', error=?, finished_at=?, updated_at=? WHERE id=?",
                    (str(error)[:2000], _fmt(now), _fmt(now), job_id))
            return _job(conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone())

    def cancel(self, job_id: int) -> dict:
        now = _fmt(_now_dt())
        with self.storage.tx() as conn:
            job = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
            if not job:
                raise StorageError("NOT_FOUND", f"Job {job_id} not found")
            if job["status"] in TERMINAL:
                raise StorageError("BAD_STATE", f"Job is already {job['status']}")
            conn.execute("UPDATE jobs SET status='CANCELLED', finished_at=?, updated_at=? WHERE id=?",
                         (now, now, job_id))
            return _job(conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone())

    def recover_stale(self, older_than_seconds: int = 900) -> int:
        """Re-queue RUNNING jobs whose worker vanished. Counts as a failed attempt."""
        cutoff = _fmt(_now_dt() - timedelta(seconds=older_than_seconds))
        now = _fmt(_now_dt())
        n = 0
        with self.storage.tx() as conn:
            for job in conn.execute("SELECT * FROM jobs WHERE status='RUNNING' AND started_at<=?", (cutoff,)).fetchall():
                if job["attempts"] < job["max_attempts"]:
                    conn.execute("UPDATE jobs SET status='QUEUED', claimed_by=NULL, error='worker lost', "
                                 "run_after=?, updated_at=? WHERE id=?", (now, now, job["id"]))
                else:
                    conn.execute("UPDATE jobs SET status='FAILED', error='worker lost', finished_at=?, "
                                 "updated_at=? WHERE id=?", (now, now, job["id"]))
                n += 1
        return n

    # ------------------------------------------------------------------ reads
    def get(self, job_id: int) -> Optional[dict]:
        conn = self.storage._connect()
        try:
            r = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
            return _job(r) if r else None
        finally:
            conn.close()

    def list(self, status: Optional[str] = None, project_id: Optional[int] = None, limit: int = 100) -> List[dict]:
        if status and status not in JOB_STATUSES:
            raise StorageError("BAD_STATUS", f"Status must be one of {JOB_STATUSES}")
        sql, params = "SELECT * FROM jobs WHERE 1=1", []
        if status:
            sql += " AND status=?"
            params.append(status)
        if project_id is not None:
            sql += " AND project_id=?"
            params.append(project_id)
        conn = self.storage._connect()
        try:
            rows = conn.execute(sql + " ORDER BY id DESC LIMIT ?", params + [max(1, min(int(limit), 500))]).fetchall()
            return [_job(r) for r in rows]
        finally:
            conn.close()

    def counts(self) -> dict:
        conn = self.storage._connect()
        try:
            out = {s: 0 for s in JOB_STATUSES}
            for r in conn.execute("SELECT status, COUNT(*) c FROM jobs GROUP BY status").fetchall():
                out[r["status"]] = r["c"]
            return out
        finally:
            conn.close()

    # --------------------------------------------------------------- handlers
    def register_handler(self, kind: str, fn: Callable[[dict], object]) -> None:
        self.handlers[kind] = fn

    def run_once(self, worker: str = "engine") -> Optional[dict]:
        """Claim and run one job with a registered in-process handler."""
        job = self.claim_next(worker, kinds=list(self.handlers) or None)
        if not job:
            return None
        handler = self.handlers.get(job["kind"])
        if handler is None:
            return self.fail(job["id"], worker, f"No handler for kind {job['kind']!r}", retry=False)
        try:
            result = handler(job)
        except PermanentJobError as exc:
            return self.fail(job["id"], worker, str(exc), retry=False)
        except Exception as exc:  # a handler crash must never kill the engine
            return self.fail(job["id"], worker, f"{type(exc).__name__}: {exc}")
        return self.complete(job["id"], worker, result)

    # ---------------------------------------------------------------- helpers
    def _owned_running(self, conn, job_id, worker):
        job = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        if not job:
            raise StorageError("NOT_FOUND", f"Job {job_id} not found")
        if job["status"] != "RUNNING":
            raise StorageError("BAD_STATE", f"Job is {job['status']}, expected RUNNING")
        if job["claimed_by"] != worker:
            raise StorageError("FORBIDDEN", "Job is claimed by another worker")
        return job

    def _finish(self, job_id, worker, status, result=None):
        now = _fmt(_now_dt())
        with self.storage.tx() as conn:
            self._owned_running(conn, job_id, worker)
            conn.execute("UPDATE jobs SET status=?, result=?, error=NULL, finished_at=?, updated_at=? WHERE id=?",
                         (status, json.dumps(result) if result is not None else None, now, now, job_id))
            return _job(conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone())
