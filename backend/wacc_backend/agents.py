"""Agent Manager: registry and liveness of agents (claude1..3, gemini, local workers).

This is bookkeeping only. It never starts processes; launching programs belongs to the
Execution Backend (T-0009) and its approval flow.
"""

import json
import re
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from .storage import Storage, StorageError

AGENT_STATUSES = ("OFFLINE", "IDLE", "BUSY", "DISABLED")
NAME_RE = re.compile(r"^[a-z][a-z0-9_-]{1,39}$")
ONLINE_WINDOW_SECONDS = 300


def _fmt(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _now() -> str:
    return _fmt(datetime.now(timezone.utc))


def _agent(row) -> dict:
    d = dict(row)
    try:
        d["capabilities"] = json.loads(d["capabilities"])
    except ValueError:
        d["capabilities"] = []
    cutoff = _fmt(datetime.now(timezone.utc) - timedelta(seconds=ONLINE_WINDOW_SECONDS))
    d["online"] = bool(d["last_seen"]) and d["last_seen"] >= cutoff and d["status"] not in ("OFFLINE", "DISABLED")
    return d


class AgentManager:
    def __init__(self, storage: Storage):
        self.storage = storage

    def register(self, name: str, role: str, capabilities: Optional[List[str]] = None) -> dict:
        name = (name or "").strip().lower()
        if not NAME_RE.match(name):
            raise StorageError("BAD_NAME", "Agent name: 2-40 chars, lowercase letters, digits, _ or -")
        role = (role or "").strip()
        if not role or len(role) > 80:
            raise StorageError("BAD_ROLE", "Role must be 1-80 characters")
        caps = sorted({c.strip() for c in (capabilities or []) if c and c.strip()})
        if len(caps) > 30 or any(len(c) > 60 for c in caps):
            raise StorageError("BAD_CAPABILITIES", "At most 30 capabilities of 60 characters")
        with self.storage.tx() as conn:
            conn.execute(
                "INSERT INTO agent_registry(name, role, capabilities, registered_at) VALUES (?,?,?,?) "
                "ON CONFLICT(name) DO UPDATE SET role=excluded.role, capabilities=excluded.capabilities",
                (name, role, json.dumps(caps), _now()))
            return _agent(conn.execute("SELECT * FROM agent_registry WHERE name=?", (name,)).fetchone())

    def heartbeat(self, name: str, status: Optional[str] = None, current_job: Optional[int] = None) -> dict:
        if status is not None and status not in AGENT_STATUSES:
            raise StorageError("BAD_STATUS", f"Status must be one of {AGENT_STATUSES}")
        with self.storage.tx() as conn:
            row = conn.execute("SELECT * FROM agent_registry WHERE name=?", (name,)).fetchone()
            if not row:
                raise StorageError("NOT_FOUND", f"Agent {name!r} is not registered")
            if row["status"] == "DISABLED" and status != "DISABLED":
                raise StorageError("DISABLED", "Agent is disabled; enable it first")
            new_status = status or ("IDLE" if row["status"] == "OFFLINE" else row["status"])
            conn.execute("UPDATE agent_registry SET status=?, current_job=?, last_seen=? WHERE name=?",
                         (new_status, current_job, _now(), name))
            return _agent(conn.execute("SELECT * FROM agent_registry WHERE name=?", (name,)).fetchone())

    def set_enabled(self, name: str, enabled: bool) -> dict:
        with self.storage.tx() as conn:
            row = conn.execute("SELECT * FROM agent_registry WHERE name=?", (name,)).fetchone()
            if not row:
                raise StorageError("NOT_FOUND", f"Agent {name!r} is not registered")
            conn.execute("UPDATE agent_registry SET status=?, current_job=NULL WHERE name=?",
                         ("OFFLINE" if enabled else "DISABLED", name))
            return _agent(conn.execute("SELECT * FROM agent_registry WHERE name=?", (name,)).fetchone())

    def get(self, name: str) -> Optional[dict]:
        conn = self.storage._connect()
        try:
            r = conn.execute("SELECT * FROM agent_registry WHERE name=?", (name,)).fetchone()
            return _agent(r) if r else None
        finally:
            conn.close()

    def list(self) -> List[dict]:
        conn = self.storage._connect()
        try:
            return [_agent(r) for r in conn.execute("SELECT * FROM agent_registry ORDER BY name").fetchall()]
        finally:
            conn.close()

    def find_capable(self, capability: str) -> List[dict]:
        """Enabled agents that declare `capability`, idle ones first."""
        agents = [a for a in self.list() if capability in a["capabilities"] and a["status"] != "DISABLED"]
        return sorted(agents, key=lambda a: (a["status"] != "IDLE", a["name"]))
