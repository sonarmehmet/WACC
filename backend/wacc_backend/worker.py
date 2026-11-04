"""Background job runner. Built-in job kinds:

  ai.complete  payload {prompt, system?, prefer?, provider?, agent?, max_tokens?} -> orchestrator result
               (agent: an agent account linked to an AI account uses that account when no provider is given)
  exec.run     payload {action, approval_id?}                            -> ExecutionService result

exec.run goes through the same policy, approval, audit and emergency-stop checks as POST /exec, so a job
can never do more than a direct request could. When an action needs approval the job fails (no retry)
and names the approval id: approve it, then enqueue the job again with that approval_id.
The engine's pause flag and the shared EMERGENCY_STOP both stop the worker from starting new work.
"""

import threading
from typing import Optional

from .engine import PermanentJobError, TaskEngine
from .security import registry_agents
from .storage import StorageError


def register_builtin_handlers(engine: TaskEngine, orchestrator, execution, data_dir=None) -> None:
    def ai_complete(job: dict):
        p = job.get("payload") or {}
        if not isinstance(p, dict) or not isinstance(p.get("prompt"), str):
            raise PermanentJobError("ai.complete needs a payload with a string 'prompt'")
        provider = p.get("provider")
        if not provider and data_dir and isinstance(p.get("agent"), str):
            # an agent account linked to an AI account uses that account (if it is still on)
            for a in registry_agents(data_dir):
                if a["name"] == p["agent"] and a["enabled"] and a["provider"]:
                    provider = a["provider"]
        try:
            return orchestrator.complete(p["prompt"], p.get("system"), p.get("prefer", "auto"),
                                         provider, int(p.get("max_tokens", 1024)))
        except (ValueError, TypeError) as exc:
            raise PermanentJobError(f"Bad ai.complete payload: {exc}")
        # OrchestratorError / provider failures propagate: the engine retries them with backoff

    def exec_run(job: dict):
        p = job.get("payload") or {}
        if not isinstance(p, dict) or not isinstance(p.get("action"), dict):
            raise PermanentJobError("exec.run needs a payload with an 'action' object")
        agent = p.get("_agent") if isinstance(p.get("_agent"), str) and p.get("_agent") else "worker"  # set by POST /jobs
        try:
            result = execution.submit(agent, p["action"], p.get("approval_id"))
        except StorageError as exc:  # bad/used approval, emergency stop: retrying cannot help
            raise PermanentJobError(f"{exc.code}: {exc.message}")
        status = result.get("status")
        if status == "APPROVAL_REQUIRED":
            raise PermanentJobError(
                f"Approval #{result.get('approval_id')} required. Approve it, then enqueue again with approval_id.")
        if status == "DENIED":
            raise PermanentJobError(f"Denied: {result.get('reason')}")
        if status in ("ERROR", "KILLED"):
            raise RuntimeError(f"{status}: {result.get('reason') or result.get('error') or ''}".strip())
        return result

    engine.register_handler("ai.complete", ai_complete)
    engine.register_handler("exec.run", exec_run)


class Worker:
    def __init__(self, engine: TaskEngine, name: str = "worker-1", poll_seconds: float = 2.0):
        self.engine, self.name, self.poll_seconds = engine, name, poll_seconds
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._loop, name=self.name, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                ran = self.engine.run_once(self.name)
            except Exception:  # storage hiccup: keep the loop alive
                ran = None
            if ran is None:
                self._stop.wait(self.poll_seconds)
