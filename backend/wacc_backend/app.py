"""FastAPI application. Every route except /health requires the X-WACC-Token header."""

from typing import List, Optional

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel

from . import __version__
from .agents import AgentManager
from .engine import TaskEngine
from .config import Settings, load_settings
from .security import get_or_create_token, token_matches
from .storage import Storage, StorageError

STATUS_MAP = {"NOT_FOUND": 404, "DUPLICATE": 409, "FORBIDDEN": 403, "BAD_STATE": 409,
              "PROJECT_ARCHIVED": 409, "DISABLED": 409}


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


def create_app(settings: Optional[Settings] = None, storage: Optional[Storage] = None,
               token: Optional[str] = None) -> FastAPI:
    settings = settings or load_settings()
    storage = storage or Storage(settings.db_path)
    engine = TaskEngine(storage)
    agents = AgentManager(storage)
    expected = token or get_or_create_token(settings)
    app = FastAPI(title="WACC Backend", version=__version__)

    def auth(x_wacc_token: str = Header(default="")):
        if not token_matches(expected, x_wacc_token):
            raise HTTPException(status_code=401, detail="Invalid or missing X-WACC-Token")

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

    @app.post("/agents/{name}/heartbeat", dependencies=[Depends(auth)])
    def agent_heartbeat(name: str, body: HeartbeatIn):
        return run(agents.heartbeat, name, body.status, body.current_job)

    @app.post("/agents/{name}/enabled", dependencies=[Depends(auth)])
    def agent_enabled(name: str, body: EnabledIn):
        return run(agents.set_enabled, name, body.enabled)

    return app
