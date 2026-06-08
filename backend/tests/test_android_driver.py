"""Tests for AndroidDriver — u2-first, ADB-fallback strategy."""

from unittest.mock import MagicMock, patch

from app.automation.core.driver import DeviceDriver, ElementRef
from app.automation.drivers.android_driver import AndroidDriver


# ── Init ──────────────────────────────────────────────────────────────────


class TestAndroidDriverInit:
    def test_platform_is_android(self):
        driver = AndroidDriver(udid="emulator-5554")
        assert driver.platform == "android"

    def test_udid_stored(self):
        driver = AndroidDriver(udid="emulator-5554")
        assert driver.udid == "emulator-5554"

    def test_implements_device_driver_protocol(self):
        assert issubclass(AndroidDriver, DeviceDriver)


# ── App lifecycle ─────────────────────────────────────────────────────────


class TestAndroidDriverLaunch:
    @patch("app.services.adb_service.ADBService")
    def test_launch_with_package_only(self, mock_adb_cls):
        mock_adb = MagicMock()
        mock_adb_cls.return_value = mock_adb
        driver = AndroidDriver(udid="emulator-5554")
        driver.launch("com.demo.app")
        mock_adb.shell.assert_called_once_with(
            "emulator-5554", "am start -n com.demo.app/.MainActivity"
        )

    @patch("app.services.adb_service.ADBService")
    def test_launch_with_activity(self, mock_adb_cls):
        mock_adb = MagicMock()
        mock_adb_cls.return_value = mock_adb
        driver = AndroidDriver(udid="emulator-5554")
        driver.launch("com.demo.app/com.demo.app.LoginActivity")
        mock_adb.shell.assert_called_once_with(
            "emulator-5554",
            "am start -n com.demo.app/com.demo.app.LoginActivity",
        )


class TestAndroidDriverStopApp:
    @patch("app.services.adb_service.ADBService")
    def test_stop_app(self, mock_adb_cls):
        mock_adb = MagicMock()
        mock_adb_cls.return_value = mock_adb
        driver = AndroidDriver(udid="emulator-5554")
        driver.stop_app("com.demo.app")
        mock_adb.shell.assert_called_once_with(
            "emulator-5554", "am force-stop com.demo.app"
        )


# ── Touch / gesture ───────────────────────────────────────────────────────


class TestAndroidDriverTap:
    @patch("app.services.u2_service.click")
    @patch("app.services.adb_service.ADBService")
    def test_tap_delegates_to_u2(self, mock_adb_cls, mock_click):
        mock_adb = MagicMock()
        mock_adb_cls.return_value = mock_adb
        driver = AndroidDriver(udid="emulator-5554")
        driver.tap(100, 200)
        mock_click.assert_called_once_with("emulator-5554", 100, 200)
        mock_adb.shell.assert_not_called()

    @patch("app.services.u2_service.click")
    @patch("app.services.adb_service.ADBService")
    def test_tap_fallback_when_u2_raises(self, mock_adb_cls, mock_click):
        mock_click.side_effect = RuntimeError("u2 failed")
        mock_adb = MagicMock()
        mock_adb_cls.return_value = mock_adb
        driver = AndroidDriver(udid="emulator-5554")
        driver.tap(100, 200)
        mock_click.assert_called_once_with("emulator-5554", 100, 200)
        mock_adb.shell.assert_called_once_with(
            "emulator-5554", "input tap 100 200"
        )


class TestAndroidDriverLongPress:
    @patch("app.services.adb_service.ADBService")
    def test_long_press(self, mock_adb_cls):
        mock_adb = MagicMock()
        mock_adb_cls.return_value = mock_adb
        driver = AndroidDriver(udid="emulator-5554")
        driver.long_press(100, 200, duration_ms=1500)
        mock_adb.shell.assert_called_once_with(
            "emulator-5554", "input swipe 100 200 100 200 1500"
        )

    @patch("app.services.adb_service.ADBService")
    def test_long_press_default_duration(self, mock_adb_cls):
        mock_adb = MagicMock()
        mock_adb_cls.return_value = mock_adb
        driver = AndroidDriver(udid="emulator-5554")
        driver.long_press(100, 200)
        mock_adb.shell.assert_called_once_with(
            "emulator-5554", "input swipe 100 200 100 200 1000"
        )


