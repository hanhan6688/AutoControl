"""Contract tests for the DeviceDriver protocol and ElementRef dataclass."""

from __future__ import annotations

import pytest

from app.automation.core.driver import DeviceDriver, ElementRef


# ---------------------------------------------------------------------------
# ElementRef tests
# ---------------------------------------------------------------------------


class TestElementRef:
    def test_frozen_dataclass(self):
        ref = ElementRef(found=True, locator_type="resource_id", locator_value="com.example:id/btn")
        with pytest.raises(AttributeError):
            ref.found = False  # type: ignore[misc]

    def test_required_fields(self):
        ref = ElementRef(found=True, locator_type="text", locator_value="Login")
        assert ref.found is True
        assert ref.locator_type == "text"
        assert ref.locator_value == "Login"

    def test_optional_fields_default_none(self):
        ref = ElementRef(found=False, locator_type="xpath", locator_value="//node")
        assert ref.bounds is None
        assert ref.center is None
        assert ref.text is None
        assert ref.resource_id is None
        assert ref.class_name is None
        assert ref.content_desc is None
        assert ref.attributes is None

    def test_optional_fields_with_values(self):
        ref = ElementRef(
            found=True,
            locator_type="resource_id",
            locator_value="com.example:id/btn",
            bounds={"left": 0, "top": 100, "right": 200, "bottom": 200},
            center=(100, 150),
            text="Submit",
            resource_id="com.example:id/btn",
            class_name="android.widget.Button",
            content_desc="Submit button",
            attributes={"clickable": "true", "enabled": "true"},
        )
        assert ref.bounds == {"left": 0, "top": 100, "right": 200, "bottom": 200}
        assert ref.center == (100, 150)
        assert ref.text == "Submit"
        assert ref.attributes == {"clickable": "true", "enabled": "true"}


# ---------------------------------------------------------------------------
# DeviceDriver protocol tests
# ---------------------------------------------------------------------------


class TestDeviceDriverProtocol:
    def test_protocol_defines_required_methods(self):
        required = [
            "platform", "launch", "stop_app", "tap", "long_press", "swipe",
            "input_text", "press_key", "screenshot", "dump_source",
            "current_app", "screen_size", "find_element", "element_exists",
        ]
        for name in required:
            assert hasattr(DeviceDriver, name), f"DeviceDriver missing: {name}"

    def test_cannot_instantiate_protocol_directly(self):
        with pytest.raises(TypeError):
            DeviceDriver(udid="test", platform="android")  # type: ignore[abstract]

    def test_concrete_subclass_must_implement_all(self):
        """A partial implementation still cannot be instantiated."""

        class PartialDriver(DeviceDriver):
            @property
            def platform(self) -> str:
                return "android"

            def launch(self, app_id: str) -> None:
                pass

        with pytest.raises(TypeError):
            PartialDriver()  # type: ignore[abstract]

    def test_full_concrete_subclass_can_instantiate(self):
        """A complete implementation can be instantiated and used."""

        class StubDriver(DeviceDriver):
            def __init__(self, udid: str) -> None:
                self._udid = udid

            @property
            def platform(self) -> str:
                return "android"

            def launch(self, app_id: str) -> None:
                pass

            def stop_app(self, app_id: str) -> None:
                pass

            def tap(self, x: int, y: int) -> None:
                pass

            def long_press(self, x: int, y: int, duration_ms: int = 1000) -> None:
                pass

            def swipe(self, sx: int, sy: int, ex: int, ey: int, duration_ms: int = 300) -> None:
                pass

            def input_text(self, text: str) -> None:
                pass

            def press_key(self, key: str) -> None:
                pass

            def screenshot(self) -> bytes:
                return b""

            def dump_source(self) -> str:
                return ""

            def current_app(self) -> dict[str, str]:
                return {}

            def screen_size(self) -> tuple[int, int]:
                return (1080, 1920)

            def find_element(self, locator_type: str, locator_value: str, timeout: float = 10.0) -> ElementRef:
                return ElementRef(found=False, locator_type=locator_type, locator_value=locator_value)

            def element_exists(self, locator_type: str, locator_value: str, timeout: float = 5.0) -> bool:
                return False

        driver = StubDriver(udid="emulator-5554")
        assert driver.platform == "android"
        assert driver.screen_size() == (1080, 1920)
        ref = driver.find_element("resource_id", "btn")
        assert ref.found is False
