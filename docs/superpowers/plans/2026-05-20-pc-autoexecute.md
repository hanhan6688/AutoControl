# PC AutoExecute Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add PC AutoExecute so agent-browser can control the same browser surface visible inside the Electron window, with optional background execution and step screenshots/logs.

**Architecture:** Electron owns the visible browser surface and exposes its CDP port to the frontend/backend through IPC. The backend `PCBrowserService` connects agent-browser to that CDP target instead of launching an unrelated browser by default. The frontend adds a PC AutoExecute view that can show/hide the embedded browser, start a browser session, run simple step actions, and stream logs/screenshot paths.

**Tech Stack:** Electron BrowserView/WebContentsView-compatible API, Chrome DevTools Protocol, agent-browser CLI, FastAPI, Vue 3, Element Plus, pytest, Vite.

---

### Task 1: Electron Embedded Browser Surface

**Files:**
- Modify: `desktop/main.js`
- Modify: `desktop/preload.js`

- [x] Open Electron with a dedicated remote debugging port.
- [x] Create one embedded browser view owned by Electron.
- [x] Expose IPC methods to show/hide/resize/navigate the embedded browser and report the CDP port.

### Task 2: Backend Agent-Browser Session

**Files:**
- Modify: `backend/app/services/pc_browser_service.py`
- Modify: `backend/app/routers/pc_browser.py`
- Test: `backend/tests/test_pc_browser_service.py`

- [x] Add explicit `connect_cdp(port)` support.
- [x] Make visible Electron browser mode the default when a CDP port is provided.
- [x] Add a lightweight event log with command, stdout/stderr snippets, screenshot path, and timestamp.

### Task 3: Frontend PC AutoExecute Page

**Files:**
- Modify: `frontend/src/api.ts`
- Create: `frontend/src/views/PCAutoExecute.vue`
- Modify: `frontend/src/router/index.ts`

- [x] Add API wrappers for PC browser connect/open/snapshot/action/screenshot/logs.
- [x] Add a PC AutoExecute page with URL, visible/background toggle, browser canvas area, action controls, and logs.
- [x] Keep the embedded browser inside Electron for visual mode; for browser/web fallback show screenshots/logs only.

### Task 4: Verification

**Commands:**
- `python -m pytest backend\tests -q`
- `npm run build` from `frontend`

- [x] Backend tests pass.
- [x] Frontend build passes.
