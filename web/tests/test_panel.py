"""End-to-end checks for the web panel server (T-0005).

Starts a real Communication Hub on a temp database and the panel server in front of it, then
drives both over HTTP the way the browser does. Needs the hub dependencies (fastapi, uvicorn).

    python -m unittest discover -s web/tests -v
"""

import http.client
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

import serve  # noqa: E402

TOKENS = {a: "tok-" + a for a in ("claude1", "claude2", "claude3", "gemini", "user")}


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


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


class FrontendSourceTests(unittest.TestCase):
    def test_no_html_injection_sinks(self):
        source = (WEB / "public" / "app.js").read_text(encoding="utf-8")
        for sink in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval(", "new Function"):
            self.assertNotIn(sink, source, sink)

    def test_no_secrets_in_frontend(self):
        for f in (WEB / "public").iterdir():
            self.assertNotIn("tokens.json", f.read_text(encoding="utf-8"), f.name)

    def test_remember_token_is_off_by_default(self):
        import re
        html = (WEB / "public" / "index.html").read_text(encoding="utf-8")
        tag = re.search(r'<input[^>]*id="remember"[^>]*>', html)
        self.assertIsNotNone(tag, "remember checkbox missing")
        self.assertIn('type="checkbox"', tag.group(0))
        self.assertNotIn("checked", tag.group(0))  # off unless the user turns it on

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
