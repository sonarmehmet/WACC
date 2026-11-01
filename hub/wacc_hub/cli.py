"""Command line interface: python -m wacc_hub <command>.

Agents running on the same machine use `--as <agent>` (local trust). Remote or mobile
clients must use the HTTP API with a per-agent token.
"""

import argparse
import json
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from . import db
from .auth import load_or_create_tokens
from .models import AGENTS, MESSAGE_TYPES, PRIORITIES
from .render import render_all
from .service import Hub, HubError

ROOT = Path(__file__).resolve().parents[2]


def _out(obj):
    print(json.dumps(obj, indent=2, ensure_ascii=False))


def _csv(value):
    return [v.strip() for v in value.split(",") if v.strip()] if value else []


def seed(hub: Hub):
    """Idempotent initial backlog assigned by claude1."""
    existing = {t["title"] for t in hub.list_tasks()}
    plan = [
        ("claude2", "Backend core: FastAPI app, auth, config, DB layer",
         "Create backend/ (FastAPI) with settings, SQLite storage, auth, health endpoint and a clean module layout.",
         ["backend/"], [], "Server starts with one command; /health responds; config via env, no secrets in code.",
         "pytest for config, db and health endpoints", "task/backend-core"),
        ("claude2", "Task Engine and Agent Manager",
         "Task Engine (queue, status, retries) and Agent Manager (register, start, stop agents) inside backend/.",
         ["backend/engine/", "backend/agents/"], ["T-0001"],
         "Tasks can be created, run and tracked; agents can be registered and listed via API.",
         "unit + API tests", "task/engine-agents"),
        ("claude2", "AI Orchestrator and Memory System",
         "Orchestrator routing requests to models (local + cloud, cost-aware) and a simple memory store.",
         ["backend/orchestrator/", "backend/memory/"], ["T-0001"],
         "Provider interface with a mock provider; memory read/write API; keys loaded from env only.",
         "unit tests with the mock provider", "task/orchestrator"),
        ("claude3", "Flutter app skeleton, API client and Agents screen",
         "Create mobile/ Flutter project: navigation, API client for the hub (token auth), Agents status screen "
         "and Agent chat screen (shared feed + send message + give task).",
         ["mobile/"], [], "App builds for Android; Agents screen shows status from /agents; chat shows /feed.",
         "flutter analyze, widget tests", "task/mobile-agents"),
        ("claude3", "Web panel: Agents and Agent Chat screens",
         "Create web/ panel (lightweight, no heavy framework needed) with the same Agents and chat views.",
         ["web/"], [], "Panel served locally; shows agents, feed, tasks; can post a message and a task.",
         "build check + API connection test", "task/web-panel"),
        ("claude1", "Environment check, start script, backup and integration",
         "scripts/check_env.ps1, start_wacc.bat, backup, docs and the integration/review of other branches.",
         ["scripts/", "start_wacc.bat", "docs/"], [], "One-click start works on Windows 10; backup creates DB copy + git bundle.",
         "script dry-run checks", "task/integration"),
        ("gemini", "Brand and visual assets: logo, app icon, palette",
         "Create assets/branding/: WACC logo (SVG + PNG), Android app icon set, color palette and a short style guide. "
         "Only assets/ is yours; do not touch code folders.",
         ["assets/"], [], "Logo, icon set and palette committed under assets/branding with a style guide.",
         "files open correctly; icon sizes match Android requirements", "task/assets"),
        ("claude1", "Windows Execution Backend security spec",
         "Write docs/EXECUTION_SECURITY.md: which actions the Windows execution backend may perform, what needs "
         "user approval, allowlists, audit logging and the emergency stop contract.",
         ["docs/EXECUTION_SECURITY.md"], [], "Spec reviewed by the user; every risky action class has an approval rule.",
         "review checklist", "task/exec-spec"),
        (None, "Windows Execution Backend implementation",
         "Implement the execution backend in backend/wacc_backend/execution/ strictly following docs/EXECUTION_SECURITY.md.",
         ["backend/wacc_backend/execution/"], ["T-0002", "T-0008"], "All actions go through the approval flow and audit log; emergency stop halts execution.",
         "unit tests with a fake executor", "task/execution"),
    ]
    created = []
    for owner, title, desc, files, deps, acc, tc, branch in plan:
        if title in existing:
            continue
        created.append(hub.create_task("claude1", title, desc, owner=owner, affected_files=files,
                                       dependencies=deps, acceptance=acc, test_criteria=tc, branch=branch,
                                       idempotency_key=f"seed:{title}")["task_id"])
    return created


