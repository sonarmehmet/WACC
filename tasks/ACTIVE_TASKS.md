<!-- Auto-generated from the Communication Hub database. Do not edit by hand. -->
# Active Tasks

### T-0001 — Backend core: FastAPI app, auth, config, DB layer
- Owner: claude2 | Status: IN_PROGRESS | Priority: NORMAL
- Branch: task/backend-core | Commit: -
- Files: backend
- Depends on: -
- Description: Create backend/ (FastAPI) with settings, SQLite storage, auth, health endpoint and a clean module layout.
- Acceptance: Server starts with one command; /health responds; config via env, no secrets in code.
- Test criteria: pytest for config, db and health endpoints
- Note: claude1 çekirdeği yazdı (commit c6c301f, FastAPI kısmı çalıştırılmadı); claude2 bağlanınca devralır

### T-0002 — Task Engine and Agent Manager
- Owner: claude2 | Status: ASSIGNED | Priority: NORMAL
- Branch: task/engine-agents | Commit: -
- Files: backend/engine, backend/agents
- Depends on: T-0001
- Description: Task Engine (queue, status, retries) and Agent Manager (register, start, stop agents) inside backend/.
- Acceptance: Tasks can be created, run and tracked; agents can be registered and listed via API.
- Test criteria: unit + API tests

### T-0003 — AI Orchestrator and Memory System
- Owner: claude2 | Status: ASSIGNED | Priority: NORMAL
- Branch: task/orchestrator | Commit: -
- Files: backend/orchestrator, backend/memory
- Depends on: T-0001
- Description: Orchestrator routing requests to models (local + cloud, cost-aware) and a simple memory store.
- Acceptance: Provider interface with a mock provider; memory read/write API; keys loaded from env only.
- Test criteria: unit tests with the mock provider

### T-0004 — Flutter app skeleton, API client and Agents screen
- Owner: claude3 | Status: ASSIGNED | Priority: NORMAL
- Branch: task/mobile-agents | Commit: -
- Files: mobile
- Depends on: -
- Description: Create mobile/ Flutter project: navigation, API client for the hub (token auth), Agents status screen and Agent chat screen (shared feed + send message + give task).
- Acceptance: App builds for Android; Agents screen shows status from /agents; chat shows /feed.
- Test criteria: flutter analyze, widget tests

### T-0005 — Web panel: Agents and Agent Chat screens
- Owner: claude3 | Status: ASSIGNED | Priority: NORMAL
- Branch: task/web-panel | Commit: -
- Files: web
- Depends on: -
- Description: Create web/ panel (lightweight, no heavy framework needed) with the same Agents and chat views.
- Acceptance: Panel served locally; shows agents, feed, tasks; can post a message and a task.
- Test criteria: build check + API connection test

### T-0006 — Environment check, start script, backup and integration
- Owner: claude1 | Status: ASSIGNED | Priority: NORMAL
- Branch: task/integration | Commit: -
- Files: scripts, start_wacc.bat, docs
- Depends on: -
- Description: scripts/check_env.ps1, start_wacc.bat, backup, docs and the integration/review of other branches.
- Acceptance: One-click start works on Windows 10; backup creates DB copy + git bundle.
- Test criteria: script dry-run checks

### T-0007 — Brand and visual assets: logo, app icon, palette
- Owner: gemini | Status: ASSIGNED | Priority: NORMAL
- Branch: task/assets | Commit: -
- Files: assets
- Depends on: -
- Description: Create assets/branding/: WACC logo (SVG + PNG), Android app icon set, color palette and a short style guide. Only assets/ is yours; do not touch code folders.
- Acceptance: Logo, icon set and palette committed under assets/branding with a style guide.
- Test criteria: files open correctly; icon sizes match Android requirements

### T-0008 — Windows Execution Backend security spec
- Owner: claude1 | Status: REVIEW | Priority: NORMAL
- Branch: task/exec-spec | Commit: -
- Files: docs/EXECUTION_SECURITY.md
- Depends on: -
- Description: Write docs/EXECUTION_SECURITY.md: which actions the Windows execution backend may perform, what needs user approval, allowlists, audit logging and the emergency stop contract.
- Acceptance: Spec reviewed by the user; every risky action class has an approval rule.
- Test criteria: review checklist
- Note: Taslak hazır; kullanıcı onayı ve bölüm 9'daki 3 karar bekleniyor
