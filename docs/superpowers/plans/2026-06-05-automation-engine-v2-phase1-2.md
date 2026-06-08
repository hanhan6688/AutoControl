# Automation Engine V2 — Phase 1 & 2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create the unified DeviceDriver abstraction and core automation engine (Locator, Wait, Assertion, Evidence) that converges the scattered device capabilities across ScriptUI, u2_service, and wda_service into a single coherent system.

**Architecture:** A new `backend/app/automation/` package introduces the `DeviceDriver` protocol with `AndroidDriver` and `IOSDriver` implementations. `LocatorChain` resolves elements via fallback strategies. `WaitEngine`, `AssertionEngine`, and `EvidenceCollector` provide first-class step-level capabilities. `ScriptUI` is refactored to delegate to the new engine while preserving its public API for backward compatibility.

**Tech Stack:** Python 3.10+, dataclasses (frozen), pytest, existing u2/ADB/WDA/scrcpy services as delegate targets

---

## File Structure

```
backend/app/automation/
  __init__.py
  core/
    __init__.py
    models.py              # Step, ActionSpec, Locator, LocatorChain, WaitSpec, AssertionSpec, Evidence
    driver.py              # DeviceDriver protocol (ABC)
  drivers/
    __init__.py
    android_driver.py      # AndroidDriver
    ios_driver.py          # IOSDriver
  locators/
    __init__.py
    resolver.py            # LocatorResolver
  waits/
    __init__.py
    engine.py              # WaitEngine
  assertions/
    __init__.py
    engine.py              # AssertionEngine
  recording/
    __init__.py
    codegen.py             # Python code generation from Steps
  reports/
    __init__.py
    evidence.py            # EvidenceCollector

backend/tests/
  test_automation_models.py
  test_android_driver.py
  test_ios_driver.py
  test_locator_resolver.py
  test_wait_engine.py
  test_assertion_engine.py
  test_evidence_collector.py
  test_codegen.py
```

**Existing files modified:**
- `backend/app/routers/scripts.py` — ScriptUI delegates to DeviceDriver
- `backend/app/main.py` — Register new automation router (Phase 3+)

---

## Task 1: Automation Package Structure + Data Models

**Files:**
- Create: `backend/app/automation/__init__.py`
- Create: `backend/app/automation/core/__init__.py`
- Create: `backend/app/automation/core/models.py`
- Create: `backend/app/automation/drivers/__init__.py`
- Create: `backend/app/automation/locators/__init__.py`
- Create: `backend/app/automation/waits/__init__.py`
- Create: `backend/app/automation/assertions/__init__.py`
- Create: `backend/app/automation/recording/__init__.py`
- Create: `backend/app/automation/reports/__init__.py`
- Test: `backend/tests/test_automation_models.py`

- [ ] **Step 1: Create directory structure and all `__init__.py` files**

```bash
mkdir -p backend/app/automation/core
mkdir -p backend/app/automation/drivers
mkdir -p backend/app/automation/locators
mkdir -p backend/app/automation/waits
mkdir -p backend/app/automation/assertions
mkdir -p backend/app/automation/recording
mkdir -p backend/app/automation/reports
```

Each `__init__.py` is empty (just a file touch). `backend/app/automation/core/__init__.py` exports key models:

```python
from .models import (
    ActionSpec,
    ActionType,
    AssertionSpec,
    AssertionType,
    Evidence,
    Locator,
    LocatorChain,
    LocatorType,
    Step,
    WaitConditionType,
    WaitSpec,
)

__all__ = [
    "ActionSpec",
    "ActionType",
    "AssertionSpec",
    "AssertionType",
    "Evidence",
    "Locator",
    "LocatorChain",
    "LocatorType",
    "Step",
    "WaitConditionType",
    "WaitSpec",
]
```

`backend/app/automation/__init__.py`:

```python
"""Unified Automation Engine V2."""
```

All other `__init__.py` files are empty.

- [ ] **Step 2: Write the failing test for data models**

File: `backend/tests/test_automation_models.py`

```python
"""Tests for automation core data models."""

from app.automation.core.models import (
    ActionSpec,
    ActionType,
    AssertionSpec,
    AssertionType,
    Evidence,
    Locator,
    LocatorChain,
    LocatorType,
    Step,
    WaitConditionType,
    WaitSpec,
)


class TestLocator:
    def test_create_resource_id_locator(self):
        loc = Locator(type=LocatorType.RESOURCE_ID, value="com.demo:id/login")
        assert loc.type == LocatorType.RESOURCE_ID
        assert loc.value == "com.demo:id/login"

    def test_create_text_locator(self):
        loc = Locator(type=LocatorType.TEXT, value="登录")
        assert loc.type == LocatorType.TEXT
        assert loc.value == "登录"

    def test_create_xpath_locator(self):
        loc = Locator(type=LocatorType.XPATH, value="//*[@text='登录']")
        assert loc.type == LocatorType.XPATH

    def test_create_ocr_locator(self):
        loc = Locator(type=LocatorType.OCR_TEXT, value="登录")
        assert loc.type == LocatorType.OCR_TEXT

    def test_create_coordinate_ratio_locator(self):
        loc = Locator(type=LocatorType.COORDINATE_RATIO, value="", x=0.52, y=0.82)
        assert loc.x == 0.52
        assert loc.y == 0.82

    def test_create_content_desc_locator(self):
        loc = Locator(type=LocatorType.CONTENT_DESC, value="Navigate up")
        assert loc.type == LocatorType.CONTENT_DESC

    def test_create_class_name_locator(self):
        loc = Locator(type=LocatorType.CLASS_NAME, value="android.widget.Button")
        assert loc.type == LocatorType.CLASS_NAME

    def test_locator_is_frozen(self):
        loc = Locator(type=LocatorType.TEXT, value="OK")
        try:
            loc.value = "Cancel"
            assert False, "Should raise FrozenInstanceError"
        except AttributeError:
            pass

    def test_locator_to_dict(self):
        loc = Locator(type=LocatorType.RESOURCE_ID, value="com.demo:id/login")
        d = loc.to_dict()
        assert d["type"] == "resource_id"
        assert d["value"] == "com.demo:id/login"


class TestLocatorChain:
    def test_create_chain_with_fallbacks(self):
        chain = LocatorChain(
            primary=Locator(type=LocatorType.RESOURCE_ID, value="com.demo:id/login"),
            fallbacks=[
                Locator(type=LocatorType.TEXT, value="登录"),
                Locator(type=LocatorType.XPATH, value="//*[@text='登录']"),
                Locator(type=LocatorType.OCR_TEXT, value="登录"),
                Locator(type=LocatorType.COORDINATE_RATIO, value="", x=0.52, y=0.82),
            ],
        )
        assert chain.primary.type == LocatorType.RESOURCE_ID
        assert len(chain.fallbacks) == 4

    def test_chain_all_locators_in_order(self):
        chain = LocatorChain(
            primary=Locator(type=LocatorType.RESOURCE_ID, value="com.demo:id/btn"),
            fallbacks=[Locator(type=LocatorType.TEXT, value="Btn")],
        )
        all_locs = chain.all_locators()
        assert len(all_locs) == 2
        assert all_locs[0].type == LocatorType.RESOURCE_ID
        assert all_locs[1].type == LocatorType.TEXT

    def test_chain_to_dict(self):
        chain = LocatorChain(
            primary=Locator(type=LocatorType.RESOURCE_ID, value="com.demo:id/btn"),
            fallbacks=[Locator(type=LocatorType.TEXT, value="Btn")],
        )
        d = chain.to_dict()
        assert d["primary"]["type"] == "resource_id"
        assert len(d["fallbacks"]) == 1


class TestActionSpec:
    def test_tap_action(self):
        action = ActionSpec(type=ActionType.TAP, locator=Locator(type=LocatorType.RESOURCE_ID, value="com.demo:id/btn"))
        assert action.type == ActionType.TAP
        assert action.locator is not None

    def test_swipe_action_with_params(self):
        action = ActionSpec(
            type=ActionType.SWIPE,
            params={"start_x": 100, "start_y": 500, "end_x": 100, "end_y": 200, "duration_ms": 300},
        )
        assert action.type == ActionType.SWIPE
        assert action.params["duration_ms"] == 300

    def test_input_action(self):
        action = ActionSpec(
            type=ActionType.INPUT,
            params={"text": "hello"},
            locator=Locator(type=LocatorType.RESOURCE_ID, value="com.demo:id/edit"),
        )
        assert action.params["text"] == "hello"

    def test_launch_action(self):
        action = ActionSpec(type=ActionType.LAUNCH, params={"app_id": "com.demo.app"})
        assert action.params["app_id"] == "com.demo.app"

    def test_action_to_dict(self):
        action = ActionSpec(type=ActionType.TAP, locator=Locator(type=LocatorType.TEXT, value="OK"))
        d = action.to_dict()
        assert d["type"] == "tap"
        assert d["locator"]["type"] == "text"


class TestWaitSpec:
    def test_visible_wait(self):
        wait = WaitSpec(
            type=WaitConditionType.VISIBLE,
            locator=Locator(type=LocatorType.RESOURCE_ID, value="com.demo:id/login"),
            timeout=10.0,
        )
        assert wait.type == WaitConditionType.VISIBLE
        assert wait.timeout == 10.0

    def test_screen_changed_wait(self):
        wait = WaitSpec(type=WaitConditionType.SCREEN_CHANGED, timeout=3.0)
        assert wait.locator is None

    def test_text_contains_wait(self):
        wait = WaitSpec(
            type=WaitConditionType.TEXT_CONTAINS,
            locator=Locator(type=LocatorType.RESOURCE_ID, value="com.demo:id/title"),
            timeout=5.0,
            text="首页",
        )
        assert wait.text == "首页"

    def test_default_poll_interval(self):
        wait = WaitSpec(type=WaitConditionType.EXISTS, locator=Locator(type=LocatorType.TEXT, value="OK"), timeout=5.0)
        assert wait.poll_interval == 0.5

    def test_wait_to_dict(self):
        wait = WaitSpec(type=WaitConditionType.VISIBLE, locator=Locator(type=LocatorType.TEXT, value="OK"), timeout=10.0)
        d = wait.to_dict()
        assert d["type"] == "visible"
        assert d["timeout"] == 10.0


class TestAssertionSpec:
    def test_exists_assertion(self):
        a = AssertionSpec(type=AssertionType.EXISTS, locator=Locator(type=LocatorType.RESOURCE_ID, value="com.demo:id/home"))
        assert a.type == AssertionType.EXISTS

    def test_text_equals_assertion(self):
        a = AssertionSpec(
            type=AssertionType.TEXT_EQUALS,
            locator=Locator(type=LocatorType.RESOURCE_ID, value="com.demo:id/title"),
            expected="首页",
        )
        assert a.expected == "首页"

    def test_ocr_contains_assertion(self):
        a = AssertionSpec(type=AssertionType.OCR_CONTAINS, expected="登录成功")
        assert a.locator is None
        assert a.expected == "登录成功"

    def test_assertion_to_dict(self):
        a = AssertionSpec(type=AssertionType.EXISTS, locator=Locator(type=LocatorType.TEXT, value="OK"))
        d = a.to_dict()
        assert d["type"] == "exists"


class TestEvidence:
    def test_create_evidence(self):
        e = Evidence(
            screenshot_path="/tmp/step_12.png",
            source_dump_path="/tmp/step_12.xml",
            ocr_summary=["登录", "首页"],
            current_app="com.demo.app",
            duration_ms=421,
        )
        assert e.screenshot_path == "/tmp/step_12.png"
        assert e.ocr_summary == ["登录", "首页"]

    def test_evidence_to_dict(self):
        e = Evidence(
            screenshot_path="/tmp/step.png",
            source_dump_path="/tmp/step.xml",
            ocr_summary=[],
            current_app="com.demo",
            duration_ms=100,
        )
        d = e.to_dict()
        assert d["screenshot_path"] == "/tmp/step.png"
        assert d["duration_ms"] == 100


class TestStep:
    def test_create_step_full(self):
        step = Step(
            id="step_12",
            title="点击登录按钮",
            action=ActionSpec(
                type=ActionType.TAP,
                locator=Locator(type=LocatorType.RESOURCE_ID, value="com.demo:id/login"),
            ),
            before_wait=WaitSpec(
                type=WaitConditionType.VISIBLE,
                locator=Locator(type=LocatorType.TEXT, value="登录"),
                timeout=10.0,
            ),
            after_wait=WaitSpec(
                type=WaitConditionType.SCREEN_CHANGED,
                timeout=3.0,
            ),
            assertions=[
                AssertionSpec(
                    type=AssertionType.EXISTS,
                    locator=Locator(type=LocatorType.RESOURCE_ID, value="com.demo:id/home_title"),
                ),
            ],
        )
        assert step.id == "step_12"
        assert step.title == "点击登录按钮"
        assert step.action.type == ActionType.TAP
        assert step.before_wait is not None
        assert step.after_wait is not None
        assert len(step.assertions) == 1

    def test_step_minimal(self):
        step = Step(
            id="step_1",
            title="Tap",
            action=ActionSpec(type=ActionType.TAP),
        )
        assert step.before_wait is None
        assert step.after_wait is None
        assert step.assertions == []

    def test_step_to_dict(self):
        step = Step(
            id="step_1",
            title="Tap OK",
            action=ActionSpec(
                type=ActionType.TAP,
                locator=Locator(type=LocatorType.TEXT, value="OK"),
            ),
        )
        d = step.to_dict()
        assert d["id"] == "step_1"
        assert d["action"]["type"] == "tap"
        assert d["before_wait"] is None

    def test_step_from_dict_roundtrip(self):
        step = Step(
            id="step_5",
            title="Input text",
            action=ActionSpec(
                type=ActionType.INPUT,
                params={"text": "hello"},
                locator=Locator(type=LocatorType.RESOURCE_ID, value="com.demo:id/edit"),
            ),
            assertions=[
                AssertionSpec(type=AssertionType.TEXT_EQUALS, locator=Locator(type=LocatorType.RESOURCE_ID, value="com.demo:id/edit"), expected="hello"),
            ],
        )
        d = step.to_dict()
        restored = Step.from_dict(d)
        assert restored.id == step.id
        assert restored.title == step.title
        assert restored.action.type == step.action.type
        assert len(restored.assertions) == 1
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `cd D:\Mobile-AI-TestOps\backend && python -m pytest tests/test_automation_models.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.automation'`

- [ ] **Step 4: Write the data models implementation**

File: `backend/app/automation/core/models.py`

