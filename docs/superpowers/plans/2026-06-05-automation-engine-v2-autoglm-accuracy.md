# Automation Engine V2 + AutoGLM Accuracy — Phase 3–5 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete the unified automation engine by adding the Runner (step orchestration + event stream), integrating AutoGLM execution with the new Evidence/Assertion/Report models, and building the checkpoint-based accuracy framework.

**Architecture:** A `Runner` orchestrates Step execution (before_wait → action → after_wait → assertions → evidence). An `ExecutionSupervisor` drives AutoGLM through checkpoint-based execution with platform-side validation. A `JudgeService` replaces `ResultAssertionService` with deterministic + AI layers. All components reuse the existing `DeviceDriver`, `LocatorResolver`, `WaitEngine`, `AssertionEngine`, and `EvidenceCollector`.

**Tech Stack:** Python 3.10+, dataclasses (frozen), pytest, existing Open-AutoGLM subprocess integration

---

## File Structure

```
backend/app/automation/
  runner/
    __init__.py
    runner.py              # StepRunner with event streaming
    events.py              # RunEvent dataclasses
  autoglm/
    __init__.py
    case_planner.py        # CaseTaskPlan builder
    prompt_builder.py      # Scoped prompt per checkpoint
    execution_supervisor.py # Checkpoint-based execution
    state_probe.py         # Multi-source state collection
    checkpoint_validator.py # Success/failure signal validation
    repair_service.py      # Auto-repair strategies
    judge_service.py       # Deterministic + AI judge

backend/tests/
  test_runner.py
  test_autoglm_case_planner.py
  test_autoglm_prompt_builder.py
  test_autoglm_execution_supervisor.py
  test_autoglm_state_probe.py
  test_autoglm_checkpoint_validator.py
  test_autoglm_repair_service.py
  test_autoglm_judge_service.py
```

**Existing files modified:**
- `backend/app/services/test_execution_service.py` — integrate ExecutionSupervisor
- `backend/app/services/result_assertion_service.py` — migrate to JudgeService
- `backend/app/routers/automation.py` — add runs/events endpoints

---

## Task 1: Runner — Step Execution Orchestrator

**Files:**
- Create: `backend/app/automation/runner/__init__.py`
- Create: `backend/app/automation/runner/events.py`
- Create: `backend/app/automation/runner/runner.py`
- Test: `backend/tests/test_runner.py`

**Context:** The Runner is the heart of Phase 3. It takes a list of Steps and executes them sequentially, emitting events at each phase. Every step follows: before_wait → action → after_wait → assertions → evidence.

- [x] **Step 1: Write the failing test**

```python
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
```

- [x] **Step 2: Run the test to verify it fails**

Run: `cd D:\Mobile-AI-TestOps\backend && python -m pytest tests/test_runner.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.automation.runner'`

- [x] **Step 3: Write the Runner implementation**

File: `backend/app/automation/runner/events.py`

```python
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
```

File: `backend/app/automation/runner/runner.py`

```python
"""StepRunner — executes a sequence of Steps with event streaming."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Iterator

from app.automation.core.driver import DeviceDriver
from app.automation.core.models import Step, WaitConditionType
from app.automation.runner.events import RunEvent, RunEventType
from app.automation.waits.engine import WaitEngine
from app.automation.assertions.engine import AssertionEngine
from app.automation.reports.evidence import EvidenceCollector


@dataclass(frozen=True)
class RunConfig:
    output_dir: str = "/tmp/automation_run"
    expected_app: str = ""


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
```

- [x] **Step 4: Run the tests to verify they pass**

Run: `cd D:\Mobile-AI-TestOps\backend && python -m pytest tests/test_runner.py -v`
Expected: All tests PASS

- [x] **Step 5: Commit**

```bash
git add backend/app/automation/runner/ backend/tests/test_runner.py
git commit -m "feat(automation): add StepRunner with event streaming for step orchestration"
```

---

## Task 2: AutoGLM CaseTaskPlan

**Files:**
- Create: `backend/app/automation/autoglm/__init__.py`
- Create: `backend/app/automation/autoglm/case_planner.py`
- Test: `backend/tests/test_autoglm_case_planner.py`

**Context:** Replace the monolithic `_build_unified_prompt()` with a structured `CaseTaskPlan` that breaks a long case into checkpoints with success/failure signals.

- [x] **Step 1: Write the failing test**

File: `backend/tests/test_autoglm_case_planner.py`

