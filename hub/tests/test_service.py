import os
import sqlite3
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from wacc_hub import db  # noqa: E402
from wacc_hub.cli import seed  # noqa: E402
from wacc_hub.render import render_all  # noqa: E402
from wacc_hub.service import Hub, HubError, normalize_path  # noqa: E402


class HubTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.hub = Hub(os.path.join(self.tmp.name, "hub.db"))

    def tearDown(self):
        self.tmp.cleanup()

    def expire_lock(self, path):
        conn = db.connect(self.hub.db_path)
        conn.execute("UPDATE locks SET expires_at='2000-01-01T00:00:00.000000Z' WHERE path=?", (path,))
        conn.close()

    def code(self, fn, *a, **kw):
        with self.assertRaises(HubError) as cm:
            fn(*a, **kw)
        return cm.exception.code


class MessageTests(HubTestCase):
    def test_send_and_lifecycle(self):
        m = self.hub.send_message("claude2", "claude3", "CODE_READY", "API ready", "see docs",
                                  response_required=True, related_files=["backend\\api.py"])
        self.assertEqual(m["status"], "DELIVERED")
        self.assertEqual(m["related_files"], ["backend/api.py"])
        self.assertEqual(len(self.hub.inbox("claude3", unread_only=True)), 1)
        self.assertEqual(len(self.hub.pending_responses("claude3")), 1)
        self.assertEqual(len(self.hub.awaiting_reply("claude2")), 1)
        self.assertEqual(self.hub.mark_read("claude3", m["message_id"])["status"], "READ")
        self.assertEqual(len(self.hub.inbox("claude3", unread_only=True)), 0)
        reply = self.hub.send_message("claude3", "claude2", "HELP_RESPONSE", "thanks",
                                      in_reply_to=m["message_id"])
        self.assertEqual(reply["in_reply_to"], m["message_id"])
        self.assertEqual(self.hub.pending_responses("claude3"), [])

    def test_idempotency(self):
        a = self.hub.send_message("claude2", "claude3", "STATUS_UPDATE", "x", idempotency_key="k1")
        b = self.hub.send_message("claude2", "claude3", "STATUS_UPDATE", "x", idempotency_key="k1")
        self.assertEqual(a["message_id"], b["message_id"])
        self.assertEqual(len(self.hub.inbox("claude3")), 1)

    def test_validation(self):
        self.assertEqual(self.code(self.hub.send_message, "claude2", "nobody", "STATUS_UPDATE", "x"), "UNKNOWN_AGENT")
        self.assertEqual(self.code(self.hub.send_message, "claude2", "claude3", "NOPE", "x"), "BAD_TYPE")
        self.assertEqual(self.code(self.hub.send_message, "claude2", "claude3", "STATUS_UPDATE", ""), "BAD_SUBJECT")
        self.assertEqual(self.code(self.hub.send_message, "claude2", "claude3", "STATUS_UPDATE", "x", "a" * 20001),
                         "CONTENT_TOO_LONG")
        self.assertEqual(self.code(self.hub.send_message, "claude2", "claude3", "STATUS_UPDATE", "x",
                                   related_files=["../secret"]), "BAD_PATH")

    def test_only_receiver_can_read(self):
        m = self.hub.send_message("claude2", "claude3", "STATUS_UPDATE", "x")
        self.assertEqual(self.code(self.hub.mark_read, "gemini", m["message_id"]), "FORBIDDEN")

    def test_broadcast(self):
        res = self.hub.send_message("claude1", "ALL", "STATUS_UPDATE", "hello")
        self.assertEqual({m["receiver"] for m in res}, {"claude2", "claude3", "gemini", "user"})

    def test_escalation_after_round_limit(self):
        conv = "CONV-debate"
        for i in range(8):
            sender, receiver = ("claude2", "claude3") if i % 2 == 0 else ("claude3", "claude2")
            self.hub.send_message(sender, receiver, "HELP_REQUEST", f"round {i}", conversation_id=conv)
        alerts = [m for m in self.hub.inbox("claude1") if m["message_type"] == "SYSTEM_ALERT"]
        self.assertEqual(len(alerts), 1)
        self.hub.send_message("claude3", "claude2", "HELP_REQUEST", "round 9", conversation_id=conv)
        self.assertEqual(len([m for m in self.hub.inbox("claude1") if m["message_type"] == "SYSTEM_ALERT"]), 1)

    def test_retry_undelivered(self):
        conn = db.connect(self.hub.db_path)
        conn.execute("INSERT INTO messages(message_id, conversation_id, sender, receiver, timestamp, message_type, "
                     "subject, status) VALUES ('M1','C','claude2','claude3','2026-01-01T00:00:00.000000Z',"
                     "'STATUS_UPDATE','q','QUEUED')")
        conn.close()
        self.assertEqual(len(self.hub.outbox("claude2")), 1)
        self.assertEqual(self.hub.retry_undelivered()["redelivered"], 1)
        self.assertEqual(self.hub.outbox("claude2"), [])


