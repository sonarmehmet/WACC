"""AI accounts the user adds and removes while WACC is running (any OpenAI-compatible endpoint).

Stored in data/ai_accounts.json (git-ignored, same trust level as the token files). The API key stays in that
file: it is never returned by the API, never logged and never written to the database. Only the user token
may change accounts; agents can list them (without keys) and use them through /ai/complete.
"""

import json
import os
import re
import tempfile
from pathlib import Path
from typing import List, Optional

from .orchestrator import CLOUD, LOCAL, OpenAICompatProvider, OrchestratorError, validate_base_url

NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{1,30}$")
RESERVED = {"local-llm", "cloud-llm", "mock"}  # names used by the environment-configured providers
DEFAULT_PRICE_IN, DEFAULT_PRICE_OUT = 0.003, 0.015
MAX_ACCOUNTS = 20


def _clean(spec: dict) -> dict:
    if not isinstance(spec, dict):
        raise OrchestratorError("BAD_ACCOUNT", "Account must be an object")
    name = str(spec.get("name", "")).strip().lower()
    if not NAME_RE.match(name):
        raise OrchestratorError("BAD_NAME", "Name must be 2-31 characters: a-z, 0-9, '-' or '_'")
    if name in RESERVED:
        raise OrchestratorError("BAD_NAME", f"{name!r} is reserved for environment-configured providers")
    kind = spec.get("kind")
    if kind not in (LOCAL, CLOUD):
        raise OrchestratorError("BAD_KIND", "kind must be 'local' or 'cloud'")
    try:
        base_url = validate_base_url(str(spec.get("base_url", "")), kind)  # local: loopback only, cloud: https only
    except ValueError as exc:
        raise OrchestratorError("BAD_URL", str(exc))
    model = str(spec.get("model", "")).strip()
    if not model or len(model) > 100 or any(c.isspace() for c in model):
        raise OrchestratorError("BAD_MODEL", "Model name is required (no spaces, up to 100 characters)")
    key = spec.get("api_key") or None
    if key is not None:
        key = str(key).strip()
        if len(key) > 500 or any(c.isspace() for c in key):
            raise OrchestratorError("BAD_KEY", "API key looks invalid (no spaces, up to 500 characters)")
    if kind == CLOUD and not key:
        raise OrchestratorError("BAD_KEY", "A cloud account needs an API key")
    prices = []
    for field, default in (("price_in_per_1k", DEFAULT_PRICE_IN), ("price_out_per_1k", DEFAULT_PRICE_OUT)):
        value = spec.get(field, default if kind == CLOUD else 0.0)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= value <= 100:
            raise OrchestratorError("BAD_PRICE", f"{field} must be a number between 0 and 100 (USD per 1000 tokens)")
        prices.append(float(value))
    return {"name": name, "kind": kind, "base_url": base_url, "model": model, "api_key": key,
            "price_in_per_1k": prices[0], "price_out_per_1k": prices[1], "enabled": bool(spec.get("enabled", True))}


def to_provider(acc: dict) -> OpenAICompatProvider:
    return OpenAICompatProvider(acc["name"], acc["kind"], acc["base_url"], acc["model"], api_key=acc.get("api_key"),
                                price_in_per_1k=acc["price_in_per_1k"], price_out_per_1k=acc["price_out_per_1k"])


def public_view(acc: dict) -> dict:
    return {k: v for k, v in acc.items() if k != "api_key"} | {"has_key": bool(acc.get("api_key")), "source": "account"}


class AccountStore:
    def __init__(self, path: Path):
        self.path = Path(path)

    def load(self) -> List[dict]:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
        accounts = []
        for item in raw if isinstance(raw, list) else []:
            try:
                accounts.append(_clean(item))
            except OrchestratorError:
                continue  # a hand-edited bad entry must not stop the backend from starting
        return accounts

    def _save(self, accounts: List[dict]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(self.path.parent), prefix=".ai_accounts.", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(accounts, fh, indent=2)
            try:
                os.chmod(tmp, 0o600)
            except OSError:
                pass
            os.replace(tmp, self.path)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)

    def add(self, spec: dict) -> dict:
        acc = _clean(spec)
        accounts = self.load()
        if any(a["name"] == acc["name"] for a in accounts):
            raise OrchestratorError("DUPLICATE", f"Account {acc['name']!r} already exists")
        if len(accounts) >= MAX_ACCOUNTS:
            raise OrchestratorError("TOO_MANY", f"At most {MAX_ACCOUNTS} accounts")
        self._save(accounts + [acc])
        return acc

    def remove(self, name: str) -> bool:
        accounts = self.load()
        kept = [a for a in accounts if a["name"] != name]
        if len(kept) == len(accounts):
            return False
        self._save(kept)
        return True

    def set_enabled(self, name: str, enabled: bool) -> Optional[dict]:
        accounts = self.load()
        for a in accounts:
            if a["name"] == name:
                a["enabled"] = bool(enabled)
                self._save(accounts)
                return a
        return None
