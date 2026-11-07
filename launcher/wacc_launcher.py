"""WACC one-click launcher: Hub + Backend + web panel + desktop window in a single program.

Used by the Windows installer (WACC.exe). No tokens to copy: the window opens already connected.
  python launcher/wacc_launcher.py                       run from source
  WACC.exe --selftest result.json                        start everything headless, check it, exit (used by CI)
"""

import argparse
import json
import os
import secrets
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

FROZEN = bool(getattr(sys, "frozen", False))
BASE = Path(getattr(sys, "_MEIPASS", None) or Path(__file__).resolve().parents[1])
HUB_PORT, BACKEND_PORT, PANEL_PORT = 8765, 8800, 8780
HOST = "127.0.0.1"


def data_dir() -> Path:
    env = os.environ.get("WACC_DATA_DIR")
    if env:
        return Path(env)
    if FROZEN and os.name == "nt":
        return Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local") / "WACC" / "data"
    return BASE / "data"


def prepare_environment() -> Path:
    """Environment must be set before the Hub/Backend modules are imported (they read it at import time)."""
    data = data_dir()
    data.mkdir(parents=True, exist_ok=True)
    workspace = data.parent / "workspace"  # the folder agents may work in (the policy confines them to it)
    workspace.mkdir(parents=True, exist_ok=True)
    os.environ["WACC_DATA_DIR"] = str(data)
    os.environ.setdefault("WACC_EXEC_ROOTS", str(workspace))
    if not FROZEN:
        for sub in ("hub", "backend", "desktop", "web"):
            sys.path.insert(0, str(BASE / sub))
    if FROZEN and getattr(sys, "stdout", None) is None:  # windowed exe has no console: keep a log instead
        log = open(data / "wacc.log", "a", encoding="utf-8", buffering=1)
        sys.stdout = sys.stderr = log
    return data


def port_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind((HOST, port))
            return True
        except OSError:
            return False


def wait_http(url: str, timeout: float = 40.0) -> bool:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        try:
            with urllib.request.urlopen(url, timeout=2) as r:
                if r.status == 200:
                    return True
        except Exception:
            time.sleep(0.3)
    return False


class Services:
    def __init__(self):
        self.servers = []
        self.panel = None
        self.worker = None
        self.tokens = {}

    def _serve(self, app, port):
        import uvicorn
        server = uvicorn.Server(uvicorn.Config(app, host=HOST, port=port, log_config=None, log_level="warning",
                                               access_log=False))
        threading.Thread(target=server.run, daemon=True, name=f"uvicorn-{port}").start()
        self.servers.append(server)

    def start(self):
        busy = [p for p in (HUB_PORT, BACKEND_PORT, PANEL_PORT) if not port_free(p)]
        if busy:
            raise RuntimeError("Port(lar) kullanımda: %s. WACC zaten açık olabilir; açıksa onu kullan, "
                               "değilse eski WACC pencerelerini kapat." % ", ".join(map(str, busy)))
        # Hub
        from wacc_hub.api import create_app as hub_app
        from wacc_hub.auth import load_or_create_tokens
        hub = hub_app()
        hub_tokens = load_or_create_tokens()
        # Backend
        from wacc_backend.app import create_app as backend_app
        from wacc_backend.config import load_env_file, load_settings
        from wacc_backend.security import get_or_create_token, get_or_create_user_token
        settings = load_settings()
        load_env_file(settings.data_dir / "llm.env")  # optional model settings
        settings = load_settings()
        user_token = get_or_create_user_token(settings)  # approval token: lives in memory only
        backend = backend_app(settings, user_token=user_token)
        from wacc_backend.worker import Worker, register_builtin_handlers
        register_builtin_handlers(backend.state.engine, backend.state.orchestrator, backend.state.execution,
                                  settings.data_dir)
        self.worker = Worker(backend.state.engine)
        self.worker.start()
        self._serve(hub, HUB_PORT)
        self._serve(backend, BACKEND_PORT)
        # Web panel (stdlib server)
        import serve
        serve.PUBLIC = (BASE / "web" / "public").resolve() if FROZEN else serve.PUBLIC
        self.panel = serve.create_server(PANEL_PORT, "http://%s:%d" % (HOST, HUB_PORT), "http://%s:%d" % (HOST, BACKEND_PORT))
        threading.Thread(target=self.panel.serve_forever, daemon=True, name="panel").start()
        self.tokens = {"hub": hub_tokens["user"], "backend": get_or_create_token(settings), "user": user_token}
        for name, url in (("Hub", "http://%s:%d/health" % (HOST, HUB_PORT)), ("Backend", "http://%s:%d/health" % (HOST, BACKEND_PORT))):
            if not wait_http(url):
                raise RuntimeError(f"{name} açılmadı (bkz. wacc.log)")

    def stop(self):
        for s in self.servers:
            s.should_exit = True
        if self.panel:
            try:
                self.panel.shutdown()
            except Exception:
                pass
        if self.worker:
            try:
                self.worker.stop()
            except Exception:
                pass


