# Script Execution: Python Env Switch + Real-time Terminal

## Problem

1. Script execution uses `exec()` in the current process — no way to switch Python environments
2. No terminal panel for real-time output display — results only shown after execution completes as static `<pre>` blocks

## Solution

Replace `exec()` with `subprocess.Popen` using the configured Python interpreter, add a WebSocket-based real-time terminal panel.

## Architecture

```
Frontend                          Backend
┌──────────────┐                  ┌──────────────────────┐
│ Python Env   │  POST /run-stream│ Script Run Manager   │
│ Dropdown     │─────────────────►│ subprocess.Popen()   │
│              │  {run_id}        │ resolved_python_path │
├──────────────┤                  ├──────────────────────┤
│ Terminal     │  WS /ws/output/  │ WebSocket Handler    │
│ Panel        │◄─────────────────│ stdout/stderr stream │
│ (real-time)  │  {type,data}     │ exit event           │
└──────────────┘                  └──────────────────────┘
```

## Backend Changes

### New endpoint: `POST /api/scripts/{path}/run-stream`

Launches script via subprocess, returns `run_id`.

Request params: `device_udid`, `platform`, `wda_url`, `python_env` (optional override path)

Response: `{ "run_id": "abc123", "python_path": "/path/to/python" }`

### New WebSocket: `GET /ws/script-output/{run_id}`

Messages pushed to client:
- `{"type": "stdout", "data": "line of output\n"}`
- `{"type": "stderr", "data": "error line\n"}`
- `{"type": "exit", "returncode": 0, "duration_ms": 1234}`

### New endpoint: `GET /api/scripts/python-envs`

Returns list of available Python environments:
```json
{
  "current": "/path/to/active/python",
  "default": "/usr/bin/python3",
  "envs": [
    { "name": "System Python", "path": "/usr/bin/python3" },
    { "name": "venv (configured)", "path": "/path/to/venv/Scripts/python.exe" }
  ]
}
```

### Script execution via subprocess

```python
async def _run_script_subprocess(
    file_path: Path,
    device_udid: str,
    run_id: str,
    *,
    python_path: str | None = None,
    platform: str = "android",
    wda_url: str | None = None,
) -> None:
    python = python_path or settings.resolved_python_path
    env = os.environ.copy()
    env["PATH"] = f"{adb_dir}{os.pathsep}{env.get('PATH', '')}"

    proc = subprocess.Popen(
        [python, str(file_path), device_udid],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
    )
    # Stream stdout/stderr via WebSocket
```

Scripts still receive runtime objects (`adb`, `ocr`, `auto_execute`, etc.) by injecting a preamble that sets them up before the user's code runs. The preamble is generated from the current `globals_dict` setup and prepended to the script.

### Run state management

```python
@dataclass
class ScriptRun:
    id: str
    path: str
    device_udid: str
    platform: str
    python_path: str
    status: str  # "running" | "completed" | "failed" | "cancelled"
    process: subprocess.Popen
    started_at: float
    completed_at: float | None = None
    returncode: int | None = None
    ws_connections: list[WebSocket] = field(default_factory=list)

_active_runs: dict[str, ScriptRun] = {}
```

### Runtime injection preamble

Since we move from `exec()` to subprocess, the runtime objects (`adb`, `ocr`, `image`, `auto_execute`, `ui`, `input`, `browser`, etc.) need to be available in the subprocess. Strategy:

- Generate a Python preamble that imports the backend's service modules and creates the same runtime objects
- Write temp file = preamble + user script, execute the temp file
- Alternatively: add a `--preamble` mechanism or use `sys.path` injection

Chosen approach: **Preamble injection**. The backend generates a setup code block that creates all runtime objects, writes a combined file to a temp location, and runs it. This keeps the subprocess simple while preserving all existing script APIs.

## Frontend Changes

### New component: `TerminalPanel.vue`

Features:
- Dark background, monospace font
- ANSI color code rendering (xterm.js-lite or manual parsing)
- Auto-scroll to bottom
- Clear / Copy buttons
- Connection status indicator
- Resize handle

Props: `runId: string | null`

Events: `@close`, `@completed(returncode: number)`

### Modified: `DeviceManager.vue`

- Add Python env dropdown in editor toolbar (next to Run button)
- Replace static `run-output` div with `TerminalPanel`
- Run button calls `/run-stream` API then connects WebSocket
- Dropdown fetches envs from `/api/scripts/python-envs`

### Modified: `AutoExecutePanel.vue`

- Playback uses the same streaming execution
- Show mini terminal output or status indicator during playback

### Modified: `api.ts`

Add functions:
- `runScriptStream(path, udid, options)` → `{ run_id, python_path }`
- `fetchPythonEnvs()` → `{ current, default, envs[] }`
- WebSocket URL helper: `getScriptOutputWsUrl(runId)`

### Modified: `scripts.ts` store

Add:
- `pythonEnvs` ref
- `selectedPythonPath` ref
- `activeRunId` ref
- `loadPythonEnvs()` action

## WebSocket Message Protocol

```
Client → Server:
  (none — client only receives)

Server → Client:
  {"type": "stdout", "data": "text\n"}
  {"type": "stderr", "data": "text\n"}
  {"type": "exit", "returncode": 0, "duration_ms": 1234}
  {"type": "error", "message": "Script launch failed: ..."}
```

## Error Handling

- Subprocess launch failure → push `{"type": "error", ...}` and close WebSocket
- Client disconnect → keep process running, discard output (no replay on reconnect)
- Process timeout → kill after configurable duration, push exit event
- Multiple clients → broadcast to all connected WebSocket clients for same `run_id`

## Backward Compatibility

- Keep existing `POST /api/scripts/{path}/run` endpoint (sync exec) for API consumers
- New `POST /api/scripts/{path}/run-stream` is the streaming variant
- Frontend migrates to streaming by default
