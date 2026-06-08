# Script Python Env Switch + Real-time Terminal Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enable Python environment switching for script execution and add a real-time terminal panel for streaming stdout/stderr output via WebSocket.

**Architecture:** Replace `exec()` with `subprocess.Popen` using configured Python interpreter. Add WebSocket endpoint for real-time output streaming. Frontend gets a terminal panel component with ANSI color support.

**Tech Stack:** FastAPI WebSocket, subprocess, Vue 3 Composition API, WebSocket API

---

## File Structure

**Backend:**
- `backend/app/routers/scripts.py` - Add streaming endpoints, WebSocket handler
- `backend/app/services/script_run_service.py` - NEW: Script run state management, subprocess execution

**Frontend:**
- `frontend/src/components/device/TerminalPanel.vue` - NEW: Real-time terminal display
- `frontend/src/composables/useScriptTerminal.ts` - NEW: WebSocket connection management
- `frontend/src/api.ts` - Add streaming API functions
- `frontend/src/stores/scripts.ts` - Add Python env state
- `frontend/src/views/DeviceManager.vue` - Integrate terminal panel, Python env selector
- `frontend/src/components/device/AutoExecutePanel.vue` - Use streaming for playback

---

## Task 1: Backend Script Run Service

**Files:**
- Create: `backend/app/services/script_run_service.py`

- [ ] **Step 1: Create the script run service with state management**

```python
"""
Script execution service with subprocess and WebSocket streaming.
"""
from __future__ import annotations

import asyncio
import os
import subprocess
import tempfile
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastapi import WebSocket

from app.config import settings


@dataclass
class ScriptRun:
    """Active script run state."""
    id: str
    path: str
    device_udid: str
    platform: str
    python_path: str
    wda_url: str | None
    status: str  # "running" | "completed" | "failed" | "cancelled"
    process: subprocess.Popen | None
    started_at: float
    completed_at: float | None = None
    returncode: int | None = None
    ws_connections: list["WebSocket"] = field(default_factory=list)


# Global state for active runs
_active_runs: dict[str, ScriptRun] = {}
_runs_lock = asyncio.Lock()


def generate_preamble(
    device_udid: str,
    platform: str,
    wda_url: str | None,
    script_type: str = "mobile",
    session: str | None = None,
) -> str:
    """Generate Python preamble that sets up runtime objects."""
    if script_type == "pc":
        return f'''
import sys
import os
sys.path.insert(0, r"{settings.backend_dir.as_posix()}")
os.environ["PYTHONIOENCODING"] = "utf-8"

from app.services.pc_browser_service import PCBrowserService
from app.routers.scripts import ScriptBrowser, ScriptInput

_browser_service = PCBrowserService()
_browser_session = "{session or 'script-browser'}"

class _Runtime:
    browser = ScriptBrowser(_browser_session, _browser_service)
    web = browser
    input = ScriptInput()

runtime = _Runtime()
globals().update({{
    "browser": runtime.browser,
    "web": runtime.web,
    "input": runtime.input,
}})
'''
    else:
        wda_url_str = f'"{wda_url}"' if wda_url else "None"
        return f'''
import sys
import os
sys.path.insert(0, r"{settings.backend_dir.as_posix()}")
os.environ["PYTHONIOENCODING"] = "utf-8"

from app.services.adb_service import ADBService
from app.services.ui_element_service import UIElementService
from app.services.visual_action_service import VisualActionService
from app.routers.scripts import (
    ScriptADB, ScriptOCR, ScriptImage, ScriptUI, ScriptInput
)

_adb_service = ADBService()
_ui_service = UIElementService()
_visual_service = VisualActionService(adb=_adb_service)

class _Runtime:
    adb = ScriptADB("{device_udid}", _adb_service)
    ocr = ScriptOCR("{device_udid}", _visual_service)
    image = ScriptImage("{device_udid}", _visual_service)
    auto_execute = ScriptUI("{device_udid}", _ui_service, _adb_service, platform="{platform}", wda_url={wda_url_str})
    ui = auto_execute
    input = ScriptInput()

    @staticmethod
    def launch(app_id):
        return _Runtime.auto_execute.launch(app_id)

runtime = _Runtime()
globals().update({{
    "adb": runtime.adb,
    "ocr": runtime.ocr,
    "image": runtime.image,
    "auto_execute": runtime.auto_execute,
    "ui": runtime.ui,
    "input": runtime.input,
    "launch": runtime.launch,
}})
'''


def create_run(
    path: str,
    device_udid: str,
    platform: str,
    python_path: str,
    wda_url: str | None = None,
) -> ScriptRun:
    """Create a new script run."""
    run_id = str(uuid.uuid4())[:8]
    run = ScriptRun(
        id=run_id,
        path=path,
        device_udid=device_udid,
        platform=platform,
        python_path=python_path,
        wda_url=wda_url,
        status="running",
        process=None,
        started_at=time.monotonic(),
    )
    _active_runs[run_id] = run
    return run


def get_run(run_id: str) -> ScriptRun | None:
    """Get a script run by ID."""
    return _active_runs.get(run_id)


def remove_run(run_id: str) -> None:
    """Remove a completed run."""
    _active_runs.pop(run_id, None)


async def broadcast_output(run: ScriptRun, msg_type: str, data: str) -> None:
    """Broadcast output to all connected WebSocket clients."""
    import json
    message = json.dumps({"type": msg_type, "data": data})
    dead_connections = []
    for ws in run.ws_connections:
        try:
            await ws.send_text(message)
        except Exception:
            dead_connections.append(ws)
    for ws in dead_connections:
        run.ws_connections.remove(ws)


async def broadcast_exit(run: ScriptRun, returncode: int, duration_ms: int) -> None:
    """Broadcast exit event to all connected WebSocket clients."""
    import json
    message = json.dumps({
        "type": "exit",
        "returncode": returncode,
        "duration_ms": duration_ms,
    })
    for ws in run.ws_connections[:]:
        try:
            await ws.send_text(message)
        except Exception:
            pass


async def broadcast_error(run: ScriptRun, message: str) -> None:
    """Broadcast error event to all connected WebSocket clients."""
    import json
    msg = json.dumps({"type": "error", "message": message})
    for ws in run.ws_connections[:]:
        try:
            await ws.send_text(msg)
        except Exception:
            pass
```

