"""Scan git-tracked files for things that must never be committed. Exit 1 when something is found.

    python scripts/scan_secrets.py            # tracked files in the working tree
    python scripts/scan_secrets.py --history  # every added line in the whole git history (slower)

Test files may contain obviously fake secrets (they test the masking code), so tests/ folders are skipped
for content patterns; sensitive FILE NAMES are flagged everywhere.
"""

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

CONTENT_PATTERNS = {
    "OpenAI-style key": re.compile(r"sk-[A-Za-z0-9_-]{20,}"),
    "GitHub token": re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,}"),
    "AWS access key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "Google API key": re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b"),
    "Slack token": re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}"),
    "Private key block": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    "Hard-coded secret assignment": re.compile(
        r"(?i)\b(?:api[_-]?key|secret|password|token)\b\s*[:=]\s*['\"][A-Za-z0-9_\-+/=]{16,}['\"]"),
    "Personal e-mail": re.compile(r"[A-Za-z0-9._%+-]+@(?:gmail|googlemail|outlook|hotmail|yahoo|icloud)\.com"),
}
SENSITIVE_NAMES = re.compile(r"(?i)(^|/)(\.env[^/]*|[^/]*\.env|tokens?\.json|backend_tokens?\.(json|txt)|ai_accounts\.json|"
                             r"llm\.env|[^/]*\.pem|[^/]*\.key|[^/]*\.p12|[^/]*\.db|[^/]*\.bundle|id_rsa[^/]*)$")
SKIP_DIRS = ("tests/", "test/")
SKIP_FILES = {"scripts/scan_secrets.py", "backend/tests/test_scan_secrets.py"}
BINARY = re.compile(r"\.(png|jpg|jpeg|gif|ico|woff2?|ttf|zip|jar|apk)$", re.I)


def tracked_files(root: Path):
    out = subprocess.run(["git", "-C", str(root), "ls-files", "-z"], capture_output=True, text=True, check=True).stdout
    return [p for p in out.split("\0") if p]


def scan_text(path: str, text: str):
    findings = []
    for number, line in enumerate(text.splitlines(), 1):
        for label, pattern in CONTENT_PATTERNS.items():
            if pattern.search(line):
                findings.append((path, number, label))
    return findings


def scan_tree(root: Path):
    findings = []
    for path in tracked_files(root):
        if SENSITIVE_NAMES.search(path):
            findings.append((path, 0, "Sensitive file name is tracked"))
            continue
        if path in SKIP_FILES or BINARY.search(path) or any(f"/{d}" in f"/{path}" for d in SKIP_DIRS):
            continue
        try:
            text = (root / path).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        findings += scan_text(path, text)
    return findings


def scan_history(root: Path):
    findings, current = [], ""
    proc = subprocess.run(["git", "-C", str(root), "log", "--all", "-p", "--no-color", "--pretty=format:@@COMMIT %h"],
                          capture_output=True, text=True, errors="replace", check=True)
    for line in proc.stdout.splitlines():
        if line.startswith("@@COMMIT "):
            current = line.split()[1]
        elif line.startswith("+++ b/"):
            current_file = line[6:]
            current = f"{current}:{current_file}"
        elif line.startswith("+") and not line.startswith("+++"):
            file_part = current.split(":", 1)[-1]
            if file_part in SKIP_FILES or any(f"/{d}" in f"/{file_part}" for d in SKIP_DIRS) or BINARY.search(file_part):
                continue
            for label, pattern in CONTENT_PATTERNS.items():
                if pattern.search(line):
                    findings.append((current, 0, label))
    return findings


def main(argv=None) -> int:
    args = sys.argv[1:] if argv is None else argv
    findings = scan_history(ROOT) if "--history" in args else scan_tree(ROOT)
    for path, number, label in findings:
        print(f"FOUND {label}: {path}" + (f":{number}" if number else ""))
    print(f"{len(findings)} finding(s)")
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
