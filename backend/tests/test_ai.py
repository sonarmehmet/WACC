import json
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from wacc_backend.memory import Memory  # noqa: E402
from wacc_backend.orchestrator import (  # noqa: E402
    CLOUD, LOCAL, MockProvider, OpenAICompatProvider, Orchestrator, OrchestratorError,
    ProviderError, build_providers, scrub, validate_base_url)
from wacc_backend.storage import Storage, StorageError  # noqa: E402


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.storage = Storage(Path(self.tmp.name) / "b.db")

    def tearDown(self):
        self.tmp.cleanup()

    def code(self, fn, *a, **kw):
        with self.assertRaises(StorageError) as cm:
            fn(*a, **kw)
        return cm.exception.code


class OrchestratorTests(Base):
    def make(self, *providers):
        return Orchestrator(self.storage, list(providers))

    def test_no_provider_and_validation(self):
        o = self.make()
        self.assertEqual(self.code(o.complete, "hi"), "NO_PROVIDER")
        o = self.make(MockProvider())
        self.assertEqual(self.code(o.complete, "  "), "BAD_PROMPT")
        self.assertEqual(self.code(o.complete, "x" * 100_001), "PROMPT_TOO_LARGE")
        self.assertEqual(self.code(o.complete, "hi", max_tokens=0), "BAD_MAX_TOKENS")
        self.assertEqual(self.code(o.complete, "hi", prefer="best"), "BAD_PREFERENCE")
        self.assertEqual(self.code(o.complete, "hi", provider="ghost"), "NOT_FOUND")

    def test_local_first_even_when_cloud_added_first(self):
        cloud = MockProvider(name="cloud", kind=CLOUD, price_in_per_1k=0.01, price_out_per_1k=0.01)
        local = MockProvider(name="local", kind=LOCAL)
        o = self.make(cloud, local)
        r = o.complete("hello")
        self.assertEqual((r["provider"], r["cost_usd"], cloud.calls), ("local", 0.0, 0))

    def test_prefer_cloud(self):
        o = self.make(MockProvider(name="local"), MockProvider(name="cloud", kind=CLOUD, price_in_per_1k=0.001))
        self.assertEqual(o.complete("hello", prefer="cloud")["provider"], "cloud")

    def test_fallback_to_next_provider_and_ledger(self):
        o = self.make(MockProvider(name="local", fail=True), MockProvider(name="cloud", kind=CLOUD, price_in_per_1k=0.0001))
        r = o.complete("hello")
        self.assertEqual((r["provider"], r["fallbacks"]), ("cloud", 1))
        by = {p["provider"]: p for p in o.usage_summary()["providers"]}
        self.assertEqual((by["local"]["calls"], by["local"]["ok_calls"]), (1, 0))
        self.assertEqual(by["cloud"]["ok_calls"], 1)

    def test_all_failed(self):
        o = self.make(MockProvider(name="a", fail=True), MockProvider(name="b", fail=True))
        self.assertEqual(self.code(o.complete, "hi"), "ALL_FAILED")

    def test_budget_blocks_cloud_but_not_local(self):
        cloud = MockProvider(name="cloud", kind=CLOUD, price_in_per_1k=1.0, price_out_per_1k=1.0)
        o = self.make(cloud)
        o.set_budget(0.001)
        self.assertEqual(self.code(o.complete, "hello world " * 50), "BUDGET_EXCEEDED")
        self.assertEqual(cloud.calls, 0)
        o.add_provider(MockProvider(name="local"))
        self.assertEqual(o.complete("hello")["provider"], "local")

    def test_budget_accumulates(self):
        cloud = MockProvider(name="cloud", kind=CLOUD, price_in_per_1k=1.0, price_out_per_1k=1.0)
        o = self.make(cloud)
        o.set_budget(0.30)
        served = 0
        for _ in range(100):
            try:
                o.complete("hello world", max_tokens=100)
                served += 1
            except OrchestratorError as exc:
                self.assertEqual(exc.code, "BUDGET_EXCEEDED")
                break
        self.assertGreaterEqual(served, 1)
        self.assertLess(served, 100)
        self.assertLessEqual(o.spent_today(), 0.30 + 1e-9)

    def test_set_budget_validation(self):
        o = self.make()
        for bad in (-1, 5000, "x", float("nan"), float("inf"), True):  # NaN would switch the limit off
            self.assertEqual(self.code(o.set_budget, bad), "BAD_BUDGET")
        self.assertEqual(o.set_budget(2.5), 2.5)
        self.assertEqual(o.get_budget(), 2.5)

    def test_ledger_never_stores_prompt_text(self):
        o = self.make(MockProvider())
        o.complete("TOP-SECRET-PROMPT-TEXT")
        conn = self.storage._connect()
        dump = json.dumps([dict(r) for r in conn.execute("SELECT * FROM ai_usage").fetchall()])
        conn.close()
        self.assertNotIn("TOP-SECRET", dump)

    def test_scrub_removes_keys(self):
        self.assertNotIn("sk-abcdef123456", scrub("failed with key sk-abcdef123456"))
        self.assertNotIn("hunter2", scrub("api_key=hunter2 and more"))
        self.assertNotIn("abc.def", scrub("Authorization: Bearer abc.def"))

    def test_url_validation(self):
        self.assertEqual(validate_base_url("http://127.0.0.1:11434/v1/", LOCAL), "http://127.0.0.1:11434/v1")
        self.assertEqual(validate_base_url("http://localhost:1234/v1", LOCAL), "http://localhost:1234/v1")
        for bad in ("http://example.com/v1", "http://192.168.1.5/v1", "ftp://localhost", ""):
            with self.assertRaises(ValueError):
                validate_base_url(bad, LOCAL)
        self.assertEqual(validate_base_url("https://api.example.com/v1", CLOUD), "https://api.example.com/v1")
        with self.assertRaises(ValueError):
            validate_base_url("http://api.example.com/v1", CLOUD)

    def test_build_providers_from_env(self):
        self.assertEqual(build_providers({}), [])
        ps = build_providers({"WACC_ENABLE_MOCK": "1", "WACC_LOCAL_LLM_URL": "http://127.0.0.1:11434/v1",
                              "WACC_CLOUD_LLM_URL": "https://api.example.com/v1", "WACC_CLOUD_LLM_KEY": "k"})
        self.assertEqual([p.name for p in ps], ["mock", "local-llm", "cloud-llm"])
        with self.assertRaises(ValueError):
            build_providers({"WACC_CLOUD_LLM_URL": "https://api.example.com/v1"})  # key missing

    def test_api_key_not_in_repr_or_listing(self):
        p = OpenAICompatProvider("c", CLOUD, "https://api.example.com/v1", "m", api_key="sk-supersecretvalue123")
        self.assertNotIn("supersecret", repr(p))
        self.assertNotIn("supersecret", json.dumps(self.make(p).list_providers()))


