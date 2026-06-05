"""Tests for automation core data models."""

from __future__ import annotations

import pytest

from app.automation.core.models import (
    ActionType,
    ActionSpec,
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


# ---------------------------------------------------------------------------
# LocatorType
# ---------------------------------------------------------------------------


class TestLocatorType:
    def test_all_variants(self):
        expected = {
            "resource_id": LocatorType.RESOURCE_ID,
            "text": LocatorType.TEXT,
            "content_desc": LocatorType.CONTENT_DESC,
            "class_name": LocatorType.CLASS_NAME,
            "xpath": LocatorType.XPATH,
            "ocr_text": LocatorType.OCR_TEXT,
            "coordinate_ratio": LocatorType.COORDINATE_RATIO,
        }
        for value, member in expected.items():
            assert member.value == value

    def test_is_str_enum(self):
        assert isinstance(LocatorType.RESOURCE_ID, str)
        assert LocatorType.RESOURCE_ID == "resource_id"


# ---------------------------------------------------------------------------
# Locator
# ---------------------------------------------------------------------------


class TestLocator:
    def test_create_minimal(self):
        loc = Locator(type=LocatorType.RESOURCE_ID, value="com.app:id/btn")
        assert loc.type is LocatorType.RESOURCE_ID
        assert loc.value == "com.app:id/btn"
        assert loc.x is None
        assert loc.y is None

    def test_create_with_coordinates(self):
        loc = Locator(type=LocatorType.COORDINATE_RATIO, x=0.5, y=0.7)
        assert loc.x == 0.5
        assert loc.y == 0.7

    def test_frozen(self):
        loc = Locator(type=LocatorType.TEXT, value="Login")
        with pytest.raises(AttributeError):
            loc.value = "Changed"  # type: ignore[misc]

    def test_to_dict_minimal(self):
        loc = Locator(type=LocatorType.XPATH, value="//android.widget.Button")
        d = loc.to_dict()
        assert d == {"type": "xpath", "value": "//android.widget.Button"}

    def test_to_dict_with_coords(self):
        loc = Locator(type=LocatorType.COORDINATE_RATIO, value="tap", x=0.3, y=0.8)
        d = loc.to_dict()
        assert d["x"] == 0.3
        assert d["y"] == 0.8

    def test_to_dict_omits_none_coords(self):
        loc = Locator(type=LocatorType.RESOURCE_ID, value="id")
        d = loc.to_dict()
        assert "x" not in d
        assert "y" not in d

    def test_from_dict_roundtrip(self):
        original = Locator(type=LocatorType.OCR_TEXT, value="Submit", x=0.1, y=0.2)
        restored = Locator.from_dict(original.to_dict())
        assert restored == original

    def test_from_dict_missing_optional(self):
        data = {"type": "resource_id", "value": "id"}
        loc = Locator.from_dict(data)
        assert loc.type is LocatorType.RESOURCE_ID
        assert loc.x is None
        assert loc.y is None


# ---------------------------------------------------------------------------
# LocatorChain
# ---------------------------------------------------------------------------


class TestLocatorChain:
    def test_primary_only(self):
        primary = Locator(type=LocatorType.RESOURCE_ID, value="id")
        chain = LocatorChain(primary=primary)
        assert chain.primary is primary
        assert chain.fallbacks == []

    def test_with_fallbacks(self):
        primary = Locator(type=LocatorType.RESOURCE_ID, value="id")
        fb1 = Locator(type=LocatorType.TEXT, value="OK")
        fb2 = Locator(type=LocatorType.CONTENT_DESC, value="desc")
        chain = LocatorChain(primary=primary, fallbacks=[fb1, fb2])
        assert len(chain.fallbacks) == 2

    def test_all_locators(self):
        primary = Locator(type=LocatorType.RESOURCE_ID, value="id")
        fb1 = Locator(type=LocatorType.TEXT, value="OK")
        fb2 = Locator(type=LocatorType.CONTENT_DESC, value="desc")
        chain = LocatorChain(primary=primary, fallbacks=[fb1, fb2])
        all_locs = chain.all_locators()
        assert all_locs == [primary, fb1, fb2]

    def test_all_locators_no_fallbacks(self):
        primary = Locator(type=LocatorType.XPATH, value="//node")
        chain = LocatorChain(primary=primary)
        assert chain.all_locators() == [primary]

    def test_to_dict(self):
        primary = Locator(type=LocatorType.RESOURCE_ID, value="id")
        fb = Locator(type=LocatorType.TEXT, value="OK")
        chain = LocatorChain(primary=primary, fallbacks=[fb])
        d = chain.to_dict()
        assert d["primary"] == primary.to_dict()
        assert d["fallbacks"] == [fb.to_dict()]

    def test_from_dict_roundtrip(self):
        primary = Locator(type=LocatorType.RESOURCE_ID, value="id")
        fb = Locator(type=LocatorType.OCR_TEXT, value="hello")
        original = LocatorChain(primary=primary, fallbacks=[fb])
        restored = LocatorChain.from_dict(original.to_dict())
        assert restored.primary == original.primary
        assert restored.fallbacks == original.fallbacks


# ---------------------------------------------------------------------------
# ActionType
# ---------------------------------------------------------------------------


class TestActionType:
    def test_all_variants(self):
        expected_values = ["tap", "long_press", "swipe", "input", "press_key", "launch", "stop_app"]
        actual_values = [m.value for m in ActionType]
        assert sorted(actual_values) == sorted(expected_values)

    def test_is_str_enum(self):
        assert isinstance(ActionType.TAP, str)


# ---------------------------------------------------------------------------
# ActionSpec
# ---------------------------------------------------------------------------


class TestActionSpec:
    def test_tap(self):
        loc = Locator(type=LocatorType.RESOURCE_ID, value="btn")
        spec = ActionSpec(type=ActionType.TAP, locator=loc)
        assert spec.type is ActionType.TAP
        assert spec.locator is not None
        assert spec.params == {}

    def test_swipe(self):
        spec = ActionSpec(
            type=ActionType.SWIPE,
            params={"direction": "up", "distance": 0.5},
        )
        assert spec.params["direction"] == "up"
        assert spec.locator is None

    def test_input(self):
        loc = Locator(type=LocatorType.RESOURCE_ID, value="input_field")
        spec = ActionSpec(type=ActionType.INPUT, locator=loc, params={"text": "hello"})
        assert spec.params["text"] == "hello"

    def test_launch(self):
        spec = ActionSpec(type=ActionType.LAUNCH, params={"package": "com.app"})
        assert spec.locator is None
        assert spec.params["package"] == "com.app"

    def test_frozen(self):
        spec = ActionSpec(type=ActionType.TAP)
        with pytest.raises(AttributeError):
            spec.type = ActionType.INPUT  # type: ignore[misc]

    def test_to_dict_with_locator(self):
        loc = Locator(type=LocatorType.RESOURCE_ID, value="btn")
        spec = ActionSpec(type=ActionType.TAP, locator=loc)
        d = spec.to_dict()
        assert d["type"] == "tap"
        assert d["locator"] == loc.to_dict()
        assert "params" not in d  # empty params omitted

    def test_to_dict_with_params(self):
        spec = ActionSpec(type=ActionType.INPUT, params={"text": "hi"})
        d = spec.to_dict()
        assert d["params"] == {"text": "hi"}

    def test_from_dict_roundtrip(self):
        loc = Locator(type=LocatorType.XPATH, value="//input")
        original = ActionSpec(type=ActionType.INPUT, locator=loc, params={"text": "world"})
        restored = ActionSpec.from_dict(original.to_dict())
        assert restored.type == original.type
        assert restored.locator == original.locator
        assert restored.params == original.params

    def test_from_dict_no_locator(self):
        data = {"type": "launch", "params": {"package": "com.app"}}
        spec = ActionSpec.from_dict(data)
        assert spec.type is ActionType.LAUNCH
        assert spec.locator is None


# ---------------------------------------------------------------------------
# WaitConditionType
# ---------------------------------------------------------------------------


class TestWaitConditionType:
    def test_all_variants(self):
        expected = [
            "visible", "gone", "exists", "text_equals", "text_contains",
            "enabled", "screen_changed", "app_foreground", "source_stable",
            "ocr_contains",
        ]
        actual = [m.value for m in WaitConditionType]
        assert sorted(actual) == sorted(expected)


# ---------------------------------------------------------------------------
# WaitSpec
# ---------------------------------------------------------------------------


class TestWaitSpec:
    def test_visible(self):
        loc = Locator(type=LocatorType.RESOURCE_ID, value="btn")
        spec = WaitSpec(type=WaitConditionType.VISIBLE, locator=loc)
        assert spec.type is WaitConditionType.VISIBLE
        assert spec.locator is not None
        assert spec.timeout == 10.0

    def test_screen_changed(self):
        spec = WaitSpec(type=WaitConditionType.SCREEN_CHANGED, timeout=5.0)
        assert spec.locator is None

    def test_text_contains(self):
        spec = WaitSpec(type=WaitConditionType.TEXT_CONTAINS, text="Welcome")
        assert spec.text == "Welcome"

    def test_default_poll_interval(self):
        spec = WaitSpec(type=WaitConditionType.EXISTS)
        assert spec.poll_interval == 0.5

    def test_custom_poll_interval(self):
        spec = WaitSpec(type=WaitConditionType.EXISTS, poll_interval=1.0)
        assert spec.poll_interval == 1.0

    def test_to_dict_defaults(self):
        spec = WaitSpec(type=WaitConditionType.VISIBLE)
        d = spec.to_dict()
        assert d["type"] == "visible"
        assert d["timeout"] == 10.0
        # locator, text omitted when None; poll_interval omitted when default
        assert "locator" not in d
        assert "text" not in d
        assert "poll_interval" not in d

    def test_to_dict_with_all(self):
        loc = Locator(type=LocatorType.RESOURCE_ID, value="btn")
        spec = WaitSpec(
            type=WaitConditionType.TEXT_CONTAINS,
            timeout=20.0,
            locator=loc,
            text="hello",
            poll_interval=1.0,
        )
        d = spec.to_dict()
        assert d["type"] == "text_contains"
        assert d["timeout"] == 20.0
        assert d["locator"] == loc.to_dict()
        assert d["text"] == "hello"
        assert d["poll_interval"] == 1.0

    def test_from_dict_roundtrip(self):
        loc = Locator(type=LocatorType.XPATH, value="//node")
        original = WaitSpec(
            type=WaitConditionType.VISIBLE,
            timeout=15.0,
            locator=loc,
            poll_interval=0.8,
        )
        restored = WaitSpec.from_dict(original.to_dict())
        assert restored.type == original.type
        assert restored.timeout == original.timeout
        assert restored.locator == original.locator
        assert restored.poll_interval == original.poll_interval


# ---------------------------------------------------------------------------
# AssertionType
# ---------------------------------------------------------------------------


class TestAssertionType:
    def test_all_variants(self):
        expected = [
            "exists", "not_exists", "text_equals", "text_contains",
            "ocr_contains", "image_exists", "app_foreground", "ai_result",
        ]
        actual = [m.value for m in AssertionType]
        assert sorted(actual) == sorted(expected)


# ---------------------------------------------------------------------------
# AssertionSpec
# ---------------------------------------------------------------------------


class TestAssertionSpec:
    def test_exists(self):
        loc = Locator(type=LocatorType.RESOURCE_ID, value="btn")
        spec = AssertionSpec(type=AssertionType.EXISTS, locator=loc)
        assert spec.type is AssertionType.EXISTS
        assert spec.locator is not None

    def test_text_equals(self):
        loc = Locator(type=LocatorType.RESOURCE_ID, value="label")
        spec = AssertionSpec(type=AssertionType.TEXT_EQUALS, locator=loc, expected="Hello")
        assert spec.expected == "Hello"

    def test_ocr_contains(self):
        spec = AssertionSpec(type=AssertionType.OCR_CONTAINS, expected="Welcome")
        assert spec.locator is None
        assert spec.expected == "Welcome"

    def test_image_exists(self):
        spec = AssertionSpec(type=AssertionType.IMAGE_EXISTS, image_path="/tmp/icon.png")
        assert spec.image_path == "/tmp/icon.png"

    def test_to_dict_minimal(self):
        spec = AssertionSpec(type=AssertionType.EXISTS)
        d = spec.to_dict()
        assert d == {"type": "exists"}

    def test_to_dict_full(self):
        loc = Locator(type=LocatorType.RESOURCE_ID, value="el")
        spec = AssertionSpec(type=AssertionType.TEXT_EQUALS, locator=loc, expected="OK")
        d = spec.to_dict()
        assert d["type"] == "text_equals"
        assert d["locator"] == loc.to_dict()
        assert d["expected"] == "OK"

    def test_from_dict_roundtrip(self):
        loc = Locator(type=LocatorType.XPATH, value="//el")
        original = AssertionSpec(type=AssertionType.TEXT_CONTAINS, locator=loc, expected="abc")
        restored = AssertionSpec.from_dict(original.to_dict())
        assert restored.type == original.type
        assert restored.locator == original.locator
        assert restored.expected == original.expected


# ---------------------------------------------------------------------------
# Evidence
# ---------------------------------------------------------------------------


class TestEvidence:
    def test_create_defaults(self):
        ev = Evidence()
        assert ev.screenshot_path == ""
        assert ev.source_dump_path == ""
        assert ev.ocr_summary == []
        assert ev.current_app == ""
        assert ev.duration_ms == 0

    def test_create_with_values(self):
        ev = Evidence(
            screenshot_path="/shots/1.png",
            source_dump_path="/dumps/1.xml",
            ocr_summary=["Login", "Submit"],
            current_app="com.app",
            duration_ms=1500,
        )
        assert ev.screenshot_path == "/shots/1.png"
        assert ev.ocr_summary == ["Login", "Submit"]
        assert ev.duration_ms == 1500

    def test_to_dict(self):
        ev = Evidence(
            screenshot_path="/s.png",
            ocr_summary=["A", "B"],
            duration_ms=100,
        )
        d = ev.to_dict()
        assert d["screenshot_path"] == "/s.png"
        assert d["ocr_summary"] == ["A", "B"]
        assert d["duration_ms"] == 100

    def test_from_dict_roundtrip(self):
        original = Evidence(
            screenshot_path="/s.png",
            source_dump_path="/d.xml",
            ocr_summary=["X"],
            current_app="com.pkg",
            duration_ms=200,
        )
        restored = Evidence.from_dict(original.to_dict())
        assert restored == original


# ---------------------------------------------------------------------------
# Step
# ---------------------------------------------------------------------------


class TestStep:
    def _make_step(self, **overrides) -> Step:
        defaults = {
            "id": "step-1",
            "title": "Tap login",
            "action": ActionSpec(
                type=ActionType.TAP,
                locator=Locator(type=LocatorType.RESOURCE_ID, value="btn_login"),
            ),
        }
        defaults.update(overrides)
        return Step(**defaults)

    def test_minimal(self):
        step = self._make_step()
        assert step.id == "step-1"
        assert step.title == "Tap login"
        assert step.before_wait is None
        assert step.after_wait is None
        assert step.assertions == []

    def test_full(self):
        loc = Locator(type=LocatorType.RESOURCE_ID, value="btn_login")
        action = ActionSpec(type=ActionType.TAP, locator=loc)
        before = WaitSpec(type=WaitConditionType.VISIBLE, locator=loc)
        after = WaitSpec(type=WaitConditionType.SCREEN_CHANGED, timeout=3.0)
        assertion = AssertionSpec(type=AssertionType.EXISTS, locator=loc)
        step = Step(
            id="step-1",
            title="Tap login button",
            action=action,
            before_wait=before,
            after_wait=after,
            assertions=[assertion],
        )
        assert step.before_wait is not None
        assert step.after_wait is not None
        assert len(step.assertions) == 1

    def test_frozen(self):
        step = self._make_step()
        with pytest.raises(AttributeError):
            step.title = "Changed"  # type: ignore[misc]

    def test_to_dict_minimal(self):
        step = self._make_step()
        d = step.to_dict()
        assert d["id"] == "step-1"
        assert d["title"] == "Tap login"
        assert "action" in d
        assert "before_wait" not in d
        assert "after_wait" not in d
        assert "assertions" not in d

    def test_to_dict_full(self):
        loc = Locator(type=LocatorType.RESOURCE_ID, value="btn")
        step = Step(
            id="s1",
            title="Do thing",
            action=ActionSpec(type=ActionType.TAP, locator=loc),
            before_wait=WaitSpec(type=WaitConditionType.VISIBLE, locator=loc),
            after_wait=WaitSpec(type=WaitConditionType.SCREEN_CHANGED),
            assertions=[AssertionSpec(type=AssertionType.EXISTS, locator=loc)],
        )
        d = step.to_dict()
        assert "before_wait" in d
        assert "after_wait" in d
        assert len(d["assertions"]) == 1

    def test_from_dict_roundtrip_minimal(self):
        step = self._make_step()
        restored = Step.from_dict(step.to_dict())
        assert restored == step

    def test_from_dict_roundtrip_full(self):
        loc = Locator(type=LocatorType.XPATH, value="//btn")
        step = Step(
            id="s2",
            title="Full step",
            action=ActionSpec(type=ActionType.INPUT, locator=loc, params={"text": "hi"}),
            before_wait=WaitSpec(type=WaitConditionType.VISIBLE, locator=loc, timeout=5.0),
            after_wait=WaitSpec(type=WaitConditionType.TEXT_CONTAINS, text="hi"),
            assertions=[
                AssertionSpec(type=AssertionType.TEXT_EQUALS, locator=loc, expected="hi"),
                AssertionSpec(type=AssertionType.OCR_CONTAINS, expected="hi"),
            ],
        )
        restored = Step.from_dict(step.to_dict())
        assert restored.id == step.id
        assert restored.title == step.title
        assert restored.action == step.action
        assert restored.before_wait == step.before_wait
        assert restored.after_wait == step.after_wait
        assert restored.assertions == step.assertions
