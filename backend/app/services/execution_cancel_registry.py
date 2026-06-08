from __future__ import annotations

import subprocess
import threading
from dataclasses import dataclass, field


@dataclass
class ExecutionCancelToken:
    run_id: str
    cancelled: bool = False
    processes: list[subprocess.Popen] = field(default_factory=list)


class ExecutionCancelRegistry:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._tokens: dict[str, ExecutionCancelToken] = {}

    def get_or_create(self, run_id: str | None) -> ExecutionCancelToken | None:
        if not run_id:
            return None
        with self._lock:
            token = self._tokens.get(run_id)
            if token is None:
                token = ExecutionCancelToken(run_id=run_id)
                self._tokens[run_id] = token
            return token

    def register_process(self, run_id: str | None, process: subprocess.Popen) -> None:
        token = self.get_or_create(run_id)
        if token is None:
            return
        with self._lock:
            token.processes.append(process)
            if token.cancelled and process.poll() is None:
                process.kill()

    def unregister_process(self, run_id: str | None, process: subprocess.Popen) -> None:
        if not run_id:
            return
        with self._lock:
            token = self._tokens.get(run_id)
            if token and process in token.processes:
                token.processes.remove(process)

    def cancel(self, run_id: str) -> bool:
        with self._lock:
            token = self._tokens.get(run_id)
            if token is None:
                token = ExecutionCancelToken(run_id=run_id, cancelled=True)
                self._tokens[run_id] = token
                return False
            token.cancelled = True
            processes = list(token.processes)

        killed = False
        for process in processes:
            if process.poll() is None:
                process.kill()
                killed = True
        return killed

    def send_input(self, run_id: str, text: str) -> bool:
        with self._lock:
            token = self._tokens.get(run_id)
            processes = list(token.processes) if token else []

        sent = False
        for process in processes:
            if process.poll() is not None or process.stdin is None:
                continue
            try:
                process.stdin.write(text)
                process.stdin.flush()
                sent = True
            except (OSError, ValueError):
                continue
        return sent

    def is_cancelled(self, run_id: str | None) -> bool:
        if not run_id:
            return False
        with self._lock:
            token = self._tokens.get(run_id)
            return bool(token and token.cancelled)

    def cleanup(self, run_id: str | None) -> None:
        if not run_id:
            return
        with self._lock:
            token = self._tokens.get(run_id)
            if token and not token.processes and not token.cancelled:
                self._tokens.pop(run_id, None)


execution_cancel_registry = ExecutionCancelRegistry()
