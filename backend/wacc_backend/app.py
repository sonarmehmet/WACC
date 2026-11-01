"""FastAPI application. Every route except /health requires the X-WACC-Token header."""

from typing import Optional

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel

from . import __version__
from .config import Settings, load_settings
from .security import get_or_create_token, token_matches
from .storage import Storage, StorageError

STATUS_MAP = {"NOT_FOUND": 404, "DUPLICATE": 409}


class ProjectIn(BaseModel):
    name: str
    description: str = ""


class ProjectPatch(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    status: Optional[str] = None


def create_app(settings: Optional[Settings] = None, storage: Optional[Storage] = None,
               token: Optional[str] = None) -> FastAPI:
    settings = settings or load_settings()
    storage = storage or Storage(settings.db_path)
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

    return app
