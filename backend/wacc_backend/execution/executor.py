"""Executors. RealExecutor touches the machine; FakeExecutor records calls for tests.

Hard rules for RealExecutor: no shell, argument lists only, hard timeout, output cap, a scrubbed
environment (no API keys), kill the whole process tree on timeout or emergency stop, and
delete_path never erases anything: it moves the target into <root>/_to_delete/.
"""

import os
import shutil
import signal
import subprocess
import sys
import threading
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, List, Optional

MAX_OUTPUT = 1_000_000
DEFAULT_TIMEOUT = 120
MAX_TIMEOUT = 1800
KILL_GRACE = 2.0
SAFE_ENV_KEYS = ("PATH", "PATHEXT", "SYSTEMROOT", "WINDIR", "COMSPEC", "TEMP", "TMP", "HOME", "USERPROFILE",
                 "APPDATA", "LOCALAPPDATA", "PROGRAMFILES", "PROGRAMFILES(X86)", "PROGRAMDATA", "JAVA_HOME",
                 "ANDROID_HOME", "ANDROID_SDK_ROOT", "FLUTTER_ROOT", "PUB_CACHE", "LANG", "LC_ALL", "PYTHONUTF8")


class ExecutionKilled(Exception):
    """The emergency stop (or a timeout) ended the action."""


def safe_env(source: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    src = os.environ if source is None else source
    return {k: v for k, v in src.items() if k.upper() in SAFE_ENV_KEYS}


def kill_tree(proc: subprocess.Popen) -> None:
    if proc.poll() is not None:
        return
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True, timeout=10)
        else:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


class Executor:
    def run(self, action: dict, should_stop: Callable[[], bool]) -> dict:
        raise NotImplementedError


class RealExecutor(Executor):
    def __init__(self, roots: List[Path], timeout: int = DEFAULT_TIMEOUT):
        self.roots = [Path(r).resolve() for r in roots]
        self.timeout = min(int(timeout), MAX_TIMEOUT)

    def run(self, action, should_stop):
        kind = action["type"]
        return getattr(self, "_" + kind)(action, should_stop)

    # ----------------------------------------------------------------- files
    def _read_file(self, action, should_stop):
        data = Path(action["path"]).read_bytes()[:MAX_OUTPUT]
        return {"content": data.decode("utf-8", "replace")}

    def _list_dir(self, action, should_stop):
        entries = sorted(p.name + ("/" if p.is_dir() else "") for p in Path(action["path"]).iterdir())
        return {"entries": entries[:1000]}

    def _write_file(self, action, should_stop):
        path = Path(action["path"])
        path.parent.mkdir(parents=True, exist_ok=True)
        content = action["content"]
        tmp = path.with_name(path.name + ".wacc-tmp")
        tmp.write_text(content, encoding="utf-8", newline="")
        os.replace(tmp, path)  # atomic: a crash never leaves a half-written file
        return {"bytes": len(content.encode("utf-8"))}

    def _delete_path(self, action, should_stop):
        target = Path(action["path"])
        if not target.exists():
            raise FileNotFoundError("Nothing to delete")
        root = next(r for r in self.roots if target == r or r in target.parents)
        if target == root:
            raise PermissionError("The project root cannot be deleted")
        trash = root / "_to_delete"
        trash.mkdir(exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        dest = trash / f"{stamp}_{target.name}"
        shutil.move(str(target), str(dest))
        return {"moved_to": str(dest.relative_to(root).as_posix())}

    # --------------------------------------------------------------- network
    def _http_get(self, action, should_stop):
        req = urllib.request.Request(action["url"], headers={"User-Agent": "WACC-exec/0.1"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = resp.read(MAX_OUTPUT)
            return {"status": resp.status, "body": body.decode("utf-8", "replace")}

    # ------------------------------------------------------------- processes
    def _run(self, action, should_stop):
        kwargs = {}
        if os.name == "nt":
            kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            kwargs["start_new_session"] = True
        proc = subprocess.Popen(action["argv"], cwd=action["cwd"], env=safe_env(), shell=False,
                                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, **kwargs)
        chunks: List[bytes] = []
        size = [0]

        def pump():
            for block in iter(lambda: proc.stdout.read(4096), b""):
                if size[0] < MAX_OUTPUT:
                    chunks.append(block)
                    size[0] += len(block)

        reader = threading.Thread(target=pump, daemon=True)
        reader.start()
        deadline = time.monotonic() + self.timeout
        reason = None
        while proc.poll() is None:
            if should_stop():
                reason = "emergency stop"
            elif time.monotonic() > deadline:
                reason = "timeout"
            if reason:
                kill_tree(proc)
                proc.wait(timeout=KILL_GRACE + 8)
                break
            time.sleep(0.05)
        reader.join(timeout=2)
        output = b"".join(chunks).decode("utf-8", "replace")
        if reason:
            raise ExecutionKilled(f"Process ended by {reason}")
        return {"exit_code": proc.returncode, "output": output, "truncated": size[0] >= MAX_OUTPUT}


class FakeExecutor(Executor):
    """Records actions instead of running them; can simulate slow processes for emergency-stop tests."""

    def __init__(self, results: Optional[dict] = None, fail_with: Optional[Exception] = None, block_seconds: float = 0):
        self.calls: List[dict] = []
        self.results = results or {}
        self.fail_with = fail_with
        self.block_seconds = block_seconds

    def run(self, action, should_stop):
        self.calls.append(action)
        if self.fail_with:
            raise self.fail_with
        end = time.monotonic() + self.block_seconds
        while time.monotonic() < end:
            if should_stop():
                raise ExecutionKilled("Process ended by emergency stop")
            time.sleep(0.01)
        return self.results.get(action["type"], {"ok": True})
