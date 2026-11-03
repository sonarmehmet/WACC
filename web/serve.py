"""Local server for the WACC web panel (T-0005).

Serves web/public and forwards /api/* to the Communication Hub and /backend/* (read-only,
allow-listed) to the Backend, so the browser talks to a single origin (no CORS, no changes to
either service). Standard library only. Listens on 127.0.0.1 only. Tokens travel in the
X-WACC-Token header and are never logged or stored here.

    python web/serve.py                      # panel :8780, Hub :8765, Backend :8800
    python web/serve.py --port 8790 --hub http://127.0.0.1:8765 --backend http://127.0.0.1:8800
"""

import argparse
import json
import mimetypes
import os
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib import error as urlerror
from urllib import request as urlrequest
from urllib.parse import urlsplit

PUBLIC = (Path(__file__).resolve().parent / "public").resolve()
DEFAULT_HUB = os.environ.get("WACC_HUB_URL", "http://127.0.0.1:8765")
DEFAULT_BACKEND = os.environ.get("WACC_BACKEND_URL", "http://127.0.0.1:8800")
DEFAULT_PORT = int(os.environ.get("WACC_WEB_PORT", "8780"))
# Backend paths the panel may read (exact match, GET only). Memory, AI calls and every other
# endpoint are deliberately not exposed here.
BACKEND_GET_PATHS = frozenset({
    "/health", "/projects", "/jobs", "/jobs/summary", "/agents", "/ai/providers", "/ai/usage",
    "/exec/approvals", "/exec/status", "/exec/audit",
})
# The only backend writes the panel may forward. Who may do them is still decided by the
# Backend from the token: approve/deny/resume and every AI-account change need the user token.
#  * decide an approval, stop/resume execution (POST)
#  * AI accounts: add (POST), switch on/off and test one (POST), remove (DELETE)
# Submitting actions (POST /exec), AI calls (/ai/complete), the budget and memory are NOT
# forwarded. Account names are checked here with the Backend's own rule (lower case only).
_AI_NAME = r"[a-z0-9][a-z0-9_-]{1,30}"
BACKEND_POST_PATHS = re.compile(
    r"^(?:/exec/(?:approvals/[0-9]{1,9}/(?:approve|deny)|stop|resume)"
    r"|/ai/accounts"
    r"|/ai/providers/" + _AI_NAME + r"/(?:enabled|test))$")
BACKEND_DELETE_PATHS = re.compile(r"^/ai/accounts/" + _AI_NAME + r"$")
MAX_BODY = 1_000_000
LOCAL_NAMES = {"127.0.0.1", "localhost", "[::1]"}
FORWARDED_HEADERS = ("X-WACC-Token", "Content-Type")
CSP = ("default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; "
       "img-src 'self' data:; base-uri 'none'; form-action 'none'; frame-ancestors 'none'")

# Never route the Hub call through an environment proxy: it is always a local address.
_OPENER = urlrequest.build_opener(urlrequest.ProxyHandler({}))


def host_is_local(host_header: str) -> bool:
    """Reject foreign Host headers (DNS-rebinding guard)."""
    host = (host_header or "").strip()
    if host.startswith("["):
        name = host.split("]")[0] + "]"
    else:
        name = host.split(":")[0]
    return name.lower() in LOCAL_NAMES