- [ ] **Step 2: Commit the service file**

```bash
git add backend/app/services/script_run_service.py
git commit -m "feat(backend): add script run service for subprocess execution

- ScriptRun dataclass for run state management
- Preamble generation for runtime object injection
- WebSocket broadcast utilities

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 2: Backend Streaming Execution Logic

**Files:**
- Modify: `backend/app/services/script_run_service.py`

- [ ] **Step 1: Add the subprocess execution function**

Append to `backend/app/services/script_run_service.py`:

```python


async def execute_script_streaming(
    run: ScriptRun,
    script_path: Path,
    script_type: str = "mobile",
    session: str | None = None,
) -> None:
    """Execute script via subprocess and stream output via WebSocket."""
    python = run.python_path or settings.resolved_python_path

    # Generate preamble
    preamble = generate_preamble(
        device_udid=run.device_udid,
        platform=run.platform,
        wda_url=run.wda_url,
        script_type=script_type,
        session=session,
    )

    # Read user script
    user_script = script_path.read_text(encoding="utf-8")

    # Combine preamble + user script
    full_script = preamble + "\n\n# User script:\n" + user_script

    # Write to temp file
    with tempfile.NamedTemporaryFile(
        mode="w",
        suffix=".py",
        delete=False,
        encoding="utf-8",
    ) as tmp:
        tmp.write(full_script)
        tmp_path = Path(tmp.name)

    try:
        # Prepare environment
        env = os.environ.copy()
        adb_dir = str(Path(settings.resolved_adb_path).resolve().parent)
        env["PATH"] = f"{adb_dir}{os.pathsep}{env.get('PATH', '')}"
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUTF8"] = "1"

        # Launch subprocess
        proc = subprocess.Popen(
            [python, str(tmp_path), run.device_udid],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        run.process = proc

        # Stream output asynchronously
        loop = asyncio.get_event_loop()

        async def read_stream(stream, msg_type: str):
            """Read from stream and broadcast."""
            try:
                while True:
                    line = await loop.run_in_executor(None, stream.readline)
                    if not line:
                        break
                    await broadcast_output(run, msg_type, line)
            except Exception:
                pass

        # Read stdout and stderr concurrently
        await asyncio.gather(
            read_stream(proc.stdout, "stdout"),
            read_stream(proc.stderr, "stderr"),
        )

        # Wait for process to complete
        returncode = await loop.run_in_executor(None, proc.wait)
        run.returncode = returncode
        run.completed_at = time.monotonic()
        run.status = "completed" if returncode == 0 else "failed"

        duration_ms = int((run.completed_at - run.started_at) * 1000)
        await broadcast_exit(run, returncode, duration_ms)

    except Exception as e:
        run.status = "failed"
        run.completed_at = time.monotonic()
        await broadcast_error(run, str(e))
    finally:
        # Clean up temp file
        try:
            tmp_path.unlink(missing_ok=True)
        except Exception:
            pass


def cancel_run(run_id: str) -> bool:
    """Cancel a running script."""
    run = _active_runs.get(run_id)
    if not run or run.status != "running":
        return False
    if run.process:
        try:
            run.process.terminate()
            run.process.wait(timeout=5)
        except Exception:
            try:
                run.process.kill()
            except Exception:
                pass
    run.status = "cancelled"
    run.completed_at = time.monotonic()
    return True


def get_python_envs() -> dict:
    """Get available Python environments."""
    import sys
    import shutil

    envs = []

    # System Python
    system_python = shutil.which("python") or shutil.which("python3")
    if system_python:
        envs.append({"name": "System Python", "path": system_python})

    # Configured venv
    if settings.venv_dir:
        venv_python = settings.venv_dir / "Scripts" / "python.exe"
        if venv_python.exists():
            envs.append({"name": f"venv ({settings.venv_dir.name})", "path": str(venv_python)})

    # Current Python
    current = settings.resolved_python_path

    return {
        "current": current,
        "default": system_python or sys.executable,
        "envs": envs,
    }
```

- [ ] **Step 2: Commit the execution logic**

```bash
git add backend/app/services/script_run_service.py
git commit -m "feat(backend): add subprocess execution with WebSocket streaming

- execute_script_streaming runs script in subprocess
- Concurrent stdout/stderr streaming
- cancel_run for process termination
- get_python_envs for environment discovery

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 3: Backend API Endpoints

**Files:**
- Modify: `backend/app/routers/scripts.py`

- [ ] **Step 1: Add imports and new schemas**

At the top of `backend/app/routers/scripts.py`, add imports after existing imports:

```python
import asyncio
from fastapi import WebSocket, WebSocketDisconnect
from app.services.script_run_service import (
    ScriptRun,
    create_run,
    get_run,
    remove_run,
    execute_script_streaming,
    cancel_run,
    get_python_envs,
)
```

Add new schemas after `ScriptRunResult`:

```python
class ScriptRunStreamStart(BaseModel):
    run_id: str
    python_path: str


class PythonEnvInfo(BaseModel):
    name: str
    path: str


class PythonEnvsResponse(BaseModel):
    current: str
    default: str
    envs: list[PythonEnvInfo]
```

- [ ] **Step 2: Add Python environments endpoint**

Add after the existing routes (before the last line):

```python
@router.get("/python-envs", response_model=PythonEnvsResponse)
def list_python_envs() -> PythonEnvsResponse:
    """Get available Python environments."""
    data = get_python_envs()
    return PythonEnvsResponse(
        current=data["current"],
        default=data["default"],
        envs=[PythonEnvInfo(**e) for e in data["envs"]],
    )
```

- [ ] **Step 3: Add streaming run endpoint**

```python
@router.post("/{path:path}/run-stream", response_model=ScriptRunStreamStart)
async def run_script_stream(
    path: str,
    device_udid: str,
    platform: str = "android",
    wda_url: str | None = None,
    python_env: str | None = None,
) -> ScriptRunStreamStart:
    """Start script execution with streaming output. Returns run_id for WebSocket connection."""
    file_path = _script_path(path)
    python_path = python_env or settings.resolved_python_path

    run = create_run(
        path=path,
        device_udid=device_udid,
        platform=platform,
        python_path=python_path,
        wda_url=wda_url,
    )

    # Start execution in background
    asyncio.create_task(
        execute_script_streaming(
            run=run,
            script_path=file_path,
            script_type="mobile",
        )
    )

    return ScriptRunStreamStart(run_id=run.id, python_path=python_path)
```

- [ ] **Step 4: Add PC streaming run endpoint**

```python
@router.post("/{path:path}/run-pc-stream", response_model=ScriptRunStreamStart)
async def run_pc_script_stream(
    path: str,
    session: str | None = None,
    python_env: str | None = None,
) -> ScriptRunStreamStart:
    """Start PC script execution with streaming output."""
    file_path = _script_path(path)
    python_path = python_env or settings.resolved_python_path

    run = create_run(
        path=path,
        device_udid="",
        platform="pc",
        python_path=python_path,
        wda_url=None,
    )

    asyncio.create_task(
        execute_script_streaming(
            run=run,
            script_path=file_path,
            script_type="pc",
            session=session,
        )
    )

    return ScriptRunStreamStart(run_id=run.id, python_path=python_path)
```

- [ ] **Step 5: Add WebSocket endpoint**

```python
@router.websocket("/output/{run_id}")
async def script_output_websocket(websocket: WebSocket, run_id: str) -> None:
    """WebSocket endpoint for real-time script output."""
    await websocket.accept()

    run = get_run(run_id)
    if not run:
        import json
        await websocket.send_text(json.dumps({"type": "error", "message": "Run not found"}))
        await websocket.close()
        return

    run.ws_connections.append(websocket)

    try:
        # Keep connection alive and handle client disconnect
        while True:
            try:
                data = await websocket.receive()
                if data.get("type") == "websocket.disconnect":
                    break
            except WebSocketDisconnect:
                break
    finally:
        if websocket in run.ws_connections:
            run.ws_connections.remove(websocket)
        # Clean up run if completed and no more connections
        if run.status in ("completed", "failed", "cancelled") and not run.ws_connections:
            remove_run(run_id)
```

- [ ] **Step 6: Add cancel endpoint**

```python
@router.post("/run/{run_id}/cancel")
def cancel_script_run(run_id: str) -> dict[str, str]:
    """Cancel a running script."""
    success = cancel_run(run_id)
    if success:
        return {"status": "cancelled", "run_id": run_id}
    raise HTTPException(status_code=404, detail="Run not found or not running")
```

- [ ] **Step 7: Commit the API endpoints**

```bash
git add backend/app/routers/scripts.py
git commit -m "feat(backend): add streaming script execution endpoints

- POST /api/scripts/{path}/run-stream starts subprocess execution
- POST /api/scripts/{path}/run-pc-stream for PC scripts
- GET /ws/script-output/{run_id} WebSocket for real-time output
- GET /api/scripts/python-envs lists available Python environments
- POST /api/scripts/run/{run_id}/cancel to stop running script

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 4: Frontend API Functions

**Files:**
- Modify: `frontend/src/api.ts`

- [ ] **Step 1: Add new interfaces and functions**

Add after `ScriptRunResult` interface (around line 768):

```typescript
export interface ScriptRunStreamStart {
  run_id: string
  python_path: string
}

export interface PythonEnvInfo {
  name: string
  path: string
}

export interface PythonEnvsResponse {
  current: string
  default: string
  envs: PythonEnvInfo[]
}
```

Add after `runScript` function (around line 830):

```typescript
export async function runScriptStream(
  path: string,
  deviceUdid: string,
  options: { platform?: string; wdaUrl?: string | null; pythonEnv?: string } = {},
): Promise<ScriptRunStreamStart> {
  const params = new URLSearchParams({ device_udid: deviceUdid })
  if (options.platform) params.set('platform', options.platform)
  if (options.wdaUrl) params.set('wda_url', options.wdaUrl)
  if (options.pythonEnv) params.set('python_env', options.pythonEnv)
  const resp = await api.post<ScriptRunStreamStart>(`/api/scripts/${path}/run-stream?${params.toString()}`)
  return resp.data
}

export async function runPcScriptStream(
  path: string,
  options: { session?: string; pythonEnv?: string } = {},
): Promise<ScriptRunStreamStart> {
  const params = new URLSearchParams()
  if (options.session) params.set('session', options.session)
  if (options.pythonEnv) params.set('python_env', options.pythonEnv)
  const resp = await api.post<ScriptRunStreamStart>(`/api/scripts/${path}/run-pc-stream?${params.toString()}`)
  return resp.data
}

export async function fetchPythonEnvs(): Promise<PythonEnvsResponse> {
  const resp = await api.get<PythonEnvsResponse>('/api/scripts/python-envs')
  return resp.data
}

export async function cancelScriptRun(runId: string): Promise<void> {
  await api.post(`/api/scripts/run/${runId}/cancel`)
}

export function getScriptOutputWebSocketUrl(runId: string): string {
  const baseUrl = new URL(apiBaseUrl)
  baseUrl.protocol = baseUrl.protocol === 'https:' ? 'wss:' : 'ws:'
  baseUrl.pathname = `/api/scripts/output/${runId}`
  return baseUrl.toString()
}
```

- [ ] **Step 2: Commit the API functions**

```bash
git add frontend/src/api.ts
git commit -m "feat(frontend): add streaming script execution API functions

- runScriptStream, runPcScriptStream for streaming execution
- fetchPythonEnvs for environment discovery
- cancelScriptRun to stop running script
- getScriptOutputWebSocketUrl for WebSocket connection

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 5: Frontend Script Terminal Composable

**Files:**
- Create: `frontend/src/composables/useScriptTerminal.ts`

- [ ] **Step 1: Create the composable**

```typescript
import { ref, onUnmounted, watch } from 'vue'
import { getScriptOutputWebSocketUrl } from '../api'

export interface TerminalLine {
  id: number
  type: 'stdout' | 'stderr' | 'system' | 'exit'
  text: string
  timestamp: number
}

export function useScriptTerminal() {
  const lines = ref<TerminalLine[]>([])
  const isConnected = ref(false)
  const isRunning = ref(false)
  const lastReturnCode = ref<number | null>(null)
  const durationMs = ref<number | null>(null)

  let ws: WebSocket | null = null
  let lineId = 0

  function connect(runId: string) {
    disconnect()

    const url = getScriptOutputWebSocketUrl(runId)
    ws = new WebSocket(url)

    ws.onopen = () => {
      isConnected.value = true
      isRunning.value = true
      addLine('system', `Connected to run ${runId}`)
    }

    ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data)
        handleMessage(msg)
      } catch {
        addLine('stderr', event.data)
      }
    }

    ws.onclose = () => {
      isConnected.value = false
      isRunning.value = false
    }

    ws.onerror = () => {
      addLine('stderr', 'WebSocket connection error')
      isConnected.value = false
      isRunning.value = false
    }
  }

  function handleMessage(msg: { type: string; data?: string; returncode?: number; duration_ms?: number; message?: string }) {
    switch (msg.type) {
      case 'stdout':
        if (msg.data) addLine('stdout', msg.data)
        break
      case 'stderr':
        if (msg.data) addLine('stderr', msg.data)
        break
      case 'exit':
        isRunning.value = false
        lastReturnCode.value = msg.returncode ?? 0
        durationMs.value = msg.duration_ms ?? 0
        addLine('exit', `Process exited with code ${msg.returncode} (${msg.duration_ms}ms)`)
        break
      case 'error':
        addLine('stderr', `Error: ${msg.message}`)
        isRunning.value = false
        break
    }
  }

  function addLine(type: TerminalLine['type'], text: string) {
    lineId++
    lines.value.push({
      id: lineId,
      type,
      text: text.replace(/\n$/, ''), // Remove trailing newline
      timestamp: Date.now(),
    })
  }

  function disconnect() {
    if (ws) {
      ws.close()
      ws = null
    }
    isConnected.value = false
  }

  function clear() {
    lines.value = []
    lineId = 0
    lastReturnCode.value = null
    durationMs.value = null
  }

  onUnmounted(() => {
    disconnect()
  })

  return {
    lines,
    isConnected,
    isRunning,
    lastReturnCode,
    durationMs,
    connect,
    disconnect,
    clear,
    addLine,
  }
}
```

- [ ] **Step 2: Export from composables index**

Add to `frontend/src/composables/index.ts`:

```typescript
export * from './useScriptTerminal'
```

- [ ] **Step 3: Commit the composable**

```bash
git add frontend/src/composables/useScriptTerminal.ts frontend/src/composables/index.ts
git commit -m "feat(frontend): add useScriptTerminal composable

- WebSocket connection management for script output
- Terminal line state with type differentiation
- Auto-cleanup on unmount

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 6: Frontend Terminal Panel Component

**Files:**
- Create: `frontend/src/components/device/TerminalPanel.vue`

- [ ] **Step 1: Create the terminal panel component**

```vue
<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import { Delete, DocumentCopy, Check } from '@element-plus/icons-vue'
import type { TerminalLine } from '../../composables/useScriptTerminal'

const props = defineProps<{
  lines: TerminalLine[]
  isRunning: boolean
  isConnected: boolean
  lastReturnCode: number | null
  durationMs: number | null
}>()

const emit = defineEmits<{
  clear: []
  cancel: []
}>()

const terminalRef = ref<HTMLElement | null>(null)
const autoScroll = ref(true)
const copied = ref(false)

const statusText = computed(() => {
  if (props.isRunning) return 'Running...'
  if (props.lastReturnCode !== null) {
    return props.lastReturnCode === 0
      ? `Completed (${props.durationMs}ms)`
      : `Failed (code ${props.lastReturnCode})`
  }
  return 'Idle'
})

const statusClass = computed(() => {
  if (props.isRunning) return 'status-running'
  if (props.lastReturnCode === 0) return 'status-success'
  if (props.lastReturnCode !== null) return 'status-error'
  return ''
})

watch(() => props.lines.length, async () => {
  if (autoScroll.value) {
    await nextTick()
    if (terminalRef.value) {
      terminalRef.value.scrollTop = terminalRef.value.scrollHeight
    }
  }
})

function getLineClass(line: TerminalLine): string {
  switch (line.type) {
    case 'stdout': return 'line-stdout'
    case 'stderr': return 'line-stderr'
    case 'system': return 'line-system'
    case 'exit': return line.text.includes('code 0') ? 'line-exit-success' : 'line-exit-error'
    default: return ''
  }
}

async function copyOutput() {
  const text = props.lines.map(l => l.text).join('\n')
  await navigator.clipboard.writeText(text)
  copied.value = true
  setTimeout(() => { copied.value = false }, 2000)
}

function handleScroll() {
  if (!terminalRef.value) return
  const { scrollTop, scrollHeight, clientHeight } = terminalRef.value
  autoScroll.value = scrollTop + clientHeight >= scrollHeight - 10
}
</script>

<template>
  <div class="terminal-panel">
    <div class="terminal-header">
      <div class="terminal-status">
        <span class="status-indicator" :class="statusClass"></span>
        <span class="status-text">{{ statusText }}</span>
      </div>
      <div class="terminal-actions">
        <el-button
          v-if="isRunning"
          size="small"
          type="danger"
          @click="emit('cancel')"
        >
          Cancel
        </el-button>
        <el-tooltip content="Copy output" placement="top">
          <el-button size="small" :icon="copied ? Check : DocumentCopy" @click="copyOutput" />
        </el-tooltip>
        <el-tooltip content="Clear" placement="top">
          <el-button size="small" :icon="Delete" @click="emit('clear')" />
        </el-tooltip>
      </div>
    </div>
    <div
      ref="terminalRef"
      class="terminal-content"
      @scroll="handleScroll"
    >
      <div
        v-for="line in lines"
        :key="line.id"
        class="terminal-line"
        :class="getLineClass(line)"
      >
        {{ line.text }}
      </div>
      <div v-if="lines.length === 0" class="terminal-empty">
        No output yet. Run a script to see output here.
      </div>
    </div>
  </div>
</template>

<style scoped>
.terminal-panel {
  display: flex;
  flex-direction: column;
  background: #1e1e1e;
  border-top: 1px solid #333;
  min-height: 120px;
  max-height: 300px;
}

.terminal-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 6px 10px;
  background: #252526;
  border-bottom: 1px solid #333;
}

