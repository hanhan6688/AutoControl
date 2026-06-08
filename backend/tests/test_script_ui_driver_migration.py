"""Tests for ScriptUI driver delegation migration."""
from unittest.mock import MagicMock, patch

from app.routers.scripts import ScriptUI


class TestScriptUIDriverDelegation:
    @patch("app.routers.scripts.AndroidDriver")
    def test_android_uses_driver(self, mock_driver_cls):
        mock_driver = MagicMock()
        mock_driver_cls.return_value = mock_driver
        ui = ScriptUI(udid="emulator-5554", platform="android")
        ui.click(100, 200)
        mock_driver.tap.assert_called_once_with(100, 200)

    @patch("app.routers.scripts.IOSDriver")
    def test_ios_uses_driver(self, mock_driver_cls):
        mock_driver = MagicMock()
        mock_driver_cls.return_value = mock_driver
        ui = ScriptUI(udid="abc123", platform="ios", wda_url="http://localhost:8100")
        ui.click(100, 200)
        mock_driver.tap.assert_called_once_with(100, 200)


class TestScriptUIParseSelector:
    def test_parse_resource_id(self):
        ui = ScriptUI(udid="emulator-5554")
        lt, lv = ui._parse_selector(resource_id="com.demo:id/btn")
        assert lt == "resource_id"
        assert lv == "com.demo:id/btn"

    def test_parse_text(self):
        ui = ScriptUI(udid="emulator-5554")
        lt, lv = ui._parse_selector(text="login")
        assert lt == "text"
        assert lv == "login"

    def test_parse_none(self):
        ui = ScriptUI(udid="emulator-5554")
        lt, lv = ui._parse_selector()
        assert lt is None
        assert lv is None


class TestScriptUIAssertionAliases:
    def test_assert_element_exists_delegates_to_assert_element(self):
        ui = ScriptUI(udid="emulator-5554")
        ui.assert_element = MagicMock(return_value={"found": True})

        result = ui.assert_element_exists(resource_id="com.demo:id/login")

        assert result == {"found": True}
        ui.assert_element.assert_called_once_with(
            text=None,
            resource_id="com.demo:id/login",
            content_desc=None,
            class_name=None,
            package=None,
            xpath=None,
            timeout=5.0,
        )

    @patch("app.routers.scripts.AndroidDriver")
    def test_assert_app_foreground_uses_driver_current_app(self, mock_driver_cls):
        mock_driver = MagicMock()
        mock_driver.current_app.return_value = {"package": "com.demo.app"}
        mock_driver_cls.return_value = mock_driver
        ui = ScriptUI(udid="emulator-5554", platform="android")

        result = ui.assert_app_foreground("com.demo.app", timeout=0.1)

        assert result["found"] is True
        assert result["current_app"] == "com.demo.app"
        mock_driver.current_app.assert_called()
