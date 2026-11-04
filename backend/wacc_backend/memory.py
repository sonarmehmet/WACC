"""Memory System: durable notes the agents can search (project decisions, facts, lessons).

Entries are archived (soft delete), never hard-deleted: irreversible deletion of stored data
needs explicit user approval. Search is token-overlap ranking over SQLite, no extra dependencies.
Never store secrets here; content that looks like a key or token is rejected.
"""

import json
import re
from datetime import datetime, timezone
from typing import List, Optional

from .storage import Storage, StorageError

MAX_CONTENT = 10_000
MAX_TAGS = 20
_WORD = re.compile(r"[\w]{2,}", re.UNICODE)
_SECRET = re.compile(r"(sk-[A-Za-z0-9_-]{16,}|-----BEGIN [A-Z ]*PRIVATE KEY-----|ghp_[A-Za-z0-9]{20,}|"
                     r"AKIA[0-9A-Z]{16}|(?i:bearer)\s+[A-Za-z0-9._-]{20,})")


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _entry(row) -> dict:
    d = dict(row)
    try:
        d["tags"] = json.loads(d["tags"])
    except ValueError:
        d["tags"] = []
    d["archived"] = bool(d["archived"])
    return d


def _words(text: str) -> set:
    return {w.lower() for w in _WORD.findall(text or "")}


class Memory:
    def __init__(self, storage: Storage):
        self.storage = storage

    def add(self, content: str, tags: Optional[List[str]] = None, project_id: Optional[int] = None,
            source: str = "") -> dict:
        content = (content or "").strip()
        if not content or len(content) > MAX_CONTENT:
            raise StorageError("BAD_CONTENT", f"Content must be 1-{MAX_CONTENT} characters")
        if _SECRET.search(content):
            raise StorageError("SECRET_DETECTED", "Content looks like a secret (key/token); refusing to store it")
        clean = sorted({t.strip().lower() for t in (tags or []) if t and t.strip()})
        if len(clean) > MAX_TAGS or any(len(t) > 40 for t in clean):
            raise StorageError("BAD_TAGS", f"At most {MAX_TAGS} tags of 40 characters")
        now = _now()
        with self.storage.tx() as conn:
            if project_id is not None and not conn.execute("SELECT 1 FROM projects WHERE id=?", (project_id,)).fetchone():
                raise StorageError("NOT_FOUND", f"Project {project_id} not found")
            cur = conn.execute(
                "INSERT INTO memories(project_id, content, tags, source, created_at, updated_at) VALUES (?,?,?,?,?,?)",
                (project_id, content, json.dumps(clean), (source or "")[:60], now, now))
            return _entry(conn.execute("SELECT * FROM memories WHERE id=?", (cur.lastrowid,)).fetchone())

    def get(self, memory_id: int) -> Optional[dict]:
        conn = self.storage._connect()
        try:
            r = conn.execute("SELECT * FROM memories WHERE id=?", (memory_id,)).fetchone()
            return _entry(r) if r else None
        finally:
            conn.close()

    def archive(self, memory_id: int) -> dict:
        with self.storage.tx() as conn:
            if not conn.execute("SELECT 1 FROM memories WHERE id=?", (memory_id,)).fetchone():
                raise StorageError("NOT_FOUND", f"Memory {memory_id} not found")
            conn.execute("UPDATE memories SET archived=1, updated_at=? WHERE id=?", (_now(), memory_id))
            return _entry(conn.execute("SELECT * FROM memories WHERE id=?", (memory_id,)).fetchone())

    def list(self, project_id: Optional[int] = None, tag: Optional[str] = None, limit: int = 50) -> List[dict]:
        sql, params = "SELECT * FROM memories WHERE archived=0", []
        if project_id is not None:
            sql += " AND project_id=?"
            params.append(project_id)
        conn = self.storage._connect()
        try:
            rows = [_entry(r) for r in conn.execute(sql + " ORDER BY id DESC", params).fetchall()]
        finally:
            conn.close()
        if tag:
            rows = [r for r in rows if tag.strip().lower() in r["tags"]]
        return rows[:max(1, min(int(limit), 200))]

    def search(self, query: str, project_id: Optional[int] = None, limit: int = 10) -> List[dict]:
        q = _words(query)
        if not q:
            raise StorageError("BAD_QUERY", "Query needs at least one word")
        scored = []
        for e in self.list(project_id=project_id, limit=200):
            words = _words(e["content"])
            tag_words = {w for t in e["tags"] for w in _words(t)}
            score = len(q & words) + 2 * len(q & tag_words)  # tag hits count double
            if score:
                scored.append((score, e["id"], e))
        scored.sort(key=lambda x: (-x[0], -x[1]))  # best score, newest first
        return [dict(e, score=s) for s, _, e in scored[:max(1, min(int(limit), 50))]]
