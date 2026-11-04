"""ExecutionService: the single door for every machine action (docs/EXECUTION_SECURITY.md).

submit(): emergency-stop check -> classify -> deny / approval / run -> audit.
Statuses returned: OK, ERROR, KILLED, DENIED, APPROVAL_REQUIRED.
"""

import time
from pathlib import Path
from typing import Callable, Iterable, Optional

from ..engine import TaskEngine
from ..storage import Storage, StorageError
from .approvals import Approvals, mask
from .executor import ExecutionKilled, Executor
from .policy import (ALLOW, APPROVAL, DEFAULT_NETWORK_ALLOWLIST, DENY, INSTALL, classify, plain_package_install)

STOP_FILE_NAME = "EMERGENCY_STOP"  # also written by the Hub, so both systems share one stop switch


class EmergencyStop:
    """Backend stops when the Hub's stop file exists or the engine is paused."""

    def __init__(self, data_dir: Path, engine: TaskEngine, approvals: Approvals):
        self.file = Path(data_dir) / STOP_FILE_NAME
        self.engine = engine
        self.approvals = approvals

    def active(self) -> bool:
        return self.file.exists() or self.engine.is_paused()

    def trigger(self, reason: str = "manual") -> dict:
        self.file.parent.mkdir(parents=True, exist_ok=True)
        self.file.write_text(mask(reason, 200), encoding="utf-8")
        self.engine.set_paused(True)
        expired = self.approvals.expire_all_open()
        self.approvals.audit("system", "SYSTEM_CHANGE", "emergency stop", "STOP", reason)
        return {"emergency_stop": True, "approvals_expired": expired}

    def clear(self) -> dict:
        if self.file.exists():
            self.file.unlink()
        self.engine.set_paused(False)
        self.approvals.audit("user", "SYSTEM_CHANGE", "emergency stop lifted", "RESUME")
        return {"emergency_stop": False}


class ExecutionService:
    def __init__(self, storage: Storage, roots: Iterable[Path], executor: Executor, stop: EmergencyStop,
                 approvals: Optional[Approvals] = None, network_allowlist=DEFAULT_NETWORK_ALLOWLIST,
                 auto_run_code: bool = False):
        self.storage = storage
        self.roots = [Path(r) for r in roots]
        self.executor = executor
        self.stop = stop
        self.approvals = approvals or stop.approvals
        self.network_allowlist = tuple(network_allowlist)
        self.auto_run_code = auto_run_code

    def submit(self, agent: str, action: dict, approval_id: Optional[int] = None) -> dict:
        agent = (agent or "").strip()
        if not agent or len(agent) > 40:
            raise StorageError("BAD_AGENT", "An agent name (1-40 characters) is required")
        if self.stop.active():
            self.approvals.audit(agent, "SYSTEM_CHANGE", str(action.get("type", "?")) if isinstance(action, dict) else "?",
                                 "DENIED", "emergency stop active")
            raise StorageError("EMERGENCY_STOP", "Emergency stop is active; only the user can lift it")

        decision = classify(action, self.roots, self.network_allowlist, requested_by=agent, auto_run_code=self.auto_run_code)
        base = {"class": decision.action_class, "summary": decision.summary}

        if decision.verdict == DENY:
            self.approvals.audit(agent, decision.action_class, decision.summary, "DENIED", decision.reason)
            return {**base, "status": "DENIED", "reason": decision.reason}

        used_approval = None
        if decision.verdict == APPROVAL:
            if (decision.action_class == INSTALL and plain_package_install(decision.normalized)
                    and self.approvals.previously_approved(decision.action_hash)):
                pass  # same package/version/project was approved before (spec 9.2)
            elif approval_id is not None:
                used_approval = self.approvals.consume(approval_id, agent, decision.action_hash)["id"]
            else:
                req = self.approvals.request(agent, decision.action_class, _reviewable(decision), decision.action_hash,
                                             decision.summary, decision.reason)
                self.approvals.audit(agent, decision.action_class, decision.summary, "APPROVAL_REQUESTED",
                                     decision.reason, approval_id=req["id"])
                return {**base, "status": "APPROVAL_REQUIRED", "approval_id": req["id"], "reason": decision.reason,
                        "expires_at": req["expires_at"]}

        return self._execute(agent, decision, base, used_approval)

    def _execute(self, agent, decision, base, approval_id) -> dict:
        started = time.monotonic()
        try:
            result = self.executor.run(decision.exec_action, self.stop.active)
            status, detail = "OK", ""
        except ExecutionKilled as exc:
            result, status, detail = None, "KILLED", str(exc)
        except Exception as exc:  # an executor failure must never crash the service
            result, status, detail = None, "ERROR", f"{type(exc).__name__}: {exc}"
        ms = int((time.monotonic() - started) * 1000)
        self.approvals.audit(agent, decision.action_class, decision.summary, status, detail, approval_id, ms)
        out = {**base, "status": status, "duration_ms": ms}
        if approval_id:
            out["approval_id"] = approval_id
        if status == "OK":
            out["result"] = _mask_result(result)
        else:
            out["error"] = mask(detail)
        return out


PREVIEW_CHARS = 6000


def _reviewable(decision) -> dict:
    """What the approval screen shows. A file write is approved by the hash of its content, so the user must be able
    to read that content: a preview is stored with the request (it is not part of the hash and never executed)."""
    shown = dict(decision.normalized)
    content = decision.payload.get("content") if decision.payload else None
    if isinstance(content, str):
        shown["content_preview"] = content[:PREVIEW_CHARS]
        if len(content) > PREVIEW_CHARS:
            shown["content_preview_truncated"] = len(content) - PREVIEW_CHARS
    return shown


def _mask_result(result):
    if isinstance(result, dict):
        return {k: (mask(v, 1_000_000) if isinstance(v, str) else v) for k, v in result.items()}
    return result
