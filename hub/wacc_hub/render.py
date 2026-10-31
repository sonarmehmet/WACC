"""Render human-readable tasks/*.md summaries from the hub database."""

from pathlib import Path

from .models import ACTIVE_TASK_STATUSES

TASKS_DIR = Path(__file__).resolve().parents[2] / "tasks"
HEADER = "<!-- Auto-generated from the Communication Hub database. Do not edit by hand. -->\n"


def _task_block(t):
    lines = [
        f"### {t['task_id']} — {t['title']}",
        f"- Owner: {t['owner'] or '-'} | Status: {t['status']} | Priority: {t['priority']}",
        f"- Branch: {t['branch'] or '-'} | Commit: {t['commit_hash'] or '-'}",
        f"- Files: {', '.join(t['affected_files']) or '-'}",
        f"- Depends on: {', '.join(t['dependencies']) or '-'}",
    ]
    if t["description"]:
        lines.append(f"- Description: {t['description']}")
    if t["acceptance"]:
        lines.append(f"- Acceptance: {t['acceptance']}")
    if t["test_criteria"]:
        lines.append(f"- Test criteria: {t['test_criteria']}")
    if t["note"]:
        lines.append(f"- Note: {t['note']}")
    return "\n".join(lines)


def _task_file(title, tasks):
    body = "\n\n".join(_task_block(t) for t in tasks) or "_Empty._"
    return f"{HEADER}# {title}\n\n{body}\n"


def render_all(hub, tasks_dir=None) -> list:
    out = Path(tasks_dir) if tasks_dir else TASKS_DIR
    out.mkdir(parents=True, exist_ok=True)
    tasks = hub.list_tasks()
    files = {
        "PROJECT_BACKLOG.md": _task_file("Project Backlog", [t for t in tasks if t["status"] == "BACKLOG"]),
        "ACTIVE_TASKS.md": _task_file("Active Tasks", [t for t in tasks if t["status"] in ACTIVE_TASK_STATUSES]),
        "COMPLETED_TASKS.md": _task_file("Completed Tasks", [t for t in tasks if t["status"] == "COMPLETED"]),
        "BLOCKED_TASKS.md": _task_file("Blocked Tasks", [t for t in tasks if t["status"] == "BLOCKED"]),
    }

    integ = hub.query("SELECT * FROM messages WHERE message_type IN ('INTEGRATION_REQUEST','INTEGRATION_RESULT',"
                      "'CODE_READY','REVIEW_RESULT') ORDER BY timestamp")
    lines = [f"- {m['timestamp']} {m['sender']} -> {m['receiver']} [{m['message_type']}] {m['subject']}"
             f"{' (' + m['related_commit'] + ')' if m['related_commit'] else ''}" for m in integ]
    files["INTEGRATION_LOG.md"] = f"{HEADER}# Integration Log\n\n" + ("\n".join(lines) or "_Empty._") + "\n"

    decs = hub.list_decisions()
    blocks = [f"### D-{d['decision_id']:04d} — {d['title']}{' (CRITICAL)' if d['critical'] else ''}\n"
              f"- By: {d['decided_by']} | {d['created_at']} | Task: {d['task_id'] or '-'}\n"
              f"- Decision: {d['decision']}\n- Rationale: {d['rationale'] or '-'}" for d in decs]
    files["TEAM_DECISIONS.md"] = f"{HEADER}# Team Decisions\n\n" + ("\n\n".join(blocks) or "_Empty._") + "\n"

    rows = ["| Agent | Role | Online | Status | Task | Unread | Pending | Last commit | Last seen |",
            "|---|---|---|---|---|---|---|---|---|"]
    for a in hub.overview():
        rows.append(f"| {a['agent_id']} | {a['role']} | {'yes' if a['online'] else 'no'} | {a['status']} | "
                    f"{a['current_task'] or '-'} | {a['unread']} | {a['pending_responses']} | "
                    f"{a['last_commit'] or '-'} | {a['last_seen'] or '-'} |")
    files["AGENT_STATUS.md"] = f"{HEADER}# Agent Status\n\n" + "\n".join(rows) + "\n"

    written = []
    for name, text in files.items():
        (out / name).write_text(text, encoding="utf-8")
        written.append(name)
    return written
