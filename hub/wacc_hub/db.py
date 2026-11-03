"""SQLite access: WAL mode, busy timeout, explicit transactions."""

import os
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .models import AGENTS

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = Path(os.environ.get("WACC_DATA_DIR", ROOT / "data"))
DEFAULT_DB = Path(os.environ.get("WACC_HUB_DB", DATA_DIR / "hub.db"))

SCHEMA = """
CREATE TABLE IF NOT EXISTS agents (
    agent_id TEXT PRIMARY KEY,
    role TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'OFFLINE',
    current_task TEXT,
    last_seen TEXT,
    last_commit TEXT,
    last_message_at TEXT
);
CREATE TABLE IF NOT EXISTS tasks (
    task_id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    owner TEXT,
    creator TEXT NOT NULL,
    affected_files TEXT NOT NULL DEFAULT '[]',
    dependencies TEXT NOT NULL DEFAULT '[]',
    acceptance TEXT NOT NULL DEFAULT '',
    test_criteria TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL,
    priority TEXT NOT NULL DEFAULT 'NORMAL',
    branch TEXT,
    commit_hash TEXT,
    note TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS messages (
    message_id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL,
    task_id TEXT,
    sender TEXT NOT NULL,
    receiver TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    message_type TEXT NOT NULL,
    priority TEXT NOT NULL DEFAULT 'NORMAL',
    subject TEXT NOT NULL,
    content TEXT NOT NULL DEFAULT '',
    related_files TEXT NOT NULL DEFAULT '[]',
    related_commit TEXT,
    response_required INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'QUEUED',
    in_reply_to TEXT,
    idempotency_key TEXT UNIQUE,
    delivery_attempts INTEGER NOT NULL DEFAULT 0,
    delivered_at TEXT,
    read_at TEXT,
    answered_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_msg_receiver ON messages(receiver, status);
CREATE INDEX IF NOT EXISTS idx_msg_sender ON messages(sender, status);
CREATE INDEX IF NOT EXISTS idx_msg_conv ON messages(conversation_id, timestamp);
CREATE TABLE IF NOT EXISTS locks (
    path TEXT PRIMARY KEY,
    owner TEXT NOT NULL,
    task_id TEXT,
    acquired_at TEXT NOT NULL,
    heartbeat_at TEXT NOT NULL,
    ttl_seconds INTEGER NOT NULL,
    expires_at TEXT NOT NULL,
    alerted_at TEXT
);
CREATE TABLE IF NOT EXISTS decisions (
    decision_id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT,
    conversation_id TEXT,
    title TEXT NOT NULL,
    decision TEXT NOT NULL,
    rationale TEXT NOT NULL DEFAULT '',
    decided_by TEXT NOT NULL,
    critical INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS checkpoints (
    checkpoint_id INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id TEXT NOT NULL,
    task_id TEXT,
    branch TEXT,
    git_commit TEXT,
    notes TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS escalations (
    conversation_id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS system_flags (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS audit_log (
    audit_id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    actor TEXT NOT NULL,
    action TEXT NOT NULL,
    detail TEXT NOT NULL DEFAULT ''
);
"""


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def utc_plus(seconds: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=seconds)).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def connect(db_path=None) -> sqlite3.Connection:
    path = Path(db_path or DEFAULT_DB)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=10, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA busy_timeout=10000")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


AGENT_COLUMNS = (
    ("kind", "TEXT NOT NULL DEFAULT 'builtin'"),   # builtin | claude | gemini | chatgpt | other
    ("provider", "TEXT"),                          # optional AI account (backend /ai/providers name) the agent uses
    ("enabled", "INTEGER NOT NULL DEFAULT 1"),
    ("removed", "INTEGER NOT NULL DEFAULT 0"),
    ("created_at", "TEXT"),
)


def _ensure_agent_columns(conn) -> None:
    have = {r["name"] for r in conn.execute("PRAGMA table_info(agents)")}
    for name, ddl in AGENT_COLUMNS:
        if name not in have:
            conn.execute(f"ALTER TABLE agents ADD COLUMN {name} {ddl}")


def init_db(db_path=None) -> None:
    conn = connect(db_path)
    try:
        conn.executescript(SCHEMA)
        _ensure_agent_columns(conn)
        for agent_id, role in AGENTS.items():
            conn.execute(
                "INSERT OR IGNORE INTO agents(agent_id, role) VALUES (?, ?)",
                (agent_id, role),
            )
        conn.execute("INSERT OR IGNORE INTO system_flags(key, value) VALUES ('emergency_stop', '0')")
    finally:
        conn.close()
