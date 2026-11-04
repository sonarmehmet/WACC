"""Approval flow and append-only audit trail (docs/EXECUTION_SECURITY.md sections 4 and 5).

An approval is bound to the SHA-256 of the exact normalized action, is single-use and expires.
Only the human user's token may decide; the service layer enforces who is asking.
"""

import json
import re
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from ..storage import Storage, StorageError

APPROVAL_TTL_SECONDS = 600
STATUSES = ("PENDING", "APPROVED", "DENIED", "EXPIRED", "EXECUTED")

_MASK = re.compile(r"(sk-[A-Za-z0-9_-]{8,}|ghp_[A-Za-z0-9]{10,}|AKIA[0-9A-Z]{12,}|(?i:bearer)\s+\S+|"
                   r"(?i:(?:api[_-]?key|token|password|secret)\s*[=:]\s*)\S+)")


def mask(text: str, limit: int = 2000) -> str:
    return _MASK.sub("[masked]", text or "")[:limit]


def _fmt(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _now_dt() -> datetime:
    return datetime.now(timezone.utc)


def _approval(row) -> dict:
    d = dict(row)
    try:
        d["action"] = json.loads(d["action"])
    except ValueError:
        pass
    return d


class Approvals:
    def __init__(self, storage: Storage):
        self.storage = storage

    # ----------------------------------------------------------------- audit
    def audit(self, agent: str, action_class: str, summary: str, outcome: str, detail: str = "",
              approval_id: Optional[int] = None, duration_ms: int = 0) -> None:
        with self.storage.tx() as conn:
            conn.execute(
                "INSERT INTO exec_audit(ts, agent, action_class, summary, approval_id, outcome, detail, duration_ms) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (_fmt(_now_dt()), agent, action_class, mask(summary, 500), approval_id, outcome, mask(detail), int(duration_ms)))

    def audit_log(self, limit: int = 200) -> List[dict]:
        conn = self.storage._connect()
        try:
            return [dict(r) for r in conn.execute("SELECT * FROM exec_audit ORDER BY id DESC LIMIT ?",
                                                  (max(1, min(int(limit), 1000)),)).fetchall()]
        finally:
            conn.close()

    # ------------------------------------------------------------- approvals
    def request(self, requested_by: str, action_class: str, normalized: dict, action_hash: str, summary: str,
                risk: str, ttl: int = APPROVAL_TTL_SECONDS) -> dict:
        now = _now_dt()
        with self.storage.tx() as conn:
            # Re-use a still-pending identical request instead of flooding the user.
            dup = conn.execute("SELECT * FROM approvals WHERE action_hash=? AND requested_by=? AND status='PENDING' "
                               "AND expires_at>?", (action_hash, requested_by, _fmt(now))).fetchone()
            if dup:
                return _approval(dup)
            cur = conn.execute(
                "INSERT INTO approvals(requested_by, action_class, action, action_hash, risk_summary, created_at, expires_at) "
                "VALUES (?,?,?,?,?,?,?)",
                (requested_by, action_class, json.dumps(normalized, default=str), action_hash,
                 f"{summary} | {risk}"[:1000], _fmt(now), _fmt(now + timedelta(seconds=ttl))))
            return _approval(conn.execute("SELECT * FROM approvals WHERE id=?", (cur.lastrowid,)).fetchone())

    def get(self, approval_id: int) -> Optional[dict]:
        self.expire_due()
        conn = self.storage._connect()
        try:
            r = conn.execute("SELECT * FROM approvals WHERE id=?", (approval_id,)).fetchone()
            return _approval(r) if r else None
        finally:
            conn.close()

    def list(self, status: Optional[str] = None, limit: int = 100) -> List[dict]:
        if status and status not in STATUSES:
            raise StorageError("BAD_STATUS", f"Status must be one of {STATUSES}")
        self.expire_due()
        sql, params = "SELECT * FROM approvals", []
        if status:
            sql += " WHERE status=?"
            params.append(status)
        conn = self.storage._connect()
        try:
            return [_approval(r) for r in conn.execute(sql + " ORDER BY id DESC LIMIT ?",
                                                       params + [max(1, min(int(limit), 500))]).fetchall()]
        finally:
            conn.close()

    def expire_due(self) -> int:
        with self.storage.tx() as conn:
            return conn.execute("UPDATE approvals SET status='EXPIRED' WHERE status IN ('PENDING','APPROVED') "
                                "AND expires_at<=?", (_fmt(_now_dt()),)).rowcount

    def expire_all_open(self) -> int:
        """Emergency stop: nothing pending or approved may run afterwards."""
        with self.storage.tx() as conn:
            return conn.execute("UPDATE approvals SET status='EXPIRED' WHERE status IN ('PENDING','APPROVED')").rowcount

    def decide(self, approval_id: int, approve: bool, decided_by: str) -> dict:
        if decided_by != "user":
            raise StorageError("FORBIDDEN", "Only the user may approve or deny actions")
        self.expire_due()
        with self.storage.tx() as conn:
            row = conn.execute("SELECT * FROM approvals WHERE id=?", (approval_id,)).fetchone()
            if not row:
                raise StorageError("NOT_FOUND", f"Approval {approval_id} not found")
            if row["status"] != "PENDING":
                raise StorageError("BAD_STATE", f"Approval is {row['status']}, not PENDING")
            conn.execute("UPDATE approvals SET status=?, decided_by=?, decided_at=? WHERE id=?",
                         ("APPROVED" if approve else "DENIED", decided_by, _fmt(_now_dt()), approval_id))
            return _approval(conn.execute("SELECT * FROM approvals WHERE id=?", (approval_id,)).fetchone())

    def consume(self, approval_id: int, requested_by: str, action_hash: str) -> dict:
        """Atomically mark an APPROVED approval as used. Fails if anything about it changed."""
        self.expire_due()
        with self.storage.tx() as conn:
            row = conn.execute("SELECT * FROM approvals WHERE id=?", (approval_id,)).fetchone()
            if not row:
                raise StorageError("NOT_FOUND", f"Approval {approval_id} not found")
            if row["requested_by"] != requested_by:
                raise StorageError("FORBIDDEN", "This approval belongs to another agent")
            if row["status"] != "APPROVED":
                raise StorageError("NOT_APPROVED", f"Approval is {row['status']}")
            if row["action_hash"] != action_hash:
                raise StorageError("HASH_MISMATCH", "The action differs from what the user approved")
            conn.execute("UPDATE approvals SET status='EXECUTED', executed_at=? WHERE id=? AND status='APPROVED'",
                         (_fmt(_now_dt()), approval_id))
            return _approval(conn.execute("SELECT * FROM approvals WHERE id=?", (approval_id,)).fetchone())

    def previously_approved(self, action_hash: str) -> bool:
        """Package installs: the same exact action, approved and run before, needs no second approval."""
        conn = self.storage._connect()
        try:
            return conn.execute("SELECT 1 FROM approvals WHERE action_hash=? AND status='EXECUTED' "
                                "AND action_class='INSTALL' LIMIT 1", (action_hash,)).fetchone() is not None
        finally:
            conn.close()
