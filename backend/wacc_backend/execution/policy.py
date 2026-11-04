"""Action classification and policy (docs/EXECUTION_SECURITY.md sections 2 and 3).

Default is deny. classify() never runs anything; it turns a raw action into a Decision:
ALLOW (run automatically, audited), APPROVAL (user must approve this exact action), or DENY.
"""

import fnmatch
import hashlib
import json
import os
from dataclasses import dataclass, field
from ipaddress import ip_address
from pathlib import Path
from typing import Iterable, List, Optional
from urllib.parse import urlsplit

from .paths import PathDenied, resolve_in_roots

READ, WRITE_PROJECT, RUN_ALLOWLIST, INSTALL, NETWORK, PUBLISH, DELETE, SYSTEM_CHANGE = (
    "READ", "WRITE_PROJECT", "RUN_ALLOWLIST", "INSTALL", "NETWORK", "PUBLISH", "DELETE", "SYSTEM_CHANGE")
PERSONAL_FILES, FINANCIAL, SECRET_EXPORT = "PERSONAL_FILES", "FINANCIAL", "SECRET_EXPORT"

ALLOW, APPROVAL, DENY = "ALLOW", "APPROVAL", "DENY"

DEFAULT_NETWORK_ALLOWLIST = ("pypi.org", "files.pythonhosted.org", "github.com", "pub.dev", "registry.npmjs.org")
MAX_WRITE_BYTES = 2_000_000
MAX_ARGS = 64
MAX_ARG_LEN = 2000

# Writing here weakens the guard rails themselves, so it always needs the user's approval.
PROTECTED_WRITE_PREFIXES = (
    "backend/wacc_backend/", "hub/wacc_hub/", "web/serve.py", "desktop/wacc_desktop/client.py", ".github/",
    "docs/EXECUTION_SECURITY.md", ".gitignore", ".gitattributes", ".claude/", "scripts/", "start_wacc", "launch.py",
)
# Files that run code or pull in code when someone starts, tests or installs the project, wherever they are.
PROTECTED_WRITE_NAMES = (
    "conftest.py", "sitecustomize.py", "usercustomize.py", "*.pth", "pytest.ini", "tox.ini", "setup.py", "setup.cfg",
    "pyproject.toml", "requirements*.txt", "package.json", "package-lock.json", "pubspec.yaml", "pubspec.lock",
    "*.bat", "*.cmd", "*.ps1", "*.sh", "*.vbs", ".gitattributes", ".gitmodules", "Makefile",
)

GIT_AUTO = {"status", "log", "diff", "show", "add", "commit", "branch", "switch", "rev-parse", "ls-files", "fetch"}
GIT_DESTRUCTIVE = {"reset", "clean", "checkout", "restore", "rebase", "stash", "rm", "mv", "revert", "cherry-pick"}
GIT_FORBIDDEN_FLAGS = ("--upload-pack", "--receive-pack", "--exec", "--config", "-c", "--git-dir", "--work-tree")
# Long options that run programs or write/read outside the project. git accepts ANY unambiguous prefix of a
# long option (--upload-p=...), so an argument is refused when its name is a prefix of one of these.
GIT_DANGEROUS_LONG = ("--upload-pack", "--receive-pack", "--exec", "--exec-path", "--config", "--git-dir",
                      "--work-tree", "--output", "--ext-diff", "--textconv", "--no-index", "--open-files-in-pager",
                      "--paginate", "--namespace", "--super-prefix", "--template", "--separate-git-dir",
                      "--output-directory", "--format-patch", "--attr-source", "--config-env")
FORCE_FLAGS = ("--force", "-f", "--force-with-lease", "--mirror", "--delete")
PROTECTED_BRANCHES = ("main", "master")

# executable -> argv prefixes (after the executable) that run automatically
AUTO_PREFIXES = {
    "python": [["-m", "pytest"], ["-m", "unittest"], ["-m", "compileall"], ["--version"]],
    "flutter": [["doctor"], ["analyze"], ["test"], ["build", "apk"], ["build", "appbundle"], ["build", "web"],
                ["build", "windows"], ["--version"]],
    "dart": [["analyze"], ["format"], ["test"], ["--version"]],
    "adb": [["devices"], ["version"]],
    "node": [["--version"]],
}
INSTALL_PREFIXES = {
    "python": [["-m", "pip", "install"]], "pip": [["install"]],
    "flutter": [["pub", "get"], ["pub", "add"], ["pub", "upgrade"]], "dart": [["pub", "get"], ["pub", "add"]],
    "npm": [["install"], ["i"], ["ci"], ["add"]],
}
# These run project code (test files, build scripts), so an agent could write a file and then run it with
# the user's rights. They need approval unless the user opts in with WACC_EXEC_AUTO_CODE=1.
CODE_RUN_PREFIXES = {
    "python": [["-m", "pytest"], ["-m", "unittest"]],
    "flutter": [["test"], ["build", "apk"], ["build", "appbundle"], ["build", "web"], ["build", "windows"]],
    "dart": [["test"]],
}
ALIASES = {"python3": "python", "py": "python", "pip3": "pip"}
KNOWN_EXECUTABLES = set(AUTO_PREFIXES) | set(INSTALL_PREFIXES) | {"git"}