class TaskTests(HubTestCase):
    def test_permissions_and_flow(self):
        self.assertEqual(self.code(self.hub.create_task, "claude2", "x", owner="claude3"), "FORBIDDEN")
        t = self.hub.create_task("claude1", "Build API", owner="claude2", affected_files=["backend/"])
        self.assertEqual((t["task_id"], t["status"]), ("T-0001", "ASSIGNED"))
        self.assertEqual(len(self.hub.pending_responses("claude2")), 1)
        self.assertEqual(self.code(self.hub.accept_task, "claude3", "T-0001"), "FORBIDDEN")
        self.assertEqual(self.hub.accept_task("claude2", "T-0001")["status"], "ACCEPTED")
        self.assertEqual(self.hub.pending_responses("claude2"), [])
        self.assertEqual(self.code(self.hub.set_task_status, "claude2", "T-0001", "COMPLETED"), "COMMIT_REQUIRED")
        self.assertEqual(self.code(self.hub.set_task_status, "claude2", "T-0001", "BLOCKED"), "NOTE_REQUIRED")
        done = self.hub.set_task_status("claude2", "T-0001", "COMPLETED", commit="abc123")
        self.assertEqual(done["commit_hash"], "abc123")
        types = [m["message_type"] for m in self.hub.inbox("claude1")]
        self.assertIn("TASK_ACCEPTED", types)
        self.assertEqual(self.hub.query_one("SELECT last_commit FROM agents WHERE agent_id='claude2'")["last_commit"], "abc123")

    def test_dependencies(self):
        self.assertEqual(self.code(self.hub.create_task, "claude1", "x", dependencies=["T-9999"]), "UNKNOWN_TASK")
        self.hub.create_task("claude1", "A", owner="claude2")
        self.hub.create_task("claude1", "B", owner="claude3", dependencies=["T-0001"])
        self.hub.accept_task("claude3", "T-0002")
        self.assertEqual(self.code(self.hub.set_task_status, "claude3", "T-0002", "COMPLETED", commit="c"), "DEPENDENCY_OPEN")

    def test_completion_releases_locks(self):
        self.hub.create_task("claude1", "A", owner="claude2")
        self.hub.accept_task("claude2", "T-0001")
        self.hub.acquire_lock("claude2", "backend/api", task_id="T-0001")
        self.hub.set_task_status("claude2", "T-0001", "COMPLETED", commit="c1")
        self.assertEqual(self.hub.list_locks(), [])

    def test_handoff(self):
        self.hub.create_task("claude1", "A", owner="claude2")
        self.hub.accept_task("claude2", "T-0001")
        self.hub.acquire_lock("claude2", "backend/x.py", task_id="T-0001")
        self.hub.handoff("claude2", "claude3", "T-0001", "half done", git_commit="deadbeef")
        t = self.hub.get_task("T-0001")
        self.assertEqual((t["owner"], t["status"]), ("claude3", "ASSIGNED"))
        self.assertEqual(self.hub.list_locks(), [])
        self.assertEqual(self.hub.latest_checkpoint("claude2")["git_commit"], "deadbeef")
        self.assertIn("HANDOFF", [m["message_type"] for m in self.hub.inbox("claude3")])

    def test_seed_is_idempotent_and_renders(self):
        self.assertEqual(len(seed(self.hub)), 9)
        self.assertEqual(self.hub.get_task("T-0009")["status"], "BACKLOG")
        self.assertEqual(self.hub.get_task("T-0007")["owner"], "gemini")
        self.assertEqual(seed(self.hub), [])
        out = Path(self.tmp.name) / "tasks"
        files = render_all(self.hub, out)
        self.assertEqual(len(files), 7)
        self.assertIn("T-0001", (out / "ACTIVE_TASKS.md").read_text(encoding="utf-8"))
        self.assertIn("claude2", (out / "AGENT_STATUS.md").read_text(encoding="utf-8"))


