"""Action classification and policy (docs/EXECUTION_SECURITY.md sections 2 and 3).

Default is deny. classify() never runs anything; it turns a raw action into a Decision:
ALLOW (run automatically, audited), APPROVAL (user must approve this exact action), or DENY.
"""

import hashlib
import json
import os
import re
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

# Writing here weakens the guard rails themselves or changes what runs at the next start (launchers,
# dependency lists, modules that shadow the standard library), so it always needs the user's approval.
PROTECTED_WRITE_PREFIXES = ("backend/wacc_backend/execution/", "docs/EXECUTION_SECURITY.md", ".gitignore", ".gitattributes",
                            ".github/", "scripts/", "backend/wacc_backend/security.py", "backend/wacc_backend/app.py",
                            "backend/wacc_backend/config.py", "backend/wacc_backend/accounts.py",
                            "hub/wacc_hub/auth.py", "hub/wacc_hub/api.py", "web/serve.py", "desktop/wacc_desktop/__main__.py")
PROTECTED_WRITE_SUFFIXES = (".bat", ".cmd", ".ps1", ".sh", ".pth", ".vbs", ".lnk", ".exe", ".dll")
PROTECTED_WRITE_NAMES = ("requirements.txt", "pubspec.yaml", "pubspec.lock", "pyproject.toml", "setup.py", "setup.cfg",
                         "conftest.py", "sitecustomize.py", "usercustomize.py", "package.json", "package-lock.json",
                         "analysis_options.yaml", "tox.ini", "pytest.ini")
# Folders that a launcher puts first on Python's import path: a new top-level .py there can shadow json, http, fastapi...
IMPORT_ROOT_DIRS = ("hub", "backend", "web", "desktop", "scripts")


def _protected_write(rel: str) -> bool:
    low = rel.lower()
    if any(low == p.rstrip("/").lower() or low.startswith(p.lower()) for p in PROTECTED_WRITE_PREFIXES):
        return True
    name = low.rsplit("/", 1)[-1]
    if low.endswith(PROTECTED_WRITE_SUFFIXES) or name in PROTECTED_WRITE_NAMES:
        return True
    parts = low.split("/")
    return name.endswith(".py") and (len(parts) == 1 or (len(parts) == 2 and parts[0] in IMPORT_ROOT_DIRS))

GIT_AUTO = {"status", "log", "diff", "show", "add", "commit", "branch", "switch", "rev-parse", "ls-files", "fetch"}
GIT_DESTRUCTIVE = {"reset", "clean", "checkout", "restore", "rebase", "stash", "rm", "mv", "revert", "cherry-pick"}
GIT_FORBIDDEN_FLAGS = ("--upload-pack", "--receive-pack", "--exec", "--config", "-c", "--git-dir", "--work-tree")
# Options that write outside the project, read arbitrary files, run helpers, or discard work. Git accepts any
# unambiguous prefix of a long option (--forc, --out) and clusters short ones (-fA), so matching is by prefix/char.
GIT_DENIED_LONG = ("--output", "--open-files-in-pager", "--ext-diff", "--textconv")
GIT_APPROVAL_LONG = ("--force", "--force-with-lease", "--no-index", "--discard-changes", "--force-create", "--orphan",
                     "--ignore-removal", "--delete", "--mirror")
GIT_DENIED_SHORT = "O"
GIT_APPROVAL_SHORT = "fCB"


def _git_option_risk(args) -> Optional[str]:
    """'deny', 'approval' or None for the options in a git argument list (stops at --)."""
    risk = None
    skip = False
    for a in args:
        if skip:
            skip = False
            continue
        if a == "--":
            break
        if a in ("-m", "--message"):
            skip = True
            continue
        if a.startswith("--"):
            name = a.split("=", 1)[0]
            if len(name) >= 3 and any(d.startswith(name) for d in GIT_DENIED_LONG):
                return "deny"
            if len(name) >= 3 and any(d.startswith(name) for d in GIT_APPROVAL_LONG):
                risk = "approval"
        elif a.startswith("-") and len(a) > 1 and not a.startswith("-m"):
            if any(ch in GIT_DENIED_SHORT for ch in a[1:]):
                return "deny"
            if any(ch in GIT_APPROVAL_SHORT for ch in a[1:]):
                risk = "approval"
    return risk
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
    "python": [["-m", "pytest"], ["-m", "unittest"], ["-m", "compileall"]],
    "flutter": [["analyze"], ["test"], ["build", "apk"], ["build", "appbundle"], ["build", "web"], ["build", "windows"]],
    "dart": [["analyze"], ["test"]],
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


_PLAIN_PACKAGE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.\-]*(\[[A-Za-z0-9_,\-]+\])?((==|>=|<=|~=|!=|<|>)[A-Za-z0-9_.*+\-]+)?")
_SAFE_INSTALL_FLAGS = ("--upgrade", "-U", "--quiet", "-q", "--no-input", "--disable-pip-version-check")


