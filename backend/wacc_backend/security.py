"""API token handling. The token comes from env or a git-ignored file under data/."""

import hmac
import os
import secrets

from .config import Settings


def get_or_create_token(settings: Settings) -> str:
    if settings.token_override:
        return settings.token_override
    path = settings.token_file
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