@dataclass
class Decision:
    action_class: str
    verdict: str
    reason: str
    summary: str
    normalized: dict = field(default_factory=dict)
    payload: dict = field(default_factory=dict)  # bulky data (file content): hashed via normalized, passed to the executor

    @property
    def exec_action(self) -> dict:
        return {**self.normalized, **self.payload}

    @property
    def action_hash(self) -> str:
        blob = json.dumps({"class": self.action_class, "action": self.normalized}, sort_keys=True, default=str)
        return hashlib.sha256(blob.encode()).hexdigest()


def _deny(cls, reason, summary="", normalized=None):
    return Decision(cls, DENY, reason, summary, normalized or {})


def _is_prefix(argv: List[str], prefix: List[str]) -> bool:
    return argv[:len(prefix)] == prefix


def _exe_name(raw: str) -> str:
    name = os.path.basename(raw.replace("\\", "/")).lower()
    if name.endswith(".exe") or name.endswith(".cmd") or name.endswith(".bat"):
        name = name.rsplit(".", 1)[0]
    return ALIASES.get(name, name)


def _path_like(arg: str) -> bool:
    if arg.startswith("-") or "://" in arg:
        return False
    return "/" in arg or "\\" in arg or arg.startswith(".") or (len(arg) > 1 and arg[1] == ":")


def classify(action: dict, roots: Iterable[Path], network_allowlist: Iterable[str] = DEFAULT_NETWORK_ALLOWLIST,
             requested_by: str = "", auto_run_code: bool = False) -> Decision:
    if not isinstance(action, dict) or not isinstance(action.get("type"), str):
        return _deny(SYSTEM_CHANGE, "Action must be an object with a 'type'")
    kind = action["type"]
    roots = list(roots)

    if kind in ("read_file", "list_dir", "write_file", "delete_path"):
        return _classify_path_action(kind, action, roots)
    if kind == "run":
        return _classify_run(action, roots, requested_by, auto_run_code)
    if kind == "http_get":
        return _classify_http(action, network_allowlist)
    return _deny(SYSTEM_CHANGE, f"Unsupported action type {kind!r}", kind)


def _classify_path_action(kind, action, roots) -> Decision:
    raw = action.get("path")
    try:
        resolved = resolve_in_roots(raw, roots, allow_missing=True)  # classify even if missing: no existence leak
    except PathDenied as exc:
        cls = {"OUTSIDE_ROOT": PERSONAL_FILES, "SECRET_FILE": SECRET_EXPORT, "DATA_DIR": SECRET_EXPORT}.get(exc.code, SYSTEM_CHANGE)
        return _deny(cls, exc.message, f"{kind} {raw}")
    norm = {"type": kind, "path": str(resolved)}
    rel = _relative(resolved, roots)
    if kind in ("read_file", "list_dir"):
        return Decision(READ, ALLOW, "Read inside the project", f"{kind} {rel}", norm)
    if kind == "write_file":
        content = action.get("content")
        if not isinstance(content, str):
            return _deny(WRITE_PROJECT, "content must be a string", f"write_file {rel}")
        if len(content.encode("utf-8")) > MAX_WRITE_BYTES:
            return _deny(WRITE_PROJECT, f"content exceeds {MAX_WRITE_BYTES} bytes", f"write_file {rel}")
        norm["sha256"] = hashlib.sha256(content.encode("utf-8")).hexdigest()
        norm["bytes"] = len(content.encode("utf-8"))
        if _is_protected_write(rel):
            return Decision(SYSTEM_CHANGE, APPROVAL, "This file defines the security rules", f"write_file {rel}", norm,
                            {"content": content})
        return Decision(WRITE_PROJECT, ALLOW, "Write inside the project", f"write_file {rel} ({norm['bytes']} bytes)", norm,
                        {"content": content})
    return Decision(DELETE, APPROVAL, "Deleting needs approval; the file is moved to _to_delete/, not erased",
                    f"delete_path {rel}", norm)


def _is_protected_write(rel: str) -> bool:
    low = rel.lower()  # Windows/macOS paths are not case sensitive
    name = low.rsplit("/", 1)[-1]
    if any(low == p.rstrip("/").lower() or low.startswith(p.lower()) for p in PROTECTED_WRITE_PREFIXES):
        return True
    return any(fnmatch.fnmatch(name, pat.lower()) for pat in PROTECTED_WRITE_NAMES)