def backup(hub: Hub):
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = ROOT / "backups"
    dest.mkdir(exist_ok=True)
    import sqlite3
    src = sqlite3.connect(str(hub.db_path))
    dst = sqlite3.connect(str(dest / f"hub_{stamp}.db"))
    with dst:
        src.backup(dst)
    src.close()
    dst.close()
    result = {"db": f"backups/hub_{stamp}.db"}
    if shutil.which("git") and (ROOT / ".git").exists():
        bundle = dest / f"wacc_{stamp}.bundle"
        proc = subprocess.run(["git", "-C", str(ROOT), "bundle", "create", str(bundle), "--all"],
                              capture_output=True, text=True)
        if proc.returncode == 0:
            result["git_bundle"] = f"backups/{bundle.name}"
    return result


def build_parser():
    p = argparse.ArgumentParser(prog="wacc_hub")
    p.add_argument("--db", help="database path (default: data/hub.db)")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("init", help="create database, tokens and tasks/*.md")
    sub.add_parser("seed", help="create the initial backlog (idempotent)")
    sub.add_parser("render", help="regenerate tasks/*.md")
    sub.add_parser("backup", help="DB copy + git bundle into backups/")
    sub.add_parser("retry", help="redeliver queued messages and alert on expired locks")
    sub.add_parser("agents", help="show agent overview")

    s = sub.add_parser("serve", help="start the HTTP API (127.0.0.1 only unless --host given)")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8765)

    s = sub.add_parser("session-start"); s.add_argument("--as", dest="me", required=True)
    s = sub.add_parser("session-end"); s.add_argument("--as", dest="me", required=True)
    s.add_argument("--notes", required=True); s.add_argument("--commit"); s.add_argument("--branch")

    s = sub.add_parser("send"); s.add_argument("--as", dest="me", required=True)
    s.add_argument("--to", required=True); s.add_argument("--type", required=True, choices=MESSAGE_TYPES)
    s.add_argument("--subject", required=True); s.add_argument("--content", default="")
    s.add_argument("--task"); s.add_argument("--conv"); s.add_argument("--priority", default="NORMAL", choices=PRIORITIES)
    s.add_argument("--files"); s.add_argument("--commit"); s.add_argument("--reply-to")
    s.add_argument("--needs-response", action="store_true")

    s = sub.add_parser("inbox"); s.add_argument("--as", dest="me", required=True); s.add_argument("--unread", action="store_true")
    s = sub.add_parser("read"); s.add_argument("--as", dest="me", required=True); s.add_argument("id")
    s = sub.add_parser("feed"); s.add_argument("--limit", type=int, default=50)

    s = sub.add_parser("tasks"); s.add_argument("--owner"); s.add_argument("--status")
    s = sub.add_parser("assign"); s.add_argument("--as", dest="me", default="claude1")
    s.add_argument("--to", required=True); s.add_argument("--title", required=True)
    s.add_argument("--desc", default=""); s.add_argument("--files"); s.add_argument("--deps")
    s.add_argument("--accept", default=""); s.add_argument("--tests", default="")
    s.add_argument("--priority", default="NORMAL", choices=PRIORITIES); s.add_argument("--branch")
    s = sub.add_parser("accept"); s.add_argument("--as", dest="me", required=True); s.add_argument("task")
    s = sub.add_parser("status"); s.add_argument("--as", dest="me", required=True)
    s.add_argument("task"); s.add_argument("state"); s.add_argument("--commit"); s.add_argument("--note")

    s = sub.add_parser("lock"); s.add_argument("--as", dest="me", required=True); s.add_argument("path")
    s.add_argument("--task"); s.add_argument("--ttl", type=int, default=900); s.add_argument("--takeover", action="store_true")
    s = sub.add_parser("unlock"); s.add_argument("--as", dest="me", required=True)
    s.add_argument("--path"); s.add_argument("--task")
    s = sub.add_parser("locks")
    s = sub.add_parser("heartbeat"); s.add_argument("--as", dest="me", required=True)
    s.add_argument("--status"); s.add_argument("--task"); s.add_argument("--commit")

    s = sub.add_parser("decide"); s.add_argument("--as", dest="me", required=True)
    s.add_argument("--title", required=True); s.add_argument("--decision", required=True)
    s.add_argument("--why", default=""); s.add_argument("--task"); s.add_argument("--conv"); s.add_argument("--critical", action="store_true")
    s = sub.add_parser("checkpoint"); s.add_argument("--as", dest="me", required=True)
    s.add_argument("--notes", required=True); s.add_argument("--task"); s.add_argument("--branch"); s.add_argument("--commit")
    s = sub.add_parser("handoff"); s.add_argument("--as", dest="me", required=True)
    s.add_argument("--to", required=True); s.add_argument("--task", required=True)
    s.add_argument("--notes", required=True); s.add_argument("--commit"); s.add_argument("--branch")

    s = sub.add_parser("stop"); s.add_argument("--as", dest="me", default="user"); s.add_argument("--reason", default="manual stop")
    sub.add_parser("resume")
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    hub = Hub(args.db) if args.db else Hub()
    try:
        c = args.cmd
        if c == "init":
            load_or_create_tokens()
            print("Hub ready. Rendered:", ", ".join(render_all(hub)))
        elif c == "seed":
            _out({"created": seed(hub)}); render_all(hub)
        elif c == "render":
            _out(render_all(hub))
        elif c == "backup":
            _out(backup(hub))
        elif c == "retry":
            _out({**hub.retry_undelivered(), "lock_alerts": hub.alert_expired_locks()})
        elif c == "agents":
            _out(hub.overview())
        elif c == "serve":
            import uvicorn
            from .api import create_app
            if args.host not in ("127.0.0.1", "localhost"):
                print("WARNING: binding beyond localhost. Use a firewall/VPN; tokens are the only protection.", file=sys.stderr)
            uvicorn.run(create_app(hub), host=args.host, port=args.port, log_level="info")
        elif c == "session-start":
            _out(hub.session_start(args.me))
        elif c == "session-end":
            _out(hub.session_end(args.me, args.notes, args.commit, args.branch))
        elif c == "send":
            _out(hub.send_message(args.me, args.to, args.type, args.subject, args.content, task_id=args.task,
                                  conversation_id=args.conv, priority=args.priority, related_files=_csv(args.files),
                                  related_commit=args.commit, response_required=args.needs_response,
                                  in_reply_to=args.reply_to))
        elif c == "inbox":
            _out(hub.inbox(args.me, unread_only=args.unread))
        elif c == "read":
            _out(hub.mark_read(args.me, args.id))
        elif c == "feed":
            _out(hub.feed(args.limit))
        elif c == "tasks":
            _out(hub.list_tasks(args.owner, args.status))
        elif c == "assign":
            _out(hub.create_task(args.me, args.title, args.desc, owner=args.to, affected_files=_csv(args.files),
                                 dependencies=_csv(args.deps), acceptance=args.accept, test_criteria=args.tests,
                                 priority=args.priority, branch=args.branch))
            render_all(hub)
        elif c == "accept":
            _out(hub.accept_task(args.me, args.task)); render_all(hub)
        elif c == "status":
            _out(hub.set_task_status(args.me, args.task, args.state, args.commit, args.note)); render_all(hub)
        elif c == "lock":
            _out(hub.acquire_lock(args.me, args.path, args.task, args.ttl, args.takeover))
        elif c == "unlock":
            _out({"released": hub.release_lock(args.me, args.path, args.task)})
        elif c == "locks":
            _out(hub.list_locks())
        elif c == "heartbeat":
            _out(hub.heartbeat(args.me, args.status, args.task, args.commit))
        elif c == "decide":
            _out(hub.record_decision(args.me, args.title, args.decision, args.why, args.task, args.conv, args.critical))
            render_all(hub)
        elif c == "checkpoint":
            _out(hub.add_checkpoint(args.me, args.notes, args.task, args.branch, args.commit))
        elif c == "handoff":
            _out(hub.handoff(args.me, args.to, args.task, args.notes, args.commit, args.branch)); render_all(hub)
        elif c == "stop":
            hub.emergency_stop(args.me, args.reason); print("EMERGENCY STOP active.")
        elif c == "resume":
            hub.resume("user"); print("Emergency stop lifted.")
        return 0
    except HubError as exc:
        print(json.dumps({"error": exc.code, "message": exc.message, "detail": exc.detail}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
