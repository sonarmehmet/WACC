"""FastAPI application. Every route except /health requires the X-WACC-Token header."""

import os
from typing import List, Optional

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel

from . import __version__
from .agents import AgentManager
from .engine import TaskEngine
from .memory import Memory
from .execution.approvals import Approvals
from .execution.executor import Executor, RealExecutor
from .execution.service import EmergencyStop, ExecutionService
from .accounts import AccountStore, public_view, to_provider
from .orchestrator import Orchestrator, OrchestratorError, Provider, build_providers
from .config import Settings, load_settings
from .security import get_or_create_agent_tokens, get_or_create_token, get_or_create_user_token, token_matches
from .storage import Storage, StorageError

STATUS_MAP = {"NOT_FOUND": 404, "DUPLICATE": 409, "FORBIDDEN": 403, "BAD_STATE": 409,
              "PROJECT_ARCHIVED": 409, "DISABLED": 409, "BUDGET_EXCEEDED": 429, "EMERGENCY_STOP": 423,
              "NOT_APPROVED": 403, "HASH_MISMATCH": 403,
              "NO_PROVIDER": 503, "ALL_FAILED": 502, "NOT_REMOVABLE": 409, "TOO_MANY": 409}


class ProjectIn(BaseModel):
    name: str
    description: str = ""