class LockTests(HubTestCase):
    def test_conflicts(self):
        self.hub.acquire_lock("claude2", "backend/api")
        self.assertEqual(self.code(self.hub.acquire_lock, "claude3", "backend/api/routes.py"), "LOCKED")
        self.assertEqual(self.code(self.hub.acquire_lock, "claude3", "backend"), "LOCKED")
        self.hub.acquire_lock("claude3", "backend/apix")  # similar prefix, no real overlap
        self.hub.acquire_lock("claude2", "backend/api/routes.py")  # owner may nest

    def test_non_workers_cannot_lock(self):
        self.assertEqual(self.code(self.hub.acquire_lock, "user", "x"), "FORBIDDEN")

    def test_path_validation(self):
        for bad in ("/etc/passwd", "C:\\x", "../x", "a/../../x", ""):
            with self.assertRaises(HubError):
                normalize_path(bad)
        self.assertEqual(normalize_path(".\\backend\\a.py"), "backend/a.py")

    def test_stale_lock_requires_takeover(self):
        self.hub.acquire_lock("claude2", "backend/core")
        self.hub.add_checkpoint("claude2", "midway", git_commit="abc")
        self.expire_lock("backend/core")
        with self.assertRaises(HubError) as cm:
            self.hub.acquire_lock("claude3", "backend/core")
        self.assertEqual(cm.exception.code, "STALE_LOCK")
        self.assertEqual(cm.exception.detail["checkpoint"]["git_commit"], "abc")
        lk = self.hub.acquire_lock("claude3", "backend/core", takeover=True)
        self.assertEqual(lk["owner"], "claude3")
        self.assertIn("SYSTEM_ALERT", [m["message_type"] for m in self.hub.inbox("claude2")])

    def test_heartbeat_extends_but_does_not_revive(self):
        self.hub.acquire_lock("claude2", "a", ttl=60)
        before = self.hub.list_locks()[0]["expires_at"]
        time.sleep(0.01)
        self.hub.heartbeat("claude2")
        self.assertGreater(self.hub.list_locks()[0]["expires_at"], before)
        self.expire_lock("a")
        self.hub.heartbeat("claude2")
        self.assertTrue(self.hub.list_locks()[0]["expired"])

    def test_alert_expired_once(self):
        self.hub.acquire_lock("claude2", "a")
        self.expire_lock("a")
        self.assertEqual(self.hub.alert_expired_locks(), 1)
        self.assertEqual(self.hub.alert_expired_locks(), 0)

    def test_session_end_releases_everything(self):
        self.hub.acquire_lock("claude2", "a")
        self.hub.acquire_lock("claude2", "b")
        res = self.hub.session_end("claude2", "usage limit", git_commit="zzz")
        self.assertEqual(res["locks_released"], 2)
        self.assertEqual(self.hub.list_locks(), [])
        start = self.hub.session_start("claude2")
        self.assertEqual(start["latest_checkpoint"]["git_commit"], "zzz")

    def test_concurrent_lock_race_has_single_winner(self):
        results = []

        def worker(agent):
            try:
                self.hub.acquire_lock(agent, "shared/file.py")
                results.append(agent)
            except HubError:
                pass

        threads = [threading.Thread(target=worker, args=(a,)) for a in ("claude1", "claude2", "claude3", "gemini")]
        [t.start() for t in threads]
        [t.join() for t in threads]
        self.assertEqual(len(results), 1)

    def test_concurrent_sends_no_loss(self):
        def worker(n):
            for i in range(10):
                self.hub.send_message("claude2", "claude3", "STATUS_UPDATE", f"{n}-{i}")

        threads = [threading.Thread(target=worker, args=(n,)) for n in range(4)]
        [t.start() for t in threads]
        [t.join() for t in threads]
        self.assertEqual(len(self.hub.inbox("claude3", limit=500)), 40)


class SafetyTests(HubTestCase):
    def test_emergency_stop(self):
        self.assertEqual(self.code(self.hub.emergency_stop, "claude2"), "FORBIDDEN")
        self.hub.emergency_stop("claude1", "test")
        self.assertTrue(self.hub.emergency_status())
        self.assertEqual(self.code(self.hub.send_message, "claude2", "claude3", "STATUS_UPDATE", "x"), "EMERGENCY_STOP")
        self.assertEqual(self.code(self.hub.acquire_lock, "claude2", "a"), "EMERGENCY_STOP")
        self.assertEqual(self.code(self.hub.resume, "claude1"), "FORBIDDEN")
        self.hub.send_message("user", "claude1", "STATUS_UPDATE", "user may still write")
        self.hub.resume("user")
        self.assertFalse(self.hub.emergency_status())
        self.hub.send_message("claude2", "claude3", "STATUS_UPDATE", "ok again")

    def test_stop_file_is_shared_with_the_backend(self):
        stop_file = Path(self.hub.db_path).parent / "EMERGENCY_STOP"
        self.assertFalse(stop_file.exists())
        self.hub.emergency_stop("user", "test")
        self.assertTrue(stop_file.exists())
        self.hub.resume("user")
        self.assertFalse(stop_file.exists())

    def test_audit_log_records_actions(self):
        self.hub.send_message("claude2", "claude3", "STATUS_UPDATE", "x")
        self.hub.acquire_lock("claude2", "a")
        actions = {r["action"] for r in self.hub.audit_log()}
        self.assertTrue({"send_message", "lock_acquire"} <= actions)

    def test_decision_broadcast_and_listing(self):
        d = self.hub.record_decision("claude1", "Use SQLite", "SQLite WAL for the hub", "cheap", critical=True)
        self.assertEqual(d["critical"], 1)
        self.assertEqual(len(self.hub.list_decisions()), 1)
        self.assertIn("TECHNICAL_DECISION", [m["message_type"] for m in self.hub.inbox("claude3")])

    def test_wal_enabled(self):
        conn = sqlite3.connect(self.hub.db_path)
        self.assertEqual(conn.execute("PRAGMA journal_mode").fetchone()[0].lower(), "wal")
        conn.close()

    def test_overview_shape(self):
        self.hub.heartbeat("claude2", status="ACTIVE")
        by_id = {a["agent_id"]: a for a in self.hub.overview()}
        self.assertTrue(by_id["claude2"]["online"])
        self.assertFalse(by_id["claude3"]["online"])


if __name__ == "__main__":
    unittest.main()
