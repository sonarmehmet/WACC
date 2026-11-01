import sys
import tempfile
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from wacc_backend import engine as engine_mod  # noqa: E402
from wacc_backend.agents import AgentManager  # noqa: E402
from wacc_backend.engine import TaskEngine  # noqa: E402
from wacc_backend.storage import Storage, StorageError  # noqa: E402


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.storage = Storage(Path(self.tmp.name) / "b.db")
        self.engine = TaskEngine(self.storage)
        self.agents = AgentManager(self.storage)

    def tearDown(self):
        self.tmp.cleanup()

    def code(self, fn, *a, **kw):
        with self.assertRaises(StorageError) as cm:
            fn(*a, **kw)
        return cm.exception.code

    def make_due(self, job_id):
        conn = self.storage._connect()
        conn.execute("UPDATE jobs SET run_after='2000-01-01T00:00:00.000000Z' WHERE id=?", (job_id,))
        conn.close()


class EngineTests(Base):
    def test_enqueue_validation(self):
        self.assertEqual(self.code(self.engine.enqueue, "", "t"), "BAD_KIND")
        self.assertEqual(self.code(self.engine.enqueue, "k", " "), "BAD_TITLE")
        self.assertEqual(self.code(self.engine.enqueue, "k", "t", priority=0), "BAD_PRIORITY")
        self.assertEqual(self.code(self.engine.enqueue, "k", "t", max_attempts=99), "BAD_ATTEMPTS")
        self.assertEqual(self.code(self.engine.enqueue, "k", "t", delay_seconds=-1), "BAD_DELAY")
        self.assertEqual(self.code(self.engine.enqueue, "k", "t", payload={"x": "a" * 200_000}), "PAYLOAD_TOO_LARGE")
        self.assertEqual(self.code(self.engine.enqueue, "k", "t", project_id=42), "NOT_FOUND")

    def test_archived_project_rejects_jobs(self):
        p = self.storage.create_project("P")
        self.storage.archive_project(p["id"])
        self.assertEqual(self.code(self.engine.enqueue, "k", "t", project_id=p["id"]), "PROJECT_ARCHIVED")

    def test_priority_then_fifo_order(self):
        low = self.engine.enqueue("k", "low", priority=9)
        a = self.engine.enqueue("k", "a", priority=2)
        b = self.engine.enqueue("k", "b", priority=2)
        order = [self.engine.claim_next("w")["id"] for _ in range(3)]
        self.assertEqual(order, [a["id"], b["id"], low["id"]])
        self.assertIsNone(self.engine.claim_next("w"))

    def test_delay_hides_job_until_due(self):
        j = self.engine.enqueue("k", "later", delay_seconds=3600)
        self.assertIsNone(self.engine.claim_next("w"))
        self.make_due(j["id"])
        self.assertEqual(self.engine.claim_next("w")["id"], j["id"])

    def test_kind_filter(self):
        self.engine.enqueue("build", "b")
        self.assertIsNone(self.engine.claim_next("w", kinds=["test"]))
        self.assertIsNotNone(self.engine.claim_next("w", kinds=["build"]))

    def test_complete_flow_and_ownership(self):
        j = self.engine.enqueue("k", "t", payload={"a": 1})
        job = self.engine.claim_next("w1")
        self.assertEqual((job["status"], job["attempts"], job["payload"]), ("RUNNING", 1, {"a": 1}))
        self.assertEqual(self.code(self.engine.complete, j["id"], "w2"), "FORBIDDEN")
        done = self.engine.complete(j["id"], "w1", {"ok": True})
        self.assertEqual((done["status"], done["result"]), ("SUCCEEDED", {"ok": True}))
        self.assertEqual(self.code(self.engine.complete, j["id"], "w1"), "BAD_STATE")

    def test_retry_with_backoff_then_fail(self):
        j = self.engine.enqueue("k", "t", max_attempts=2)
        self.engine.claim_next("w")
        r1 = self.engine.fail(j["id"], "w", "boom")
        self.assertEqual((r1["status"], r1["error"]), ("QUEUED", "boom"))
        self.assertIsNone(self.engine.claim_next("w"))  # backoff delays the retry
        self.make_due(j["id"])
        self.engine.claim_next("w")
        r2 = self.engine.fail(j["id"], "w", "boom again")
        self.assertEqual((r2["status"], r2["attempts"]), ("FAILED", 2))
        self.assertIsNotNone(r2["finished_at"])

    def test_fail_without_retry(self):
        j = self.engine.enqueue("k", "t")
        self.engine.claim_next("w")
        self.assertEqual(self.engine.fail(j["id"], "w", "fatal", retry=False)["status"], "FAILED")

    def test_cancel(self):
        j = self.engine.enqueue("k", "t")
        self.assertEqual(self.engine.cancel(j["id"])["status"], "CANCELLED")
        self.assertEqual(self.code(self.engine.cancel, j["id"]), "BAD_STATE")
        self.assertEqual(self.code(self.engine.cancel, 999), "NOT_FOUND")
        self.assertIsNone(self.engine.claim_next("w"))

    def test_pause_blocks_claims_only(self):
        self.engine.enqueue("k", "t")
        self.engine.set_paused(True)
        self.assertTrue(self.engine.is_paused())
        self.assertIsNone(self.engine.claim_next("w"))
        self.assertEqual(self.engine.enqueue("k", "still accepted")["status"], "QUEUED")
        self.engine.set_paused(False)
        self.assertIsNotNone(self.engine.claim_next("w"))

    def test_recover_stale(self):
        j = self.engine.enqueue("k", "t", max_attempts=2)
        self.engine.claim_next("w")
        conn = self.storage._connect()
        conn.execute("UPDATE jobs SET started_at='2000-01-01T00:00:00.000000Z'")
        conn.close()
        self.assertEqual(self.engine.recover_stale(900), 1)
        self.assertEqual(self.engine.get(j["id"])["status"], "QUEUED")
        self.engine.claim_next("w")
        conn = self.storage._connect()
        conn.execute("UPDATE jobs SET started_at='2000-01-01T00:00:00.000000Z'")
        conn.close()
        self.engine.recover_stale(900)
        self.assertEqual(self.engine.get(j["id"])["status"], "FAILED")

    def test_list_and_counts(self):
        a = self.engine.enqueue("k", "a")
        self.engine.enqueue("k", "b")
        self.engine.cancel(a["id"])
        self.assertEqual(len(self.engine.list()), 2)
        self.assertEqual([j["title"] for j in self.engine.list(status="CANCELLED")], ["a"])
        self.assertEqual(self.engine.counts()["QUEUED"], 1)
        self.assertEqual(self.code(self.engine.list, "WEIRD"), "BAD_STATUS")

    def test_handlers_success_failure_and_missing(self):
        self.engine.register_handler("echo", lambda job: {"echo": job["payload"]})
        self.engine.register_handler("bad", lambda job: 1 / 0)
        e = self.engine.enqueue("echo", "e", payload={"x": 1})
        self.assertEqual(self.engine.run_once()["result"], {"echo": {"x": 1}})
        b = self.engine.enqueue("bad", "b", max_attempts=1)
        failed = self.engine.run_once()
        self.assertEqual(failed["status"], "FAILED")
        self.assertIn("ZeroDivisionError", failed["error"])
        self.engine.enqueue("unknown", "u")
        self.assertIsNone(self.engine.run_once())  # no handler -> not claimed by this worker
        self.assertEqual(self.engine.get(e["id"])["status"], "SUCCEEDED")
        self.assertIsNotNone(b)

    def test_concurrent_claims_never_double_assign(self):
        for i in range(20):
            self.engine.enqueue("k", f"j{i}")
        claimed, lock = [], threading.Lock()

        def worker(name):
            while True:
                job = self.engine.claim_next(name)
                if not job:
                    return
                with lock:
                    claimed.append(job["id"])

        threads = [threading.Thread(target=worker, args=(f"w{n}",)) for n in range(5)]
        [t.start() for t in threads]
        [t.join() for t in threads]
        self.assertEqual(len(claimed), 20)
        self.assertEqual(len(set(claimed)), 20)


