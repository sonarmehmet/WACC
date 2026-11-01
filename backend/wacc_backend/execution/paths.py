"""Path safety: resolve fully (.., symlinks/junctions, case) and confine to the allowed roots."""

import fnmatch
import os
from pathlib import Path
from typing import Iterable, List

# Files agents must never read or write, whatever the root.
SECRET_PATTERNS = ("tokens.json", "*token*.txt", "*token*.json", ".env", ".env.*", "*.env", "*.pem", "*.key",
                   "*.jks", "id_rsa*", "id_ed25519*", "key.properties", "*.keystore", "credentials*.json")
PROTECTED_DIRS = (".git",)  # raw .git internals are only touched through git commands


class PathDenied(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _norm(p: Path) -> str:
    return os.path.normcase(str(p))


def is_secret_file(path: Path) -> bool:
    name = path.name.lower()
    return any(fnmatch.fnmatch(name, pat.lower()) for pat in SECRET_PATTERNS)


def resolve_in_roots(raw: str, roots: Iterable[Path], cwd: Path = None, allow_missing: bool = True) -> Path:
    """Return the fully resolved path or raise PathDenied. Never trusts the lexical form."""
    if not isinstance(raw, str) or not raw.strip() or "\x00" in raw or "\n" in raw:
        raise PathDenied("BAD_PATH", "Path is empty or contains control characters")
    roots_resolved: List[Path] = [Path(r).resolve() for r in roots]
    if not roots_resolved:
        raise PathDenied("NO_ROOTS", "No allowed root is configured")
    candidate = Path(raw)
    if not candidate.is_absolute():
        candidate = (Path(cwd) if cwd else roots_resolved[0]) / candidate
    try:
        resolved = candidate.resolve(strict=not allow_missing)
    except (OSError, RuntimeError):
        raise PathDenied("BAD_PATH", "Path cannot be resolved")
    inside = any(_norm(resolved) == _norm(r) or _norm(resolved).startswith(_norm(r) + os.sep) for r in roots_resolved)
    if not inside:
        raise PathDenied("OUTSIDE_ROOT", "Path is outside the allowed project folders")
    if is_secret_file(resolved):
        raise PathDenied("SECRET_FILE", "This file holds secrets and is not accessible to agents")
    for root in roots_resolved:
        try:
            rel = resolved.relative_to(root)
        except ValueError:
            continue
        if rel.parts and rel.parts[0] in PROTECTED_DIRS:
            raise PathDenied("PROTECTED_DIR", "Use git commands instead of touching .git directly")
        if rel.parts and rel.parts[0] == "data" and len(rel.parts) > 1 and rel.parts[1] not in (".gitkeep",):
            raise PathDenied("DATA_DIR", "Runtime data (databases, tokens) is not accessible to agents")
    return resolved