def make_handler(hub_url: str, backend_url: str = DEFAULT_BACKEND):
    hub_url = hub_url.rstrip("/")
    backend_url = backend_url.rstrip("/")

    class Handler(BaseHTTPRequestHandler):
        server_version = "WACCPanel/0.1"

        # ------------------------------------------------------------ helpers
        def log_message(self, fmt, *args):  # request line only; headers (token) are never printed
            print("[web] %s %s" % (self.address_string(), fmt % args))

        def _send(self, status, body: bytes, content_type="application/json", extra=None):
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", CSP)
            self.send_header("Referrer-Policy", "no-referrer")
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)

        def _json(self, status, payload):
            self._send(status, json.dumps(payload).encode("utf-8"))

        def _guard(self, write: bool) -> bool:
            if not host_is_local(self.headers.get("Host", "")):
                self._json(403, {"detail": {"code": "BAD_HOST", "message": "Only local access is allowed"}})
                return False
            origin = self.headers.get("Origin")
            if write and origin and urlsplit(origin).netloc != self.headers.get("Host", ""):
                self._json(403, {"detail": {"code": "BAD_ORIGIN", "message": "Cross-origin request refused"}})
                return False
            return True

        # ------------------------------------------------------------- routes
        def do_GET(self):
            if not self._guard(write=False):
                return
            if self.path == "/api" or self.path.startswith("/api/"):
                return self._proxy("GET")
            if self.path == "/backend" or self.path.startswith("/backend/"):
                return self._backend("GET")
            self._static()

        def do_POST(self):
            if not self._guard(write=True):
                return
            if self.path.startswith("/api/"):
                return self._proxy("POST")
            if self.path.startswith("/backend/"):
                return self._backend("POST")
            self._json(405, {"detail": "Method not allowed"})

        def do_PUT(self):
            self._json(405, {"detail": "Method not allowed"})

        do_PATCH = do_PUT

        def do_DELETE(self):
            if not self._guard(write=True):
                return
            if self.path.startswith("/backend/"):
                return self._backend("DELETE")
            self._json(405, {"detail": "Method not allowed"})

        def _static(self):
            rel = urlsplit(self.path).path.lstrip("/") or "index.html"
            target = (PUBLIC / rel).resolve()
            if target != PUBLIC and PUBLIC not in target.parents:
                return self._json(404, {"detail": "Not found"})
            if target.is_dir():
                target = target / "index.html"
            if not target.is_file():
                return self._json(404, {"detail": "Not found"})
            ctype = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
            if ctype.startswith("text/") or ctype in ("application/javascript", "application/json"):
                ctype += "; charset=utf-8"
            self._send(200, target.read_bytes(), ctype)

        def _proxy(self, method):
            """Hub: /api/<path> -> <hub>/<path>. GET and POST."""
            path = self.path[len("/api"):] or "/"
            body = None
            if method == "POST":
                body = self._read_body()
                if body is None:
                    return
            self._forward(method, hub_url + path, body, "HUB_UNREACHABLE",
                          "Hub'a ulasilamiyor (%s). Hub calisiyor mu?" % hub_url)

        def _read_body(self):
            """Request body, or None after answering 413 when it is too large."""
            try:
                length = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                length = 0
            if length > MAX_BODY:
                self._json(413, {"detail": "Request too large"})
                return None
            return self.rfile.read(length) if length else b""

        def _backend(self, method):
            """Backend: /backend/<path> -> <backend>/<path>. Allow-listed: a few GET paths, the
            approval/stop POSTs and the AI-account writes only (no AI calls, no budget, no memory,
            no job or project writes). The Backend tokens are separate secrets; the Backend
            alone decides who may do what."""
            parts = urlsplit(self.path)
            path = parts.path[len("/backend"):] or "/"
            unreachable = "Backend'e ulasilamiyor (%s). Backend calisiyor mu?" % backend_url
            if method == "GET":
                if path not in BACKEND_GET_PATHS:
                    return self._json(404, {"detail": {"code": "NOT_EXPOSED",
                                                       "message": "Bu backend yolu panelden acik degil"}})
                url = backend_url + path + ("?" + parts.query if parts.query else "")
                return self._forward("GET", url, None, "BACKEND_UNREACHABLE", unreachable)
            if method == "DELETE":
                if not BACKEND_DELETE_PATHS.fullmatch(path):
                    return self._json(405, {"detail": "Method not allowed"})
                return self._forward("DELETE", backend_url + path, None, "BACKEND_UNREACHABLE", unreachable)
            if not BACKEND_POST_PATHS.fullmatch(path):
                return self._json(405, {"detail": "Method not allowed"})
            body = self._read_body()
            if body is None:
                return
            self._forward("POST", backend_url + path, body, "BACKEND_UNREACHABLE", unreachable)

        def _forward(self, method, url, body, unreachable_code, unreachable_message):
            req = urlrequest.Request(url, data=body, method=method)
            for name in FORWARDED_HEADERS:
                value = self.headers.get(name)
                if value:
                    req.add_header(name, value)
            try:
                with _OPENER.open(req, timeout=10) as resp:
                    self._send(resp.status, resp.read(), resp.headers.get("Content-Type", "application/json"))
            except urlerror.HTTPError as exc:  # upstream answered with an error: pass it through unchanged
                self._send(exc.code, exc.read(), exc.headers.get("Content-Type", "application/json"))
            except (urlerror.URLError, TimeoutError, OSError):
                self._json(502, {"detail": {"code": unreachable_code, "message": unreachable_message}})

    return Handler


def create_server(port: int = DEFAULT_PORT, hub_url: str = DEFAULT_HUB,
                  backend_url: str = DEFAULT_BACKEND) -> ThreadingHTTPServer:
    return ThreadingHTTPServer(("127.0.0.1", port), make_handler(hub_url, backend_url))


def main():
    parser = argparse.ArgumentParser(description="WACC web panel (local only)")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--hub", default=DEFAULT_HUB, help="Hub base URL (default %(default)s)")
    parser.add_argument("--backend", default=DEFAULT_BACKEND, help="Backend base URL (default %(default)s)")
    args = parser.parse_args()
    server = create_server(args.port, args.hub, args.backend)
    print("[web] Panel: http://127.0.0.1:%d  (Hub: %s, Backend: %s)" % (args.port, args.hub, args.backend))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
