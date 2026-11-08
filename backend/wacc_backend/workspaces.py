"""Project workspaces: one local folder per project, and the agents that may work in it.

A workspace is the user's decision (user token only): its folder may be anywhere on the computer except the places
that would let an agent reach WACC itself, the system or credentials. An agent that is assigned to one or more
workspaces can only touch those folders (the execution policy still decides what needs approval); an agent that is
in none keeps the default workspace folder. Removing a workspace never deletes the folder or its files.

Stored in data/workspaces.json (git-ignored). Nothing secret is kept here.
"""

import json
import os
import re
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable, List, Optional

from .storage import StorageError

NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{1,30}$")
AGENT_RE = re.compile(r"^[a-z][a-z0-9_-]{1,19}$")
MAX_WORKSPACES = 50
MAX_AGENTS = 30
_TR = str.maketrans("çğıöşüÇĞİÖŞÜâîû", "cgiosuCGIOSUaiu")
SENSITIVE_PARTS = {".ssh", ".aws", ".gnupg", ".azure", ".kube", ".docker", "appdata", "system32", "syswow64"}


def slugify(title: str) -> str:
    text = str(title or "").translate(_TR).lower()
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    return text[:31].strip("-")


def _same_or_inside(path: Path, other: Path) -> bool:
    a, b = os.path.normcase(str(path)), os.path.normcase(str(other))
    return a == b or a.startswith(b + os.sep)


def check_folder(folder: Path, forbidden: Iterable[Path], trusted_root: Optional[Path] = None) -> Path:
    """The resolved folder, or StorageError when an agent must not work there."""
    try:
        resolved = folder.resolve()
    except (OSError, RuntimeError):
        raise StorageError("BAD_FOLDER", "Klasör yolu çözülemedi")
    if trusted_root is not None and _same_or_inside(resolved, trusted_root.resolve()) and resolved != trusted_root.resolve():
        for bad in forbidden:  # WACC's own default workspace folder: only the overlap rule applies
            bad = Path(bad).resolve()
            if _same_or_inside(resolved, bad) or _same_or_inside(bad, resolved):
                raise StorageError("BAD_FOLDER", "WACC'ın kendi program/veri klasörüyle çakışan bir klasör olamaz")
        return resolved
    if resolved.parent == resolved:
        raise StorageError("BAD_FOLDER", "Bir sürücünün kökü proje klasörü olamaz; içinde bir klasör seç")
    if any(part.lower() in SENSITIVE_PARTS for part in resolved.parts):
        raise StorageError("BAD_FOLDER", "Sistem, kimlik bilgisi ya da uygulama verisi klasörleri proje klasörü olamaz")
    for env in ("WINDIR", "ProgramFiles", "ProgramFiles(x86)", "ProgramData"):
        base = os.environ.get(env)
        if base and _same_or_inside(resolved, Path(base)):
            raise StorageError("BAD_FOLDER", "Windows ve Program Files klasörleri proje klasörü olamaz")
    home = Path.home().resolve()
    if os.path.normcase(str(resolved)) == os.path.normcase(str(home)):
        raise StorageError("BAD_FOLDER", "Kullanıcı klasörünün tamamı yerine içinden bir klasör seç (örn. Belgeler\\ProjeAdi)")
    for bad in forbidden:
        bad = Path(bad).resolve()
        if _same_or_inside(resolved, bad) or _same_or_inside(bad, resolved):
            raise StorageError("BAD_FOLDER", "WACC'ın kendi program/veri klasörüyle çakışan bir klasör olamaz")
    return resolved