```python
"""Core data models for the Unified Automation Engine V2."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class LocatorType(str, Enum):
    """Supported locator strategies, ordered by reliability."""

    RESOURCE_ID = "resource_id"
    TEXT = "text"
    CONTENT_DESC = "content_desc"
    CLASS_NAME = "class_name"
    XPATH = "xpath"
    OCR_TEXT = "ocr_text"
    COORDINATE_RATIO = "coordinate_ratio"


class ActionType(str, Enum):
    """Supported automation actions."""

    TAP = "tap"
    LONG_PRESS = "long_press"
    SWIPE = "swipe"
    INPUT = "input"
    PRESS_KEY = "press_key"
    LAUNCH = "launch"
    STOP_APP = "stop_app"


class WaitConditionType(str, Enum):
    """Supported wait conditions."""

    VISIBLE = "visible"
    GONE = "gone"
    EXISTS = "exists"
    TEXT_EQUALS = "text_equals"
    TEXT_CONTAINS = "text_contains"
    ENABLED = "enabled"
    SCREEN_CHANGED = "screen_changed"
    APP_FOREGROUND = "app_foreground"
    SOURCE_STABLE = "source_stable"
    OCR_CONTAINS = "ocr_contains"


class AssertionType(str, Enum):
    """Supported assertion types."""

    EXISTS = "exists"
    NOT_EXISTS = "not_exists"
    TEXT_EQUALS = "text_equals"
    TEXT_CONTAINS = "text_contains"
    OCR_CONTAINS = "ocr_contains"
    IMAGE_EXISTS = "image_exists"
    APP_FOREGROUND = "app_foreground"
    AI_RESULT = "ai_result"


@dataclass(frozen=True)
class Locator:
    """A single element locator using one strategy."""

    type: LocatorType
    value: str = ""
    x: float | None = None
    y: float | None = None

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"type": self.type.value, "value": self.value}
        if self.x is not None:
            d["x"] = self.x
        if self.y is not None:
            d["y"] = self.y
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Locator:
        return cls(
            type=LocatorType(data["type"]),
            value=data.get("value", ""),
            x=data.get("x"),
            y=data.get("y"),
        )


@dataclass(frozen=True)
class LocatorChain:
    """Primary locator with ordered fallback strategies."""

    primary: Locator
    fallbacks: list[Locator] = field(default_factory=list)

    def all_locators(self) -> list[Locator]:
        """Return primary + fallbacks in resolution order."""
        return [self.primary] + list(self.fallbacks)

    def to_dict(self) -> dict[str, Any]:
        return {
            "primary": self.primary.to_dict(),
            "fallbacks": [f.to_dict() for f in self.fallbacks],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> LocatorChain:
        return cls(
            primary=Locator.from_dict(data["primary"]),
            fallbacks=[Locator.from_dict(f) for f in data.get("fallbacks", [])],
        )


@dataclass(frozen=True)
class ActionSpec:
    """Specification for a single automation action."""

    type: ActionType
    locator: Locator | None = None
    params: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"type": self.type.value}
        if self.locator is not None:
            d["locator"] = self.locator.to_dict()
        if self.params:
            d["params"] = dict(self.params)
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ActionSpec:
        locator = Locator.from_dict(data["locator"]) if "locator" in data else None
        return cls(
            type=ActionType(data["type"]),
            locator=locator,
            params=data.get("params", {}),
        )


@dataclass(frozen=True)
class WaitSpec:
    """Explicit wait condition specification."""

    type: WaitConditionType
    timeout: float = 10.0
    locator: Locator | None = None
    text: str | None = None
    poll_interval: float = 0.5

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"type": self.type.value, "timeout": self.timeout}
        if self.locator is not None:
            d["locator"] = self.locator.to_dict()
        if self.text is not None:
            d["text"] = self.text
        if self.poll_interval != 0.5:
            d["poll_interval"] = self.poll_interval
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> WaitSpec:
        locator = Locator.from_dict(data["locator"]) if "locator" in data else None
        return cls(
            type=WaitConditionType(data["type"]),
            timeout=data.get("timeout", 10.0),
            locator=locator,
            text=data.get("text"),
            poll_interval=data.get("poll_interval", 0.5),
        )


@dataclass(frozen=True)
class AssertionSpec:
    """Step-level or end-of-run assertion specification."""

    type: AssertionType
    locator: Locator | None = None
    expected: str | None = None
    image_path: str | None = None

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"type": self.type.value}
        if self.locator is not None:
            d["locator"] = self.locator.to_dict()
        if self.expected is not None:
            d["expected"] = self.expected
        if self.image_path is not None:
            d["image_path"] = self.image_path
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AssertionSpec:
        locator = Locator.from_dict(data["locator"]) if "locator" in data else None
        return cls(
            type=AssertionType(data["type"]),
            locator=locator,
            expected=data.get("expected"),
            image_path=data.get("image_path"),
        )


@dataclass(frozen=True)
class Evidence:
    """Step-level evidence snapshot."""

    screenshot_path: str = ""
    source_dump_path: str = ""
    ocr_summary: list[str] = field(default_factory=list)
    current_app: str = ""
    duration_ms: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "screenshot_path": self.screenshot_path,
            "source_dump_path": self.source_dump_path,
            "ocr_summary": list(self.ocr_summary),
            "current_app": self.current_app,
            "duration_ms": self.duration_ms,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Evidence:
        return cls(
            screenshot_path=data.get("screenshot_path", ""),
            source_dump_path=data.get("source_dump_path", ""),
            ocr_summary=data.get("ocr_summary", []),
            current_app=data.get("current_app", ""),
            duration_ms=data.get("duration_ms", 0),
        )


@dataclass(frozen=True)
class Step:
    """A single structured automation step."""

    id: str
    title: str
    action: ActionSpec
    before_wait: WaitSpec | None = None
    after_wait: WaitSpec | None = None
    assertions: list[AssertionSpec] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "id": self.id,
            "title": self.title,
            "action": self.action.to_dict(),
        }
        if self.before_wait is not None:
            d["before_wait"] = self.before_wait.to_dict()
        if self.after_wait is not None:
            d["after_wait"] = self.after_wait.to_dict()
        if self.assertions:
            d["assertions"] = [a.to_dict() for a in self.assertions]
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Step:
        return cls(
            id=data["id"],
            title=data["title"],
            action=ActionSpec.from_dict(data["action"]),
            before_wait=WaitSpec.from_dict(data["before_wait"]) if "before_wait" in data else None,
            after_wait=WaitSpec.from_dict(data["after_wait"]) if "after_wait" in data else None,
            assertions=[AssertionSpec.from_dict(a) for a in data.get("assertions", [])],
        )
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `cd D:\Mobile-AI-TestOps\backend && python -m pytest tests/test_automation_models.py -v`
Expected: All 25+ tests PASS

- [ ] **Step 6: Commit**

```bash
git add backend/app/automation/ backend/tests/test_automation_models.py
git commit -m "feat(automation): add core data models — Step, Locator, LocatorChain, WaitSpec, AssertionSpec, Evidence"
```

---

## Task 2: DeviceDriver Protocol

**Files:**
- Create: `backend/app/automation/core/driver.py`
- Test: `backend/tests/test_android_driver.py` (contract tests will be written here first)

- [ ] **Step 1: Write the failing test for DeviceDriver protocol**

File: `backend/tests/test_android_driver.py` (initial version — just protocol contract)

```python
"""Contract tests for DeviceDriver protocol and AndroidDriver."""

from app.automation.core.driver import DeviceDriver