def plain_package_install(normalized: dict) -> bool:
    """True when an install only names packages from the default index (name, optional version). Only those may
    skip a second approval: 'pip install .', '-r file', URLs, other indexes or editable installs run content that
    can change after the user approved the identical command line."""
    argv = normalized.get("argv") or []
    if argv[:4] == ["python", "-m", "pip", "install"]:
        rest = argv[4:]
    elif argv[:2] == ["pip", "install"]:
        rest = argv[2:]
    else:
        return False  # flutter/dart/npm installs always ask again
    names = [a for a in rest if not a.startswith("-")]
    flags = [a for a in rest if a.startswith("-")]
    return bool(names) and all(_PLAIN_PACKAGE.fullmatch(a) for a in names) and all(f in _SAFE_INSTALL_FLAGS for f in flags)


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


def _path_candidates(arg: str, exe: str) -> List[str]:
    """Strings in one argument that may name a file: the argument, an option value (--out=PATH) and,
    for git, every part after a colon (REV:PATH, :0:PATH, :(top)PATH). Bare names count for git because
    git treats them as pathspecs."""
    out = []
    value = arg
    if arg.startswith("-"):
        if "=" not in arg:
            return out
        value = arg.split("=", 1)[1]
        if not value:
            return out
    if _path_like(value) or exe == "git":
        out.append(value)
    if exe == "git" and "://" not in value:
        drive = len(value) > 1 and value[1] == ":"
        for i, ch in enumerate(value):
            if ch == ":" and not (drive and i == 1):
                tail = value[i + 1:]
                if tail.startswith("("):  # pathspec magic such as :(top)path
                    tail = tail.split(")", 1)[-1]
                if tail:
                    out.append(tail)
    return out


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
        if _protected_write(rel):
            return Decision(SYSTEM_CHANGE, APPROVAL, "This file defines the security rules or what runs at the next start", f"write_file {rel}", norm,
                            {"content": content})
        return Decision(WRITE_PROJECT, ALLOW, "Write inside the project", f"write_file {rel} ({norm['bytes']} bytes)", norm,
                        {"content": content})
    return Decision(DELETE, APPROVAL, "Deleting needs approval; the file is moved to _to_delete/, not erased",
                    f"delete_path {rel}", norm)


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
        if a in ("-m", "--message") and exe == "git":
            skip = True
            continue
        for cand in _path_candidates(a, exe):
            if exe == "python" and args[:1] == ["-m"] and a == args[1]:
                break
            try:
                resolve_in_roots(cand, roots, cwd=cwd)
            except PathDenied as exc:
                cls = SECRET_EXPORT if exc.code in ("SECRET_FILE", "DATA_DIR") else PERSONAL_FILES
                return _deny(cls, f"Argument {a!r}: {exc.message}", summary, norm)

    if exe == "git":
        return _classify_git(args, norm, summary, requested_by)
    for prefix in INSTALL_PREFIXES.get(exe, []):
        if _is_prefix(args, prefix):
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


def _classify_git(args, norm, summary, requested_by) -> Decision:
    if not args or args[0].startswith("-"):
        return Decision(SYSTEM_CHANGE, APPROVAL, "git global options are not allowed automatically", summary, norm)
    if any(a in GIT_FORBIDDEN_FLAGS or a.startswith(("--upload-pack", "--receive-pack", "--exec=", "--config=")) for a in args):
        return _deny(SYSTEM_CHANGE, "This git option can run arbitrary programs", summary, norm)
    sub = args[0]
    risk = _git_option_risk(args[1:])
    if risk == "deny":
        return _deny(SYSTEM_CHANGE, "This git option writes files, reads arbitrary files or runs helpers", summary, norm)
    if sub == "push":
        if any(a in FORCE_FLAGS or (a.startswith("+") and len(a) > 1) for a in args[1:]):
            return _deny(PUBLISH, "Force/delete pushes are never allowed", summary, norm)
        if any(a.split(":")[-1] in PROTECTED_BRANCHES for a in args[1:] if not a.startswith("-")) and requested_by != "claude1":
            return _deny(PUBLISH, "Only claude1 may push main, and only with approval", summary, norm)
        return Decision(PUBLISH, APPROVAL, "Publishing needs approval every time", summary, norm)
    if sub in GIT_DESTRUCTIVE or (sub == "branch" and any(a in ("-D", "-d", "--delete", "-m", "-M") for a in args)):
        return Decision(DELETE, APPROVAL, "Can discard work; needs approval each time", summary, norm)
    if sub in GIT_AUTO:
        if risk == "approval":
            return Decision(DELETE, APPROVAL, "Force / no-index / discard options need approval each time", summary, norm)
        if sub == "fetch" and any(not a.startswith("-") and not re.fullmatch(r"[A-Za-z0-9_.-]{1,40}", a) for a in args[1:]):
            return Decision(NETWORK, APPROVAL, "Fetching from a URL or path needs approval (only remote names are automatic)", summary, norm)
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
