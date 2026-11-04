"""Hardening found by attacking the running system (docs/SECURITY_TEST_LOG.md)."""
import http.server
import sys
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import tempfile  # noqa: E402

from wacc_backend.execution.executor import RealExecutor  # noqa: E402
from wacc_backend.orchestrator import LOCAL, OpenAICompatProvider, ProviderError  # noqa: E402


class _Spy(http.server.BaseHTTPRequestHandler):
    seen = []
    redirect_to = None

    def _go(self):
        type(self).seen.append((self.path, self.headers.get("Authorization")))
        if type(self).redirect_to and self.server.server_port == type(self).first_port:
            self.send_response(302)
            self.send_header("Location", type(self).redirect_to)
            self.end_headers()
            return
        body = b'{"choices":[{"message":{"content":"x"}}]}'
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    do_GET = do_POST = _go

    def log_message(self, *a):
        pass


class RedirectTests(unittest.TestCase):
    def setUp(self):
        _Spy.seen = []
        self.first = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Spy)
        self.second = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Spy)
        _Spy.first_port = self.first.server_port
        _Spy.redirect_to = "http://127.0.0.1:%d/stolen" % self.second.server_port
        for srv in (self.first, self.second):
            threading.Thread(target=srv.serve_forever, daemon=True).start()

    def tearDown(self):
        for srv in (self.first, self.second):
            srv.shutdown()
            srv.server_close()
        _Spy.redirect_to = None

    def test_ai_key_is_not_forwarded_by_a_redirect(self):
        provider = OpenAICompatProvider("p", LOCAL, "http://127.0.0.1:%d/v1" % self.first.server_port, "m",
                                        api_key="sk-secret-key-123456")
        with self.assertRaises(ProviderError):
            provider.complete("hi", None, 5)
        self.assertEqual([p for p, _ in _Spy.seen if p == "/stolen"], [])  # the second server was never asked

    def test_http_get_does_not_follow_a_redirect_to_an_unsafe_address(self):
        ex = RealExecutor([Path(tempfile.mkdtemp())])
        with self.assertRaises(Exception) as cm:
            ex.run({"type": "http_get", "url": "http://127.0.0.1:%d/start" % self.first.server_port}, lambda: False)
        self.assertIn("Redirect", str(cm.exception))
        self.assertEqual([p for p, _ in _Spy.seen if p == "/stolen"], [])


if __name__ == "__main__":
    unittest.main()