.terminal-status {
  display: flex;
  align-items: center;
  gap: 8px;
}

.status-indicator {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #666;
}

.status-indicator.status-running {
  background: #f0ad4e;
  animation: pulse 1s infinite;
}

.status-indicator.status-success {
  background: #5cb85c;
}

.status-indicator.status-error {
  background: #d9534f;
}

@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.5; }
}

.status-text {
  font-size: 12px;
  color: #ccc;
}

.terminal-actions {
  display: flex;
  gap: 4px;
}

.terminal-content {
  flex: 1;
  overflow: auto;
  padding: 8px 10px;
  font-family: 'Consolas', 'Monaco', 'Courier New', monospace;
  font-size: 12px;
  line-height: 1.5;
}

.terminal-line {
  white-space: pre-wrap;
  word-break: break-all;
}

.line-stdout {
  color: #d4d4d4;
}

.line-stderr {
  color: #f48771;
}

.line-system {
  color: #6a9955;
}

.line-exit-success {
  color: #4ec9b0;
}

.line-exit-error {
  color: #f14c14;
}

.terminal-empty {
  color: #666;
  font-style: italic;
}
</style>
```

- [ ] **Step 2: Commit the terminal panel**

```bash
git add frontend/src/components/device/TerminalPanel.vue
git commit -m "feat(frontend): add TerminalPanel component

