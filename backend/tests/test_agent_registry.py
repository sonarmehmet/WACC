import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from wacc_backend.config import load_settings  # noqa: E402
from wacc_backend.engine import TaskEngine  # noqa: E402
from wacc_backend.execution.approvals import Approvals  # noqa: E402
from wacc_backend.execution.executor import FakeExecutor  # noqa: E402
from wacc_backend.execution.service import EmergencyStop, ExecutionService  # noqa: E402
from wacc_backend.orchestrator import MockProvider, Orchestrator  # noqa: E402
from wacc_backend.security import AgentTokenBook, get_or_create_agent_tokens, registry_agents  # noqa: E402
from wacc_backend.storage import Storage  # noqa: E402
from wacc_backend.worker import register_builtin_handlers  # noqa: E402


def write_registry(directory, agents):
    (Path(directory) / "agents.json").write_text(json.dumps(agents), encoding="utf-8")


class TokenBookTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.settings = load_settings({"WACC_DATA_DIR": self.tmp.name})

    def tearDown(self):
        self.tmp.cleanup()

    def test_built_ins_work_without_a_registry_file(self):
        book = AgentTokenBook(self.settings)
        tokens = get_or_create_agent_tokens(self.settings)
        self.assertEqual(book.who(tokens["claude2"]), "claude2")
        self.assertIsNone(book.who("nope"))
        self.assertIsNone(book.who(""))

    def test_new_registry_agent_gets_a_token_without_restart_and_removal_revokes_it(self):
        book = AgentTokenBook(self.settings)
        book.who("warm-up")
        write_registry(self.tmp.name, [{"name": "gpt1", "kind": "chatgpt", "role": "R", "provider": None, "enabled": True}])
        # the first lookup after the registry changed creates the token; read it back from the file
        book.who("x")
        token = json.loads(self.settings.agent_tokens_file.read_text(encoding="utf-8"))["gpt1"]
        self.assertEqual(book.who(token), "gpt1")
        write_registry(self.tmp.name, [])  # removed in the Hub
        self.assertIsNone(book.who(token))

    def test_switched_off_agents_are_rejected_until_switched_on(self):
        write_registry(self.tmp.name, [{"name": "gpt1", "kind": "chatgpt", "enabled": True}])
        book = AgentTokenBook(self.settings)
        book.who("x")
        token = json.loads(self.settings.agent_tokens_file.read_text(encoding="utf-8"))["gpt1"]
        self.assertEqual(book.who(token), "gpt1")
        write_registry(self.tmp.name, [{"name": "gpt1", "kind": "chatgpt", "enabled": False}])
        self.assertIsNone(book.who(token))
        write_registry(self.tmp.name, [{"name": "gpt1", "kind": "chatgpt", "enabled": True}])
        self.assertEqual(book.who(token), "gpt1")

    def test_bad_registry_entries_are_ignored(self):
        write_registry(self.tmp.name, [{"name": "../evil"}, {"name": "Good1"}, "junk", {"name": "fine-1", "provider": 5}])
        self.assertEqual([a["name"] for a in registry_agents(self.tmp.name)], ["fine-1"])
        (Path(self.tmp.name) / "agents.json").write_text("not json", encoding="utf-8")
        self.assertEqual(registry_agents(self.tmp.name), [])

    def test_fixed_tokens_are_used_as_given(self):
        book = AgentTokenBook(None, fixed={"claude2": "tok"})
        self.assertEqual(book.who("tok"), "claude2")


class WorkerAgentProviderTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name).resolve()
        storage = Storage(base / "b.db")
        self.engine = TaskEngine(storage)
        approvals = Approvals(storage)
        stop = EmergencyStop(base / "hubdata", self.engine, approvals)
        execution = ExecutionService(storage, [base], FakeExecutor(), stop, approvals)
        self.first, self.second = MockProvider(name="first"), MockProvider(name="second", model="m2")
        self.orch = Orchestrator(storage, [self.first, self.second])
        register_builtin_handlers(self.engine, self.orch, execution, base)
        self.base = base

    def tearDown(self):
        self.tmp.cleanup()

    def run_job(self, payload):
        j = self.engine.enqueue("ai.complete", "t", payload)
        self.engine.run_once("w")
        return self.engine.get(j["id"])

    def test_agent_linked_to_an_account_uses_that_account(self):
        write_registry(self.base, [{"name": "gpt1", "kind": "chatgpt", "provider": "second", "enabled": True}])
        job = self.run_job({"prompt": "hi", "agent": "gpt1"})
        self.assertEqual(job["status"], "SUCCEEDED")
        self.assertEqual(job["result"]["provider"], "second")

    def test_explicit_provider_wins_and_unlinked_or_disabled_agents_use_normal_routing(self):
        write_registry(self.base, [{"name": "gpt1", "kind": "chatgpt", "provider": "second", "enabled": True},
                                   {"name": "gpt2", "kind": "chatgpt", "provider": "second", "enabled": False},
                                   {"name": "gpt3", "kind": "chatgpt", "provider": None, "enabled": True}])
        self.assertEqual(self.run_job({"prompt": "hi", "agent": "gpt1", "provider": "first"})["result"]["provider"], "first")
        self.assertEqual(self.run_job({"prompt": "hi", "agent": "gpt2"})["result"]["provider"], "first")
        self.assertEqual(self.run_job({"prompt": "hi", "agent": "gpt3"})["result"]["provider"], "first")
        self.assertEqual(self.run_job({"prompt": "hi", "agent": "ghost"})["result"]["provider"], "first")


if __name__ == "__main__":
    unittest.main()
