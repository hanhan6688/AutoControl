"""StepRunner — executes a sequence of Steps with event streaming."""

from __future__ import annotations

import os
from typing import Iterator

from app.automation.core.driver import DeviceDriver
from app.automation.core.models import Step
from app.automation.runner.events import RunEvent, RunEventType
from app.automation.waits.engine import WaitEngine
from app.automation.assertions.engine import AssertionEngine
from app.automation.reports.evidence import EvidenceCollector


class StepRunner:
    """Executes Steps sequentially, yielding RunEvents at each phase."""

    def __init__(self, driver: DeviceDriver, output_dir: str = "/tmp/automation_run", expected_app: str = "") -> None:
        self._driver = driver
        self._output_dir = output_dir
        self._expected_app = expected_app
        self._wait_engine = WaitEngine(driver)
        self._assertion_engine = AssertionEngine(driver)
        self._evidence_collector: EvidenceCollector | None = None

    def run(self, steps: list[Step]) -> Iterator[RunEvent]:
        os.makedirs(self._output_dir, exist_ok=True)
        self._evidence_collector = EvidenceCollector(self._driver, self._output_dir)

        yield RunEvent(event_type=RunEventType.RUN_STARTED, message="Run started")

        for step in steps:
            yield from self._run_step(step)

        yield RunEvent(event_type=RunEventType.RUN_FINISHED, message="Run finished")

    def _run_step(self, step: Step) -> Iterator[RunEvent]:
        yield RunEvent(event_type=RunEventType.STEP_STARTED, step_id=step.id, step_title=step.title, message=f"Step {step.id}: {step.title}")

        # Before wait
        if step.before_wait is not None:
            yield RunEvent(event_type=RunEventType.WAIT_STARTED, step_id=step.id, message=f"Before wait: {step.before_wait.type.value}")
            self._wait_engine.wait(step.before_wait, expected_app=self._expected_app)

        # Action
        self._execute_action(step)
        yield RunEvent(event_type=RunEventType.ACTION_EXECUTED, step_id=step.id, message=f"Action {step.action.type.value} executed")

        # After wait
        if step.after_wait is not None:
            yield RunEvent(event_type=RunEventType.WAIT_STARTED, step_id=step.id, message=f"After wait: {step.after_wait.type.value}")
            self._wait_engine.wait(step.after_wait, expected_app=self._expected_app)

        # Assertions
        for assertion in step.assertions:
            result = self._assertion_engine.evaluate(assertion)
            if result.passed:
                yield RunEvent(event_type=RunEventType.ASSERTION_PASSED, step_id=step.id, message=result.message)
            else:
                yield RunEvent(event_type=RunEventType.ASSERTION_FAILED, step_id=step.id, message=result.message)

        # Evidence
        if self._evidence_collector is not None:
            evidence = self._evidence_collector.capture(step.id)
            yield RunEvent(
                event_type=RunEventType.EVIDENCE_SAVED,
                step_id=step.id,
                message=f"Evidence captured: screenshot={evidence.screenshot_path}",
                data={"screenshot_path": evidence.screenshot_path, "source_dump_path": evidence.source_dump_path},
            )

    def _execute_action(self, step: Step) -> None:
        action = step.action
        atype = action.type
        params = action.params

        if atype.value == "tap":
            x = params.get("x", 0)
            y = params.get("y", 0)
            self._driver.tap(x, y)
        elif atype.value == "long_press":
            x = params.get("x", 0)
            y = params.get("y", 0)
            duration = params.get("duration_ms", 1000)
            self._driver.long_press(x, y, duration)
        elif atype.value == "swipe":
            sx = params.get("start_x", 0)
            sy = params.get("start_y", 0)
            ex = params.get("end_x", 0)
            ey = params.get("end_y", 0)
            duration = params.get("duration_ms", 300)
            self._driver.swipe(sx, sy, ex, ey, duration)
        elif atype.value == "input":
            text = params.get("text", "")
            self._driver.input_text(text)
        elif atype.value == "press_key":
            key = params.get("key", "")
            self._driver.press_key(key)
        elif atype.value == "launch":
            app_id = params.get("app_id", "")
            self._driver.launch(app_id)
        elif atype.value == "stop_app":
            app_id = params.get("app_id", "")
            self._driver.stop_app(app_id)