class TestAndroidDriverSwipe:
    @patch("app.services.u2_service.swipe")
    @patch("app.services.adb_service.ADBService")
    def test_swipe_delegates_to_u2(self, mock_adb_cls, mock_swipe):
        mock_adb = MagicMock()
        mock_adb_cls.return_value = mock_adb
        driver = AndroidDriver(udid="emulator-5554")
        driver.swipe(100, 200, 300, 400, duration_ms=500)
        mock_swipe.assert_called_once_with(
            "emulator-5554", 100, 200, 300, 400, duration=0.5
        )
        mock_adb.shell.assert_not_called()

    @patch("app.services.u2_service.swipe")
    @patch("app.services.adb_service.ADBService")
    def test_swipe_fallback_when_u2_raises(self, mock_adb_cls, mock_swipe):
        mock_swipe.side_effect = RuntimeError("u2 failed")
        mock_adb = MagicMock()
        mock_adb_cls.return_value = mock_adb
        driver = AndroidDriver(udid="emulator-5554")
        driver.swipe(100, 200, 300, 400, duration_ms=500)
        mock_swipe.assert_called_once_with(
            "emulator-5554", 100, 200, 300, 400, duration=0.5
        )
        mock_adb.shell.assert_called_once_with(
            "emulator-5554", "input swipe 100 200 300 400 500"
        )

    @patch("app.services.u2_service.swipe")
    @patch("app.services.adb_service.ADBService")
    def test_swipe_default_duration(self, mock_adb_cls, mock_swipe):
        mock_adb = MagicMock()
        mock_adb_cls.return_value = mock_adb
        driver = AndroidDriver(udid="emulator-5554")
        driver.swipe(0, 0, 100, 100)
        mock_swipe.assert_called_once_with(
            "emulator-5554", 0, 0, 100, 100, duration=0.3
        )


# ── Input ─────────────────────────────────────────────────────────────────


class TestAndroidDriverInputText:
    @patch("app.services.adb_service.ADBService")
    def test_input_text_delegates_to_adb(self, mock_adb_cls):
        mock_adb = MagicMock()
        mock_adb_cls.return_value = mock_adb
        driver = AndroidDriver(udid="emulator-5554")
        driver.input_text("hello world")
        mock_adb.input_text.assert_called_once_with(
            "emulator-5554", "hello world"
        )


class TestAndroidDriverPressKey:
    @patch("app.services.adb_service.ADBService")
    def test_press_key_back(self, mock_adb_cls):
        mock_adb = MagicMock()
        mock_adb_cls.return_value = mock_adb
        driver = AndroidDriver(udid="emulator-5554")
        driver.press_key("back")
        mock_adb.shell.assert_called_once_with(
            "emulator-5554", "input keyevent 4"
        )

    @patch("app.services.adb_service.ADBService")
    def test_press_key_home(self, mock_adb_cls):
        mock_adb = MagicMock()
        mock_adb_cls.return_value = mock_adb
        driver = AndroidDriver(udid="emulator-5554")
        driver.press_key("home")
        mock_adb.shell.assert_called_once_with(
            "emulator-5554", "input keyevent 3"
        )

    @patch("app.services.adb_service.ADBService")
    def test_press_key_enter(self, mock_adb_cls):
        mock_adb = MagicMock()
        mock_adb_cls.return_value = mock_adb
        driver = AndroidDriver(udid="emulator-5554")
        driver.press_key("enter")
        mock_adb.shell.assert_called_once_with(
            "emulator-5554", "input keyevent 66"
        )

    @patch("app.services.adb_service.ADBService")
    def test_press_key_is_case_insensitive(self, mock_adb_cls):
        mock_adb = MagicMock()
        mock_adb_cls.return_value = mock_adb
        driver = AndroidDriver(udid="emulator-5554")
        driver.press_key("HOME")
        mock_adb.shell.assert_called_once_with(
            "emulator-5554", "input keyevent 3"
        )

    @patch("app.services.adb_service.ADBService")
    def test_press_key_unknown_passed_through(self, mock_adb_cls):
        mock_adb = MagicMock()
        mock_adb_cls.return_value = mock_adb
        driver = AndroidDriver(udid="emulator-5554")
        driver.press_key("42")
        mock_adb.shell.assert_called_once_with(
            "emulator-5554", "input keyevent 42"
        )