- Dark terminal theme with syntax highlighting
- Auto-scroll with manual override
- Copy and clear actions
- Status indicator for running/completed/failed

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 7: Update Scripts Store

**Files:**
- Modify: `frontend/src/stores/scripts.ts`

- [ ] **Step 1: Add Python environment state**

Add imports at the top:

```typescript
import {
  fetchScripts,
  fetchScriptTree,
  fetchScript,
  createScript as apiCreateScript,
  createFolder as apiCreateFolder,
  saveScript as apiSaveScript,
  deleteScript as apiDeleteScript,
  deleteFolder as apiDeleteFolder,
  runScript as apiRunScript,
  runScriptStream as apiRunScriptStream,
  fetchPythonEnvs,
  cancelScriptRun,
  type ScriptFile,
  type ScriptRunResult,
  type FileTreeItem,
  type PythonEnvsResponse,
  type PythonEnvInfo,
} from '../api'
```

Add new state and actions in the store function:

```typescript
  // Python environment state
  const pythonEnvs = ref<PythonEnvsResponse | null>(null)
  const selectedPythonPath = ref<string>('')
  const activeRunId = ref<string | null>(null)

  async function loadPythonEnvs() {
    try {
      pythonEnvs.value = await fetchPythonEnvs()
      if (!selectedPythonPath.value && pythonEnvs.value) {
        selectedPythonPath.value = pythonEnvs.value.current
      }
    } catch (e) {
      console.error('Failed to load Python envs:', e)
    }
  }

  function selectPythonPath(path: string) {
    selectedPythonPath.value = path
  }

  async function runActiveScriptStream(
    deviceUdid: string,
    options: { platform?: string; wdaUrl?: string | null } = {},
  ) {
    if (!activeScript.value) return null
    running.value = true
    error.value = null
    try {
      const result = await apiRunScriptStream(activeScript.value.path, deviceUdid, {
        ...options,
        pythonEnv: selectedPythonPath.value || undefined,
      })
      activeRunId.value = result.run_id
      return result
    } catch (e) {
      error.value = e instanceof Error ? e.message : '运行脚本失败'
      return null
    } finally {
      running.value = false
    }
  }

  async function cancelActiveRun() {
    if (!activeRunId.value) return
    try {
      await cancelScriptRun(activeRunId.value)
      activeRunId.value = null
    } catch (e) {
      console.error('Failed to cancel run:', e)
    }
  }
```

