"""JudgeService — deterministic + AI verdict for AutoGLM execution results."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class JudgeResult:
    verdict: str
    confidence: float = 0.0
    reason: str = ""


class JudgeService:
    """Determines the final verdict based on checkpoint results and device state."""

    def determine(self, checkpoints_passed: int, total_checkpoints: int, final_app: str, expected_app: str) -> JudgeResult:
        if final_app != expected_app:
            return JudgeResult(verdict="failed", confidence=0.9, reason=f"Final app mismatch: expected {expected_app}, got {final_app}")

        if checkpoints_passed == total_checkpoints and total_checkpoints > 0:
            return JudgeResult(verdict="passed", confidence=0.85, reason="All checkpoints passed and app is correct")

        if checkpoints_passed == 0:
            return JudgeResult(verdict="failed", confidence=0.8, reason="No checkpoints passed")

        return JudgeResult(verdict="uncertain", confidence=0.5, reason=f"Partial progress: {checkpoints_passed}/{total_checkpoints} checkpoints passed")