# ── Screen / hierarchy ────────────────────────────────────────────────────


class TestAndroidDriverScreenshot:
    @patch("app.services.u2_service.screenshot")
    @patch("app.services.adb_service.ADBService")
    def test_screenshot_u2(self, mock_adb_cls, mock_screenshot):
        mock_screenshot.return_value = b"png_data"
        mock_adb = MagicMock()
        mock_adb_cls.return_value = mock_adb
        driver = AndroidDriver(udid="emulator-5554")
        result = driver.screenshot()
        assert result == b"png_data"
        mock_adb.capture_screen_png.assert_not_called()

    @patch("app.services.u2_service.screenshot")
    @patch("app.services.adb_service.ADBService")
    def test_screenshot_fallback_when_u2_raises(self, mock_adb_cls, mock_screenshot):
        mock_screenshot.side_effect = RuntimeError("u2 failed")
        mock_adb = MagicMock()
        mock_adb.capture_screen_png.return_value = b"adb_png"
        mock_adb_cls.return_value = mock_adb
        driver = AndroidDriver(udid="emulator-5554")
        result = driver.screenshot()
        assert result == b"adb_png"
        mock_screenshot.assert_called_once_with("emulator-5554")
        mock_adb.capture_screen_png.assert_called_once_with("emulator-5554")


class TestAndroidDriverDumpSource:
    @patch("app.services.u2_service.dump_hierarchy")
    @patch("app.services.adb_service.ADBService")
    def test_dump_source_u2(self, mock_adb_cls, mock_dump):
        mock_dump.return_value = "<hierarchy><node /></hierarchy>"
        mock_adb = MagicMock()
        mock_adb_cls.return_value = mock_adb
        driver = AndroidDriver(udid="emulator-5554")
        result = driver.dump_source()
        assert result == "<hierarchy><node /></hierarchy>"
        mock_adb.dump_ui_hierarchy.assert_not_called()

    @patch("app.services.u2_service.dump_hierarchy")
    @patch("app.services.adb_service.ADBService")
    def test_dump_source_fallback_when_u2_raises(self, mock_adb_cls, mock_dump):
        mock_dump.side_effect = RuntimeError("u2 failed")
        mock_adb = MagicMock()
        mock_adb.dump_ui_hierarchy.return_value = "<hierarchy><adb /></hierarchy>"
        mock_adb_cls.return_value = mock_adb
        driver = AndroidDriver(udid="emulator-5554")
        result = driver.dump_source()
        assert result == "<hierarchy><adb /></hierarchy>"
        mock_dump.assert_called_once_with("emulator-5554")
        mock_adb.dump_ui_hierarchy.assert_called_once_with("emulator-5554")


# ── Device info ───────────────────────────────────────────────────────────


