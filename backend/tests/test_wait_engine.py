from unittest.mock import MagicMock

from app.automation.core.driver import DeviceDriver, ElementRef
from app.automation.core.models import Locator, LocatorType, WaitConditionType, WaitSpec
from app.automation.waits.engine import WaitEngine, WaitResult


class TestWaitEngineVisible:
    def test_element_visible_immediately(self):
        driver = MagicMock(spec=DeviceDriver)
        driver.find_element.return_value = ElementRef(
            found=True,
            locator_type="resource_id",
            locator_value="com.demo:id/btn",
        )
        spec = WaitSpec(
            type=WaitConditionType.VISIBLE,
            locator=Locator(type=LocatorType.RESOURCE_ID, value="com.demo:id/btn"),
            timeout=5.0,
        )
        result = WaitEngine(driver).wait(spec)
        assert result.met is True

    def test_element_not_visible_timeout(self):
        driver = MagicMock(spec=DeviceDriver)
        driver.find_element.return_value = ElementRef(
            found=False, locator_type="resource_id", locator_value="missing"
        )
        spec = WaitSpec(
            type=WaitConditionType.VISIBLE,
            locator=Locator(type=LocatorType.RESOURCE_ID, value="missing"),
            timeout=0.1,
            poll_interval=0.03,
        )
        result = WaitEngine(driver).wait(spec)
        assert result.met is False


class TestWaitEngineExists:
    def test_element_exists(self):
        driver = MagicMock(spec=DeviceDriver)
        driver.find_element.return_value = ElementRef(
            found=True, locator_type="text", locator_value="OK"
        )
        spec = WaitSpec(
            type=WaitConditionType.EXISTS,
            locator=Locator(type=LocatorType.TEXT, value="OK"),
            timeout=5.0,
        )
        result = WaitEngine(driver).wait(spec)
        assert result.met is True


class TestWaitEngineGone:
    def test_element_gone(self):
        driver = MagicMock(spec=DeviceDriver)
        driver.find_element.return_value = ElementRef(
            found=False, locator_type="resource_id", locator_value="loading"
        )
        spec = WaitSpec(
            type=WaitConditionType.GONE,
            locator=Locator(type=LocatorType.RESOURCE_ID, value="loading"),
            timeout=5.0,
        )
        result = WaitEngine(driver).wait(spec)
        assert result.met is True

    def test_element_still_present_not_gone(self):
        driver = MagicMock(spec=DeviceDriver)
        driver.find_element.return_value = ElementRef(
            found=True, locator_type="resource_id", locator_value="loading"
        )
        spec = WaitSpec(
            type=WaitConditionType.GONE,
            locator=Locator(type=LocatorType.RESOURCE_ID, value="loading"),
            timeout=0.1,
            poll_interval=0.03,
        )
        result = WaitEngine(driver).wait(spec)
        assert result.met is False


class TestWaitEngineAppForeground:
    def test_app_foreground_matches(self):
        driver = MagicMock(spec=DeviceDriver)
        driver.current_app.return_value = {"package": "com.demo.app"}
        spec = WaitSpec(type=WaitConditionType.APP_FOREGROUND, timeout=5.0)
        result = WaitEngine(driver).wait(spec, expected_app="com.demo.app")
        assert result.met is True

    def test_app_foreground_mismatch(self):
        driver = MagicMock(spec=DeviceDriver)
        driver.current_app.return_value = {"package": "com.other.app"}
        spec = WaitSpec(
            type=WaitConditionType.APP_FOREGROUND, timeout=0.1, poll_interval=0.03
        )
        result = WaitEngine(driver).wait(spec, expected_app="com.demo.app")
        assert result.met is False


class TestWaitEngineScreenChanged:
    def test_screen_changes(self):
        driver = MagicMock(spec=DeviceDriver)
        driver.screenshot.side_effect = [b"screen1", b"screen2"]
        spec = WaitSpec(
            type=WaitConditionType.SCREEN_CHANGED, timeout=5.0, poll_interval=0.01
        )
        result = WaitEngine(driver).wait(spec)
        assert result.met is True


class TestWaitResult:
    def test_wait_result_fields(self):
        result = WaitResult(met=True, elapsed_ms=42, condition=WaitConditionType.VISIBLE)
        assert result.met is True
        assert result.elapsed_ms == 42
