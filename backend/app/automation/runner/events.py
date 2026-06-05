"""Run event dataclasses for the automation runner."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class RunEventType(str, Enum):
    RUN_STARTED = "run_started"
    RUN_FINISHED = "run_finished"
    STEP_STARTED = "step_started"
    WAIT_STARTED = "wait_started"
    ACTION_EXECUTED = "action_executed"
    ASSERTION_PASSED = "assertion_passed"
    ASSERTION_FAILED = "assertion_failed"
    EVIDENCE_SAVED = "evidence_saved"


@dataclass(frozen=True)
class RunEvent:
    event_type: RunEventType
    step_id: str = ""
    step_title: str = ""
    message: str = ""
    data: dict[str, Any] = field(default_factory=dict)