class ProjectPatch(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    status: Optional[str] = None


class JobIn(BaseModel):
    kind: str
    title: str
    payload: dict = {}
    project_id: Optional[int] = None
    priority: int = 5
    max_attempts: int = 3
    delay_seconds: int = 0


class ClaimIn(BaseModel):
    worker: str
    kinds: Optional[List[str]] = None


class CompleteIn(BaseModel):
    worker: str
    result: Optional[dict] = None


class FailIn(BaseModel):
    worker: str
    error: str
    retry: bool = True


class AgentIn(BaseModel):
    name: str
    role: str
    capabilities: List[str] = []


class HeartbeatIn(BaseModel):
    status: Optional[str] = None
    current_job: Optional[int] = None


class EnabledIn(BaseModel):
    enabled: bool


class CompleteRequest(BaseModel):
    prompt: str
    system: Optional[str] = None
    prefer: str = "auto"
    provider: Optional[str] = None
    max_tokens: int = 1024


class ExecIn(BaseModel):
    agent: str
    action: dict
    approval_id: Optional[int] = None


class StopIn(BaseModel):
    reason: str = "manual stop"


class BudgetIn(BaseModel):
    usd: float


class AccountIn(BaseModel):
    name: str
    kind: str
    base_url: str
    model: str
    api_key: Optional[str] = None
    price_in_per_1k: Optional[float] = None
    price_out_per_1k: Optional[float] = None
    enabled: bool = True


class MemoryIn(BaseModel):
    content: str
    tags: List[str] = []
    project_id: Optional[int] = None
    source: str = ""


def create_app(settings: Optional[Settings] = None, storage: Optional[Storage] = None,
               token: Optional[str] = None, providers: Optional[List[Provider]] = None,
               executor: Optional[Executor] = None, user_token: Optional[str] = None,
               agent_tokens: Optional[dict] = None) -> FastAPI:
    settings = settings or load_settings()
    storage = storage or Storage(settings.db_path)
    engine = TaskEngine(storage)
    agents = AgentManager(storage)
    orchestrator = Orchestrator(storage, providers if providers is not None else build_providers(os.environ))
    memory = Memory(storage)
    account_store = AccountStore(settings.data_dir / "ai_accounts.json")
    for acc in account_store.load():
        try:
            orchestrator.add_account(to_provider(acc), acc["enabled"])
        except (ValueError, StorageError):
            pass  # a stale or conflicting entry must not stop the backend from starting
    expected = token or get_or_create_token(settings)
    user_expected = user_token or get_or_create_user_token(settings)
    agent_token_map = agent_tokens if agent_tokens is not None else get_or_create_agent_tokens(settings)
    approvals = Approvals(storage)
    stop = EmergencyStop(settings.data_dir, engine, approvals)
    execution = ExecutionService(storage, settings.exec_roots, executor or RealExecutor(settings.exec_roots), stop, approvals,
                                auto_run_code=settings.exec_auto_code)
    app = FastAPI(title="WACC Backend", version=__version__)
    app.state.engine, app.state.orchestrator, app.state.execution = engine, orchestrator, execution

    def caller(x_wacc_token: str = Header(default="")) -> str:
        """Who is calling: 'user' (the human), an agent name (own token), or 'shared' (legacy read token)."""
        if token_matches(user_expected, x_wacc_token):
            return "user"
        for name, tok in agent_token_map.items():
            if token_matches(tok, x_wacc_token):
                return name
        if token_matches(expected, x_wacc_token):
            return "shared"
        raise HTTPException(status_code=401, detail="Invalid or missing X-WACC-Token")

    def auth(who: str = Depends(caller)) -> str:
        """Role: 'user' (human, can approve) or 'agent'."""
        return "user" if who == "user" else "agent"

    def acting_agent(who: str, claimed: str) -> str:
        """The name an action is attributed to. Agents may only act as themselves."""
        if who == "user":
            return claimed
        if who == "shared":
            raise HTTPException(status_code=403, detail={"code": "FORBIDDEN", "message":
                                "The shared token is read-only here; use your own agent token"})
        if claimed != who:
            raise HTTPException(status_code=403, detail={"code": "FORBIDDEN", "message":
                                f"This token belongs to {who}; it cannot act as {claimed!r}"})
        return who

    def user_only(role: str = Depends(auth)) -> str:
        if role != "user":
            raise HTTPException(status_code=403, detail={"code": "FORBIDDEN", "message": "Only the user token may do this"})
        return role

    def run(fn, *args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except StorageError as exc:
            raise HTTPException(status_code=STATUS_MAP.get(exc.code, 400),
                                detail={"code": exc.code, "message": exc.message})

    @app.get("/health")
    def health():
        return {"ok": True, "version": __version__, "schema_version": storage.schema_version()}

    @app.get("/projects", dependencies=[Depends(auth)])
    def list_projects(include_archived: bool = False):
        return storage.list_projects(include_archived)

    @app.post("/projects", status_code=201, dependencies=[Depends(auth)])
    def create_project(body: ProjectIn):
        return run(storage.create_project, body.name, body.description)

    @app.get("/projects/{project_id}", dependencies=[Depends(auth)])
    def get_project(project_id: int):
        project = storage.get_project(project_id)
        if not project:
            raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Project not found"})
        return project

    @app.patch("/projects/{project_id}", dependencies=[Depends(auth)])
    def patch_project(project_id: int, body: ProjectPatch):
        return run(storage.update_project, project_id, body.name, body.description, body.status)

    @app.post("/projects/{project_id}/archive", dependencies=[Depends(auth)])
    def archive_project(project_id: int):
        return run(storage.archive_project, project_id)

    # ------------------------------------------------------------- task engine
    @app.post("/jobs", status_code=201, dependencies=[Depends(auth)])
    def enqueue(body: JobIn):
        return run(engine.enqueue, body.kind, body.title, body.payload, body.project_id,
                   body.priority, body.max_attempts, body.delay_seconds)

    @app.get("/jobs", dependencies=[Depends(auth)])
    def list_jobs(status: Optional[str] = None, project_id: Optional[int] = None, limit: int = 100):
        return run(engine.list, status, project_id, limit)

    @app.get("/jobs/summary", dependencies=[Depends(auth)])
    def job_summary():
        return {"counts": engine.counts(), "paused": engine.is_paused()}

    @app.post("/jobs/claim", dependencies=[Depends(auth)])
    def claim(body: ClaimIn):
        return {"job": run(engine.claim_next, body.worker, body.kinds)}

    @app.get("/jobs/{job_id}", dependencies=[Depends(auth)])
    def get_job(job_id: int):
        job = engine.get(job_id)
        if not job:
            raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Job not found"})
        return job

    @app.post("/jobs/{job_id}/complete", dependencies=[Depends(auth)])
    def complete(job_id: int, body: CompleteIn):
        return run(engine.complete, job_id, body.worker, body.result)

    @app.post("/jobs/{job_id}/fail", dependencies=[Depends(auth)])
    def fail(job_id: int, body: FailIn):
        return run(engine.fail, job_id, body.worker, body.error, body.retry)

    @app.post("/jobs/{job_id}/cancel", dependencies=[Depends(auth)])
    def cancel(job_id: int):
        return run(engine.cancel, job_id)

    @app.post("/engine/pause", dependencies=[Depends(auth)])
    def pause():
        engine.set_paused(True)
        return {"paused": True}

    @app.post("/engine/resume", dependencies=[Depends(auth)])
    def resume():
        engine.set_paused(False)
        return {"paused": False}

    # ----------------------------------------------------------- agent manager
    @app.get("/agents", dependencies=[Depends(auth)])
    def list_agents():
        return agents.list()

    @app.post("/agents", status_code=201, dependencies=[Depends(auth)])
    def register_agent(body: AgentIn):
        return run(agents.register, body.name, body.role, body.capabilities)

    @app.post("/agents/{name}/heartbeat")
    def agent_heartbeat(name: str, body: HeartbeatIn, who: str = Depends(caller)):
        acting_agent(who, name)  # an agent can only report on itself
        return run(agents.heartbeat, name, body.status, body.current_job)

    @app.post("/agents/{name}/enabled", dependencies=[Depends(user_only)])  # switching agents on/off is the human's call
    def agent_enabled(name: str, body: EnabledIn):
        return run(agents.set_enabled, name, body.enabled)

    # ----------------------------------------------------------- AI orchestrator
    @app.post("/ai/complete", dependencies=[Depends(auth)])
    def ai_complete(body: CompleteRequest):
        return run(orchestrator.complete, body.prompt, body.system, body.prefer, body.provider, body.max_tokens)

    @app.get("/ai/providers", dependencies=[Depends(auth)])
    def ai_providers():
        return orchestrator.list_providers()

    # Accounts are the human's: only the user token adds, removes, switches or tests them (keys never come back).
    @app.post("/ai/accounts", status_code=201, dependencies=[Depends(user_only)])
    def ai_account_add(body: AccountIn):
        spec = {k: v for k, v in body.dict().items() if v is not None}
        def add():
            if spec.get("name", "").strip().lower() in orchestrator.providers:
                raise OrchestratorError("DUPLICATE", f"A provider named {spec['name']!r} already exists")
            acc = account_store.add(spec)
            orchestrator.add_account(to_provider(acc), acc["enabled"])
            return public_view(acc)
        return run(add)

    @app.delete("/ai/accounts/{name}", dependencies=[Depends(user_only)])
    def ai_account_remove(name: str):
        def remove():
            orchestrator.remove_account(name)
            return {"removed": account_store.remove(name)}
        return run(remove)

    @app.post("/ai/providers/{name}/enabled", dependencies=[Depends(user_only)])
    def ai_provider_enabled(name: str, body: EnabledIn):
        def switch():
            orchestrator.set_enabled(name, body.enabled)
            account_store.set_enabled(name, body.enabled)  # persisted for accounts; env providers reset on restart
            return {"name": name, "enabled": body.enabled}
        return run(switch)

    @app.post("/ai/providers/{name}/test", dependencies=[Depends(user_only)])
    def ai_provider_test(name: str):
        return run(orchestrator.test_provider, name)

    @app.get("/ai/usage", dependencies=[Depends(auth)])
    def ai_usage():
        return orchestrator.usage_summary()

    @app.post("/ai/budget", dependencies=[Depends(user_only)])  # spending limit is the human's decision
    def ai_budget(body: BudgetIn):
        return {"budget_usd": run(orchestrator.set_budget, body.usd)}

    # ------------------------------------------------------------------ memory
    @app.post("/memory", status_code=201, dependencies=[Depends(auth)])
    def memory_add(body: MemoryIn):
        return run(memory.add, body.content, body.tags, body.project_id, body.source)

    @app.get("/memory", dependencies=[Depends(auth)])
    def memory_list(project_id: Optional[int] = None, tag: Optional[str] = None, limit: int = 50):
        return memory.list(project_id, tag, limit)

    @app.get("/memory/search", dependencies=[Depends(auth)])
    def memory_search(q: str, project_id: Optional[int] = None, limit: int = 10):
        return run(memory.search, q, project_id, limit)

    @app.get("/memory/{memory_id}", dependencies=[Depends(auth)])
    def memory_get(memory_id: int):
        entry = memory.get(memory_id)
        if not entry:
            raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Memory not found"})
        return entry

    @app.post("/memory/{memory_id}/archive", dependencies=[Depends(auth)])
    def memory_archive(memory_id: int):
        return run(memory.archive, memory_id)

    # ------------------------------------------------------- execution backend
    @app.post("/exec")
    def exec_submit(body: ExecIn, who: str = Depends(caller)):
        agent = acting_agent(who, body.agent)  # attribution comes from the token, not from the request body
        return run(execution.submit, agent, body.action, body.approval_id)

    @app.get("/exec/approvals", dependencies=[Depends(auth)])
    def exec_approvals(status: Optional[str] = None, limit: int = 100):
        return run(approvals.list, status, limit)

    @app.get("/exec/approvals/{approval_id}", dependencies=[Depends(auth)])
    def exec_approval(approval_id: int):
        item = approvals.get(approval_id)
        if not item:
            raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Approval not found"})
        return item

    @app.post("/exec/approvals/{approval_id}/approve", dependencies=[Depends(user_only)])
    def exec_approve(approval_id: int):
        return run(approvals.decide, approval_id, True, "user")

    @app.post("/exec/approvals/{approval_id}/deny", dependencies=[Depends(user_only)])
    def exec_deny(approval_id: int):
        return run(approvals.decide, approval_id, False, "user")

    @app.get("/exec/audit", dependencies=[Depends(auth)])
    def exec_audit(limit: int = 200):
        return approvals.audit_log(limit)

    @app.post("/exec/stop", dependencies=[Depends(auth)])
    def exec_stop(body: StopIn):
        return stop.trigger(body.reason)

    @app.post("/exec/resume", dependencies=[Depends(user_only)])
    def exec_resume():
        return stop.clear()

    @app.get("/exec/status", dependencies=[Depends(auth)])
    def exec_status():
        return {"emergency_stop": stop.active(), "roots": [str(r) for r in settings.exec_roots]}

    return app