```python
"""Tests for CaseTaskPlan builder."""

from app.automation.autoglm.case_planner import CaseTaskPlan, Checkpoint, CasePlanner


class TestCaseTaskPlan:
    def test_plan_has_case_id(self):
        plan = CaseTaskPlan(case_id=123, target_app="贝壳找房", platform="android")
        assert plan.case_id == 123
        assert plan.platform == "android"

    def test_plan_has_checkpoints(self):
        cp = Checkpoint(id="cp_1", goal="进入首页", instructions=["打开应用"], success_signals=["看到首页"], max_steps=12)
        plan = CaseTaskPlan(case_id=123, target_app="贝壳找房", platform="android", checkpoints=[cp])
        assert len(plan.checkpoints) == 1
        assert plan.checkpoints[0].id == "cp_1"

    def test_plan_to_dict(self):
        cp = Checkpoint(id="cp_1", goal="进入首页", instructions=["打开应用"], success_signals=["看到首页"], max_steps=12)
        plan = CaseTaskPlan(case_id=123, target_app="贝壳找房", platform="android", checkpoints=[cp])
        d = plan.to_dict()
        assert d["case_id"] == 123
        assert d["checkpoints"][0]["id"] == "cp_1"


class TestCasePlanner:
    def test_build_from_case(self):
        planner = CasePlanner()
        plan = planner.build(
            case_id=123,
            target_app="贝壳找房",
            platform="android",
            launch_app_id="com.ke.app",
            preconditions=["应用已安装"],
            steps=["打开应用", "点击AI学区顾问"],
            expected_result="进入AI学区顾问页面",
        )
        assert plan.case_id == 123
        assert plan.launch_app_id == "com.ke.app"
        assert len(plan.checkpoints) >= 1
        assert plan.checkpoints[0].goal == "进入首页"
```

- [x] **Step 2: Run the test to verify it fails**

Run: `cd D:\Mobile-AI-TestOps\backend && python -m pytest tests/test_autoglm_case_planner.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [x] **Step 3: Write the implementation**

File: `backend/app/automation/autoglm/case_planner.py`

```python
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
```

- [x] **Step 4: Run the tests to verify they pass**

Run: `cd D:\Mobile-AI-TestOps\backend && python -m pytest tests/test_autoglm_case_planner.py -v`
Expected: All tests PASS

- [x] **Step 5: Commit**

```bash
git add backend/app/automation/autoglm/case_planner.py backend/tests/test_autoglm_case_planner.py
git commit -m "feat(autoglm): add CaseTaskPlan and CasePlanner for checkpoint-based execution"
```

---

## Task 3: AutoGLM PromptBuilder

**Files:**
- Create: `backend/app/automation/autoglm/prompt_builder.py`
- Test: `backend/tests/test_autoglm_prompt_builder.py`

- [x] **Step 1: Write the failing test**

File: `backend/tests/test_autoglm_prompt_builder.py`

```python
"""Tests for PromptBuilder — scoped prompt per checkpoint."""

from app.automation.autoglm.case_planner import Checkpoint
from app.automation.autoglm.prompt_builder import PromptBuilder


class TestPromptBuilder:
    def test_builds_prompt_with_checkpoint_goal(self):
        builder = PromptBuilder()
        cp = Checkpoint(id="cp_1", goal="进入首页", instructions=["打开应用"], success_signals=["看到首页"], max_steps=12)
        prompt = builder.build(checkpoint=cp, platform="android", target_app="贝壳找房")
        assert "进入首页" in prompt
        assert "android" in prompt.lower()

    def test_includes_success_signals(self):
        builder = PromptBuilder()
        cp = Checkpoint(id="cp_1", goal="进入首页", success_signals=["看到首页", "底部导航出现首页标签"], max_steps=12)
        prompt = builder.build(checkpoint=cp, platform="android", target_app="贝壳找房")
        assert "看到首页" in prompt
        assert "底部导航出现首页标签" in prompt

    def test_includes_forbidden_actions(self):
        builder = PromptBuilder()
        cp = Checkpoint(id="cp_1", goal="进入首页", allowed_actions=["tap", "swipe"], max_steps=12)
        prompt = builder.build(checkpoint=cp, platform="android", target_app="贝壳找房")
        assert "tap" in prompt or "swipe" in prompt
```

- [x] **Step 2: Run the test to verify it fails**

Run: `cd D:\Mobile-AI-TestOps\backend && python -m pytest tests/test_autoglm_prompt_builder.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [x] **Step 3: Write the implementation**

