# Project Stabilization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Improve project usability and operational stability without removing existing mobile, PC/Web, reporting, or Electron functionality.

**Architecture:** Keep current FastAPI/Vue/Electron boundaries. Add small stability utilities and endpoints around existing services instead of restructuring large modules in this pass. Preserve mobile AutoGLM and PC agent-browser execution paths.

**Tech Stack:** FastAPI, SQLAlchemy, Vue 3, Vite, Electron, pytest, npm scripts.

---

### Task 1: Startup Scripts

**Files:**
- Modify: `package.json`
- Modify: `frontend/package.json`
- Modify: `README.md`

- [ ] Make root scripts explicit: `dev` for full Electron app, `dev:browser` for Vite-only browser mode, `dev:backend` for FastAPI.
- [ ] Make `frontend/npm run dev` start Vite directly so it does not recurse back to the root script.
- [ ] Document which command opens Electron and which command only opens browser mode.

### Task 2: Health Check

**Files:**
- Create: `backend/app/services/project_health_service.py`
- Modify: `backend/app/routers/diagnostic.py`
- Test: `backend/tests/test_project_health.py`

- [ ] Add a read-only health snapshot covering backend runtime, database URL type, tool paths, PC Agent model config, agent-browser availability, Open-AutoGLM root, report/upload sizes.
- [ ] Expose it at `GET /api/diagnostic/project-health`.
- [ ] Add tests with monkeypatched filesystem and settings.

### Task 3: Report Cleanup

**Files:**
- Create: `backend/app/services/artifact_cleanup_service.py`
- Modify: `backend/app/routers/diagnostic.py`
- Test: `backend/tests/test_artifact_cleanup_service.py`

- [ ] Add dry-run cleanup for `backend/static/reports` and `backend/static/uploads`.
- [ ] Support `max_age_days`, `max_total_mb`, and `dry_run`.
- [ ] Protect `.gitkeep` and reject paths outside managed artifact roots.
- [ ] Expose endpoint `POST /api/diagnostic/artifacts/cleanup`.

### Task 4: Documentation

**Files:**
- Modify: `README.md`

- [ ] Update startup, Electron, exe packaging, MiniMax PC Agent, Leyoujia login state, report cleanup, and verification commands.

### Task 5: Verification

**Commands:**
- `python -m pytest backend\tests -q`
- `npm run build` from `frontend`
- `npm audit --audit-level=moderate --json`
- `npm --prefix frontend audit --audit-level=moderate --json`

- [ ] Record any blocked checks explicitly.
