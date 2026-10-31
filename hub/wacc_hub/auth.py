"""Per-agent API tokens. Stored in data/tokens.json (git-ignored, never committed)."""

import hmac
import json
import os
import secrets

from . import db
from .models import AGENTS

TOKEN_FILE = db.DATA_DIR / "tokens.json"


def load_or_create_tokens(path=None) -> dict:
    path = path or TOKEN_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    tokens = {}
    if path.exists():
        try:
            tokens = json.loads(path.read_text(encoding="utf-8"))
        except ValueError:
            tokens = {}
    changed = False
    for agent in AGENTS:
        if not tokens.get(agent):
            tokens[agent] = secrets.token_urlsafe(32)
            changed = True
    if changed:
        path.write_text(json.dumps(tokens, indent=2), encoding="utf-8")
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
    return tokens


def resolve_actor(tokens: dict, presented: str):
    """Return the agent id owning `presented`, or None. Constant-time comparison."""
    if not presented:
        return None
    found = None
    for agent, token in tokens.items():
        if hmac.compare_digest(token.encode(), presented.encode()):
            found = agent
    return found
