import json
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from wacc_desktop.client import Api, ApiError, WaccClient, describe_approval  # noqa: E402

SEEN = []


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, payload):
        raw = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _handle(self):
        n = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(n)) if n else None
        SEEN.append((self.command, self.path, self.headers.get("X-WACC-Token"), body))
        if self.path == "/boom":
            return self._send(403, {"detail": {"code": "FORBIDDEN", "message": "user token required"}})
        if self.path.startswith("/exec/approvals?"):
            return self._send(200, [{"id": 7, "action_class": "INSTALL", "requested_by": "claude2",
                                     "action": {"type": "run", "argv": ["pip", "install", "x"]}}])
        self._send(200, {"ok": True})

    do_GET = do_POST = _handle


class ClientTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = HTTPServer(("127.0.0.1", 0), Handler)
        cls.url = f"http://127.0.0.1:{cls.server.server_port}"
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def setUp(self):
        SEEN.clear()

    def test_token_header_and_json_body(self):
        Api(self.url, "tok").post("/x", {"a": 1})
        self.assertEqual(SEEN[0], ("POST", "/x", "tok", {"a": 1}))

    def test_error_message_is_extracted(self):
        with self.assertRaises(ApiError) as ctx:
            Api(self.url, "tok").get("/boom")
        self.assertEqual((ctx.exception.status, ctx.exception.message), (403, "user token required"))

    def test_unreachable_server_is_an_api_error_without_token(self):
        with self.assertRaises(ApiError) as ctx:
            Api("http://127.0.0.1:1", "secret-token", timeout=1).get("/x")
        self.assertNotIn("secret-token", ctx.exception.message)

    def test_approve_uses_only_the_user_token(self):
        c = WaccClient(backend_token="agent-tok", user_token="user-tok", backend_url=self.url)
        c.approve(7)
        self.assertEqual(SEEN[-1][:3], ("POST", "/exec/approvals/7/approve", "user-tok"))
        c.pending_approvals()
        self.assertEqual(SEEN[-1][2], "agent-tok")

    def test_approve_and_resume_refuse_without_user_token(self):
        c = WaccClient(backend_token="agent-tok", backend_url=self.url)
        for fn in (lambda: c.approve(1), lambda: c.deny(1), c.exec_resume):
            with self.assertRaises(ApiError):
                fn()
        self.assertEqual(SEEN, [])

    def test_describe_approval_shows_the_command(self):
        text = describe_approval(WaccClient(backend_url=self.url, backend_token="t").pending_approvals()[0])
        self.assertIn("pip install x", text)
        self.assertIn("claude2", text)
        self.assertIn("INSTALL", text)


if __name__ == "__main__":
    unittest.main()
