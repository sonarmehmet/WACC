"""HTTP client for the Hub (8765) and the backend (8800). No third-party packages.

Tokens are kept in memory only. The approval ("user") token is never written to disk.
Everything returned by the servers is untrusted text; the UI only shows it in labels/lists.
"""

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Optional

HUB_URL = "http://127.0.0.1:8765"
BACKEND_URL = "http://127.0.0.1:8800"


class ApiError(Exception):
    def __init__(self, message: str, status: Optional[int] = None):
        super().__init__(message)
        self.message = message
        self.status = status


def _error_text(raw: bytes) -> str:
    try:
        data = json.loads(raw.decode("utf-8", "replace"))
    except ValueError:
        return raw.decode("utf-8", "replace")[:200] or "error"
    detail = data.get("detail", data) if isinstance(data, dict) else data
    if isinstance(detail, dict):
        return str(detail.get("message") or detail.get("code") or detail)[:300]
    return str(detail)[:300]


class Api:
    def __init__(self, base_url: str, token: str = "", timeout: float = 8.0):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout = timeout

    def request(self, method: str, path: str, body: Any = None) -> Any:
        data = None if body is None else json.dumps(body).encode("utf-8")
        req = urllib.request.Request(self.base_url + path, data=data, method=method)
        req.add_header("Accept", "application/json")
        if data is not None:
            req.add_header("Content-Type", "application/json")
        if self.token:
            req.add_header("X-WACC-Token", self.token)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read()
        except urllib.error.HTTPError as exc:
            raise ApiError(_error_text(exc.read()), exc.code) from None
        except (urllib.error.URLError, OSError) as exc:
            raise ApiError(f"Cannot reach {self.base_url}: {getattr(exc, 'reason', exc)}") from None
        return json.loads(raw.decode("utf-8")) if raw else None

    def get(self, path: str) -> Any:
        return self.request("GET", path)

    def post(self, path: str, body: Any = None) -> Any:
        return self.request("POST", path, {} if body is None else body)


class WaccClient:
    """Hub token acts as the agent that owns it; backend_token is the backend's agent token and
    user_token (typed by the human each session) is the only one that can approve or resume."""

    def __init__(self, hub_token: str = "", backend_token: str = "", user_token: str = "",
                 hub_url: str = HUB_URL, backend_url: str = BACKEND_URL):
        self.hub = Api(hub_url, hub_token)
        self.backend = Api(backend_url, backend_token)
        self.user_backend = Api(backend_url, user_token)  # approve / deny / resume only

    # Hub
    def agents(self):
        return self.hub.get("/agents")

    # Agent accounts: the Hub only lets the user token add, remove or switch them
    def register_agent(self, name: str, kind: str, role: str = "", provider: str = ""):
        body = {"name": name, "kind": kind, "role": role}
        if provider:
            body["provider"] = provider
        return self.hub.post("/agents", body)

    def set_agent_enabled(self, name: str, enabled: bool):
        return self.hub.post("/agents/" + urllib.parse.quote(name, safe="") + "/enabled", {"enabled": bool(enabled)})

    def remove_agent(self, name: str):
        return self.hub.request("DELETE", "/agents/" + urllib.parse.quote(name, safe=""))

    def tasks(self):
        return self.hub.get("/tasks")

    def feed(self, limit: int = 100):
        return self.hub.get(f"/feed?limit={int(limit)}")

    def hub_stop(self, reason: str = "Stopped from desktop panel"):
        return self.hub.post("/system/stop", {"reason": reason})

    # Backend
    def pending_approvals(self):
        return self.backend.get("/exec/approvals?status=PENDING")

    def approve(self, approval_id: int):
        if not self.user_backend.token:
            raise ApiError("Enter the approval token first")
        return self.user_backend.post(f"/exec/approvals/{int(approval_id)}/approve")

    def deny(self, approval_id: int):
        if not self.user_backend.token:
            raise ApiError("Enter the approval token first")
        return self.user_backend.post(f"/exec/approvals/{int(approval_id)}/deny")

    def exec_status(self):
        return self.backend.get("/exec/status")

    def exec_stop(self, reason: str = "Stopped from desktop panel"):
        return self.backend.post("/exec/stop", {"reason": reason})

    def exec_resume(self):
        if not self.user_backend.token:
            raise ApiError("Enter the approval token first")
        return self.user_backend.post("/exec/resume")

    # AI accounts (any OpenAI-compatible endpoint). Changing them needs the approval (user) token.
    def providers(self):
        return self.backend.get("/ai/providers")

    def add_account(self, spec: dict):
        self._need_user()
        return self.user_backend.post("/ai/accounts", spec)

    def remove_account(self, name: str):
        self._need_user()
        return self.user_backend.request("DELETE", "/ai/accounts/" + urllib.parse.quote(name, safe=""))

    def set_provider_enabled(self, name: str, enabled: bool):
        self._need_user()
        return self.user_backend.post("/ai/providers/" + urllib.parse.quote(name, safe="") + "/enabled", {"enabled": bool(enabled)})

    def test_provider(self, name: str):
        self._need_user()
        return self.user_backend.post("/ai/providers/" + urllib.parse.quote(name, safe="") + "/test")

    def _need_user(self):
        if not self.user_backend.token:
            raise ApiError("Enter the approval token first")

    def audit(self, limit: int = 100):
        return self.backend.get(f"/exec/audit?limit={int(limit)}")


KIND_LABELS = {"builtin": "hazır", "claude": "Claude", "gemini": "Gemini", "chatgpt": "ChatGPT", "other": "diğer"}


def describe_agent(a: dict) -> str:
    state = "açık" if a.get("enabled", 1) else "KAPALI"
    online = "çevrimiçi" if a.get("online") else "çevrimdışı"
    kind = KIND_LABELS.get(a.get("kind") or "builtin", str(a.get("kind")))
    link = f"  → {a['provider']}" if a.get("provider") else ""
    return f"{a.get('agent_id') or a.get('name')}  [{kind}, {state}, {online}]  {a.get('role') or ''}{link}"


def describe_provider(p: dict) -> str:
    state = "açık" if p.get("enabled", True) else "KAPALI"
    where = "yerel" if p.get("kind") == "local" else "bulut"
    origin = "hesap" if p.get("source") == "account" else "ortam"
    return f"{p.get('name')}  [{where}, {state}, {origin}]  {p.get('model') or '-'}"


def describe_approval(item: dict) -> str:
    """One readable line for an approval request (shows exactly what would run)."""
    action = item.get("action")
    if isinstance(action, dict):
        shown = action.get("argv") or action.get("path") or action.get("url") or action.get("type")
        if isinstance(shown, list):
            shown = " ".join(str(p) for p in shown)
        what = f"{action.get('type', '?')}: {shown}"
    else:
        what = str(action)
    return f"#{item.get('id')} [{item.get('action_class', '?')}] {item.get('requested_by', '?')} -> {what}"