Add to the return statement:

```typescript
    pythonEnvs,
    selectedPythonPath,
    activeRunId,
    loadPythonEnvs,
    selectPythonPath,
    runActiveScriptStream,
    cancelActiveRun,
```

- [ ] **Step 2: Commit the store updates**

```bash
git add frontend/src/stores/scripts.ts
git commit -m "feat(frontend): add Python env state to scripts store

- pythonEnvs, selectedPythonPath, activeRunId state
- loadPythonEnvs, selectPythonPath actions
- runActiveScriptStream for streaming execution
- cancelActiveRun to stop running script

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 8: Integrate Terminal Panel in DeviceManager

**Files:**
- Modify: `frontend/src/views/DeviceManager.vue`

- [ ] **Step 1: Add imports**

Add to imports section (around line 42):

```typescript
import TerminalPanel from '../components/device/TerminalPanel.vue'
import { useScriptTerminal } from '../composables'
```

- [ ] **Step 2: Add terminal composable and state**

Add after `const scriptStore = useScriptStore()`:

```typescript
// Script terminal
const terminal = useScriptTerminal()
```

- [ ] **Step 3: Update runActiveScript function**

Replace the existing `runActiveScript` function (around line 1158):

```typescript
async function runActiveScript() {
  if (!activeScriptPath.value || !deviceStore.activeDevice) return
  scriptStore.scriptContent = activeScriptContent.value ?? ''
  if (scriptStore.activeScript?.path !== activeScriptPath.value) {
    const sf = scriptStore.scripts.find(s => s.path === activeScriptPath.value)
    if (sf) scriptStore.activeScript = sf
  }
  terminal.clear()
  const result = await scriptStore.runActiveScriptStream(deviceStore.activeDevice.udid, {
    platform: deviceStore.activeDevice.platform,
    wdaUrl: deviceStore.activeDevice.wda_url ?? null,
  })
  if (result) {
    terminal.connect(result.run_id)
  } else if (scriptStore.error) {
    ElMessage.error(scriptStore.error)
  }
}
```

- [ ] **Step 4: Add cancel function**

Add after `runActiveScript`:

```typescript
async function cancelScriptRun() {
  await scriptStore.cancelActiveRun()
  terminal.addLine('system', 'Script execution cancelled')
}
```

- [ ] **Step 5: Add Python env selector in toolbar**

Replace the toolbar section in the editor (around line 1508-1528) with:

```vue
<div class="script-editor-toolbar">
  <div class="toolbar-left">
    <el-button
      size="small"
      type="primary"
      :disabled="!activeScriptDirty"
      :loading="scriptStore.saving"
      @click="saveActiveScript"
    >
      保存
    </el-button>
    <el-button
      size="small"
      type="primary"
      :disabled="!deviceStore.activeDevice"
      :loading="terminal.isRunning"
      @click="runActiveScript"
    >
      ▶ Run
    </el-button>
    <el-select
      v-model="scriptStore.selectedPythonPath"
      size="small"
      placeholder="Python环境"
      style="width: 140px"
      @focus="scriptStore.loadPythonEnvs()"
    >
      <el-option
        v-for="env in scriptStore.pythonEnvs?.envs ?? []"
        :key="env.path"
        :label="env.name"
        :value="env.path"
      />
    </el-select>
  </div>
  <div class="toolbar-right">
    <!-- existing zoom and line number buttons -->
  </div>
