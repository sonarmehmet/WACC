"""Local server for the WACC web panel (T-0005).

Serves web/public and forwards /api/* to the Communication Hub and /backend/* (read-only,
allow-listed) to the Backend, so the browser talks to a single origin (no CORS, no changes to
either service). Standard library only. Listens on 127.0.0.1 only. Tokens travel in the
X-WACC-Token header and are never logged or stored here.

    python web/serve.py                      # panel :8780, Hub :8765, Backend :8800
    python web/serve.py --port 8790 --hub http://127.0.0.1:8765 --backend http://127.0.0.1:8800
"""

import argparse
import hmac
import secrets
import json
import mimetypes
import os
import re
import threading
import time
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib import error as urlerror
from urllib import request as urlrequest
from urllib.parse import parse_qs, urlsplit

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
# AI chat (POST /ai/complete, text in / text out, counted against the daily budget) is forwarded for the
# control-room chat box. Submitting actions (POST /exec), the budget and memory are NOT forwarded. Account names are checked here with the Backend's own rule (lower case only).
_AI_NAME = r"[a-z0-9][a-z0-9_-]{1,30}"
BACKEND_POST_PATHS = re.compile(
    r"^(?:/exec/(?:approvals/[0-9]{1,9}/(?:approve|deny)|stop|resume)"
    r"|/ai/accounts|/ai/complete|/ai/discover"
    r"|/ai/providers/" + _AI_NAME + r"/(?:enabled|test))$")
# Hub: removing a user-managed agent. The Hub alone decides (user token only; built-ins are refused).
HUB_DELETE_PATHS = re.compile(r"^/api/agents/[a-z][a-z0-9_-]{1,19}$")
BACKEND_DELETE_PATHS = re.compile(r"^/ai/accounts/" + _AI_NAME + r"$")
MAX_BODY = 1_000_000
LOCAL_NAMES = {"127.0.0.1", "localhost", "[::1]"}
FORWARDED_HEADERS = ("X-WACC-Token", "Content-Type")
CSP = ("default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; "
       "img-src 'self' data:; base-uri 'none'; form-action 'none'; frame-ancestors 'none'")

# Never route the Hub call through an environment proxy: it is always a local address.
_OPENER = urlrequest.build_opener(urlrequest.ProxyHandler({}))


# Desktop window hand-off (used only by the launcher, see launcher/wacc_launcher.py). The launcher opens the
# panel in its own window with a one-time key in the address; the page trades that key for the tokens once
# (so no token ever sits on a command line or in a file the browser keeps), then pings so the launcher
# knows the window is still open. /_wacc/quit needs the user's approval token.
_DESKTOP = {"nonce": None, "tokens": None, "quit_token": "", "on_quit": None, "on_reopen": None,
            "sessions": set(), "last_ping": time.time()}
_DESKTOP_LOCK = threading.Lock()
_DIAG = {"fn": None}


def set_diag(fn) -> None:
    """fn() -> dict with the services' health and the tail of the log, shown by the Ayarlar "Tanı raporu" button."""
    _DIAG["fn"] = fn


def arm_desktop(nonce: str, tokens: dict, on_quit, on_reopen=None) -> None:
    """Called again for every new window: each window needs its own one-time key."""
    with _DESKTOP_LOCK:
        _DESKTOP.update(nonce=nonce, tokens=dict(tokens), quit_token=tokens.get("user", ""), on_quit=on_quit,
                        last_ping=time.time())
        if on_reopen is not None:
            _DESKTOP["on_reopen"] = on_reopen


