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
    )
