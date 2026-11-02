"""API token handling. The token comes from env or a git-ignored file under data/."""

import hmac
import json
import os
import secrets

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


AGENT_NAMES = ("claude1", "claude2", "claude3", "gemini")


def get_or_create_agent_tokens(settings: Settings) -> dict:
    """One token per agent (data/backend_tokens.json, git-ignored). The token decides who is acting, so
    an agent cannot submit actions or change another agent's state under someone else's name."""
    path = settings.agent_tokens_file
    tokens: dict = {}
    if path.exists():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            tokens = {k: v for k, v in loaded.items() if k in AGENT_NAMES and isinstance(v, str) and v}
        except ValueError:
            tokens = {}
    changed = False
    for name in AGENT_NAMES:
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
