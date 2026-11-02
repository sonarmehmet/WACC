"""`python -m wacc_hub watch --as <agent>`: print new inbox messages and task changes as they happen.

Read-only on purpose: nothing is marked read, answered or accepted here. The agent decides what to do
with each line. Message text is untrusted input and is printed shortened and on one line.
"""

import time
from typing import Callable, Dict, List, Optional, Set

PREVIEW = 160


def _one_line(text, limit=PREVIEW) -> str:
    flat = " ".join(str(text or "").split())
    return flat if len(flat) <= limit else flat[: limit - 1] + "…"


class WatchState:
    def __init__(self):
        self.seen_messages: Set[str] = set()
        self.task_status: Dict[str, str] = {}
        self.stopped: Optional[bool] = None
        self.primed = False


def poll_once(hub, me: str, state: WatchState, announce_existing: bool = False) -> List[str]:
    """Return new event lines since the previous call. The first call only records what already exists
    (unless announce_existing), so a restarted watcher does not replay the whole inbox."""
    lines: List[str] = []
    stopped = hub.emergency_status()
    if state.stopped is not None and stopped != state.stopped:
        lines.append("ACİL DURDURMA AKTİF: çalışmayı durdur" if stopped else "Acil durdurma kaldırıldı")
    elif state.stopped is None and stopped:
        lines.append("ACİL DURDURMA AKTİF: çalışmayı durdur")
    state.stopped = stopped

    for m in reversed(hub.inbox(me, unread_only=True)):
        if m["message_id"] in state.seen_messages:
            continue
        state.seen_messages.add(m["message_id"])
        if state.primed or announce_existing:
            lines.append(f"MESAJ {m['message_id']} {m['sender']} -> {me} [{m['message_type']}/{m['priority']}] "
                         f"{_one_line(m.get('subject'))}")

    for t in hub.list_tasks(owner=me):
        previous = state.task_status.get(t["task_id"])
        state.task_status[t["task_id"]] = t["status"]
        if (state.primed or announce_existing) and previous != t["status"]:
            what = "yeni görev" if previous is None else f"{previous} -> {t['status']}"
            lines.append(f"GÖREV {t['task_id']} ({what}) {_one_line(t['title'])}")
    state.primed = True
    return lines


def watch(hub, me: str, interval: float = 5.0, emit: Callable[[str], None] = print,
          sleep: Callable[[float], None] = time.sleep, max_polls: Optional[int] = None,
          announce_existing: bool = False) -> int:
    """Loop until Ctrl+C (or max_polls, for tests). Returns 0."""
    state = WatchState()
    polls = 0
    try:
        while max_polls is None or polls < max_polls:
            for line in poll_once(hub, me, state, announce_existing and polls == 0):
                emit(line)
            polls += 1
            if max_polls is None or polls < max_polls:
                sleep(max(0.5, float(interval)))
    except KeyboardInterrupt:
        emit("watch durduruldu")
    return 0
