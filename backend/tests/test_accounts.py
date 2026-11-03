import json
import os
import stat
import sys
import tempfile
import threading
import unittest
from http.server import HTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from test_ai import FakeLLM  # noqa: E402
from wacc_backend.accounts import AccountStore, public_view, to_provider  # noqa: E402
from wacc_backend.orchestrator import MockProvider, Orchestrator, OrchestratorError  # noqa: E402
from wacc_backend.storage import Storage, StorageError  # noqa: E402


class AccountTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.store = AccountStore(base / "ai_accounts.json")
        self.orch = Orchestrator(Storage(base / "b.db"), [MockProvider()])
        self.srv = HTTPServer(("127.0.0.1", 0), FakeLLM)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.srv.server_port}/v1"
        FakeLLM.mode = "ok"

    def tearDown(self):
        self.srv.shutdown()
        self.srv.server_close()
        self.tmp.cleanup()

    def local(self, **kw):
        return {"name": "my-ollama", "kind": "local", "base_url": self.url, "model": "llama3", **kw}

    def code(self, fn, *a, **kw):
        with self.assertRaises(StorageError) as cm:
            fn(*a, **kw)
        return cm.exception.code

    # --- store
    def test_add_persist_and_reload_without_exposing_the_key(self):
        acc = self.store.add({"name": "openrouter", "kind": "cloud", "base_url": "https://openrouter.ai/api/v1",
                              "model": "some/model", "api_key": "sk-secret-123456"})
        self.assertNotIn("api_key", public_view(acc))
        self.assertTrue(public_view(acc)["has_key"])
        self.assertNotIn("sk-secret", json.dumps(public_view(acc)))
        again = AccountStore(self.store.path).load()
        self.assertEqual([a["name"] for a in again], ["openrouter"])
        self.assertEqual(again[0]["api_key"], "sk-secret-123456")
        self.assertEqual(again[0]["price_in_per_1k"], 0.003)  # cloud defaults so the budget still means something
        if os.name == "posix":
            self.assertEqual(stat.S_IMODE(os.stat(self.store.path).st_mode), 0o600)

    def test_validation_rules(self):
        bad = [
            ({"name": "A", "kind": "local", "base_url": self.url, "model": "m"}, "BAD_NAME"),
            ({"name": "mock", "kind": "local", "base_url": self.url, "model": "m"}, "BAD_NAME"),
            ({"name": "x1", "kind": "wat", "base_url": self.url, "model": "m"}, "BAD_KIND"),
            ({"name": "x1", "kind": "local", "base_url": "http://example.com/v1", "model": "m"}, "BAD_URL"),  # not loopback
            ({"name": "x1", "kind": "cloud", "base_url": "http://api.example.com/v1", "model": "m", "api_key": "k"}, "BAD_URL"),
            ({"name": "x1", "kind": "cloud", "base_url": "https://api.example.com/v1", "model": "m"}, "BAD_KEY"),
            ({"name": "x1", "kind": "cloud", "base_url": "https://api.example.com/v1", "model": "m", "api_key": "a b"}, "BAD_KEY"),
            ({"name": "x1", "kind": "local", "base_url": self.url, "model": "two words"}, "BAD_MODEL"),
            ({"name": "x1", "kind": "local", "base_url": self.url, "model": "m", "price_in_per_1k": -1}, "BAD_PRICE"),
        ]
        for spec, expected in bad:
            self.assertEqual(self.code(self.store.add, spec), expected, spec)
        self.assertEqual(self.store.load(), [])

    def test_duplicate_and_limit(self):
        self.store.add(self.local())
        self.assertEqual(self.code(self.store.add, self.local()), "DUPLICATE")
        for i in range(19):
            self.store.add(self.local(name=f"acc-{i:02d}"))
        self.assertEqual(self.code(self.store.add, self.local(name="one-too-many")), "TOO_MANY")

    def test_remove_and_enable_persist(self):
        self.store.add(self.local())
        self.assertFalse(self.store.set_enabled("my-ollama", False)["enabled"])
        self.assertFalse(AccountStore(self.store.path).load()[0]["enabled"])
        self.assertTrue(self.store.remove("my-ollama"))
        self.assertFalse(self.store.remove("my-ollama"))
        self.assertIsNone(self.store.set_enabled("ghost", True))

    def test_corrupt_file_and_bad_entries_do_not_break_loading(self):
        self.store.path.write_text("not json", encoding="utf-8")
        self.assertEqual(self.store.load(), [])
        self.store.path.write_text(json.dumps([self.local(), {"name": "BAD!"}, "junk"]), encoding="utf-8")
        self.assertEqual([a["name"] for a in self.store.load()], ["my-ollama"])

    # --- orchestrator
    def test_account_is_used_then_switched_off_and_removed_at_runtime(self):
        acc = self.store.add(self.local())
        self.orch.add_account(to_provider(acc))
        out = self.orch.complete("hi", provider="my-ollama")
        self.assertEqual((out["provider"], out["text"]), ("my-ollama", "pong"))

        self.orch.set_enabled("my-ollama", False)
        self.assertEqual(self.code(self.orch.complete, "hi", provider="my-ollama"), "DISABLED")
        self.assertEqual(self.orch.complete("hi")["provider"], "mock")  # auto routing skips switched-off accounts
        self.assertFalse([p for p in self.orch.list_providers() if p["name"] == "my-ollama"][0]["enabled"])

        self.orch.set_enabled("my-ollama", True)
        self.assertEqual(self.orch.complete("hi", provider="my-ollama")["provider"], "my-ollama")  # usable again
        self.assertTrue(self.orch.remove_account("my-ollama"))
        self.assertEqual(self.code(self.orch.complete, "hi", provider="my-ollama"), "NOT_FOUND")

    def test_env_providers_cannot_be_removed_and_names_cannot_clash(self):
        self.assertEqual(self.code(self.orch.remove_account, "mock"), "NOT_REMOVABLE")
        self.assertEqual(self.code(self.orch.add_account, MockProvider()), "DUPLICATE")
        self.assertEqual(self.code(self.orch.set_enabled, "ghost", True), "NOT_FOUND")

    def test_test_provider_reports_success_failure_and_works_when_switched_off(self):
        self.orch.add_account(to_provider(self.store.add(self.local())), enabled=False)
        ok = self.orch.test_provider("my-ollama")
        self.assertTrue(ok["ok"])
        self.assertEqual(ok["reply"], "pong")
        FakeLLM.mode = "500"
        bad = self.orch.test_provider("my-ollama")
        self.assertFalse(bad["ok"])
        self.assertIn("HTTP 500", bad["error"])
        self.assertEqual(self.code(self.orch.test_provider, "ghost"), "NOT_FOUND")

    def test_cloud_key_is_sent_but_never_listed(self):
        class Capture(FakeLLM):
            pass
        acc = {"name": "cloudy", "kind": "cloud", "base_url": "https://api.example.com/v1", "model": "m",
               "api_key": "sk-abcdefghijk"}
        p = to_provider(self.store.add(acc))
        self.orch.add_account(p)
        listing = json.dumps(self.orch.list_providers())
        self.assertNotIn("sk-abcdefghijk", listing)
        self.assertNotIn("sk-abcdefghijk", repr(p))


if __name__ == "__main__":
    unittest.main()
