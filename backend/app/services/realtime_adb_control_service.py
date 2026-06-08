"""Low-latency Android control using a persistent adb shell."""

from __future__ import annotations

import subprocess
import threading

from app.config import settings


class RealtimeAdbControlService:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._shells: dict[str, subprocess.Popen[str]] = {}

    def send(self, udid: str, command: str) -> None:
        process = self._get_shell(udid)
        try:
            assert process.stdin is not None
            process.stdin.write(f"{command}\n")
            process.stdin.flush()
        except (OSError, ValueError):
            self.close(udid)
            process = self._get_shell(udid)
            assert process.stdin is not None
            process.stdin.write(f"{command}\n")
            process.stdin.flush()

    def close(self, udid: str) -> None:
        with self._lock:
            process = self._shells.pop(udid, None)
        if process is None:
            return
        if process.stdin is not None:
            try:
                process.stdin.close()
            except OSError:
                pass
        if process.poll() is None:
            process.terminate()

    def _get_shell(self, udid: str) -> subprocess.Popen[str]:
        with self._lock:
            process = self._shells.get(udid)
            if process is not None and process.poll() is None and process.stdin is not None:
                return process

            process = subprocess.Popen(
                [settings.resolved_adb_path, "-s", udid, "shell"],
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
            )
            self._shells[udid] = process
            return process


realtime_adb_control_service = RealtimeAdbControlService()
