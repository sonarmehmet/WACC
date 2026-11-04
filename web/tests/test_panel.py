"""End-to-end checks for the web panel server (T-0005).

Starts a real Communication Hub on a temp database and the panel server in front of it, then
drives both over HTTP the way the browser does. Needs the hub dependencies (fastapi, uvicorn).

    python -m unittest discover -s web/tests -v
"""

import http.client
import http.server
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

WEB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WEB))
sys.path.insert(0, str(WEB.parent / "hub"))

try:
    import uvicorn
    from wacc_hub.api import create_app
    from wacc_hub.service import Hub
    HAVE_HUB = True
except Exception:  # hub dependencies not installed
    HAVE_HUB = False

sys.path.insert(0, str(WEB.parent / "backend"))
try:
    from wacc_backend.app import create_app as create_backend_app
    from wacc_backend.config import load_settings as load_backend_settings
    from wacc_backend.execution.executor import FakeExecutor
    from wacc_backend.orchestrator import MockProvider
    HAVE_BACKEND = True
except Exception:  # backend (or its dependencies) not available
    HAVE_BACKEND = False

import serve  # noqa: E402

TOKENS = {a: "tok-" + a for a in ("claude1", "claude2", "claude3", "gemini", "user")}


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]



class _FakeLLMHandler(http.server.BaseHTTPRequestHandler):
    """Tiny OpenAI-compatible endpoint (chat completions) on loopback."""
    seen_auth = []

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        self.rfile.read(length)
        type(self).seen_auth.append(self.headers.get("Authorization"))
        body = json.dumps({"choices": [{"message": {"content": "OK"}}],
                           "usage": {"prompt_tokens": 5, "completion_tokens": 1}}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


@unittest.skipUnless(HAVE_HUB, "fastapi/uvicorn not installed")
class PanelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        hub = Hub(os.path.join(cls.tmp.name, "hub.db"))
        hub_port = free_port()
        cls.hub_server = uvicorn.Server(uvicorn.Config(
            create_app(hub, dict(TOKENS)), host="127.0.0.1", port=hub_port, log_level="warning"))
        cls.hub_thread = threading.Thread(target=cls.hub_server.run, daemon=True)
        cls.hub_thread.start()
        deadline = time.time() + 10
        while not cls.hub_server.started and time.time() < deadline:
            time.sleep(0.05)
        assert cls.hub_server.started, "hub did not start"

        cls.panel = serve.create_server(0, "http://127.0.0.1:%d" % hub_port)
        cls.port = cls.panel.server_address[1]
        threading.Thread(target=cls.panel.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.panel.shutdown()
        cls.panel.server_close()
        cls.hub_server.should_exit = True
        cls.hub_thread.join(5)
        cls.tmp.cleanup()

    # ------------------------------------------------------------------ helpers
    def call(self, method, path, body=None, token=None, headers=None, port=None):
        hdrs = dict(headers or {})
        if token:
            hdrs["X-WACC-Token"] = TOKENS.get(token, token)
        data = None
        if body is not None:
            data = json.dumps(body)
            hdrs["Content-Type"] = "application/json"
        conn = http.client.HTTPConnection("127.0.0.1", port or self.port, timeout=10)
        try:
            conn.request(method, path, body=data, headers=hdrs)
            resp = conn.getresponse()
            raw = resp.read()
            return resp.status, dict(resp.getheaders()), raw
        finally:
            conn.close()

    def api(self, method, path, body=None, token="user"):
        status, _, raw = self.call(method, "/api" + path, body, token)
        return status, json.loads(raw or b"null")

    # ------------------------------------------------------------------- static
    def test_serves_panel_files_with_security_headers(self):
        for path, needle in (("/", b"WACC Panel"), ("/app.js", b"X-WACC-Token"), ("/style.css", b"--accent")):
            status, headers, raw = self.call("GET", path)
            self.assertEqual(status, 200, path)
            self.assertIn(needle, raw, path)
        _, headers, _ = self.call("GET", "/")
        self.assertIn("default-src 'self'", headers["Content-Security-Policy"])
        self.assertEqual(headers["X-Content-Type-Options"], "nosniff")

    def test_path_traversal_is_refused(self):
        for path in ("/../serve.py", "/%2e%2e/serve.py", "/..%2fserve.py", "/public/../../README.md"):
            status, _, raw = self.call("GET", path)
            self.assertEqual(status, 404, path)
            self.assertNotIn(b"ThreadingHTTPServer", raw)

    def test_foreign_host_header_is_refused(self):
        status, _, _ = self.call("GET", "/", headers={"Host": "evil.example"})
        self.assertEqual(status, 403)
        status, _, _ = self.call("GET", "/api/health", headers={"Host": "evil.example:8780"})
        self.assertEqual(status, 403)

    def test_cross_origin_post_is_refused(self):
        status, _, _ = self.call("POST", "/api/messages", {"x": 1}, "user",
                                 headers={"Origin": "http://evil.example"})
        self.assertEqual(status, 403)

    def test_only_get_and_post_are_allowed(self):
        for method in ("PUT", "DELETE", "PATCH"):
            status, _, _ = self.call(method, "/api/tasks", token="user")
            self.assertEqual(status, 405, method)

    def test_only_agent_removal_is_forwarded_as_hub_delete(self):
        for path in ("/api/agents/Upper", "/api/agents/a", "/api/agents/ab/cd", "/api/agents/", "/api/messages/1"):
            status, _, _ = self.call("DELETE", path, token="user")
            self.assertEqual(status, 405, path)
        status, _, _ = self.call("DELETE", "/api/agents/gone-agent", token="user")
        self.assertEqual(status, 404)  # reached the Hub, which says the agent is unknown

    # -------------------------------------------------------------------- proxy
    def test_health_is_proxied_without_token(self):
        status, body = self.api("GET", "/health", token=None)
        self.assertEqual(status, 200)
        self.assertTrue(body["ok"])
        self.assertFalse(body["emergency_stop"])

    def test_missing_or_wrong_token_is_401(self):
        self.assertEqual(self.api("GET", "/whoami", token=None)[0], 401)
        self.assertEqual(self.api("GET", "/whoami", token="wrong")[0], 401)

    def test_token_decides_the_actor(self):
        self.assertEqual(self.api("GET", "/whoami", token="user")[1], {"agent": "user"})
        self.assertEqual(self.api("GET", "/whoami", token="claude3")[1], {"agent": "claude3"})

    def test_agents_overview_lists_all_agents(self):
        status, agents = self.api("GET", "/agents")
        self.assertEqual(status, 200)
        self.assertEqual({a["agent_id"] for a in agents}, set(TOKENS))
        for key in ("online", "unread", "pending_responses", "active_tasks", "blocked_tasks"):
            self.assertIn(key, agents[0])

    def test_post_message_appears_in_feed(self):
        status, sent = self.api("POST", "/messages", {
            "receiver": "claude2", "message_type": "STATUS_UPDATE", "subject": "panel ping",
            "content": "<script>alert(1)</script>", "priority": "HIGH", "response_required": True,
            "idempotency_key": "panel-test-1"})
        self.assertEqual(status, 200, sent)
        status, feed = self.api("GET", "/feed?limit=50")
        self.assertEqual(status, 200)
        mine = [m for m in feed if m["subject"] == "panel ping"]
        self.assertEqual(len(mine), 1)
        self.assertEqual(mine[0]["sender"], "user")
        self.assertEqual(mine[0]["content"], "<script>alert(1)</script>")  # stored verbatim; the UI renders it as text
        status, filtered = self.api("GET", "/feed?conversation_id=" + mine[0]["conversation_id"])
        self.assertEqual([m["message_id"] for m in filtered], [mine[0]["message_id"]])

    def test_create_assign_accept_and_update_task(self):
        status, task = self.api("POST", "/tasks", {
            "title": "panel task", "description": "d", "owner": "claude3", "priority": "HIGH",
            "affected_files": ["web/"], "acceptance": "a", "test_criteria": "t"})
        self.assertEqual(status, 200, task)
        tid = task["task_id"]
        self.assertEqual(task["status"], "ASSIGNED")

        status, tasks = self.api("GET", "/tasks?owner=claude3")
        self.assertIn(tid, [t["task_id"] for t in tasks])
        # the Hub normalises paths (trailing slash dropped)
        self.assertEqual(next(t for t in tasks if t["task_id"] == tid)["affected_files"], ["web"])

        self.assertEqual(self.api("POST", "/tasks/%s/accept" % tid, token="claude3")[0], 200)
        status, updated = self.api("POST", "/tasks/%s/status" % tid,
                                   {"status": "IN_PROGRESS", "note": "started"}, token="claude3")
        self.assertEqual(status, 200, updated)
        self.assertEqual(updated["status"], "IN_PROGRESS")

        status, body = self.api("POST", "/tasks/%s/assign/claude2" % tid)
        self.assertEqual(status, 200, body)

    def test_worker_cannot_create_tasks_and_error_is_passed_through(self):
        status, body = self.api("POST", "/tasks", {"title": "nope"}, token="claude3")
        self.assertEqual(status, 403)
        self.assertEqual(body["detail"]["code"], "FORBIDDEN")

    def test_locks_endpoint(self):
        self.assertEqual(self.api("POST", "/locks", {"path": "web/", "ttl": 60}, token="claude3")[0], 200)
        status, locks = self.api("GET", "/locks")
        self.assertEqual(status, 200)
        lock = next(l for l in locks if l["path"] == "web")
        self.assertEqual(lock["owner"], "claude3")
        self.assertFalse(lock["expired"])
        self.api("POST", "/locks/release", {"path": "web/"}, token="claude3")

    def test_emergency_stop_and_resume(self):
        self.assertEqual(self.api("POST", "/system/stop", {"reason": "panel test"})[0], 200)
        try:
            self.assertTrue(self.api("GET", "/health", token=None)[1]["emergency_stop"])
            # workers are blocked while stopped; only the user may resume
            self.assertEqual(self.api("POST", "/system/resume", token="claude1")[0], 403)
        finally:
            self.assertEqual(self.api("POST", "/system/resume")[0], 200)
        self.assertFalse(self.api("GET", "/health", token=None)[1]["emergency_stop"])

    def test_unreachable_hub_gives_502_with_code(self):
        dead = serve.create_server(0, "http://127.0.0.1:%d" % free_port())
        port = dead.server_address[1]
        threading.Thread(target=dead.serve_forever, daemon=True).start()
        try:
            status, _, raw = self.call("GET", "/api/health", port=port)
        finally:
            dead.shutdown()
            dead.server_close()
        self.assertEqual(status, 502)
        self.assertEqual(json.loads(raw)["detail"]["code"], "HUB_UNREACHABLE")


@unittest.skipUnless(HAVE_HUB and HAVE_BACKEND, "fastapi/uvicorn or backend not available")
class BackendProxyTests(unittest.TestCase):
    """/backend/* is a read-only, allow-listed view of the real Backend."""

    TOKEN = "backend-secret"        # agent token
    USER_TOKEN = "human-secret"     # the only token that may approve
    CLAUDE2_TOKEN = "claude2-secret"  # per-agent token: the Backend attributes /exec by token

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        settings = load_backend_settings({"WACC_DATA_DIR": cls.tmp.name})
        backend_port = free_port()
        cls.backend_server = uvicorn.Server(uvicorn.Config(
            create_backend_app(settings, token=cls.TOKEN, providers=[MockProvider()],
                               executor=FakeExecutor(), user_token=cls.USER_TOKEN,
                               agent_tokens={"claude2": cls.CLAUDE2_TOKEN}),
            host="127.0.0.1", port=backend_port, log_level="warning"))
        cls.backend_thread = threading.Thread(target=cls.backend_server.run, daemon=True)
        cls.backend_thread.start()
        deadline = time.time() + 10
        while not cls.backend_server.started and time.time() < deadline:
            time.sleep(0.05)
        assert cls.backend_server.started, "backend did not start"
        cls.backend_url = "http://127.0.0.1:%d" % backend_port

        cls.llm = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _FakeLLMHandler)
        cls.llm_url = "http://127.0.0.1:%d/v1" % cls.llm.server_address[1]
        threading.Thread(target=cls.llm.serve_forever, daemon=True).start()

        # seed through the real backend API
        cls.direct("POST", "/projects", {"name": "Panel Project", "description": "seed"})
        cls.direct("POST", "/jobs", {"kind": "demo", "title": "<b>seed job</b>"})
        cls.direct("POST", "/agents", {"name": "worker1", "role": "builder", "capabilities": ["build"]}, token=cls.USER_TOKEN)

        cls.panel = serve.create_server(0, "http://127.0.0.1:%d" % free_port(), cls.backend_url)
        cls.port = cls.panel.server_address[1]
        threading.Thread(target=cls.panel.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.panel.shutdown()
        cls.panel.server_close()
        cls.llm.shutdown()
        cls.llm.server_close()
        cls.backend_server.should_exit = True
        cls.backend_thread.join(5)
        cls.tmp.cleanup()

    @classmethod
    def direct(cls, method, path, body=None, token=None):
        """Straight to the Backend as an agent (not through the panel)."""
        conn = http.client.HTTPConnection(cls.backend_url.split("//")[1], timeout=10)
        try:
            conn.request(method, path, body=json.dumps(body) if body is not None else None,
                         headers={"X-WACC-Token": token or cls.TOKEN, "Content-Type": "application/json"})
            resp = conn.getresponse()
            raw = resp.read()
            assert resp.status < 300, (path, resp.status, raw)
            return json.loads(raw or b"null")
        finally:
            conn.close()

    @classmethod
    def request_approval(cls, path):
        """An agent asks to delete `path`; returns the pending approval id."""
        out = cls.direct("POST", "/exec", {"agent": "claude2", "action": {"type": "delete_path", "path": path}},
                         token=cls.CLAUDE2_TOKEN)
        assert out["status"] == "APPROVAL_REQUIRED", out
        return out["approval_id"]

    def post(self, path, token=None, body=None, headers=None, port=None):
        hdrs = {"Content-Type": "application/json"}
        hdrs.update(headers or {})
        if token:
            hdrs["X-WACC-Token"] = token
        conn = http.client.HTTPConnection("127.0.0.1", port or self.port, timeout=10)
        try:
            conn.request("POST", path, body=json.dumps(body if body is not None else {}), headers=hdrs)
            resp = conn.getresponse()
            raw = resp.read()
            return resp.status, json.loads(raw or b"null")
        finally:
            conn.close()

    def delete(self, path, token=None, headers=None, port=None):
        hdrs = dict(headers or {})
        if token:
            hdrs["X-WACC-Token"] = token
        conn = http.client.HTTPConnection("127.0.0.1", port or self.port, timeout=10)
        try:
            conn.request("DELETE", path, headers=hdrs)
            resp = conn.getresponse()
            raw = resp.read()
            return resp.status, json.loads(raw or b"null")
        finally:
            conn.close()

    def get(self, path, token=TOKEN, headers=None, port=None):
        hdrs = dict(headers or {})
        if token:
            hdrs["X-WACC-Token"] = token
        conn = http.client.HTTPConnection("127.0.0.1", port or self.port, timeout=10)
        try:
            conn.request("GET", path, headers=hdrs)
            resp = conn.getresponse()
            raw = resp.read()
            return resp.status, json.loads(raw or b"null")
        finally:
            conn.close()

    def test_health_is_public(self):
        status, body = self.get("/backend/health", token=None)
        self.assertEqual(status, 200)
        self.assertTrue(body["ok"])
        self.assertIn("schema_version", body)

    def test_token_is_required_and_passed_through(self):
        self.assertEqual(self.get("/backend/jobs/summary", token=None)[0], 401)
        self.assertEqual(self.get("/backend/jobs/summary", token="wrong")[0], 401)
        status, body = self.get("/backend/jobs/summary")
        self.assertEqual(status, 200)
        self.assertGreaterEqual(body["counts"]["QUEUED"], 1)
        self.assertIn("paused", body)

    def test_read_endpoints_used_by_the_panel(self):
        status, jobs = self.get("/backend/jobs?limit=50")
        self.assertEqual(status, 200)
        self.assertIn("<b>seed job</b>", [j["title"] for j in jobs])  # raw text; UI renders it as text
        status, projects = self.get("/backend/projects")
        self.assertEqual([p["name"] for p in projects], ["Panel Project"])
        status, agents = self.get("/backend/agents")
        self.assertEqual(agents[0]["name"], "worker1")
        self.assertEqual(agents[0]["capabilities"], ["build"])
        status, providers = self.get("/backend/ai/providers")
        self.assertEqual(status, 200)
        self.assertEqual(len(providers), 1)
        status, usage = self.get("/backend/ai/usage")
        self.assertEqual(status, 200)
        self.assertIn("budget_usd", usage)

    def test_other_backend_paths_are_not_exposed(self):
        for path in ("/backend/memory", "/backend/memory/search?q=x", "/backend/jobs/1",
                     "/backend/jobs/claim", "/backend/engine/pause", "/backend/ai/complete",
                     "/backend/../api/health", "/backend/%2e%2e/api/health", "/backend/projects/1"):
            status, body = self.get(path)
            self.assertEqual(status, 404, path)
            self.assertEqual(body["detail"]["code"], "NOT_EXPOSED", path)

    def test_only_the_listed_writes_are_forwarded(self):
        for path in ("/backend/jobs", "/backend/engine/pause", "/backend/projects", "/backend/exec",
                     "/backend/memory", "/backend/ai/complete", "/backend/ai/budget",
                     "/backend/exec/approvals", "/backend/exec/approvals/x/approve",
                     "/backend/exec/approvals/1/approve/extra", "/backend/exec/approvals/1",
                     "/backend/exec/stopp", "/backend/../exec/stop",
                     # AI accounts: only the exact account/enable/test paths, lower-case names
                     "/backend/ai/accounts/", "/backend/ai/accounts/ab", "/backend/ai/providers/mock",
                     "/backend/ai/providers/Upper/enabled", "/backend/ai/providers/a/enabled",
                     "/backend/ai/providers/ab/enabled/extra", "/backend/ai/providers/ab/budget",
                     "/backend/ai/providers/../ai/budget/test", "/backend/ai/providers/a%2fb/test",
                     "/backend/ai/accounts%2f..%2fbudget"):
            status, _ = self.post(path, token=self.USER_TOKEN, body={"kind": "x", "title": "y"})
            self.assertEqual(status, 405, path)
        for path in ("/backend/ai/accounts", "/backend/ai/accounts/", "/backend/ai/accounts/Upper",
                     "/backend/ai/accounts/a", "/backend/ai/accounts/ab/cd", "/backend/ai/providers/mock",
                     "/backend/projects/1", "/backend/jobs/1", "/backend/exec/approvals/1",
                     "/backend/memory/1", "/backend/ai/budget", "/backend/ai/accounts/../budget"):
            status, _ = self.delete(path, token=self.USER_TOKEN)
            self.assertEqual(status, 405, "DELETE " + path)
        # nothing was created, deleted or paused
        self.assertEqual([p["name"] for p in self.get("/backend/projects")[1]], ["Panel Project"])
        self.assertFalse(self.get("/backend/jobs/summary")[1]["paused"])
        self.assertIn("mock", [p["name"] for p in self.get("/backend/ai/providers")[1]])

    def test_ai_account_lifecycle_and_the_key_never_comes_back(self):
        secret = "sk-test-secret-key-12345"
        acct = {"name": "acct-one", "kind": "local", "base_url": self.llm_url, "model": "fake-model",
                "api_key": secret, "price_in_per_1k": 0.001, "price_out_per_1k": 0.002}
        # an agent token cannot add, switch, test or remove accounts (the Backend decides)
        self.assertEqual(self.post("/backend/ai/accounts", token=self.TOKEN, body=acct)[0], 403)
        self.assertEqual(self.post("/backend/ai/accounts", body=acct)[0], 401)

        status, created = self.post("/backend/ai/accounts", token=self.USER_TOKEN, body=acct)
        self.assertEqual(status, 201, created)
        self.assertNotIn("api_key", created)
        self.assertTrue(created["has_key"])
        self.assertNotIn(secret, json.dumps(created))

        status, providers = self.get("/backend/ai/providers")
        self.assertEqual(status, 200)
        self.assertNotIn(secret, json.dumps(providers))
        row = next(p for p in providers if p["name"] == "acct-one")
        self.assertEqual((row["source"], row["enabled"], row["kind"], row["model"]),
                         ("account", True, "local", "fake-model"))
        self.assertEqual(next(p for p in providers if p["name"] == "mock")["source"], "env")

        # switch off / on
        path = "/backend/ai/providers/acct-one/enabled"
        self.assertEqual(self.post(path, token=self.TOKEN, body={"enabled": False})[0], 403)
        self.assertEqual(self.post(path, token=self.USER_TOKEN, body={"enabled": False})[1],
                         {"name": "acct-one", "enabled": False})
        row = next(p for p in self.get("/backend/ai/providers")[1] if p["name"] == "acct-one")
        self.assertFalse(row["enabled"])

        # test works while switched off and sends the stored key to the endpoint, not to us
        _FakeLLMHandler.seen_auth.clear()
        self.assertEqual(self.post("/backend/ai/providers/acct-one/test", token=self.TOKEN)[0], 403)
        status, result = self.post("/backend/ai/providers/acct-one/test", token=self.USER_TOKEN)
        self.assertEqual(status, 200, result)
        self.assertTrue(result["ok"])
        self.assertEqual(result["reply"], "OK")
        self.assertNotIn(secret, json.dumps(result))
        self.assertEqual(_FakeLLMHandler.seen_auth, ["Bearer " + secret])
        self.assertEqual(self.post(path, token=self.USER_TOKEN, body={"enabled": True})[0], 200)

        # remove
        self.assertEqual(self.delete("/backend/ai/accounts/acct-one", token=self.TOKEN)[0], 403)
        self.assertEqual(self.delete("/backend/ai/accounts/acct-one", token=self.USER_TOKEN),
                         (200, {"removed": True}))
        self.assertNotIn("acct-one", [p["name"] for p in self.get("/backend/ai/providers")[1]])
        self.assertEqual(self.delete("/backend/ai/accounts/acct-one", token=self.USER_TOKEN),
                         (200, {"removed": False}))

    def test_ai_account_validation_errors_are_passed_through_without_the_key(self):
        secret = "sk-another-secret-99999"
        status, body = self.post("/backend/ai/accounts", token=self.USER_TOKEN, body={
            "name": "bad-cloud", "kind": "cloud", "base_url": "http://insecure.example/v1",
            "model": "m", "api_key": secret})
        self.assertEqual(status, 400, body)  # cloud needs https
        self.assertNotIn(secret, json.dumps(body))
        status, body = self.post("/backend/ai/accounts", token=self.USER_TOKEN, body={
            "name": "Bad Name", "kind": "local", "base_url": self.llm_url, "model": "m"})
        self.assertEqual(status, 400, body)
        self.assertNotIn("bad-cloud", [p["name"] for p in self.get("/backend/ai/providers")[1]])

    def test_environment_providers_cannot_be_removed_but_can_be_switched(self):
        status, body = self.delete("/backend/ai/accounts/mock", token=self.USER_TOKEN)
        self.assertGreaterEqual(status, 400, body)
        self.assertIn("mock", [p["name"] for p in self.get("/backend/ai/providers")[1]])
        path = "/backend/ai/providers/mock/enabled"
        self.assertEqual(self.post(path, token=self.USER_TOKEN, body={"enabled": False})[0], 200)
        self.assertEqual(self.post(path, token=self.USER_TOKEN, body={"enabled": True})[0], 200)

    def test_cross_origin_and_foreign_host_ai_changes_are_refused(self):
        acct = {"name": "csrf-acct", "kind": "local", "base_url": self.llm_url, "model": "m"}
        for headers in ({"Origin": "http://evil.example"}, {"Host": "evil.example"}):
            self.assertEqual(self.post("/backend/ai/accounts", token=self.USER_TOKEN, body=acct,
                                       headers=headers)[0], 403)
            self.assertEqual(self.post("/backend/ai/providers/mock/enabled", token=self.USER_TOKEN,
                                       body={"enabled": False}, headers=headers)[0], 403)
            self.assertEqual(self.delete("/backend/ai/accounts/csrf-acct", token=self.USER_TOKEN,
                                         headers=headers)[0], 403)
        names = [p["name"] for p in self.get("/backend/ai/providers")[1]]
        self.assertNotIn("csrf-acct", names)
        self.assertTrue(next(p for p in self.get("/backend/ai/providers")[1] if p["name"] == "mock")["enabled"])

    def test_pending_approval_is_listed_with_the_raw_action(self):
        aid = self.request_approval("list-me.txt")
        status, items = self.get("/backend/exec/approvals?status=PENDING")
        self.assertEqual(status, 200)
        item = next(i for i in items if i["id"] == aid)
        self.assertEqual(item["status"], "PENDING")
        self.assertEqual(item["requested_by"], "claude2")
        self.assertEqual(item["action"]["type"], "delete_path")
        self.assertEqual(len(item["action_hash"]), 64)
        self.assertIn("expires_at", item)

    def test_agent_token_cannot_decide(self):
        aid = self.request_approval("agent-cannot.txt")
        for verb in ("approve", "deny"):
            status, body = self.post("/backend/exec/approvals/%d/%s" % (aid, verb), token=self.TOKEN)
            self.assertEqual(status, 403, verb)
            self.assertEqual(body["detail"]["code"], "FORBIDDEN")
        self.assertEqual(self.post("/backend/exec/approvals/%d/approve" % aid)[0], 401)  # no token at all
        self.assertEqual(self.get("/backend/exec/approvals?status=PENDING")[1][0]["status"], "PENDING")

    def test_user_can_deny(self):
        aid = self.request_approval("deny-me.txt")
        status, body = self.post("/backend/exec/approvals/%d/deny" % aid, token=self.USER_TOKEN)
        self.assertEqual(status, 200, body)
        self.assertEqual((body["status"], body["decided_by"]), ("DENIED", "user"))
        again = self.post("/backend/exec/approvals/%d/approve" % aid, token=self.USER_TOKEN)
        self.assertEqual(again[0], 409)  # decided already: cannot flip it

    def test_user_approval_lets_the_agent_run_once(self):
        action = {"type": "delete_path", "path": "approve-me.txt"}
        aid = self.request_approval("approve-me.txt")
        status, body = self.post("/backend/exec/approvals/%d/approve" % aid, token=self.USER_TOKEN)
        self.assertEqual((status, body["status"]), (200, "APPROVED"))
        done = self.direct("POST", "/exec", {"agent": "claude2", "action": action, "approval_id": aid},
                           token=self.CLAUDE2_TOKEN)
        self.assertEqual(done["status"], "OK")
        # single use: the same approval cannot run it again
        conn = http.client.HTTPConnection(self.backend_url.split("//")[1], timeout=10)
        try:
            conn.request("POST", "/exec", body=json.dumps({"agent": "claude2", "action": action, "approval_id": aid}),
                         headers={"X-WACC-Token": self.CLAUDE2_TOKEN, "Content-Type": "application/json"})
            self.assertEqual(conn.getresponse().status, 403)
        finally:
            conn.close()
        executed = [i for i in self.get("/backend/exec/approvals")[1] if i["id"] == aid][0]
        self.assertEqual(executed["status"], "EXECUTED")

    def test_audit_trail_is_readable(self):
        self.request_approval("audit-me.txt")
        status, rows = self.get("/backend/exec/audit?limit=50")
        self.assertEqual(status, 200)
        self.assertTrue(any(r["outcome"] == "APPROVAL_REQUESTED" for r in rows))

    def test_stop_and_resume(self):
        self.assertFalse(self.get("/backend/exec/status")[1]["emergency_stop"])
        try:
            self.assertEqual(self.post("/backend/exec/stop", token=self.TOKEN, body={"reason": "panel test"})[0], 200)
            self.assertTrue(self.get("/backend/exec/status")[1]["emergency_stop"])
            # an agent token may stop but never resume
            self.assertEqual(self.post("/backend/exec/resume", token=self.TOKEN)[0], 403)
            self.assertTrue(self.get("/backend/exec/status")[1]["emergency_stop"])
        finally:
            self.assertEqual(self.post("/backend/exec/resume", token=self.USER_TOKEN)[0], 200)
        self.assertFalse(self.get("/backend/exec/status")[1]["emergency_stop"])
        self.assertFalse(self.get("/backend/jobs/summary")[1]["paused"])

    def test_cross_origin_decision_is_refused(self):
        aid = self.request_approval("csrf.txt")
        status, _ = self.post("/backend/exec/approvals/%d/approve" % aid, token=self.USER_TOKEN,
                              headers={"Origin": "http://evil.example"})
        self.assertEqual(status, 403)
        status, _ = self.post("/backend/exec/approvals/%d/approve" % aid, token=self.USER_TOKEN,
                              headers={"Host": "evil.example"})
        self.assertEqual(status, 403)
        pending = [i for i in self.get("/backend/exec/approvals?status=PENDING")[1] if i["id"] == aid]
        self.assertEqual(len(pending), 1)  # still undecided

    def test_foreign_host_is_refused(self):
        status, _ = self.get("/backend/health", token=None, headers={"Host": "evil.example"})
        self.assertEqual(status, 403)

    def test_unreachable_backend_gives_502_with_code(self):
        dead = serve.create_server(0, "http://127.0.0.1:1", "http://127.0.0.1:%d" % free_port())
        port = dead.server_address[1]
        threading.Thread(target=dead.serve_forever, daemon=True).start()
        try:
            status, body = self.get("/backend/health", token=None, port=port)
        finally:
            dead.shutdown()
            dead.server_close()
        self.assertEqual(status, 502)
        self.assertEqual(body["detail"]["code"], "BACKEND_UNREACHABLE")


class FrontendSourceTests(unittest.TestCase):
    def test_no_html_injection_sinks(self):
        source = (WEB / "public" / "app.js").read_text(encoding="utf-8")
        for sink in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval(", "new Function"):
            self.assertNotIn(sink, source, sink)

    def test_no_secrets_in_frontend(self):
        for f in (WEB / "public").iterdir():
            self.assertNotIn(b"tokens.json", f.read_bytes(), f.name)  # images included

    def test_remember_token_is_off_by_default(self):
        import re
        html = (WEB / "public" / "index.html").read_text(encoding="utf-8")
        tag = re.search(r'<input[^>]*id="remember"[^>]*>', html)
        self.assertIsNotNone(tag, "remember checkbox missing")
        self.assertIn('type="checkbox"', tag.group(0))
        self.assertNotIn("checked", tag.group(0))  # off unless the user turns it on

    def test_backend_calls_go_through_two_helpers_only(self):
        source = (WEB / "public" / "app.js").read_text(encoding="utf-8")
        self.assertEqual(source.count('request("/backend"'), 2)  # backendGet (GET) and approvalCall
        self.assertIn("function backendGet(path) {\n  return request(\"/backend\", state.backendToken, path, {});", source)

    def test_approval_token_is_never_stored(self):
        source = (WEB / "public" / "app.js").read_text(encoding="utf-8")
        self.assertIn("approvalToken", source)
        for number, line in enumerate(source.splitlines(), 1):
            if "approvalToken" in line or "approvalTimer" in line:
                for sink in ("saveToken", "setItem", "localStorage", "sessionStorage", "document.cookie", "indexedDB"):
                    self.assertNotIn(sink, line, "app.js:%d" % number)
        # the secret is also removed from the input as soon as it is taken
        self.assertIn('$("approvalToken").value = "";', source)

    def test_ai_api_key_is_never_kept(self):
        source = (WEB / "public" / "app.js").read_text(encoding="utf-8")
        for number, line in enumerate(source.splitlines(), 1):
            if "apiKey" in line or '"aiKey"' in line or "api_key" in line:
                for sink in ("saveToken", "setItem", "localStorage", "sessionStorage", "document.cookie",
                             "indexedDB", "console."):
                    self.assertNotIn(sink, line, "app.js:%d" % number)
        self.assertNotIn("state.apiKey", source)
        self.assertNotIn("apiKey:", source)  # never a property of long-lived state
        # the field is emptied before the request leaves, not after it
        self.assertLess(source.index('$("aiKey").value = ""; // the secret leaves'),
                        source.index('await aiChange("/ai/accounts"'))
        self.assertIn("$(\"aiKey\").value = \"\";", source)  # also cleared by "Unut"

    def test_ai_forms_do_not_invite_password_managers(self):
        html = (WEB / "public" / "index.html").read_text(encoding="utf-8")
        self.assertIn('id="aiToken" type="password" autocomplete="new-password"', html)
        self.assertIn('id="aiKey" type="password" autocomplete="new-password"', html)

    def test_approval_display_reveals_hidden_characters_and_never_cuts_silently(self):
        source = (WEB / "public" / "app.js").read_text(encoding="utf-8")
        self.assertIn("HIDDEN_CHARS", source)
        for needle in ("\\u2028-\\u202e", "\\u200b-\\u200f", "\\u2060-\\u206f", "ASCII dışı", "gösterilmedi"):
            self.assertIn(needle, source)
        # the confirm dialog and the card use the same reveal path; no 300-character cut of the action
        self.assertNotIn("return clip(text, 300);", source)
        self.assertIn("splitPreview(item.action)", source)

    def test_branding_files_are_linked_and_served(self):
        html = (WEB / "public" / "index.html").read_text(encoding="utf-8")
        self.assertIn('rel="icon" type="image/png" sizes="32x32" href="/favicon-32.png"', html)
        self.assertIn('src="/icon-192.png"', html)
        for name in ("favicon-32.png", "icon-192.png"):  # copies of assets/: keep them in step
            self.assertEqual((WEB / "public" / name).read_bytes(), (WEB.parent / "assets" / name).read_bytes())

    def test_notification_is_opt_in_and_carries_no_agent_text(self):
        source = (WEB / "public" / "app.js").read_text(encoding="utf-8")
        # the permission prompt only comes from a click, never at load
        self.assertEqual(source.count("requestPermission"), 1)
        self.assertIn('$("notifyBtn").addEventListener("click", enableNotifications)', source)
        start = source.index("function notifyNewApprovals")
        body = source[start:source.index("\n}\n", start)]
        self.assertIn("new window.Notification(", body)
        for untrusted in ("action", "requested_by", "risk_summary", ".summary"):
            self.assertNotIn(untrusted, body)

    def test_approval_form_does_not_invite_password_managers(self):
        html = (WEB / "public" / "index.html").read_text(encoding="utf-8")
        self.assertIn('id="approvalToken" type="password" autocomplete="new-password"', html)

    def test_token_is_persistent_only_when_remembered(self):
        source = (WEB / "public" / "app.js").read_text(encoding="utf-8")
        # no direct localStorage/sessionStorage use outside the token helpers
        self.assertEqual(source.count("window.localStorage"), 1)
        self.assertEqual(source.count("window.sessionStorage"), 1)
        self.assertNotIn("readStore", source)
        self.assertNotIn("writeStore", source)
        self.assertIn("persistent === remember", source)

    @unittest.skipUnless(shutil.which("node"), "node not installed")
    def test_javascript_parses(self):
        result = subprocess.run(["node", "--check", str(WEB / "public" / "app.js")],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