</div>
```

- [ ] **Step 6: Replace run-output with TerminalPanel**

Replace the `run-output` div (around line 1563-1566) with:

```vue
<TerminalPanel
  :lines="terminal.lines.value"
  :is-running="terminal.isRunning.value"
  :is-connected="terminal.isConnected.value"
  :last-return-code="terminal.lastReturnCode.value"
  :duration-ms="terminal.durationMs.value"
  @clear="terminal.clear()"
  @cancel="cancelScriptRun()"
/>
```

- [ ] **Step 7: Load Python envs on mount**

Add to `onMounted` callback (around line 1207):

```typescript
onMounted(() => {
  loadDevices()
  scriptStore.loadScriptTree()
  scriptStore.loadPythonEnvs()
  startPolling()
})
```

- [ ] **Step 8: Commit DeviceManager changes**

```bash
git add frontend/src/views/DeviceManager.vue
git commit -m "feat(frontend): integrate terminal panel in DeviceManager

- Replace static output with TerminalPanel
- Add Python environment selector dropdown
- Use streaming execution for Run button
- Add cancel button for running scripts

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 9: Update AutoExecutePanel for Streaming Playback

**Files:**
- Modify: `frontend/src/views/DeviceManager.vue`

- [ ] **Step 1: Update playbackRecording function**

