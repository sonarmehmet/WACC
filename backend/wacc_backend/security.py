"""API token handling. The token comes from env or a git-ignored file under data/."""

import hmac
import json
import os
import re
import secrets
from pathlib import Path
from typing import Optional

from .config import Settings


def get_or_create_token(settings: Settings) -> str:
    if settings.token_override:
        return settings.token_override
    return _file_token(settings.token_file)


def get_or_create_user_token(settings: Settings) -> str:
    """Token only the human holds; it alone may approve actions.

    It is NEVER written to disk: agents run on the same computer and could read a file. Unless the
    user pins one via WACC_BACKEND_USER_TOKEN, a fresh token is generated at each start and shown
    once in the console window.
    """
    return settings.user_token_override or secrets.token_urlsafe(32)


AGENT_NAMES = ("claude1", "claude2", "claude3", "gemini")  # built in; more come from data/agents.json (Hub registry)


def registry_agents(data_dir) -> list:
    """Agents the Hub published in data/agents.json (non-secret): [{name, kind, role, provider, enabled}]."""
    try:
        raw = json.loads((Path(data_dir) / "agents.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    out = []
    for item in raw if isinstance(raw, list) else []:
        name = item.get("name") if isinstance(item, dict) else None
        if isinstance(name, str) and re.fullmatch(r"[a-z][a-z0-9_-]{1,19}", name):
            out.append({"name": name, "kind": str(item.get("kind", "other")), "role": str(item.get("role", "")),
                        "provider": item.get("provider") if isinstance(item.get("provider"), str) else None,
                        "enabled": bool(item.get("enabled", True))})
    return out


def _agent_names(settings: Settings) -> list:
    names = list(AGENT_NAMES)
    for a in registry_agents(settings.data_dir):
        if a["name"] not in names:
            names.append(a["name"])
    return names


def get_or_create_agent_tokens(settings: Settings) -> dict:
    """One token per agent (data/backend_tokens.json, git-ignored). The token decides who is acting, so
    an agent cannot submit actions or change another agent's state under someone else's name.
    Agents added later in the Hub (data/agents.json) get a token here too."""
    path = settings.agent_tokens_file
    names = _agent_names(settings)
    tokens: dict = {}
    if path.exists():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            tokens = {k: v for k, v in loaded.items() if isinstance(v, str) and v and k in names}
        except ValueError:
            tokens = {}
    changed = False
    for name in names:
        if name not in tokens:
            tokens[name] = secrets.token_urlsafe(32)
            changed = True
    if changed or not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(tokens, indent=2), encoding="utf-8")
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
    return tokens


class AgentTokenBook:
    """Per-agent tokens that follow the Hub's agent list without restarting the backend: reloads whenever
    agents.json or backend_tokens.json changes. Switched-off or removed agents are not accepted."""

    def __init__(self, settings: Optional[Settings] = None, fixed: Optional[dict] = None):
        self.settings, self.fixed = settings, fixed
        self._stamp = None
        self._tokens: dict = dict(fixed or {})
        self._disabled: set = set()

    def _mtime(self, path):
        try:
            return path.stat().st_mtime_ns
        except OSError:
            return None

    def _refresh(self) -> None:
        if self.fixed is not None:
            return
        s = self.settings
        stamp = (self._mtime(s.data_dir / "agents.json"), self._mtime(s.agent_tokens_file))
        if stamp == self._stamp:
            return
        self._tokens = get_or_create_agent_tokens(s)
        self._disabled = {a["name"] for a in registry_agents(s.data_dir) if not a["enabled"]}
        self._stamp = (self._mtime(s.data_dir / "agents.json"), self._mtime(s.agent_tokens_file))

    def who(self, presented: str) -> Optional[str]:
        self._refresh()
        found = None
        for name, tok in self._tokens.items():
            if token_matches(tok, presented) and name not in self._disabled:
                found = name
        return found


def _file_token(path) -> str:
    if path.exists():
        value = path.read_text(encoding="utf-8").strip()
        if value:
            return value
    path.parent.mkdir(parents=True, exist_ok=True)
    value = secrets.token_urlsafe(32)
    path.write_text(value, encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return value


def token_matches(expected: str, presented: str) -> bool:
    if not expected or not presented:
        return False
    return hmac.compare_digest(expected.encode(), presented.encode())