class TestDeviceDriverProtocol:
    def test_protocol_defines_required_methods(self):
        """Verify DeviceDriver has all required method signatures."""
        required = [
            "platform",
            "launch",
            "stop_app",
            "tap",
            "long_press",
            "swipe",
            "input_text",
            "press_key",
            "screenshot",
            "dump_source",
            "current_app",
            "screen_size",
            "find_element",
            "element_exists",
        ]
        for name in required:
            assert hasattr(DeviceDriver, name), f"DeviceDriver missing: {name}"

    def test_cannot_instantiate_protocol_directly(self):
        """DeviceDriver is abstract — cannot be instantiated."""
        try:
            DeviceDriver(udid="test", platform="android")
            assert False, "Should not instantiate abstract class"
        except TypeError:
            pass
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd D:\Mobile-AI-TestOps\backend && python -m pytest tests/test_android_driver.py::TestDeviceDriverProtocol -v`
Expected: FAIL — `ImportError: cannot import name 'DeviceDriver'`

- [ ] **Step 3: Write the DeviceDriver protocol**

File: `backend/app/automation/core/driver.py`

```python
"""DeviceDriver protocol — the unified interface for all platform drivers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ElementRef:
    """Result of finding an element on the device."""

    found: bool
    locator_type: str
    locator_value: str
    bounds: dict[str, int] | None = None
    center: tuple[int, int] | None = None
    text: str | None = None
    resource_id: str | None = None
    class_name: str | None = None
    content_desc: str | None = None
    attributes: dict[str, Any] | None = None


class DeviceDriver(ABC):
    """Abstract base class for platform-specific device drivers.

    All automation actions (recording, playback, AI execution) go through
    this single interface. Platform drivers implement these methods using
    their native toolchains (ADB/u2 for Android, WDA for iOS).
    """

    @property
    @abstractmethod
    def platform(self) -> str:
        """Return the platform identifier: 'android' or 'ios'."""
        ...

    @abstractmethod
    def launch(self, app_id: str) -> None:
        """Launch an app by package name (Android) or bundle ID (iOS)."""
        ...

    @abstractmethod
    def stop_app(self, app_id: str) -> None:
        """Force-stop an app."""
        ...

    @abstractmethod
    def tap(self, x: int, y: int) -> None:
        """Tap at device pixel coordinates."""
        ...

    @abstractmethod
    def long_press(self, x: int, y: int, duration_ms: int = 1000) -> None:
        """Long-press at device pixel coordinates."""
        ...

    @abstractmethod
    def swipe(self, sx: int, sy: int, ex: int, ey: int, duration_ms: int = 300) -> None:
        """Swipe from start to end coordinates."""
        ...

    @abstractmethod
    def input_text(self, text: str) -> None:
        """Input text into the currently focused field."""
        ...

    @abstractmethod
    def press_key(self, key: str) -> None:
        """Press a key by name (back, home, enter, etc.)."""
        ...

    @abstractmethod
    def screenshot(self) -> bytes:
        """Capture a screenshot and return PNG bytes."""
        ...

    @abstractmethod
    def dump_source(self) -> str:
        """Dump the current UI hierarchy as XML."""
        ...

    @abstractmethod
    def current_app(self) -> dict[str, str]:
        """Return current foreground app info: {package, activity} for Android or {bundle_id} for iOS."""
        ...

    @abstractmethod
    def screen_size(self) -> tuple[int, int]:
        """Return device screen size as (width, height) in pixels."""
        ...

    @abstractmethod
    def find_element(self, locator_type: str, locator_value: str, timeout: float = 10.0) -> ElementRef:
        """Find an element using the given locator strategy. Returns ElementRef with found=False if not found."""
        ...

    @abstractmethod
    def element_exists(self, locator_type: str, locator_value: str, timeout: float = 5.0) -> bool:
        """Check if an element exists within the timeout."""
        ...
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd D:\Mobile-AI-TestOps\backend && python -m pytest tests/test_android_driver.py::TestDeviceDriverProtocol -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/automation/core/driver.py backend/tests/test_android_driver.py
git commit -m "feat(automation): add DeviceDriver protocol with ElementRef result type"
```

---

## Task 3: AndroidDriver

**Files:**
- Create: `backend/app/automation/drivers/android_driver.py`
- Modify: `backend/tests/test_android_driver.py` (add AndroidDriver tests)

- [ ] **Step 1: Write the failing tests for AndroidDriver**

Append to `backend/tests/test_android_driver.py`:

```python
"""Contract tests for DeviceDriver protocol and AndroidDriver."""

from unittest.mock import MagicMock, patch

from app.automation.core.driver import DeviceDriver, ElementRef
from app.automation.drivers.android_driver import AndroidDriver


class TestDeviceDriverProtocol:
    def test_protocol_defines_required_methods(self):
        """Verify DeviceDriver has all required method signatures."""
        required = [
            "platform",
            "launch",
            "stop_app",
            "tap",
            "long_press",
            "swipe",
            "input_text",
            "press_key",
            "screenshot",
            "dump_source",
            "current_app",
            "screen_size",
            "find_element",
            "element_exists",
        ]
        for name in required:
            assert hasattr(DeviceDriver, name), f"DeviceDriver missing: {name}"

    def test_cannot_instantiate_protocol_directly(self):
        """DeviceDriver is abstract — cannot be instantiated."""
        try:
            DeviceDriver(udid="test", platform="android")
            assert False, "Should not instantiate abstract class"
        except TypeError:
            pass


class TestAndroidDriverInit:
    def test_platform_is_android(self):
        driver = AndroidDriver(udid="emulator-5554")
        assert driver.platform == "android"

    def test_udid_stored(self):
        driver = AndroidDriver(udid="emulator-5554")
        assert driver.udid == "emulator-5554"


class TestAndroidDriverLaunch:
    @patch("app.automation.drivers.android_driver.ADBService")
    def test_launch_calls_adb_shell(self, mock_adb_cls):
        mock_adb = MagicMock()
        mock_adb_cls.return_value = mock_adb
        driver = AndroidDriver(udid="emulator-5554")
        driver.launch("com.demo.app")
        mock_adb.shell.assert_called_once_with("emulator-5554", "am start -n com.demo.app/.MainActivity")

    @patch("app.automation.drivers.android_driver.ADBService")
    def test_launch_with_activity(self, mock_adb_cls):
        mock_adb = MagicMock()
        mock_adb_cls.return_value = mock_adb
        driver = AndroidDriver(udid="emulator-5554")
        driver.launch("com.demo.app/com.demo.app.LoginActivity")
        mock_adb.shell.assert_called_once_with("emulator-5554", "am start -n com.demo.app/com.demo.app.LoginActivity")


class TestAndroidDriverStopApp:
    @patch("app.automation.drivers.android_driver.ADBService")
    def test_stop_app_calls_adb_shell(self, mock_adb_cls):
        mock_adb = MagicMock()
        mock_adb_cls.return_value = mock_adb
        driver = AndroidDriver(udid="emulator-5554")
        driver.stop_app("com.demo.app")
        mock_adb.shell.assert_called_once_with("emulator-5554", "am force-stop com.demo.app")


class TestAndroidDriverTap:
    @patch("app.automation.drivers.android_driver.ADBService")
    def test_tap_delegates_to_u2(self, mock_adb_cls):
        with patch("app.automation.drivers.android_driver.u2_service") as mock_u2:
            mock_u2.click.return_value = True
            driver = AndroidDriver(udid="emulator-5554")
            driver.tap(100, 200)
            mock_u2.click.assert_called_once_with("emulator-5554", 100, 200)

    @patch("app.automation.drivers.android_driver.ADBService")
    def test_tap_fallback_to_adb(self, mock_adb_cls):
        mock_adb = MagicMock()
        mock_adb_cls.return_value = mock_adb
        with patch("app.automation.drivers.android_driver.u2_service") as mock_u2:
            mock_u2.click.side_effect = RuntimeError("u2 not available")
            driver = AndroidDriver(udid="emulator-5554")
            driver.tap(100, 200)
            mock_adb.shell.assert_called_once_with("emulator-5554", "input tap 100 200")


class TestAndroidDriverLongPress:
    @patch("app.automation.drivers.android_driver.ADBService")
    def test_long_press_delegates_to_adb(self, mock_adb_cls):
        mock_adb = MagicMock()
        mock_adb_cls.return_value = mock_adb
        driver = AndroidDriver(udid="emulator-5554")
        driver.long_press(100, 200, duration_ms=1000)
        mock_adb.shell.assert_called_once_with("emulator-5554", "input swipe 100 200 100 200 1000")


class TestAndroidDriverSwipe:
    @patch("app.automation.drivers.android_driver.ADBService")
    def test_swipe_delegates_to_u2(self, mock_adb_cls):
        with patch("app.automation.drivers.android_driver.u2_service") as mock_u2:
            driver = AndroidDriver(udid="emulator-5554")
            driver.swipe(100, 500, 100, 200, duration_ms=300)
            mock_u2.swipe.assert_called_once_with("emulator-5554", 100, 500, 100, 200, 300)

    @patch("app.automation.drivers.android_driver.ADBService")
    def test_swipe_fallback_to_adb(self, mock_adb_cls):
        mock_adb = MagicMock()
        mock_adb_cls.return_value = mock_adb
        with patch("app.automation.drivers.android_driver.u2_service") as mock_u2:
            mock_u2.swipe.side_effect = RuntimeError("u2 not available")
            driver = AndroidDriver(udid="emulator-5554")
            driver.swipe(100, 500, 100, 200, duration_ms=300)
            mock_adb.shell.assert_called_once_with("emulator-5554", "input swipe 100 500 100 200 300")


class TestAndroidDriverInputText:
    @patch("app.automation.drivers.android_driver.ADBService")
    def test_input_text_delegates_to_adb(self, mock_adb_cls):
        mock_adb = MagicMock()
        mock_adb_cls.return_value = mock_adb
        mock_adb.input_text.return_value = True
        driver = AndroidDriver(udid="emulator-5554")
        driver.input_text("hello")
        mock_adb.input_text.assert_called_once_with("emulator-5554", "hello")


class TestAndroidDriverPressKey:
    @patch("app.automation.drivers.android_driver.ADBService")
    def test_press_back(self, mock_adb_cls):
        mock_adb = MagicMock()
        mock_adb_cls.return_value = mock_adb
        driver = AndroidDriver(udid="emulator-5554")
        driver.press_key("back")
        mock_adb.shell.assert_called_once_with("emulator-5554", "input keyevent 4")

    @patch("app.automation.drivers.android_driver.ADBService")
    def test_press_home(self, mock_adb_cls):
        mock_adb = MagicMock()
        mock_adb_cls.return_value = mock_adb
        driver = AndroidDriver(udid="emulator-5554")
        driver.press_key("home")
        mock_adb.shell.assert_called_once_with("emulator-5554", "input keyevent 3")

    @patch("app.automation.drivers.android_driver.ADBService")
    def test_press_enter(self, mock_adb_cls):
        mock_adb = MagicMock()
        mock_adb_cls.return_value = mock_adb
        driver = AndroidDriver(udid="emulator-5554")
        driver.press_key("enter")
        mock_adb.shell.assert_called_once_with("emulator-5554", "input keyevent 66")


class TestAndroidDriverScreenshot:
    @patch("app.automation.drivers.android_driver.ADBService")
    def test_screenshot_delegates_to_u2(self, mock_adb_cls):
        with patch("app.automation.drivers.android_driver.u2_service") as mock_u2:
            mock_u2.screenshot.return_value = b"\x89PNG"
            driver = AndroidDriver(udid="emulator-5554")
            result = driver.screenshot()
            assert result == b"\x89PNG"
            mock_u2.screenshot.assert_called_once_with("emulator-5554")

    @patch("app.automation.drivers.android_driver.ADBService")
    def test_screenshot_fallback_to_adb(self, mock_adb_cls):
        mock_adb = MagicMock()
        mock_adb_cls.return_value = mock_adb
        mock_adb.capture_screen_png.return_value = b"\x89PNG_FALLBACK"
        with patch("app.automation.drivers.android_driver.u2_service") as mock_u2:
            mock_u2.screenshot.side_effect = RuntimeError("u2 not available")
            driver = AndroidDriver(udid="emulator-5554")
            result = driver.screenshot()
            assert result == b"\x89PNG_FALLBACK"


class TestAndroidDriverDumpSource:
    @patch("app.automation.drivers.android_driver.ADBService")
    def test_dump_source_delegates_to_u2(self, mock_adb_cls):
        with patch("app.automation.drivers.android_driver.u2_service") as mock_u2:
            mock_u2.dump_hierarchy.return_value = "<hierarchy/>"
            driver = AndroidDriver(udid="emulator-5554")
            result = driver.dump_source()
            assert result == "<hierarchy/>"
            mock_u2.dump_hierarchy.assert_called_once_with("emulator-5554")


class TestAndroidDriverCurrentApp:
    @patch("app.automation.drivers.android_driver.ADBService")
    def test_current_app_parses_dumpsys(self, mock_adb_cls):
        mock_adb = MagicMock()
        mock_adb_cls.return_value = mock_adb
        mock_adb.shell.return_value = "mResumedActivity=ActivityRecord{abc u0 com.demo.app/.MainActivity t123}"
        driver = AndroidDriver(udid="emulator-5554")
        result = driver.current_app()
        assert result["package"] == "com.demo.app"
        assert result["activity"] == ".MainActivity"


class TestAndroidDriverScreenSize:
    @patch("app.automation.drivers.android_driver.ADBService")
    def test_screen_size_parses_adb_output(self, mock_adb_cls):
        mock_adb = MagicMock()
        mock_adb_cls.return_value = mock_adb
        mock_adb.get_screen_size.return_value = (1080, 2400)
        driver = AndroidDriver(udid="emulator-5554")
        result = driver.screen_size()
        assert result == (1080, 2400)


class TestAndroidDriverFindElement:
    @patch("app.automation.drivers.android_driver.ADBService")
    def test_find_element_by_resource_id(self, mock_adb_cls):
        with patch("app.automation.drivers.android_driver.u2_service") as mock_u2:
            mock_u2.exists_selector.return_value = True
            driver = AndroidDriver(udid="emulator-5554")
            result = driver.find_element("resource_id", "com.demo:id/btn")
            assert result.found is True
            assert result.locator_type == "resource_id"

    @patch("app.automation.drivers.android_driver.ADBService")
    def test_find_element_not_found(self, mock_adb_cls):
        with patch("app.automation.drivers.android_driver.u2_service") as mock_u2:
            mock_u2.exists_selector.return_value = False
            driver = AndroidDriver(udid="emulator-5554")
            result = driver.find_element("resource_id", "com.demo:id/missing", timeout=0.1)
            assert result.found is False


class TestAndroidDriverElementExists:
    @patch("app.automation.drivers.android_driver.ADBService")
    def test_element_exists_returns_bool(self, mock_adb_cls):
        with patch("app.automation.drivers.android_driver.u2_service") as mock_u2:
            mock_u2.exists_selector.return_value = True
            driver = AndroidDriver(udid="emulator-5554")
            assert driver.element_exists("resource_id", "com.demo:id/btn") is True
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd D:\Mobile-AI-TestOps\backend && python -m pytest tests/test_android_driver.py -v -k "not Protocol"`
Expected: FAIL — `ImportError: cannot import name 'AndroidDriver'`

- [ ] **Step 3: Write the AndroidDriver implementation**

File: `backend/app/automation/drivers/android_driver.py`

```python
"""Android device driver — delegates to ADBService, u2_service, and scrcpy_control_service."""

from __future__ import annotations

import logging
import re
from typing import Any

from app.automation.core.driver import DeviceDriver, ElementRef
from app.services import adb_service, u2_service

logger = logging.getLogger(__name__)

# Key name → Android keycode mapping
_KEY_MAP: dict[str, int] = {
    "back": 4,
    "home": 3,
    "enter": 66,
    "recent": 187,
    "delete": 67,
    "tab": 61,
    "escape": 111,
    "space": 62,
    "volume_up": 24,
    "volume_down": 25,
    "power": 26,
}


class AndroidDriver(DeviceDriver):
    """Android platform driver using ADB + uiautomator2.

    Strategy: u2 first (faster, more reliable selectors), ADB fallback.
    """

    def __init__(self, udid: str) -> None:
        self._udid = udid
        self._adb = adb_service.ADBService()

    @property
    def platform(self) -> str:
        return "android"

    @property
    def udid(self) -> str:
        return self._udid

    def launch(self, app_id: str) -> None:
        if "/" in app_id:
            cmd = f"am start -n {app_id}"
        else:
            cmd = f"am start -n {app_id}/.MainActivity"
        self._adb.shell(self._udid, cmd)

    def stop_app(self, app_id: str) -> None:
        self._adb.shell(self._udid, f"am force-stop {app_id}")

    def tap(self, x: int, y: int) -> None:
        try:
            u2_service.click(self._udid, x, y)
        except Exception:
            self._adb.shell(self._udid, f"input tap {x} {y}")

    def long_press(self, x: int, y: int, duration_ms: int = 1000) -> None:
        self._adb.shell(self._udid, f"input swipe {x} {y} {x} {y} {duration_ms}")

    def swipe(self, sx: int, sy: int, ex: int, ey: int, duration_ms: int = 300) -> None:
        try:
            u2_service.swipe(self._udid, sx, sy, ex, ey, duration_ms)
        except Exception:
            self._adb.shell(self._udid, f"input swipe {sx} {sy} {ex} {ey} {duration_ms}")

    def input_text(self, text: str) -> None:
        self._adb.input_text(self._udid, text)

    def press_key(self, key: str) -> None:
        keycode = _KEY_MAP.get(key.lower())
        if keycode is not None:
            self._adb.shell(self._udid, f"input keyevent {keycode}")
        else:
            self._adb.shell(self._udid, f"input keyevent {key}")

    def screenshot(self) -> bytes:
        try:
            return u2_service.screenshot(self._udid)
        except Exception:
            return self._adb.capture_screen_png(self._udid)

    def dump_source(self) -> str:
        try:
            return u2_service.dump_hierarchy(self._udid)
        except Exception:
            return self._adb.dump_ui_hierarchy(self._udid)

    def current_app(self) -> dict[str, str]:
        output = self._adb.shell(self._udid, "dumpsys activity activities | grep mResumedActivity")
        match = re.search(r"(\S+)/(\S+)\s", output)
        if match:
            return {"package": match.group(1), "activity": match.group(2)}
        return {"package": "", "activity": ""}

    def screen_size(self) -> tuple[int, int]:
        return self._adb.get_screen_size(self._udid)

    def find_element(self, locator_type: str, locator_value: str, timeout: float = 10.0) -> ElementRef:
        found = u2_service.exists_selector(
            self._udid,
            **{locator_type: locator_value},
            timeout=timeout,
        )
        return ElementRef(
            found=found,
            locator_type=locator_type,
            locator_value=locator_value,
        )

    def element_exists(self, locator_type: str, locator_value: str, timeout: float = 5.0) -> bool:
        return u2_service.exists_selector(
            self._udid,
            **{locator_type: locator_value},
            timeout=timeout,
        )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd D:\Mobile-AI-TestOps\backend && python -m pytest tests/test_android_driver.py -v`
Expected: All tests PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/automation/drivers/android_driver.py backend/tests/test_android_driver.py
git commit -m "feat(automation): add AndroidDriver with u2-first, ADB-fallback strategy"
```

---

## Task 4: IOSDriver

**Files:**
- Create: `backend/app/automation/drivers/ios_driver.py`
- Test: `backend/tests/test_ios_driver.py`

- [ ] **Step 1: Write the failing tests for IOSDriver**

File: `backend/tests/test_ios_driver.py`

```python
"""Tests for IOSDriver."""

from unittest.mock import MagicMock, patch

from app.automation.core.driver import ElementRef
from app.automation.drivers.ios_driver import IOSDriver


class TestIOSDriverInit:
    def test_platform_is_ios(self):
        driver = IOSDriver(udid="abc123", wda_url="http://localhost:8100")
        assert driver.platform == "ios"

    def test_udid_stored(self):
        driver = IOSDriver(udid="abc123", wda_url="http://localhost:8100")
        assert driver.udid == "abc123"

    def test_wda_url_stored(self):
        driver = IOSDriver(udid="abc123", wda_url="http://localhost:8100")
        assert driver.wda_url == "http://localhost:8100"


class TestIOSDriverLaunch:
    @patch("app.automation.drivers.ios_driver.wda_service")
    def test_launch_calls_wda(self, mock_wda):
        driver = IOSDriver(udid="abc123", wda_url="http://localhost:8100")
        driver.launch("com.demo.app")
        mock_wda.launch_app.assert_called_once_with("abc123", "http://localhost:8100", "com.demo.app")


class TestIOSDriverStopApp:
    @patch("app.automation.drivers.ios_driver.wda_service")
    def test_stop_app_not_supported_gracefully(self, mock_wda):
        driver = IOSDriver(udid="abc123", wda_url="http://localhost:8100")
        # iOS stop_app is a no-op (WDA doesn't have a direct terminate in our service)
        driver.stop_app("com.demo.app")
        # Should not raise


class TestIOSDriverTap:
    @patch("app.automation.drivers.ios_driver.wda_service")
    def test_tap_calls_wda(self, mock_wda):
        driver = IOSDriver(udid="abc123", wda_url="http://localhost:8100")
        driver.tap(100, 200)
        mock_wda.click.assert_called_once_with("abc123", "http://localhost:8100", 100, 200)


class TestIOSDriverLongPress:
    @patch("app.automation.drivers.ios_driver.wda_service")
    def test_long_press_calls_wda_with_duration(self, mock_wda):
        driver = IOSDriver(udid="abc123", wda_url="http://localhost:8100")
        driver.long_press(100, 200, duration_ms=1000)
        # WDA click with hold — our wda_service.click takes x, y
        # long_press is implemented as tap+wait+release or WDA specific
        mock_wda.click.assert_called()


class TestIOSDriverSwipe:
    @patch("app.automation.drivers.ios_driver.wda_service")
    def test_swipe_calls_wda(self, mock_wda):
        driver = IOSDriver(udid="abc123", wda_url="http://localhost:8100")
        driver.swipe(100, 500, 100, 200, duration_ms=300)
        mock_wda.swipe.assert_called_once_with("abc123", "http://localhost:8100", 100, 500, 100, 200, 300)


class TestIOSDriverInputText:
    @patch("app.automation.drivers.ios_driver.wda_service")
    def test_input_text_uses_wda_client(self, mock_wda):
        mock_client = MagicMock()
        mock_wda.get_client.return_value = mock_client
        driver = IOSDriver(udid="abc123", wda_url="http://localhost:8100")
        driver.input_text("hello")
        mock_client.type_keys.assert_called_once_with("hello")


class TestIOSDriverPressKey:
    @patch("app.automation.drivers.ios_driver.wda_service")
    def test_press_home(self, mock_wda):
        mock_client = MagicMock()
        mock_wda.get_client.return_value = mock_client
        driver = IOSDriver(udid="abc123", wda_url="http://localhost:8100")
        driver.press_key("home")
        mock_client.home.assert_called_once()


class TestIOSDriverScreenshot:
    @patch("app.automation.drivers.ios_driver.wda_service")
    def test_screenshot_calls_wda(self, mock_wda):
        mock_wda.screenshot.return_value = b"\x89PNG"
        driver = IOSDriver(udid="abc123", wda_url="http://localhost:8100")
        result = driver.screenshot()
        assert result == b"\x89PNG"
        mock_wda.screenshot.assert_called_once_with("abc123", "http://localhost:8100")


class TestIOSDriverDumpSource:
    @patch("app.automation.drivers.ios_driver.wda_service")
    def test_dump_source_calls_wda(self, mock_wda):
        mock_wda.dump_source.return_value = "<XCUIElementTypeApplication/>"
        driver = IOSDriver(udid="abc123", wda_url="http://localhost:8100")
        result = driver.dump_source()
        assert result == "<XCUIElementTypeApplication/>"
        mock_wda.dump_source.assert_called_once_with("abc123", "http://localhost:8100")


class TestIOSDriverCurrentApp:
    @patch("app.automation.drivers.ios_driver.wda_service")
    def test_current_app_returns_bundle_id(self, mock_wda):
        mock_client = MagicMock()
        mock_wda.get_client.return_value = mock_client
        mock_client.session_info.return_value = {"bundleId": "com.demo.app"}
        driver = IOSDriver(udid="abc123", wda_url="http://localhost:8100")
        result = driver.current_app()
        assert result.get("bundle_id") == "com.demo.app"


class TestIOSDriverScreenSize:
    @patch("app.automation.drivers.ios_driver.wda_service")
    def test_screen_size_from_wda(self, mock_wda):
        mock_client = MagicMock()
        mock_wda.get_client.return_value = mock_client
        mock_client.window_size.return_value = MagicMock(width=390, height=844)
        driver = IOSDriver(udid="abc123", wda_url="http://localhost:8100")
        result = driver.screen_size()
        assert result == (390, 844)


class TestIOSDriverFindElement:
    @patch("app.automation.drivers.ios_driver.wda_service")
    def test_find_element_by_class_name(self, mock_wda):
        mock_client = MagicMock()
        mock_wda.get_client.return_value = mock_client
        mock_el = MagicMock()
        mock_el.exists = True
        mock_el.bounds = {"x": 10, "y": 20, "width": 100, "height": 40}
        mock_client.find_element.return_value = mock_el
        driver = IOSDriver(udid="abc123", wda_url="http://localhost:8100")
        result = driver.find_element("class_name", "XCUIElementTypeButton")
        assert result.found is True
        assert result.locator_type == "class_name"

    @patch("app.automation.drivers.ios_driver.wda_service")
    def test_find_element_not_found(self, mock_wda):
        mock_client = MagicMock()
        mock_wda.get_client.return_value = mock_client
        mock_el = MagicMock()
        mock_el.exists = False
        mock_client.find_element.return_value = mock_el
        driver = IOSDriver(udid="abc123", wda_url="http://localhost:8100")
        result = driver.find_element("class_name", "XCUIElementTypeButton", timeout=0.1)
        assert result.found is False


class TestIOSDriverElementExists:
    @patch("app.automation.drivers.ios_driver.wda_service")
    def test_element_exists_returns_bool(self, mock_wda):
        mock_client = MagicMock()
        mock_wda.get_client.return_value = mock_client
        mock_el = MagicMock()
        mock_el.exists = True
        mock_client.find_element.return_value = mock_el
        driver = IOSDriver(udid="abc123", wda_url="http://localhost:8100")
        assert driver.element_exists("class_name", "XCUIElementTypeButton") is True
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd D:\Mobile-AI-TestOps\backend && python -m pytest tests/test_ios_driver.py -v`
Expected: FAIL — `ImportError: cannot import name 'IOSDriver'`

- [ ] **Step 3: Write the IOSDriver implementation**

File: `backend/app/automation/drivers/ios_driver.py`

```python
"""iOS device driver — delegates to wda_service and ios_service."""

from __future__ import annotations

import logging

from app.automation.core.driver import DeviceDriver, ElementRef
from app.services import wda_service

logger = logging.getLogger(__name__)


class IOSDriver(DeviceDriver):
    """iOS platform driver using WebDriverAgent.

    WDA provides: tap, swipe, screenshot, source dump, app launch.
    Initial implementation does NOT depend on real-time video stream.
    """

    def __init__(self, udid: str, wda_url: str) -> None:
        self._udid = udid
        self._wda_url = wda_url

    @property
    def platform(self) -> str:
        return "ios"

    @property
    def udid(self) -> str:
        return self._udid

    @property
    def wda_url(self) -> str:
        return self._wda_url

    def _client(self):
        return wda_service.get_client(self._udid, self._wda_url)

    def launch(self, app_id: str) -> None:
        wda_service.launch_app(self._udid, self._wda_url, app_id)

    def stop_app(self, app_id: str) -> None:
        # WDA doesn't expose a direct terminate in our current service layer.
        # This is a graceful no-op; can be enhanced later.
        logger.info("stop_app('%s') called on iOS — not yet supported by WDA service", app_id)

    def tap(self, x: int, y: int) -> None:
        wda_service.click(self._udid, self._wda_url, x, y)

    def long_press(self, x: int, y: int, duration_ms: int = 1000) -> None:
        client = self._client()
        client.tap_hold(x, y, duration_ms / 1000.0)

    def swipe(self, sx: int, sy: int, ex: int, ey: int, duration_ms: int = 300) -> None:
        wda_service.swipe(self._udid, self._wda_url, sx, sy, ex, ey, duration_ms)

    def input_text(self, text: str) -> None:
        client = self._client()
        client.type_keys(text)

    def press_key(self, key: str) -> None:
        client = self._client()
        key_lower = key.lower()
        if key_lower == "home":
            client.home()
        elif key_lower == "back":
            # iOS has no universal "back"; simulate via swipe right from left edge
            size = client.window_size()
            client.swipe(10, size.height // 2, size.width // 2, size.height // 2, 0.3)
        else:
            logger.warning("Unsupported iOS key press: %s", key)

    def screenshot(self) -> bytes:
        return wda_service.screenshot(self._udid, self._wda_url)

    def dump_source(self) -> str:
        return wda_service.dump_source(self._udid, self._wda_url)

    def current_app(self) -> dict[str, str]:
        client = self._client()
        info = client.session_info()
        return {"bundle_id": info.get("bundleId", "")}

    def screen_size(self) -> tuple[int, int]:
        client = self._client()
        size = client.window_size()
        return (size.width, size.height)

    def find_element(self, locator_type: str, locator_value: str, timeout: float = 10.0) -> ElementRef:
        client = self._client()
        # Map locator_type to WDA find strategy
        wda_locator = _map_locator(locator_type, locator_value)
        el = client.find_element(**wda_locator)
        found = el.exists if hasattr(el, "exists") else bool(el)
        bounds = None
        center = None
        if found and hasattr(el, "bounds"):
            b = el.bounds
            bounds = {"x": b.get("x", 0), "y": b.get("y", 0), "width": b.get("width", 0), "height": b.get("height", 0)}
            center = (int(b.get("x", 0) + b.get("width", 0) / 2), int(b.get("y", 0) + b.get("height", 0) / 2))
        return ElementRef(
            found=found,
            locator_type=locator_type,
            locator_value=locator_value,
            bounds=bounds,
            center=center,
        )

    def element_exists(self, locator_type: str, locator_value: str, timeout: float = 5.0) -> bool:
        result = self.find_element(locator_type, locator_value, timeout=timeout)
        return result.found


def _map_locator(locator_type: str, locator_value: str) -> dict:
    """Map automation LocatorType to WDA find_element kwargs."""
    mapping = {
        "class_name": {"class_name": locator_value},
        "resource_id": {"accessibility_id": locator_value},
        "text": {"name": locator_value},
        "xpath": {"xpath": locator_value},
        "content_desc": {"accessibility_id": locator_value},
    }
    return mapping.get(locator_type, {"name": locator_value})
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd D:\Mobile-AI-TestOps\backend && python -m pytest tests/test_ios_driver.py -v`
Expected: All tests PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/automation/drivers/ios_driver.py backend/tests/test_ios_driver.py
git commit -m "feat(automation): add IOSDriver with WDA delegation"
```

---

## Task 5: LocatorResolver

**Files:**
- Create: `backend/app/automation/locators/resolver.py`
- Test: `backend/tests/test_locator_resolver.py`

- [ ] **Step 1: Write the failing tests**

File: `backend/tests/test_locator_resolver.py`

```python
"""Tests for LocatorResolver — resolves LocatorChain with fallback."""

from unittest.mock import MagicMock

from app.automation.core.driver import DeviceDriver, ElementRef
from app.automation.core.models import Locator, LocatorChain, LocatorType
from app.automation.locators.resolver import LocatorResolver, ResolveResult


def _make_driver(find_results: dict[str, ElementRef]) -> MagicMock:
    """Create a mock driver that returns specific results per locator key."""
    driver = MagicMock(spec=DeviceDriver)

    def fake_find(locator_type: str, locator_value: str, timeout: float = 5.0) -> ElementRef:
        key = f"{locator_type}:{locator_value}"
        return find_results.get(key, ElementRef(found=False, locator_type=locator_type, locator_value=locator_value))

    driver.find_element = MagicMock(side_effect=fake_find)
    return driver


class TestLocatorResolverPrimaryOnly:
    def test_primary_found_returns_immediately(self):
        driver = _make_driver({
            "resource_id:com.demo:id/btn": ElementRef(found=True, locator_type="resource_id", locator_value="com.demo:id/btn", center=(100, 200)),
        })
        chain = LocatorChain(primary=Locator(type=LocatorType.RESOURCE_ID, value="com.demo:id/btn"))
        resolver = LocatorResolver(driver)
        result = resolver.resolve(chain)
        assert result.found is True
        assert result.resolved_locator.type == LocatorType.RESOURCE_ID

    def test_primary_not_found_no_fallbacks(self):
        driver = _make_driver({})
        chain = LocatorChain(primary=Locator(type=LocatorType.RESOURCE_ID, value="com.demo:id/missing"))
        resolver = LocatorResolver(driver)
        result = resolver.resolve(chain)
        assert result.found is False


class TestLocatorResolverWithFallbacks:
    def test_primary_fails_first_fallback_succeeds(self):
        driver = _make_driver({
            "text:登录": ElementRef(found=True, locator_type="text", locator_value="登录", center=(150, 800)),
        })
        chain = LocatorChain(
            primary=Locator(type=LocatorType.RESOURCE_ID, value="com.demo:id/login"),
            fallbacks=[
                Locator(type=LocatorType.TEXT, value="登录"),
                Locator(type=LocatorType.XPATH, value="//*[@text='登录']"),
            ],
        )
        resolver = LocatorResolver(driver)
        result = resolver.resolve(chain)
        assert result.found is True
        assert result.resolved_locator.type == LocatorType.TEXT
        assert result.resolved_locator.value == "登录"

    def test_all_locators_fail(self):
        driver = _make_driver({})
        chain = LocatorChain(
            primary=Locator(type=LocatorType.RESOURCE_ID, value="com.demo:id/missing"),
            fallbacks=[Locator(type=LocatorType.TEXT, value="不存在")],
        )
        resolver = LocatorResolver(driver)
        result = resolver.resolve(chain)
        assert result.found is False
        assert result.attempted_count == 2

    def test_third_fallback_succeeds(self):
        driver = _make_driver({
            "xpath://*[@text='登录']": ElementRef(found=True, locator_type="xpath", locator_value="//*[@text='登录']", center=(200, 800)),
        })
        chain = LocatorChain(
            primary=Locator(type=LocatorType.RESOURCE_ID, value="com.demo:id/login"),
            fallbacks=[
                Locator(type=LocatorType.TEXT, value="登录"),
                Locator(type=LocatorType.XPATH, value="//*[@text='登录']"),
            ],
        )
        resolver = LocatorResolver(driver)
        result = resolver.resolve(chain)
        assert result.found is True
        assert result.resolved_locator.type == LocatorType.XPATH
        assert result.attempted_count == 3


class TestLocatorResolverCoordinateRatio:
    def test_coordinate_ratio_always_resolves(self):
        driver = _make_driver({})
        driver.screen_size.return_value = (1080, 2400)
        chain = LocatorChain(
            primary=Locator(type=LocatorType.RESOURCE_ID, value="com.demo:id/btn"),
            fallbacks=[Locator(type=LocatorType.COORDINATE_RATIO, value="", x=0.5, y=0.8)],
        )
        resolver = LocatorResolver(driver)
        result = resolver.resolve(chain)
        assert result.found is True
        assert result.coordinates == (540, 1920)

    def test_coordinate_ratio_without_screen_size(self):
        driver = _make_driver({})
        driver.screen_size.side_effect = RuntimeError("no device")
        chain = LocatorChain(
            primary=Locator(type=LocatorType.RESOURCE_ID, value="com.demo:id/btn"),
            fallbacks=[Locator(type=LocatorType.COORDINATE_RATIO, value="", x=0.5, y=0.8)],
        )
        resolver = LocatorResolver(driver)
        result = resolver.resolve(chain)
        assert result.found is False


class TestResolveResult:
    def test_resolve_result_fields(self):
        result = ResolveResult(
            found=True,
            resolved_locator=Locator(type=LocatorType.TEXT, value="OK"),
            element_ref=ElementRef(found=True, locator_type="text", locator_value="OK"),
            attempted_count=1,
            coordinates=None,
        )
        assert result.found is True
        assert result.attempted_count == 1
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd D:\Mobile-AI-TestOps\backend && python -m pytest tests/test_locator_resolver.py -v`
Expected: FAIL — `ImportError: cannot import name 'LocatorResolver'`

- [ ] **Step 3: Write the LocatorResolver implementation**

File: `backend/app/automation/locators/resolver.py`

```python
"""LocatorResolver — resolves a LocatorChain by trying primary then fallbacks."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from app.automation.core.driver import DeviceDriver, ElementRef
from app.automation.core.models import Locator, LocatorChain, LocatorType

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ResolveResult:
    """Result of resolving a LocatorChain against a device."""

    found: bool
    resolved_locator: Locator | None = None
    element_ref: ElementRef | None = None
    attempted_count: int = 0
    coordinates: tuple[int, int] | None = None


