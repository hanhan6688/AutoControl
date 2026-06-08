# AutoExecute Mobile UI Element Recording Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build AutoExecute recording and replay for mobile clicks as replayable UI element selectors with OCR, image matching, and coordinate fallback support.

**Architecture:** Add a backend UI hierarchy service that normalizes Android UIAutomator XML, iOS WDA source, and Harmony/HDC-compatible hierarchy data into one element model. The script runtime gets an `auto_execute` DSL that retries selector-based clicks first and falls back to OCR/image/coordinate actions when provided. The Vue device screen records a clicked point by asking the backend for the best element under that point, then appends stable replay code to the active script.

**Tech Stack:** FastAPI, Pydantic, ADB/UIAutomator, WDA-compatible iOS source, HDC-ready provider boundary, Vue 3 Composition API, Element Plus, pytest, Vite.

---

### Task 1: Backend UI Element Service

**Files:**
- Create: `backend/app/services/ui_element_service.py`
- Modify: `backend/app/services/adb_service.py`
- Modify: `backend/app/schemas.py`
- Test: `backend/tests/test_ui_element_service.py`

- [x] Parse mobile UI hierarchy into normalized elements with bounds, center, selector, and XPath-like metadata.
- [x] Locate the smallest clickable element containing a recorded point.
- [x] Keep package filtering optional so WeChat mini-program pages can still match nested nodes.

### Task 2: Device API

**Files:**
- Modify: `backend/app/routers/devices.py`
- Modify: `frontend/src/api.ts`
- Test: `backend/tests/test_devices_ui_routes.py`

- [x] Add an endpoint for locating the UI element at a clicked screen point.
- [x] Return generated Python DSL code plus fallback coordinates.

### Task 3: Script DSL Replay

**Files:**
- Modify: `backend/app/routers/scripts.py`
- Test: `backend/tests/test_scripts_router.py`

- [x] Add `auto_execute.click(...)`, `auto_execute.find(...)`, and `auto_execute.dump(...)`, while keeping `ui` as a compatibility alias.
- [x] Support selector replay first, OCR/image fallback second, coordinate fallback last.

### Task 4: Vue Recording UX

**Files:**
- Modify: `frontend/src/views/DeviceManager.vue`

- [x] Add an element recording switch and package-name input in the screen controls.
- [x] When enabled, append `ui.click(...)` code from the backend instead of only `adb.click(...)`.
- [x] Keep existing OCR and image matching buttons and generated code.

### Task 5: Verification

**Commands:**
- `python -m pytest backend\tests -q`
- `npm run build` from `frontend`

- [x] Confirm backend tests pass.
- [x] Confirm frontend TypeScript/Vite build passes.
