"""FastAPI service. Binds to 127.0.0.1 by default; every call except /health needs a token.

The token decides the acting agent, so an agent can never impersonate another one.
"""

from typing import List, Optional

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from . import __version__
from .auth import load_or_create_tokens, new_token, resolve_actor, save_tokens
from .render import render_all
from .service import Hub, HubError

STATUS_MAP = {"DUPLICATE": 409, "AGENT_DISABLED": 403, "NOT_REMOVABLE": 409, "BAD_NAME": 400, "BAD_KIND": 400, "BAD_PROVIDER": 400, 
    "UNKNOWN_AGENT": 404, "UNKNOWN_TASK": 404, "UNKNOWN_MESSAGE": 404,
    "FORBIDDEN": 403, "EMERGENCY_STOP": 423, "LOCKED": 409, "STALE_LOCK": 409,
    "BAD_STATE": 409, "DEPENDENCY_OPEN": 409,
}


class SendIn(BaseModel):
    receiver: str
    message_type: str
    subject: str
    content: str = ""
    conversation_id: Optional[str] = None
    task_id: Optional[str] = None
    priority: str = "NORMAL"
    related_files: List[str] = Field(default_factory=list)
    related_commit: Optional[str] = None
    response_required: bool = False
    in_reply_to: Optional[str] = None
    idempotency_key: Optional[str] = None


class TaskIn(BaseModel):
    title: str
    description: str = ""
    owner: Optional[str] = None
    affected_files: List[str] = Field(default_factory=list)
    dependencies: List[str] = Field(default_factory=list)
    acceptance: str = ""
    test_criteria: str = ""
    priority: str = "NORMAL"
    branch: Optional[str] = None


class StatusIn(BaseModel):
    status: str
    commit: Optional[str] = None
    note: Optional[str] = None


class LockIn(BaseModel):
    path: str
    task_id: Optional[str] = None
    ttl: int = 900
    takeover: bool = False


class ReleaseIn(BaseModel):
    path: Optional[str] = None
    task_id: Optional[str] = None


class HeartbeatIn(BaseModel):
    status: Optional[str] = None
    current_task: Optional[str] = None
    last_commit: Optional[str] = None


class DecisionIn(BaseModel):
    title: str
    decision: str
    rationale: str = ""
    task_id: Optional[str] = None
    conversation_id: Optional[str] = None
    critical: bool = False


class CheckpointIn(BaseModel):
    notes: str
    task_id: Optional[str] = None
    branch: Optional[str] = None
    git_commit: Optional[str] = None


class HandoffIn(BaseModel):
    to_agent: str
    task_id: str
    notes: str
    git_commit: Optional[str] = None
    branch: Optional[str] = None


class SessionEndIn(BaseModel):
    notes: str
    git_commit: Optional[str] = None
    branch: Optional[str] = None


class AgentIn(BaseModel):
    name: str
    kind: str = "other"
    role: str = ""
    provider: Optional[str] = None


class EnabledIn(BaseModel):
    enabled: bool


class StopIn(BaseModel):
    reason: str = "manual stop"