class FakeLLM(BaseHTTPRequestHandler):
    mode = "ok"
    seen = {}

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        FakeLLM.seen = {"path": self.path, "auth": self.headers.get("Authorization"), "model": body["model"],
                        "roles": [m["role"] for m in body["messages"]]}
        if FakeLLM.mode == "500":
            self.send_response(500)
            self.end_headers()
            return
        payload = b"not json" if FakeLLM.mode == "garbage" else json.dumps(
            {"choices": [{"message": {"content": "pong"}}], "usage": {"prompt_tokens": 7, "completion_tokens": 3}}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *a):
        pass


class OpenAICompatTests(Base):
    def setUp(self):
        super().setUp()
        self.srv = HTTPServer(("127.0.0.1", 0), FakeLLM)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.srv.server_port}/v1"
        FakeLLM.mode = "ok"

    def tearDown(self):
        self.srv.shutdown()
        self.srv.server_close()
        super().tearDown()

    def test_success_uses_chat_completions_and_reports_usage(self):
        p = OpenAICompatProvider("local-llm", LOCAL, self.url, "llama3")
        o = Orchestrator(self.storage, [p])
        r = o.complete("ping", system="be brief")
        self.assertEqual((r["text"], r["tokens_in"], r["tokens_out"], r["model"]), ("pong", 7, 3, "llama3"))
        self.assertEqual(FakeLLM.seen["path"], "/v1/chat/completions")
        self.assertEqual(FakeLLM.seen["roles"], ["system", "user"])
        self.assertIsNone(FakeLLM.seen["auth"])

    def test_http_error_and_garbage_trigger_fallback(self):
        local = OpenAICompatProvider("local-llm", LOCAL, self.url, "m")
        o = Orchestrator(self.storage, [local, MockProvider(name="backup")])
        for mode in ("500", "garbage"):
            FakeLLM.mode = mode
            self.assertEqual(o.complete("ping")["provider"], "backup")

    def test_unreachable_is_provider_error(self):
        p = OpenAICompatProvider("dead", LOCAL, "http://127.0.0.1:1/v1", "m", timeout=2)
        with self.assertRaises(ProviderError):
            p.complete("x", None, 10)