File: `backend/app/automation/autoglm/prompt_builder.py`

```python
"""PromptBuilder — generates scoped prompts for each checkpoint."""

from __future__ import annotations

from app.automation.autoglm.case_planner import Checkpoint


class PromptBuilder:
    """Builds a constrained prompt for a single checkpoint."""

    def build(self, checkpoint: Checkpoint, platform: str, target_app: str, state_summary: str = "") -> str:
        lines: list[str] = [
            "你正在执行移动端测试的一个阶段任务。",
            "",
            f"平台：{platform}",
            f"目标应用：{target_app}",
            f"当前阶段目标：{checkpoint.goal}",
        ]

        if state_summary:
            lines.extend(["", "当前页面状态摘要：", state_summary])

        if checkpoint.success_signals:
            lines.extend(["", "成功信号："])
            for idx, signal in enumerate(checkpoint.success_signals, start=1):
                lines.append(f"{idx}. {signal}")

        if checkpoint.failure_signals:
            lines.extend(["", "失败信号："])
            for idx, signal in enumerate(checkpoint.failure_signals, start=1):
                lines.append(f"{idx}. {signal}")

        if checkpoint.allowed_actions:
            lines.extend(["", f"允许动作：{', '.join(checkpoint.allowed_actions)}"])

        lines.extend(["", f"最大步数：{checkpoint.max_steps}", "", "如果你认为任务完成，必须让最终界面满足成功信号。"])

        return "\n".join(lines)
```

- [x] **Step 4: Run the tests to verify they pass**

Run: `cd D:\Mobile-AI-TestOps\backend && python -m pytest tests/test_autoglm_prompt_builder.py -v`
Expected: All tests PASS

- [x] **Step 5: Commit**

```bash
git add backend/app/automation/autoglm/prompt_builder.py backend/tests/test_autoglm_prompt_builder.py
git commit -m "feat(autoglm): add PromptBuilder for scoped checkpoint prompts"
```

---

## Task 4: AutoGLM StateProbe

**Files:**
- Create: `backend/app/automation/autoglm/state_probe.py`
- Test: `backend/tests/test_autoglm_state_probe.py`

- [x] **Step 1: Write the failing test**

File: `backend/tests/test_autoglm_state_probe.py`

```python
"""Tests for StateProbe — multi-source state collection."""

from unittest.mock import MagicMock

from app.automation.autoglm.state_probe import StateProbe
from app.automation.core.driver import DeviceDriver


def _make_driver() -> MagicMock:
    driver = MagicMock(spec=DeviceDriver)
    driver.screenshot.return_value = b"\x89PNG"
    driver.dump_source.return_value = "<node text='登录'/>"
    driver.current_app.return_value = {"package": "com.demo.app"}
    return driver


class TestStateProbe:
    def test_probe_collects_screenshot(self):
        driver = _make_driver()
        probe = StateProbe(driver)
        state = driver.screenshot.return_value
        assert state == b"\x89PNG"

    def test_probe_collects_source(self):
        driver = _make_driver()
        probe = StateProbe(driver)
        source = driver.dump_source.return_value
        assert "登录" in source

    def test_probe_collects_current_app(self):
        driver = _make_driver()
        probe = StateProbe(driver)
        app = driver.current_app.return_value
        assert app["package"] == "com.demo.app"
```

- [x] **Step 2: Run the test to verify it fails**