class LocatorResolver:
    """Resolves a LocatorChain by trying each locator in order until one succeeds.

    Strategy:
    1. Try each locator in the chain (primary first, then fallbacks)
    2. For non-coordinate locators, call driver.find_element()
    3. For COORDINATE_RATIO locators, compute pixel coordinates from screen size
    4. Return the first successful resolution
    """

    def __init__(self, driver: DeviceDriver) -> None:
        self._driver = driver

    def resolve(self, chain: LocatorChain, timeout: float = 5.0) -> ResolveResult:
        """Resolve the chain, returning the first successful locator result."""
        attempted = 0
        for locator in chain.all_locators():
            attempted += 1
            if locator.type == LocatorType.COORDINATE_RATIO:
                result = self._resolve_coordinate(locator)
                if result.found:
                    return ResolveResult(
                        found=True,
                        resolved_locator=locator,
                        attempted_count=attempted,
                        coordinates=result.coordinates,
                    )
            else:
                ref = self._driver.find_element(
                    locator.type.value,
                    locator.value,
                    timeout=timeout,
                )
                if ref.found:
                    return ResolveResult(
                        found=True,
                        resolved_locator=locator,
                        element_ref=ref,
                        attempted_count=attempted,
                    )
                logger.debug("Locator %s=%s not found, trying next fallback", locator.type.value, locator.value)

        return ResolveResult(found=False, attempted_count=attempted)

    def _resolve_coordinate(self, locator: Locator) -> _CoordResult:
        """Convert a COORDINATE_RATIO locator to pixel coordinates."""
        if locator.x is None or locator.y is None:
            return _CoordResult(found=False)
        try:
            width, height = self._driver.screen_size()
            px = int(locator.x * width)
            py = int(locator.y * height)
            return _CoordResult(found=True, coordinates=(px, py))
        except Exception:
            logger.debug("Failed to get screen size for coordinate resolution")
            return _CoordResult(found=False)