class TestAndroidDriverCurrentApp:
    @patch("app.services.adb_service.ADBService")
    def test_returns_package_and_activity(self, mock_adb_cls):
        mock_adb = MagicMock()
        mock_adb_cls.return_value = mock_adb
        mock_result = MagicMock()
        mock_result.stdout = (
            "  mResumedActivity: ActivityRecord{xxx u0 "
            "com.demo.app/com.demo.app.MainActivity t54}"
        )
        mock_adb.shell.return_value = mock_result
        driver = AndroidDriver(udid="emulator-5554")
        result = driver.current_app()
        assert result == {
            "package": "com.demo.app",
            "activity": "com.demo.app.MainActivity",
        }

    @patch("app.services.adb_service.ADBService")
    def test_returns_empty_when_no_match(self, mock_adb_cls):
        mock_adb = MagicMock()
        mock_adb_cls.return_value = mock_adb
        mock_result = MagicMock()
        mock_result.stdout = "No activities found"
        mock_adb.shell.return_value = mock_result
        driver = AndroidDriver(udid="emulator-5554")
        result = driver.current_app()
        assert result == {"package": "", "activity": ""}


class TestAndroidDriverScreenSize:
    @patch("app.services.adb_service.ADBService")
    def test_delegates_to_adb(self, mock_adb_cls):
        mock_adb = MagicMock()
        mock_adb_cls.return_value = mock_adb
        mock_adb.get_screen_size.return_value = (1080, 1920)
        driver = AndroidDriver(udid="emulator-5554")
        result = driver.screen_size()
        assert result == (1080, 1920)
        mock_adb.get_screen_size.assert_called_once_with("emulator-5554")


# ── Element search ────────────────────────────────────────────────────────


class TestAndroidDriverFindElement:
    @patch("app.services.u2_service.exists_selector")
    @patch("app.services.adb_service.ADBService")
    def test_find_element_found(self, mock_adb_cls, mock_exists):
        mock_exists.return_value = True
        mock_adb = MagicMock()
        mock_adb_cls.return_value = mock_adb
        driver = AndroidDriver(udid="emulator-5554")
        result = driver.find_element("text", "Login", timeout=10.0)
        mock_exists.assert_called_once_with(
            "emulator-5554", text="Login", timeout=10.0
        )
        assert isinstance(result, ElementRef)
        assert result.found is True
        assert result.locator_type == "text"
        assert result.locator_value == "Login"

    @patch("app.services.u2_service.exists_selector")
    @patch("app.services.adb_service.ADBService")
    def test_find_element_not_found(self, mock_adb_cls, mock_exists):
        mock_exists.return_value = False
        mock_adb = MagicMock()
        mock_adb_cls.return_value = mock_adb
        driver = AndroidDriver(udid="emulator-5554")
        result = driver.find_element("resource_id", "btn_login", timeout=5.0)
        mock_exists.assert_called_once_with(
            "emulator-5554", resource_id="btn_login", timeout=5.0
        )
        assert isinstance(result, ElementRef)
        assert result.found is False
        assert result.locator_type == "resource_id"
        assert result.locator_value == "btn_login"


class TestAndroidDriverElementExists:
    @patch("app.services.u2_service.exists_selector")
    @patch("app.services.adb_service.ADBService")
    def test_element_exists_found(self, mock_adb_cls, mock_exists):
        mock_exists.return_value = True
        mock_adb = MagicMock()
        mock_adb_cls.return_value = mock_adb
        driver = AndroidDriver(udid="emulator-5554")
        assert driver.element_exists("text", "Login") is True
        mock_exists.assert_called_once_with(
            "emulator-5554", text="Login", timeout=5.0
        )

    @patch("app.services.u2_service.exists_selector")
    @patch("app.services.adb_service.ADBService")
    def test_element_exists_not_found(self, mock_adb_cls, mock_exists):
        mock_exists.return_value = False
        mock_adb = MagicMock()
        mock_adb_cls.return_value = mock_adb
        driver = AndroidDriver(udid="emulator-5554")
        assert driver.element_exists("text", "Login") is False
        mock_exists.assert_called_once_with(
            "emulator-5554", text="Login", timeout=5.0
        )