def create_app(hub: Optional[Hub] = None, tokens: Optional[dict] = None, token_path=None) -> FastAPI:
    hub = hub or Hub()
    persist = token_path is not None or tokens is None  # tests pass an in-memory dict and skip the file
    tokens = tokens or load_or_create_tokens(token_path)
    app = FastAPI(title="WACC Communication Hub", version=__version__)

    def actor(x_wacc_token: str = Header(default="")):
        who = resolve_actor(tokens, x_wacc_token)
        if not who:
            raise HTTPException(status_code=401, detail="Invalid or missing X-WACC-Token")
        if not hub.agent_enabled(who):  # switched off or removed accounts stop working immediately
            raise HTTPException(status_code=403, detail={"code": "AGENT_DISABLED", "message": f"{who} is switched off"})
        return who

    def run(fn, *args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except HubError as exc:
            raise HTTPException(status_code=STATUS_MAP.get(exc.code, 400),
                                detail={"code": exc.code, "message": exc.message, "detail": exc.detail})

    @app.get("/health")
    def health():
        return {"ok": True, "version": __version__, "emergency_stop": hub.emergency_status()}

    @app.get("/whoami")
    def whoami(me: str = Depends(actor)):
        return {"agent": me}

    # messages
    @app.post("/messages")
    def send(body: SendIn, me: str = Depends(actor)):
        data = body.model_dump()
        receiver, mtype, subject, content = (data.pop("receiver"), data.pop("message_type"),
                                             data.pop("subject"), data.pop("content"))
        return run(hub.send_message, me, receiver, mtype, subject, content, **data)

    @app.get("/inbox")
    def inbox(unread: bool = False, limit: int = 100, me: str = Depends(actor)):
        return hub.inbox(me, unread_only=unread, limit=min(limit, 500))

    @app.get("/sent")
    def sent(limit: int = 100, me: str = Depends(actor)):
        return hub.sent(me, limit=min(limit, 500))

    @app.get("/outbox")
    def outbox(me: str = Depends(actor)):
        return hub.outbox(me)

    @app.get("/pending")
    def pending(me: str = Depends(actor)):
        return {"must_answer": hub.pending_responses(me), "awaiting_reply": hub.awaiting_reply(me)}

    @app.post("/messages/{message_id}/read")
    def read(message_id: str, me: str = Depends(actor)):
        return run(hub.mark_read, me, message_id)

    @app.post("/messages/{message_id}/answered")
    def answered(message_id: str, me: str = Depends(actor)):
        return run(hub.mark_answered, me, message_id)

    @app.get("/feed")
    def feed(limit: int = 200, conversation_id: Optional[str] = None, me: str = Depends(actor)):
        return hub.feed(limit=min(limit, 500), conversation_id=conversation_id)

    # tasks
    @app.post("/tasks")
    def create_task(body: TaskIn, me: str = Depends(actor)):
        return run(hub.create_task, me, **body.model_dump())

    @app.get("/tasks")
    def tasks(owner: Optional[str] = None, status: Optional[str] = None, me: str = Depends(actor)):
        return hub.list_tasks(owner=owner, status=status)

    @app.post("/tasks/{task_id}/assign/{owner}")
    def assign(task_id: str, owner: str, me: str = Depends(actor)):
        return run(hub.assign_task, me, task_id, owner)

    @app.post("/tasks/{task_id}/accept")
    def accept(task_id: str, me: str = Depends(actor)):
        return run(hub.accept_task, me, task_id)

    @app.post("/tasks/{task_id}/status")
    def task_status(task_id: str, body: StatusIn, me: str = Depends(actor)):
        return run(hub.set_task_status, me, task_id, body.status, body.commit, body.note)

    # locks
    @app.get("/locks")
    def locks(me: str = Depends(actor)):
        return hub.list_locks()

    @app.post("/locks")
    def lock(body: LockIn, me: str = Depends(actor)):
        return run(hub.acquire_lock, me, body.path, body.task_id, body.ttl, body.takeover)

    @app.post("/locks/release")
    def release(body: ReleaseIn, me: str = Depends(actor)):
        return {"released": run(hub.release_lock, me, body.path, body.task_id)}

    # agents / sessions
    @app.get("/agents")
    def agents(me: str = Depends(actor)):
        return hub.overview()

    # Agent accounts are the human's: only the user token adds, removes or switches them.
    @app.post("/agents", status_code=201)
    def agent_add(body: AgentIn, me: str = Depends(actor)):
        row = run(hub.register_agent, me, body.name, body.kind, body.role, body.provider)
        token = new_token()
        tokens[row["agent_id"]] = token
        if persist:
            save_tokens(tokens, token_path)
        return {"agent": row, "token": token}  # the only time the token is shown; it also lives in data/tokens.json

    @app.post("/agents/{name}/enabled")
    def agent_enabled(name: str, body: EnabledIn, me: str = Depends(actor)):
        return run(hub.set_agent_enabled, me, name, body.enabled)

    @app.delete("/agents/{name}")
    def agent_remove(name: str, me: str = Depends(actor)):
        out = run(hub.remove_agent, me, name)
        tokens.pop(name, None)
        if persist:
            save_tokens(tokens, token_path)
        return out

    @app.post("/heartbeat")
    def heartbeat(body: HeartbeatIn, me: str = Depends(actor)):
        return run(hub.heartbeat, me, **body.model_dump())

    @app.post("/session/start")
    def session_start(me: str = Depends(actor)):
        return run(hub.session_start, me)

    @app.post("/session/end")
    def session_end(body: SessionEndIn, me: str = Depends(actor)):
        return run(hub.session_end, me, body.notes, body.git_commit, body.branch)

    @app.post("/handoff")
    def handoff(body: HandoffIn, me: str = Depends(actor)):
        return run(hub.handoff, me, body.to_agent, body.task_id, body.notes, body.git_commit, body.branch)

    # decisions / checkpoints
    @app.post("/decisions")
    def decide(body: DecisionIn, me: str = Depends(actor)):
        return run(hub.record_decision, me, **body.model_dump())

    @app.get("/decisions")
    def decisions(me: str = Depends(actor)):
        return hub.list_decisions()

    @app.post("/checkpoints")
    def checkpoint(body: CheckpointIn, me: str = Depends(actor)):
        return run(hub.add_checkpoint, me, **body.model_dump())

    # safety
    @app.post("/system/stop")
    def stop(body: StopIn, me: str = Depends(actor)):
        run(hub.emergency_stop, me, body.reason)
        return {"emergency_stop": True}

    @app.post("/system/resume")
    def resume(me: str = Depends(actor)):
        run(hub.resume, me)
        return {"emergency_stop": False}

    @app.get("/audit")
    def audit(limit: int = 200, me: str = Depends(actor)):
        if me not in ("user", "claude1"):
            raise HTTPException(status_code=403, detail="Audit log is restricted")
        return hub.audit_log(limit=min(limit, 1000))

    @app.post("/render")
    def render(me: str = Depends(actor)):
        return {"written": render_all(hub)}

    return app
