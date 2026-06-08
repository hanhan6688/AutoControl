"""Script execution service with subprocess and WebSocket streaming."""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import sys
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


_active_runs: dict[str, ScriptRun] = {}


def generate_preamble(
    device_udid: str,
    platform: str,
    wda_url: str | None,
    script_type: str = "mobile",
    session: str | None = None,
) -> str:
    """Generate Python preamble that sets up runtime objects."""
    backend_dir = settings.backend_dir.as_posix()
    if script_type == "pc":
        return f'''
import sys
import os
sys.path.insert(0, r"{backend_dir}")
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
sys.path.insert(0, r"{backend_dir}")
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
    message = json.dumps({"type": msg_type, "data": data})
    dead = []
    for ws in run.ws_connections:
        try:
            await ws.send_text(message)
        except Exception:
            dead.append(ws)
    for ws in dead:
        run.ws_connections.remove(ws)


async def broadcast_exit(run: ScriptRun, returncode: int, duration_ms: int) -> None:
    """Broadcast exit event to all connected WebSocket clients."""
    message = json.dumps({"type": "exit", "returncode": returncode, "duration_ms": duration_ms})
    for ws in run.ws_connections[:]:
        try:
            await ws.send_text(message)
        except Exception:
            pass


async def broadcast_error(run: ScriptRun, message: str) -> None:
    """Broadcast error event to all connected WebSocket clients."""
    msg = json.dumps({"type": "error", "message": message})
    for ws in run.ws_connections[:]:
        try:
            await ws.send_text(msg)
        except Exception:
            pass


async def execute_script_streaming(
    run: ScriptRun,
    script_path: Path,
    script_type: str = "mobile",
    session: str | None = None,
) -> None:
    """Execute script via subprocess and stream output via WebSocket."""
    python = run.python_path or settings.resolved_python_path

    preamble = generate_preamble(
        device_udid=run.device_udid,
        platform=run.platform,
        wda_url=run.wda_url,
        script_type=script_type,
        session=session,
    )
    user_script = script_path.read_text(encoding="utf-8")
    full_script = preamble + "\n\n# User script:\n" + user_script

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".py", delete=False, encoding="utf-8",
    ) as tmp:
        tmp.write(full_script)
        tmp_path = Path(tmp.name)

    try:
        env = os.environ.copy()
        adb_dir = str(Path(settings.resolved_adb_path).resolve().parent)
        env["PATH"] = f"{adb_dir}{os.pathsep}{env.get('PATH', '')}"
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUTF8"] = "1"

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

        loop = asyncio.get_event_loop()

        async def read_stream(stream, msg_type: str):
            try:
                while True:
                    line = await loop.run_in_executor(None, stream.readline)
                    if not line:
                        break
                    await broadcast_output(run, msg_type, line)
            except Exception:
                pass

        await asyncio.gather(
            read_stream(proc.stdout, "stdout"),
            read_stream(proc.stderr, "stderr"),
        )

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
    envs = []

    def add_env(name: str, path: str | Path | None) -> None:
        if not path:
            return
        resolved = str(Path(path).resolve())
        if any(str(Path(env["path"]).resolve()).lower() == resolved.lower() for env in envs):
            return
        envs.append({"name": name, "path": resolved})

    system_python = shutil.which("python") or shutil.which("python3")
    if system_python:
        add_env("System Python", system_python)

    if settings.venv_dir:
        venv_python = settings.venv_dir / "Scripts" / "python.exe"
        if venv_python.exists():
            add_env(f"venv ({settings.venv_dir.name})", venv_python)

    project_venv_python = settings.project_root / ".venv" / "Scripts" / "python.exe"
    if project_venv_python.exists():
        add_env("Project venv (.venv)", project_venv_python)

    current = settings.resolved_python_path
    add_env("Current Backend Python", current)

    return {
        "current": current,
        "default": system_python or sys.executable,
        "envs": envs,
    }
