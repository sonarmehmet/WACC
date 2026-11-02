"""Settings loaded from environment variables. No secrets live in code."""

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Optional

ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class Settings:
    host: str
    port: int
    data_dir: Path
    db_path: Path
    token_file: Path
    token_override: Optional[str]
    user_token_override: Optional[str]
    exec_roots: tuple
    agent_tokens_file: Path = Path("backend_tokens.json")
    exec_auto_code: bool = False


def load_settings(env: Optional[Mapping[str, str]] = None) -> Settings:
    env = os.environ if env is None else env
    data_dir = Path(env.get("WACC_DATA_DIR") or ROOT / "data")
    try:
        port = int(env.get("WACC_BACKEND_PORT", "8800"))
    except ValueError:
        raise ValueError("WACC_BACKEND_PORT must be an integer")
    if not 1 <= port <= 65535:
        raise ValueError("WACC_BACKEND_PORT must be between 1 and 65535")
    return Settings(
        host=env.get("WACC_BACKEND_HOST", "127.0.0.1"),  # localhost only by default
        port=port,
        data_dir=data_dir,
        db_path=Path(env.get("WACC_BACKEND_DB") or data_dir / "backend.db"),
        token_file=data_dir / "backend_token.txt",
        token_override=env.get("WACC_BACKEND_TOKEN") or None,
        user_token_override=env.get("WACC_BACKEND_USER_TOKEN") or None,
        exec_auto_code=env.get("WACC_EXEC_AUTO_CODE", "") == "1",
        agent_tokens_file=data_dir / "backend_tokens.json",
        exec_roots=tuple(Path(r) for r in env.get("WACC_EXEC_ROOTS", str(ROOT)).split(os.pathsep) if r),
    )


# Keys that may come from data/llm.env. The approval token must never live in a file, and nothing outside
# the WACC_ namespace (PATH, PYTHONPATH, ...) may be set from it.
ENV_FILE_DENY = {"WACC_BACKEND_USER_TOKEN", "WACC_BACKEND_TOKEN"}


def load_env_file(path, env=None) -> list:
    """Read KEY=VALUE lines (# comments allowed) into env without overriding what is already set.

    Returns the list of keys that were applied. Missing file -> nothing."""
    env = os.environ if env is None else env
    applied = []
    try:
        lines = Path(path).read_text(encoding="utf-8-sig").splitlines()
    except OSError:
        return applied
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip().strip('"').strip("'")
        if not key.startswith("WACC_") or key in ENV_FILE_DENY or not value or key in env:
            continue
        env[key] = value
        applied.append(key)
    return applied
