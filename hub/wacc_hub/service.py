"""Core hub logic: messages, tasks, locks, decisions, checkpoints, emergency stop.

All state-changing methods run inside one BEGIN IMMEDIATE transaction.
Every agent-supplied value is treated as untrusted input and validated.
"""

import json
import posixpath
import sqlite3
import time
import uuid
from contextlib import contextmanager

from . import db
from .models import (
    ACTIVE_TASK_STATUSES, AGENTS, BROADCAST, DEFAULT_LOCK_TTL, LEADERS,
    MAX_CONTENT, MAX_DELIVERY_ATTEMPTS, MAX_DISCUSSION_ROUNDS, MAX_LOCK_TTL,
    MAX_SUBJECT, MESSAGE_TYPES, ONLINE_WINDOW, PRIORITIES, TASK_STATUSES, WORKERS,
)


class HubError(Exception):
    """Business-rule failure. `code` is a stable machine-readable string."""

    def __init__(self, code: str, message: str = "", detail=None):
        super().__init__(f"{code}: {message}" if message else code)
        self.code = code
        self.message = message or code
        self.detail = detail


def _row(r):
    if r is None:
        return None
    d = dict(r)
    for key in ("related_files", "affected_files", "dependencies"):
        if key in d and isinstance(d[key], str):
            try:
                d[key] = json.loads(d[key])
            except ValueError:
                d[key] = []
    return d


def _rows(rs):
    return [_row(r) for r in rs]


def normalize_path(path: str) -> str:
    if not isinstance(path, str) or not path.strip():
        raise HubError("BAD_PATH", "Path is empty")
    p = path.replace("\\", "/").strip()
    if p.startswith("/") or (len(p) > 1 and p[1] == ":"):
        raise HubError("BAD_PATH", "Absolute paths are not allowed; use repo-relative paths")
    p = posixpath.normpath(p)
    if p == ".." or p.startswith("../") or p == ".":
        raise HubError("BAD_PATH", "Path escapes the repository")
    return p


def _overlaps(a: str, b: str) -> bool:
    return a == b or a.startswith(b + "/") or b.startswith(a + "/")


