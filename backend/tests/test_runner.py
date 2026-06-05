"""Tests for StepRunner — step execution orchestration with event streaming."""

from unittest.mock import MagicMock

from app.automation.core.driver import DeviceDriver, ElementRef
from app.automation.core.models import (
    ActionSpec,
    ActionType,
    AssertionSpec,
    AssertionType,
    Locator,
    LocatorType,
    Step,
    WaitConditionType,
    WaitSpec,
)
from app.automation.runner.events import RunEventType
from app.automation.runner.runner import StepRunner


def _make_driver() -> MagicMock:
    driver = MagicMock(spec=DeviceDriver)
    driver.find_element.return_value = ElementRef(
        found=True, locator_type="resource_id", locator_value="btn", center=(100, 200)
    )
    driver.current_app.return_value = {"package": "com.demo.app"}
    driver.screenshot.return_value = b"\x89PNG"
    driver.dump_source.return_value = "<hierarchy/>"
    driver.screen_size.return_value = (1080, 2400)
    return driver


class TestStepRunnerEvents:
    def test_run_started_and_finished_events(self):
        driver = _make_driver()
        runner = StepRunner(driver, output_dir="/tmp/run")
        events = list(runner.run([Step(id="s1", title="Tap", action=ActionSpec(type=ActionType.TAP, params={"x": 100, "y": 200}))]))
        types = [e.event_type for e in events]
        assert RunEventType.RUN_STARTED in types
        assert RunEventType.RUN_FINISHED in types

    def test_step_started_and_executed_events(self):
        driver = _make_driver()
        runner = StepRunner(driver, output_dir="/tmp/run")
        events = list(runner.run([Step(id="s1", title="Tap", action=ActionSpec(type=ActionType.TAP, params={"x": 100, "y": 200}))]))
        types = [e.event_type for e in events]
        assert RunEventType.STEP_STARTED in types
        assert RunEventType.ACTION_EXECUTED in types

    def test_assertion_passed_event(self):
        driver = _make_driver()
        runner = StepRunner(driver, output_dir="/tmp/run")
        step = Step(
            id="s1",
            title="Tap",
            action=ActionSpec(type=ActionType.TAP, params={"x": 100, "y": 200}),
            assertions=[AssertionSpec(type=AssertionType.EXISTS, locator=Locator(type=LocatorType.RESOURCE_ID, value="btn"))],
        )
        events = list(runner.run([step]))
        types = [e.event_type for e in events]
        assert RunEventType.ASSERTION_PASSED in types

    def test_evidence_saved_event(self):
        driver = _make_driver()
        runner = StepRunner(driver, output_dir="/tmp/run")
        events = list(runner.run([Step(id="s1", title="Tap", action=ActionSpec(type=ActionType.TAP, params={"x": 100, "y": 200}))]))
        types = [e.event_type for e in events]
        assert RunEventType.EVIDENCE_SAVED in types

    def test_wait_started_event(self):
        driver = _make_driver()
        runner = StepRunner(driver, output_dir="/tmp/run")
        step = Step(
            id="s1",
            title="Tap",
            before_wait=WaitSpec(type=WaitConditionType.VISIBLE, locator=Locator(type=LocatorType.RESOURCE_ID, value="btn"), timeout=0.1),
            action=ActionSpec(type=ActionType.TAP, params={"x": 100, "y": 200}),
        )
        events = list(runner.run([step]))
        types = [e.event_type for e in events]
        assert RunEventType.WAIT_STARTED in types
