from __future__ import annotations

import subprocess
from dataclasses import dataclass

from app.config import settings


class ScrcpyError(RuntimeError):
    pass


@dataclass(frozen=True)
class ScrcpySession:
    udid: str
    pid: int
    command: list[str]


class ScrcpyService:
    _processes: dict[str, subprocess.Popen[bytes]] = {}

    def __init__(self, scrcpy_path: str | None = None) -> None:
        self.scrcpy_path = scrcpy_path or settings.resolved_scrcpy_path

    def start(self, udid: str, max_size: int = 1280, max_fps: int = 30) -> ScrcpySession:
        existing = self._processes.get(udid)
        if existing and existing.poll() is None:
            return ScrcpySession(udid=udid, pid=existing.pid, command=existing.args)  # type: ignore[arg-type]

        command = [
            self.scrcpy_path,
            "--serial",
            udid,
            "--max-size",
            str(max_size),
            "--max-fps",
            str(max_fps),
            "--window-title",
            f"Mobile AI TestOps - {udid}",
            "--stay-awake",
        ]

        try:
            process = subprocess.Popen(command)
        except OSError as exc:
            raise ScrcpyError(f"failed to start scrcpy: {exc}") from exc

        self._processes[udid] = process
        return ScrcpySession(udid=udid, pid=process.pid, command=command)

    def stop(self, udid: str) -> bool:
        process = self._processes.get(udid)
        if process is None:
            return False

        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()

        self._processes.pop(udid, None)
        return True

    def status(self, udid: str) -> dict[str, object]:
        process = self._processes.get(udid)
        if process is None:
            return {"running": False, "pid": None}

        running = process.poll() is None
        if not running:
            self._processes.pop(udid, None)
        return {"running": running, "pid": process.pid if running else None}
