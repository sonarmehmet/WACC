"""Check the configured local/cloud model with one tiny request.

Usage (from the repo root):  python scripts/check_llm.py
Reads WACC_LOCAL_LLM_* / WACC_CLOUD_LLM_* from the environment or data/llm.env. Prints only status,
model name, latency and the first words of the answer. Never prints keys.
"""

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from wacc_backend.config import load_env_file  # noqa: E402
from wacc_backend.orchestrator import ProviderError, build_providers  # noqa: E402


def main() -> int:
    applied = load_env_file(ROOT / "data" / "llm.env")
    if applied:
        print("data/llm.env: " + ", ".join(k for k in applied if "KEY" not in k))
    try:
        providers = build_providers(__import__("os").environ)
    except ValueError as exc:
        print(f"CONFIG ERROR: {exc}")
        return 2
    if not providers:
        print("No model configured. Set WACC_LOCAL_LLM_URL (e.g. http://127.0.0.1:11434/v1) and "
              "WACC_LOCAL_LLM_MODEL in data/llm.env. See docs/LOCAL_LLM.md")
        return 2
    failed = 0
    for p in providers:
        start = time.time()
        try:
            out = p.complete("Reply with the single word OK.", "You are a connectivity test.", 16)
            print(f"PASS {p.name} ({p.kind}, {p.model}) {time.time() - start:.1f}s -> {out.text.strip()[:40]!r}")
        except ProviderError as exc:
            failed += 1
            print(f"FAIL {p.name} ({p.kind}, {p.model}): {exc}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