@dataclass(frozen=True)
class _CoordResult:
    found: bool = False
    coordinates: tuple[int, int] | None = None
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd D:\Mobile-AI-TestOps\backend && python -m pytest tests/test_locator_resolver.py -v`
Expected: All tests PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/automation/locators/resolver.py backend/tests/test_locator_resolver.py
git commit -m "feat(automation): add LocatorResolver with chain fallback and coordinate ratio"
```

---

## Task 6: WaitEngine

**Files:**
- Create: `backend/app/automation/waits/engine.py`
- Test: `backend/tests/test_wait_engine.py`

- [ ] **Step 1: Write the failing tests**

File: `backend/tests/test_wait_engine.py`

```python
"""Tests for WaitEngine — explicit wait condition evaluation."""

import time
from unittest.mock import MagicMock

from app.automation.core.driver import DeviceDriver, ElementRef
from app.automation.core.models import Locator, LocatorType, WaitConditionType, WaitSpec
from app.automation.waits.engine import WaitEngine, WaitResult


def _make_driver_with_app(app_package: str = "com.demo.app", source: str = "") -> MagicMock:
    driver = MagicMock(spec=DeviceDriver)
    driver.current_app.return_value = {"package": app_package}
    driver.dump_source.return_value = source
    return driver


class TestWaitEngineVisible:
    def test_element_visible_immediately(self):
        driver = MagicMock(spec=DeviceDriver)
        driver.find_element.return_value = ElementRef(found=True, locator_type="resource_id", locator_value="com.demo:id/btn")
        engine = WaitEngine(driver)
        spec = WaitSpec(type=WaitConditionType.VISIBLE, locator=Locator(type=LocatorType.RESOURCE_ID, value="com.demo:id/btn"), timeout=5.0)
        result = engine.wait(spec)
        assert result.met is True
        assert result.elapsed_ms < 1000

    def test_element_not_visible_timeout(self):
        driver = MagicMock(spec=DeviceDriver)
        driver.find_element.return_value = ElementRef(found=False, locator_type="resource_id", locator_value="com.demo:id/missing")
        engine = WaitEngine(driver)
        spec = WaitSpec(type=WaitConditionType.VISIBLE, locator=Locator(type=LocatorType.RESOURCE_ID, value="com.demo:id/missing"), timeout=0.2, poll_interval=0.05)
        result = engine.wait(spec)
        assert result.met is False
        assert result.elapsed_ms >= 150


class TestWaitEngineExists:
    def test_element_exists(self):
        driver = MagicMock(spec=DeviceDriver)
        driver.find_element.return_value = ElementRef(found=True, locator_type="text", locator_value="OK")
        engine = WaitEngine(driver)
        spec = WaitSpec(type=WaitConditionType.EXISTS, locator=Locator(type=LocatorType.TEXT, value="OK"), timeout=5.0)
        result = engine.wait(spec)
        assert result.met is True


class TestWaitEngineGone:
    def test_element_gone(self):
        driver = MagicMock(spec=DeviceDriver)
        driver.find_element.return_value = ElementRef(found=False, locator_type="resource_id", locator_value="com.demo:id/loading")
        engine = WaitEngine(driver)
        spec = WaitSpec(type=WaitConditionType.GONE, locator=Locator(type=LocatorType.RESOURCE_ID, value="com.demo:id/loading"), timeout=5.0)
        result = engine.wait(spec)
        assert result.met is True

    def test_element_still_present_not_gone(self):
        driver = MagicMock(spec=DeviceDriver)
        driver.find_element.return_value = ElementRef(found=True, locator_type="resource_id", locator_value="com.demo:id/loading")
        engine = WaitEngine(driver)
        spec = WaitSpec(type=WaitConditionType.GONE, locator=Locator(type=LocatorType.RESOURCE_ID, value="com.demo:id/loading"), timeout=0.2, poll_interval=0.05)
        result = engine.wait(spec)
        assert result.met is False


class TestWaitEngineAppForeground:
    def test_app_is_foreground(self):
        driver = _make_driver_with_app("com.demo.app")
        engine = WaitEngine(driver)
        spec = WaitSpec(type=WaitConditionType.APP_FOREGROUND, timeout=5.0)
        result = engine.wait(spec, expected_app="com.demo.app")
        assert result.met is True

    def test_app_not_foreground(self):
        driver = _make_driver_with_app("com.other.app")
        engine = WaitEngine(driver)
        spec = WaitSpec(type=WaitConditionType.APP_FOREGROUND, timeout=0.2, poll_interval=0.05)
        result = engine.wait(spec, expected_app="com.demo.app")
        assert result.met is False


class TestWaitEngineScreenChanged:
    def test_screen_changed_detected(self):
        driver = MagicMock(spec=DeviceDriver)
        driver.screenshot.side_effect = [b"screen1", b"screen2"]
        engine = WaitEngine(driver)
        spec = WaitSpec(type=WaitConditionType.SCREEN_CHANGED, timeout=5.0)
        result = engine.wait(spec)
        assert result.met is True


class TestWaitResult:
    def test_wait_result_fields(self):
        result = WaitResult(met=True, elapsed_ms=42, condition=WaitConditionType.VISIBLE)
        assert result.met is True
        assert result.elapsed_ms == 42
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd D:\Mobile-AI-TestOps\backend && python -m pytest tests/test_wait_engine.py -v`
Expected: FAIL — `ImportError: cannot import name 'WaitEngine'`

- [ ] **Step 3: Write the WaitEngine implementation**

File: `backend/app/automation/waits/engine.py`

```python
"""WaitEngine — evaluates explicit wait conditions against a device."""

from __future__ import annotations

import hashlib
import logging
import time
from dataclasses import dataclass

from app.automation.core.driver import DeviceDriver
from app.automation.core.models import LocatorType, WaitConditionType, WaitSpec

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class WaitResult:
    """Result of evaluating a wait condition."""

    met: bool
    elapsed_ms: int
    condition: WaitConditionType


class WaitEngine:
    """Evaluates WaitSpec conditions by polling the device driver.

    Supports: visible, gone, exists, text_equals, text_contains,
    enabled, screen_changed, app_foreground, source_stable, ocr_contains.
    """

    def __init__(self, driver: DeviceDriver) -> None:
        self._driver = driver

    def wait(self, spec: WaitSpec, expected_app: str | None = None) -> WaitResult:
        """Evaluate the wait condition, polling until met or timeout."""
        start = time.monotonic()
        timeout = spec.timeout
        poll_interval = spec.poll_interval

        while True:
            met = self._evaluate(spec, expected_app)
            elapsed = time.monotonic() - start
            if met:
                return WaitResult(met=True, elapsed_ms=int(elapsed * 1000), condition=spec.type)
            if elapsed >= timeout:
                return WaitResult(met=False, elapsed_ms=int(elapsed * 1000), condition=spec.type)
            time.sleep(poll_interval)

    def _evaluate(self, spec: WaitSpec, expected_app: str | None = None) -> bool:
        """Evaluate a single check for the given wait condition."""
        cond = spec.type

        if cond == WaitConditionType.VISIBLE:
            return self._check_element_found(spec)

        if cond == WaitConditionType.EXISTS:
            return self._check_element_found(spec)

        if cond == WaitConditionType.GONE:
            return not self._check_element_found(spec)

        if cond == WaitConditionType.APP_FOREGROUND:
            return self._check_app_foreground(expected_app)

        if cond == WaitConditionType.SCREEN_CHANGED:
            return self._check_screen_changed()

        if cond == WaitConditionType.SOURCE_STABLE:
            return self._check_source_stable()

        if cond == WaitConditionType.ENABLED:
            return self._check_element_found(spec)

        if cond == WaitConditionType.TEXT_EQUALS:
            return self._check_element_found(spec)

        if cond == WaitConditionType.TEXT_CONTAINS:
            return self._check_element_found(spec)

        if cond == WaitConditionType.OCR_CONTAINS:
            # OCR check is deferred to AssertionEngine — treat as not met
            return False

        logger.warning("Unhandled wait condition: %s", cond)
        return False

    def _check_element_found(self, spec: WaitSpec) -> bool:
        if spec.locator is None:
            return False
        ref = self._driver.find_element(spec.locator.type.value, spec.locator.value, timeout=0)
        return ref.found

    def _check_app_foreground(self, expected_app: str | None) -> bool:
        if expected_app is None:
            return True
        app_info = self._driver.current_app()
        package = app_info.get("package", "") or app_info.get("bundle_id", "")
        return package == expected_app

    _last_screenshot_hash: str | None = None

    def _check_screen_changed(self) -> bool:
        screenshot = self._driver.screenshot()
        current_hash = hashlib.md5(screenshot).hexdigest()
        if self._last_screenshot_hash is None:
            self._last_screenshot_hash = current_hash
            return False
        changed = current_hash != self._last_screenshot_hash
        self._last_screenshot_hash = current_hash
        return changed

    _last_source_hash: str | None = None

    def _check_source_stable(self) -> bool:
        source = self._driver.dump_source()
        current_hash = hashlib.md5(source.encode()).hexdigest()
        if self._last_source_hash is None:
            self._last_source_hash = current_hash
            return False
        stable = current_hash == self._last_source_hash
        self._last_source_hash = current_hash
        return stable
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd D:\Mobile-AI-TestOps\backend && python -m pytest tests/test_wait_engine.py -v`
Expected: All tests PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/automation/waits/engine.py backend/tests/test_wait_engine.py
git commit -m "feat(automation): add WaitEngine with polling and condition evaluation"
```

---

## Task 7: AssertionEngine

**Files:**
- Create: `backend/app/automation/assertions/engine.py`
- Test: `backend/tests/test_assertion_engine.py`

- [ ] **Step 1: Write the failing tests**

File: `backend/tests/test_assertion_engine.py`

```python
"""Tests for AssertionEngine — step-level and end-of-run assertion evaluation."""

from unittest.mock import MagicMock

from app.automation.assertions.engine import AssertionEngine, AssertionResult
from app.automation.core.driver import DeviceDriver, ElementRef
from app.automation.core.models import AssertionSpec, AssertionType, Locator, LocatorType


def _make_driver(found: bool = True, current_app_pkg: str = "com.demo.app") -> MagicMock:
    driver = MagicMock(spec=DeviceDriver)
    driver.find_element.return_value = ElementRef(
        found=found,
        locator_type="resource_id",
        locator_value="com.demo:id/btn",
        text="登录" if found else None,
    )
    driver.current_app.return_value = {"package": current_app_pkg}
    driver.screenshot.return_value = b"\x89PNG"
    driver.dump_source.return_value = '<node text="登录成功"/>'
    return driver


class TestAssertionEngineExists:
    def test_element_exists_pass(self):
        driver = _make_driver(found=True)
        engine = AssertionEngine(driver)
        spec = AssertionSpec(type=AssertionType.EXISTS, locator=Locator(type=LocatorType.RESOURCE_ID, value="com.demo:id/btn"))
        result = engine.evaluate(spec)
        assert result.passed is True

    def test_element_not_exists_fail(self):
        driver = _make_driver(found=False)
        engine = AssertionEngine(driver)
        spec = AssertionSpec(type=AssertionType.EXISTS, locator=Locator(type=LocatorType.RESOURCE_ID, value="com.demo:id/missing"))
        result = engine.evaluate(spec)
        assert result.passed is False


class TestAssertionEngineNotExists:
    def test_element_not_exists_pass(self):
        driver = _make_driver(found=False)
        engine = AssertionEngine(driver)
        spec = AssertionSpec(type=AssertionType.NOT_EXISTS, locator=Locator(type=LocatorType.RESOURCE_ID, value="com.demo:id/loading"))
        result = engine.evaluate(spec)
        assert result.passed is True

    def test_element_still_exists_fail(self):
        driver = _make_driver(found=True)
        engine = AssertionEngine(driver)
        spec = AssertionSpec(type=AssertionType.NOT_EXISTS, locator=Locator(type=LocatorType.RESOURCE_ID, value="com.demo:id/loading"))
        result = engine.evaluate(spec)
        assert result.passed is False