def last_ping() -> float:
    return _DESKTOP["last_ping"]


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
            line = re.sub(r"(/_wacc/\w+)\?\S*", r"\1", fmt % args)  # the one-time key stays out of the log too
            print("[web] %s %s" % (self.address_string(), line))

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
            if urlsplit(self.path).path == "/_wacc/handoff":
                return self._handoff()
            if urlsplit(self.path).path == "/_wacc/diag":
                fn = _DIAG["fn"]
                return self._json(200, fn() if fn else {"note": "no diagnostics in this mode"})
            self._static()

        def do_POST(self):
            if not self._guard(write=True):
                return
            if self.path.startswith("/api/"):
                return self._proxy("POST")
            if self.path.startswith("/backend/"):
                return self._backend("POST")
            if self.path == "/_wacc/ping":
                _DESKTOP["last_ping"] = time.time()
                return self._json(200, {"ok": True})
            if self.path == "/_wacc/quit":
                return self._quit()
            if self.path == "/_wacc/reopen":
                # a second start of WACC asks the running one for a window instead of failing on busy ports;
                # it can only make a window appear (the tokens stay behind the one-time key)
                with _DESKTOP_LOCK:
                    on_reopen = _DESKTOP["on_reopen"]
                if not on_reopen:
                    return self._json(404, {"detail": "Not available"})
                threading.Thread(target=on_reopen, daemon=True).start()
                return self._json(200, {"ok": True})
            self._json(405, {"detail": "Method not allowed"})

        def do_PUT(self):
            self._json(405, {"detail": "Method not allowed"})

        do_PATCH = do_PUT

        def do_DELETE(self):
            if not self._guard(write=True):
                return
            if self.path.startswith("/backend/"):
                return self._backend("DELETE")
            if HUB_DELETE_PATHS.fullmatch(self.path):
                return self._proxy("DELETE")
            self._json(405, {"detail": "Method not allowed"})

        def _handoff(self):
            """Trade the launcher's one-time key for the tokens (the window then gets a session cookie), or, after a
            page reload, show that cookie instead. Same-origin only. The cookie is HttpOnly + SameSite=Strict and
            only valid while this app runs, so a reload does not lose the tokens and nothing is written to disk."""
            site = self.headers.get("Sec-Fetch-Site")
            key = (parse_qs(urlsplit(self.path).query).get("k") or [""])[0]
            cookie = SimpleCookie(self.headers.get("Cookie") or "")
            session = cookie["wacc_win"].value if "wacc_win" in cookie else ""
            extra = None
            with _DESKTOP_LOCK:
                nonce = _DESKTOP["nonce"]
                same_site = site in (None, "same-origin")
                tokens = None
                if same_site and key and nonce and hmac.compare_digest(key.encode(), nonce.encode()):
                    _DESKTOP["nonce"] = None  # single use
                    session = secrets.token_urlsafe(24)
                    _DESKTOP["sessions"].add(session)
                    tokens = _DESKTOP["tokens"]
                    extra = {"Set-Cookie": "wacc_win=%s; Path=/_wacc; HttpOnly; SameSite=Strict" % session}
                elif same_site and not key and session and session in _DESKTOP["sessions"]:
                    tokens = _DESKTOP["tokens"]
            if not tokens:
                return self._json(403, {"detail": {"code": "NO_HANDOFF", "message": "Hand-off key invalid or used"}})
            self._send(200, json.dumps({k: tokens.get(k, "") for k in ("hub", "backend", "user")}).encode("utf-8"),
                       extra=extra)

        def _quit(self):
            token = self.headers.get("X-WACC-Token", "")
            with _DESKTOP_LOCK:
                expected, on_quit = _DESKTOP["quit_token"], _DESKTOP["on_quit"]
            if not (expected and on_quit and hmac.compare_digest(token.encode(), expected.encode())):
                return self._json(403, {"detail": {"code": "FORBIDDEN", "message": "User token required"}})
            self._json(200, {"ok": True})
            threading.Thread(target=on_quit, daemon=True).start()

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
            if length < 0:
                self._json(400, {"detail": "Bad Content-Length"})
                return None
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
            self._forward("POST", backend_url + path, body, "BACKEND_UNREACHABLE", unreachable,
                          timeout=100 if path == "/ai/complete" else 10)  # a model may need a while to answer

        def _forward(self, method, url, body, unreachable_code, unreachable_message, timeout=10):
            req = urlrequest.Request(url, data=body, method=method)
            for name in FORWARDED_HEADERS:
                value = self.headers.get(name)
                if value:
                    req.add_header(name, value)
            try:
                with _OPENER.open(req, timeout=timeout) as resp:
                    self._send(resp.status, resp.read(), resp.headers.get("Content-Type", "application/json"))
            except urlerror.HTTPError as exc:  # upstream answered with an error: pass it through unchanged
                self._send(exc.code, exc.read(), exc.headers.get("Content-Type", "application/json"))
            except (urlerror.URLError, TimeoutError, OSError) as exc:
                reason = getattr(exc, "reason", exc)
                if isinstance(exc, TimeoutError) or isinstance(reason, TimeoutError) or "timed out" in str(reason):
                    # The Backend is up but the AI account did not answer in time: say that, not "unreachable".
                    self._json(504, {"detail": {"code": "BACKEND_SLOW", "message":
                                                "Yapay zekâ hesabı zamanında cevap vermedi (Backend çalışıyor). "
                                                "Ajanlar > Hesapları test et ile hangi hesabın takıldığına bak."}})
                else:
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