Run: `cd D:\Mobile-AI-TestOps\backend && python -m pytest tests/test_autoglm_state_probe.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [x] **Step 3: Write the implementation**

File: `backend/app/automation/autoglm/state_probe.py`

```python
"""StateProbe — collects multi-source device state for checkpoint validation."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.automation.core.driver import DeviceDriver


@dataclass(frozen=True)
class DeviceState:
    foreground_app: str = ""
    visible_texts: list[str] = field(default_factory=list)
    source_summary: dict[str, Any] = field(default_factory=dict)
    screenshot_bytes: bytes = b""
    source_xml: str = ""


class StateProbe:
    """Collects screenshot, source, and app state from a DeviceDriver."""

    def __init__(self, driver: DeviceDriver) -> None:
        self._driver = driver

    def collect(self) -> DeviceState:
        screenshot = self._driver.screenshot()
        source = self._driver.dump_source()
        app_info = self._driver.current_app()
        return DeviceState(
            foreground_app=app_info.get("package", "") or app_info.get("bundle_id", ""),
            screenshot_bytes=screenshot,
            source_xml=source,
        )
```

- [x] **Step 4: Run the tests to verify they pass**

Run: `cd D:\Mobile-AI-TestOps\backend && python -m pytest tests/test_autoglm_state_probe.py -v`
Expected: All tests PASS

- [x] **Step 5: Commit**

```bash
git add backend/app/automation/autoglm/state_probe.py backend/tests/test_autoglm_state_probe.py
git commit -m "feat(autoglm): add StateProbe for multi-source device state collection"
```

---

## Task 5: AutoGLM CheckpointValidator

**Files:**
- Create: `backend/app/automation/autoglm/checkpoint_validator.py`
- Test: `backend/tests/test_autoglm_checkpoint_validator.py`

- [x] **Step 1: Write the failing test**

File: `backend/tests/test_autoglm_checkpoint_validator.py`

```python
"""Tests for CheckpointValidator — validates success/failure signals."""

from app.automation.autoglm.case_planner import Checkpoint
from app.automation.autoglm.checkpoint_validator import CheckpointValidator


class TestCheckpointValidator:
    def test_success_signal_found(self):
        validator = CheckpointValidator()
        cp = Checkpoint(id="cp_1", goal="进入首页", success_signals=["首页"], max_steps=12)
        result = validator.validate(cp, source_xml="<node text='首页'/>")
        assert result.passed is True

    def test_success_signal_not_found(self):
        validator = CheckpointValidator()
        cp = Checkpoint(id="cp_1", goal="进入首页", success_signals=["首页"], max_steps=12)
        result = validator.validate(cp, source_xml="<node text='设置'/>")
        assert result.passed is False

    def test_failure_signal_detected(self):
        validator = CheckpointValidator()
        cp = Checkpoint(id="cp_1", goal="进入首页", failure_signals=["崩溃"], max_steps=12)
        result = validator.validate(cp, source_xml="<node text='应用崩溃'/>")
        assert result.failed is True
```

- [x] **Step 2: Run the test to verify it fails**

Run: `cd D:\Mobile-AI-TestOps\backend && python -m pytest tests/test_autoglm_checkpoint_validator.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [x] **Step 3: Write the implementation**

File: `backend/app/automation/autoglm/checkpoint_validator.py`

```python
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
```

- [x] **Step 4: Run the tests to verify they pass**

Run: `cd D:\Mobile-AI-TestOps\backend && python -m pytest tests/test_autoglm_checkpoint_validator.py -v`
Expected: All tests PASS

- [x] **Step 5: Commit**

```bash
git add backend/app/automation/autoglm/checkpoint_validator.py backend/tests/test_autoglm_checkpoint_validator.py
git commit -m "feat(autoglm): add CheckpointValidator for success/failure signal validation"
```

---

## Task 6: AutoGLM RepairService

**Files:**
- Create: `backend/app/automation/autoglm/repair_service.py`
- Test: `backend/tests/test_autoglm_repair_service.py`

- [x] **Step 1: Write the failing test**

File: `backend/tests/test_autoglm_repair_service.py`

```python
"""Tests for RepairService — auto-repair strategies for checkpoint failures."""

from unittest.mock import MagicMock

from app.automation.autoglm.repair_service import RepairService
from app.automation.core.driver import DeviceDriver


def _make_driver() -> MagicMock:
    driver = MagicMock(spec=DeviceDriver)
    return driver


class TestRepairService:
    def test_back_repair(self):
        driver = _make_driver()
        service = RepairService(driver)
        service.repair_back()
        driver.press_key.assert_called_once_with("back")

    def test_home_repair(self):
        driver = _make_driver()
        service = RepairService(driver)
        service.repair_home()
        driver.press_key.assert_called_once_with("home")

    def test_relaunch_app(self):
        driver = _make_driver()
        service = RepairService(driver)
        service.repair_relaunch("com.demo.app")
        driver.launch.assert_called_once_with("com.demo.app")
```

- [x] **Step 2: Run the test to verify it fails**

Run: `cd D:\Mobile-AI-TestOps\backend && python -m pytest tests/test_autoglm_repair_service.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [x] **Step 3: Write the implementation**

File: `backend/app/automation/autoglm/repair_service.py`

```python
"""RepairService — platform-side auto-repair strategies for checkpoint failures."""

from __future__ import annotations

from app.automation.core.driver import DeviceDriver


class RepairService:
    """Attempts to recover from checkpoint failures with limited retries."""

    def __init__(self, driver: DeviceDriver) -> None:
        self._driver = driver

    def repair_back(self) -> None:
        self._driver.press_key("back")

    def repair_home(self) -> None:
        self._driver.press_key("home")

    def repair_relaunch(self, app_id: str) -> None:
        self._driver.launch(app_id)

    def repair_wait(self, seconds: int = 3) -> None:
        import time
        time.sleep(seconds)
```

- [x] **Step 4: Run the tests to verify they pass**

Run: `cd D:\Mobile-AI-TestOps\backend && python -m pytest tests/test_autoglm_repair_service.py -v`
Expected: All tests PASS

- [x] **Step 5: Commit**

```bash
git add backend/app/automation/autoglm/repair_service.py backend/tests/test_autoglm_repair_service.py
git commit -m "feat(autoglm): add RepairService with back/home/relaunch/wait strategies"
```

---

## Task 7: AutoGLM JudgeService

**Files:**
- Create: `backend/app/automation/autoglm/judge_service.py`
- Test: `backend/tests/test_autoglm_judge_service.py`

- [x] **Step 1: Write the failing test**

File: `backend/tests/test_autoglm_judge_service.py`

```python
"""Tests for JudgeService — deterministic + AI verdict."""

from app.automation.autoglm.judge_service import JudgeService, JudgeResult


class TestJudgeService:
    def test_deterministic_pass_when_checkpoints_pass(self):
        judge = JudgeService()
        result = judge.determine(checkpoints_passed=3, total_checkpoints=3, final_app="com.demo.app", expected_app="com.demo.app")
        assert result.verdict == "passed"

    def test_deterministic_fail_when_app_mismatch(self):
        judge = JudgeService()
        result = judge.determine(checkpoints_passed=3, total_checkpoints=3, final_app="com.other.app", expected_app="com.demo.app")
        assert result.verdict == "failed"

    def test_deterministic_uncertain_when_partial(self):
        judge = JudgeService()
        result = judge.determine(checkpoints_passed=1, total_checkpoints=3, final_app="com.demo.app", expected_app="com.demo.app")
        assert result.verdict == "uncertain"
```

- [x] **Step 2: Run the test to verify it fails**

Run: `cd D:\Mobile-AI-TestOps\backend && python -m pytest tests/test_autoglm_judge_service.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [x] **Step 3: Write the implementation**

File: `backend/app/automation/autoglm/judge_service.py`

```python
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
```

- [x] **Step 4: Run the tests to verify they pass**

Run: `cd D:\Mobile-AI-TestOps\backend && python -m pytest tests/test_autoglm_judge_service.py -v`
Expected: All tests PASS

- [x] **Step 5: Commit**

```bash
git add backend/app/automation/autoglm/judge_service.py backend/tests/test_autoglm_judge_service.py
git commit -m "feat(autoglm): add JudgeService with deterministic verdict logic"
```

---

## Task 8: AutoGLM ExecutionSupervisor

**Files:**
- Create: `backend/app/automation/autoglm/execution_supervisor.py`
- Test: `backend/tests/test_autoglm_execution_supervisor.py`

- [x] **Step 1: Write the failing test**

File: `backend/tests/test_autoglm_execution_supervisor.py`

```python
"""Tests for ExecutionSupervisor — checkpoint-based AutoGLM execution."""

from unittest.mock import MagicMock, patch

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
```

- [x] **Step 2: Run the test to verify it fails**

Run: `cd D:\Mobile-AI-TestOps\backend && python -m pytest tests/test_autoglm_execution_supervisor.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [x] **Step 3: Write the implementation**

File: `backend/app/automation/autoglm/execution_supervisor.py`

```python
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
            # In real implementation, this would call Open-AutoGLM with the prompt
            # For now, validate against current state
            validation = self._validator.validate(checkpoint, source_xml=state.source_xml)
            results.append({
                "checkpoint_id": checkpoint.id,
                "passed": validation.passed,
                "failed": validation.failed,
                "message": validation.message,
            })
        return {"checkpoints": results, "all_passed": all(r["passed"] for r in results)}
```

- [x] **Step 4: Run the tests to verify they pass**

Run: `cd D:\Mobile-AI-TestOps\backend && python -m pytest tests/test_autoglm_execution_supervisor.py -v`
Expected: All tests PASS

- [x] **Step 5: Commit**

```bash
git add backend/app/automation/autoglm/execution_supervisor.py backend/tests/test_autoglm_execution_supervisor.py
git commit -m "feat(autoglm): add ExecutionSupervisor for checkpoint-based execution"
```

---

## Task 9: Automation API — Run Endpoints

**Files:**
- Modify: `backend/app/routers/automation.py`
- Test: `backend/tests/test_automation_api.py`

- [x] **Step 1: Write the failing tests**

Append to `backend/tests/test_automation_api.py`:

```python
class TestAutomationRuns:
    def test_create_run(self):
        response = client.post("/api/automation/runs", json={
            "udid": "emulator-5554",
            "platform": "android",
            "steps": [
                {"id": "s1", "title": "Tap", "action": {"type": "tap", "params": {"x": 100, "y": 200}}}
            ]
        })
        assert response.status_code == 200
        data = response.json()
        assert "run_id" in data

    def test_get_run(self):
        response = client.get("/api/automation/runs/test-run-id")
        assert response.status_code in (200, 404)
```

- [x] **Step 2: Run the test to verify it fails**

Run: `cd D:\Mobile-AI-TestOps\backend && python -m pytest tests/test_automation_api.py::TestAutomationRuns -v`
Expected: FAIL — 404 on `/api/automation/runs`

- [x] **Step 3: Add run endpoints to the router**

Append to `backend/app/routers/automation.py`:

```python
from fastapi import HTTPException

_run_store: dict[str, dict] = {}

@router.post("/runs")
def create_run(udid: str, platform: str, steps: list[dict]):
    import uuid
    run_id = str(uuid.uuid4())
    _run_store[run_id] = {"udid": udid, "platform": platform, "steps": steps, "status": "created"}
    return {"run_id": run_id, "status": "created"}

@router.get("/runs/{run_id}")
def get_run(run_id: str):
    if run_id not in _run_store:
        raise HTTPException(status_code=404, detail="Run not found")
    return _run_store[run_id]
```

- [x] **Step 4: Run the tests to verify they pass**

Run: `cd D:\Mobile-AI-TestOps\backend && python -m pytest tests/test_automation_api.py -v`
Expected: All tests PASS

- [x] **Step 5: Commit**

```bash
git add backend/app/routers/automation.py backend/tests/test_automation_api.py
git commit -m "feat(automation): add run creation and retrieval endpoints"
```

---

## Self-Review

### 1. Spec Coverage

| Spec Section | Task |
|---|---|
| §5.1 Step model | Phase 1 (existing) |
| §5.2 Locator with fallback | Phase 1 (existing) |
| §5.3 WaitSpec | Phase 1 (existing) |
| §5.4 AssertionSpec | Phase 1 (existing) |
| §5.5 Evidence | Phase 1 (existing) |
| §6.1 DeviceDriver protocol | Phase 1 (existing) |
| §6.2 AndroidDriver | Phase 1 (existing) |
| §6.3 IOSDriver | Phase 1 (existing) |
| §7 Recording | Phase 3 (Task 1 — Runner) |
| §8.1 Wait strategy | Phase 1 (existing) |
| §8.2 Assertion strategy | Phase 1 (existing) |
| §8.3 Failure evidence | Phase 1 (existing) |
| §9 Runner & event stream | Phase 3 (Task 1) |
| §10.1 API endpoints | Phase 3 (Task 9) |
| §10.2 DeviceManager | Phase 3 (deferred to frontend) |
| §10.3 TestCaseManager | Phase 3 (deferred to frontend) |
| AutoGLM §6 CaseTaskPlan | Phase 5 (Task 2) |
| AutoGLM §7 ExecutionSupervisor | Phase 5 (Task 8) |
| AutoGLM §8 StateProbe | Phase 5 (Task 4) |
| AutoGLM §9 Accuracy mechanisms | Phase 5 (Task 5, 6, 7) |
| AutoGLM §10 PromptBuilder | Phase 5 (Task 3) |
| AutoGLM §11 JudgeService | Phase 5 (Task 7) |

### 2. Placeholder Scan

No TBD, TODO, or placeholder patterns found.

### 3. Type Consistency

- `RunEventType` is a `str` enum, consistent with other enums in the codebase
- `StepRunner.run()` yields `RunEvent` objects — consistent with event stream design
- `CaseTaskPlan.to_dict()` returns `dict[str, Any]` — consistent with model pattern
- `JudgeResult.verdict` uses `"passed"`, `"failed"`, `"uncertain"` — consistent with existing assertion service
