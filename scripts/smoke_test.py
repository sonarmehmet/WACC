"""First-run smoke test (stdlib only). Run after start_wacc.bat is up.

Usage: python scripts/smoke_test.py
Checks the Hub (8765) and Backend (8800) answer, tokens work and auth is enforced.
"""
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HUB, BACKEND = "http://127.0.0.1:8765", "http://127.0.0.1:8800"
results = []


def call(url, token=None, method="GET", body=None):
    req = urllib.request.Request(url, method=method)
    if token:
        req.add_header("X-WACC-Token", token)
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, data=data, timeout=5) as r:
            return r.status, json.loads(r.read() or b"null")
    except urllib.error.HTTPError as e:
        return e.code, None
    except Exception as e:  # connection refused etc.
        return 0, str(e)


def check(name, ok, detail=""):
    results.append(ok)
    print(("PASS " if ok else "FAIL ") + name + (f"  [{detail}]" if detail and not ok else ""))


def main():
    s, _ = call(HUB + "/health")
    check("hub /health", s == 200, s)
    s, _ = call(HUB + "/inbox")
    check("hub rejects missing token", s == 401, s)
    try:
        tokens = json.loads((ROOT / "data" / "tokens.json").read_text(encoding="utf-8"))
    except Exception as e:
        check("hub tokens.json readable", False, e)
        tokens = {}
    if tokens.get("claude1"):
        s, body = call(HUB + "/whoami", tokens["claude1"])
        check("hub token identifies claude1", s == 200 and body and body.get("agent") == "claude1", s)
        s, body = call(HUB + "/agents", tokens["claude1"])
        check("hub /agents lists 5 agents", s == 200 and isinstance(body, list) and len(body) == 5, s)
        s, body = call(HUB + "/tasks", tokens["claude1"])
        check("hub has seeded tasks", s == 200 and isinstance(body, list) and len(body) >= 6, s)

    s, body = call(BACKEND + "/health")
    check("backend /health", s == 200, body)
    s, _ = call(BACKEND + "/projects")
    check("backend rejects missing token", s == 401, s)
    try:
        btoken = (ROOT / "data" / "backend_token.txt").read_text(encoding="utf-8").strip()
    except Exception as e:
        check("backend token readable", False, e)
        btoken = ""
    if btoken:
        s, _ = call(BACKEND + "/projects", btoken)
        check("backend /projects with token", s == 200, s)

    print(f"\n{sum(results)}/{len(results)} checks passed")
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
