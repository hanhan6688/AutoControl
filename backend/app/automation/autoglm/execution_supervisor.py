"""ExecutionSupervisor — drives AutoGLM through checkpoint-based execution."""

from __future__ import annotations

from app.automation.autoglm.case_planner import CaseTaskPlan, Checkpoint
from app.automation.autoglm.checkpoint_validator import CheckpointValidator
from app.automation.autoglm.prompt_builder import PromptBuilder
from app.automation.autoglm.repair_service import RepairService
from app.automation.autoglm.state_probe import StateProbe
from app.automation.core.driver import DeviceDriver


class ExecutionSupervisor:
    """Executes a CaseTaskPlan checkpoint by checkpoint with validation and repair."""

    def __init__(self, driver: DeviceDriver) -> None:
        self._driver = driver
        self._probe = StateProbe(driver)
        self._validator = CheckpointValidator()
        self._repair = RepairService(driver)
        self._prompt_builder = PromptBuilder()

    def preflight(self) -> bool:
        """Verify device is ready before starting execution."""
        try:
            self._driver.screenshot()
            self._driver.dump_source()
            return True
        except Exception:
            return False

    def run(self, plan: CaseTaskPlan) -> dict:
        """Run all checkpoints and return execution summary."""
        results = []
        for checkpoint in plan.checkpoints:
            state = self._probe.collect()
            prompt = self._prompt_builder.build(checkpoint, plan.platform, plan.target_app)
            validation = self._validator.validate(checkpoint, source_xml=state.source_xml)
            results.append({
                "checkpoint_id": checkpoint.id,
                "passed": validation.passed,
                "failed": validation.failed,
                "message": validation.message,
            })
        return {"checkpoints": results, "all_passed": all(r["passed"] for r in results)}
