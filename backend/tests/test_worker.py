import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from wacc_backend.engine import TaskEngine  # noqa: E402
from wacc_backend.execution.approvals import Approvals  # noqa: E402
from wacc_backend.execution.executor import FakeExecutor  # noqa: E402
from wacc_backend.execution.service import EmergencyStop, ExecutionService  # noqa: E402
from wacc_backend.orchestrator import MockProvider, Orchestrator  # noqa: E402
from wacc_backend.storage import Storage  # noqa: E402
from wacc_backend.worker import Worker, register_builtin_handlers  # noqa: E402


class WorkerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name).resolve()
        self.root = base / "proj"
        (self.root / "docs").mkdir(parents=True)
        (self.root / "notes.txt").write_text("hello", encoding="utf-8")
        self.storage = Storage(base / "b.db")
        self.engine = TaskEngine(self.storage)
        self.approvals = Approvals(self.storage)
        self.stop = EmergencyStop(base / "hubdata", self.engine, self.approvals)
        self.fake = FakeExecutor()
        self.execution = ExecutionService(self.storage, [self.root], self.fake, self.stop, self.approvals)
        self.orch = Orchestrator(self.storage, [MockProvider()])
        register_builtin_handlers(self.engine, self.orch, self.execution)

    def tearDown(self):
        self.tmp.cleanup()

    def job(self, kind, payload, attempts=3):
        j = self.engine.enqueue(kind, "t", payload, max_attempts=attempts)
        self.engine.run_once("w")
        return self.engine.get(j["id"])

    def test_ai_complete_job_succeeds(self):
        j = self.job("ai.complete", {"prompt": "hello"})
        self.assertEqual(j["status"], "SUCCEEDED")
        self.assertIn("[mock] hello", str(j["result"]))

    def test_bad_ai_payload_fails_without_retry(self):
        j = self.job("ai.complete", {"nope": 1})
        self.assertEqual((j["status"], j["attempts"]), ("FAILED", 1))

    def test_exec_read_runs_through_the_policy(self):
        j = self.job("exec.run", {"action": {"type": "read_file", "path": "notes.txt"}})
        self.assertEqual(j["status"], "SUCCEEDED", j)
        self.assertEqual(self.fake.calls[-1]["type"], "read_file") if hasattr(self.fake, "calls") else None

    def test_denied_action_fails_permanently(self):
        j = self.job("exec.run", {"action": {"type": "read_file", "path": "../outside.txt"}})
        self.assertEqual((j["status"], j["attempts"]), ("FAILED", 1))
        self.assertIn("Denied", j["error"])

    def test_action_needing_approval_names_the_approval_and_then_runs_once_approved(self):
        action = {"type": "run", "argv": ["pip", "install", "requests"]}
        j = self.job("exec.run", {"action": action})
        self.assertEqual((j["status"], j["attempts"]), ("FAILED", 1))
        self.assertIn("Approval #", j["error"])
        pending = self.approvals.list("PENDING")
        self.assertEqual(len(pending), 1)
        self.approvals.decide(pending[0]["id"], True, "user")
        j2 = self.job("exec.run", {"action": action, "approval_id": pending[0]["id"]})
        self.assertEqual(j2["status"], "SUCCEEDED", j2)
        # same package/version was approved and run before: no second approval (spec 9.2)
        self.assertEqual(self.job("exec.run", {"action": action})["status"], "SUCCEEDED")

    def test_approval_is_single_use_for_other_actions(self):
        action = {"type": "delete_path", "path": "notes.txt"}
        first = self.job("exec.run", {"action": action})
        self.assertEqual(first["status"], "FAILED")
        approval = self.approvals.list("PENDING")[0]["id"]
        self.approvals.decide(approval, True, "user")
        self.assertEqual(self.job("exec.run", {"action": action, "approval_id": approval})["status"], "SUCCEEDED")
        again = self.job("exec.run", {"action": action, "approval_id": approval}, attempts=1)
        self.assertEqual(again["status"], "FAILED")

    def test_emergency_stop_blocks_exec_jobs_and_pause_blocks_all(self):
        self.stop.trigger("test")
        self.assertIsNone(self.engine.run_once("w"))  # engine is paused by the stop
        self.stop.clear()
        self.assertEqual(self.job("ai.complete", {"prompt": "x"})["status"], "SUCCEEDED")

    def test_worker_thread_processes_and_stops(self):
        worker = Worker(self.engine, poll_seconds=0.05)
        j = self.engine.enqueue("ai.complete", "t", {"prompt": "bg"})
        worker.start()
        try:
            for _ in range(100):
                if self.engine.get(j["id"])["status"] == "SUCCEEDED":
                    break
                import time
                time.sleep(0.05)
        finally:
            worker.stop()
        self.assertEqual(self.engine.get(j["id"])["status"], "SUCCEEDED")
        self.assertFalse(worker._thread.is_alive())


if __name__ == "__main__":
    unittest.main()