def _relative(path: Path, roots) -> str:
    for r in roots:
        try:
            return path.relative_to(Path(r).resolve()).as_posix() or "."
        except ValueError:
            continue
    return str(path)


def _classify_run(action, roots, requested_by, auto_run_code: bool = False) -> Decision:
    argv = action.get("argv")
    if (not isinstance(argv, list) or not argv or len(argv) > MAX_ARGS
            or any(not isinstance(a, str) or not a or len(a) > MAX_ARG_LEN or "\x00" in a or "\n" in a for a in argv)):
        return _deny(SYSTEM_CHANGE, "argv must be a non-empty list of up to 64 plain strings", "run")
    summary = "run " + " ".join(argv)
    if "/" in argv[0] or "\\" in argv[0]:
        return _deny(SYSTEM_CHANGE, "Executables must be given by name, not by path", summary)
    try:
        cwd = resolve_in_roots(action.get("cwd") or str(Path(roots[0]).resolve()), roots, allow_missing=False)
    except PathDenied as exc:
        return _deny(PERSONAL_FILES if exc.code == "OUTSIDE_ROOT" else SYSTEM_CHANGE, exc.message, summary)
    exe, args = _exe_name(argv[0]), argv[1:]
    norm = {"type": "run", "argv": [exe] + args, "cwd": str(cwd)}

    # Path-looking arguments must stay inside the roots (values of -m/--message are free text).
    skip = False
    for a in args:
        if skip:
            skip = False
            continue
        if a in ("-m", "--message") and exe == "git" and args[:1] and args[0] in ("commit", "tag"):
            skip = True  # free text of a commit/tag message, not a path
            continue
        if a.startswith("--") and "=" in a:  # --output=/outside, --file=../x: check the value like a path argument
            value = a.split("=", 1)[1]
            if _path_like(value):
                try:
                    resolve_in_roots(value, roots, cwd=cwd)
                except PathDenied as exc:
                    cls = SECRET_EXPORT if exc.code in ("SECRET_FILE", "DATA_DIR") else PERSONAL_FILES
                    return _deny(cls, f"Argument {a!r}: {exc.message}", summary, norm)
        if _path_like(a) and not (exe == "python" and args[:1] == ["-m"] and a == args[1]):
            try:
                resolve_in_roots(a, roots, cwd=cwd)
            except PathDenied as exc:
                cls = SECRET_EXPORT if exc.code in ("SECRET_FILE", "DATA_DIR") else PERSONAL_FILES
                return _deny(cls, f"Argument {a!r}: {exc.message}", summary, norm)

    if exe == "git":
        return _classify_git(args, norm, summary, requested_by)
    for prefix in INSTALL_PREFIXES.get(exe, []):
        if _is_prefix(args, prefix):
            # The approval covers what will be installed, not just the words of the command: bind it to the
            # content of the manifests/requirement files/local packages it reads (they are agent-writable).
            norm["inputs_sha256"] = _install_fingerprint(exe, args, cwd, roots)
            return Decision(INSTALL, APPROVAL, "Installing packages needs approval (once per package/version)", summary, norm)
    if not auto_run_code:
        for prefix in CODE_RUN_PREFIXES.get(exe, []):
            if _is_prefix(args, prefix):
                return Decision(SYSTEM_CHANGE, APPROVAL, "Runs project code (tests/build); needs approval unless WACC_EXEC_AUTO_CODE=1", summary, norm)
    for prefix in AUTO_PREFIXES.get(exe, []):
        if _is_prefix(args, prefix):
            return Decision(RUN_ALLOWLIST, ALLOW, "Allowlisted command", summary, norm)
    if exe in KNOWN_EXECUTABLES:
        return Decision(SYSTEM_CHANGE, APPROVAL, "Command is not on the automatic allowlist", summary, norm)
    return Decision(SYSTEM_CHANGE, APPROVAL, "Unknown program; unclassified actions count as system changes", summary, norm)


MANIFESTS = {"pip": ("requirements.txt", "pyproject.toml", "setup.py", "setup.cfg"),
             "python": ("requirements.txt", "pyproject.toml", "setup.py", "setup.cfg"),
             "npm": ("package.json", "package-lock.json", "npm-shrinkwrap.json"),
             "flutter": ("pubspec.yaml", "pubspec.lock"), "dart": ("pubspec.yaml", "pubspec.lock")}
_FINGERPRINT_LIMIT = 5_000_000