class WorkspaceStore:
    def __init__(self, path: Path, default_root: Path, forbidden: Iterable[Path] = ()):
        self.path = Path(path)
        self.default_root = Path(default_root)
        self.forbidden = [Path(p) for p in forbidden]
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ io
    def _load(self) -> List[dict]:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
        out = []
        for item in raw if isinstance(raw, list) else []:
            if isinstance(item, dict) and NAME_RE.match(str(item.get("name", ""))) and item.get("folder"):
                out.append({"name": item["name"], "title": str(item.get("title") or item["name"])[:60],
                            "folder": str(item["folder"]), "created": str(item.get("created", "")),
                            "agents": [a for a in item.get("agents", []) if isinstance(a, str) and AGENT_RE.match(a)][:MAX_AGENTS]})
        return out

    def _save(self, items: List[dict]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(self.path.parent), suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(items, fh, ensure_ascii=False, indent=2)
            os.replace(tmp, self.path)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)

    @staticmethod
    def _view(item: dict) -> dict:
        folder = Path(item["folder"])
        return {**item, "exists": folder.is_dir()}

    # ----------------------------------------------------------------- read
    def list(self) -> List[dict]:
        return [self._view(i) for i in self._load()]

    def get(self, name: str) -> dict:
        for item in self._load():
            if item["name"] == name:
                return self._view(item)
        raise StorageError("NOT_FOUND", f"Proje bulunamadı: {name!r}")

    def folders(self) -> List[Path]:
        return [Path(i["folder"]) for i in self._load()]

    def folders_for(self, agent: str) -> Optional[List[Path]]:
        """The folders this agent is confined to, or None when it is in no project (default workspace applies)."""
        mine = [Path(i["folder"]) for i in self._load() if agent in i["agents"]]
        return mine or None

    def projects_of(self, agent: str) -> List[str]:
        return [i["name"] for i in self._load() if agent in i["agents"]]

    # ---------------------------------------------------------------- write
    def add(self, title: str, folder: Optional[str] = None, agents: Optional[List[str]] = None) -> dict:
        title = str(title or "").strip()
        name = slugify(title)
        if not NAME_RE.match(name):
            raise StorageError("BAD_NAME", "Proje adı 2-31 karakter olmalı (harf ve rakam)")
        if folder and str(folder).strip():
            raw = Path(str(folder).strip().strip('"'))
            if not raw.is_absolute():
                raise StorageError("BAD_FOLDER", "Klasör tam yol olmalı (örn. C:\\Users\\sen\\Belgeler\\proje)")
            target = raw
        else:
            target = self.default_root / name
        with self._lock:
            items = self._load()
            if len(items) >= MAX_WORKSPACES:
                raise StorageError("TOO_MANY", f"En fazla {MAX_WORKSPACES} proje")
            if any(i["name"] == name for i in items):
                raise StorageError("DUPLICATE", f"'{name}' adlı bir proje zaten var")
            resolved = check_folder(target, self.forbidden, self.default_root)
            if any(os.path.normcase(i["folder"]) == os.path.normcase(str(resolved)) for i in items):
                raise StorageError("DUPLICATE", "Bu klasör zaten başka bir projeye bağlı")
            try:
                resolved.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                raise StorageError("BAD_FOLDER", f"Klasör oluşturulamadı: {exc.strerror or type(exc).__name__}")
            item = {"name": name, "title": title[:60], "folder": str(resolved),
                    "created": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "agents": [a for a in (agents or []) if AGENT_RE.match(a)][:MAX_AGENTS]}
            items.append(item)
            self._save(items)
            return self._view(item)

    def remove(self, name: str) -> bool:
        """Forget the project. The folder and everything in it stay."""
        with self._lock:
            items = self._load()
            kept = [i for i in items if i["name"] != name]
            if len(kept) == len(items):
                return False
            self._save(kept)
            return True

    def assign(self, name: str, agent: str) -> dict:
        if not AGENT_RE.match(agent or ""):
            raise StorageError("BAD_AGENT", "Ajan adı geçersiz")
        with self._lock:
            items = self._load()
            for item in items:
                if item["name"] == name:
                    if agent not in item["agents"]:
                        if len(item["agents"]) >= MAX_AGENTS:
                            raise StorageError("TOO_MANY", f"Bir projede en fazla {MAX_AGENTS} ajan")
                        item["agents"].append(agent)
                        self._save(items)
                    return self._view(item)
        raise StorageError("NOT_FOUND", f"Proje bulunamadı: {name!r}")

    def unassign(self, name: str, agent: str) -> dict:
        with self._lock:
            items = self._load()
            for item in items:
                if item["name"] == name:
                    item["agents"] = [a for a in item["agents"] if a != agent]
                    self._save(items)
                    return self._view(item)
        raise StorageError("NOT_FOUND", f"Proje bulunamadı: {name!r}")

    def forget_agent(self, agent: str) -> None:
        with self._lock:
            items = self._load()
            for item in items:
                item["agents"] = [a for a in item["agents"] if a != agent]
            self._save(items)
