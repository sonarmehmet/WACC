import json
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from wacc_backend.accounts import _clean  # noqa: E402
from wacc_backend.orchestrator import (  # noqa: E402
    LOCAL, MockProvider, OpenAICompatProvider, Orchestrator, OrchestratorError, ProviderError, classify_http, clean_key)
from wacc_backend.storage import Storage  # noqa: E402
import tempfile  # noqa: E402


class XaiLike(BaseHTTPRequestHandler):
    """Behaves like api.x.ai: /v1/responses only; the key decides the outcome."""
    seen = []

    def log_message(self, *a):
        pass

    def _json(self, code, payload):
        raw = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(raw)

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        key = (self.headers.get("Authorization") or "")[7:]
        XaiLike.seen.append((self.path, key, body))
        if self.path != "/v1/responses":
            return self._json(404, {"error": "not found"})
        if key == "bad":
            return self._json(400, {"error": "Incorrect API key provided: bad"})
        if key == "mgmt":
            return self._json(403, {"error": "This is a management key; use it with the management API"})
        if key == "nocredit":
            return self._json(403, {"error": "Your team has either used all available credits or reached its monthly spending limit"})
        if body["model"] != "grok-4.7":
            return self._json(404, {"error": {"message": "The model " + body["model"] + " does not exist"}})
        self._json(200, {"output": [{"type": "reasoning", "content": []},
                                    {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "OK"}]}],
                         "usage": {"input_tokens": 9, "output_tokens": 2}})


class GrokTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = HTTPServer(("127.0.0.1", 0), XaiLike)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.url = f"http://127.0.0.1:{cls.srv.server_port}/v1"

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.orch = Orchestrator(Storage(Path(self.tmp.name) / "b.db"))
        XaiLike.seen = []

    def tearDown(self):
        self.tmp.cleanup()

    def grok(self, name, key, model="grok-4.7"):
        p = OpenAICompatProvider(name, LOCAL, self.url, model, api_key=key)
        p.api = "responses"  # what the api.x.ai host selects automatically
        return p

    def test_xai_host_uses_responses_api_and_key_is_cleaned(self):
        p = OpenAICompatProvider("g", "cloud", "https://api.x.ai/v1", "grok-4.7", api_key='  "Bearer xai-key1"\n')
        self.assertEqual(p.api, "responses")
        self.assertEqual(p._api_key, "xai-key1")
        self.assertEqual(OpenAICompatProvider("o", "cloud", "https://api.openai.com/v1", "m", api_key="k").api, "chat")

    def test_responses_request_and_answer(self):
        out = self.grok("g", " 'good' ").complete("hi", "be brief", 16)
        self.assertEqual((out.text, out.tokens_in, out.tokens_out), ("OK", 9, 2))
        path, key, body = XaiLike.seen[0]
        self.assertEqual((path, key), ("/v1/responses", "good"))
        self.assertEqual([m["role"] for m in body["input"]], ["system", "user"])
        self.assertIs(body["store"], False)
        self.assertNotIn("messages", body)

    def test_api_errors_are_told_apart_from_model_errors(self):
        for key, model, category in (("bad", "grok-4.7", "key"), ("mgmt", "grok-4.7", "key"),
                                     ("nocredit", "grok-4.7", "credits"), ("good", "grok-9", "model")):
            with self.assertRaises(ProviderError) as cm:
                self.grok("g", key, model).complete("hi", None, 16)
            self.assertEqual(cm.exception.category, category, key)
            self.assertTrue(cm.exception.hint)
        self.assertIn("Management", classify_http(403, "management key", "api.x.ai")[1])

    def test_each_account_is_tested_alone_and_a_failure_blocks_nobody(self):
        self.orch.add_account(self.grok("grok1", "bad"))
        self.orch.add_account(self.grok("grok2", "good"))
        self.orch.add_account(self.grok("grok3", "nocredit"))
        results = {n: self.orch.test_provider(n) for n in ("grok1", "grok2", "grok3")}
        self.assertEqual([results[n]["ok"] for n in ("grok1", "grok2", "grok3")], [False, True, False])
        self.assertEqual(results["grok1"]["category"], "key")
        self.assertEqual(results["grok3"]["category"], "credits")
        self.assertEqual(results["grok2"]["model"], "grok-4.7")
        # broken accounts are skipped for a while, the working one answers, nothing was deleted
        out = self.orch.complete("hi")
        self.assertEqual(out["provider"], "grok2")
        self.assertEqual(out["fallbacks"], 0)
        listed = {p["name"]: p for p in self.orch.list_providers()}
        self.assertEqual(set(listed), {"grok1", "grok2", "grok3"})
        self.assertTrue(listed["grok1"]["cooling_down"])
        # an explicit request for the broken account still tries it (and reports why it fails)
        self.assertEqual(self.orch.test_provider("grok1")["category"], "key")

    def test_fixed_key_recovers_after_cooldown_reset(self):
        self.orch.add_account(self.grok("grok1", "bad"))
        self.orch.add_account(MockProvider(name="spare"))
        self.orch.test_provider("grok1")
        self.assertEqual(self.orch.complete("hi", prefer="cloud")["provider"], "spare")
        self.orch.providers["grok1"]._api_key = "good"
        self.assertTrue(self.orch.test_provider("grok1")["ok"])
        self.assertFalse({p["name"]: p for p in self.orch.list_providers()}["grok1"]["cooling_down"])

    def test_saved_accounts_with_messy_keys_are_cleaned_not_dropped(self):
        acc = _clean({"name": "grok1", "kind": "cloud", "base_url": "https://api.x.ai/v1", "model": "grok-4.7",
                      "api_key": ' "xai-abc123" \n'})
        self.assertEqual(acc["api_key"], "xai-abc123")
        with self.assertRaises(OrchestratorError):
            _clean({"name": "grok1", "kind": "cloud", "base_url": "https://api.x.ai/v1", "model": "grok-4.7", "api_key": "xai abc"})

    def test_clean_key_rules(self):
        self.assertEqual(clean_key("“xai-x”​"), "xai-x")
        for bad in ("a b", "xaiş", "x" * 501):
            with self.assertRaises(ValueError):
                clean_key(bad)


if __name__ == "__main__":
    unittest.main()
