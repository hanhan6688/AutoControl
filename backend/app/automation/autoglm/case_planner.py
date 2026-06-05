"""CaseTaskPlan — structured plan for checkpoint-based AutoGLM execution."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Checkpoint:
    id: str
    goal: str
    instructions: list[str] = field(default_factory=list)
    success_signals: list[str] = field(default_factory=list)
    failure_signals: list[str] = field(default_factory=list)
    takeover_signals: list[str] = field(default_factory=list)
    allowed_actions: list[str] = field(default_factory=lambda: ["tap", "swipe", "input", "back", "home", "wait"])
    max_steps: int = 12

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "goal": self.goal,
            "instructions": list(self.instructions),
            "success_signals": list(self.success_signals),
            "failure_signals": list(self.failure_signals),
            "takeover_signals": list(self.takeover_signals),
            "allowed_actions": list(self.allowed_actions),
            "max_steps": self.max_steps,
        }


@dataclass(frozen=True)
class CaseTaskPlan:
    case_id: int
    target_app: str
    platform: str
    launch_app_id: str = ""
    preconditions: list[str] = field(default_factory=list)
    checkpoints: list[Checkpoint] = field(default_factory=list)
    final_expectations: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "target_app": self.target_app,
            "platform": self.platform,
            "launch_app_id": self.launch_app_id,
            "preconditions": list(self.preconditions),
            "checkpoints": [cp.to_dict() for cp in self.checkpoints],
            "final_expectations": list(self.final_expectations),
        }


class CasePlanner:
    """Builds a CaseTaskPlan from raw case data."""

    def build(
        self,
        *,
        case_id: int,
        target_app: str,
        platform: str,
        launch_app_id: str = "",
        preconditions: list[str] | None = None,
        steps: list[str] | None = None,
        expected_result: str = "",
    ) -> CaseTaskPlan:
        checkpoints = self._derive_checkpoints(steps or [], expected_result)
        return CaseTaskPlan(
            case_id=case_id,
            target_app=target_app,
            platform=platform,
            launch_app_id=launch_app_id,
            preconditions=preconditions or [],
            checkpoints=checkpoints,
            final_expectations=[expected_result] if expected_result else [],
        )

    def _derive_checkpoints(self, steps: list[str], expected_result: str) -> list[Checkpoint]:
        if not steps:
            return [Checkpoint(id="cp_1", goal="完成任务", instructions=["执行用例"], success_signals=[expected_result or "任务完成"], max_steps=15)]

        checkpoints: list[Checkpoint] = []
        for idx, step in enumerate(steps, start=1):
            checkpoints.append(
                Checkpoint(
                    id=f"cp_{idx}",
                    goal=step,
                    instructions=[step],
                    success_signals=[f"完成: {step}"],
                    max_steps=12,
                )
            )
        return checkpoints
