"""CheckpointValidator — validates whether a checkpoint's success/failure signals are met."""

from __future__ import annotations

from dataclasses import dataclass

from app.automation.autoglm.case_planner import Checkpoint


@dataclass(frozen=True)
class ValidationResult:
    passed: bool = False
    failed: bool = False
    message: str = ""


class CheckpointValidator:
    """Validates checkpoint success/failure signals against device state."""

    def validate(self, checkpoint: Checkpoint, source_xml: str = "", foreground_app: str = "") -> ValidationResult:
        for signal in checkpoint.failure_signals:
            if signal in source_xml:
                return ValidationResult(passed=False, failed=True, message=f"Failure signal detected: {signal}")

        for signal in checkpoint.success_signals:
            if signal in source_xml:
                return ValidationResult(passed=True, failed=False, message=f"Success signal matched: {signal}")

        return ValidationResult(passed=False, failed=False, message="No success signal matched")