class AgentTests(Base):
    def test_register_validation_and_upsert(self):
        for bad in ("A", "Bad Name", "1abc", ""):
            self.assertEqual(self.code(self.agents.register, bad, "r"), "BAD_NAME")
        self.assertEqual(self.code(self.agents.register, "claude2", ""), "BAD_ROLE")
        a = self.agents.register("Claude2", "backend", ["python", "python", " api "])
        self.assertEqual((a["name"], a["capabilities"], a["status"]), ("claude2", ["api", "python"], "OFFLINE"))
        self.agents.register("claude2", "backend-core")
        self.assertEqual(self.agents.get("claude2")["role"], "backend-core")
        self.assertEqual(len(self.agents.list()), 1)

    def test_heartbeat_and_online(self):
        self.agents.register("claude3", "frontend")
        self.assertFalse(self.agents.get("claude3")["online"])
        a = self.agents.heartbeat("claude3", current_job=7)
        self.assertEqual((a["status"], a["current_job"], a["online"]), ("IDLE", 7, True))
        self.assertEqual(self.agents.heartbeat("claude3", status="BUSY")["status"], "BUSY")
        self.assertEqual(self.code(self.agents.heartbeat, "claude3", status="WEIRD"), "BAD_STATUS")
        self.assertEqual(self.code(self.agents.heartbeat, "ghost"), "NOT_FOUND")

    def test_stale_heartbeat_is_offline(self):
        self.agents.register("gemini", "visual")
        self.agents.heartbeat("gemini")
        conn = self.storage._connect()
        conn.execute("UPDATE agent_registry SET last_seen='2000-01-01T00:00:00.000000Z'")
        conn.close()
        self.assertFalse(self.agents.get("gemini")["online"])

    def test_disable_blocks_heartbeat(self):
        self.agents.register("claude2", "backend")
        self.assertEqual(self.agents.set_enabled("claude2", False)["status"], "DISABLED")
        self.assertEqual(self.code(self.agents.heartbeat, "claude2"), "DISABLED")
        self.assertEqual(self.agents.set_enabled("claude2", True)["status"], "OFFLINE")
        self.assertEqual(self.agents.heartbeat("claude2")["status"], "IDLE")

    def test_find_capable_prefers_idle_and_skips_disabled(self):
        for n in ("a1", "a2", "a3"):
            self.agents.register(n, "r", ["flutter"])
        self.agents.register("other", "r", ["python"])
        self.agents.heartbeat("a2", status="IDLE")
        self.agents.heartbeat("a3", status="BUSY")
        self.agents.set_enabled("a1", False)
        self.assertEqual([a["name"] for a in self.agents.find_capable("flutter")], ["a2", "a3"])


if __name__ == "__main__":
    unittest.main()
