"""Tests for ExecutionSupervisor — checkpoint-based AutoGLM execution."""

from unittest.mock import MagicMock

from app.automation.autoglm.case_planner import CaseTaskPlan, Checkpoint
from app.automation.autoglm.execution_supervisor import ExecutionSupervisor
from app.automation.core.driver import DeviceDriver


def _make_driver() -> MagicMock:
    driver = MagicMock(spec=DeviceDriver)
    driver.current_app.return_value = {"package": "com.demo.app"}
    driver.screenshot.return_value = b"\x89PNG"
    driver.dump_source.return_value = "<node text='首页'/>"
    return driver


class TestExecutionSupervisor:
    def test_run_all_checkpoints(self):
        driver = _make_driver()
        plan = CaseTaskPlan(
            case_id=123,
            target_app="Demo",
            platform="android",
            checkpoints=[
                Checkpoint(id="cp_1", goal="进入首页", success_signals=["首页"], max_steps=12),
            ],
        )
        supervisor = ExecutionSupervisor(driver)
        result = supervisor.run(plan)
        assert result is not None

    def test_preflight_checks_device(self):
        driver = _make_driver()
        supervisor = ExecutionSupervisor(driver)
        assert supervisor.preflight() is True
