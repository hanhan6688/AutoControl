# PC Agent Execution Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a PC-side test execution loop where AI decides the next browser action and agent-browser executes it, with manual login pause/resume and per-step screenshots/logs.

**Architecture:** Keep `PCBrowserService` as the low-level executor. Add `PCBrowserAgentService` as the decision loop that reads URL/title/snapshot, asks the configured planner model for a JSON action, executes one step through agent-browser, captures evidence, and streams NDJSON events to the frontend.

**Tech Stack:** FastAPI, OpenAI-compatible chat completions, agent-browser CLI, Vue 3, Element Plus.

---

### Task 1: Backend Agent Loop

**Files:**
- Create: `backend/app/services/pc_browser_agent_service.py`
- Modify: `backend/app/services/pc_browser_service.py`
- Test: `backend/tests/test_pc_browser_agent_service.py`

- [ ] Add tests for JSON decision parsing, manual-auth pause, finish result, and action execution.
- [ ] Implement a focused PC agent service with dependency injection for browser and model clients.
- [ ] Capture a screenshot after every executed step.

### Task 2: Streaming API

**Files:**
- Modify: `backend/app/routers/pc_browser.py`
- Test: `backend/tests/test_pc_browser_routes.py`

- [ ] Add `/api/pc-browser/agent/run/stream`.
- [ ] Return NDJSON events compatible with the existing frontend stream reader style.

### Task 3: Frontend PC AutoExecute Controls

**Files:**
- Modify: `frontend/src/api.ts`
- Modify: `frontend/src/views/PCAutoExecute.vue`

- [ ] Add AI task input, run, continue, and stop controls.
- [ ] Show streaming step logs and screenshots.
- [ ] When the backend emits `need_user`, keep the embedded browser usable and show a continue button.

### Task 4: Verification

**Files:**
- Existing test/build commands only.

- [ ] Run backend pytest.
- [ ] Run frontend build.
