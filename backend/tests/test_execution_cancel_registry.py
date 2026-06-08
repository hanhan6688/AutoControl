from __future__ import annotations

import subprocess
import sys


def test_execution_cancel_registry_can_send_resume_input() -> None:
    from app.services.execution_cancel_registry import ExecutionCancelRegistry

    process = subprocess.Popen(
        [
            sys.executable,
            "-c",
            (
                "import sys\n"
                "print('ready', flush=True)\n"
                "line = sys.stdin.readline()\n"
                "print('got:' + line.strip(), flush=True)\n"
            ),
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
    )
    registry = ExecutionCancelRegistry()
    try:
        registry.register_process("run-1", process)
        assert process.stdout is not None
        assert process.stdout.readline().strip() == "ready"

        assert registry.send_input("run-1", "\n") is True
        assert process.stdout.readline().strip() == "got:"
        assert process.wait(timeout=5) == 0
    finally:
        if process.poll() is None:
            process.kill()


def test_execution_cancel_registry_send_input_returns_false_without_process() -> None:
    from app.services.execution_cancel_registry import ExecutionCancelRegistry

    assert ExecutionCancelRegistry().send_input("missing", "\n") is False