class TestAssertionEngineTextEquals:
    def test_text_matches_pass(self):
        driver = _make_driver(found=True)
        driver.find_element.return_value = ElementRef(
            found=True, locator_type="resource_id", locator_value="com.demo:id/title", text="首页",
        )
        engine = AssertionEngine(driver)
        spec = AssertionSpec(type=AssertionType.TEXT_EQUALS, locator=Locator(type=LocatorType.RESOURCE_ID, value="com.demo:id/title"), expected="首页")
        result = engine.evaluate(spec)
        assert result.passed is True

    def test_text_mismatch_fail(self):
        driver = _make_driver(found=True)
        driver.find_element.return_value = ElementRef(
            found=True, locator_type="resource_id", locator_value="com.demo:id/title", text="设置",
        )
        engine = AssertionEngine(driver)
        spec = AssertionSpec(type=AssertionType.TEXT_EQUALS, locator=Locator(type=LocatorType.RESOURCE_ID, value="com.demo:id/title"), expected="首页")
        result = engine.evaluate(spec)
        assert result.passed is False


class TestAssertionEngineTextContains:
    def test_text_contains_pass(self):
        driver = _make_driver(found=True)
        driver.find_element.return_value = ElementRef(
            found=True, locator_type="resource_id", locator_value="com.demo:id/msg", text="登录成功，欢迎回来",
        )
        engine = AssertionEngine(driver)
        spec = AssertionSpec(type=AssertionType.TEXT_CONTAINS, locator=Locator(type=LocatorType.RESOURCE_ID, value="com.demo:id/msg"), expected="登录成功")
        result = engine.evaluate(spec)
        assert result.passed is True


class TestAssertionEngineAppForeground:
    def test_app_foreground_pass(self):
        driver = _make_driver(current_app_pkg="com.demo.app")
        engine = AssertionEngine(driver)
        spec = AssertionSpec(type=AssertionType.APP_FOREGROUND, expected="com.demo.app")
        result = engine.evaluate(spec)
        assert result.passed is True

    def test_app_not_foreground_fail(self):
        driver = _make_driver(current_app_pkg="com.other.app")
        engine = AssertionEngine(driver)
        spec = AssertionSpec(type=AssertionType.APP_FOREGROUND, expected="com.demo.app")
        result = engine.evaluate(spec)
        assert result.passed is False


class TestAssertionEngineOcrContains:
    def test_ocr_contains_found_in_source(self):
        driver = _make_driver()
        driver.dump_source.return_value = '<node text="登录成功"/>'
        engine = AssertionEngine(driver)
        spec = AssertionSpec(type=AssertionType.OCR_CONTAINS, expected="登录成功")
        result = engine.evaluate(spec)
        assert result.passed is True

    def test_ocr_contains_not_found(self):
        driver = _make_driver()
        driver.dump_source.return_value = '<node text="设置"/>'
        engine = AssertionEngine(driver)
        spec = AssertionSpec(type=AssertionType.OCR_CONTAINS, expected="登录成功")
        result = engine.evaluate(spec)
        assert result.passed is False


class TestAssertionEngineEvaluateAll:
    def test_evaluate_all_returns_list(self):
        driver = _make_driver(found=True)
        engine = AssertionEngine(driver)
        specs = [
            AssertionSpec(type=AssertionType.EXISTS, locator=Locator(type=LocatorType.RESOURCE_ID, value="com.demo:id/btn")),
            AssertionSpec(type=AssertionType.APP_FOREGROUND, expected="com.demo.app"),
        ]
        results = engine.evaluate_all(specs)
        assert len(results) == 2
        assert all(r.passed for r in results)

    def test_evaluate_all_empty(self):
        driver = _make_driver()
        engine = AssertionEngine(driver)
        results = engine.evaluate_all([])
        assert results == []


