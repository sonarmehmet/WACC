# WACC Backend

Owner: claude2 (T-0001..T-0003). T-0001 core was started by claude1 on branch `task/backend-core`.

## Run (Windows)

```
set PYTHONPATH=backend
.venv\Scripts\python -m wacc_backend
```
Listens on `127.0.0.1:8800`. Token: env `WACC_BACKEND_TOKEN`, or generated into `data/backend_token.txt` (git-ignored).

## Settings (env)
`WACC_BACKEND_HOST` (default 127.0.0.1), `WACC_BACKEND_PORT` (8800), `WACC_DATA_DIR`, `WACC_BACKEND_DB`, `WACC_BACKEND_TOKEN`.

## API
- `GET /health` (public)
- `GET/POST /projects`, `GET/PATCH /projects/{id}`, `POST /projects/{id}/archive` (header `X-WACC-Token`)

Projects are archived, never hard-deleted.

## Next (T-0002, T-0003)
Task Engine, Agent Manager, AI Orchestrator (provider interface + mock), Memory System. Add new tables as new entries in `storage.MIGRATIONS`; never edit an existing migration.
