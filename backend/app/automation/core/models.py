"""Core data models for the Unified Automation Engine V2."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


# ---------------------------------------------------------------------------
# Locator
# ---------------------------------------------------------------------------


class LocatorType(str, Enum):
    """Supported locator strategies."""

    RESOURCE_ID = "resource_id"
    TEXT = "text"
    CONTENT_DESC = "content_desc"
    CLASS_NAME = "class_name"
    XPATH = "xpath"
    OCR_TEXT = "ocr_text"
    COORDINATE_RATIO = "coordinate_ratio"


@dataclass(frozen=True)
class Locator:
    """A single element locator."""

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
    """Primary locator with ordered fallbacks."""

    primary: Locator
    fallbacks: list[Locator] = field(default_factory=list)

    def all_locators(self) -> list[Locator]:
        return [self.primary, *self.fallbacks]

    def to_dict(self) -> dict[str, Any]:
        return {
            "primary": self.primary.to_dict(),
            "fallbacks": [fb.to_dict() for fb in self.fallbacks],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> LocatorChain:
        return cls(
            primary=Locator.from_dict(data["primary"]),
            fallbacks=[Locator.from_dict(fb) for fb in data.get("fallbacks", [])],
        )


# ---------------------------------------------------------------------------
# Action
# ---------------------------------------------------------------------------


class ActionType(str, Enum):
    """Supported action types."""

    TAP = "tap"
    LONG_PRESS = "long_press"
    SWIPE = "swipe"
    INPUT = "input"
    PRESS_KEY = "press_key"
    LAUNCH = "launch"
    STOP_APP = "stop_app"


@dataclass(frozen=True)
class ActionSpec:
    """Specification for a single action."""

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
        locator_data = data.get("locator")
        return cls(
            type=ActionType(data["type"]),
            locator=Locator.from_dict(locator_data) if locator_data else None,
            params=data.get("params", {}),
        )


# ---------------------------------------------------------------------------
# Wait
# ---------------------------------------------------------------------------


class WaitConditionType(str, Enum):
    """Supported wait condition types."""

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


@dataclass(frozen=True)
class WaitSpec:
    """Specification for a wait condition."""

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
        locator_data = data.get("locator")
        return cls(
            type=WaitConditionType(data["type"]),
            timeout=data.get("timeout", 10.0),
            locator=Locator.from_dict(locator_data) if locator_data else None,
            text=data.get("text"),
            poll_interval=data.get("poll_interval", 0.5),
        )


# ---------------------------------------------------------------------------
# Assertion
# ---------------------------------------------------------------------------


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
class AssertionSpec:
    """Specification for a single assertion."""

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
        locator_data = data.get("locator")
        return cls(
            type=AssertionType(data["type"]),
            locator=Locator.from_dict(locator_data) if locator_data else None,
            expected=data.get("expected"),
            image_path=data.get("image_path"),
        )


# ---------------------------------------------------------------------------
# Evidence
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Evidence:
    """Collected evidence for a step execution."""

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


# ---------------------------------------------------------------------------
# Step
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Step:
    """A single automation step combining action, waits, and assertions."""

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
        before_wait_data = data.get("before_wait")
        after_wait_data = data.get("after_wait")
        return cls(
            id=data["id"],
            title=data["title"],
            action=ActionSpec.from_dict(data["action"]),
            before_wait=WaitSpec.from_dict(before_wait_data) if before_wait_data else None,
            after_wait=WaitSpec.from_dict(after_wait_data) if after_wait_data else None,
            assertions=[AssertionSpec.from_dict(a) for a in data.get("assertions", [])],
        )