Replace the existing `playbackRecording` function (around line 877):

```typescript
async function playbackRecording() {
  if (!deviceStore.activeDevice) {
    ElMessage.warning('请先选择一个设备')
    return
  }
  if (!activeScriptPath.value) {
    ElMessage.warning('请先打开一个脚本文件')
    return
  }
  if (activeScriptDirty.value) {
    ElMessage.warning('请先保存当前脚本')
    return
  }

  autoExecutePlaying.value = true
  terminal.clear()
  try {
    ElMessage.info('开始回放脚本...')
    const result = await scriptStore.runActiveScriptStream(deviceStore.activeDevice.udid, {
      platform: deviceStore.activeDevice.platform,
      wdaUrl: deviceStore.activeDevice.wda_url ?? null,
    })
    if (result) {
      terminal.connect(result.run_id)
      // Wait for completion
      const unwatch = watch(terminal.isRunning, (running) => {
        if (!running) {
          autoExecutePlaying.value = false
          if (terminal.lastReturnCode.value === 0) {
            ElMessage.success('脚本回放完成')
          } else {
            ElMessage.error(`脚本回放失败: code ${terminal.lastReturnCode.value}`)
          }
          unwatch()
        }
      })
    }
  } catch (error) {
    autoExecutePlaying.value = false
    ElMessage.error(error instanceof Error ? error.message : '脚本回放失败')
  }
}
```