def call(url, token="", method="GET", body=None):
    req = urllib.request.Request(url, data=json.dumps(body).encode() if body is not None else None, method=method,
                                 headers={"X-WACC-Token": token, "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as r:
        raw = r.read()
        return r.status, (json.loads(raw) if raw else None)


def selftest(out_path: str) -> int:
    result = {"ok": False, "checks": {}}
    services = Services()
    try:
        services.start()
        t = services.tokens
        hub, be = "http://%s:%d" % (HOST, HUB_PORT), "http://%s:%d" % (HOST, BACKEND_PORT)
        result["checks"]["hub_whoami_user"] = call(hub + "/whoami", t["hub"])[1] == {"agent": "user"}
        result["checks"]["hub_rejects_bad_token"] = False
        try:
            call(hub + "/whoami", "wrong")
        except urllib.error.HTTPError as e:
            result["checks"]["hub_rejects_bad_token"] = e.code == 401
        result["checks"]["backend_health"] = call(be + "/health")[0] == 200
        result["checks"]["backend_user_exec_status"] = call(be + "/exec/status", t["user"])[0] == 200
        result["checks"]["backend_shared_token_cannot_approve"] = False
        try:
            call(be + "/exec/approvals/1/approve", t["backend"], "POST", {})
        except urllib.error.HTTPError as e:
            result["checks"]["backend_shared_token_cannot_approve"] = e.code == 403
        status, page = 0, b""
        with urllib.request.urlopen("http://%s:%d/" % (HOST, PANEL_PORT), timeout=10) as r:
            status, page = r.status, r.read()
        result["checks"]["panel_serves_ui"] = status == 200 and b"WACC" in page
        status, agents = call(hub + "/agents", t["hub"])
        result["checks"]["hub_has_builtin_agents"] = status == 200 and len(agents) >= 4
        result["checks"]["panel_proxies_hub"] = call("http://%s:%d/api/whoami" % (HOST, PANEL_PORT), t["hub"])[1] == {"agent": "user"}
        result["checks"]["data_in_expected_dir"] = (data_dir() / "hub.db").exists() and (data_dir() / "tokens.json").exists()
        import serve
        quit_called = []
        serve.arm_desktop("selftest-key-selftest-key", t, lambda: quit_called.append(1))
        panel = "http://%s:%d" % (HOST, PANEL_PORT)
        got = call(panel + "/_wacc/handoff?k=selftest-key-selftest-key")[1]
        result["checks"]["window_handoff_gives_tokens"] = got == {"hub": t["hub"], "backend": t["backend"], "user": t["user"]}
        result["checks"]["window_handoff_is_single_use"] = False
        try:
            call(panel + "/_wacc/handoff?k=selftest-key-selftest-key")
        except urllib.error.HTTPError as e:
            result["checks"]["window_handoff_is_single_use"] = e.code == 403
        result["checks"]["window_quit_needs_user_token"] = False
        try:
            call(panel + "/_wacc/quit", t["hub"], "POST", {})
        except urllib.error.HTTPError as e:
            result["checks"]["window_quit_needs_user_token"] = e.code == 403 and not quit_called
        result["checks"]["window_ping_ok"] = call(panel + "/_wacc/ping", "", "POST", {})[0] == 200
        result["ok"] = all(result["checks"].values())
    except Exception as exc:  # report, never hang
        result["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        services.stop()
        Path(out_path).write_text(json.dumps(result, indent=2), encoding="utf-8")
    return 0 if result["ok"] else 1


def find_browser():
    """Edge (on every Windows 10/11) or Chrome: a Chromium browser that can show the panel as its own app window."""
    candidates = []
    for env in ("ProgramFiles(x86)", "ProgramFiles", "LOCALAPPDATA"):
        base = os.environ.get(env)
        if base:
            candidates += [Path(base) / "Microsoft" / "Edge" / "Application" / "msedge.exe",
                           Path(base) / "Google" / "Chrome" / "Application" / "chrome.exe"]
    for path in candidates:
        if path.is_file():
            return str(path)
    for name in ("microsoft-edge", "google-chrome", "chromium", "chromium-browser"):
        found = shutil.which(name)
        if found:
            return found
    return None


def open_window(services, data, quit_event):
    """Open the control-room panel in its own window, already connected. Returns the browser process,
    or None when no suitable browser exists (the caller then falls back to the Tk window)."""
    browser = find_browser()
    if not browser or os.environ.get("WACC_UI") == "tk":
        return None
    import serve
    key = secrets.token_urlsafe(24)  # one-time: the page trades it for the tokens, then it is dead
    serve.arm_desktop(key, services.tokens, quit_event.set)
    profile = data.parent / "window-profile"
    profile.mkdir(parents=True, exist_ok=True)
    args = [browser, "--app=http://%s:%d/?k=%s" % (HOST, PANEL_PORT, key), "--user-data-dir=%s" % profile,
            "--window-size=1360,860", "--no-first-run", "--no-default-browser-check", "--disable-features=Translate"]
    try:
        return subprocess.Popen(args)
    except OSError as exc:
        print("window start failed: %s" % exc, file=sys.stderr)
        return None


def wait_for_window(proc, quit_event):
    """Block until the window is closed (or the app's own close button was used)."""
    import serve
    started = time.monotonic()
    while not quit_event.is_set():
        time.sleep(0.5)
        if proc.poll() is not None:
            if time.monotonic() - started > 15:
                break  # the person closed the window
            # the browser handed the window to another process and exited: follow the page's heartbeat instead
            if time.time() - serve.last_ping() > 150:
                break
    if proc.poll() is None:
        proc.terminate()


def run_gui() -> int:
    services = Services()
    try:
        services.start()
        quit_event = threading.Event()
        proc = open_window(services, data_dir(), quit_event)
        if proc is not None:
            wait_for_window(proc, quit_event)
            return 0
        from wacc_desktop.ui import App  # no Chromium browser found: the plain Tk window still works
        App(preset=services.tokens).mainloop()
        return 0
    except Exception as exc:
        message = f"WACC başlatılamadı:\n\n{exc}\n\nAyrıntı: {data_dir() / 'wacc.log'}"
        try:
            import tkinter
            from tkinter import messagebox
            root = tkinter.Tk()
            root.withdraw()
            messagebox.showerror("WACC", message)
        except Exception:
            print(message, file=sys.stderr)
        return 1
    finally:
        services.stop()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="WACC")
    parser.add_argument("--selftest", metavar="RESULT_JSON", help="headless self check (CI), writes a JSON result")
    args = parser.parse_args(argv)
    prepare_environment()
    return selftest(args.selftest) if args.selftest else run_gui()


if __name__ == "__main__":
    sys.exit(main())