def _install_fingerprint(exe, args, cwd: Path, roots) -> str:
    """SHA-256 over every file an install reads: manifests in cwd, -r/-c files, and local directories given as
    packages (their whole tree, capped). Unreadable or oversized input changes the hash, never hides it."""
    files = []
    for name in MANIFESTS.get(exe, ()):
        files.append(Path(cwd) / name)
    take_next = False
    for a in args:
        if take_next:
            files.append(Path(cwd) / a)
            take_next = False
        elif a in ("-r", "--requirement", "-c", "--constraint", "-e", "--editable"):
            take_next = True
        elif a.startswith(("--requirement=", "--constraint=")):
            files.append(Path(cwd) / a.split("=", 1)[1])
        elif a.startswith("-"):
            continue
        elif a == "." or a.startswith(("./", "../", ".\\")) or "/" in a or "\\" in a:
            files.append(Path(cwd) / a)
    h, total = hashlib.sha256(), 0
    for f in sorted(set(files), key=str):
        try:
            targets = sorted(p for p in f.rglob("*") if p.is_file() and ".git" not in p.parts) if f.is_dir() else [f]
        except OSError:
            targets = []
        for t in targets:
            try:
                data = t.read_bytes()
            except OSError:
                data = b"<unreadable>"
            total += len(data)
            h.update(str(t).encode() + b"\0" + hashlib.sha256(data).digest())
            if total > _FINGERPRINT_LIMIT:
                h.update(b"<too large>" + os.urandom(8))  # never matches a previous approval
                return h.hexdigest()
    return h.hexdigest()


def _classify_git(args, norm, summary, requested_by) -> Decision:
    if not args or args[0].startswith("-"):
        return Decision(SYSTEM_CHANGE, APPROVAL, "git global options are not allowed automatically", summary, norm)
    if any(a in GIT_FORBIDDEN_FLAGS or a.startswith(("--upload-pack", "--receive-pack", "--exec=", "--config=")) for a in args):
        return _deny(SYSTEM_CHANGE, "This git option can run arbitrary programs", summary, norm)
    for a in args[1:]:
        if a == "--":
            break
        if a.startswith("--") and len(a) > 2:
            name = a.split("=", 1)[0]
            if any(bad.startswith(name) for bad in GIT_DANGEROUS_LONG):  # includes abbreviations like --upload-p
                return _deny(SYSTEM_CHANGE, "This git option can run programs or write outside the project", summary, norm)
        elif a.startswith("-O") or a.startswith("-o") and args[0] != "push":
            return _deny(SYSTEM_CHANGE, "This git option reads or writes an arbitrary file", summary, norm)
    sub = args[0]
    if sub == "push":
        if any(a in FORCE_FLAGS or (a.startswith("+") and len(a) > 1) for a in args[1:]):
            return _deny(PUBLISH, "Force/delete pushes are never allowed", summary, norm)
        if any(a.split(":")[-1] in PROTECTED_BRANCHES for a in args[1:] if not a.startswith("-")) and requested_by != "claude1":
            return _deny(PUBLISH, "Only claude1 may push main, and only with approval", summary, norm)
        return Decision(PUBLISH, APPROVAL, "Publishing needs approval every time", summary, norm)
    if sub in GIT_DESTRUCTIVE or (sub == "branch" and any(a in ("-D", "-d", "--delete", "-m", "-M") for a in args)):
        return Decision(DELETE, APPROVAL, "Can discard work; needs approval each time", summary, norm)
    if sub == "fetch" and any(":" in a or "@" in a for a in args[1:] if not a.startswith("-")):
        return Decision(NETWORK, APPROVAL, "Fetching from a URL/other location needs approval", summary, norm)
    if sub in GIT_AUTO:
        if sub == "commit" and any(a in ("--amend", "--no-verify") for a in args):
            return Decision(SYSTEM_CHANGE, APPROVAL, "Rewriting history or skipping hooks needs approval", summary, norm)
        return Decision(RUN_ALLOWLIST, ALLOW, "Allowlisted git command", summary, norm)
    return Decision(SYSTEM_CHANGE, APPROVAL, "git command is not on the automatic allowlist", summary, norm)


def _classify_http(action, allowlist) -> Decision:
    url = action.get("url")
    parts = urlsplit(url if isinstance(url, str) else "")
    host = (parts.hostname or "").lower()
    summary = f"http_get {url}"
    if parts.scheme != "https" or not host or parts.username or parts.password:
        return _deny(NETWORK, "Only plain https URLs without credentials are allowed", summary)
    try:
        ip = ip_address(host)
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
            return _deny(NETWORK, "Requests to local/private addresses are not allowed", summary)
    except ValueError:
        if host == "localhost" or host.endswith((".local", ".internal", ".localhost")):
            return _deny(NETWORK, "Requests to local names are not allowed", summary)
    norm = {"type": "http_get", "url": url}
    if any(host == d or host.endswith("." + d) for d in allowlist):
        return Decision(NETWORK, ALLOW, "Allowlisted domain", summary, norm)
    return Decision(NETWORK, APPROVAL, "Domain is not on the allowlist", summary, norm)