class Hub:
    def __init__(self, db_path=None):
        self.db_path = db_path or db.DEFAULT_DB
        db.init_db(self.db_path)

    # ------------------------------------------------------------ plumbing
    @contextmanager
    def tx(self):
        conn = db.connect(self.db_path)
        try:
            for attempt in range(5):
                try:
                    conn.execute("BEGIN IMMEDIATE")
                    break
                except sqlite3.OperationalError as exc:
                    if "locked" in str(exc) and attempt < 4:
                        time.sleep(0.2 * (attempt + 1))
                        continue
                    raise
            try:
                yield conn
                conn.execute("COMMIT")
            except BaseException:
                conn.execute("ROLLBACK")
                raise
        finally:
            conn.close()

    def query(self, sql, params=()):
        conn = db.connect(self.db_path)
        try:
            return _rows(conn.execute(sql, params).fetchall())
        finally:
            conn.close()

    def query_one(self, sql, params=()):
        rows = self.query(sql, params)
        return rows[0] if rows else None

    @staticmethod
    def _audit(conn, actor, action, detail=""):
        conn.execute(
            "INSERT INTO audit_log(ts, actor, action, detail) VALUES (?,?,?,?)",
            (db.utcnow(), actor, action, str(detail)[:2000]),
        )

    @staticmethod
    def _check_agent(agent, allow_user=True):
        if agent not in AGENTS or (agent == "user" and not allow_user):
            raise HubError("UNKNOWN_AGENT", f"Unknown agent: {agent!r}")

    @staticmethod
    def _stopped(conn) -> bool:
        r = conn.execute("SELECT value FROM system_flags WHERE key='emergency_stop'").fetchone()
        return bool(r and r["value"] == "1")

    def _guard(self, conn, actor):
        if self._stopped(conn) and actor != "user":
            raise HubError("EMERGENCY_STOP", "Emergency stop is active; only the user may resume")

    @staticmethod
    def _touch(conn, agent):
        conn.execute("UPDATE agents SET last_seen=? WHERE agent_id=?", (db.utcnow(), agent))

    # ------------------------------------------------------------ messages
    def _send(self, conn, sender, receiver, message_type, subject, content="",
              conversation_id=None, task_id=None, priority="NORMAL",
              related_files=None, related_commit=None, response_required=False,
              in_reply_to=None, idempotency_key=None, escalate=True):
        self._check_agent(sender)
        if receiver != BROADCAST:
            self._check_agent(receiver)
        if message_type not in MESSAGE_TYPES:
            raise HubError("BAD_TYPE", f"Unknown message type: {message_type}")
        if priority not in PRIORITIES:
            raise HubError("BAD_PRIORITY", f"Unknown priority: {priority}")
        subject = (subject or "").strip()
        content = content or ""
        if not subject or len(subject) > MAX_SUBJECT:
            raise HubError("BAD_SUBJECT", f"Subject must be 1-{MAX_SUBJECT} characters")
        if len(content) > MAX_CONTENT:
            raise HubError("CONTENT_TOO_LONG", f"Content exceeds {MAX_CONTENT} characters")
        files = [normalize_path(f) for f in (related_files or [])]
        if task_id and not conn.execute("SELECT 1 FROM tasks WHERE task_id=?", (task_id,)).fetchone():
            raise HubError("UNKNOWN_TASK", f"Unknown task: {task_id}")

        if receiver == BROADCAST:
            targets = [a for a in AGENTS if a != sender]
        else:
            targets = [receiver]
        conv = conversation_id or (f"CONV-{task_id}" if task_id else f"CONV-{uuid.uuid4().hex[:10]}")
        results = []
        for target in targets:
            key = f"{idempotency_key}:{target}" if idempotency_key else None
            if key:
                existing = conn.execute("SELECT * FROM messages WHERE idempotency_key=?", (key,)).fetchone()
                if existing:
                    results.append(_row(existing))
                    continue
            now = db.utcnow()
            mid = f"MSG-{uuid.uuid4().hex[:12]}"
            conn.execute(
                """INSERT INTO messages(message_id, conversation_id, task_id, sender, receiver,
                   timestamp, message_type, priority, subject, content, related_files,
                   related_commit, response_required, status, in_reply_to, idempotency_key,
                   delivery_attempts, delivered_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?, 'DELIVERED', ?, ?, 1, ?)""",
                (mid, conv, task_id, sender, target, now, message_type, priority, subject,
                 content, json.dumps(files), related_commit, 1 if response_required else 0,
                 in_reply_to, key, now),
            )
            results.append(_row(conn.execute("SELECT * FROM messages WHERE message_id=?", (mid,)).fetchone()))
        if in_reply_to:
            conn.execute(
                "UPDATE messages SET status='ANSWERED', answered_at=? "
                "WHERE message_id=? AND receiver=? AND status IN ('DELIVERED','READ')",
                (db.utcnow(), in_reply_to, sender),
            )
        conn.execute(
            "UPDATE agents SET last_message_at=?, last_seen=? WHERE agent_id=?",
            (db.utcnow(), db.utcnow(), sender),
        )
        if escalate:
            self._check_escalation(conn, conv)
        return results

    def send_message(self, sender, receiver, message_type, subject, content="", **kw):
        with self.tx() as conn:
            self._guard(conn, sender)
            res = self._send(conn, sender, receiver, message_type, subject, content, **kw)
            self._audit(conn, sender, "send_message", f"{message_type} -> {receiver}: {subject}")
        return res[0] if len(res) == 1 else res

    def _check_escalation(self, conn, conv):
        if conn.execute("SELECT 1 FROM escalations WHERE conversation_id=?", (conv,)).fetchone():
            return
        if conn.execute("SELECT 1 FROM decisions WHERE conversation_id=?", (conv,)).fetchone():
            return
        n = conn.execute(
            "SELECT COUNT(*) c FROM messages WHERE conversation_id=? "
            "AND message_type IN ('HELP_REQUEST','HELP_RESPONSE','REVIEW_REQUEST','REVIEW_RESULT',"
            "'INTEGRATION_REQUEST','INTEGRATION_RESULT','BUG_REPORT','BUG_FIXED')",
            (conv,),
        ).fetchone()["c"]
        if n < MAX_DISCUSSION_ROUNDS:
            return
        conn.execute("INSERT INTO escalations(conversation_id, created_at) VALUES (?,?)", (conv, db.utcnow()))
        text = (f"Conversation {conv} reached {n} messages without a recorded decision. "
                "claude1 must prepare a decision proposal and present it to the user.")
        for target in ("claude1", "user"):
            self._send(conn, "claude1" if target == "user" else "user", target, "SYSTEM_ALERT",
                       "Discussion limit reached", text, conversation_id=conv,
                       priority="HIGH", response_required=True, escalate=False)

    def inbox(self, agent, unread_only=False, limit=100):
        self._check_agent(agent)
        sql = "SELECT * FROM messages WHERE receiver=?"
        if unread_only:
            sql += " AND status='DELIVERED'"
        sql += " ORDER BY timestamp DESC LIMIT ?"
        return self.query(sql, (agent, int(limit)))

    def sent(self, agent, limit=100):
        self._check_agent(agent)
        return self.query("SELECT * FROM messages WHERE sender=? ORDER BY timestamp DESC LIMIT ?",
                          (agent, int(limit)))

    def outbox(self, agent):
        self._check_agent(agent)
        return self.query("SELECT * FROM messages WHERE sender=? AND status IN ('QUEUED','FAILED') "
                          "ORDER BY timestamp", (agent,))

    def pending_responses(self, agent):
        """Messages addressed to `agent` that still need an answer from it."""
        self._check_agent(agent)
        return self.query("SELECT * FROM messages WHERE receiver=? AND response_required=1 "
                          "AND status IN ('DELIVERED','READ') ORDER BY timestamp", (agent,))

    def awaiting_reply(self, agent):
        """Messages `agent` sent that are still waiting for an answer."""
        self._check_agent(agent)
        return self.query("SELECT * FROM messages WHERE sender=? AND response_required=1 "
                          "AND status IN ('DELIVERED','READ') ORDER BY timestamp", (agent,))

    def mark_read(self, agent, message_id):
        with self.tx() as conn:
            self._guard(conn, agent)
            m = conn.execute("SELECT * FROM messages WHERE message_id=?", (message_id,)).fetchone()
            if not m:
                raise HubError("UNKNOWN_MESSAGE", message_id)
            if m["receiver"] != agent:
                raise HubError("FORBIDDEN", "Only the receiver can mark a message as read")
            if m["status"] == "DELIVERED":
                conn.execute("UPDATE messages SET status='READ', read_at=? WHERE message_id=?",
                             (db.utcnow(), message_id))
            self._touch(conn, agent)
            return _row(conn.execute("SELECT * FROM messages WHERE message_id=?", (message_id,)).fetchone())

    def mark_answered(self, agent, message_id):
        with self.tx() as conn:
            self._guard(conn, agent)
            m = conn.execute("SELECT * FROM messages WHERE message_id=?", (message_id,)).fetchone()
            if not m:
                raise HubError("UNKNOWN_MESSAGE", message_id)
            if m["receiver"] != agent:
                raise HubError("FORBIDDEN", "Only the receiver can answer a message")
            conn.execute("UPDATE messages SET status='ANSWERED', answered_at=COALESCE(answered_at, ?) "
                         "WHERE message_id=?", (db.utcnow(), message_id))
            return _row(conn.execute("SELECT * FROM messages WHERE message_id=?", (message_id,)).fetchone())

    def retry_undelivered(self):
        """Re-deliver QUEUED/FAILED messages; give up after MAX_DELIVERY_ATTEMPTS."""
        done = failed = 0
        with self.tx() as conn:
            for m in conn.execute("SELECT message_id, delivery_attempts FROM messages "
                                  "WHERE status IN ('QUEUED','FAILED')").fetchall():
                if m["delivery_attempts"] >= MAX_DELIVERY_ATTEMPTS:
                    conn.execute("UPDATE messages SET status='FAILED' WHERE message_id=?", (m["message_id"],))
                    failed += 1
                else:
                    conn.execute("UPDATE messages SET status='DELIVERED', delivered_at=?, "
                                 "delivery_attempts=delivery_attempts+1 WHERE message_id=?",
                                 (db.utcnow(), m["message_id"]))
                    done += 1
        return {"redelivered": done, "failed": failed}

    def feed(self, limit=200, conversation_id=None):
        """Shared conversation stream for the user-facing panel (oldest first)."""
        if conversation_id:
            rows = self.query("SELECT * FROM messages WHERE conversation_id=? ORDER BY timestamp DESC LIMIT ?",
                              (conversation_id, int(limit)))
        else:
            rows = self.query("SELECT * FROM messages ORDER BY timestamp DESC LIMIT ?", (int(limit),))
        return list(reversed(rows))

    # --------------------------------------------------------------- tasks
    def _next_task_id(self, conn):
        r = conn.execute("SELECT MAX(CAST(SUBSTR(task_id, 3) AS INTEGER)) m FROM tasks").fetchone()
        return f"T-{(r['m'] or 0) + 1:04d}"

    def create_task(self, actor, title, description="", owner=None, affected_files=None,
                    dependencies=None, acceptance="", test_criteria="", priority="NORMAL",
                    branch=None, idempotency_key=None):
        if actor not in LEADERS:
            raise HubError("FORBIDDEN", "Only claude1 or the user can create/assign tasks")
        if priority not in PRIORITIES:
            raise HubError("BAD_PRIORITY", priority)
        if owner is not None:
            self._check_agent(owner, allow_user=False)
        files = [normalize_path(f) for f in (affected_files or [])]
        deps = list(dependencies or [])
        with self.tx() as conn:
            self._guard(conn, actor)
            if not (title or "").strip():
                raise HubError("BAD_TITLE", "Title is required")
            for d in deps:
                if not conn.execute("SELECT 1 FROM tasks WHERE task_id=?", (d,)).fetchone():
                    raise HubError("UNKNOWN_TASK", f"Dependency not found: {d}")
            tid = self._next_task_id(conn)
            now = db.utcnow()
            status = "ASSIGNED" if owner else "BACKLOG"
            conn.execute(
                """INSERT INTO tasks(task_id, title, description, owner, creator, affected_files,
                   dependencies, acceptance, test_criteria, status, priority, branch, created_at, updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (tid, title.strip(), description, owner, actor, json.dumps(files), json.dumps(deps),
                 acceptance, test_criteria, status, priority, branch, now, now),
            )
            if owner:
                body = (f"{description}\n\nAffected files: {', '.join(files) or '-'}\n"
                        f"Dependencies: {', '.join(deps) or '-'}\nAcceptance: {acceptance or '-'}\n"
                        f"Test criteria: {test_criteria or '-'}\nBranch: {branch or '-'}")
                self._send(conn, actor, owner, "TASK_ASSIGNMENT", f"[{tid}] {title.strip()}", body,
                           task_id=tid, priority=priority, related_files=files,
                           response_required=True, idempotency_key=idempotency_key)
            self._audit(conn, actor, "create_task", f"{tid} owner={owner}")
            return _row(conn.execute("SELECT * FROM tasks WHERE task_id=?", (tid,)).fetchone())

    def assign_task(self, actor, task_id, owner):
        if actor not in LEADERS:
            raise HubError("FORBIDDEN", "Only claude1 or the user can assign tasks")
        self._check_agent(owner, allow_user=False)
        with self.tx() as conn:
            self._guard(conn, actor)
            t = conn.execute("SELECT * FROM tasks WHERE task_id=?", (task_id,)).fetchone()
            if not t:
                raise HubError("UNKNOWN_TASK", task_id)
            conn.execute("UPDATE tasks SET owner=?, status='ASSIGNED', updated_at=? WHERE task_id=?",
                         (owner, db.utcnow(), task_id))
            self._send(conn, actor, owner, "TASK_ASSIGNMENT", f"[{task_id}] {t['title']}",
                       t["description"], task_id=task_id, priority=t["priority"],
                       response_required=True)
            self._audit(conn, actor, "assign_task", f"{task_id} -> {owner}")
            return _row(conn.execute("SELECT * FROM tasks WHERE task_id=?", (task_id,)).fetchone())

    def get_task(self, task_id):
        return self.query_one("SELECT * FROM tasks WHERE task_id=?", (task_id,))

    def list_tasks(self, owner=None, status=None):
        sql, params = "SELECT * FROM tasks WHERE 1=1", []
        if owner:
            sql += " AND owner=?"
            params.append(owner)
        if status:
            sql += " AND status=?"
            params.append(status)
        return self.query(sql + " ORDER BY task_id", params)

    def accept_task(self, agent, task_id):
        with self.tx() as conn:
            self._guard(conn, agent)
            t = conn.execute("SELECT * FROM tasks WHERE task_id=?", (task_id,)).fetchone()
            if not t:
                raise HubError("UNKNOWN_TASK", task_id)
            if t["owner"] != agent:
                raise HubError("FORBIDDEN", "Task is not assigned to you")
            if t["status"] != "ASSIGNED":
                raise HubError("BAD_STATE", f"Task is {t['status']}, expected ASSIGNED")
            conn.execute("UPDATE tasks SET status='ACCEPTED', updated_at=? WHERE task_id=?",
                         (db.utcnow(), task_id))
            conn.execute("UPDATE agents SET status='ACTIVE', current_task=?, last_seen=? WHERE agent_id=?",
                         (task_id, db.utcnow(), agent))
            assignment = conn.execute(
                "SELECT message_id FROM messages WHERE task_id=? AND receiver=? "
                "AND message_type='TASK_ASSIGNMENT' ORDER BY timestamp DESC LIMIT 1",
                (task_id, agent)).fetchone()
            self._send(conn, agent, t["creator"], "TASK_ACCEPTED", f"[{task_id}] accepted",
                       f"{agent} accepted {task_id}.", task_id=task_id,
                       in_reply_to=assignment["message_id"] if assignment else None)
            self._audit(conn, agent, "accept_task", task_id)
            return _row(conn.execute("SELECT * FROM tasks WHERE task_id=?", (task_id,)).fetchone())

    def set_task_status(self, actor, task_id, status, commit=None, note=None):
        if status not in TASK_STATUSES:
            raise HubError("BAD_STATUS", status)
        with self.tx() as conn:
            self._guard(conn, actor)
            t = conn.execute("SELECT * FROM tasks WHERE task_id=?", (task_id,)).fetchone()
            if not t:
                raise HubError("UNKNOWN_TASK", task_id)
            if actor != t["owner"] and actor not in LEADERS:
                raise HubError("FORBIDDEN", "Only the owner or a leader can change task status")
            if t["status"] in ("COMPLETED", "CANCELLED") and actor != "user":
                raise HubError("BAD_STATE", f"Task is already {t['status']}")
            if status == "BLOCKED" and not (note or "").strip():
                raise HubError("NOTE_REQUIRED", "A blocker description is required")
            if status == "COMPLETED" and not commit and not t["commit_hash"]:
                raise HubError("COMMIT_REQUIRED", "Provide the commit hash that completes the task")
            if status == "COMPLETED":
                for d in json.loads(t["dependencies"]):
                    dep = conn.execute("SELECT status FROM tasks WHERE task_id=?", (d,)).fetchone()
                    if dep and dep["status"] != "COMPLETED":
                        raise HubError("DEPENDENCY_OPEN", f"Dependency {d} is {dep['status']}")
            conn.execute(
                "UPDATE tasks SET status=?, commit_hash=COALESCE(?, commit_hash), "
                "note=COALESCE(?, note), updated_at=? WHERE task_id=?",
                (status, commit, note, db.utcnow(), task_id))
            if commit:
                conn.execute("UPDATE agents SET last_commit=? WHERE agent_id=?", (commit, t["owner"] or actor))
            if status in ("COMPLETED", "BLOCKED", "CANCELLED"):
                conn.execute("DELETE FROM locks WHERE task_id=?", (task_id,))
                if t["owner"]:
                    conn.execute("UPDATE agents SET current_task=NULL, status='IDLE' WHERE agent_id=? "
                                 "AND current_task=?", (t["owner"], task_id))
            if status in ("COMPLETED", "BLOCKED"):
                mtype = "TASK_COMPLETED" if status == "COMPLETED" else "TASK_BLOCKED"
                recipients = {t["creator"], "claude1"} - {actor}
                for r in recipients:
                    self._send(conn, actor, r, mtype, f"[{task_id}] {status.lower()}",
                               note or "", task_id=task_id, related_commit=commit,
                               priority="HIGH" if status == "BLOCKED" else "NORMAL",
                               response_required=(status == "BLOCKED"))
            self._audit(conn, actor, "set_task_status", f"{task_id} -> {status}")
            return _row(conn.execute("SELECT * FROM tasks WHERE task_id=?", (task_id,)).fetchone())

    # --------------------------------------------------------------- locks
    def acquire_lock(self, agent, path, task_id=None, ttl=DEFAULT_LOCK_TTL, takeover=False):
        if agent not in WORKERS:
            raise HubError("FORBIDDEN", "Only worker agents can hold locks")
        path = normalize_path(path)
        ttl = max(30, min(int(ttl), MAX_LOCK_TTL))
        with self.tx() as conn:
            self._guard(conn, agent)
            now = db.utcnow()
            for lk in conn.execute("SELECT * FROM locks").fetchall():
                if not _overlaps(lk["path"], path):
                    continue
                if lk["owner"] == agent:
                    continue
                if lk["expires_at"] > now:
                    raise HubError("LOCKED", f"{lk['path']} is locked by {lk['owner']} until {lk['expires_at']}",
                                   {"path": lk["path"], "owner": lk["owner"], "expires_at": lk["expires_at"]})
                if not takeover:
                    cp = conn.execute("SELECT * FROM checkpoints WHERE agent_id=? ORDER BY checkpoint_id DESC LIMIT 1",
                                      (lk["owner"],)).fetchone()
                    raise HubError(
                        "STALE_LOCK",
                        f"{lk['path']} has an expired lock from {lk['owner']}. Inspect git status and the "
                        "checkpoint, then retry with takeover=True.",
                        {"path": lk["path"], "owner": lk["owner"], "checkpoint": _row(cp)})
                conn.execute("DELETE FROM locks WHERE path=?", (lk["path"],))
                self._audit(conn, agent, "lock_takeover", f"{lk['path']} from {lk['owner']}")
                self._send(conn, agent, lk["owner"], "SYSTEM_ALERT", f"Lock taken over: {lk['path']}",
                           f"{agent} took over the expired lock on {lk['path']}.", escalate=False)
            conn.execute(
                "INSERT INTO locks(path, owner, task_id, acquired_at, heartbeat_at, ttl_seconds, expires_at) "
                "VALUES (?,?,?,?,?,?,?) ON CONFLICT(path) DO UPDATE SET heartbeat_at=excluded.heartbeat_at, "
                "ttl_seconds=excluded.ttl_seconds, expires_at=excluded.expires_at, task_id=excluded.task_id",
                (path, agent, task_id, now, now, ttl, db.utc_plus(ttl)))
            self._audit(conn, agent, "lock_acquire", path)
            return _row(conn.execute("SELECT * FROM locks WHERE path=?", (path,)).fetchone())

    def heartbeat(self, agent, status=None, current_task=None, last_commit=None):
        """Agent liveness + extends every lock the agent holds."""
        self._check_agent(agent)
        with self.tx() as conn:
            self._guard(conn, agent)
            now = db.utcnow()
            conn.execute(
                "UPDATE agents SET last_seen=?, status=COALESCE(?, CASE WHEN status='OFFLINE' THEN 'ACTIVE' ELSE status END), "
                "current_task=COALESCE(?, current_task), last_commit=COALESCE(?, last_commit) WHERE agent_id=?",
                (now, status, current_task, last_commit, agent))
            for lk in conn.execute("SELECT path, ttl_seconds, expires_at FROM locks WHERE owner=?", (agent,)).fetchall():
                if lk["expires_at"] > now:  # an expired lock must go through takeover rules, not silent revival
                    conn.execute("UPDATE locks SET heartbeat_at=?, expires_at=? WHERE path=?",
                                 (now, db.utc_plus(lk["ttl_seconds"]), lk["path"]))
            return _row(conn.execute("SELECT * FROM agents WHERE agent_id=?", (agent,)).fetchone())

    def release_lock(self, agent, path=None, task_id=None):
        with self.tx() as conn:
            if path:
                p = normalize_path(path)
                lk = conn.execute("SELECT * FROM locks WHERE path=?", (p,)).fetchone()
                if not lk:
                    return 0
                if lk["owner"] != agent and agent not in LEADERS:
                    raise HubError("FORBIDDEN", "Not the lock owner")
                conn.execute("DELETE FROM locks WHERE path=?", (p,))
                n = 1
            elif task_id:
                n = conn.execute("DELETE FROM locks WHERE owner=? AND task_id=?", (agent, task_id)).rowcount
            else:
                n = conn.execute("DELETE FROM locks WHERE owner=?", (agent,)).rowcount
            self._audit(conn, agent, "lock_release", f"{path or task_id or 'all'} ({n})")
            return n

    def list_locks(self):
        now = db.utcnow()
        rows = self.query("SELECT * FROM locks ORDER BY path")
        for r in rows:
            r["expired"] = r["expires_at"] <= now
        return rows

    def alert_expired_locks(self):
        """Notify claude1 once per expired lock. Locks are never auto-deleted."""
        alerted = 0
        with self.tx() as conn:
            for lk in conn.execute("SELECT * FROM locks WHERE expires_at<=? AND alerted_at IS NULL",
                                   (db.utcnow(),)).fetchall():
                self._send(conn, "user", "claude1", "SYSTEM_ALERT", f"Lock expired: {lk['path']}",
                           f"{lk['owner']}'s lock on {lk['path']} expired. Check git status and the "
                           "latest checkpoint before reassigning.", priority="HIGH", escalate=False)
                conn.execute("UPDATE locks SET alerted_at=? WHERE path=?", (db.utcnow(), lk["path"]))
                alerted += 1
        return alerted

    # ----------------------------------------------- decisions / checkpoints
    def record_decision(self, agent, title, decision, rationale="", task_id=None,
                        conversation_id=None, critical=False):
        self._check_agent(agent)
        if not (title or "").strip() or not (decision or "").strip():
            raise HubError("BAD_INPUT", "Title and decision are required")
        with self.tx() as conn:
            self._guard(conn, agent)
            cur = conn.execute(
                "INSERT INTO decisions(task_id, conversation_id, title, decision, rationale, decided_by, critical, created_at) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (task_id, conversation_id, title.strip(), decision, rationale, agent,
                 1 if critical else 0, db.utcnow()))
            self._send(conn, agent, BROADCAST, "TECHNICAL_DECISION", title.strip(),
                       f"{decision}\n\nRationale: {rationale or '-'}", task_id=task_id,
                       conversation_id=conversation_id, priority="HIGH" if critical else "NORMAL",
                       escalate=False)
            self._audit(conn, agent, "decision", title)
            return _row(conn.execute("SELECT * FROM decisions WHERE decision_id=?", (cur.lastrowid,)).fetchone())

    def list_decisions(self):
        return self.query("SELECT * FROM decisions ORDER BY decision_id")

    def add_checkpoint(self, agent, notes, task_id=None, branch=None, git_commit=None):
        self._check_agent(agent)
        with self.tx() as conn:
            self._guard(conn, agent)
            cur = conn.execute(
                "INSERT INTO checkpoints(agent_id, task_id, branch, git_commit, notes, created_at) VALUES (?,?,?,?,?,?)",
                (agent, task_id, branch, git_commit, notes, db.utcnow()))
            if git_commit:
                conn.execute("UPDATE agents SET last_commit=? WHERE agent_id=?", (git_commit, agent))
            self._touch(conn, agent)
            return _row(conn.execute("SELECT * FROM checkpoints WHERE checkpoint_id=?", (cur.lastrowid,)).fetchone())

    def latest_checkpoint(self, agent):
        return self.query_one("SELECT * FROM checkpoints WHERE agent_id=? ORDER BY checkpoint_id DESC LIMIT 1", (agent,))

    # ---------------------------------------------------- handoff / sessions
    def handoff(self, agent, to_agent, task_id, notes, git_commit=None, branch=None):
        self._check_agent(to_agent, allow_user=False)
        with self.tx() as conn:
            self._guard(conn, agent)
            t = conn.execute("SELECT * FROM tasks WHERE task_id=?", (task_id,)).fetchone()
            if not t:
                raise HubError("UNKNOWN_TASK", task_id)
            if t["owner"] != agent and agent not in LEADERS:
                raise HubError("FORBIDDEN", "Only the owner or a leader can hand off a task")
            conn.execute("INSERT INTO checkpoints(agent_id, task_id, branch, git_commit, notes, created_at) "
                         "VALUES (?,?,?,?,?,?)", (agent, task_id, branch, git_commit, notes, db.utcnow()))
            conn.execute("DELETE FROM locks WHERE owner=? AND task_id=?", (agent, task_id))
            conn.execute("UPDATE tasks SET owner=?, status='ASSIGNED', updated_at=? WHERE task_id=?",
                         (to_agent, db.utcnow(), task_id))
            conn.execute("UPDATE agents SET current_task=NULL WHERE agent_id=? AND current_task=?", (agent, task_id))
            self._send(conn, agent, to_agent, "HANDOFF", f"[{task_id}] handoff from {agent}", notes,
                       task_id=task_id, related_commit=git_commit, priority="HIGH", response_required=True)
            self._audit(conn, agent, "handoff", f"{task_id} -> {to_agent}")
            return _row(conn.execute("SELECT * FROM tasks WHERE task_id=?", (task_id,)).fetchone())

    def session_end(self, agent, notes, git_commit=None, branch=None):
        """Usage limit reached or session closing: save state and free every lock."""
        if agent not in WORKERS:
            raise HubError("FORBIDDEN", "Only worker agents have sessions")
        with self.tx() as conn:
            cur_task = conn.execute("SELECT current_task FROM agents WHERE agent_id=?", (agent,)).fetchone()["current_task"]
            conn.execute("INSERT INTO checkpoints(agent_id, task_id, branch, git_commit, notes, created_at) "
                         "VALUES (?,?,?,?,?,?)", (agent, cur_task, branch, git_commit, notes, db.utcnow()))
            released = conn.execute("DELETE FROM locks WHERE owner=?", (agent,)).rowcount
            conn.execute("UPDATE agents SET status='OFFLINE', last_seen=?, last_commit=COALESCE(?, last_commit) "
                         "WHERE agent_id=?", (db.utcnow(), git_commit, agent))
            if agent != "claude1":
                self._send(conn, agent, "claude1", "STATUS_UPDATE", f"{agent} session ended",
                           f"{notes}\nLocks released: {released}", task_id=cur_task, related_commit=git_commit,
                           escalate=False)
            self._audit(conn, agent, "session_end", f"locks released={released}")
            return {"locks_released": released, "task": cur_task}

    def session_start(self, agent):
        """Resume bundle: everything an agent needs to continue after a restart."""
        if agent not in WORKERS:
            raise HubError("FORBIDDEN", "Only worker agents have sessions")
        self.heartbeat(agent, status="ACTIVE")
        locks = self.list_locks()
        return {
            "agent": agent,
            "emergency_stop": self.emergency_status(),
            "unread": self.inbox(agent, unread_only=True),
            "pending_responses": self.pending_responses(agent),
            "assigned_tasks": [t for t in self.list_tasks(owner=agent) if t["status"] in ACTIVE_TASK_STATUSES or t["status"] == "BLOCKED"],
            "latest_checkpoint": self.latest_checkpoint(agent),
            "agents": self.overview(),
            "my_expired_locks": [l for l in locks if l["owner"] == agent and l["expired"]],
            "all_expired_locks": [l for l in locks if l["expired"]],
        }

    # ----------------------------------------------------- emergency / audit
    def emergency_status(self):
        r = self.query_one("SELECT value FROM system_flags WHERE key='emergency_stop'")
        return bool(r and r["value"] == "1")

    def emergency_stop(self, actor, reason="manual stop"):
        if actor not in LEADERS:
            raise HubError("FORBIDDEN", "Only claude1 or the user can trigger an emergency stop")
        with self.tx() as conn:
            conn.execute("UPDATE system_flags SET value='1' WHERE key='emergency_stop'")
            self._audit(conn, actor, "EMERGENCY_STOP", reason)
            self._send(conn, actor, BROADCAST, "SYSTEM_ALERT", "EMERGENCY STOP",
                       f"All agents must stop work immediately. Reason: {reason}",
                       priority="CRITICAL", escalate=False)

    def resume(self, actor):
        if actor != "user":
            raise HubError("FORBIDDEN", "Only the user can lift an emergency stop")
        with self.tx() as conn:
            conn.execute("UPDATE system_flags SET value='0' WHERE key='emergency_stop'")
            self._audit(conn, actor, "RESUME", "")
            self._send(conn, actor, BROADCAST, "SYSTEM_ALERT", "Emergency stop lifted",
                       "Work may resume. Run session-start first.", escalate=False)

    def audit_log(self, limit=200):
        return self.query("SELECT * FROM audit_log ORDER BY audit_id DESC LIMIT ?", (int(limit),))

    # ------------------------------------------------------------ dashboard
    def overview(self):
        now = db.utcnow()
        out = []
        for a in self.query("SELECT * FROM agents ORDER BY agent_id"):
            aid = a["agent_id"]
            last_sent = self.query_one("SELECT subject, receiver, timestamp FROM messages WHERE sender=? "
                                       "ORDER BY timestamp DESC LIMIT 1", (aid,))
            a["online"] = bool(a["last_seen"]) and self._age(a["last_seen"], now) <= ONLINE_WINDOW
            a["last_sent"] = last_sent
            a["pending_responses"] = len(self.pending_responses(aid))
            a["awaiting_reply"] = len(self.awaiting_reply(aid))
            a["unread"] = len(self.inbox(aid, unread_only=True, limit=1000))
            tasks = self.list_tasks(owner=aid)
            a["active_tasks"] = len([t for t in tasks if t["status"] in ACTIVE_TASK_STATUSES])
            a["blocked_tasks"] = len([t for t in tasks if t["status"] == "BLOCKED"])
            out.append(a)
        return out

    @staticmethod
    def _age(ts, now):
        from datetime import datetime
        fmt = "%Y-%m-%dT%H:%M:%S.%fZ"
        return (datetime.strptime(now, fmt) - datetime.strptime(ts, fmt)).total_seconds()