- [ ] **Step 2: Add watch import if not present**

Check if `watch` is already imported from Vue. If not, add it:

```typescript
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
```

- [ ] **Step 3: Commit the playback update**

```bash
git add frontend/src/views/DeviceManager.vue
git commit -m "feat(frontend): use streaming execution for script playback

- playbackRecording now uses runActiveScriptStream
- Terminal shows real-time output during playback
- Status updates on completion

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 10: End-to-End Testing

**Files:**
- None (manual testing)

- [ ] **Step 1: Start the backend server**

```bash
cd D:/Mobile-AI-TestOps/backend
python -m uvicorn app.main:app --reload --port 8000
```

- [ ] **Step 2: Start the frontend dev server**

```bash
cd D:/Mobile-AI-TestOps/frontend
npm run dev
```

- [ ] **Step 3: Test Python environment switching**

1. Open the app in browser
2. Open a script file
3. Click the Python environment dropdown
4. Verify available environments are listed
5. Select a different environment
6. Run the script and verify it uses the selected Python

- [ ] **Step 4: Test real-time terminal output**

1. Create a test script with print statements and sleep:
```python
import time
print("Starting test...")
for i in range(5):
    print(f"Step {i+1}")
    time.sleep(1)
print("Done!")
```
2. Run the script
3. Verify output appears line by line in the terminal panel
4. Verify status indicator shows "Running..."
5. Verify status changes to "Completed" when done

- [ ] **Step 5: Test cancel functionality**

1. Create a long-running script:
```python
import time
print("Starting long task...")
for i in range(100):
    print(f"Step {i+1}")
    time.sleep(1)
```
2. Run the script
3. Click "Cancel" button
4. Verify script stops and status shows "Failed" or "Cancelled"

- [ ] **Step 6: Test playback from AutoExecutePanel**

1. Record a simple script using the AutoExecute recording feature
2. Save the script
3. Click "录制回放" button
4. Verify terminal shows real-time output during playback

---

## Self-Review Checklist

**1. Spec coverage:**
- ✅ Python env switching: Task 3 (GET /python-envs), Task 7 (store), Task 8 (UI)
- ✅ Real-time terminal: Task 1-2 (backend), Task 5-6 (frontend), Task 8 (integration)
- ✅ WebSocket streaming: Task 3 (endpoint), Task 5 (composable)
- ✅ Cancel functionality: Task 3 (endpoint), Task 8 (UI)

**2. Placeholder scan:**
- No TBD, TODO, or vague instructions found
- All code blocks contain complete implementations

**3. Type consistency:**
- `ScriptRunStreamStart` used consistently in backend and frontend
- `PythonEnvsResponse` / `PythonEnvInfo` match between API and store
- `TerminalLine` type defined in composable and used in component