class MemoryTests(Base):
    def setUp(self):
        super().setUp()
        self.mem = Memory(self.storage)

    def test_add_validation(self):
        self.assertEqual(self.code(self.mem.add, "  "), "BAD_CONTENT")
        self.assertEqual(self.code(self.mem.add, "x" * 10_001), "BAD_CONTENT")
        self.assertEqual(self.code(self.mem.add, "ok", tags=[f"t{i}" for i in range(25)]), "BAD_TAGS")
        self.assertEqual(self.code(self.mem.add, "ok", tags=["x" * 41]), "BAD_TAGS")
        self.assertEqual(self.code(self.mem.add, "ok", project_id=9), "NOT_FOUND")

    def test_secrets_are_refused(self):
        for text in ("key sk-abcdefghijklmnop1234", "ghp_" + "a" * 24, "AKIA" + "A" * 16,
                     "-----BEGIN RSA PRIVATE KEY-----", "Authorization: Bearer " + "a" * 30):
            self.assertEqual(self.code(self.mem.add, text), "SECRET_DETECTED")

    def test_add_get_and_tags_normalised(self):
        e = self.mem.add("  Hub uses SQLite WAL  ", tags=["DB", "db", " hub "], source="claude1")
        self.assertEqual((e["content"], e["tags"], e["source"]), ("Hub uses SQLite WAL", ["db", "hub"], "claude1"))
        self.assertEqual(self.mem.get(e["id"])["content"], e["content"])
        self.assertIsNone(self.mem.get(999))

    def test_search_ranking_tags_double_and_recency(self):
        a = self.mem.add("Flutter app talks to the hub API", tags=["mobile"])
        b = self.mem.add("Hub stores messages in SQLite", tags=["hub", "database"])
        c = self.mem.add("Unrelated note about lunch")
        hits = self.mem.search("hub sqlite")
        self.assertEqual([h["id"] for h in hits], [b["id"], a["id"]])
        self.assertEqual(hits[0]["score"], 4)  # sqlite + hub in text, hub in tag (x2) -> 1+1+2
        self.assertNotIn(c["id"], [h["id"] for h in hits])
        self.assertEqual(self.code(self.mem.search, "!!"), "BAD_QUERY")
        first = self.mem.add("zeta rollout note")
        second = self.mem.add("zeta rollout note")
        self.assertEqual([h["id"] for h in self.mem.search("zeta")], [second["id"], first["id"]])  # tie -> newest first

    def test_project_scope_archive_and_list(self):
        p = self.storage.create_project("P")
        a = self.mem.add("alpha decision", project_id=p["id"], tags=["decision"])
        self.mem.add("alpha elsewhere")
        self.assertEqual([m["id"] for m in self.mem.search("alpha", project_id=p["id"])], [a["id"]])
        self.assertEqual(len(self.mem.list(tag="decision")), 1)
        self.assertTrue(self.mem.archive(a["id"])["archived"])
        self.assertEqual(self.mem.search("alpha", project_id=p["id"]), [])
        self.assertIsNotNone(self.mem.get(a["id"]))  # archived, never deleted
        self.assertEqual(self.code(self.mem.archive, 999), "NOT_FOUND")


if __name__ == "__main__":
    unittest.main()