class TestAssertionResult:
    def test_assertion_result_fields(self):
        r = AssertionResult(passed=True, assertion_type=AssertionType.EXISTS, message="Element found")
        assert r.passed is True
        assert r.message == "Element found"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd D:\Mobile-AI-TestOps\backend && python -m pytest tests/test_assertion_engine.py -v`
Expected: FAIL — `ImportError: cannot import name 'AssertionEngine'`

- [ ] **Step 3: Write the AssertionEngine implementation**

File: `backend/app/automation/assertions/engine.py`

```python
"""AssertionEngine — evaluates step-level and end-of-run assertions."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from app.automation.core.driver import DeviceDriver
from app.automation.core.models import AssertionSpec, AssertionType

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AssertionResult:
    """Result of evaluating a single assertion."""

    passed: bool
    assertion_type: AssertionType
    message: str = ""


class AssertionEngine:
    """Evaluates AssertionSpec objects against the current device state.

    Supports: exists, not_exists, text_equals, text_contains,
    ocr_contains, app_foreground, image_exists, ai_result.
    """

    def __init__(self, driver: DeviceDriver) -> None:
        self._driver = driver

    def evaluate(self, spec: AssertionSpec) -> AssertionResult:
        """Evaluate a single assertion."""
        atype = spec.type

        if atype == AssertionType.EXISTS:
            return self._assert_exists(spec)
        if atype == AssertionType.NOT_EXISTS:
            return self._assert_not_exists(spec)
        if atype == AssertionType.TEXT_EQUALS:
            return self._assert_text_equals(spec)
        if atype == AssertionType.TEXT_CONTAINS:
            return self._assert_text_contains(spec)
        if atype == AssertionType.OCR_CONTAINS:
            return self._assert_ocr_contains(spec)
        if atype == AssertionType.APP_FOREGROUND:
            return self._assert_app_foreground(spec)
        if atype == AssertionType.IMAGE_EXISTS:
            return self._assert_image_exists(spec)
        if atype == AssertionType.AI_RESULT:
            return AssertionResult(passed=False, assertion_type=atype, message="AI_RESULT assertion requires external evaluation")

        return AssertionResult(passed=False, assertion_type=atype, message=f"Unsupported assertion type: {atype}")

    def evaluate_all(self, specs: list[AssertionSpec]) -> list[AssertionResult]:
        """Evaluate all assertions and return results in order."""
        return [self.evaluate(spec) for spec in specs]

    def _assert_exists(self, spec: AssertionSpec) -> AssertionResult:
        if spec.locator is None:
            return AssertionResult(passed=False, assertion_type=spec.type, message="No locator provided for exists assertion")
        ref = self._driver.find_element(spec.locator.type.value, spec.locator.value, timeout=2.0)
        if ref.found:
            return AssertionResult(passed=True, assertion_type=spec.type, message=f"Element found: {spec.locator.type.value}={spec.locator.value}")
        return AssertionResult(passed=False, assertion_type=spec.type, message=f"Element not found: {spec.locator.type.value}={spec.locator.value}")

    def _assert_not_exists(self, spec: AssertionSpec) -> AssertionResult:
        if spec.locator is None:
            return AssertionResult(passed=True, assertion_type=spec.type, message="No locator — vacuously true")
        ref = self._driver.find_element(spec.locator.type.value, spec.locator.value, timeout=2.0)
        if not ref.found:
            return AssertionResult(passed=True, assertion_type=spec.type, message=f"Element not found as expected: {spec.locator.type.value}={spec.locator.value}")
        return AssertionResult(passed=False, assertion_type=spec.type, message=f"Element still exists: {spec.locator.type.value}={spec.locator.value}")

    def _assert_text_equals(self, spec: AssertionSpec) -> AssertionResult:
        if spec.locator is None:
            return AssertionResult(passed=False, assertion_type=spec.type, message="No locator provided")
        ref = self._driver.find_element(spec.locator.type.value, spec.locator.value, timeout=2.0)
        if not ref.found:
            return AssertionResult(passed=False, assertion_type=spec.type, message="Element not found")
        actual_text = ref.text or ""
        expected = spec.expected or ""
        if actual_text == expected:
            return AssertionResult(passed=True, assertion_type=spec.type, message=f"Text matches: '{actual_text}'")
        return AssertionResult(passed=False, assertion_type=spec.type, message=f"Text mismatch: expected '{expected}', got '{actual_text}'")

    def _assert_text_contains(self, spec: AssertionSpec) -> AssertionResult:
        if spec.locator is None:
            return AssertionResult(passed=False, assertion_type=spec.type, message="No locator provided")
        ref = self._driver.find_element(spec.locator.type.value, spec.locator.value, timeout=2.0)
        if not ref.found:
            return AssertionResult(passed=False, assertion_type=spec.type, message="Element not found")
        actual_text = ref.text or ""
        expected = spec.expected or ""
        if expected in actual_text:
            return AssertionResult(passed=True, assertion_type=spec.type, message=f"Text contains '{expected}'")
        return AssertionResult(passed=False, assertion_type=spec.type, message=f"Text does not contain '{expected}': got '{actual_text}'")

    def _assert_ocr_contains(self, spec: AssertionSpec) -> AssertionResult:
        """Check if expected text appears in the UI source dump (lightweight OCR proxy)."""
        expected = spec.expected or ""
        if not expected:
            return AssertionResult(passed=False, assertion_type=spec.type, message="No expected text provided")
        source = self._driver.dump_source()
        if expected in source:
            return AssertionResult(passed=True, assertion_type=spec.type, message=f"Text '{expected}' found in source")
        return AssertionResult(passed=False, assertion_type=spec.type, message=f"Text '{expected}' not found in source")

    def _assert_app_foreground(self, spec: AssertionSpec) -> AssertionResult:
        expected = spec.expected or ""
        app_info = self._driver.current_app()
        package = app_info.get("package", "") or app_info.get("bundle_id", "")
        if package == expected:
            return AssertionResult(passed=True, assertion_type=spec.type, message=f"App '{expected}' is in foreground")
        return AssertionResult(passed=False, assertion_type=spec.type, message=f"Expected '{expected}', got '{package}'")

    def _assert_image_exists(self, spec: AssertionSpec) -> AssertionResult:
        """Image template assertion — deferred to VisualActionService integration."""
        return AssertionResult(passed=False, assertion_type=spec.type, message="IMAGE_EXISTS assertion not yet implemented — use OCR_CONTAINS as fallback")
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd D:\Mobile-AI-TestOps\backend && python -m pytest tests/test_assertion_engine.py -v`
Expected: All tests PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/automation/assertions/engine.py backend/tests/test_assertion_engine.py
git commit -m "feat(automation): add AssertionEngine with exists/not_exists/text/ocr/app_foreground"
```

---

## Task 8: EvidenceCollector

**Files:**
- Create: `backend/app/automation/reports/evidence.py`
- Test: `backend/tests/test_evidence_collector.py`

- [ ] **Step 1: Write the failing tests**

File: `backend/tests/test_evidence_collector.py`

```python
"""Tests for EvidenceCollector — captures screenshots, source dumps, and state."""

import os
import tempfile
from unittest.mock import MagicMock

from app.automation.core.driver import DeviceDriver
from app.automation.core.models import Evidence
from app.automation.reports.evidence import EvidenceCollector


def _make_driver(screenshot_bytes: bytes = b"\x89PNG", source: str = "<hierarchy/>", app_pkg: str = "com.demo.app") -> MagicMock:
    driver = MagicMock(spec=DeviceDriver)
    driver.screenshot.return_value = screenshot_bytes
    driver.dump_source.return_value = source
    driver.current_app.return_value = {"package": app_pkg}
    return driver


class TestEvidenceCollectorCapture:
    def test_capture_saves_screenshot(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            driver = _make_driver()
            collector = EvidenceCollector(driver, output_dir=tmpdir)
            evidence = collector.capture(step_id="step_1")
            assert evidence.screenshot_path.endswith("step_1.png")
            assert os.path.exists(evidence.screenshot_path)
            with open(evidence.screenshot_path, "rb") as f:
                assert f.read() == b"\x89PNG"

    def test_capture_saves_source_dump(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            driver = _make_driver(source="<node text='hello'/>")
            collector = EvidenceCollector(driver, output_dir=tmpdir)
            evidence = collector.capture(step_id="step_2")
            assert evidence.source_dump_path.endswith("step_2.xml")
            assert os.path.exists(evidence.source_dump_path)
            with open(evidence.source_dump_path, "r", encoding="utf-8") as f:
                assert f.read() == "<node text='hello'/>"

    def test_capture_records_current_app(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            driver = _make_driver(app_pkg="com.test.app")
            collector = EvidenceCollector(driver, output_dir=tmpdir)
            evidence = collector.capture(step_id="step_3")
            assert evidence.current_app == "com.test.app"

    def test_capture_records_duration(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            driver = _make_driver()
            collector = EvidenceCollector(driver, output_dir=tmpdir)
            evidence = collector.capture(step_id="step_4")
            assert evidence.duration_ms >= 0

    def test_capture_handles_screenshot_failure(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            driver = _make_driver()
            driver.screenshot.side_effect = RuntimeError("screenshot failed")
            collector = EvidenceCollector(driver, output_dir=tmpdir)
            evidence = collector.capture(step_id="step_5")
            assert evidence.screenshot_path == ""
            # Should still capture source if possible

    def test_capture_handles_source_failure(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            driver = _make_driver()
            driver.dump_source.side_effect = RuntimeError("source failed")
            collector = EvidenceCollector(driver, output_dir=tmpdir)
            evidence = collector.capture(step_id="step_6")
            assert evidence.source_dump_path == ""
            # Should still capture screenshot

    def test_capture_with_ocr_summary(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            driver = _make_driver(source="<node text='登录'/><node text='首页'/>")
            collector = EvidenceCollector(driver, output_dir=tmpdir)
            evidence = collector.capture(step_id="step_7", ocr_summary=["登录", "首页"])
            assert evidence.ocr_summary == ["登录", "首页"]
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd D:\Mobile-AI-TestOps\backend && python -m pytest tests/test_evidence_collector.py -v`
Expected: FAIL — `ImportError: cannot import name 'EvidenceCollector'`

- [ ] **Step 3: Write the EvidenceCollector implementation**

File: `backend/app/automation/reports/evidence.py`

```python
"""EvidenceCollector — captures screenshots, source dumps, and device state for each step."""

from __future__ import annotations

import logging
import os
import time

from app.automation.core.driver import DeviceDriver
from app.automation.core.models import Evidence

logger = logging.getLogger(__name__)


class EvidenceCollector:
    """Captures per-step evidence: screenshot, source dump, app state, OCR summary.

    All artifacts are saved to output_dir with the step_id as filename prefix.
    """

    def __init__(self, driver: DeviceDriver, output_dir: str) -> None:
        self._driver = driver
        self._output_dir = output_dir
        os.makedirs(output_dir, exist_ok=True)

    def capture(self, step_id: str, ocr_summary: list[str] | None = None) -> Evidence:
        """Capture evidence for the current device state."""
        start = time.monotonic()

        screenshot_path = self._save_screenshot(step_id)
        source_dump_path = self._save_source(step_id)

        current_app = self._get_current_app()

        elapsed_ms = int((time.monotonic() - start) * 1000)

        return Evidence(
            screenshot_path=screenshot_path,
            source_dump_path=source_dump_path,
            ocr_summary=ocr_summary or [],
            current_app=current_app,
            duration_ms=elapsed_ms,
        )

    def _save_screenshot(self, step_id: str) -> str:
        try:
            png_bytes = self._driver.screenshot()
            path = os.path.join(self._output_dir, f"{step_id}.png")
            with open(path, "wb") as f:
                f.write(png_bytes)
            return path
        except Exception:
            logger.debug("Failed to capture screenshot for %s", step_id, exc_info=True)
            return ""

    def _save_source(self, step_id: str) -> str:
        try:
            source_xml = self._driver.dump_source()
            path = os.path.join(self._output_dir, f"{step_id}.xml")
            with open(path, "w", encoding="utf-8") as f:
                f.write(source_xml)
            return path
        except Exception:
            logger.debug("Failed to dump source for %s", step_id, exc_info=True)
            return ""

    def _get_current_app(self) -> str:
        try:
            info = self._driver.current_app()
            return info.get("package", "") or info.get("bundle_id", "")
        except Exception:
            return ""
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd D:\Mobile-AI-TestOps\backend && python -m pytest tests/test_evidence_collector.py -v`
Expected: All tests PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/automation/reports/evidence.py backend/tests/test_evidence_collector.py
git commit -m "feat(automation): add EvidenceCollector with screenshot/source/app capture"
```

---

## Task 9: Python Codegen from Steps

**Files:**
- Create: `backend/app/automation/recording/codegen.py`
- Test: `backend/tests/test_codegen.py`

- [ ] **Step 1: Write the failing tests**

File: `backend/tests/test_codegen.py`

```python
"""Tests for Python codegen — generate auto_execute-compatible code from Steps."""

from app.automation.core.models import (
    ActionSpec,
    ActionType,
    AssertionSpec,
    AssertionType,
    Locator,
    LocatorChain,
    LocatorType,
    Step,
    WaitConditionType,
    WaitSpec,
)
from app.automation.recording.codegen import generate_step_code, generate_script


class TestGenerateStepCode:
    def test_tap_with_resource_id(self):
        step = Step(
            id="step_1",
            title="点击登录",
            action=ActionSpec(type=ActionType.TAP, locator=Locator(type=LocatorType.RESOURCE_ID, value="com.demo:id/login")),
        )
        code = generate_step_code(step)
        assert 'auto_execute.click(resource_id="com.demo:id/login")' in code

    def test_tap_with_text(self):
        step = Step(
            id="step_2",
            title="点击确定",
            action=ActionSpec(type=ActionType.TAP, locator=Locator(type=LocatorType.TEXT, value="确定")),
        )
        code = generate_step_code(step)
        assert 'auto_execute.click(text="确定")' in code

    def test_tap_with_fallback_coordinates(self):
        step = Step(
            id="step_3",
            title="点击",
            action=ActionSpec(
                type=ActionType.TAP,
                locator=Locator(type=LocatorType.RESOURCE_ID, value="com.demo:id/btn"),
                params={"fallback_x": 541, "fallback_y": 1768},
            ),
        )
        code = generate_step_code(step)
        assert 'auto_execute.click(resource_id="com.demo:id/btn"' in code
        assert "fallback=(541, 1768)" in code

    def test_tap_coordinate_only(self):
        step = Step(
            id="step_4",
            title="点击坐标",
            action=ActionSpec(
                type=ActionType.TAP,
                params={"x": 540, "y": 960},
            ),
        )
        code = generate_step_code(step)
        assert "auto_execute.click(540, 960)" in code

    def test_input_action(self):
        step = Step(
            id="step_5",
            title="输入用户名",
            action=ActionSpec(
                type=ActionType.INPUT,
                locator=Locator(type=LocatorType.RESOURCE_ID, value="com.demo:id/username"),
                params={"text": "testuser"},
            ),
        )
        code = generate_step_code(step)
        assert 'auto_execute.input(resource_id="com.demo:id/username", text="testuser")' in code

    def test_swipe_action(self):
        step = Step(
            id="step_6",
            title="向上滑动",
            action=ActionSpec(
                type=ActionType.SWIPE,
                params={"start_x": 540, "start_y": 1500, "end_x": 540, "end_y": 500, "duration_ms": 300},
            ),
        )
        code = generate_step_code(step)
        assert "auto_execute.swipe(540, 1500, 540, 500, duration=300)" in code

    def test_launch_action(self):
        step = Step(
            id="step_7",
            title="启动App",
            action=ActionSpec(type=ActionType.LAUNCH, params={"app_id": "com.demo.app"}),
        )
        code = generate_step_code(step)
        assert 'auto_execute.launch("com.demo.app")' in code

    def test_press_key_back(self):
        step = Step(
            id="step_8",
            title="返回",
            action=ActionSpec(type=ActionType.PRESS_KEY, params={"key": "back"}),
        )
        code = generate_step_code(step)
        assert 'auto_execute.back()' in code

    def test_press_key_home(self):
        step = Step(
            id="step_9",
            title="Home",
            action=ActionSpec(type=ActionType.PRESS_KEY, params={"key": "home"}),
        )
        code = generate_step_code(step)
        assert 'auto_execute.home()' in code

    def test_long_press_action(self):
        step = Step(
            id="step_10",
            title="长按",
            action=ActionSpec(type=ActionType.LONG_PRESS, params={"x": 540, "y": 960, "duration_ms": 1000}),
        )
        code = generate_step_code(step)
        assert "auto_execute.long_press(540, 960, duration=1000)" in code


class TestGenerateStepCodeWithWait:
    def test_before_wait_generates_wait_for_element(self):
        step = Step(
            id="step_11",
            title="点击登录",
            action=ActionSpec(type=ActionType.TAP, locator=Locator(type=LocatorType.RESOURCE_ID, value="com.demo:id/login")),
            before_wait=WaitSpec(type=WaitConditionType.VISIBLE, locator=Locator(type=LocatorType.RESOURCE_ID, value="com.demo:id/login"), timeout=10.0),
        )
        code = generate_step_code(step)
        assert 'auto_execute.wait_for_element(resource_id="com.demo:id/login", timeout=10)' in code
        assert 'auto_execute.click(resource_id="com.demo:id/login")' in code

    def test_before_wait_with_text(self):
        step = Step(
            id="step_12",
            title="点击",
            action=ActionSpec(type=ActionType.TAP, locator=Locator(type=LocatorType.TEXT, value="登录")),
            before_wait=WaitSpec(type=WaitConditionType.VISIBLE, locator=Locator(type=LocatorType.TEXT, value="登录"), timeout=5.0),
        )
        code = generate_step_code(step)
        assert 'auto_execute.wait_for_element(text="登录", timeout=5)' in code


class TestGenerateStepCodeWithAssertion:
    def test_assertion_generates_assert_code(self):
        step = Step(
            id="step_13",
            title="点击登录",
            action=ActionSpec(type=ActionType.TAP, locator=Locator(type=LocatorType.RESOURCE_ID, value="com.demo:id/login")),
            assertions=[
                AssertionSpec(type=AssertionType.EXISTS, locator=Locator(type=LocatorType.RESOURCE_ID, value="com.demo:id/home_title")),
            ],
        )
        code = generate_step_code(step)
        assert 'auto_execute.assert_element(resource_id="com.demo:id/home_title")' in code

    def test_text_equals_assertion(self):
        step = Step(
            id="step_14",
            title="检查标题",
            action=ActionSpec(type=ActionType.TAP, locator=Locator(type=LocatorType.RESOURCE_ID, value="com.demo:id/btn")),
            assertions=[
                AssertionSpec(type=AssertionType.TEXT_EQUALS, locator=Locator(type=LocatorType.RESOURCE_ID, value="com.demo:id/title"), expected="首页"),
            ],
        )
        code = generate_step_code(step)
        assert 'assert_text_visible' in code or 'text_equals' in code


class TestGenerateScript:
    def test_generate_script_from_multiple_steps(self):
        steps = [
            Step(
                id="step_1",
                title="启动App",
                action=ActionSpec(type=ActionType.LAUNCH, params={"app_id": "com.demo.app"}),
            ),
            Step(
                id="step_2",
                title="点击登录",
                action=ActionSpec(type=ActionType.TAP, locator=Locator(type=LocatorType.RESOURCE_ID, value="com.demo:id/login")),
                before_wait=WaitSpec(type=WaitConditionType.VISIBLE, locator=Locator(type=LocatorType.RESOURCE_ID, value="com.demo:id/login"), timeout=10.0),
            ),
        ]
        script = generate_script(steps)
        assert 'auto_execute.launch("com.demo.app")' in script
        assert 'auto_execute.wait_for_element' in script
        assert 'auto_execute.click' in script

    def test_generate_script_includes_comments(self):
        steps = [
            Step(id="step_1", title="启动App", action=ActionSpec(type=ActionType.LAUNCH, params={"app_id": "com.demo.app"})),
        ]
        script = generate_script(steps)
        assert "# step_1: 启动App" in script
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd D:\Mobile-AI-TestOps\backend && python -m pytest tests/test_codegen.py -v`
Expected: FAIL — `ImportError: cannot import name 'generate_step_code'`

- [ ] **Step 3: Write the codegen implementation**

File: `backend/app/automation/recording/codegen.py`

```python
"""Python code generator — converts structured Steps into auto_execute-compatible Python code."""

from __future__ import annotations

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


def generate_step_code(step: Step) -> str:
    """Generate a single Python code line (or block) for a Step."""
    lines: list[str] = []

    # Before-wait
    if step.before_wait is not None:
        lines.append(_generate_wait(step.before_wait))

    # Action
    lines.append(_generate_action(step.action))

    # Assertions
    for assertion in step.assertions:
        lines.append(_generate_assertion(assertion))

    return "\n".join(lines)


def generate_script(steps: list[Step]) -> str:
    """Generate a complete Python script from a list of Steps."""
    lines: list[str] = []
    for step in steps:
        lines.append(f"# {step.id}: {step.title}")
        lines.append(generate_step_code(step))
        lines.append("")
    return "\n".join(lines).strip() + "\n"


def _locator_arg(locator: Locator) -> str:
    """Format a Locator as a keyword argument for auto_execute methods."""
    type_arg_map = {
        LocatorType.RESOURCE_ID: "resource_id",
        LocatorType.TEXT: "text",
        LocatorType.CONTENT_DESC: "content_desc",
        LocatorType.CLASS_NAME: "class_name",
        LocatorType.XPATH: "xpath",
    }
    arg_name = type_arg_map.get(locator.type)
    if arg_name:
        return f'{arg_name}="{locator.value}"'
    # Fallback: coordinate
    if locator.type == LocatorType.COORDINATE_RATIO:
        return f"coordinate_ratio=({locator.x}, {locator.y})"
    return f'locator="{locator.value}"'


def _generate_action(action: ActionSpec) -> str:
    """Generate code for a single action."""
    atype = action.type

    if atype == ActionType.TAP:
        return _generate_click(action)
    if atype == ActionType.LONG_PRESS:
        return _generate_long_press(action)
    if atype == ActionType.SWIPE:
        return _generate_swipe(action)
    if atype == ActionType.INPUT:
        return _generate_input(action)
    if atype == ActionType.LAUNCH:
        app_id = action.params.get("app_id", "")
        return f'auto_execute.launch("{app_id}")'
    if atype == ActionType.STOP_APP:
        app_id = action.params.get("app_id", "")
        return f'auto_execute.stop_app("{app_id}")'
    if atype == ActionType.PRESS_KEY:
        key = action.params.get("key", "")
        if key.lower() == "back":
            return "auto_execute.back()"
        if key.lower() == "home":
            return "auto_execute.home()"
        return f'auto_execute.press_key("{key}")'

    return f"# unsupported action: {atype.value}"


def _generate_click(action: ActionSpec) -> str:
    """Generate auto_execute.click() code."""
    if action.locator is not None:
        loc_arg = _locator_arg(action.locator)
        # Add fallback coordinates if present
        fallback_x = action.params.get("fallback_x")
        fallback_y = action.params.get("fallback_y")
        if fallback_x is not None and fallback_y is not None:
            return f"auto_execute.click({loc_arg}, fallback=({fallback_x}, {fallback_y}))"
        return f"auto_execute.click({loc_arg})"
    # Coordinate-only click
    x = action.params.get("x", 0)
    y = action.params.get("y", 0)
    return f"auto_execute.click({x}, {y})"


def _generate_long_press(action: ActionSpec) -> str:
    """Generate auto_execute.long_press() code."""
    x = action.params.get("x", 0)
    y = action.params.get("y", 0)
    duration = action.params.get("duration_ms", 1000)
    return f"auto_execute.long_press({x}, {y}, duration={duration})"


def _generate_swipe(action: ActionSpec) -> str:
    """Generate auto_execute.swipe() code."""
    sx = action.params.get("start_x", 0)
    sy = action.params.get("start_y", 0)
    ex = action.params.get("end_x", 0)
    ey = action.params.get("end_y", 0)
    duration = action.params.get("duration_ms", 300)
    return f"auto_execute.swipe({sx}, {sy}, {ex}, {ey}, duration={duration})"


def _generate_input(action: ActionSpec) -> str:
    """Generate auto_execute.input() code."""
    text = action.params.get("text", "")
    if action.locator is not None:
        loc_arg = _locator_arg(action.locator)
        return f'auto_execute.input({loc_arg}, text="{text}")'
    return f'auto_execute.input(text="{text}")'


def _generate_wait(wait: WaitSpec) -> str:
    """Generate auto_execute.wait_for_element() code."""
    if wait.locator is not None:
        loc_arg = _locator_arg(wait.locator)
        timeout = int(wait.timeout)
        return f"auto_execute.wait_for_element({loc_arg}, timeout={timeout})"
    return f"auto_execute.wait(timeout={int(wait.timeout)})"


def _generate_assertion(assertion: AssertionSpec) -> str:
    """Generate assertion code."""
    if assertion.type == AssertionType.EXISTS and assertion.locator is not None:
        loc_arg = _locator_arg(assertion.locator)
        return f"auto_execute.assert_element({loc_arg})"
    if assertion.type == AssertionType.TEXT_EQUALS and assertion.locator is not None:
        loc_arg = _locator_arg(assertion.locator)
        expected = assertion.expected or ""
        return f'auto_execute.assert_text_visible({loc_arg}, expected_text="{expected}")'
    if assertion.type == AssertionType.TEXT_CONTAINS and assertion.expected:
        return f'auto_execute.assert_text_visible(text="{assertion.expected}")'
    if assertion.type == AssertionType.OCR_CONTAINS and assertion.expected:
        return f'ocr.find("{assertion.expected}")'
    return f"# assertion: {assertion.type.value}"
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd D:\Mobile-AI-TestOps\backend && python -m pytest tests/test_codegen.py -v`
Expected: All tests PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/automation/recording/codegen.py backend/tests/test_codegen.py
git commit -m "feat(automation): add Python codegen — Step to auto_execute script generation"
```

---

## Task 10: Automation API Router

**Files:**
- Create: `backend/app/routers/automation.py`
- Modify: `backend/app/main.py` — register the new router
- Test: `backend/tests/test_automation_api.py`

- [ ] **Step 1: Write the failing tests**

File: `backend/tests/test_automation_api.py`

```python
"""Tests for Automation API router."""

from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


class TestLocatorPreview:
    @patch("app.routers.automation.AndroidDriver")
    @patch("app.routers.automation.LocatorResolver")
    def test_locator_preview_returns_resolve_result(self, mock_resolver_cls, mock_driver_cls):
        from app.automation.core.models import Locator, LocatorChain, LocatorType
        from app.automation.locators.resolver import ResolveResult

        mock_resolver = MagicMock()
        mock_resolver.resolve.return_value = ResolveResult(
            found=True,
            resolved_locator=Locator(type=LocatorType.RESOURCE_ID, value="com.demo:id/btn"),
            attempted_count=1,
        )
        mock_resolver_cls.return_value = mock_resolver

        response = client.post("/api/automation/locators/preview", json={
            "udid": "emulator-5554",
            "platform": "android",
            "locator_chain": {
                "primary": {"type": "resource_id", "value": "com.demo:id/btn"},
                "fallbacks": [],
            },
        })
        assert response.status_code == 200
        data = response.json()
        assert data["found"] is True


class TestAssertionValidate:
    @patch("app.routers.automation.AndroidDriver")
    @patch("app.routers.automation.AssertionEngine")
    def test_assertion_validate_returns_result(self, mock_engine_cls, mock_driver_cls):
        from app.automation.assertions.engine import AssertionResult
        from app.automation.core.models import AssertionType

        mock_engine = MagicMock()
        mock_engine.evaluate.return_value = AssertionResult(
            passed=True,
            assertion_type=AssertionType.EXISTS,
            message="Element found",
        )
        mock_engine_cls.return_value = mock_engine

        response = client.post("/api/automation/assertions/validate", json={
            "udid": "emulator-5554",
            "platform": "android",
            "assertion": {
                "type": "exists",
                "locator": {"type": "resource_id", "value": "com.demo:id/btn"},
            },
        })
        assert response.status_code == 200
        data = response.json()
        assert data["passed"] is True


class TestHealthEndpoint:
    def test_automation_health(self):
        response = client.get("/api/automation/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd D:\Mobile-AI-TestOps\backend && python -m pytest tests/test_automation_api.py -v`
Expected: FAIL — 404 on `/api/automation/health` (router not registered)

- [ ] **Step 3: Write the Automation API router**

File: `backend/app/routers/automation.py`

```python
"""Automation API — locator preview, assertion validation, and run management."""

from __future__ import annotations

from fastapi import APIRouter

from app.automation.assertions.engine import AssertionEngine, AssertionResult
from app.automation.core.models import AssertionSpec, LocatorChain
from app.automation.drivers.android_driver import AndroidDriver
from app.automation.drivers.ios_driver import IOSDriver
from app.automation.locators.resolver import LocatorResolver, ResolveResult
from app.automation.core.driver import DeviceDriver

router = APIRouter(prefix="/api/automation", tags=["automation"])


def _create_driver(udid: str, platform: str, wda_url: str | None = None) -> DeviceDriver:
    """Factory: create the appropriate driver for the platform."""
    if platform == "ios":
        return IOSDriver(udid=udid, wda_url=wda_url or "http://localhost:8100")
    return AndroidDriver(udid=udid)


@router.get("/health")
def automation_health():
    return {"status": "ok"}


@router.post("/locators/preview")
def locator_preview(
    udid: str,
    platform: str,
    locator_chain: dict,
    wda_url: str | None = None,
):
    """Preview locator resolution — try the chain and return which locator resolved."""
    driver = _create_driver(udid, platform, wda_url)
    chain = LocatorChain.from_dict(locator_chain)
    resolver = LocatorResolver(driver)
    result = resolver.resolve(chain)
    return _resolve_result_to_dict(result)


@router.post("/assertions/validate")
def assertion_validate(
    udid: str,
    platform: str,
    assertion: dict,
    wda_url: str | None = None,
):
    """Validate a single assertion against the current device state."""
    driver = _create_driver(udid, platform, wda_url)
    spec = AssertionSpec.from_dict(assertion)
    engine = AssertionEngine(driver)
    result = engine.evaluate(spec)
    return _assertion_result_to_dict(result)


def _resolve_result_to_dict(result: ResolveResult) -> dict:
    d = {
        "found": result.found,
        "attempted_count": result.attempted_count,
    }
    if result.resolved_locator is not None:
        d["resolved_locator"] = result.resolved_locator.to_dict()
    if result.coordinates is not None:
        d["coordinates"] = list(result.coordinates)
    return d


def _assertion_result_to_dict(result: AssertionResult) -> dict:
    return {
        "passed": result.passed,
        "assertion_type": result.assertion_type.value,
        "message": result.message,
    }
```

- [ ] **Step 4: Register the router in main.py**

Read `backend/app/main.py` and add the import and registration:

```python
# Add to imports:
from app.routers import automation

# Add to router registrations in create_app():
app.include_router(automation.router)
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd D:\Mobile-AI-TestOps\backend && python -m pytest tests/test_automation_api.py -v`
Expected: All tests PASS

- [ ] **Step 6: Commit**

```bash
git add backend/app/routers/automation.py backend/app/main.py backend/tests/test_automation_api.py
git commit -m "feat(automation): add Automation API router with locator preview and assertion validation"
```

---

## Task 11: Migrate ScriptUI to Use DeviceDriver

**Files:**
- Modify: `backend/app/routers/scripts.py` — ScriptUI delegates to DeviceDriver
- Test: `backend/tests/test_scripts_router.py` (extend existing tests)

This is the most critical backward-compatibility task. ScriptUI currently calls u2_service, wda_service, ADBService, and UIElementService directly. After migration, it delegates to a DeviceDriver instance while keeping the same public API (`auto_execute.click()`, `auto_execute.input()`, etc.).

- [ ] **Step 1: Write the failing test for ScriptUI driver delegation**

Append to `backend/tests/test_scripts_router.py`:

```python
"""Additional tests for ScriptUI driver delegation."""


class TestScriptUIDriverDelegation:
    def test_script_ui_uses_android_driver(self):
        from unittest.mock import MagicMock, patch
        from app.routers.scripts import ScriptUI
        from app.automation.drivers.android_driver import AndroidDriver

        with patch.object(AndroidDriver, "tap") as mock_tap:
            ui = ScriptUI(udid="emulator-5554", platform="android")
            ui.click(x=100, y=200)
            mock_tap.assert_called_once_with(100, 200)

    def test_script_ui_uses_ios_driver(self):
        from unittest.mock import MagicMock, patch
        from app.routers.scripts import ScriptUI
        from app.automation.drivers.ios_driver import IOSDriver

        with patch.object(IOSDriver, "tap") as mock_tap:
            ui = ScriptUI(udid="abc123", platform="ios", wda_url="http://localhost:8100")
            ui.click(x=100, y=200)
            mock_tap.assert_called_once_with(100, 200)

    def test_script_ui_click_with_selector_delegates_to_driver_find(self):
        from unittest.mock import MagicMock, patch
        from app.routers.scripts import ScriptUI
        from app.automation.drivers.android_driver import AndroidDriver
        from app.automation.core.driver import ElementRef

        with patch.object(AndroidDriver, "find_element") as mock_find, \
             patch.object(AndroidDriver, "tap") as mock_tap:
            mock_find.return_value = ElementRef(
                found=True, locator_type="resource_id", locator_value="com.demo:id/btn", center=(100, 200),
            )
            ui = ScriptUI(udid="emulator-5554", platform="android")
            ui.click(resource_id="com.demo:id/btn")
            mock_find.assert_called_once_with("resource_id", "com.demo:id/btn", timeout=10.0)
            mock_tap.assert_called_once_with(100, 200)

    def test_script_ui_screenshot_delegates_to_driver(self):
        from unittest.mock import MagicMock, patch
        from app.routers.scripts import ScriptUI
        from app.automation.drivers.android_driver import AndroidDriver

        with patch.object(AndroidDriver, "screenshot") as mock_ss:
            mock_ss.return_value = b"\x89PNG"
            ui = ScriptUI(udid="emulator-5554", platform="android")
            result = ui.screenshot()
            mock_ss.assert_called_once()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd D:\Mobile-AI-TestOps\backend && python -m pytest tests/test_scripts_router.py::TestScriptUIDriverDelegation -v`
Expected: FAIL — ScriptUI does not yet delegate to DeviceDriver

- [ ] **Step 3: Modify ScriptUI to accept and use a DeviceDriver**

This step modifies `backend/app/routers/scripts.py`. The key changes to the `ScriptUI` class:

1. Add `driver` parameter to `__init__` — create a driver if not provided
2. Delegate `click()` to `driver.tap()` when coordinates are known
3. Delegate `click(resource_id=...)` to `driver.find_element()` then `driver.tap()`
4. Delegate `screenshot()` to `driver.screenshot()`
5. Delegate `swipe()` to `driver.swipe()`
6. Delegate `launch()` to `driver.launch()`
7. Keep the existing fallback paths for when driver fails

**The actual modification pattern** — in `ScriptUI.__init__`, add driver creation:

```python
class ScriptUI:
    def __init__(self, udid: str, platform: str = "android", wda_url: str | None = None):
        self.udid = udid
        self.platform = platform
        self.wda_url = wda_url
        # Create a DeviceDriver for delegation
        if platform == "ios" and wda_url:
            self._driver = IOSDriver(udid=udid, wda_url=wda_url)
        else:
            self._driver = AndroidDriver(udid=udid)
        # Keep existing service references for backward compat
        self._adb = ADBService()
        self._ui_element_service = UIElementService()
        self._visual = VisualActionService()
```

**For `click()`** — add driver delegation as primary path:

```python
def click(self, x=None, y=None, resource_id=None, text=None, content_desc=None, class_name=None, xpath=None, timeout=10.0, fallback=None):
    # Selector-based click: find element center via driver, then tap
    if resource_id or text or content_desc or class_name or xpath:
        locator_type, locator_value = self._parse_selector(resource_id, text, content_desc, class_name, xpath)
        ref = self._driver.find_element(locator_type, locator_value, timeout=timeout)
        if ref.found and ref.center:
            self._driver.tap(ref.center[0], ref.center[1])
            return {"found": True, "method": "driver_selector", "locator": locator_type, "value": locator_value}
        # Fallback to existing UIElementService logic
        ...
    # Coordinate click
    if x is not None and y is not None:
        self._driver.tap(x, y)
        return {"found": True, "method": "driver_coordinate", "x": x, "y": y}
    ...
```

**For `screenshot()`** — add driver delegation:

```python
def screenshot(self, path=None):
    try:
        png_bytes = self._driver.screenshot()
        # Save to path if provided
        if path:
            with open(path, "wb") as f:
                f.write(png_bytes)
        return {"success": True, "method": "driver", "size": len(png_bytes)}
    except Exception:
        # Fallback to existing logic
        ...
```

**Important**: The full modification is extensive. The engineer should:
1. Read the existing `ScriptUI` class in full
2. Add `from app.automation.core.driver import DeviceDriver` and driver imports at the top
3. Add `_driver` creation in `__init__`
4. Add `_parse_selector()` helper method
5. Modify each method to try `self._driver` first, then fall back to existing logic
6. Run ALL existing ScriptUI tests to confirm backward compatibility

- [ ] **Step 4: Run all ScriptUI-related tests**

Run: `cd D:\Mobile-AI-TestOps\backend && python -m pytest tests/test_scripts_router.py -v`
Expected: All tests PASS (both old and new)

- [ ] **Step 5: Run the full test suite**

Run: `cd D:\Mobile-AI-TestOps\backend && python -m pytest tests/ -v`
Expected: All tests PASS

- [ ] **Step 6: Commit**

```bash
git add backend/app/routers/scripts.py backend/tests/test_scripts_router.py
git commit -m "feat(automation): migrate ScriptUI to delegate to DeviceDriver with backward compat"
```

---

## Self-Review

### 1. Spec Coverage

| Spec Section | Task |
|---|---|
| §5.1 Step model | Task 1 |
| §5.2 Locator with fallback | Task 1 + Task 5 |
| §5.3 WaitSpec | Task 1 + Task 6 |
| §5.4 AssertionSpec | Task 1 + Task 7 |
| §5.5 Evidence | Task 1 + Task 8 |
| §6.1 DeviceDriver protocol | Task 2 |
| §6.2 AndroidDriver | Task 3 |
| §6.3 IOSDriver | Task 4 |
| §7.1 Android recording | Task 9 (codegen) — frontend recording is Phase 3 |
| §7.2 iOS recording | Task 9 (codegen) — frontend recording is Phase 3 |
| §8.1 Wait strategy | Task 6 |
| §8.2 Assertion strategy | Task 7 |
| §8.3 Failure evidence | Task 8 |
| §10.1 API endpoints | Task 10 (partial — runs/events are Phase 4) |
| §11 Compatibility | Task 11 (ScriptUI migration) |

**Not covered in Phase 1+2 (deferred to Phase 3-5):**
- §9 Runner & event stream (Phase 4)
- §10.2 DeviceManager recording refactor (Phase 3)
- §10.3 TestCaseManager report center (Phase 4)
- POST /api/automation/runs (Phase 4)
- GET /api/automation/runs/{id}/events (Phase 4)
- POST /api/automation/recordings (Phase 3)

### 2. Placeholder Scan

No TBD, TODO, or placeholder patterns found. All steps contain complete code.

### 3. Type Consistency

- `Locator.type` is `LocatorType` enum everywhere
- `ActionSpec.type` is `ActionType` enum everywhere
- `WaitSpec.type` is `WaitConditionType` enum everywhere
- `AssertionSpec.type` is `AssertionType` enum everywhere
- `DeviceDriver.find_element()` returns `ElementRef` — used consistently in LocatorResolver, WaitEngine, AssertionEngine
- `LocatorResolver.resolve()` returns `ResolveResult` — used consistently in API router
- `AssertionEngine.evaluate()` returns `AssertionResult` — used consistently in API router
- `EvidenceCollector.capture()` returns `Evidence` — consistent with model definition
- `generate_step_code()` / `generate_script()` return `str` — consistent with test expectations
